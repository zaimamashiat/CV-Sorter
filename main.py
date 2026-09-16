"""
CV Screening Pipeline - FastAPI Version v3.0
Run: uvicorn main:app --reload --port 8000 --host 0.0.0.0

Changes in v3.0:
  - Integrated RMFL (Reinforcement-based Multi-criteria Feature Learning)
    No manual weights; Dirichlet policy network learns optimal criterion
    weights per job-role context from hiring outcome feedback
  - 9 structured scoring criteria fully integrated into /rank-cvs
  - New endpoints: POST /feedback, GET /rmfl-weights
  - Portfolio skill extraction uses Groq/LLaMA (unchanged from v2.2)
  - NER model still used for CV text skill extraction only (unchanged)
"""

import os
import re
import time
import json
import io
import zipfile
import tempfile
from typing import List, Optional, Dict, Any, Tuple

# ──────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

OCR_OUTPUT_FOLDER           = os.path.join(BASE_DIR, "ocr_output")
EXCEL_OUTPUT_PATH           = os.path.join(BASE_DIR, "resume_summary.xlsx")
LDA_MODEL_PATH              = os.path.join(BASE_DIR, "models", "lda_model")
EMBED_DATA_PATH             = os.path.join(BASE_DIR, "models", "id2word.pkl")
EMBED_TFIDF_PATH            = os.path.join(BASE_DIR, "models", "tfidf_model.pkl")
PROCESSED_BIGRAM_DATA_PATH  = os.path.join(BASE_DIR, "models", "bigram_mod.pkl")
PROCESSED_TRIGRAM_DATA_PATH = os.path.join(BASE_DIR, "models", "trigram_mod.pkl")
K_MEANS_MODEL_PATH          = os.path.join(BASE_DIR, "models", "kmeans_model.pkl")
DESIGNATION_MODEL_PATH      = os.path.join(BASE_DIR, "models", "designation_model")
EXPERIENCE_MODEL_PATH       = os.path.join(BASE_DIR, "models", "experience_model")
RMFL_CHECKPOINT             = os.path.join(BASE_DIR, "models", "rmfl_weights.pt")

NER_MODEL_PATH = os.getenv("NER_MODEL_PATH", r"C:\PROJECTS\models\ner")

os.makedirs(OCR_OUTPUT_FOLDER, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "models"), exist_ok=True)

# ──────────────────────────────────────────────
# IMPORTS
# ──────────────────────────────────────────────
import pdfplumber
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions import Categorical, Dirichlet
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer, util
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from rapidfuzz import fuzz
from groq import Groq
import spacy
import numpy as np
import pickle
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize
from gensim import models as gensim_models
from gensim.utils import simple_preprocess
from gensim.matutils import sparse2full
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.probability import FreqDist
from dateutil import parser as date_parser
from datetime import datetime
from dateutil.relativedelta import relativedelta
from collections import defaultdict
import docx2txt

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
MAX_CHARS_JD  = 4000
MAX_CHARS_CV  = 2000
MAX_CHARS_WEB = 3000
GITHUB_API    = "https://api.github.com"

SEMANTIC_WEIGHT = 0.7
TECH_WEIGHT     = 0.3

CATEGORIES = [
    "Data Science",
    "Python Developer", "Web Developer", "Database", "DotNet Developer",
    "Automation Testing", "Machine Learning Engineer", "DevOps Engineer",
    "Mobile Developer", "Cloud Engineer",
]

JD_TECH_FIELDS = [
    "Technology", "Skills", "Technical Skills", "tech_skills",
    "technologies", "Technical_Skills", "Required_Skills"
]

TECH_SKILLS_COLUMN_OPTIONS = [
    "Technical Skills (??????????? ??????)\ne.g. Figma, .NET etc.",
    "Technical Skills", "tech_skills", "skills"
]

PORTFOLIO_COLUMN_OPTIONS = [
    "Portfolio Link", "portfolio link", "Portfolio", "portfolio",
    "Portfolio URL", "Website", "GitHub", "Github", "LinkedIn", "link", "url"
]

ALLOWED_ORIGINS = [
    "http://localhost:3000", "http://localhost:5173",
    "http://localhost:8080", "http://localhost:4200",
    "http://127.0.0.1:3000", "http://127.0.0.1:5173",
    "http://127.0.0.1:8080", "http://127.0.0.1:4200",
]

# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────
app = FastAPI(
    title="CV Screening API",
    description="AI-powered CV screening with RMFL learned criterion weights",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

# ══════════════════════════════════════════════
# SBERT
# ══════════════════════════════════════════════
SBERT_MODEL_ID = os.getenv(
    "SBERT_MODEL_ID",
    "sentence-transformers/all-mpnet-base-v2",
)
# Download the public model from Hugging Face on first use, then reuse its
# normal cache. This avoids a dependency on a machine-specific local path.
sbert_model    = SentenceTransformer(SBERT_MODEL_ID)
_sbert_out_dim = sbert_model.get_sentence_embedding_dimension()
_sbert_reducer = nn.Linear(_sbert_out_dim, 384) if _sbert_out_dim != 384 else nn.Identity()
_sbert_reducer.eval()

def _sbert_embed(text: str) -> torch.Tensor:
    raw = sbert_model.encode(text[:512], convert_to_tensor=True)
    with torch.no_grad():
        reduced = _sbert_reducer(raw.unsqueeze(0))
    return reduced.squeeze(0)


# ══════════════════════════════════════════════════════════════════════════════
# RMFL — Reinforcement-based Multi-criteria Feature Learning
# Learns optimal criterion weights via a Dirichlet policy network.
# No manual weights anywhere — the agent discovers them from hiring feedback.
# ══════════════════════════════════════════════════════════════════════════════

CRITERIA_KEYS = [
    "relevant_background",
    "results_achievements",
    "relevant_courses",
    "training_certification",
    "relevant_skills",
    "work_experience",
    "projects_coursework",
    "thesis_publications",
    "portfolio",
]
N_CRITERIA    = len(CRITERIA_KEYS)   # 9
N_ROLE_DIM    = 64
HIDDEN_DIM    = 128
RMFL_LR       = 3e-4
ENTROPY_COEFF = 0.05    # keeps exploration alive
WEIGHT_FLOOR  = 0.02    # no criterion ever fully zeroed out


class RoleEncoder(nn.Module):
    """
    Encodes JD title + skills into a 64-dim vector via EmbeddingBag over a
    fixed role-signal vocabulary.  Allows the policy to emit DIFFERENT weight
    distributions for different job types (DevOps vs Research vs Web Dev).
    """
    ROLE_VOCAB = [
        "data", "science", "machine", "learning", "engineer", "developer",
        "devops", "cloud", "mobile", "web", "backend", "frontend", "fullstack",
        "security", "research", "analyst", "product", "manager", "architect",
        "junior", "senior", "lead", "principal", "intern", "associate",
        "published", "thesis", "phd", "research",
        "aws", "azure", "gcp", "kubernetes", "terraform",
        "react", "vue", "angular", "node",
        "spark", "kafka", "airflow", "etl",
        "pytorch", "tensorflow", "transformers",
    ]

    def __init__(self, out_dim: int = N_ROLE_DIM):
        super().__init__()
        self.vocab = {w: i for i, w in enumerate(self.ROLE_VOCAB)}
        self.embed = nn.EmbeddingBag(
            len(self.ROLE_VOCAB) + 1, out_dim,
            mode="mean", padding_idx=len(self.ROLE_VOCAB)
        )
        self.out_dim = out_dim

    def forward(self, role_text: str) -> torch.Tensor:
        tokens  = role_text.lower().split()
        indices = [self.vocab[t] for t in tokens if t in self.vocab]
        if not indices:
            indices = [len(self.ROLE_VOCAB) - 1]
        return self.embed(torch.tensor([indices], dtype=torch.long)).squeeze(0)


class CriteriaWeightPolicy(nn.Module):
    """
    Input  : role_emb (64-dim) + normalised criteria scores (9-dim)
    Output : Dirichlet concentration params alpha (9-dim)

    Dirichlet is used instead of Softmax because weights are continuous and
    must sum to 1.  Higher alpha_i => criterion i gets more weight on average.
    """
    def __init__(self, role_dim=N_ROLE_DIM, n_criteria=N_CRITERIA, hidden_dim=HIDDEN_DIM):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(role_dim + n_criteria, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, n_criteria),
            nn.Softplus(),   # alpha must be > 0
        )
        nn.init.constant_(self.net[-2].bias, 0.54)  # near-uniform init

    def forward(self, role_emb: torch.Tensor, scores: torch.Tensor) -> Dirichlet:
        x      = torch.cat([role_emb, scores], dim=-1)
        alphas = self.net(x) + 1e-3
        return Dirichlet(alphas)


class ReplayBuffer:
    """Circular buffer storing (role_text, scores, weights, reward) experiences."""
    def __init__(self, capacity: int = 500):
        self.capacity = capacity
        self.buffer: List[dict] = []

    def push(self, role_text: str, scores: List[float],
             weights: List[float], reward: float):
        self.buffer.append({"role_text": role_text, "scores": scores,
                             "weights": weights, "reward": reward})
        if len(self.buffer) > self.capacity:
            self.buffer.pop(0)

    def sample(self, batch_size: int) -> List[dict]:
        idx = np.random.choice(len(self.buffer),
                               min(batch_size, len(self.buffer)), replace=False)
        return [self.buffer[i] for i in idx]

    def __len__(self):
        return len(self.buffer)


