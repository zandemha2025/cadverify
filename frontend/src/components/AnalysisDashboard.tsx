"use client";

import type { ValidationResult } from "@/lib/api";
import IssueList from "./IssueList";
import ProcessScoreCard from "./ProcessScoreCard";
import FeaturesList from "./FeaturesList";

interface AnalysisDashboardProps {
  result: ValidationResult;
}

const VERDICT_STYLES = {
  pass: { bg: "bg-green-50", border: "border-green-200", text: "text-green-800", label: "Manufacturable" },
  issues: { bg: "bg-yellow-50", border: "border-yellow-200", text: "text-yellow-800", label: "Issues Found" },
  fail: { bg: "bg-red-50", border: "border-red-200", text: "text-red-800", label: "Not Manufacturable" },
  unknown: { bg: "bg-gray-50", border: "border-gray-200", text: "text-gray-800", label: "Unknown" },
};

const PROCESS_LABELS: Record<string, string> = {
  fdm: "FDM / FFF",
  sla: "SLA Resin",
  dlp: "DLP Resin",
  sls: "SLS (Powder)",
  mjf: "MJF (HP)",
  dmls: "DMLS (Metal)",
  slm: "SLM (Metal)",
  ebm: "EBM (Metal)",
  binder_jetting: "Binder Jetting",
  ded: "DED",
  waam: "WAAM",
  cnc_3axis: "CNC 3-Axis",
  cnc_5axis: "CNC 5-Axis",
  cnc_turning: "CNC Turning",
  wire_edm: "Wire EDM",
  injection_molding: "Injection Molding",
  die_casting: "Die Casting",
  investment_casting: "Investment Casting",
  sand_casting: "Sand Casting",
  sheet_metal: "Sheet Metal",
  forging: "Forging",
};

export default function AnalysisDashboard({ result }: AnalysisDashboardProps) {
  const verdict = VERDICT_STYLES[result.overall_verdict] ?? VERDICT_STYLES.unknown;
  const dims = result.geometry.bounding_box_mm;

  // Extract unique standard citations from all issues
  const allIssues = [
    ...result.universal_issues,
    ...result.process_scores.flatMap((ps) => ps.issues),
  ];
  const citationTags = extractCitationTags(allIssues);

  return (
    <div className="space-y-6">
      {/* Verdict Banner */}
      <div className={`p-4 rounded-xl border ${verdict.bg} ${verdict.border}`}>
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className={`text-2xl font-bold ${verdict.text}`}>{verdict.label}</span>
              {result.rule_pack && (
                <RulePackBadge name={result.rule_pack.name} version={result.rule_pack.version} />
              )}
            </div>
            <p className="text-sm text-gray-600 mt-1">
              {result.filename} ({result.file_type.toUpperCase()}) — analyzed in {result.analysis_time_ms}ms
            </p>
          </div>
          {result.best_process && (
            <div className="text-right">
              <p className="text-xs text-gray-500 uppercase tracking-wide">Best Fit</p>
              <p className="font-semibold text-gray-800">
                {PROCESS_LABELS[result.best_process] ?? result.best_process}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Geometry Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Dimensions" value={`${dims[0]} x ${dims[1]} x ${dims[2]} mm`} />
        <StatCard label="Volume" value={`${(result.geometry.volume_mm3 / 1000).toFixed(1)} cm³`} />
        <StatCard label="Faces" value={result.geometry.faces.toLocaleString()} />
        <StatCard
          label="Watertight"
          value={result.geometry.is_watertight ? "Yes" : "No"}
          color={result.geometry.is_watertight ? "text-green-600" : "text-red-600"}
        />
      </div>

      {/* Detected Features */}
      {result.features && result.features.length > 0 && (
        <FeaturesList features={result.features} />
      )}

      {/* Universal Issues */}
      {result.universal_issues.length > 0 && (
        <div>
          <h3 className="font-semibold text-gray-800 mb-2">Universal Issues</h3>
          <IssueList issues={result.universal_issues} />
        </div>
      )}

      {/* Process Rankings */}
      <div>
        <h3 className="font-semibold text-gray-800 mb-3">Process Suitability</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {result.process_scores.map((ps) => (
            <ProcessScoreCard
              key={ps.process}
              process={ps.process}
              label={PROCESS_LABELS[ps.process] ?? ps.process}
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

      {/* Priority Fixes */}
      {result.priority_fixes.length > 0 && (
        <div>
          <h3 className="font-semibold text-gray-800 mb-2">Priority Fixes</h3>
          <div className="space-y-2">
            {result.priority_fixes.map((fix, i) => (
              <div key={i} className="p-3 bg-white border rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <SeverityBadge severity={fix.severity} />
                  <span className="font-mono text-xs text-gray-500">{fix.code}</span>
                  <span className="text-xs text-gray-400">({fix.process})</span>
                </div>
                <p className="text-sm text-gray-700">{fix.message}</p>
                {fix.fix && (
                  <p className="text-sm text-blue-700 mt-1">
                    <FixSuggestionWithCitations text={fix.fix} />
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Standards Referenced */}
      {citationTags.length > 0 && (
        <div>
          <h3 className="font-semibold text-gray-800 mb-2">Standards Referenced</h3>
          <div className="flex flex-wrap gap-2">
            {citationTags.map((tag) => (
              <span
                key={tag}
                className={`px-2.5 py-1 rounded-md text-xs font-mono font-medium border ${getCitationColor(tag)}`}
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-white border rounded-lg p-3">
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`font-semibold text-sm mt-0.5 ${color ?? "text-gray-800"}`}>{value}</p>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const styles = {
    error: "bg-red-100 text-red-700",
    warning: "bg-yellow-100 text-yellow-700",
    info: "bg-blue-100 text-blue-700",
  };
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${styles[severity as keyof typeof styles] ?? styles.info}`}>
      {severity}
    </span>
  );
}

const CITATION_COLORS: Record<string, string> = {
  aerospace: "bg-blue-50 text-blue-700 border-blue-200",
  automotive: "bg-green-50 text-green-700 border-green-200",
  oil_gas: "bg-orange-50 text-orange-700 border-orange-200",
  "oil-gas": "bg-orange-50 text-orange-700 border-orange-200",
  medical: "bg-purple-50 text-purple-700 border-purple-200",
};

function getCitationColor(tag: string): string {
  const key = tag.toLowerCase().replace(/[\s&]+/g, "_");
  return CITATION_COLORS[key] ?? "bg-gray-50 text-gray-700 border-gray-200";
}

function RulePackBadge({ name, version }: { name: string; version: string }) {
  const colorMap: Record<string, string> = {
    aerospace: "bg-blue-100 text-blue-800",
    automotive: "bg-green-100 text-green-800",
    oil_gas: "bg-orange-100 text-orange-800",
    medical: "bg-purple-100 text-purple-800",
  };
  const key = name.toLowerCase().replace(/[\s&-]+/g, "_");
  const color = colorMap[key] ?? "bg-gray-100 text-gray-800";
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${color}`}>
      {name} v{version}
    </span>
  );
}

/** Parse `[tag]` markers from fix suggestion text and render them as badges */
function FixSuggestionWithCitations({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[([^\]]+)\]$/);
        if (match) {
          const tag = match[1];
          return (
            <span
              key={i}
              className={`inline-block mx-0.5 px-1.5 py-0.5 rounded text-xs font-mono font-medium border ${getCitationColor(tag)}`}
            >
              {tag}
            </span>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
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
      for (const m of matches) {
        tags.add(m[1]);
      }
    }
  }
  return Array.from(tags).sort();
}
