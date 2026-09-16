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
  cvFile:            File | null,
  resumeFiles:       File[],
  extractPortfolios: boolean,
) {
  const fd = new FormData();
  fd.append("jd_file",            jdFile);
  if (cvFile) fd.append("cv_file", cvFile);
  resumeFiles.forEach((file) => fd.append("resume_files", file));
  fd.append("extract_portfolios", String(extractPortfolios));

  const res = await fetch(`${API_BASE}/rank-cvs`, { method: "POST", body: fd });
  return mustJson<RankingResponse>(res);
}

export async function convertToAtsPdfs(csvFile: File) {
  const fd = new FormData();
  fd.append("file", csvFile);
  const res = await fetch(`${API_BASE}/convert-ats-cvs`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const raw = await res.text();
    try {
      const parsed = JSON.parse(raw);
      throw new Error(parsed.detail || raw || `HTTP ${res.status}`);
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error(raw || `HTTP ${res.status}`);
      throw error;
    }
  }
  return {
    blob: await res.blob(),
    filename: "ats_cv_pdfs.zip",
    count: Number(res.headers.get("X-Generated-Count") || 0),
  };
}