def shape_reward(
    outcome:               Optional[str] = None,
    human_rank:            Optional[int] = None,
    system_rank:           Optional[int] = None,
    total_candidates:      int           = 1,
    weighted_score:        float         = 0.0,
    rank_mismatch_penalty: float         = 0.1,
) -> float:
    """
    Converts any combination of hiring feedback signals into a scalar in [-1,+1].
    Falls back to a weak score-confidence signal when no external feedback exists.
    """
    reward, signals_used = 0.0, 0

    if outcome:
        outcome_map = {"hired": +1.0, "shortlisted": +0.5,
                       "screened_out": -0.3, "rejected": -1.0}
        if outcome in outcome_map:
            reward       += outcome_map[outcome]
            signals_used += 1

    if human_rank is not None and system_rank is not None and total_candidates > 1:
        rank_diff       = abs(human_rank - system_rank)
        normalised_diff = rank_diff / max(total_candidates - 1, 1)
        rank_signal     = 1.0 - 2.0 * normalised_diff
        reward         += rank_signal * (1 - rank_mismatch_penalty)
        signals_used   += 1

    if signals_used == 0:
        reward       = (weighted_score / 100.0) * 0.3
        signals_used = 1

    return float(np.clip(reward / signals_used, -1.0, +1.0))


class RMFLAgent:
    """
    Reinforcement-based Multi-criteria Feature Learner.

    Flow:
      1. get_weights(role_text, criteria_scores)  →  called inside /rank-cvs
      2. update(role_text, scores, weights, reward)  →  called inside /feedback
      3. save() / load()  →  checkpoint persistence
    """

    def __init__(self):
        self.role_encoder = RoleEncoder(out_dim=N_ROLE_DIM)
        self.policy       = CriteriaWeightPolicy(
            role_dim=N_ROLE_DIM, n_criteria=N_CRITERIA, hidden_dim=HIDDEN_DIM)
        self.optimizer    = optim.Adam(
            list(self.role_encoder.parameters()) +
            list(self.policy.parameters()), lr=RMFL_LR)
        self.replay       = ReplayBuffer(capacity=500)
        self.update_steps = 0

    def get_weights(
        self,
        role_text:       str,
        criteria_scores: Dict[str, float],
        deterministic:   bool = False,
    ) -> Tuple[Dict[str, float], torch.Tensor, float]:
        """
        Returns learned weight dict, log_prob tensor (for REINFORCE), and entropy.
        deterministic=True  → Dirichlet mean  (used for final scoring & audit)
        deterministic=False → sample           (used during training exploration)
        """
        self.role_encoder.eval()
        self.policy.eval()
        scores_vec = torch.tensor(
            [criteria_scores.get(k, 0.0) / 100.0 for k in CRITERIA_KEYS],
            dtype=torch.float32)
        with torch.no_grad():
            role_emb = self.role_encoder(role_text)
            dist     = self.policy(role_emb, scores_vec)
            raw_w    = (dist.concentration / dist.concentration.sum()
                        if deterministic else dist.sample())
            log_prob = dist.log_prob(raw_w + 1e-8)
            entropy  = dist.entropy().item()
        floored   = torch.clamp(raw_w, min=WEIGHT_FLOOR)
        weights_t = floored / floored.sum()
        weights   = {k: round(weights_t[i].item(), 4) for i, k in enumerate(CRITERIA_KEYS)}
        return weights, log_prob, entropy

    def update(self, role_text: str, criteria_scores: Dict[str, float],
               weights_used: Dict[str, float], reward: float, batch_size: int = 16):
        """Store experience then run a mini-batch REINFORCE + entropy-bonus update."""
        self.replay.push(
            role_text,
            [criteria_scores.get(k, 0.0) for k in CRITERIA_KEYS],
            [weights_used.get(k, 1 / N_CRITERIA) for k in CRITERIA_KEYS],
            reward,
        )
        if len(self.replay) < max(batch_size // 2, 4):
            return

        self.role_encoder.train()
        self.policy.train()

        batch   = self.replay.sample(batch_size)
        rewards = torch.tensor([e["reward"] for e in batch], dtype=torch.float32)
        if rewards.std() > 1e-6:
            rewards = (rewards - rewards.mean()) / (rewards.std() + 1e-8)

        total_loss = torch.tensor(0.0, requires_grad=True)
        for exp, norm_r in zip(batch, rewards):
            sv  = torch.tensor([s / 100.0 for s in exp["scores"]], dtype=torch.float32)
            wv  = torch.clamp(
                    torch.tensor(exp["weights"], dtype=torch.float32), min=1e-6)
            wv  = wv / wv.sum()
            dist = self.policy(self.role_encoder(exp["role_text"]), sv)
            loss = -(dist.log_prob(wv + 1e-8) * norm_r) - ENTROPY_COEFF * dist.entropy()
            total_loss = total_loss + loss

        self.optimizer.zero_grad()
        (total_loss / len(batch)).backward()
        nn.utils.clip_grad_norm_(
            list(self.role_encoder.parameters()) +
            list(self.policy.parameters()), max_norm=1.0)
        self.optimizer.step()
        self.update_steps += 1

    def save(self):
        os.makedirs(os.path.dirname(RMFL_CHECKPOINT), exist_ok=True)
        torch.save({
            "role_encoder": self.role_encoder.state_dict(),
            "policy":       self.policy.state_dict(),
            "optimizer":    self.optimizer.state_dict(),
            "update_steps": self.update_steps,
            "replay":       self.replay.buffer,
        }, RMFL_CHECKPOINT)
        print(f"RMFL saved → {RMFL_CHECKPOINT} (steps={self.update_steps})")

    def load(self):
        if not os.path.exists(RMFL_CHECKPOINT):
            print("RMFL: No checkpoint — starting from uniform weights")
            return
        ckpt = torch.load(RMFL_CHECKPOINT, map_location="cpu")
        self.role_encoder.load_state_dict(ckpt["role_encoder"])
        self.policy.load_state_dict(ckpt["policy"])
        self.optimizer.load_state_dict(ckpt["optimizer"])
        self.update_steps  = ckpt.get("update_steps", 0)
        self.replay.buffer = ckpt.get("replay", [])
        print(f"RMFL: Loaded (steps={self.update_steps}, replay={len(self.replay)})")

    def get_current_weights_for_role(self, role_text: str) -> dict:
        uniform = {k: 50.0 for k in CRITERIA_KEYS}
        weights, _, entropy = self.get_weights(role_text, uniform, deterministic=True)
        return {"weights": weights, "entropy": entropy, "update_steps": self.update_steps}


# Global RMFL agent — one instance for the entire app lifetime
rmfl_agent = RMFLAgent()


# ══════════════════════════════════════════════
# Model cache
# ══════════════════════════════════════════════
_models: Dict[str, Any] = {}

def get_models():
    global _models
    if _models:
        return _models
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY environment variable is not set")

    print("Loading BERT...")
    tokenizer = AutoTokenizer.from_pretrained("SwaKyxd/resume-analyser-bert")
    bert      = AutoModelForSequenceClassification.from_pretrained("SwaKyxd/resume-analyser-bert")
    bert.eval()

    print(f"Loading SBERT from: {SBERT_MODEL_ID} (dim={_sbert_out_dim})...")

    ner = None
    if os.path.exists(NER_MODEL_PATH):
        try:
            ner = spacy.load(NER_MODEL_PATH)
            print("NER model loaded ✓")
        except Exception as e:
            print(f"⚠️  NER model failed to load: {e}")
    else:
        print(f"⚠️  NER model not found: {NER_MODEL_PATH}")

    _models = {
        "tokenizer": tokenizer,
        "bert":      bert,
        "sbert":     sbert_model,
        "reducer":   _sbert_reducer,
        "groq":      Groq(api_key=GROQ_API_KEY),
        "ner":       ner,
    }

    rmfl_agent.load()   # always load RMFL checkpoint with other models
    print("All models + RMFL agent loaded ✓")
    return _models


# ══════════════════════════════════════════════
# Resume Policy (role/experience inference — unchanged from v2.2)
# ══════════════════════════════════════════════
class ResumePolicy(nn.Module):
    def __init__(self, input_dim=384, hidden_dim=128, num_actions=3):
        super().__init__()
        self.fc1     = nn.Linear(input_dim, hidden_dim)
        self.relu    = nn.ReLU()
        self.fc2     = nn.Linear(hidden_dim, num_actions)
        self.softmax = nn.Softmax(dim=-1)

    def forward(self, x):
        return self.softmax(self.fc2(self.relu(self.fc1(x))))

policy_model     = ResumePolicy(input_dim=384, hidden_dim=128, num_actions=3)
policy_optimizer = optim.Adam(policy_model.parameters(), lr=1e-4)
ACTIONS          = ["use_designation_model", "use_experience_model", "combine_both"]

def build_context_vector(designation_text, skills_text, experience_text):
    combined = f"{designation_text}. {skills_text}. {experience_text}"
    return _sbert_embed(combined).unsqueeze(0).requires_grad_(True)

def reinforce_update(optimizer, log_prob, reward):
    loss = -log_prob * reward
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()

def policy_guided_resume_analysis(designation_text, skills_text, experience_text,
                                   resume_text, training_mode=True):
    ctx    = build_context_vector(designation_text, skills_text, experience_text)
    probs  = policy_model(ctx)
    dist   = Categorical(probs)
    action = dist.sample()
    log_prob      = dist.log_prob(action)
    chosen_action = ACTIONS[action.item()]

    if chosen_action == "use_designation_model":
        label, conf = run_designation_model(resume_text); comp_cost = 1.0
    elif chosen_action == "use_experience_model":
        label, conf = run_experience_model(resume_text); comp_cost = 0.8
    else:
        d_label, d_conf = run_designation_model(resume_text)
        _,       e_conf = run_experience_model(resume_text)
        label = d_label; conf = (d_conf + e_conf) / 2; comp_cost = 1.5

    reward = conf - 0.1 * comp_cost
    if training_mode:
        reinforce_update(policy_optimizer, log_prob, reward)

    return {"action": chosen_action, "pred_label": label, "reward": float(reward),
            "accuracy": float(conf), "policy_probs": probs.detach().cpu().numpy().tolist()}


# ══════════════════════════════════════════════
# Designation / Experience models
# ══════════════════════════════════════════════
_designation_tokenizer = _designation_model = None
_experience_tokenizer  = _experience_model  = None

def _load_local_models():
    global _designation_tokenizer, _designation_model
    global _experience_tokenizer,  _experience_model
    if _designation_model is None and os.path.exists(DESIGNATION_MODEL_PATH):
        print("Loading designation model...")
        _designation_tokenizer = AutoTokenizer.from_pretrained(DESIGNATION_MODEL_PATH)
        _designation_model     = AutoModelForSequenceClassification.from_pretrained(DESIGNATION_MODEL_PATH)
        _designation_model.eval()
    if _experience_model is None and os.path.exists(EXPERIENCE_MODEL_PATH):
        print("Loading experience model...")
        _experience_tokenizer = AutoTokenizer.from_pretrained(EXPERIENCE_MODEL_PATH)
        _experience_model     = AutoModelForSequenceClassification.from_pretrained(EXPERIENCE_MODEL_PATH)
        _experience_model.eval()

def run_designation_model(resume_text: str):
    _load_local_models()
    if _designation_model is None:
        return _fallback_category(resume_text)
    inputs = _designation_tokenizer(resume_text, truncation=True, padding=True,
                                    max_length=512, return_tensors="pt")
    with torch.no_grad():
        logits = _designation_model(**inputs).logits
        probs  = torch.softmax(logits, dim=-1)[0]
    num_outputs = logits.shape[-1]
    if num_outputs >= len(CATEGORIES):
        pred  = torch.argmax(probs).item()
        label = CATEGORIES[pred % len(CATEGORIES)]
        score = probs[pred].item()
    else:
        pred       = torch.argmax(probs).item()
        score      = probs[pred].item()
        chunk_size = max(1, len(CATEGORIES) // num_outputs)
        start      = pred * chunk_size
        end        = start + chunk_size if pred < num_outputs - 1 else len(CATEGORIES)
        label      = _pick_best_category(resume_text, CATEGORIES[start:end])
    return label, round(0.3 + (score * 0.7), 4)

def _fallback_category(resume_text: str) -> tuple:
    return _pick_best_category(resume_text, CATEGORIES), 0.3

def _pick_best_category(resume_text: str, candidates: List[str]) -> str:
    if len(candidates) == 1:
        return candidates[0]
    try:
        text_emb = _sbert_embed(resume_text[:512])
        cat_embs = torch.stack([_sbert_embed(c) for c in candidates])
        sims     = util.cos_sim(text_emb.unsqueeze(0), cat_embs)[0]
        return candidates[torch.argmax(sims).item()]
    except Exception:
        return candidates[0]

def run_experience_model(resume_text: str):
    _load_local_models()
    label_map = {0: "Junior", 1: "Mid", 2: "Senior"}
    if _experience_model is None:
        return "Unknown", 0.0
    inputs = _experience_tokenizer(resume_text, truncation=True, padding=True,
                                   max_length=512, return_tensors="pt")
    with torch.no_grad():
        logits = _experience_model(**inputs).logits
        pred   = torch.argmax(logits, dim=-1).item()
        score  = torch.softmax(logits, dim=-1)[0, pred].item()
    return label_map.get(pred, "Unknown"), score

def infer_experience_level_with_model(resume_text: str) -> str:
    return run_experience_model(resume_text)[0]


# ══════════════════════════════════════════════
# NER skill extraction  (CV text only)
# ══════════════════════════════════════════════
NER_SKILL_LABELS = {"Skills", "Technology", "Designation", "Certifications"}

def ner_extract_skills(text: str, ner_model) -> List[str]:
    if ner_model is None or not text.strip():
        return []
    try:
        doc = ner_model(text[:1000])
        skills = []
        for ent in doc.ents:
            if ent.label_ in NER_SKILL_LABELS:
                for part in re.split(r"[,;|/]", ent.text):
                    s = normalize_skill(part)
                    if s and len(s) > 1:
                        skills.append(s)
        return skills
    except Exception as e:
        print(f"NER extraction error: {e}")
        return []


# ══════════════════════════════════════════════
# Groq portfolio extraction
# ══════════════════════════════════════════════
_SKILL_BLOCKLIST = {
    "leetcode", "codeforces", "atcoder", "codechef", "hackerrank", "hackerearth",
    "topcoder", "spoj", "codeabbey",
    "discord", "slack", "linkedin", "twitter", "reddit", "facebook", "instagram",
    "telegram", "whatsapp", "skype", "zoom", "teams",
    "vs code", "vscode", "visual studio code", "pycharm", "intellij", "webstorm",
    "sublime", "sublime text", "atom", "notepad++", "code-blocks", "codeblocks",
    "eclipse", "netbeans", "xcode", "android studio",
    "netlify", "vercel", "heroku", "github pages", "render",
    "github", "git & github", "competitive programming", "problem solving",
    "open source", "agile", "scrum",
}

def llm_summarize_and_extract_skills(text: str, context: str, groq_client) -> tuple:
    if not text or len(text.strip()) < 100:
        return "", []
    prompt = f"""Analyze this {context} portfolio content carefully.
Return ONLY valid JSON with exactly two fields:
  "summary": a single paragraph (max 120 words) describing technical skills, notable projects, tools & frameworks, and overall developer profile
  "skills": a comma-separated string of ONLY genuine technical skills

Rules for "skills":
- INCLUDE ONLY: programming languages, frameworks/libraries, databases, cloud platforms, DevOps/infrastructure tools
- DO NOT INCLUDE: competitive programming platforms, social platforms, code editors or IDEs, soft skills
- "skills" must be a flat comma-separated string, not an array
- No markdown, no code fences, no extra keys

Content ({context}):
{text[:3000]}"""
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0, max_completion_tokens=500,
        )
        raw  = re.sub(r"```json\n?|```\n?",
                      "", resp.choices[0].message.content.strip()).strip()
        data = json.loads(raw)
        return data.get("summary", "").strip(), _parse_groq_skills(data.get("skills", ""))
    except json.JSONDecodeError:
        raw = locals().get("raw", "")
        return (raw[:300] if raw else ""), []
    except Exception as e:
        print(f"Groq error ({context}): {e}")
        return f"Extraction failed: {e}", []

def _parse_groq_skills(skills_raw: str) -> List[str]:
    if not skills_raw or not isinstance(skills_raw, str):
        return []
    skills = []
    for token in skills_raw.split(","):
        s = normalize_skill(token)
        if not s or len(s) > 40:
            continue
        if re.search(
            r"\b(is|are|was|were|the|and|or|to|in|of|for|with|that|this|here|below|"
            r"have|has|had|will|would|can|could|should|may|might|must)\b", s):
            continue
        if s in _SKILL_BLOCKLIST or any(b in s for b in _SKILL_BLOCKLIST):
            continue
        skills.append(s)
    seen: set = set()
    return [s for s in skills if not (s in seen or seen.add(s))]


# ══════════════════════════════════════════════════════════════════════════════
# 9 CRITERIA SCORERS
# Each returns a float 0–100.
# Raw scores are passed to the RMFL agent which produces learned weights.
# ══════════════════════════════════════════════════════════════════════════════

RESULT_SIGNALS = [
    "improved","reduced","increased","achieved","delivered","launched","built","led",
    "grew","optimized","saved","generated","deployed","published","awarded","ranked",
    "won","promoted","%","percent","revenue","cost","users","accuracy","f1","auc",
]
COURSE_SIGNALS = [
    "coursework","course","module","subject","studied","curriculum","elective",
    "major","minor","specialization","coursera","udemy","edx","udacity","nptel",
    "mooc","online course","completed course",
]
TRAINING_SIGNALS = [
    "certified","certification","certificate","training","bootcamp","workshop",
    "seminar","aws certified","gcp certified","azure certified","pmp","scrum master",
    "cissp","comptia","oracle certified","microsoft certified","google certified",
    "professional certificate",
]
PROJECT_SIGNALS = [
    "project","built","developed","implemented","created","designed","coursework",
    "capstone","final year project","fyp","hackathon","contributed","repository","repo",
]
THESIS_SIGNALS = [
    "thesis","dissertation","research paper","published","publication","journal",
    "conference paper","arxiv","ieee","acm","springer","proceedings",
    "peer reviewed","peer-reviewed","undergraduate thesis","graduate thesis","master thesis",
]
EXPERIENCE_SIGNALS = [
    "intern","internship","full-time","part-time","contract","freelance",
    "engineer","developer","analyst","manager","consultant","associate",
    "worked at","employed","joined","role","position",
]


def _kw_hit_rate(text: str, keywords: List[str]) -> float:
    if not text.strip():
        return 0.0
    t = text.lower()
    hits = sum(1 for kw in keywords if kw in t)
    return round(min(hits / max(len(keywords) * 0.3, 1), 1.0) * 100, 2)

def _sem_vs_jd(text: str, jd_emb: torch.Tensor) -> float:
    if not text.strip():
        return 0.0
    emb = _sbert_embed(text[:512])
    return round(util.cos_sim(emb.unsqueeze(0), jd_emb.unsqueeze(0)).item() * 100, 2)

def _rel_sents(text: str, signals: List[str]) -> str:
    return " ".join(
        s for s in re.split(r"[.\n]", text)
        if any(sig in s.lower() for sig in signals)
    )[:2000]


def score_relevant_background(meta, cv_text, jd_emb, jd_skills):
    profile = " ".join([str(meta.get("Designation","")), str(meta.get("Skills","")),
                        str(meta.get("Education","")), cv_text[:300]])
    sem     = _sem_vs_jd(profile, jd_emb)
    overlap = sum(1 for s in jd_skills if s in profile.lower())
    return round(min(sem + min(overlap * 3, 20.0), 100.0), 2)

def score_results_achievements(meta, cv_text):
    text = " ".join([cv_text, str(meta.get("Projects","")), str(meta.get("Rewards",""))])
    base = _kw_hit_rate(text, RESULT_SIGNALS)
    nums = len(re.findall(
        r"\b\d+[%xX]|\$\d+|\d+[kKmMbB]\b|\d+\s*(percent|users|customers|revenue)", text))
    return round(min(base + min(nums * 5, 30.0), 100.0), 2)

def score_relevant_courses(meta, cv_text, jd_skills, jd_emb):
    text = " ".join([str(meta.get("Education","")), str(meta.get("Certifications","")), cv_text])
    sig  = _kw_hit_rate(text, COURSE_SIGNALS)
    if sig == 0.0:
        return 0.0
    sem = _sem_vs_jd(_rel_sents(text, COURSE_SIGNALS), jd_emb)
    return round(0.4 * sig + 0.6 * sem, 2)

def score_training_certification(meta, cv_text, jd_skills):
    text    = " ".join([str(meta.get("Certifications","")),
                        str(meta.get("Technology","")), cv_text])
    base    = _kw_hit_rate(text, TRAINING_SIGNALS)
    overlap = sum(1 for s in jd_skills if s in text.lower())
    return round(min(base + min(overlap * 8, 40.0), 100.0), 2)

def score_relevant_skills(cv_skills, jd_skills, ner_skills, portfolio_skills):
    all_cv    = list(set(cv_skills + ner_skills))
    port_only = [s for s in portfolio_skills if s not in all_cv]
    pct_cv, _, _   = fuzzy_skill_match(all_cv, jd_skills)
    pct_port, _, _ = fuzzy_skill_match(port_only, jd_skills) if port_only else (0.0, [], [])
    return round(min(0.7 * pct_cv + 0.3 * pct_port, 100.0), 2)

def score_work_experience(meta, cv_text, jd_skills, jd_emb):
    exp_raw  = str(meta.get("Experience", meta.get("experience", "")))
    exp_text = " ".join([exp_raw, cv_text])
    months        = parse_duration(exp_raw)
    dur_score     = round(min(months / 1.2, 100.0), 2)
    sem           = _sem_vs_jd(_rel_sents(exp_text, EXPERIENCE_SIGNALS), jd_emb)
    overlap_boost = min(sum(1 for s in jd_skills if s in exp_text.lower()) * 5, 30.0)
    return round(0.4 * dur_score + 0.6 * min(sem + overlap_boost, 100.0), 2)

def score_projects_coursework(meta, cv_text, jd_skills, jd_emb):
    proj_text = " ".join([str(meta.get("Projects","")), cv_text])
    sig = _kw_hit_rate(proj_text, PROJECT_SIGNALS)
    if sig == 0.0:
        return 0.0
    sem     = _sem_vs_jd(_rel_sents(proj_text, PROJECT_SIGNALS), jd_emb)
    overlap = min(sum(1 for s in jd_skills if s in proj_text.lower()) * 6, 30.0)
    return round(min(0.3 * sig + 0.5 * sem + 0.2 * overlap * 3.33, 100.0), 2)

def score_thesis_publications(meta, cv_text, jd_emb):
    text = " ".join([str(meta.get("Education","")), str(meta.get("Projects","")), cv_text])
    sig  = _kw_hit_rate(text, THESIS_SIGNALS)
    if sig == 0.0:
        return 0.0
    sem       = _sem_vs_jd(_rel_sents(text, THESIS_SIGNALS), jd_emb)
    pub_bonus = 20.0 if any(kw in text.lower() for kw in
                ["published","arxiv","ieee","acm","springer","journal","proceedings"]) else 0.0
    return round(min(0.4 * sig + 0.4 * sem + 0.2 * pub_bonus, 100.0), 2)

def score_portfolio_criterion(portfolio_data, jd_skills, jd_emb):
    if not portfolio_data:
        return 0.0
    summary    = portfolio_data.get("summary", "")
    port_skills = portfolio_data.get("skills_detected", [])
    sem        = _sem_vs_jd(summary, jd_emb) if summary else 0.0
    pct, _, _  = fuzzy_skill_match(
        [normalize_skill(s) for s in port_skills], jd_skills
    ) if port_skills else (0.0, [], [])
    return round(0.5 * sem + 0.5 * pct, 2)


def compute_detailed_criteria_score(
    meta, cv_text, cv_skills, ner_skills, portfolio_skills,
    portfolio_data, jd_skills, jd_emb, role_text,
) -> dict:
    """
    Compute all 9 raw criterion scores (0-100), ask the RMFL agent for
    learned weights, return weighted total + full breakdown.
    """
    raw_scores = {
        "relevant_background":    score_relevant_background(meta, cv_text, jd_emb, jd_skills),
        "results_achievements":   score_results_achievements(meta, cv_text),
        "relevant_courses":       score_relevant_courses(meta, cv_text, jd_skills, jd_emb),
        "training_certification": score_training_certification(meta, cv_text, jd_skills),
        "relevant_skills":        score_relevant_skills(cv_skills, jd_skills, ner_skills,
                                                         portfolio_skills),
        "work_experience":        score_work_experience(meta, cv_text, jd_skills, jd_emb),
        "projects_coursework":    score_projects_coursework(meta, cv_text, jd_skills, jd_emb),
        "thesis_publications":    score_thesis_publications(meta, cv_text, jd_emb),
        "portfolio":              score_portfolio_criterion(portfolio_data, jd_skills, jd_emb),
    }

    weights, log_prob, entropy = rmfl_agent.get_weights(
        role_text, raw_scores, deterministic=True)

    weighted_total = round(sum(weights[k] * raw_scores[k] for k in CRITERIA_KEYS), 2)

    breakdown = {
        k: {"learned_weight": weights[k],
            "raw_score":      raw_scores[k],
            "contribution":   round(weights[k] * raw_scores[k], 2)}
        for k in CRITERIA_KEYS
    }
    return {
        "criteria_scores": raw_scores, "learned_weights": weights,
        "weight_entropy": entropy, "weighted_total": weighted_total,
        "breakdown": breakdown, "log_prob": log_prob,
    }


# ══════════════════════════════════════════════
# Pydantic schemas
# ══════════════════════════════════════════════
class PortfolioResult(BaseModel):
    url:             str
    type:            str
    summary:         str
    skills_detected: List[str]
    repos:           Optional[List[Dict]]
    error:           Optional[str]

class CVRankEntry(BaseModel):
    rank:                int
    candidate_id:        str
    candidate_name:      Optional[str] = None
    candidate_email:     Optional[str] = None
    candidate_phone:     Optional[str] = None
    cv_text:             Optional[str] = None
    raw_row:             Optional[Dict[str, Any]] = None
    category:            str
    category_confidence: float
    semantic_match_pct:  float
    tech_match_pct:      float
    keyword_score:       float = 0.0
    entity_keyword_hits: Optional[Dict[str, List[str]]] = None
    priority_boost:      float
    criteria_scores:     Optional[Dict[str, float]] = None
    learned_weights:     Optional[Dict[str, float]] = None
    criteria_breakdown:  Optional[Dict[str, Any]]   = None
    criteria_total:      Optional[float]             = None
    weight_entropy:      Optional[float]             = None
    total_score:         float
    matched_skills:      List[str]
    missing_skills:      List[str]
    portfolio_url:       Optional[str]
    portfolio_type:      Optional[str]
    portfolio_summary:   Optional[str]
    portfolio_skills:    Optional[List[str]]

class RankedCandidate(BaseModel):
    rank:                int
    candidate:           str
    category:            str
    tech_match_pct:      float
    keyword_score:       float
    entity_keyword_hits: Optional[Dict[str, List[str]]]
    semantic_match_pct:  float
    criteria_total:      float
    learned_weights:     Optional[Dict[str, float]]
    total_score:         float
    matched_skills:      List[str]

class RankingResponse(BaseModel):
    jd_title:           Optional[str]
    jd_skills:          List[str]
    total_candidates:   int
    portfolios_scraped: int
    semantic_weight:    float
    tech_weight:        float
    rmfl_update_steps:  int
    ranked_table:       List[RankedCandidate]
    rankings:           List[CVRankEntry]

class JDExtractResponse(BaseModel):
    filename:  str
    extracted: Dict[str, Any]

class HealthResponse(BaseModel):
    status:           str
    models_loaded:    bool
    rmfl_steps:       int
    rmfl_replay_size: int

class FeedbackItem(BaseModel):
    candidate_id:     str
    role_text:        str
    criteria_scores:  Dict[str, float]
    weights_used:     Dict[str, float]
    outcome:          Optional[str] = None   # hired|rejected|shortlisted|screened_out
    human_rank:       Optional[int] = None
    system_rank:      Optional[int] = None
    total_candidates: int           = 1
    weighted_score:   float         = 0.0

class FeedbackBatch(BaseModel):
    feedback: List[FeedbackItem]

class WeightsResponse(BaseModel):
    role_text:    str
    weights:      Dict[str, float]
    entropy:      float
    update_steps: int

class SearchCVsResponse(BaseModel):
    query:            str
    query_tokens:     List[str]
    total_matched:    int
    keyword_clusters: Dict[str, List[str]]
    results:          List[Dict[str, Any]]


# ══════════════════════════════════════════════
# PORTFOLIO SCRAPING
# ══════════════════════════════════════════════
def normalize_url(raw: str) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    url = raw.strip()
    if url.lower() in {"n/a", "none", "no", "-", ""}:
        return None
    if not url.startswith("http"):
        url = "https://" + url
    if "." not in url:
        return None
    return url

def detect_portfolio_type(url: str) -> str:
    u = url.lower()
    if "github.com"   in u: return "github"
    if "linkedin.com" in u: return "linkedin"
    return "website"

def scrape_website_text(url: str, timeout: int = 12) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; CVScreener/3.0)"}
    try:
        r = requests.get(url, timeout=timeout, headers=headers)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text)[:MAX_CHARS_WEB]
    except Exception as e:
        return f"ERROR: {e}"

