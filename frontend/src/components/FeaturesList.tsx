"use client";

import type { FeatureInfo } from "@/lib/api";
import { TONE, confidenceTone } from "@/lib/status";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface FeaturesListProps {
  features: FeatureInfo[];
}

function formatDimension(feature: FeatureInfo): string {
  const parts: string[] = [];
  if (feature.radius != null) parts.push(`r=${feature.radius.toFixed(2)}mm`);
  if (feature.depth != null) parts.push(`d=${feature.depth.toFixed(2)}mm`);
  if (feature.area != null) parts.push(`${feature.area.toFixed(1)}mm²`);
  return parts.length > 0 ? parts.join(" × ") : "—";
}

function confTone(confidence: number) {
  return confidenceTone(
    confidence >= 0.9 ? "high" : confidence >= 0.7 ? "medium" : "low"
  );
}

export default function FeaturesList({ features }: FeaturesListProps) {
  if (!features || features.length === 0) return null;

  const grouped = new Map<string, FeatureInfo[]>();
  for (const f of features) {
    const kind = f.kind.toLowerCase();
    const existing = grouped.get(kind);
    if (existing) existing.push(f);
    else grouped.set(kind, [f]);
  }

  const sortedGroups = Array.from(grouped.entries()).sort(
    (a, b) => b[1].length - a[1].length
  );

  return (
    <div>
      <h3 className="mb-3 text-base font-semibold leading-[22px] text-foreground">
        Detected features
        <span className="num ml-2 text-sm font-normal text-muted-foreground">
          ({features.length} total)
        </span>
      </h3>
      <div className="space-y-3">
        {sortedGroups.map(([kind, items]) => (
          <Card key={kind}>
            <CardContent compact>
              <div className="mb-2 flex items-center gap-2">
                <span className="text-sm font-semibold capitalize text-foreground">
                  {kind}
                </span>
                <Badge variant="neutral" size="sm" className="num">
                  {items.length}
                </Badge>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {items.map((feature, idx) => {
                  const tone = confTone(feature.confidence);
                  return (
                    <div
                      key={idx}
                      className="rounded-[var(--radius)] border border-border bg-muted/40 p-2 text-xs"
                    >
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span className="num text-muted-foreground">
                          {feature.face_count} face
                          {feature.face_count !== 1 ? "s" : ""}
                        </span>
                        <div className="flex items-center gap-1.5">
                          <div className="h-1.5 w-12 overflow-hidden rounded-full bg-muted">
                            <div
                              className={`h-full rounded-full ${TONE[tone].solid}`}
                              style={{
                                width: `${Math.round(feature.confidence * 100)}%`,
                              }}
                            />
                          </div>
                          <span className="num text-muted-foreground">
                            {Math.round(feature.confidence * 100)}%
                          </span>
                        </div>
                      </div>
                      <p className="num text-foreground">
                        {formatDimension(feature)}
                      </p>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
