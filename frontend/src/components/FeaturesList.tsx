"use client";

import type { FeatureInfo } from "@/lib/api";

interface FeaturesListProps {
  features: FeatureInfo[];
}

const KIND_CONFIG: Record<string, { color: string; bg: string; icon: string }> = {
  hole: { color: "text-blue-700", bg: "bg-blue-50 border-blue-100", icon: "O" },
  pocket: { color: "text-amber-700", bg: "bg-amber-50 border-amber-100", icon: "U" },
  slot: { color: "text-indigo-700", bg: "bg-indigo-50 border-indigo-100", icon: "=" },
  boss: { color: "text-green-700", bg: "bg-green-50 border-green-100", icon: "T" },
  rib: { color: "text-teal-700", bg: "bg-teal-50 border-teal-100", icon: "|" },
  fillet: { color: "text-purple-700", bg: "bg-purple-50 border-purple-100", icon: "R" },
  chamfer: { color: "text-pink-700", bg: "bg-pink-50 border-pink-100", icon: "/" },
  flat: { color: "text-gray-700", bg: "bg-gray-50 border-gray-200", icon: "_" },
  cylinder: { color: "text-cyan-700", bg: "bg-cyan-50 border-cyan-100", icon: "C" },
  cone: { color: "text-orange-700", bg: "bg-orange-50 border-orange-100", icon: "V" },
  sphere: { color: "text-rose-700", bg: "bg-rose-50 border-rose-100", icon: "S" },
};

function getKindConfig(kind: string) {
  return KIND_CONFIG[kind.toLowerCase()] ?? { color: "text-gray-700", bg: "bg-gray-50 border-gray-200", icon: "?" };
}

function formatDimension(feature: FeatureInfo): string {
  const parts: string[] = [];
  if (feature.radius !== null && feature.radius !== undefined) {
    parts.push(`r=${feature.radius.toFixed(2)}mm`);
  }
  if (feature.depth !== null && feature.depth !== undefined) {
    parts.push(`d=${feature.depth.toFixed(2)}mm`);
  }
  if (feature.area !== null && feature.area !== undefined) {
    parts.push(`${feature.area.toFixed(1)}mm\u00B2`);
  }
  return parts.length > 0 ? parts.join(" \u00D7 ") : "\u2014";
}

function confidenceBar(confidence: number): string {
  if (confidence >= 0.9) return "bg-green-500";
  if (confidence >= 0.7) return "bg-yellow-500";
  return "bg-red-500";
}

export default function FeaturesList({ features }: FeaturesListProps) {
  if (!features || features.length === 0) return null;

  // Group features by kind
  const grouped = new Map<string, FeatureInfo[]>();
  for (const f of features) {
    const kind = f.kind.toLowerCase();
    const existing = grouped.get(kind);
    if (existing) {
      existing.push(f);
    } else {
      grouped.set(kind, [f]);
    }
  }

  const sortedGroups = Array.from(grouped.entries()).sort(
    (a, b) => b[1].length - a[1].length
  );

  return (
    <div>
      <h3 className="font-semibold text-gray-800 mb-3">
        Detected Features
        <span className="ml-2 text-sm font-normal text-gray-500">
          ({features.length} total)
        </span>
      </h3>
      <div className="space-y-3">
        {sortedGroups.map(([kind, items]) => {
          const config = getKindConfig(kind);
          return (
            <div key={kind} className={`border rounded-lg p-3 ${config.bg}`}>
              <div className="flex items-center gap-2 mb-2">
                <span
                  className={`w-6 h-6 rounded flex items-center justify-center text-xs font-bold ${config.color} bg-white border`}
                >
                  {config.icon}
                </span>
                <span className={`font-semibold text-sm capitalize ${config.color}`}>
                  {kind}
                </span>
                <span className="text-xs text-gray-500">
                  ({items.length})
                </span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {items.map((feature, idx) => (
                  <div
                    key={idx}
                    className="bg-white rounded-md border p-2 text-xs"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-gray-600">
                        {feature.face_count} face{feature.face_count !== 1 ? "s" : ""}
                      </span>
                      <div className="flex items-center gap-1.5">
                        <div className="w-12 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${confidenceBar(feature.confidence)}`}
                            style={{ width: `${Math.round(feature.confidence * 100)}%` }}
                          />
                        </div>
                        <span className="text-gray-500">
                          {Math.round(feature.confidence * 100)}%
                        </span>
                      </div>
                    </div>
                    <p className="text-gray-700">{formatDimension(feature)}</p>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
