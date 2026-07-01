"use client";

import { StatusBadge } from "@/components/ui/status-badge";

interface ConfidenceBadgeProps {
  score: number;
  level: "high" | "medium" | "low";
}

const WARNINGS: Record<ConfidenceBadgeProps["level"], string | undefined> = {
  high: undefined,
  medium: "Some geometry may be approximate",
  low: "Reconstruction quality is uncertain — review carefully",
};

export default function ConfidenceBadge({ score, level }: ConfidenceBadgeProps) {
  const label = `${level.charAt(0).toUpperCase()}${level.slice(1)} confidence (${score.toFixed(1)}%)`;
  return (
    <div className="space-y-1">
      <StatusBadge confidence={level} label={label} />
      {WARNINGS[level] && (
        <p className="text-xs text-muted-foreground">{WARNINGS[level]}</p>
      )}
    </div>
  );
}
