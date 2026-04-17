"use client";

interface ConfidenceBadgeProps {
  score: number;
  level: "high" | "medium" | "low";
}

const LEVEL_STYLES: Record<
  ConfidenceBadgeProps["level"],
  { bg: string; label: string; warning?: string }
> = {
  high: {
    bg: "bg-green-100 text-green-800",
    label: "High Confidence",
  },
  medium: {
    bg: "bg-amber-100 text-amber-800",
    label: "Medium Confidence",
    warning: "Some geometry may be approximate",
  },
  low: {
    bg: "bg-red-100 text-red-800",
    label: "Low Confidence",
    warning: "Reconstruction quality is uncertain -- review carefully",
  },
};

export default function ConfidenceBadge({ score, level }: ConfidenceBadgeProps) {
  const config = LEVEL_STYLES[level];

  return (
    <div className="space-y-1">
      <span
        className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-medium ${config.bg}`}
      >
        {config.label} ({score.toFixed(1)}%)
      </span>
      {config.warning && (
        <p className="text-xs text-gray-500">{config.warning}</p>
      )}
    </div>
  );
}