def extract_github_username(url: str) -> Optional[str]:
    parts = re.split(r"[/?#]", url.replace("https://","").replace("http://",""))
    if len(parts) >= 2 and "github.com" in parts[0]:
        u = parts[1].strip()
        return u if u else None
    return None

def fetch_github_repos(username: str, max_repos: int = 8) -> List[Dict]:
    try:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "CVScreener/3.0"}
        r = requests.get(f"{GITHUB_API}/users/{username}/repos",
                         params={"sort": "updated", "per_page": max_repos},
                         timeout=10, headers=headers)
        if r.status_code != 200:
            return []
        return [{"name": repo.get("name",""), "description": repo.get("description") or "",
                 "language": repo.get("language") or "", "topics": repo.get("topics",[]),
                 "stars": repo.get("stargazers_count",0), "url": repo.get("html_url","")}
                for repo in r.json()]
    except Exception as e:
        print(f"GitHub API error ({username}): {e}")
        return []

def fetch_github_readme(username: str, repo: str) -> str:
    try:
        r = requests.get(f"{GITHUB_API}/repos/{username}/{repo}/readme",
                         headers={"Accept": "application/vnd.github.raw",
                                  "User-Agent": "CVScreener/3.0"}, timeout=8)
        return r.text[:1500] if r.status_code == 200 else ""
    except Exception:
        return ""

