import { useState, useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { rankCVs, extractJD } from "@/lib/api";
import type { RankingResponse } from "@/lib/types";
import {
  FileText, FileSpreadsheet, Globe,
  Loader2, AlertCircle, CheckCircle2, Plus, X,
} from "lucide-react";

type Props = {
  onSubmit: (payload: {
    jdFiles:           File[];
    cvFile:            File | null;
    resumeFiles:       File[];
    extractPortfolios: boolean;
    jdExtractedList:   Array<{ file: File; extracted: Record<string, any> }>;
    ranking:           RankingResponse;
    areaOfInterestMap: Record<string, string>;
  }) => void;
  onCancel?: () => void;
};

// ── CSV Area-of-Interest parser ──────────────────────────────────────────────
async function parseAreaOfInterestFromCSV(file: File): Promise<Record<string, string>> {
  const text  = await file.text();
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) return {};

  const parseLine = (line: string): string[] => {
    const result: string[] = [];
    let current  = "";
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (inQuotes && line[i + 1] === '"') { current += '"'; i++; }
        else inQuotes = !inQuotes;
      } else if (ch === "," && !inQuotes) {
        result.push(current.trim());
        current = "";
      } else {
        current += ch;
      }
    }
    result.push(current.trim());
    return result;
  };

  const headers = parseLine(lines[0]).map((h) => h.replace(/^"|"$/g, "").trim());

  const AOI_ALIASES = [
    "area of interest", "area_of_interest", "areaofinterest",
    "interest", "domain", "field", "specialization", "focus area",
  ];
  const ID_ALIASES = [
    "email", "candidate_email", "e-mail",
    "id", "candidate_id", "candidate id",
    "name", "candidate_name", "full name",
  ];

  const aoiIdx = headers.findIndex((h) => AOI_ALIASES.includes(h.toLowerCase()));
  const idIdx  = headers.findIndex((h) => ID_ALIASES.includes(h.toLowerCase()));

  if (aoiIdx === -1) return {};

  const map: Record<string, string> = {};
  for (let i = 1; i < lines.length; i++) {
    const cols = parseLine(lines[i]).map((c) => c.replace(/^"|"$/g, "").trim());
    const aoi  = cols[aoiIdx] ?? "";
    if (!aoi) continue;
    const key = idIdx !== -1 ? (cols[idIdx] ?? String(i)) : String(i);
    if (key) map[key] = aoi;
  }
  return map;
}

// ── Stage definitions ────────────────────────────────────────────────────────
interface StageConfig {
  key:      string;
  label:    string;
  sublabel: string;
  weight:   number;
}

const buildStages = (jdCount: number, withPortfolio: boolean): StageConfig[] => {
  const stages: StageConfig[] = [
    {
      key:      "extracting-jd",
      label:    jdCount > 1 ? `Extracting ${jdCount} job descriptions` : "Extracting job description",
      sublabel: "Parsing PDFs with LLaMA...",
      weight:   withPortfolio ? 8 : 20,
    },
    {
      key:      "ranking",
      label:    "Embedding & ranking candidates",
      sublabel: jdCount > 1
        ? `BERT + SBERT + RMFL across ${jdCount} JDs...`
        : "BERT · SBERT · fuzzy matching · RMFL criteria scoring...",
      weight: withPortfolio ? 12 : 80,
    },
  ];
  if (withPortfolio) {
    stages.push({
      key:      "scraping-portfolios",
      label:    "Scraping portfolios",
      sublabel: "GitHub · LinkedIn · websites via LLaMA...",
      weight:   80,
    });
  }
  return stages;
};

// ── Animated progress hook ───────────────────────────────────────────────────
function useAnimatedProgress(
  stageIndex: number,
  stages:     StageConfig[],
  done:       boolean,
  running:    boolean,
  withPortfolio: boolean,
) {
  const [progress, setProgress] = useState(0);
  const rafRef   = useRef<number>(0);
  const startRef = useRef<number>(0);

  const totalWeight  = stages.reduce((s, st) => s + st.weight, 0);
  const stagePcts    = stages.map((_, i) =>
    stages.slice(0, i).reduce((s, st) => s + st.weight, 0) / totalWeight * 100
  );
  const stageEndPcts = stages.map((_, i) =>
    stages.slice(0, i + 1).reduce((s, st) => s + st.weight, 0) / totalWeight * 100
  );

  useEffect(() => {
    cancelAnimationFrame(rafRef.current);

    if (done)     { setProgress(100); return; }
    if (!running) { setProgress(0);   return; }

    const stageStart = stagePcts[stageIndex]    ?? 0;
    const stageEnd   = stageEndPcts[stageIndex] ?? 100;
    const stageMax   = stageEnd - 3; // leave a 3% gap so it never hits next stage early

    startRef.current = performance.now();

    const BASE_DURATION  = withPortfolio ? 180_000 : 30_000;
    const stageWeight    = stages[stageIndex]?.weight ?? 100;
    const duration       = (stageWeight / totalWeight) * BASE_DURATION;

    const animate = (now: number) => {
      const elapsed = now - startRef.current;
      const t       = Math.min(elapsed / duration, 1);
      const eased   = 1 - Math.pow(1 - t, 2);
      const pct     = stageStart + eased * (stageMax - stageStart);
      setProgress(Math.min(pct, stageMax));
      if (t < 1) rafRef.current = requestAnimationFrame(animate);
    };

    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stageIndex, done, running]);

  return progress;
}

