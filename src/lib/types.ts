// ── GET /health response ─────────────────────────────────────────────────────
export interface HealthResponse {
  status:           string;
  models_loaded:    boolean;
  rmfl_steps:       number;
  rmfl_replay_size: number;
}

// ── POST /extract-jd response ─────────────────────────────────────────────────
export interface ApiJDExtractResponse {
  filename:  string;
  extracted: Record<string, any>;
}

// ── RMFL criterion breakdown entry ───────────────────────────────────────────
export interface CriterionBreakdown {
  learned_weight: number;
  raw_score:      number;
  contribution:   number;
}

// ── Raw API response from POST /rank-cvs  (rankings array item) ──────────────
export interface ApiCVRankEntry {
  rank:                 number;
  candidate_id:         string;
  candidate_name:       string | null;
  candidate_email:      string | null;
  candidate_phone:      string | null;
  cv_text:              string | null;
  raw_row:              Record<string, string> | null;
  category:             string;
  area_of_interest:     string | null;
  category_confidence:  number;
  semantic_match_pct:   number;
  tech_match_pct:       number;
  keyword_score:        number;
  entity_keyword_hits:  Record<string, string[]> | null;
  priority_boost:       number;
  total_score:          number;
  matched_skills:       string[];
  missing_skills:       string[];
  portfolio_url:        string | null;
  portfolio_type:       string | null;
  portfolio_summary:    string | null;
  portfolio_skills:     string[] | null;
  portfolio_status:     "generated" | "empty" | "not_processed" | "not_provided";
  portfolio_error:      string | null;
  // ── RMFL fields (present when backend v3.0+ is used) ──────────────────────
  criteria_scores:      Record<string, number>             | null;
  learned_weights:      Record<string, number>             | null;
  criteria_breakdown:   Record<string, CriterionBreakdown> | null;
  criteria_total:       number | null;
  weight_entropy:       number | null;
}

// ── UI-enriched candidate (ApiCVRankEntry + local UI aliases) ─────────────────
export interface UICandidate extends ApiCVRankEntry {
  /** UI alias — resolves to candidate_name → email → candidate_id */
  id:               string;
  name:             string;
  email:            string;
  /** Set from the CSV "Area of Interest" column or areaOfInterestMap */
  area_of_interest: string;
}

// ── Job Description stored in local state ────────────────────────────────────
export interface UIJD {
  id:          string;
  Job_Title:   string;
  Company:     string;
  Location:    string;
  Technology:  string;
}

// ── Full /rank-cvs API response ───────────────────────────────────────────────
export interface RankingResponse {
  jd_title:           string | null;
  jd_skills:          string[];
  total_candidates:   number;
  portfolios_scraped: number;
  semantic_weight:    number;
  tech_weight:        number;
  rmfl_update_steps:  number;
  ranked_table:       RankedCandidate[];
  rankings:           ApiCVRankEntry[];
}

// ── Slim ranked_table entry from /rank-cvs ───────────────────────────────────
export interface RankedCandidate {
  rank:                number;
  candidate:           string;
  category:            string;
  tech_match_pct:      number;
  keyword_score:       number;
  entity_keyword_hits: Record<string, string[]> | null;
  semantic_match_pct:  number;
  criteria_total:      number;
  learned_weights:     Record<string, number> | null;
  total_score:         number;
  matched_skills:      string[];
}