def scrape_portfolio(url: str, groq_client, ner_model=None) -> Dict:
    clean = normalize_url(url)
    base  = {"url": clean or url, "type": "unknown",
             "summary": "", "skills_detected": [], "repos": None, "error": None}
    if not clean:
        base["error"] = "Invalid URL"; return base
    ptype = detect_portfolio_type(clean)
    base["type"] = ptype
    try:
        if ptype == "github":
            username = extract_github_username(clean)
            if not username:
                base["error"] = "Cannot extract GitHub username"; return base
            repos = fetch_github_repos(username)
            base["repos"] = repos
            readme_texts = []
            for repo in sorted(repos, key=lambda r: r["stars"], reverse=True)[:3]:
                txt = fetch_github_readme(username, repo["name"])
                if txt:
                    readme_texts.append(f"[{repo['name']}]\n{txt}")
                time.sleep(0.3)
            repo_lines = "\n".join(
                f"{r['name']} ({r['language']}): {r['description']}"
                for r in repos if r.get("description"))
            combined = (f"GitHub: {username}\n\nRepos:\n{repo_lines}\n\nREADMEs:\n"
                        + "\n\n".join(readme_texts))
            base["summary"], base["skills_detected"] = \
                llm_summarize_and_extract_skills(combined, "GitHub", groq_client)
        elif ptype == "linkedin":
            text = scrape_website_text(clean)
            if text.startswith("ERROR") or len(text.strip()) < 200:
                base["error"] = "LinkedIn blocked scraping (expected)"
            else:
                base["summary"], base["skills_detected"] = \
                    llm_summarize_and_extract_skills(text, "LinkedIn", groq_client)
        else:
            text = scrape_website_text(clean)
            if text.startswith("ERROR"):
                base["error"] = text; base["summary"] = "Could not fetch website"
            else:
                base["summary"], base["skills_detected"] = \
                    llm_summarize_and_extract_skills(text, "portfolio website", groq_client)
    except Exception as e:
        base["error"] = str(e); base["summary"] = f"Extraction failed: {e}"
    return base


