import type {
  ApiJDExtractResponse,
  RankingResponse,
  HealthResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function mustJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function health() {
  const res = await fetch(`${API_BASE}/health`);
  return mustJson<HealthResponse>(res);
}

export async function extractJD(jdPdfFile: File) {
  const fd = new FormData();
  fd.append("file", jdPdfFile);

  const res = await fetch(`${API_BASE}/extract-jd`, { method: "POST", body: fd });
  return mustJson<ApiJDExtractResponse>(res);
}

export async function rankCVs(
  jdFile:            File,
  cvFile:            File,
  extractPortfolios: boolean,
) {
  const fd = new FormData();
  fd.append("jd_file",            jdFile);
  fd.append("cv_file",            cvFile);
  fd.append("extract_portfolios", String(extractPortfolios));

  const res = await fetch(`${API_BASE}/rank-cvs`, { method: "POST", body: fd });
  return mustJson<RankingResponse>(res);
}