// ── Component ────────────────────────────────────────────────────────────────
export function UploadView({ onSubmit, onCancel }: Props) {
  const [jdFiles, setJdFiles]                     = useState<File[]>([]);
  const [cvFile,  setCvFile]                      = useState<File | null>(null);
  const [resumeFiles, setResumeFiles]              = useState<File[]>([]);
  const [extractPortfolios, setExtractPortfolios] = useState(false);
  const [stageIndex, setStageIndex]               = useState(0);
  const [isDone, setIsDone]                       = useState(false);
  const [isRunning, setIsRunning]                 = useState(false);
  const [candidateCount, setCandidateCount]       = useState<number | null>(null);
  const [aoiDetected, setAoiDetected]             = useState<boolean | null>(null);
  const [rmflSteps, setRmflSteps]                 = useState<number | null>(null);

  const stages       = buildStages(jdFiles.length || 1, extractPortfolios);
  const progressLive = useAnimatedProgress(stageIndex, stages, isDone, isRunning, extractPortfolios);

  // Detect AOI column whenever CV file changes
  useEffect(() => {
    if (!cvFile) { setAoiDetected(null); return; }
    parseAreaOfInterestFromCSV(cvFile).then((map) => {
      setAoiDetected(Object.keys(map).length > 0);
    });
  }, [cvFile]);

  const addJdFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const pdfs = Array.from(incoming).filter((f) => f.type === "application/pdf");
    setJdFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      return [...prev, ...pdfs.filter((f) => !names.has(f.name))];
    });
  };

  const removeJd = (index: number) =>
    setJdFiles((prev) => prev.filter((_, i) => i !== index));

  const addResumeFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const pdfs = Array.from(incoming).filter(
      (file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
    );
    setResumeFiles((prev) => {
      const names = new Set(prev.map((file) => file.name));
      return [...prev, ...pdfs.filter((file) => !names.has(file.name))];
    });
  };

  const mutation = useMutation({
    mutationFn: async () => {
      if (jdFiles.length === 0) throw new Error("Please select at least one JD PDF");
      if (!cvFile && resumeFiles.length === 0) {
        throw new Error("Please select a Candidates CSV or at least one resume PDF");
      }

      // Reset state
      setIsRunning(true);
      setIsDone(false);
      setStageIndex(0);
      setCandidateCount(null);
      setRmflSteps(null);

      // ── Step 1: parse AOI from CSV ─────────────────────────────────────
      const areaOfInterestMap = cvFile
        ? await parseAreaOfInterestFromCSV(cvFile)
        : {};

      // ── Step 2: extract all JDs in parallel ───────────────────────────
      setStageIndex(0);
      const jdExtractedList = await Promise.all(
        jdFiles.map(async (file) => {
          const resp = await extractJD(file);
          return { file, extracted: resp?.extracted ?? {} };
        })
      );

      // ── Step 3: rank candidates (server runs BERT+SBERT+RMFL) ─────────
      setStageIndex(1);
      if (extractPortfolios) setStageIndex(2);

      // Always use the first JD file for the ranking call
      // (multi-JD support can be added server-side later)
      const ranking: RankingResponse = await rankCVs(
        jdFiles[0],
        cvFile,
        resumeFiles,
        extractPortfolios,
      );

      setCandidateCount(ranking.total_candidates);
      setRmflSteps(ranking.rmfl_update_steps ?? null);

      setIsDone(true);
      setIsRunning(false);

      return { jdExtractedList, ranking, areaOfInterestMap };
    },

    onSuccess: ({ jdExtractedList, ranking, areaOfInterestMap }) => {
      onSubmit({
        jdFiles,
        cvFile,
        resumeFiles,
        extractPortfolios,
        jdExtractedList,
        ranking,
        areaOfInterestMap,
      });
    },

    onError: () => {
      setIsRunning(false);
      setIsDone(false);
      setStageIndex(0);
    },
  });

  const isPending    = mutation.isPending;
  const currentStage = stages[Math.min(stageIndex, stages.length - 1)];
  const pct          = Math.round(progressLive);

  const barColor =
    pct < 33 ? "bg-blue-500" :
    pct < 66 ? "bg-teal-500" :
               "bg-green-500";

  return (
    <div className="w-full max-w-4xl mx-auto space-y-6 py-4 md:py-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Upload &amp; Rank</h2>
          <p className="text-sm text-muted-foreground">
            Upload JD PDFs, then add candidates from a CSV and/or resume PDFs
          </p>
        </div>
        {onCancel && (
          <button
            onClick={onCancel}
            disabled={isPending}
            className="px-3 py-2 text-xs font-semibold rounded-lg bg-muted hover:bg-muted/80 disabled:opacity-50 transition-colors"
          >
            Back
          </button>
        )}
      </div>

      <div className="rounded-2xl border bg-card shadow-card p-6 md:p-8 space-y-6">

        {/* ── JD files ────────────────────────────────────────────────── */}
        <div className="space-y-1.5">
          <label className="text-sm font-semibold text-foreground flex items-center gap-2">
            <FileText className="w-4 h-4 text-muted-foreground" />
            Job Description(s) (PDF)
            {jdFiles.length > 0 && (
              <span className="ml-auto text-xs font-normal bg-teal-100 text-teal-700 px-2 py-0.5 rounded-full">
                {jdFiles.length} file{jdFiles.length > 1 ? "s" : ""} added
              </span>
            )}
          </label>

          <label
            className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg border border-dashed cursor-pointer transition-colors text-sm
              ${isPending ? "opacity-50 pointer-events-none" : "hover:bg-muted/40 hover:border-teal-400"}`}
          >
            <Plus className="w-4 h-4 text-muted-foreground shrink-0" />
            <span className="text-muted-foreground">
              {jdFiles.length === 0 ? "Select one or more JD PDFs" : "Add more JD PDFs"}
            </span>
            <input
              type="file"
              accept="application/pdf"
              multiple
              disabled={isPending}
              className="hidden"
              onChange={(e) => addJdFiles(e.target.files)}
            />
          </label>

          {jdFiles.length > 0 && (
            <ul className="space-y-1">
              {jdFiles.map((f, i) => (
                <li
                  key={f.name + i}
                  className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/30 rounded-lg px-3 py-1.5"
                >
                  <CheckCircle2 className="w-3 h-3 text-green-500 shrink-0" />
                  <span className="flex-1 truncate">{f.name}</span>
                  {!isPending && (
                    <button
                      onClick={() => removeJd(i)}
                      className="text-muted-foreground hover:text-red-500 transition-colors"
                      aria-label="Remove JD"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {jdFiles.length > 1 && (
            <p className="text-xs text-teal-600 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              Candidates ranked by best match across all {jdFiles.length} JDs
            </p>
          )}
        </div>

        {/* ── CSV file ────────────────────────────────────────────────── */}
        <div className="space-y-1.5">
          <label className="text-sm font-semibold text-foreground flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4 text-muted-foreground" />
            Candidates (CSV)
          </label>
          <input
            type="file"
            accept=".csv,text/csv"
            disabled={isPending}
            onChange={(e) => setCvFile(e.target.files?.[0] ?? null)}
            className="w-full text-sm file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-muted file:text-foreground hover:file:bg-muted/80 disabled:opacity-50"
          />
          {cvFile && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-green-500" /> {cvFile.name}
              </p>
              {aoiDetected === true && (
                <p className="text-xs text-teal-600 flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" />
                  "Area of Interest" column detected — will be shown in results
                </p>
              )}
              {aoiDetected === false && (
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />
                  No "Area of Interest" column found
                </p>
              )}
            </div>
          )}
        </div>

        {/* ── Portfolio toggle ─────────────────────────────────────────── */}
        <div className="space-y-1.5">
          <label className="text-sm font-semibold text-foreground flex items-center gap-2">
            <FileText className="w-4 h-4 text-muted-foreground" />
            Candidate Resumes (PDF)
            {resumeFiles.length > 0 && (
              <span className="ml-auto text-xs font-normal bg-teal-100 text-teal-700 px-2 py-0.5 rounded-full">
                {resumeFiles.length} file{resumeFiles.length > 1 ? "s" : ""} added
              </span>
            )}
          </label>
          <p className="text-xs text-muted-foreground">
            Each PDF is scanned with EasyOCR and its contact details, skills, and resume text are matched against the JD.
          </p>
          <label className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg border border-dashed cursor-pointer transition-colors text-sm ${
            isPending ? "opacity-50 pointer-events-none" : "hover:bg-muted/40 hover:border-teal-400"
          }`}>
            <Plus className="w-4 h-4 text-muted-foreground shrink-0" />
            <span className="text-muted-foreground">
              {resumeFiles.length === 0 ? "Select one or more resume PDFs" : "Add more resume PDFs"}
            </span>
            <input
              type="file"
              accept="application/pdf,.pdf"
              multiple
              disabled={isPending}
              className="hidden"
              onChange={(event) => addResumeFiles(event.target.files)}
            />
          </label>
          {resumeFiles.length > 0 && (
            <ul className="space-y-1">
              {resumeFiles.map((file, index) => (
                <li
                  key={`${file.name}-${index}`}
                  className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/30 rounded-lg px-3 py-1.5"
                >
                  <CheckCircle2 className="w-3 h-3 text-green-500 shrink-0" />
                  <span className="flex-1 truncate">{file.name}</span>
                  {!isPending && (
                    <button
                      type="button"
                      onClick={() => setResumeFiles((prev) => prev.filter((_, i) => i !== index))}
                      className="text-muted-foreground hover:text-red-500 transition-colors"
                      aria-label="Remove resume"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer select-none transition-colors ${
          extractPortfolios ? "bg-teal-50 border-teal-200 dark:bg-teal-950/20 dark:border-teal-800" : "bg-muted/30 border-border"
        } ${isPending ? "opacity-50 pointer-events-none" : ""}`}>
          <input
            type="checkbox"
            checked={extractPortfolios}
            onChange={(e) => setExtractPortfolios(e.target.checked)}
            className="mt-0.5"
          />
          <div>
            <p className="text-sm font-semibold text-foreground flex items-center gap-1.5">
              <Globe className="w-3.5 h-3.5" /> Scrape portfolio links
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Fetches GitHub repos, LinkedIn, and personal sites to detect extra skills.{" "}
              <span className="font-medium text-foreground">Adds ~2–3 min</span> for large batches.
            </p>
          </div>
        </label>

        {/* ── Submit ───────────────────────────────────────────────────── */}
        <button
          onClick={() => mutation.mutate()}
          disabled={isPending || jdFiles.length === 0 || (!cvFile && resumeFiles.length === 0)}
          className="w-full px-4 py-2.5 text-sm font-semibold rounded-lg teal-gradient text-white shadow-teal hover:opacity-90 disabled:opacity-60 transition-opacity flex items-center justify-center gap-2"
        >
          {isPending ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Processing...</>
          ) : jdFiles.length > 1 ? (
            `Process & Rank Across ${jdFiles.length} JDs`
          ) : (
            "Process & Rank Candidates"
          )}
        </button>

        {/* ── Progress UI ───────────────────────────────────────────────── */}
        {isPending && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-foreground">{currentStage?.label}</span>
                <span className="tabular-nums text-muted-foreground">{pct}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-300 ease-out ${barColor}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="text-[11px] text-muted-foreground">{currentStage?.sublabel}</p>
            </div>

            {/* Stage checklist */}
            <div className="rounded-lg bg-muted/40 border divide-y divide-border overflow-hidden">
              {stages.map((s, i) => {
                const done   = i < stageIndex || isDone;
                const active = i === stageIndex && !isDone;
                return (
                  <div
                    key={s.key}
                    className={`flex items-center gap-3 px-3 py-2.5 text-xs transition-colors ${
                      done   ? "text-green-700 bg-green-50/60 dark:text-green-400 dark:bg-green-950/20" :
                      active ? "text-foreground bg-background font-medium" :
                               "text-muted-foreground"
                    }`}
                  >
                    {done ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />
                    ) : active ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
                    ) : (
                      <span className="w-3.5 h-3.5 rounded-full border border-muted-foreground/40 shrink-0 inline-block" />
                    )}
                    <span className="flex-1">{s.label}</span>
                    {/* Show live stats on the ranking stage once complete */}
                    {done && s.key === "ranking" && candidateCount !== null && (
                      <span className="text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded-full">
                        {candidateCount} candidates
                      </span>
                    )}
                    {done && s.key === "ranking" && rmflSteps !== null && (
                      <span className="text-[10px] bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-400 px-1.5 py-0.5 rounded-full">
                        RMFL step {rmflSteps}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>

            {extractPortfolios && stageIndex >= stages.length - 1 && !isDone && (
              <p className="text-[11px] text-muted-foreground text-center">
                Portfolio scraping takes ~2 sec per URL — grab a coffee ☕
              </p>
            )}
          </div>
        )}

        {/* ── Error ────────────────────────────────────────────────────── */}
        {mutation.error && (
          <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 dark:bg-red-950/20 dark:border-red-800 p-3 text-xs text-red-700 dark:text-red-400">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <pre className="whitespace-pre-wrap font-sans">
              {(mutation.error as Error).message}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