# ══════════════════════════════════════════════
# CORE PIPELINE UTILS
# ══════════════════════════════════════════════
def extract_pdf_text(path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: text += t + "\n"
    except Exception as e:
        print(f"pdfplumber: {e}")
    if not text.strip():
        try:
            import PyPDF2
            with open(path, "rb") as f:
                for page in PyPDF2.PdfReader(f).pages:
                    t = page.extract_text()
                    if t: text += t + "\n"
        except Exception as e:
            print(f"PyPDF2: {e}")
    return re.sub(r"\s+", " ", text).strip()


_easyocr_reader = None


def extract_resume_pdf_with_easyocr(path: str) -> str:
    """Render a resume PDF and OCR every page with EasyOCR."""
    global _easyocr_reader
    try:
        import easyocr
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PDF resume OCR requires easyocr and pymupdf. "
            "Install the packages in requirements.txt."
        ) from exc

    if _easyocr_reader is None:
        # EasyOCR downloads its English recognition weights on first use.
        _easyocr_reader = easyocr.Reader(["en"], gpu=torch.cuda.is_available())

    pages: List[str] = []
    document = fitz.open(path)
    try:
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, pixmap.n
            )
            page_lines = _easyocr_reader.readtext(
                image, detail=0, paragraph=True
            )
            pages.append("\n".join(str(line) for line in page_lines))
    finally:
        document.close()

    return re.sub(r"[ \t]+", " ", "\n".join(pages)).strip()


def resume_text_to_record(text: str, filename: str) -> Dict[str, str]:
    """Create fields expected by the ranking pipeline from OCR text."""
    email_match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
    phone_match = re.search(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)", text)
    url_match = re.search(
        r"(?:https?://|www\.)[^\s<>]+|(?:github|linkedin)\.com/[^\s<>]+",
        text,
        re.IGNORECASE,
    )

    name = ""
    for raw_line in text.splitlines()[:12]:
        line = raw_line.strip(" |-:,.")
        words = line.split()
        if (2 <= len(words) <= 5 and len(line) <= 80
                and all(re.fullmatch(r"[A-Za-z][A-Za-z'.-]*", word) for word in words)
                and not any(term in line.lower() for term in
                            ("resume", "curriculum", "email", "phone", "address"))):
            name = line
            break

    email = email_match.group(0) if email_match else ""
    phone = phone_match.group(0).strip() if phone_match else ""
    portfolio = url_match.group(0).rstrip(".,);]") if url_match else ""
    if portfolio.startswith("www."):
        portfolio = "https://" + portfolio

    return {
        "Candidate_ID": email or filename,
        "Name": name or os.path.splitext(filename)[0].replace("_", " "),
        "Email": email,
        "Phone": phone,
        "Resume Text": text,
        "Skills": ", ".join(extract_skills_from_text(text)),
        "Portfolio Link": portfolio,
        "resume_file_name": filename,
    }

def read_word_resume(word_doc: str) -> Optional[str]:
    try:
        text = docx2txt.process(word_doc)
        text = ''.join(str(text)).replace("\n", "")
        return text if text.strip() else None
    except Exception as e:
        print(f"Error reading {word_doc}: {e}"); return None

def truncate(text: str, n: int) -> str:
    if len(text) <= n: return text
    cut = text[:n]
    for sep in ("\n", "."):
        pos = cut.rfind(sep)
        if pos > n * 0.8: return cut[:pos + 1]
    return cut

def call_groq(prompt: str, groq_client, retries=3, delay=3) -> str:
    for attempt in range(retries):
        try:
            resp = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0, max_completion_tokens=1024,
            )
            return resp.choices[0].message.content
        except Exception as e:
            wait = delay * (attempt + 1) * 2 if "rate_limit" in str(e).lower() else delay
            if attempt < retries - 1: time.sleep(wait)
    return "{}"

def normalize_skill(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())

def parse_duration(text: str) -> float:
    text = (text.lower().replace('yrs','years').replace('yr','year')
                .replace('mos','months').replace('mo','month'))
    matches = re.findall(r'(\d+(?:\.\d+)?)\s*(year|month|week|day)s?', text)
    months  = 0.0
    for value, unit in matches:
        val = float(value)
        if   'year'  in unit: months += val * 12
        elif 'month' in unit: months += val
        elif 'week'  in unit: months += val / 4.345
        elif 'day'   in unit: months += val / 30
    return round(months)

