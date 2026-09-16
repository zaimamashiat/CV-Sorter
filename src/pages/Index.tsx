import { useMemo, useState, useEffect } from "react";

// ── Tiny localStorage hook ────────────────────────────────────────────────────
function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key);
      return stored ? (JSON.parse(stored) as T) : initialValue;
    } catch {
      return initialValue;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      console.warn(`localStorage write failed for key "${key}":`, e);
    }
  }, [key, value]);

  return [value, setValue] as const;
}

import heroBg from "@/assets/hero-bg.jpg";
import { Sidebar } from "@/components/Sidebar";
import { StatsCards } from "@/components/StatsCards";
import { JDCard } from "@/components/JDCard";
import { RankingTable } from "@/components/RankingTable";
import { AnalyticsView } from "@/components/AnalyticsView";
import { UploadView } from "@/components/UploadView";
import { AtsConverterView } from "@/components/AtsConverterView";
import { Bell, Search, Download, Trash2 } from "lucide-react";
import type { ApiCVRankEntry, UIJD, UICandidate } from "@/lib/types";

type View = "dashboard" | "jds" | "candidates" | "analytics" | "upload" | "ats" | "settings";

function mapApiCandidatesToTable(
  entries: ApiCVRankEntry[],
  areaOfInterestMap: Record<string, string> = {}
): UICandidate[] {
  return entries.map((e) => {
    const displayName =
      e.candidate_name?.trim() ||
      e.candidate_email?.trim() ||
      e.candidate_id;

    const aoiKey = e.candidate_email?.trim() || e.candidate_id;
    const area_of_interest =
      areaOfInterestMap[aoiKey] ??
      areaOfInterestMap[e.candidate_id] ??
      (e as any).area_of_interest ??
      "";

    return {
      ...e,
      id: e.candidate_id,
      name: displayName,
      email: e.candidate_email || "",
      area_of_interest,
      // RMFL fields — pass through as-is from API response
      criteria_scores:    e.criteria_scores    ?? null,
      learned_weights:    e.learned_weights    ?? null,
      criteria_breakdown: e.criteria_breakdown ?? null,
      criteria_total:     e.criteria_total     ?? null,
      weight_entropy:     e.weight_entropy     ?? null,
    };
  });
}

function pickField(
  obj: Record<string, unknown>,
  keys: string[],
  fallback = ""
): string {
  for (const k of keys) {
    const v = obj?.[k];
    if (v !== undefined && v !== null && String(v).trim() !== "") {
      return String(v).trim();
    }
  }
  return fallback;
}

