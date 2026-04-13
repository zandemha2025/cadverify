"use client";

import type { Issue } from "@/lib/api";

interface IssueListProps {
  issues: Issue[];
}

const SEVERITY_ICON = {
  error: { color: "text-red-500", bg: "bg-red-50", icon: "!" },
  warning: { color: "text-yellow-500", bg: "bg-yellow-50", icon: "!" },
  info: { color: "text-blue-500", bg: "bg-blue-50", icon: "i" },
};

const CITATION_COLORS: Record<string, string> = {
  aerospace: "bg-blue-50 text-blue-700 border-blue-200",
  automotive: "bg-green-50 text-green-700 border-green-200",
  oil_gas: "bg-orange-50 text-orange-700 border-orange-200",
  "oil-gas": "bg-orange-50 text-orange-700 border-orange-200",
  medical: "bg-purple-50 text-purple-700 border-purple-200",
};

function CitationText({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[([^\]]+)\]$/);
        if (match) {
          const tag = match[1];
          const key = tag.toLowerCase().replace(/[\s&]+/g, "_");
          const color = CITATION_COLORS[key] ?? "bg-gray-50 text-gray-700 border-gray-200";
          return (
            <span
              key={i}
              className={`inline-block mx-0.5 px-1.5 py-0.5 rounded text-xs font-mono font-medium border ${color}`}
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

export default function IssueList({ issues }: IssueListProps) {
  if (issues.length === 0) return null;

  return (
    <div className="space-y-2">
      {issues.map((issue, i) => {
        const sev = SEVERITY_ICON[issue.severity] ?? SEVERITY_ICON.info;
        return (
          <div key={i} className={`p-3 rounded-lg border ${sev.bg}`}>
            <div className="flex items-start gap-2">
              <span className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold text-white ${
                issue.severity === "error" ? "bg-red-500" :
                issue.severity === "warning" ? "bg-yellow-500" : "bg-blue-500"
              }`}>
                {sev.icon}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="font-mono text-xs text-gray-600">{issue.code}</span>
                  {issue.measured_value !== undefined && issue.required_value !== undefined && (
                    <span className="text-xs text-gray-400">
                      {issue.measured_value.toFixed(2)} / {issue.required_value} required
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-800">{issue.message}</p>
                {issue.fix_suggestion && (
                  <p className="text-sm text-blue-700 mt-1 whitespace-pre-line">
                    <CitationText text={issue.fix_suggestion} />
                  </p>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
