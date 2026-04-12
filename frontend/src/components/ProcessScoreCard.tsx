"use client";

interface ProcessScoreCardProps {
  process: string;
  label: string;
  score: number;
  verdict: "pass" | "issues" | "fail";
  material: string | null;
  machine: string | null;
  costFactor: number | null;
  issueCount: number;
}

const VERDICT_COLORS = {
  pass: { bar: "bg-green-500", text: "text-green-700", badge: "bg-green-100 text-green-800" },
  issues: { bar: "bg-yellow-500", text: "text-yellow-700", badge: "bg-yellow-100 text-yellow-800" },
  fail: { bar: "bg-red-500", text: "text-red-700", badge: "bg-red-100 text-red-800" },
};

export default function ProcessScoreCard({
  label,
  score,
  verdict,
  material,
  machine,
  costFactor,
  issueCount,
}: ProcessScoreCardProps) {
  const colors = VERDICT_COLORS[verdict];
  const pct = Math.round(score * 100);

  return (
    <div className="bg-white border rounded-xl p-4 hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between mb-2">
        <h4 className="font-semibold text-gray-800 text-sm">{label}</h4>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors.badge}`}>
          {verdict === "pass" ? "PASS" : verdict === "fail" ? "FAIL" : "ISSUES"}
        </span>
      </div>

      {/* Score bar */}
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden mb-3">
        <div
          className={`h-full rounded-full transition-all duration-500 ${colors.bar}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="space-y-1 text-xs text-gray-600">
        <p className={`font-semibold ${colors.text}`}>
          Suitability: {pct}%
        </p>
        {material && <p>Material: {material}</p>}
        {machine && <p>Machine: {machine}</p>}
        {costFactor !== null && <p>Est. cost factor: ${costFactor.toFixed(2)}</p>}
        {issueCount > 0 && <p className="text-gray-400">{issueCount} issue{issueCount !== 1 ? "s" : ""}</p>}
      </div>
    </div>
  );
}