function resolveDisplayName(c: UICandidate): string {
  if (c.candidate_name?.trim()) return c.candidate_name.trim();
  if (c.name?.trim() && c.name.trim() !== (c.candidate_email ?? "").trim()) return c.name.trim();
  if (c.raw_row) {
    const nameKeys = ["Name", "name", "Full Name", "full_name", "FullName", "candidate_name"];
    for (const k of nameKeys) {
      const v = (c.raw_row as Record<string, string>)[k]?.trim();
      if (v) return v;
    }
  }
  if (c.candidate_email?.trim()) {
    const local = c.candidate_email.split("@")[0];
    return local.replace(/[._-]/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
  }
  return c.candidate_id;
}

/**
 * Download candidates as CSV — includes RMFL criteria_total column.
 */
function downloadCandidatesCSV(candidates: UICandidate[], jdTitle: string) {
  const hasAoi      = candidates.some((c) => (c as any).area_of_interest);
  const hasCriteria = candidates.some((c) => c.criteria_total != null);

  const headers = [
    "Rank", "Name", "Email",
    ...(hasAoi ? ["Area of Interest"] : []),
    "Category",
    "Tech Match (%)", "Semantic Match (%)",
    ...(hasCriteria ? ["Criteria Total (RMFL)"] : []),
    "Matched Skills", "Missing Skills", "Portfolio URL",
  ];

  const escape = (val: unknown) => {
    const str = val === null || val === undefined ? "" : String(val);
    return str.includes(",") || str.includes('"') || str.includes("\n")
      ? `"${str.replace(/"/g, '""')}"`
      : str;
  };

  const rows = candidates.map((c) => [
    escape(c.rank),
    escape(resolveDisplayName(c)),
    escape(c.candidate_email ?? c.email ?? ""),
    ...(hasAoi ? [escape((c as any).area_of_interest ?? "")] : []),
    escape(c.category),
    escape(c.tech_match_pct),
    escape(c.semantic_match_pct),
    ...(hasCriteria ? [escape(c.criteria_total?.toFixed(2) ?? "")] : []),
    escape((c.matched_skills ?? []).join("; ")),
    escape((c.missing_skills ?? []).join("; ")),
    escape(c.portfolio_url ?? ""),
  ]);

  const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href  = url;
  const safeName = jdTitle.replace(/[^a-z0-9]/gi, "_").toLowerCase() || "rankings";
  link.download  = `${safeName}_rankings.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Build analytics-compatible object from stored state.
 * Now forwards RMFL fields (criteria_scores, learned_weights, criteria_total)
 * so AnalyticsView can render the criteria breakdown chart.
 */
function buildAnalyticsData(
  jds: UIJD[],
  candidatesByJd: Record<string, UICandidate[]>,
  selectedJD: UIJD | null
) {
  const allCandidates = selectedJD
    ? (candidatesByJd[selectedJD.id] ?? [])
    : Object.values(candidatesByJd).flat();

  if (!allCandidates.length) return null;

  const techSource = selectedJD ?? jds[0];
  const jd_skills  = techSource?.Technology
    ? techSource.Technology.split(",").map((s) => s.trim()).filter(Boolean)
    : [];

  const rankings = allCandidates.map((c) => ({
    rank:                c.rank ?? 0,
    candidate_id:        c.candidate_id,
    candidate_name:      resolveDisplayName(c),
    candidate_email:     c.candidate_email ?? c.email ?? "",
    category:            c.category ?? "Unknown",
    category_confidence: c.category_confidence ?? 0,
    semantic_match_pct:  c.semantic_match_pct ?? 0,
    tech_match_pct:      c.tech_match_pct ?? 0,
    matched_skills:      c.matched_skills ?? [],
    missing_skills:      c.missing_skills ?? [],
    portfolio_url:       c.portfolio_url,
    portfolio_type:      c.portfolio_type,
    portfolio_summary:   c.portfolio_summary,
    portfolio_skills:    c.portfolio_skills,
    // ── RMFL fields forwarded to AnalyticsView ──────────────────────────
    criteria_scores:     c.criteria_scores    ?? null,
    learned_weights:     c.learned_weights    ?? null,
    criteria_breakdown:  c.criteria_breakdown ?? null,
    criteria_total:      c.criteria_total     ?? null,
    weight_entropy:      c.weight_entropy     ?? null,
  }));

  const portfolios_scraped = rankings.filter((r) => r.portfolio_url).length;

  return {
    jd_title:           selectedJD?.Job_Title ?? (jds.length > 1 ? "All JDs" : jds[0]?.Job_Title),
    jd_skills,
    total_candidates:   rankings.length,
    portfolios_scraped,
    semantic_weight:    0.5,
    tech_weight:        0.5,
    rankings,
  };
}

export default function Index() {
  const [activeView, setActiveView] = useState<View>("dashboard");

  const [jds, setJDs] = useLocalStorage<UIJD[]>("cv_pipeline_jds", []);
  const [candidatesByJd, setCandidatesByJd] = useLocalStorage<Record<string, UICandidate[]>>(
    "cv_pipeline_candidates",
    {}
  );

  const [selectedJdId, setSelectedJdId] = useState<string | null>(() => {
    try {
      const stored     = localStorage.getItem("cv_pipeline_jds");
      const storedJds: UIJD[] = stored ? JSON.parse(stored) : [];
      return storedJds[0]?.id ?? null;
    } catch {
      return null;
    }
  });
  const [searchQuery, setSearchQuery] = useState("");

  const selectedJD = useMemo(() => {
    if (!jds.length) return null;
    if (selectedJdId) {
      const found = jds.find((j) => j.id === selectedJdId);
      if (found) return found;
      setSelectedJdId(jds[0].id);
      return jds[0];
    }
    return jds[0];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jds, selectedJdId]);

  const allCandidates = useMemo(() => {
    const id = selectedJdId ?? selectedJD?.id;
    return id ? (candidatesByJd[id] ?? []) : [];
  }, [selectedJdId, selectedJD, candidatesByJd]);

  const candidates = useMemo(() => {
    if (!searchQuery.trim()) return allCandidates;
    const q = searchQuery.toLowerCase();
    return allCandidates.filter(
      (c) =>
        c.name?.toLowerCase().includes(q) ||
        c.email?.toLowerCase().includes(q) ||
        c.candidate_id?.toLowerCase().includes(q) ||
        c.category?.toLowerCase().includes(q)
    );
  }, [allCandidates, searchQuery]);

  const allCandidatesFlat = useMemo(() => Object.values(candidatesByJd).flat(), [candidatesByJd]);
  const totalCandidates   = allCandidatesFlat.length;
  const avgTechMatch      = totalCandidates > 0
    ? allCandidatesFlat.reduce((s, c) => s + (c.tech_match_pct ?? 0), 0) / totalCandidates
    : 0;
  const topMatchPct       = totalCandidates > 0
    ? Math.max(...allCandidatesFlat.map((c) => c.tech_match_pct ?? 0))
    : 0;
  const shortlisted       = allCandidatesFlat.filter((c) => (c.tech_match_pct ?? 0) >= 70).length;
  const portfoliosScraped = allCandidatesFlat.filter((c) => c.portfolio_url).length;

  // Average RMFL criteria total across all candidates (shown in hero banner)
  const avgCriteriaTotal = useMemo(() => {
    const withCriteria = allCandidatesFlat.filter((c) => c.criteria_total != null);
    if (!withCriteria.length) return null;
    return withCriteria.reduce((s, c) => s + (c.criteria_total ?? 0), 0) / withCriteria.length;
  }, [allCandidatesFlat]);

  const analyticsData = useMemo(
    () => buildAnalyticsData(jds, candidatesByJd, selectedJD),
    [jds, candidatesByJd, selectedJD]
  );

  const handleDeleteCandidate = (jdId: string, candidateId: string) => {
    setCandidatesByJd((prev) => ({
      ...prev,
      [jdId]: (prev[jdId] ?? []).filter((c) => c.candidate_id !== candidateId),
    }));
  };

  const handleDeleteJD = (jdId: string) => {
    setJDs((prev) => prev.filter((j) => j.id !== jdId));
    setCandidatesByJd((prev) => {
      const next = { ...prev };
      delete next[jdId];
      return next;
    });
    if (selectedJdId === jdId) setSelectedJdId(null);
  };

  const handleDeleteRanking = (jdId: string) => {
    const ok = window.confirm(
      "Delete all ranked candidates for this Job Description?\n\nThis will clear the entire ranking list, but keep the JD."
    );
    if (!ok) return;
    setCandidatesByJd((prev) => ({ ...prev, [jdId]: [] }));
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar activeView={activeView} onNavigate={(v) => setActiveView(v as View)} />

      <main className="flex-1 overflow-y-auto">
        {/* ── Top bar ──────────────────────────────────────────────────────── */}
        <header className="sticky top-0 z-10 bg-background/95 backdrop-blur border-b border-border px-6 py-3 flex items-center gap-4">
          <div className="flex-1 relative max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search candidates, JDs..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border bg-muted/30 focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <button className="relative p-2 rounded-lg hover:bg-muted transition-colors">
            <Bell className="w-4 h-4 text-muted-foreground" />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-teal" />
          </button>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-primary-foreground text-xs font-semibold">
              HR
            </div>
            <div className="hidden sm:block">
              <p className="text-xs font-semibold text-foreground">HR Manager</p>
              <p className="text-[10px] text-muted-foreground">Admin</p>
            </div>
          </div>
        </header>

        <div className="p-6 space-y-6">
          {/* ══════════════════════════════════════════════════════════════════
              DASHBOARD VIEW
          ══════════════════════════════════════════════════════════════════ */}
          {activeView === "dashboard" && (
            <>
              {/* Hero Banner */}
              <div
                className="relative rounded-2xl overflow-hidden h-44 flex items-end p-6"
                style={{
                  backgroundImage: `url(${heroBg})`,
                  backgroundSize: "cover",
                  backgroundPosition: "center 30%",
                }}
              >
                <div
                  className="absolute inset-0"
                  style={{
                    background:
                      "linear-gradient(105deg, hsl(224,64%,14%) 45%, hsl(224,64%,14%,0.6) 70%, hsl(224,64%,14%,0.1) 100%)",
                  }}
                />
                <div className="relative z-10">
                  <h1 className="text-2xl font-bold text-white tracking-tight">
                    CV Screening Pipeline
                  </h1>
                  <p className="text-sm text-white/70 mt-1">
                    AI-powered talent ranking — BERT · SBERT · Fuzzy Matching · LLaMA · RMFL
                  </p>
                  <div className="flex items-center gap-4 mt-3">
                    {[
                      `${totalCandidates} Candidates`,
                      `${jds.length} Job Descriptions`,
                      topMatchPct > 0 ? `${topMatchPct}% Top Tech Match` : "—",
                      avgCriteriaTotal != null
                        ? `${avgCriteriaTotal.toFixed(1)} Avg Criteria Score`
                        : null,
                    ]
                      .filter(Boolean)
                      .map((tag) => (
                        <span
                          key={tag as string}
                          className="px-2 py-0.5 rounded-full bg-white/10 border border-white/20 text-xs text-white/80 font-medium"
                        >
                          {tag}
                        </span>
                      ))}
                  </div>
                </div>
              </div>

              <StatsCards
                totalJDs={jds.length}
                totalCandidates={totalCandidates}
                avgTechMatch={avgTechMatch}
                topMatchScore={topMatchPct}
                shortlisted={shortlisted}
                portfoliosScraped={portfoliosScraped}
              />

              <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
                {/* ── JD List ─────────────────────────────────────────────── */}
                <div className="xl:col-span-1 space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-foreground">Job Descriptions</h2>
                    <button
                      onClick={() => setActiveView("upload")}
                      className="text-xs text-teal font-medium hover:underline"
                    >
                      + Upload JD
                    </button>
                  </div>

                  {jds.length === 0 ? (
                    <div className="rounded-xl border bg-card shadow-card p-6 text-center space-y-2">
                      <p className="text-sm font-medium text-foreground">No JDs yet</p>
                      <p className="text-xs text-muted-foreground">
                        Click{" "}
                        <button
                          onClick={() => setActiveView("upload")}
                          className="font-semibold text-teal hover:underline"
                        >
                          Upload JD
                        </button>{" "}
                        to upload a Job Description PDF and a Candidates CSV to start ranking.
                      </p>
                    </div>
                  ) : (
                    jds.map((jd) => (
                      <JDCard
                        key={jd.id}
                        jd={jd as any}
                        isSelected={selectedJD?.id === jd.id}
                        onSelect={() => setSelectedJdId(jd.id)}
                        onDelete={() => handleDeleteJD(jd.id)}
                        candidateCount={candidatesByJd[jd.id]?.length ?? 0}
                      />
                    ))
                  )}
                </div>

                {/* ── Rankings Panel ──────────────────────────────────────── */}
                <div className="xl:col-span-3 space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-sm font-semibold text-foreground">
                        Rankings —{" "}
                        {selectedJD?.Job_Title ?? (
                          <span className="text-muted-foreground">No JD selected</span>
                        )}
                      </h2>
                      <p className="text-xs text-muted-foreground">
                        {selectedJD
                          ? `${selectedJD.Company} · ${selectedJD.Location}`
                          : "Upload a JD + CSV to view ranked candidates."}
                      </p>
                    </div>

                    <div className="flex items-center gap-3">
                      {candidates.length > 0 && (
                        <span className="text-xs text-muted-foreground">
                          {candidates.length} candidate{candidates.length !== 1 ? "s" : ""}
                          {searchQuery && " (filtered)"}
                        </span>
                      )}

                      {selectedJD && (candidatesByJd[selectedJD.id]?.length ?? 0) > 0 && (
                        <button
                          onClick={() => handleDeleteRanking(selectedJD.id)}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-border bg-card hover:bg-muted transition-colors"
                        >
                          <Trash2 className="w-3.5 h-3.5 text-destructive" />
                          <span className="text-destructive">Clear Ranking</span>
                        </button>
                      )}

                      {candidates.length > 0 && selectedJD && (
                        <button
                          onClick={() => downloadCandidatesCSV(candidates as any, selectedJD.Job_Title)}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-border bg-card hover:bg-muted transition-colors"
                        >
                          <Download className="w-3.5 h-3.5" />
                          Export CSV
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Required Tech Skills */}
                  <div className="rounded-xl border bg-card shadow-card p-4">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                      Required Tech Skills
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {(selectedJD?.Technology ?? "")
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean)
                        .map((skill) => (
                          <span
                            key={skill}
                            className="px-2 py-0.5 rounded-full bg-primary/8 border border-primary/20 text-xs font-medium text-primary"
                          >
                            {skill}
                          </span>
                        ))}
                      {!selectedJD?.Technology && (
                        <span className="text-xs text-muted-foreground">
                          No extracted tech skills yet.
                        </span>
                      )}
                    </div>
                  </div>

                  <RankingTable
                    key={selectedJD?.id ?? "no-jd"}
                    candidates={candidates as any}
                    jdTitle={selectedJD?.Job_Title ?? ""}
                    onDelete={selectedJD ? (id) => handleDeleteCandidate(selectedJD.id, id) : undefined}
                  />
                </div>
              </div>
            </>
          )}

          {/* ══════════════════════════════════════════════════════════════════
              JDs VIEW
          ══════════════════════════════════════════════════════════════════ */}
          {activeView === "jds" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-foreground">Job Descriptions</h2>
                  <p className="text-sm text-muted-foreground">
                    {jds.length} JD{jds.length !== 1 ? "s" : ""} processed
                  </p>
                </div>
                <button
                  onClick={() => setActiveView("upload")}
                  className="px-4 py-2 text-xs font-semibold rounded-lg teal-gradient text-white shadow-teal hover:opacity-90 transition-opacity"
                >
                  + Upload New JD
                </button>
              </div>

              {jds.length === 0 ? (
                <div className="rounded-xl border bg-card shadow-card p-8 text-center space-y-3">
                  <p className="text-base font-semibold text-foreground">No Job Descriptions yet</p>
                  <p className="text-sm text-muted-foreground max-w-sm mx-auto">
                    Upload a JD PDF and a Candidates CSV to begin AI-powered screening.
                  </p>
                  <button
                    onClick={() => setActiveView("upload")}
                    className="px-4 py-2 text-sm font-semibold rounded-lg teal-gradient text-white shadow-teal hover:opacity-90 transition-opacity"
                  >
                    Upload JD + CSV
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  {jds.map((jd) => (
                    <JDCard
                      key={jd.id}
                      jd={jd as any}
                      isSelected={selectedJD?.id === jd.id}
                      onSelect={() => {
                        setSelectedJdId(jd.id);
                        setActiveView("candidates");
                      }}
                      onDelete={() => handleDeleteJD(jd.id)}
                      candidateCount={candidatesByJd[jd.id]?.length ?? 0}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════════
              CANDIDATES VIEW
          ══════════════════════════════════════════════════════════════════ */}
          {activeView === "candidates" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-foreground">Candidate Rankings</h2>
                  <p className="text-sm text-muted-foreground">
                    {selectedJD
                      ? `Showing ${candidates.length} candidate${candidates.length !== 1 ? "s" : ""} for ${selectedJD.Job_Title}`
                      : "Select a JD below to view ranked candidates"}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  {selectedJD && (candidatesByJd[selectedJD.id]?.length ?? 0) > 0 && (
                    <button
                      onClick={() => handleDeleteRanking(selectedJD.id)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-border bg-card hover:bg-muted transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5 text-destructive" />
                      <span className="text-destructive">Clear Ranking</span>
                    </button>
                  )}

                  {candidates.length > 0 && selectedJD && (
                    <button
                      onClick={() => downloadCandidatesCSV(candidates as any, selectedJD.Job_Title)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-border bg-card hover:bg-muted transition-colors"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Export CSV
                    </button>
                  )}
                </div>
              </div>

              {/* JD Filter Pills */}
              {jds.length > 0 && (
                <div className="flex gap-2 flex-wrap">
                  {jds.map((jd) => (
                    <button
                      key={jd.id}
                      onClick={() => { setSelectedJdId(jd.id); setSearchQuery(""); }}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                        selectedJD?.id === jd.id
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground hover:bg-muted/80"
                      }`}
                    >
                      {jd.Job_Title}
                      <span className="ml-1.5 opacity-60">
                        ({candidatesByJd[jd.id]?.length ?? 0})
                      </span>
                    </button>
                  ))}
                </div>
              )}

              <RankingTable
                key={selectedJD?.id ?? "no-jd"}
                candidates={candidates as any}
                jdTitle={selectedJD?.Job_Title ?? ""}
                onDelete={selectedJD ? (id) => handleDeleteCandidate(selectedJD.id, id) : undefined}
              />
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════════
              ANALYTICS VIEW
          ══════════════════════════════════════════════════════════════════ */}
          {activeView === "analytics" && (
            <div className="space-y-4">
              {jds.length > 1 && (
                <div className="flex gap-2 flex-wrap">
                  {jds.map((jd) => (
                    <button
                      key={jd.id}
                      onClick={() => setSelectedJdId(jd.id)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                        selectedJD?.id === jd.id
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground hover:bg-muted/80"
                      }`}
                    >
                      {jd.Job_Title}
                      <span className="ml-1.5 opacity-60">
                        ({candidatesByJd[jd.id]?.length ?? 0})
                      </span>
                    </button>
                  ))}
                </div>
              )}

              <AnalyticsView rankingData={analyticsData ?? undefined} />
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════════
              UPLOAD VIEW
          ══════════════════════════════════════════════════════════════════ */}
          {activeView === "upload" && (
            <UploadView
              onCancel={() => setActiveView("dashboard")}
              onSubmit={({ jdFiles, jdExtractedList, ranking, areaOfInterestMap }) => {
                const mappedCandidates = mapApiCandidatesToTable(
                  ranking.rankings,
                  areaOfInterestMap
                );

                const newJDs: UIJD[] = jdExtractedList.map(({ extracted }) => {
                  const id = crypto.randomUUID();
                  const Job_Title  = pickField(extracted as Record<string, unknown>,
                    ["Job_Title","JobTitle","job_title","title"], "Untitled JD");
                  const Company    = pickField(extracted as Record<string, unknown>,
                    ["Company","company","organisation","organization"], "");
                  const Location   = pickField(extracted as Record<string, unknown>,
                    ["Location","location","city","country"], "");
                  const Technology = pickField(extracted as Record<string, unknown>,
                    ["Technology","technologies","Technical Skills","Technical_Skills",
                     "tech_skills","Required_Skills","Skills","skills"], "");
                  return { id, Job_Title, Company, Location, Technology };
                });

                setJDs((prev) => [...newJDs, ...prev]);

                setCandidatesByJd((prev) => {
                  const next = { ...prev };
                  for (const jd of newJDs) {
                    next[jd.id] = mappedCandidates;
                  }
                  return next;
                });

                setSelectedJdId(newJDs[0]?.id ?? null);
                setActiveView("dashboard");
              }}
            />
          )}

          {/* ══════════════════════════════════════════════════════════════════
              SETTINGS VIEW
          ══════════════════════════════════════════════════════════════════ */}
          {activeView === "ats" && <AtsConverterView />}

          {activeView === "settings" && (
            <div className="space-y-4 max-w-xl">
              <h2 className="text-xl font-bold text-foreground">Settings</h2>
              <div className="rounded-xl border bg-card shadow-card p-5 space-y-4">
                <p className="text-sm text-muted-foreground">
                  Configure your CV screening pipeline preferences.
                </p>
                <button className="px-4 py-2 text-sm font-semibold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
                  Save Settings
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
