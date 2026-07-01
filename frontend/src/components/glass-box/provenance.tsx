"use client";

/**
 * Provenance — the atom of the glass box. A number is never naked: it carries
 * WHERE IT CAME FROM. The encoding is two true dimensions (see lib/status):
 *   • FILL  = grounded (MEASURED / SHOP / USER) vs a generic guess (hollow DEFAULT)
 *   • HUE   = source (measured-blue / calibration-teal / override-green / slate)
 * This file is the single rendering of that system; every glass-box surface
 * composes <ProvenanceChip> / <ProvenanceDot>.
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import { provMeta, type Provenance } from "@/lib/status";

/** A 8px marker: filled = grounded, hollow ring = DEFAULT ("we're guessing"). */
export function ProvenanceDot({
  provenance,
  className,
}: {
  provenance: Provenance | string;
  className?: string;
}) {
  const m = provMeta(provenance);
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block size-2 shrink-0 rounded-full border",
        m.filled ? m.dot : "border-2 bg-transparent",
        !m.filled && m.dot,
        className
      )}
    />
  );
}

/**
 * The provenance tag rendered on a number. Compact by default; `source` appends
 * the engine's verbatim source string (mono micro) for the inline drill-down.
 */
export function ProvenanceChip({
  provenance,
  source,
  withLabel = true,
  size = "sm",
  className,
  title,
}: {
  provenance: Provenance | string;
  source?: string;
  withLabel?: boolean;
  size?: "xs" | "sm";
  className?: string;
  title?: string;
}) {
  const m = provMeta(provenance);
  return (
    <span
      title={title ?? `${m.label} — ${m.description}${source ? `\n${source}` : ""}`}
      className={cn(
        "num inline-flex items-center gap-1 rounded-xs border font-medium",
        m.chip,
        size === "xs" ? "px-1 py-0 text-[10px] leading-4" : "px-1.5 py-0.5 text-micro",
        className
      )}
    >
      <ProvenanceDot provenance={provenance} className="size-1.5" />
      {withLabel && <span className="tracking-wide">{m.label}</span>}
      {source && (
        <span className="font-normal opacity-70" data-prov-source>
          {source}
        </span>
      )}
    </span>
  );
}

const LEGEND_ORDER: Provenance[] = ["MEASURED", "SHOP", "USER", "DEFAULT"];

/** The 4-way legend — teaches the encoding once; the honesty rail in miniature. */
export function ProvenanceLegend({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5", className)}>
      {LEGEND_ORDER.map((p) => {
        const m = provMeta(p);
        return (
          <span key={p} className="inline-flex items-center gap-1.5 text-xs">
            <ProvenanceDot provenance={p} />
            <span className={cn("num font-medium", m.fg)}>{m.label}</span>
            <span className="text-muted-foreground">{m.description}</span>
          </span>
        );
      })}
    </div>
  );
}
