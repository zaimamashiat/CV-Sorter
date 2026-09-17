import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SkillTag } from "./SkillTag";
import { Badge } from "@/components/ui/badge";
import {
  Mail, Phone, ExternalLink, Award, Brain,
  Github, Globe, Linkedin, TrendingUp, Star, BarChart2, AlertTriangle
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { ApiCandidate } from "./RankingTable";
import { CRITERIA_LABELS } from "./RankingTable";

interface CandidateModalProps {
  candidate: ApiCandidate | null;
  jdTitle:   string;
  onClose:   () => void;
}

function PortfolioIcon({ type, className }: { type: string | null; className?: string }) {
  if (type === "github")   return <Github   className={className} />;
  if (type === "linkedin") return <Linkedin className={className} />;
  return <Globe className={className} />;
}

/** Colour-coded bar for a 0-100 score */
function ScoreBar({ score, label, weight }: { score: number; label: string; weight?: number }) {
  const colour =
    score >= 70 ? "bg-green-500" :
    score >= 45 ? "bg-amber-500" :
    "bg-red-400";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-foreground">{label}</span>
        <div className="flex items-center gap-2">
          {weight != null && (
            <span className="text-[10px] text-muted-foreground">
              w={( weight * 100).toFixed(1)}%
            </span>
          )}
          <span className={cn(
            "font-semibold tabular-nums",
            score >= 70 ? "text-green-600 dark:text-green-400" :
            score >= 45 ? "text-amber-600 dark:text-amber-400" :
            "text-red-500"
          )}>
            {score.toFixed(1)}
          </span>
        </div>
      </div>
      <div className="h-2 bg-muted rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", colour)}
          style={{ width: `${Math.min(score, 100)}%` }}
        />
      </div>
    </div>
  );
}