def months_to_string(months: float) -> str:
    months = round(months, 2)
    if months < 1: return f"{round(months * 30)} days"
    years, rem = int(months // 12), int(months % 12)
    result = []
    if years > 0: result.append(f"{years} year{'s' if years > 1 else ''}")
    if rem   > 0: result.append(f"{rem} month{'s' if rem > 1 else ''}")
    return ' '.join(result) if result else "0 months"

DESIGNATION_RANK = {
    'intern':0.5,'junior':0.8,'associate':1.0,'engineer':1.1,
    'senior':1.3,'lead':1.5,'manager':1.7,'director':2.0,'head':2.2,'chief':2.5,
}
TOP_COMPANIES = {
    'openai':2.5,'google':2.4,'microsoft':2.3,'apple':2.2,
    'facebook':2.2,'meta':2.2,'amazon':2.1,'nvidia':2.0,
}
DEGREE_RANK  = {'phd':2.5,'masters':2.0,'mba':1.8,'bachelors':1.5,'diploma':1.2}
COLLEGE_RANK = {'mit':2.5,'stanford':2.4,'iit':2.3,'harvard':2.3,'berkeley':2.1}

PROJECT_KEYWORDS_BY_ROLE = {
    'web_developer':  {'web':2.5,'frontend':2.3,'backend':2.2,'react':2.5},
    'data_scientist': {'ai':2.5,'ml':2.3,'nlp':2.2,'pytorch':2.0},
    'data_engineer':  {'etl':2.5,'pipeline':2.3,'spark':2.2},
    'devops_engineer':{'kubernetes':2.4,'docker':2.3,'ci/cd':2.2},
    'software_engineer':{'api':2.0,'system':2.2},
    'product_manager':{'roadmap':2.3,'strategy':2.5},
}
CERT_KEYWORDS_BY_ROLE = {
    'web_developer':  {'html':1.5,'css':1.5,'javascript':1.8},
    'data_scientist': {'ml':2.0,'ai':2.1,'dl':2.0,'gcp':1.9},
    'data_engineer':  {'big data':2.0,'spark':2.0},
    'devops_engineer':{'aws':2.2,'azure':2.0,'docker':2.0,'terraform':2.1},
    'software_engineer':{'java':1.5,'python':1.5},
    'product_manager':{'pmp':2.0,'scrum':1.8},
}
REWARD_KEYWORDS_BY_ROLE = {
    'web_developer':  {'best frontend':2.0,'ux':1.8},
    'data_scientist': {'innovation':2.2,'research':2.0},
    'devops_engineer':{'automation':2.0,'uptime':1.9},
    'product_manager':{'delivery':2.0,'vision':2.2},
}

def _get_max_rank(text: str, rank_map: dict) -> float:
    return max((v for k, v in rank_map.items() if k in text.lower()), default=0.0)

def _infer_primary_role(designation_text: str) -> str:
    role_keywords = {
        'web_developer':  ['web developer','frontend','backend','full stack','react'],
        'data_scientist': ['data scientist','machine learning','ml','ai','nlp'],
        'data_engineer':  ['data engineer','etl','big data','pipeline'],
        'devops_engineer':['devops','site reliability','sre','infrastructure','cloud'],
        'software_engineer':['software engineer','developer'],
        'product_manager':['product manager','pm'],
    }
    counts = {r: sum(1 for kw in kws if kw in designation_text.lower())
              for r, kws in role_keywords.items()}
    return max(counts, key=counts.get)

def compute_priority_boost(meta: dict, matched_skills: List[str]) -> float:
    boost = 0.0
    def _field(*keys):
        for k in keys:
            v = str(meta.get(k,"")).strip()
            if v and v.lower() != "nan": return v.lower()
        return ""
    designation_text = _field("Designation","designation","Title")
    companies_text   = _field("Companies","companies","Company","Employer")
    education_text   = _field("Education","education","Degree")
    college_text     = _field("CollegeName","College","college_name","University")
    experience_text  = _field("Experience","experience","Work Experience")
    projects_text    = _field("Projects","projects")
    certs_text       = _field("Certifications","certifications")
    rewards_text     = _field("Rewards","rewards","Awards")
    primary_role     = _infer_primary_role(designation_text)
    boost += min(parse_duration(experience_text) / 12, 10.0)
    boost += _get_max_rank(designation_text, DESIGNATION_RANK)
    boost += _get_max_rank(companies_text,   TOP_COMPANIES)
    boost += _get_max_rank(education_text,   DEGREE_RANK)
    boost += _get_max_rank(college_text,     COLLEGE_RANK)
    boost += _get_max_rank(projects_text,    PROJECT_KEYWORDS_BY_ROLE.get(primary_role,{}))
    boost += _get_max_rank(certs_text,       CERT_KEYWORDS_BY_ROLE.get(primary_role,{}))
    boost += _get_max_rank(rewards_text,     REWARD_KEYWORDS_BY_ROLE.get(primary_role,{}))
    if matched_skills: boost += 3.0
    return round(boost, 4)

def parse_skills_str(raw) -> List[str]:
    if not raw: return []
    return [normalize_skill(s) for s in re.split(r"[,;|]", str(raw)) if s.strip()]

def fuzzy_skill_match(cv_skills, jd_skills, threshold=80):
    if not jd_skills: return 0.0, [], []
    if not cv_skills: return 0.0, [], list(jd_skills)
    matched, missing = [], []
    for jd_s in jd_skills:
        best = max((max(fuzz.ratio(jd_s,c), fuzz.token_sort_ratio(jd_s,c),
                        fuzz.token_set_ratio(jd_s,c)) for c in cv_skills), default=0)
        (matched if best >= threshold else missing).append(jd_s)
    return round(len(matched) / len(jd_skills) * 100, 2), matched, missing

def extract_skills_from_text(text: str) -> List[str]:
    tokens = re.split(r"[,;|\n]", text)
    skills = []
    for t in tokens:
        t = t.strip()
        if not t or len(t.split()) > 4 or t.isdigit(): continue
        if re.search(r"\b(is|are|was|were|have|has|had|will|would|can|could|the|and|or|to|in|of|for|with)\b",
                     t.lower()): continue
        skills.append(normalize_skill(t))
    seen = set()
    return [s for s in skills if not (s in seen or seen.add(s))]

def predict_category(text: str, models):
    tok, bert = models["tokenizer"], models["bert"]
    inp = tok(text[:512], truncation=True, padding=True, max_length=512, return_tensors="pt")
    with torch.no_grad():
        probs = torch.softmax(bert(**inp).logits, dim=1)
        idx   = torch.argmax(probs, dim=1).item()
    if idx < len(CATEGORIES):
        return CATEGORIES[idx], round(probs[0][idx].item(), 4)
    return _pick_best_category(text, CATEGORIES), round(probs[0][idx].item(), 4)

def extract_jd_json(text: str, groq_client) -> dict:
    prompt = f"""Extract from this Job Description, return ONLY valid JSON with fields:
Job_Title, Company, Location, Experience, Education,
Skills (comma-separated string), Technology (comma-separated string),
Responsibilities, Qualifications, Salary, Additional_Info
Empty string "" for missing. No markdown.

JD:
{truncate(text, MAX_CHARS_JD)}"""
    raw = call_groq(prompt, groq_client)
    raw = re.sub(r"```json\n?|```\n?", "", raw.strip()).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "JSON parse failed", "raw": raw[:500]}


# ══════════════════════════════════════════════
# QUERY SEARCH SCORER
# ══════════════════════════════════════════════
SCORING_ENTITY_COLUMNS = [
    "Skills","Designation","Companies","Education","CollegeName",
    "Experience","Certifications","Technology","Links","Projects","Rewards"
]
IDENTITY_COLUMNS = ["Name","Address","Location","Email","Phone"]
QUERY_STOPWORDS = {
    "i","me","my","we","our","you","your","he","she","they","it",
    "is","are","was","were","be","been","being","have","has","had",
    "do","does","did","will","would","shall","should","may","might",
    "can","could","a","an","the","and","but","or","so","if","in",
    "on","at","to","for","of","with","by","from","as","into",
    "about","who","what","which","that","this","these","those",
    "find","me","show","get","list","give","all","any","some",
}

def tokenize_query(query: str) -> List[str]:
    tokens = re.findall(r"[a-zA-Z0-9#+.\-]+", query.lower())
    return [t for t in tokens if t not in QUERY_STOPWORDS and len(t) > 1]

def query_score_dataframe(df: pd.DataFrame, query_text: str) -> tuple:
    query_tokens    = tokenize_query(query_text)
    query_embedding = sbert_model.encode(query_text, convert_to_tensor=True)
    word_freq       = FreqDist(query_tokens)
    results, keyword_clusters = [], {}

    for _, row in df.iterrows():
        resume_file = str(row.get("resume_file_name", row.name)).strip()
        matched_identity = any(
            query_text.lower() in str(row.get(col,"")).lower()
            for col in IDENTITY_COLUMNS)
        combined_entity_text = " ".join(
            str(row.get(col,"")).lower() for col in SCORING_ENTITY_COLUMNS
            if str(row.get(col,"")).strip())
        matched_keywords: Dict[str, List[str]] = {}
        for col in SCORING_ENTITY_COLUMNS:
            val  = str(row.get(col,"")).lower()
            hits = [kw for kw in query_tokens if kw in val]
            if hits: matched_keywords[col] = hits
        if not matched_keywords and not matched_identity:
            continue
        if matched_keywords and combined_entity_text.strip():
            resume_embedding = sbert_model.encode(combined_entity_text, convert_to_tensor=True)
            sim_score        = util.cos_sim(query_embedding, resume_embedding).item() * 100
            keyword_score    = round(
                len(set(query_tokens) & set(combined_entity_text.split()))
                / max(1, len(query_tokens)) * 100, 2)
            final_score = round(0.8 * sim_score + 0.2 * keyword_score, 2)
        else:
            final_score = keyword_score = sim_score = 0.0

        policy_output = policy_guided_resume_analysis(
            str(row.get("Designation","")), str(row.get("Skills","")),
            str(row.get("Experience","")), combined_entity_text, training_mode=False)

        entity_dict = {col: str(row.get(col,""))
                       for col in SCORING_ENTITY_COLUMNS + IDENTITY_COLUMNS
                       if str(row.get(col,"")).strip()}
        results.append({
            "resume_file_name": resume_file,
            "similarity_score": final_score,
            "semantic_score":   round(sim_score, 2),
            "keyword_score":    keyword_score,
            "matched_keywords": matched_keywords,
            "matched_identity": matched_identity,
            "inferred_role":    policy_output["pred_label"],
            "experience_level": infer_experience_level_with_model(combined_entity_text),
            "entities":         entity_dict,
        })
        matched_terms = tuple(
            sorted({t for terms in matched_keywords.values() for t in terms})
        ) or ("matched_identity",)
        keyword_clusters.setdefault(matched_terms, []).append(resume_file)

    results.sort(key=lambda x: (x["similarity_score"], x["matched_identity"]), reverse=True)
    return results, query_tokens, word_freq, keyword_clusters


