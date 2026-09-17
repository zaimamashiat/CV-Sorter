import { useState } from "react";
import { ScoreBadge } from "./ScoreBadge";
import { SkillTag } from "./SkillTag";
import { CandidateModal } from "./CandidateModal";
import { Badge } from "@/components/ui/badge";
import { ChevronUp, ChevronDown, ExternalLink, Eye, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

// ── RMFL criterion breakdown entry ───────────────────────────────────────────
export interface CriterionBreakdown {
  learned_weight: number;
  raw_score:      number;
  contribution:   number;
}

// ── API response shape from /rank-cvs ────────────────────────────────────────
export interface ApiCandidate {
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
  matched_skills:       string[];
  missing_skills:       string[];
  portfolio_url:        string | null;
  portfolio_type:       string | null;
  portfolio_summary:    string | null;
  portfolio_skills:     string[] | null;
  portfolio_status:     "generated" | "empty" | "not_processed" | "not_provided";
  portfolio_error:      string | null;
  // ── RMFL fields ────────────────────────────────────────────────────────────
  criteria_scores:      Record<string, number>              | null;
  learned_weights:      Record<string, number>              | null;
  criteria_breakdown:   Record<string, CriterionBreakdown>  | null;
  criteria_total:       number | null;
  weight_entropy:       number | null;
  // ── UI aliases ─────────────────────────────────────────────────────────────
  id?:    string;
  name?:  string;
  email?: string;
  phone?: string;
}

type SortKey = "rank" | "tech_match_pct" | "semantic_match_pct" | "criteria_total";

interface RankingTableProps {
  candidates: ApiCandidate[];
  jdTitle:    string;
  onDelete?:  (candidateId: string) => void;
}

// Human-readable labels for the 9 RMFL criteria keys
const CRITERIA_LABELS: Record<string, string> = {
  relevant_background:    "Background",
  results_achievements:   "Results",
  relevant_courses:       "Courses",
  training_certification: "Certifications",
  relevant_skills:        "Skills",
  work_experience:        "Experience",
  projects_coursework:    "Projects",
  thesis_publications:    "Thesis / Research",
  portfolio:              "Portfolio",
};

export function RankingTable({ candidates, jdTitle, onDelete }: RankingTableProps) {
  const [sortKey, setSortKey]     = useState<SortKey>("rank");
  const [sortAsc, setSortAsc]     = useState(true);
  const [selected, setSelected]   = useState<ApiCandidate | null>(null);
  const [filter, setFilter]       = useState("");
  const [localList, setLocalList] = useState<ApiCandidate[]>(candidates);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  // Whether ANY candidate in the list has RMFL data — controls column visibility
  const hasCriteriaData = localList.some((c) => c.criteria_total != null);

  const portfolioStatus = (c: ApiCandidate) => {
    if (c.portfolio_status) return c.portfolio_status;
    if (!c.portfolio_url) return "not_provided";
    return c.portfolio_summary || (c.portfolio_skills?.length ?? 0) > 0
      ? "generated"
      : "empty";
  };

  const portfolioStatusView = (c: ApiCandidate) => {
    const status = portfolioStatus(c);
    if (status === "generated") return { label: "Generated", className: "border-green-200 bg-green-50 text-green-700 dark:border-green-900 dark:bg-green-950/40 dark:text-green-300" };
    if (status === "empty") return { label: "Empty — Review", className: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300" };
    if (status === "not_processed") return { label: "Not processed", className: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300" };
    return { label: "Not provided", className: "border-border bg-muted/40 text-muted-foreground" };
  };

  const displayName = (c: ApiCandidate) => {
    if (c.candidate_name?.trim()) return c.candidate_name.trim();
    if (c.name?.trim() && c.name.trim() !== (c.candidate_email ?? "").trim()) return c.name.trim();
    if (c.raw_row) {
      const nameKeys = ["Full Name ", "Full Name", "Name", "name", "full_name", "FullName", "candidate_name"];
      for (const k of nameKeys) {
        const v = c.raw_row[k]?.trim();
        if (v) return v;
      }
    }
    if (c.candidate_email?.trim()) {
      const local = c.candidate_email.split("@")[0];
      return local.replace(/[._-]/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
    }
    return c.candidate_id;
  };

  const displayAreaOfInterest = (c: ApiCandidate): string | null => {
    if (c.area_of_interest?.trim()) return c.area_of_interest.trim();
    if (c.raw_row) {
      const aoiKeys = [
        "Area of Interest ", "Area of Interest", "area_of_interest",
        "AreaOfInterest", "Interest", "interest", "Domain", "domain", "Field", "field",
      ];
      for (const k of aoiKeys) {
        const v = c.raw_row[k]?.trim();
        if (v && v.toLowerCase() !== "nan" && v !== "-") return v;
      }
    }
    return null;
  };

  const initials = (c: ApiCandidate) =>
    displayName(c).split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase();

  const handleDelete = (candidateId: string) => {
    setLocalList((prev) => prev.filter((c) => c.candidate_id !== candidateId));
    setConfirmId(null);
    if (selected?.candidate_id === candidateId) setSelected(null);
    onDelete?.(candidateId);
  };

  const sorted = [...localList]
    .filter((c) => {
      const q = filter.toLowerCase();
      return (
        displayName(c).toLowerCase().includes(q) ||
        (c.category?.toLowerCase() ?? "").includes(q) ||
        (c.candidate_email?.toLowerCase() ?? "").includes(q) ||
        (displayAreaOfInterest(c)?.toLowerCase() ?? "").includes(q) ||
        portfolioStatusView(c).label.toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      let av: number, bv: number;
      if (sortKey === "criteria_total") {
        av = a.criteria_total ?? -1;
        bv = b.criteria_total ?? -1;
      } else {
        av = a[sortKey] as number;
        bv = b[sortKey] as number;
      }
      return sortAsc ? av - bv : bv - av;
    });

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(key === "rank"); }
  };

  const SortIcon = ({ col }: { col: SortKey }) =>
    sortKey === col
      ? sortAsc ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
      : <ChevronUp className="w-3 h-3 opacity-30" />;

  if (localList.length === 0) {
    return (
      <div className="rounded-xl border bg-card shadow-card p-8 text-center">
        <p className="text-sm font-medium text-foreground">No candidates yet</p>
        <p className="text-xs text-muted-foreground mt-1">
          Upload a JD PDF and a candidates CSV to start ranking.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4">
        {/* Filter bar */}
        <div className="flex items-center gap-3">
          <input
            type="text"
            placeholder="Filter by name, email, category, or area of interest..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="flex-1 max-w-xs px-3 py-2 text-sm rounded-lg border bg-background focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <span className="text-sm text-muted-foreground">
            {sorted.length} candidate{sorted.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Table */}
        <div className="rounded-xl border overflow-hidden shadow-card">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/50 border-b">
                  <th className="text-left px-4 py-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide w-14">
                    <button className="flex items-center gap-1" onClick={() => toggleSort("rank")}>
                      Rank <SortIcon col="rank" />
                    </button>
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
                    Candidate
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
                    Category
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
                    Area of Interest
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
                    <button className="flex items-center gap-1" onClick={() => toggleSort("tech_match_pct")}>
                      Tech Match <SortIcon col="tech_match_pct" />
                    </button>
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
                    <button className="flex items-center gap-1" onClick={() => toggleSort("semantic_match_pct")}>
                      Semantic <SortIcon col="semantic_match_pct" />
                    </button>
                  </th>

                  {/* RMFL Criteria column — only rendered when data is present */}
                  {hasCriteriaData && (
                    <th className="text-left px-4 py-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
                      <button className="flex items-center gap-1" onClick={() => toggleSort("criteria_total")}>
                        Criteria Score <SortIcon col="criteria_total" />
                      </button>
                    </th>
                  )}

                  <th className="text-left px-4 py-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
                    Matched Skills
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
                    Portfolio Output
                  </th>
                  <th className="px-4 py-3 w-28" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {sorted.map((c, i) => (
                  <tr
                    key={c.candidate_id}
                    className={cn(
                      "hover:bg-muted/30 transition-colors cursor-pointer group",
                      i === 0 && "bg-amber-50/50 dark:bg-amber-950/10"
                    )}
                    onClick={() => setSelected(c)}
                  >
                    {/* Rank */}
                    <td className="px-4 py-3">
                      <div className={cn(
                        "w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold",
                        c.rank === 1 ? "bg-amber-400 text-amber-900"   :
                        c.rank === 2 ? "bg-slate-200 text-slate-700"   :
                        c.rank === 3 ? "bg-orange-200 text-orange-800" :
                        "bg-muted text-muted-foreground"
                      )}>
                        {c.rank}
                      </div>
                    </td>

                    {/* Candidate */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary font-semibold text-xs shrink-0">
                          {initials(c)}
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium text-foreground truncate max-w-[160px]">
                            {displayName(c)}
                          </p>
                          <p className="text-xs text-muted-foreground truncate max-w-[160px]">
                            {c.candidate_email || c.candidate_id}
                          </p>
                        </div>
                      </div>
                    </td>

                    {/* Category */}
                    <td className="px-4 py-3">
                      <Badge variant="secondary" className="text-xs font-medium whitespace-nowrap">
                        {c.category}
                      </Badge>
                    </td>

                    {/* Area of Interest */}
                    <td className="px-4 py-3">
                      {displayAreaOfInterest(c) ? (
                        <Badge variant="outline" className="text-xs font-medium whitespace-nowrap max-w-[140px] truncate block">
                          {displayAreaOfInterest(c)}
                        </Badge>
                      ) : (
                        <span className="text-[11px] text-muted-foreground">—</span>
                      )}
                    </td>

                    {/* Tech match */}
                    <td className="px-4 py-3">
                      <ScoreBadge score={c.tech_match_pct} showBar />
                    </td>

                    {/* Semantic match */}
                    <td className="px-4 py-3">
                      <ScoreBadge score={c.semantic_match_pct} showBar />
                    </td>

                    {/* RMFL Criteria total — mini bar + value */}
                    {hasCriteriaData && (
                      <td className="px-4 py-3">
                        {c.criteria_total != null ? (
                          <div className="flex flex-col gap-1 min-w-[80px]">
                            <span className={cn(
                              "text-xs font-semibold tabular-nums",
                              c.criteria_total >= 70 ? "text-green-600 dark:text-green-400" :
                              c.criteria_total >= 45 ? "text-amber-600 dark:text-amber-400" :
                              "text-red-500 dark:text-red-400"
                            )}>
                              {c.criteria_total.toFixed(1)}
                            </span>
                            <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                              <div
                                className={cn(
                                  "h-full rounded-full transition-all",
                                  c.criteria_total >= 70 ? "bg-green-500" :
                                  c.criteria_total >= 45 ? "bg-amber-500" :
                                  "bg-red-500"
                                )}
                                style={{ width: `${Math.min(c.criteria_total, 100)}%` }}
                              />
                            </div>
                          </div>
                        ) : (
                          <span className="text-[11px] text-muted-foreground">—</span>
                        )}
                      </td>
                    )}

                    {/* Matched skills */}
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1 max-w-[200px]">
                        {(c.matched_skills ?? []).slice(0, 3).map((s) => (
                          <SkillTag key={s} skill={s} matched />
                        ))}
                        {(c.matched_skills ?? []).length > 3 && (
                          <span className="text-[11px] text-muted-foreground px-1">
                            +{c.matched_skills.length - 3}
                          </span>
                        )}
                        {(c.matched_skills ?? []).length === 0 && (
                          <span className="text-[11px] text-muted-foreground">—</span>
                        )}
                      </div>
                    </td>

                    {/* Portfolio generation/review status */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 whitespace-nowrap">
                        <Badge
                          variant="outline"
                          className={cn("text-[11px] font-semibold", portfolioStatusView(c).className)}
                          title={c.portfolio_error ?? undefined}
                        >
                          {portfolioStatusView(c).label}
                        </Badge>
                        {c.portfolio_url && (
                          <a
                            href={c.portfolio_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary hover:text-primary/80"
                            title="Open portfolio for human review"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                      </div>
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-2">
                        <button
                          className="flex items-center gap-1 text-xs text-teal font-medium"
                          onClick={(e) => { e.stopPropagation(); setSelected(c); }}
                        >
                          <Eye className="w-3.5 h-3.5" /> View
                        </button>

                        {confirmId === c.candidate_id ? (
                          <div className="flex items-center gap-1">
                            <button
                              className="text-[11px] text-destructive font-semibold hover:underline"
                              onClick={(e) => { e.stopPropagation(); handleDelete(c.candidate_id); }}
                            >
                              Confirm
                            </button>
                            <span className="text-muted-foreground text-[11px]">/</span>
                            <button
                              className="text-[11px] text-muted-foreground hover:underline"
                              onClick={(e) => { e.stopPropagation(); setConfirmId(null); }}
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive transition-colors font-medium"
                            onClick={(e) => { e.stopPropagation(); setConfirmId(c.candidate_id); }}
                          >
                            <Trash2 className="w-3.5 h-3.5" /> Delete
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <CandidateModal
        candidate={selected}
        jdTitle={jdTitle}
        onClose={() => setSelected(null)}
      />
    </>
  );
}

// Export CRITERIA_LABELS so CandidateModal can reuse them
export { CRITERIA_LABELS };