export function CandidateModal({ candidate, jdTitle, onClose }: CandidateModalProps) {
  const hasCriteria = !!(candidate?.criteria_scores && candidate?.criteria_total != null);
  const hasPortfolio = !!candidate?.portfolio_url;

  // Available tabs depend on what data is present
  type Tab = "cv" | "criteria" | "portfolio";
  const availableTabs: Tab[] = [
    "cv",
    ...(hasCriteria  ? (["criteria"]  as Tab[]) : []),
    ...(hasPortfolio ? (["portfolio"] as Tab[]) : []),
  ];
  const [tab, setTab] = useState<Tab>("cv");

  if (!candidate) return null;

  const techMatch = candidate.tech_match_pct     ?? 0;
  const semMatch  = candidate.semantic_match_pct ?? 0;
  const overall   = techMatch * 0.6 + semMatch * 0.4;

  // Parse repos from raw_row if present
  let repos: Array<{
    name: string; description: string; language: string; stars: number; url: string;
  }> = [];
  try {
    const raw = candidate.raw_row?.portfolio_repos;
    if (raw) repos = JSON.parse(raw as string);
  } catch { /* no repos */ }

  const displayName =
    candidate.candidate_name?.trim() ||
    candidate.candidate_email?.trim() ||
    candidate.candidate_id;

  const initials = displayName
    .split(" ")
    .map((n: string) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  const tabLabel: Record<Tab, string> = {
    cv:        "CV / Resume",
    criteria:  "Criteria Scores",
    portfolio: "Portfolio",
  };

  return (
    <Dialog open={!!candidate} onOpenChange={() => onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-3">
            <div className={cn(
              "w-10 h-10 rounded-xl flex items-center justify-center font-bold text-sm shrink-0",
              candidate.rank === 1 ? "bg-amber-100 text-amber-700" :
              candidate.rank === 2 ? "bg-slate-100 text-slate-600" :
              candidate.rank === 3 ? "bg-orange-100 text-orange-700" :
              "bg-primary/10 text-primary"
            )}>
              {initials}
            </div>
            <div className="min-w-0">
              <p className="text-base font-semibold truncate">{displayName}</p>
              <p className="text-xs text-muted-foreground font-normal">
                Ranked #{candidate.rank} for {jdTitle}
              </p>
            </div>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-5 pt-2">

          {/* ── Contact row ──────────────────────────────────────────────── */}
          <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
            {candidate.candidate_email && (
              <span className="flex items-center gap-1.5">
                <Mail className="w-3.5 h-3.5" /> {candidate.candidate_email}
              </span>
            )}
            {candidate.candidate_phone && (
              <span className="flex items-center gap-1.5">
                <Phone className="w-3.5 h-3.5" /> {candidate.candidate_phone}
              </span>
            )}
            {candidate.portfolio_url && (
              <a
                href={candidate.portfolio_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-primary hover:underline"
              >
                <PortfolioIcon type={candidate.portfolio_type} className="w-3.5 h-3.5" />
                {candidate.portfolio_type
                  ? candidate.portfolio_type.charAt(0).toUpperCase() + candidate.portfolio_type.slice(1)
                  : "Portfolio"}
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>

          {/* ── Category ─────────────────────────────────────────────────── */}
          <div className="flex items-center gap-3">
            <Badge variant="secondary" className="flex items-center gap-1.5">
              <Brain className="w-3 h-3" /> {candidate.category}
            </Badge>
            <span className="text-xs text-muted-foreground">
              Confidence: {((candidate.category_confidence ?? 0) * 100).toFixed(1)}%
            </span>
          </div>

          {/* ── Score cards ───────────────────────────────────────────────── */}
          <div className={cn("grid gap-3", hasCriteria ? "grid-cols-4" : "grid-cols-3")}>
            {[
              { label: "Tech Match",     score: techMatch, icon: "⚙️" },
              { label: "Semantic Match", score: semMatch,  icon: "🧠" },
              { label: "Overall Score",  score: overall,   icon: "🏆" },
              ...(hasCriteria
                ? [{ label: "Criteria Score", score: candidate.criteria_total!, icon: "📊" }]
                : []),
            ].map(({ label, score, icon }) => (
              <div key={label} className="rounded-xl border bg-muted/30 p-4 text-center">
                <div className="text-xl mb-1">{icon}</div>
                <p className="text-2xl font-bold text-foreground">
                  {score.toFixed(1)}
                  <span className="text-sm font-normal text-muted-foreground">%</span>
                </p>
                <p className="text-xs text-muted-foreground mt-1">{label}</p>
                <div className="mt-2 h-1.5 bg-muted rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      score >= 75 ? "bg-green-500" : score >= 50 ? "bg-amber-500" : "bg-red-500"
                    }`}
                    style={{ width: `${Math.min(score, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>

          {/* ── Tabs ─────────────────────────────────────────────────────── */}
          {availableTabs.length > 1 && (
            <div className="flex gap-1 p-1 bg-muted/40 rounded-xl w-fit">
              {availableTabs.map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={cn(
                    "flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium rounded-lg transition-colors",
                    tab === t
                      ? "bg-background shadow-sm text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {t === "criteria" && <BarChart2 className="w-3.5 h-3.5" />}
                  {tabLabel[t]}
                </button>
              ))}
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════
              CV TAB
          ══════════════════════════════════════════════════════════════ */}
          {tab === "cv" && (
            <div className="space-y-4">
              {(candidate.matched_skills ?? []).length > 0 && (
                <div>
                  <p className="text-sm font-semibold text-foreground mb-2 flex items-center gap-2">
                    <Award className="w-4 h-4 text-green-500" />
                    Matched Skills ({candidate.matched_skills.length})
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {candidate.matched_skills.map((s) => (
                      <SkillTag key={s} skill={s} matched />
                    ))}
                  </div>
                </div>
              )}

              {(candidate.missing_skills ?? []).length > 0 && (
                <div>
                  <p className="text-sm font-semibold text-foreground mb-2 flex items-center gap-2">
                    <Award className="w-4 h-4 text-red-500" />
                    Missing Skills ({candidate.missing_skills.length})
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {candidate.missing_skills.map((s) => (
                      <SkillTag key={s} skill={s} matched={false} />
                    ))}
                  </div>
                </div>
              )}

              {candidate.cv_text && (
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">
                    Resume Preview
                  </p>
                  <p className="text-xs text-muted-foreground leading-relaxed bg-muted/20 rounded-lg p-3 whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {candidate.cv_text}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════
              CRITERIA TAB  (RMFL breakdown)
          ══════════════════════════════════════════════════════════════ */}
          {tab === "criteria" && hasCriteria && (
            <div className="space-y-5">

              {/* Summary row */}
              <div className="flex items-center justify-between rounded-xl border bg-muted/20 px-4 py-3">
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    RMFL Weighted Total
                  </p>
                  <p className={cn(
                    "text-2xl font-bold mt-0.5",
                    (candidate.criteria_total ?? 0) >= 70 ? "text-green-600 dark:text-green-400" :
                    (candidate.criteria_total ?? 0) >= 45 ? "text-amber-600 dark:text-amber-400" :
                    "text-red-500"
                  )}>
                    {candidate.criteria_total!.toFixed(2)}
                    <span className="text-sm font-normal text-muted-foreground ml-1">/ 100</span>
                  </p>
                </div>
                {candidate.weight_entropy != null && (
                  <div className="text-right">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                      Weight Entropy
                    </p>
                    <p className="text-sm font-semibold text-foreground mt-0.5">
                      {candidate.weight_entropy.toFixed(3)}
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      (higher = more uniform)
                    </p>
                  </div>
                )}
              </div>

              {/* Per-criterion score bars */}
              <div className="space-y-3">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Criterion Breakdown
                </p>
                {Object.entries(candidate.criteria_scores ?? {}).map(([key, rawScore]) => {
                  const breakdown = candidate.criteria_breakdown?.[key];
                  const weight    = breakdown?.learned_weight ?? candidate.learned_weights?.[key];
                  return (
                    <ScoreBar
                      key={key}
                      label={CRITERIA_LABELS[key] ?? key}
                      score={rawScore}
                      weight={weight}
                    />
                  );
                })}
              </div>

              {/* Learned weights pill grid */}
              {candidate.learned_weights && (
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                    Learned Weights (RMFL Policy)
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(candidate.learned_weights)
                      .sort(([, a], [, b]) => b - a)
                      .map(([key, w]) => (
                        <span
                          key={key}
                          className={cn(
                            "px-2.5 py-1 rounded-full text-[11px] font-semibold border",
                            w >= 0.15
                              ? "bg-primary/10 border-primary/30 text-primary"
                              : "bg-muted border-border text-muted-foreground"
                          )}
                        >
                          {CRITERIA_LABELS[key] ?? key}: {(w * 100).toFixed(1)}%
                        </span>
                      ))}
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-2">
                    Weights learned by the RMFL Dirichlet policy for this job role context. Highlighted pills (≥15%) are the dominant criteria.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════════
              PORTFOLIO TAB
          ══════════════════════════════════════════════════════════════ */}
          {tab === "portfolio" && hasPortfolio && (
            <div className="space-y-4">

              {/* URL header */}
              <div className="flex items-center justify-between rounded-xl border bg-muted/20 px-4 py-3">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                    <PortfolioIcon type={candidate.portfolio_type} className="w-4 h-4 text-primary" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold capitalize">
                      {candidate.portfolio_type ?? "Portfolio"}
                    </p>
                    <p className="text-xs text-muted-foreground truncate max-w-[300px]">
                      {candidate.portfolio_url}
                    </p>
                  </div>
                </div>
                <a
                  href={candidate.portfolio_url!}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                >
                  Open <ExternalLink className="w-3 h-3" />
                </a>
              </div>

              {!candidate.portfolio_summary && (candidate.portfolio_skills?.length ?? 0) === 0 && (
                <div className="rounded-xl border border-red-200 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950/30">
                  <p className="flex items-center gap-2 text-sm font-semibold text-red-700 dark:text-red-300">
                    <AlertTriangle className="w-4 h-4" />
                    Empty portfolio output — human review required
                  </p>
                  <p className="mt-1.5 text-xs text-red-700/80 dark:text-red-300/80">
                    {candidate.portfolio_error ||
                      "The portfolio URL was available, but no summary or technical skills could be extracted. Open the original link above to review it manually."}
                  </p>
                </div>
              )}

              {candidate.portfolio_summary && (
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                    Summary
                  </p>
                  <p className="text-sm text-foreground leading-relaxed bg-muted/20 rounded-lg p-3">
                    {candidate.portfolio_summary}
                  </p>
                </div>
              )}

              {(candidate.portfolio_skills ?? []).length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2 flex items-center gap-1.5">
                    <TrendingUp className="w-3.5 h-3.5" /> Skills Detected
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {candidate.portfolio_skills!.map((s) => (
                      <SkillTag key={s} skill={s} matched size="sm" />
                    ))}
                  </div>
                </div>
              )}

              {repos.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2 flex items-center gap-1.5">
                    <Github className="w-3.5 h-3.5" /> Repositories
                  </p>
                  <div className="space-y-2">
                    {repos.map((repo, idx) => (
                      <div
                        key={idx}
                        className="flex items-start justify-between rounded-lg border bg-muted/10 px-3 py-2.5 gap-3"
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium">{repo.name}</span>
                            {repo.language && (
                              <span className="text-[11px] bg-muted px-2 py-0.5 rounded-full">
                                {repo.language}
                              </span>
                            )}
                            {repo.stars > 0 && (
                              <span className="flex items-center gap-0.5 text-[11px] text-amber-500">
                                <Star className="w-3 h-3 fill-amber-400 stroke-amber-400" />
                                {repo.stars}
                              </span>
                            )}
                          </div>
                          {repo.description && (
                            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                              {repo.description}
                            </p>
                          )}
                        </div>
                        {repo.url && (
                          <a
                            href={repo.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="shrink-0 text-primary hover:opacity-70"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {candidate.portfolio_type === "linkedin" && (
                <div className="rounded-xl border bg-blue-50/50 dark:bg-blue-950/20 p-4">
                  <p className="flex items-center gap-2 text-sm font-medium text-foreground mb-1">
                    <Linkedin className="w-4 h-4 text-blue-600" /> LinkedIn Profile
                  </p>
                  <p className="text-xs text-muted-foreground">
                    LinkedIn restricts automated scraping. Visit the profile directly for full details.
                  </p>
                  <a
                    href={candidate.portfolio_url!}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 mt-2 text-xs text-blue-600 font-medium hover:underline"
                  >
                    Open profile <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              )}
            </div>
          )}

        </div>
      </DialogContent>
    </Dialog>
  );
}
