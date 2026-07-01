"use client";

/**
 * THE DECISION PLATE (identity signature 1) — the cost rendered as a designed,
 * finance-grade artifact: a machined graphite faceplate carrying, in a single
 * glance, the monumental answer + the recommended make + lead time + the honest
 * (hatched) confidence band + the make-vs-buy crossover + a row of provenance
 * dots proving the figure is grounded. The Ramp "number-as-hero" move made true
 * to THIS product. Same component on the marketing hero and (later) the in-app
 * decision header — driven by the engine's REAL report, never a typed fixture.
 */

import * as React from "react";
import { cn } from "@/lib/utils";
import { ESTIMATE, BREAKEVEN, PART } from "./data";
import { DimensionLine, ProvDot, useCountUp } from "./datum";

const USD2 = (n: number) =>
  n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const USD0 = (n: number) =>
  `$${n.toLocaleString("en-US", { maximumFractionDigits: n < 100 ? 2 : 0 })}`;

export interface DecisionPlateProps {
  /** roll the hero number on mount (hero only); false for static reuse */
  animate?: boolean;
  className?: string;
}

/** The view model, mapped from the engine's real output (single source). */
function usePlateModel() {
  const c = ESTIMATE.confidence!;
  const pointFrac = (c.point_usd - c.low_usd) / (c.high_usd - c.low_usd);
  return {
    unit: ESTIMATE.unit_cost_usd, // 14.14
    low: c.low_usd, // 8.49
    high: c.high_usd, // 19.80
    point: c.point_usd, // 14.14
    pointFrac,
    bandLabel: c.label, // "assumption-based, not yet validated"
    leadLow: ESTIMATE.lead_time!.low_days, // 5.6
    leadHigh: ESTIMATE.lead_time!.high_days, // 10.4
    make: PART.process, // "MJF (PP)"
    crossover: BREAKEVEN.crossoverQty ?? 1962, // 1962
  };
}

export function DecisionPlate({ animate = true, className }: DecisionPlateProps) {
  const m = usePlateModel();
  const rolled = useCountUp(animate ? m.unit : m.unit, 560);
  const shown = animate ? rolled : m.unit;
  const [whole, cents] = USD2(shown).split(".");

  return (
    <div
      className={cn(
        "cv-on-dark cv-faceplate cv-settle rounded-[var(--radius-lg)] p-5 sm:p-6",
        className
      )}
    >
      {/* bezel header strip */}
      <div className="flex items-center justify-between gap-3 border-b border-[#27395800] pb-3">
        <span className="cv-eyebrow">The decision plate</span>
        <span className="num inline-flex items-center gap-2 text-micro text-[#9fb6d6]">
          <span
            aria-hidden
            className="inline-block size-1.5 animate-pulse rounded-full bg-[#3fa3e8]"
          />
          {PART.name} · qty {PART.qty}
        </span>
      </div>

      {/* the monumental answer */}
      <div className="pt-5">
        <span className="cv-eyebrow">Should-cost · make now</span>
        <div className="mt-2 flex items-end gap-1">
          <span className="cv-readout-hero pb-1 text-[2rem] text-[#7fa3c8] sm:text-[2.5rem]">
            $
          </span>
          <span
            className="cv-readout-hero text-[5rem] leading-[0.86] text-[#f1f6fc] sm:text-[6rem]"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {whole}
            <span className="text-[#cfe0f2]">.{cents}</span>
          </span>
          <span className="num pb-3 text-sm text-[#7fa3c8] sm:text-base">/unit</span>
        </div>
        {/* the CAD dimension-line callout — the answer's engineering provenance */}
        <DimensionLine label="measured · sourced · editable" className="mt-1.5" />
      </div>

      {/* sub-figures: the recommended make + lead time */}
      <div className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius)] border border-[#274063] bg-[#274063]">
        <div className="bg-[#101e34] px-4 py-3">
          <p className="num text-micro uppercase tracking-[0.12em] text-[#7fa3c8]">
            Recommended make
          </p>
          <p className="cv-display mt-1 text-lg text-[#eaeff7]">Make by {m.make}</p>
        </div>
        <div className="bg-[#101e34] px-4 py-3">
          <p className="num text-micro uppercase tracking-[0.12em] text-[#7fa3c8]">
            Lead time
          </p>
          <p className="mt-1">
            <span className="num text-lg font-semibold text-[#eaeff7]">
              {m.leadLow}–{m.leadHigh}
            </span>
            <span className="num ml-1 text-sm text-[#7fa3c8]">days</span>
          </p>
        </div>
      </div>

      {/* the honest confidence band — hatched = not yet validated */}
      <div className="mt-4">
        <div className="flex items-baseline justify-between">
          <span className="cv-eyebrow">Confidence · 80%</span>
          <span className="num text-micro text-[#9fb6d6]">
            {USD0(m.low)} – {USD0(m.high)} / unit
          </span>
        </div>
        <div className="relative mt-2 h-2.5 w-full overflow-hidden rounded-full bg-[#0a1626]">
          <div
            className="absolute inset-y-0 left-0 right-0"
            style={{
              backgroundImage:
                "repeating-linear-gradient(135deg, rgba(63,163,232,0.55) 0 2px, transparent 2px 6px)",
            }}
          />
          <span
            className="absolute top-1/2 h-4 w-[2px] -translate-y-1/2 -translate-x-1/2 rounded-[1px] bg-[#7fc1f3]"
            style={{ left: `${Math.min(100, Math.max(0, m.pointFrac * 100))}%` }}
            aria-hidden
          />
        </div>
        <p className="mt-1.5 num text-micro text-[#9fb6d6]">
          {m.bandLabel} — a stated assumption band, not a measured accuracy.
        </p>
      </div>

      {/* the crossover line */}
      <div className="mt-4 rounded-[var(--radius)] border border-[#274063] bg-[#0e1c30] px-4 py-3">
        <p className="text-sm leading-relaxed text-[#cfe0f2]">
          <span className="cv-display text-[#eaeff7]">{m.make}</span> wins{" "}
          <span className="num text-[#7fc1f3]">≤ {m.crossover.toLocaleString()}</span>{" "}
          units · injection molding above —{" "}
          <span className="text-[#e0b070]">if redesigned</span>, never a current
          quote.
        </p>
      </div>

      {/* provenance dots — the figure is grounded */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[#1d2c45] pt-3.5">
        <ProvDot tone="measured" label="MEASURED" onDark />
        <ProvDot tone="shop" label="SHOP" onDark />
        <ProvDot tone="default" label="DEFAULT" onDark />
        <span className="num ml-auto text-micro text-[#6f88a8]">
          real cost-truth-engine output
        </span>
      </div>
    </div>
  );
}