# ══════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════

@app.get("/")
def root():
    return {"message": "CV Screening API v3.0 — RMFL integrated",
            "docs": "/docs", "health": "/health"}

@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "models_loaded": bool(_models),
            "rmfl_steps": rmfl_agent.update_steps,
            "rmfl_replay_size": len(rmfl_agent.replay)}

@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    return {}

@app.post("/load-models")
def load_models_route():
    get_models()
    return {"status": "Models and RMFL agent loaded successfully",
            "rmfl_steps": rmfl_agent.update_steps}


@app.post("/convert-ats-cvs")
async def convert_ats_cvs(file: UploadFile = File(...)):
    """Convert every row in a candidate CSV into an ATS-friendly PDF."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files are accepted")
    content = await file.read()
    if not content:
        raise HTTPException(400, "The uploaded CSV is empty")
    try:
        from ats_converter import generate_ats_pdfs
        generated = generate_ats_pdfs(content)
    except (ImportError, OSError) as exc:
        raise HTTPException(
            503, "ATS PDF dependencies are unavailable. Install requirements.txt."
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for filename, pdf_bytes in generated:
            bundle.writestr(filename, pdf_bytes)
    archive.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="ats_cv_pdfs.zip"',
        "X-Generated-Count": str(len(generated)),
    }
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers=headers,
    )

@app.post("/extract-jd", response_model=JDExtractResponse)
async def extract_jd(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted")
    models = get_models()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read()); p = tmp.name
    try:
        text = extract_pdf_text(p)
    finally:
        os.unlink(p)
    if not text or len(text) < 50:
        raise HTTPException(422, "Could not extract text from PDF")
    return {"filename": file.filename, "extracted": extract_jd_json(text, models["groq"])}

@app.post("/extract-portfolio", response_model=PortfolioResult)
async def extract_portfolio_endpoint(url: str = Form(...)):
    models  = get_models()
    cleaned = normalize_url(url)
    if not cleaned:
        raise HTTPException(400, "Invalid or empty URL")
    return scrape_portfolio(cleaned, models["groq"])

@app.post("/rank-cvs", response_model=RankingResponse)
async def rank_cvs(
    jd_file:            UploadFile = File(...),
    cv_file:            Optional[UploadFile] = File(None),
    resume_files:       Optional[List[UploadFile]] = File(None),
    extract_portfolios: bool  = Form(False),
    semantic_weight:    float = Form(SEMANTIC_WEIGHT),
    tech_weight:        float = Form(TECH_WEIGHT),
):
    models  = get_models()
    total_w = semantic_weight + tech_weight
    if total_w <= 0:
        semantic_weight, tech_weight = SEMANTIC_WEIGHT, TECH_WEIGHT; total_w = 1.0
    sem_w = round(semantic_weight / total_w, 4)
    tec_w = round(1.0 - sem_w, 4)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as jd_tmp:
        jd_tmp.write(await jd_file.read()); jd_path = jd_tmp.name
    cv_path: Optional[str] = None
    resume_paths: List[Tuple[str, str]] = []
    if cv_file and cv_file.filename:
        if not cv_file.filename.lower().endswith(".csv"):
            raise HTTPException(400, "Candidate spreadsheet must be a CSV file")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as cv_tmp:
            cv_tmp.write(await cv_file.read()); cv_path = cv_tmp.name
    for resume_file in resume_files or []:
        if not resume_file.filename or not resume_file.filename.lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF resume files are accepted")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as resume_tmp:
            resume_tmp.write(await resume_file.read())
            resume_paths.append((resume_tmp.name, resume_file.filename))
    if not cv_path and not resume_paths:
        raise HTTPException(400, "Upload a Candidates CSV or at least one resume PDF")

    try:
        # ── 1. Extract JD ──────────────────────────────────────────────────
        jd_text = extract_pdf_text(jd_path)
        if not jd_text or len(jd_text) < 50:
            raise HTTPException(422, "Could not extract text from JD PDF")
        jd_data   = extract_jd_json(jd_text, models["groq"])
        jd_skills = parse_skills_str(
            next((jd_data[f] for f in JD_TECH_FIELDS if f in jd_data and jd_data[f]), ""))
        # Role text gives RMFL context about this job
        role_text = " ".join(filter(None, [
            jd_data.get("Job_Title",""), jd_data.get("Technology",""), jd_data.get("Skills","")]))

        # ── 2. Load CSV ────────────────────────────────────────────────────
        frames: List[pd.DataFrame] = []
        if cv_path:
            frames.append(pd.read_csv(cv_path).fillna(""))
        if resume_paths:
            ocr_records = []
            for resume_path, original_name in resume_paths:
                try:
                    resume_text = extract_resume_pdf_with_easyocr(resume_path)
                except Exception as exc:
                    raise HTTPException(
                        422, f"Could not OCR {original_name}: {exc}"
                    ) from exc
                if len(resume_text) < 20:
                    raise HTTPException(
                        422, f"EasyOCR could not find enough text in {original_name}"
                    )
                ocr_records.append(resume_text_to_record(resume_text, original_name))
            frames.append(pd.DataFrame(ocr_records))
        df = pd.concat(frames, ignore_index=True, sort=False).fillna("")
        skills_col = next(
            (c for opt in TECH_SKILLS_COLUMN_OPTIONS for c in [opt] if c in df.columns),
            next((c for c in df.columns
                  if "technical" in c.lower() and "skill" in c.lower()), None))
        portfolio_col = next(
            (opt for opt in PORTFOLIO_COLUMN_OPTIONS if opt in df.columns),
            next((c for c in df.columns if any(k in c.lower() for k in
                  ["portfolio","github","website","linkedin","link","url"])), None))
        id_col = next((c for c in ["Email Address","Email","Candidate_ID","ID"]
                       if c in df.columns), None)

        NAME_COL_CANDIDATES   = ["Name","Full Name","Candidate Name","First Name","Last Name"]
        EMAIL_COL_CANDIDATES  = ["Email Address","Email","E-mail","candidate_email"]
        PHONE_COL_CANDIDATES  = ["Phone","Phone Number","Contact","Contact Number","Mobile"]
        RESUME_COL_CANDIDATES = ["Resume","CV","CV Text","Resume Text",
                                  "Cover Letter","Summary","Profile"]

        cv_ids, cv_texts, cv_skills_list, cv_port_urls, cv_meta_rows = [], [], [], [], []

        for idx, row in df.iterrows():
            raw_id = None
            if id_col and str(row.get(id_col)).strip():
                raw_id = str(row[id_col])
            else:
                for c in EMAIL_COL_CANDIDATES:
                    if c in df.columns and str(row.get(c)).strip():
                        raw_id = str(row[c]); break
            cv_ids.append(raw_id or f"row_{idx}")

            resume_text = ""
            for c in RESUME_COL_CANDIDATES + ["Summary","Profile","About","Bio"]:
                if c in df.columns and str(row.get(c)).strip():
                    resume_text = str(row.get(c)).strip(); break
            if not resume_text:
                resume_text = " | ".join(str(v) for v in row.values if str(v).strip())
            cv_texts.append(resume_text[:MAX_CHARS_CV])

            explicit_skills = (parse_skills_str(str(row[skills_col]))
                               if skills_col and str(row.get(skills_col,"")).strip()
                               else extract_skills_from_text(resume_text))
            cv_skills_list.append(explicit_skills)
            cv_port_urls.append(
                normalize_url(str(row[portfolio_col])) if portfolio_col else None)

            raw_row: Dict[str, Any] = {}
            for k, v in row.items():
                try:
                    raw_row[str(k)] = v if (v is not None and not pd.isna(v)) else ""
                except Exception:
                    raw_row[str(k)] = str(v)
            cv_meta_rows.append(raw_row)

        if not cv_texts:
            raise HTTPException(422, "No CV records found in CSV")

        # ── 3. Portfolio scraping ──────────────────────────────────────────
        port_cache: Dict[str, Dict] = {}
        if extract_portfolios and portfolio_col:
            unique = list({u for u in cv_port_urls if u})
            print(f"Scraping {len(unique)} unique portfolio URLs…")
            for u in unique:
                print(f"  → {u}")
                port_cache[u] = scrape_portfolio(u, models["groq"])
                time.sleep(2)

        # ── 4. JD keyword tokenization ─────────────────────────────────────
        jd_keyword_tokens = tokenize_query(" ".join(jd_skills) + " " + jd_text)
        jd_word_freq      = FreqDist(jd_keyword_tokens)

        # ── 5. Embeddings ──────────────────────────────────────────────────
        jd_emb  = _sbert_embed(jd_text)
        cv_embs = torch.stack([_sbert_embed(t) for t in cv_texts])

        # ── 6. Category + NER ──────────────────────────────────────────────
        cat_results = [predict_category(t[:512], models) for t in cv_texts]
        ner_skills_list = (
            [ner_extract_skills(t, models["ner"]) for t in cv_texts]
            if models.get("ner") else [[] for _ in cv_texts])

        RANK_ENTITY_COLS = [
            "Skills","Designation","Companies","Education","CollegeName",
            "Experience","Certifications","Technology","Links","Projects","Rewards"
        ]

        # ── 7. Build candidate rows ────────────────────────────────────────
        rows = []
        for i, cid in enumerate(cv_ids):
            port_url  = cv_port_urls[i]
            port_data = port_cache.get(port_url, {}) if port_url else {}
            meta      = cv_meta_rows[i]

            augmented = list(cv_skills_list[i])
            if port_data.get("skills_detected"):
                augmented = list(set(augmented + [
                    normalize_skill(s) for s in port_data["skills_detected"]]))
            if ner_skills_list[i]:
                augmented = list(set(augmented + ner_skills_list[i]))

            tech_pct, matched, missing = fuzzy_skill_match(augmented, jd_skills)
            sem_pct = round(
                util.cos_sim(jd_emb.unsqueeze(0), cv_embs[i].unsqueeze(0)).item() * 100, 2)

            combined_entity_text = " ".join(
                str(meta.get(col,"")).lower() for col in RANK_ENTITY_COLS
                if str(meta.get(col,"")).strip())
            entity_keyword_hits: Dict[str, List[str]] = {}
            for col in RANK_ENTITY_COLS:
                val  = str(meta.get(col,"")).lower()
                hits = [kw for kw in jd_keyword_tokens if kw in val]
                if hits: entity_keyword_hits[col] = hits

            matched_tokens  = set(jd_keyword_tokens) & set(combined_entity_text.split())
            weighted_hits   = sum(jd_word_freq[t] for t in matched_tokens)
            total_jd_weight = sum(jd_word_freq[t] for t in jd_keyword_tokens) or 1
            keyword_score   = round(weighted_hits / total_jd_weight * 100, 2)
            priority_boost  = compute_priority_boost(meta, matched)

            # ── RMFL: 9 criteria scores + learned weights ──────────────────
            portfolio_skills_norm = [normalize_skill(s)
                                     for s in port_data.get("skills_detected", [])]
            criteria_result = compute_detailed_criteria_score(
                meta=meta, cv_text=cv_texts[i],
                cv_skills=cv_skills_list[i], ner_skills=ner_skills_list[i],
                portfolio_skills=portfolio_skills_norm, portfolio_data=port_data,
                jd_skills=jd_skills, jd_emb=jd_emb, role_text=role_text,
            )
            criteria_total = criteria_result["weighted_total"]

            # ── Final score ────────────────────────────────────────────────
            # 50% RMFL criteria | 30% SBERT semantic | 20% tech/keyword blend
            blended_tech = round(0.6 * tech_pct + 0.4 * keyword_score, 2)
            total_score  = round(
                0.50 * criteria_total
                + 0.30 * sem_pct
                + 0.20 * blended_tech
                + priority_boost * 0.05, 2)

            policy_output = policy_guided_resume_analysis(
                str(meta.get("Designation", meta.get("designation",""))),
                str(meta.get("Skills",      meta.get("skills",""))),
                str(meta.get("Experience",  meta.get("experience",""))),
                cv_texts[i], training_mode=False)

            candidate_name  = next((str(meta[c]).strip() for c in NAME_COL_CANDIDATES
                                    if c in meta and str(meta[c]).strip()), "")
            candidate_email = next((str(meta[c]).strip() for c in EMAIL_COL_CANDIDATES
                                    if c in meta and str(meta[c]).strip()), "")
            candidate_phone = next((str(meta[c]).strip() for c in PHONE_COL_CANDIDATES
                                    if c in meta and str(meta[c]).strip()), "")

            rows.append({
                "rank":                0,
                "candidate_id":        cid,
                "candidate_name":      candidate_name,
                "candidate_email":     candidate_email,
                "candidate_phone":     candidate_phone,
                "cv_text":             cv_texts[i],
                "raw_row":             meta,
                "category":            policy_output["pred_label"] or cat_results[i][0],
                "category_confidence": cat_results[i][1],
                "semantic_match_pct":  sem_pct,
                "tech_match_pct":      tech_pct,
                "keyword_score":       keyword_score,
                "entity_keyword_hits": entity_keyword_hits,
                "priority_boost":      priority_boost,
                "criteria_scores":     criteria_result["criteria_scores"],
                "learned_weights":     criteria_result["learned_weights"],
                "criteria_breakdown":  criteria_result["breakdown"],
                "criteria_total":      criteria_total,
                "weight_entropy":      criteria_result["weight_entropy"],
                "total_score":         total_score,
                "matched_skills":      matched,
                "missing_skills":      missing,
                "portfolio_url":       port_url,
                "portfolio_type":      port_data.get("type"),
                "portfolio_summary":   port_data.get("summary") or None,
                "portfolio_skills":    port_data.get("skills_detected") or None,
            })

        # ── 8. Sort & rank ─────────────────────────────────────────────────
        rows.sort(key=lambda x: x["total_score"], reverse=True)
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank

        # ── 9. Slim table ──────────────────────────────────────────────────
        ranked_table = [
            {
                "rank":                row["rank"],
                "candidate":           (row["candidate_name"] or row["candidate_email"]
                                        or row["candidate_id"]),
                "category":            row["category"],
                "tech_match_pct":      row["tech_match_pct"],
                "keyword_score":       row["keyword_score"],
                "entity_keyword_hits": row["entity_keyword_hits"],
                "semantic_match_pct":  row["semantic_match_pct"],
                "criteria_total":      row["criteria_total"],
                "learned_weights":     row["learned_weights"],
                "total_score":         row["total_score"],
                "matched_skills":      row["matched_skills"],
            }
            for row in rows
        ]

        return {
            "jd_title":           jd_data.get("Job_Title",""),
            "jd_skills":          jd_skills,
            "total_candidates":   len(rows),
            "portfolios_scraped": len(port_cache),
            "semantic_weight":    sem_w,
            "tech_weight":        tec_w,
            "rmfl_update_steps":  rmfl_agent.update_steps,
            "ranked_table":       ranked_table,
            "rankings":           rows,
        }

    finally:
        if os.path.exists(jd_path):
            os.unlink(jd_path)
        if cv_path and os.path.exists(cv_path):
            os.unlink(cv_path)
        for resume_path, _ in resume_paths:
            if os.path.exists(resume_path):
                os.unlink(resume_path)


@app.post("/feedback",
          summary="Submit hiring outcomes to train the RMFL weight policy")
def submit_feedback(batch: FeedbackBatch):
    """
    Call this after hiring decisions are known.
    Each item triggers a mini-batch REINFORCE update inside the RMFL agent.

    Supported outcomes: "hired" | "shortlisted" | "screened_out" | "rejected"
    Rank fields are optional but improve signal quality significantly.

    Example:
        POST /feedback
        {
          "feedback": [{
            "candidate_id": "alice@example.com",
            "role_text": "Senior ML Engineer pytorch transformers",
            "criteria_scores": {"relevant_skills": 85, "work_experience": 70, ...},
            "weights_used":    {"relevant_skills": 0.18, "work_experience": 0.21, ...},
            "outcome": "hired",
            "system_rank": 2, "human_rank": 1,
            "total_candidates": 30, "weighted_score": 78.4
          }]
        }
    """
    updated = 0
    for item in batch.feedback:
        reward = shape_reward(
            outcome=item.outcome, human_rank=item.human_rank,
            system_rank=item.system_rank, total_candidates=item.total_candidates,
            weighted_score=item.weighted_score,
        )
        rmfl_agent.update(
            role_text=item.role_text, criteria_scores=item.criteria_scores,
            weights_used=item.weights_used, reward=reward,
        )
        updated += 1
    rmfl_agent.save()
    return {"status": "updated", "items_processed": updated,
            "total_update_steps": rmfl_agent.update_steps,
            "replay_size": len(rmfl_agent.replay)}


@app.get("/rmfl-weights", response_model=WeightsResponse,
         summary="Inspect current learned weights for a role context")
def get_rmfl_weights(role_text: str = "software engineer python"):
    """
    Returns the Dirichlet-mean weights the RMFL agent assigns for a role.
    Useful for auditing and understanding what the agent has learned.

    Examples:
        GET /rmfl-weights?role_text=senior+devops+aws+kubernetes
        GET /rmfl-weights?role_text=phd+research+nlp+pytorch
        GET /rmfl-weights?role_text=junior+react+frontend+developer
    """
    result = rmfl_agent.get_current_weights_for_role(role_text)
    return {"role_text": role_text, "weights": result["weights"],
            "entropy": result["entropy"], "update_steps": result["update_steps"]}


@app.post("/skill-match")
def skill_match_endpoint(
    cv_skills: str = Form(...),
    jd_skills: str = Form(...),
    threshold: int = Form(80),
):
    cv_list = parse_skills_str(cv_skills)
    jd_list = parse_skills_str(jd_skills)
    pct, matched, missing = fuzzy_skill_match(cv_list, jd_list, threshold)
    return {"match_pct": pct, "matched": matched, "missing": missing,
            "cv_count": len(cv_list), "jd_count": len(jd_list)}

@app.get("/categories")
def get_categories():
    return {"categories": CATEGORIES}

@app.post("/search-cvs", response_model=SearchCVsResponse)
async def search_cvs(
    cv_file: UploadFile = File(...),
    query:   str        = Form(...),
):
    """Free-text search over a CSV of resumes, ranked by semantic + keyword relevance."""
    if not query.strip():
        raise HTTPException(400, "Query cannot be empty")
    get_models()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(await cv_file.read()); csv_path = tmp.name
    try:
        df = pd.read_csv(csv_path).fillna("")
    finally:
        os.unlink(csv_path)
    if df.empty:
        raise HTTPException(422, "CSV is empty or could not be parsed")
    results, query_tokens, _, keyword_clusters = query_score_dataframe(df, query)
    return {
        "query":            query,
        "query_tokens":     query_tokens,
        "total_matched":    len(results),
        "keyword_clusters": {", ".join(k): v for k, v in keyword_clusters.items()},
        "results":          results,
    }
