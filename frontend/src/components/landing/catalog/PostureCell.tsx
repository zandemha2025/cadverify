"use client";

/**
 * PostureCell — the provenance posture of a catalog row's make-now route, drawn
 * as the product's own grammar: one marker per driver, FILLED when the value is
 * grounded (MEASURED / SHOP / USER) and a HOLLOW ring when it is a generic DEFAULT
 * guess. Reuses PROVENANCE_META (the single provenance vocabulary) so the markers
 * match the glass box exactly. Never colour-only: a mono `g/N` label states the
 * grounded count in text, and the whole cell carries an aria/title summary.
 */

import { PROVENANCE_META, type Provenance } from "@/lib/status";
import { cn } from "@/lib/utils";
import type { PostureCounts } from "@/lib/catalog";

/** grounded-first order so the filled markers lead and the hollow gaps trail. */
const ORDER: Provenance[] = ["MEASURED", "SHOP", "USER", "DEFAULT"];
const MAX_DOTS = 8;

function summary(p: PostureCounts): string {
  const parts: string[] = [];
  if (p.measured) parts.push(`${p.measured} measured`);
  if (p.shop) parts.push(`${p.shop} shop`);
  if (p.user) parts.push(`${p.user} overridden`);
  if (p.default) parts.push(`${p.default} default`);
  return `${p.grounded} of ${p.total} drivers grounded — ${parts.join(", ")}`;
}

export function PostureCell({ posture }: { posture: PostureCounts }) {
  if (posture.total === 0) {
    return <span className="text-subtle-foreground">—</span>;
  }

  // Build the marker list grounded-first, capped so a very driver-heavy estimate
  // stays a single tidy row; overflow is stated as "+k".
  const markers: Provenance[] = [];
  for (const prov of ORDER) {
    const n =
      prov === "MEASURED"
        ? posture.measured
        : prov === "SHOP"
          ? posture.shop
          : prov === "USER"
            ? posture.user
            : posture.default;
    for (let i = 0; i < n; i++) markers.push(prov);
  }
  const shown = markers.slice(0, MAX_DOTS);
  const overflow = markers.length - shown.length;

  return (
    <span className="inline-flex items-center gap-2" title={summary(posture)}>
      <span className="flex items-center gap-1" aria-hidden>
        {shown.map((prov, i) => (
          <span
            key={i}
            className={cn("size-2 rounded-full border", PROVENANCE_META[prov].dot)}
          />
        ))}
        {overflow > 0 && (
          <span className="num text-[10px] text-subtle-foreground">+{overflow}</span>
        )}
      </span>
      <span className="num text-[11px] text-muted-foreground">
        {posture.grounded}/{posture.total}
      </span>
    </span>
  );
}
