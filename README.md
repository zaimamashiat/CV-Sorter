# 🎯 TalentMatch — AI-Powered CV Screening Pipeline

An end-to-end recruitment screening system that ranks candidates from a Google Form CSV export against a Job Description PDF using BERT, SBERT, fuzzy matching, and LLaMA via Groq.

---

## ✨ Features

- **JD Extraction** — Parses a Job Description PDF and extracts structured fields (title, company, required skills, responsibilities, etc.) using LLaMA
- **Bilingual CSV Support** — Handles Google Form exports with mixed Bengali/English column headers out of the box
- **AI Candidate Ranking** — Ranks candidates using a combination of:
  - **BERT** (`SwaKyxd/resume-analyser-bert`) for resume category classification
  - **SBERT** (`all-mpnet-base-v2`) for semantic similarity between JD and candidate profile
  - **RapidFuzz** for fuzzy skill matching with configurable threshold
- **Portfolio Scraping** *(optional)* — Fetches GitHub repos, LinkedIn pages, and personal websites; uses LLaMA to summarise and extract additional skills
- **PDF Resume OCR** — Upload one or more resume PDFs; EasyOCR extracts candidate details for JD matching
- **ATS CV Converter** — Convert candidate CSV exports into clean, searchable ATS PDFs
- **Live Dashboard** — React frontend with candidate rankings table, JD management, analytics charts, and candidate detail modals

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      React Frontend                      │
│  Dashboard · Rankings Table · Analytics · Upload View    │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP (multipart/form-data)
┌─────────────────────▼───────────────────────────────────┐
│                   FastAPI Backend                         │
│                                                          │
│  /extract-jd     →  pdfplumber + LLaMA (Groq)           │
│  /rank-cvs       →  BERT + SBERT + Fuzzy + LLaMA        │
│  /extract-portfolio → requests + BeautifulSoup + LLaMA  │
│  /debug-csv      →  Column detection diagnostic          │
└─────────────────────────────────────────────────────────┘
```

---

## 📋 Prerequisites

- Python 3.10+
- Node.js 18+
- A [Groq API key](https://console.groq.com) (free tier works)

---

## 🚀 Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/your-org/talent-match.git
cd talent-match
```

### 2. Backend setup

```bash
cd backend   # or wherever main.py lives

# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install fastapi uvicorn pdfplumber PyPDF2 pandas torch \
            sentence-transformers transformers rapidfuzz \
            groq requests beautifulsoup4

# Set your Groq API key
set GROQ_API_KEY=your_key_here        # Windows
# export GROQ_API_KEY=your_key_here  # macOS/Linux

# Start the server
uvicorn main:app --reload --port 8000
```

The API will be live at `http://localhost:8000`  
Interactive docs at `http://localhost:8000/docs`

### 3. Frontend setup

```bash
cd frontend   # or wherever your React app lives

npm install
npm run dev
```

The app will be available at `http://localhost:5173`

---

## 📁 CSV Format

The backend is designed for **Google Form CSV exports**. Column detection is keyword-based, so exact header names don't need to match — it finds columns by searching for keywords in both English and Bengali.

### Supported column sections

| Section | Keywords detected |
|---|---|
| Identity | Full Name, Email Address, Phone Number |
| Education | University Name, Bachelors/Honors Subject, CGPA |
| Portfolio | Portfolio Link, GitHub, LinkedIn, Website |
| Work Experience | Designation, Organization, Starting Date, Ending Date (×3) |
| Certifications | Name of the Certification, Course Duration (×3) |
| Skills | Digital Skills, Technical Skills, Language Skills, Soft Skills |
| Training | Training Name, Training Organization, Training Duration (×3) |

> **Tip:** If you're unsure whether your CSV is being parsed correctly, upload it to the `/debug-csv` endpoint first. It shows exactly which columns were detected and a preview of the extracted resume text for the first two candidates.

---

## 🔌 API Reference

### `POST /extract-jd`
Extracts structured fields from a Job Description PDF.

| Field | Type |
|---|---|
| `file` | PDF file |

**Response:** JSON with `Job_Title`, `Company`, `Location`, `Skills`, `Technology`, etc.

---

### `POST /rank-cvs`
Main endpoint. Ranks all candidates in the CSV against the JD.

| Field | Type | Description |
|---|---|---|
| `jd_file` | PDF | Job Description |
| `cv_file` | CSV | Candidates (Google Form export) |
| `extract_portfolios` | bool | Scrape portfolio URLs (slow, optional) |

