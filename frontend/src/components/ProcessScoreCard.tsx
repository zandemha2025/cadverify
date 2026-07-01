"use client";

import { TONE, verdictTone } from "@/lib/status";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";

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

export default function ProcessScoreCard({
  label,
  score,
  verdict,
  material,
  machine,
  costFactor,
  issueCount,
}: ProcessScoreCardProps) {
  const tone = verdictTone(verdict);
  const pct = Math.round(score * 100);

  return (
    <Card>
      <CardContent compact>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h4 className="text-sm font-semibold text-foreground">{label}</h4>
          <StatusBadge verdict={verdict} size="sm" />
        </div>

        {/* suitability bar — tone-coloured fill */}
        <div className="mb-3 h-2 overflow-hidden rounded-full bg-muted">
          <div
            className={`h-full rounded-full ${TONE[tone].solid}`}
            style={{ width: `${pct}%` }}
          />
        </div>

        <div className="space-y-1 text-xs text-muted-foreground">
          <p className={`num font-semibold ${TONE[tone].fg}`}>
            Suitability: {pct}%
          </p>
          {material && <p>Material: {material}</p>}
          {machine && <p>Machine: {machine}</p>}
          {costFactor !== null && (
            <p className="num">Est. cost factor: ${costFactor.toFixed(2)}</p>
          )}
          {issueCount > 0 && (
            <p>
              {issueCount} issue{issueCount !== 1 ? "s" : ""}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
