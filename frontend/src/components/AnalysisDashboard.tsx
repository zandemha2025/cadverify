"use client";

import type { ValidationResult } from "@/lib/api";
import { verdictTone, verdictLabel, procLabel } from "@/lib/status";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/ui/status-badge";
import IssueList, { flattenIssues, type IndexedIssue } from "./IssueList";
import ProcessScoreCard from "./ProcessScoreCard";
import FeaturesList from "./FeaturesList";

interface AnalysisDashboardProps {
  result: ValidationResult;
  /** workspace wiring: the currently-selected issue (for 3D linking). */
  selectedIssueKey?: string | null;
  /** workspace wiring: fired when an issue row is clicked. */
  onSelectIssue?: (item: IndexedIssue) => void;
}

export default function AnalysisDashboard({
  result,
  selectedIssueKey,
  onSelectIssue,
}: AnalysisDashboardProps) {
  const tone = verdictTone(result.overall_verdict);
  const dims = result.geometry.bounding_box_mm;
  const issues = flattenIssues(result);

  const allIssues = [
    ...result.universal_issues,
    ...result.process_scores.flatMap((ps) => ps.issues),
  ];
  const citationTags = extractCitationTags(allIssues);

  return (
    <div className="space-y-6">
      {/* Verdict banner */}
      <Card tone={tone} className="overflow-hidden">
        <CardContent
          compact
          className={`flex items-start justify-between gap-3 ${
            tone === "pass"
              ? "bg-pass-bg"
              : tone === "warn"
                ? "bg-warn-bg"
                : tone === "fail"
                  ? "bg-fail-bg"
                  : "bg-muted"
          }`}
        >
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge
                tone={tone}
                label={verdictLabel(result.overall_verdict, true)}
              />
              {result.rule_pack && (
                <Badge variant="outline" size="sm">
                  {result.rule_pack.name} v{result.rule_pack.version}
                </Badge>
              )}
            </div>
            <p className="num mt-1 text-sm text-muted-foreground">
              {result.filename} ({result.file_type.toUpperCase()}) — analyzed in{" "}
              {result.analysis_time_ms}ms
            </p>
          </div>
          {result.best_process && (
            <div className="text-right">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Best fit
              </p>
              <p className="font-semibold text-foreground">
                {procLabel(result.best_process)}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Geometry summary */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Dimensions" value={`${dims[0]} × ${dims[1]} × ${dims[2]} mm`} />
        <StatTile
          label="Volume"
          value={`${(result.geometry.volume_mm3 / 1000).toFixed(1)} cm³`}
        />
        <StatTile label="Faces" value={result.geometry.faces.toLocaleString()} />
        <StatTile
          label="Watertight"
          value={result.geometry.is_watertight ? "Yes" : "No"}
          tone={result.geometry.is_watertight ? "pass" : "fail"}
        />
      </div>

      {/* Issues (Required / Advisory / Notes) — linked to geometry */}
      <div>
        <h3 className="mb-3 text-base font-semibold leading-[22px] text-foreground">
          Manufacturability issues
        </h3>
        {issues.length > 0 ? (
          <IssueList
            items={issues}
            selectedKey={selectedIssueKey}
            onSelect={onSelectIssue}
          />
        ) : (
          <Card tone="pass">
            <CardContent compact className="bg-pass-bg">
              <div className="flex items-center gap-2">
                <StatusBadge tone="pass" label="Pass" size="sm" />
                <span className="text-sm text-foreground">
                  No DFM issues found across the evaluated processes.
                </span>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Detected features */}
      {result.features && result.features.length > 0 && (
        <FeaturesList features={result.features} />
      )}

      {/* Process suitability */}
      <div>
        <h3 className="mb-3 text-base font-semibold leading-[22px] text-foreground">
          Process suitability
        </h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {result.process_scores.map((ps) => (
            <ProcessScoreCard
              key={ps.process}
              process={ps.process}
              label={procLabel(ps.process)}
              score={ps.score}
              verdict={ps.verdict}
              material={ps.recommended_material}
              machine={ps.recommended_machine}
              costFactor={ps.estimated_cost_factor}
              issueCount={ps.issues.length}
            />
          ))}
        </div>
      </div>

      {/* Standards referenced */}
      {citationTags.length > 0 && (
        <div>
          <h3 className="mb-2 text-base font-semibold leading-[22px] text-foreground">
            Standards referenced
          </h3>
          <div className="flex flex-wrap gap-2">
            {citationTags.map((tag) => (
              <Badge key={tag} variant="outline" size="md" className="num">
                {tag}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "pass" | "fail";
}) {
  return (
    <Card className="p-3">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p
        className={`num mt-0.5 text-sm font-semibold ${
          tone === "pass"
            ? "text-pass"
            : tone === "fail"
              ? "text-fail"
              : "text-foreground"
        }`}
      >
        {value}
      </p>
    </Card>
  );
}

interface IssueWithFixSuggestion {
  fix_suggestion: string | null;
}

/** Extract unique citation tags like [aerospace] from all issue fix_suggestions */
function extractCitationTags(issues: IssueWithFixSuggestion[]): string[] {
  const tags = new Set<string>();
  for (const issue of issues) {
    if (issue.fix_suggestion) {
      const matches = issue.fix_suggestion.matchAll(/\[([^\]]+)\]/g);
      for (const m of matches) tags.add(m[1]);
    }
  }
  return Array.from(tags).sort();
}
