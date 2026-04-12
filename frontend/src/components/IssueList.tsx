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
                  <p className="text-sm text-blue-700 mt-1 whitespace-pre-line">{issue.fix_suggestion}</p>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