**Response:**
```json
{
  "jd_title": "Software Engineer",
  "jd_skills": ["python", "react", "docker"],
  "total_candidates": 231,
  "portfolios_scraped": 0,
  "rankings": [
    {
      "rank": 1,
      "candidate_id": "candidate@email.com",
      "candidate_name": "Jane Doe",
      "candidate_email": "candidate@email.com",
      "candidate_phone": "+880...",
      "category": "Python Developer",
      "category_confidence": 0.91,
      "semantic_match_pct": 74.3,
      "tech_match_pct": 83.3,
      "matched_skills": ["python", "docker"],
      "missing_skills": ["react"],
      "portfolio_url": "https://github.com/janedoe",
      "portfolio_summary": "...",
      "portfolio_skills": ["python", "fastapi", "postgresql"]
    }
  ]
}
```

---

### `POST /extract-portfolio`
Scrape and analyse a single portfolio URL.

| Field | Type |
|---|---|
| `url` | string |

---

### `POST /debug-csv`
Diagnostic endpoint — shows how every column in your CSV was classified and a resume text preview for the first two rows.

---

### `POST /skill-match`
Standalone fuzzy skill matching between two comma-separated skill strings.

| Field | Type | Default |
|---|---|---|
| `cv_skills` | string | — |
| `jd_skills` | string | — |
| `threshold` | int | 80 |

---

## 🧠 How Ranking Works

Each candidate gets two scores:

1. **Tech Match %** — fuzzy string matching (RapidFuzz) between the candidate's extracted skills and the JD's required skills. Uses `ratio`, `partial_ratio`, `token_sort_ratio`, and `token_set_ratio` — the best of the four wins for each skill pair.

2. **Semantic Match %** — cosine similarity between the SBERT embedding of the full JD text and the SBERT embedding of the candidate's structured resume text, reduced from 768→384 dimensions.

**Final ranking** sorts by Tech Match % first, then Semantic Match % as a tiebreaker.

If portfolio scraping is enabled, skills detected from GitHub/LinkedIn/websites are merged with the candidate's form-submitted skills before matching — so a candidate who listed "Python" in the form but whose GitHub shows Docker and PostgreSQL will have those counted too.

---

## 🖥️ Frontend Pages

| Page | Description |
|---|---|
| **Dashboard** | Hero banner, stats cards, JD list, and rankings table for the selected JD |
| **Job Descriptions** | Card grid of all uploaded JDs |
| **Candidates** | Full rankings table with JD filter pills |
| **Analytics** | Charts: avg tech match by JD, score distribution, category pie, skill gap analysis, radar profile |
| **Upload** | JD PDF plus candidate CSV and/or EasyOCR resume PDFs, with animated progress and stage tracking |

---

## ⚙️ Configuration

All config constants are at the top of `main.py`:

```python
MAX_CHARS_JD  = 4000   # Characters sent to LLaMA for JD extraction
MAX_CHARS_CV  = 3000   # Characters used per candidate for embedding
MAX_CHARS_WEB = 3000   # Characters scraped from portfolio pages
```

Fuzzy matching threshold (default 80) can be changed per-request via the `/skill-match` endpoint or adjusted globally in `fuzzy_skill_match()`.

---

## ⚠️ Known Limitations

- **Portfolio scraping is slow** — ~2 seconds per URL, sequential. 231 candidates with portfolios = ~8 minutes. A streaming or async queue would fix this.
- **LinkedIn blocks scraping** — expected behaviour. The candidate's form-submitted skills are still used.
- **No authentication** — the API has open CORS. Add an API key header or OAuth before deploying to production.
- **Models load on first request** — BERT + SBERT take 20–40 seconds to load on cold start. Hit `/load-models` at startup to pre-warm.
- **LLaMA rate limits** — Groq's free tier has RPM limits. If you hit them, the `call_groq()` function retries with exponential backoff automatically.

---

## 📦 Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.10+ |
| ML — Classification | BERT (`SwaKyxd/resume-analyser-bert`) via HuggingFace Transformers |
| ML — Embeddings | SBERT (`all-mpnet-base-v2`) via sentence-transformers |
| ML — Skill Matching | RapidFuzz |
| LLM | LLaMA 3.1 8B Instant via Groq API |
| PDF Parsing / OCR | pdfplumber, PyPDF2, PyMuPDF, EasyOCR |
| Web Scraping | requests, BeautifulSoup4 |
| Frontend | React, TypeScript, Vite |
| UI Components | shadcn/ui, Tailwind CSS |
| Charts | Recharts |
| Data Fetching | TanStack Query |

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

---

## 📄 License

MIT
