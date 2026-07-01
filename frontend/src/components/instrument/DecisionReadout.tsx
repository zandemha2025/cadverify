"use client";

/**
 * DecisionReadout — the decision rendered as a live instrument readout, not a
 * report row. It leads with ONLY the answer: the recommended process, the
 * monumental cost/unit (Archivo Expanded), and the one-line crossover. The
 * cost MORPHS as the scrubber moves; the process FLIP triggers a single
 * caliper-settle. Everything else — the confidence band, the lead/quantity
 * metaline, the "if redesigned" note — is deliberately quiet and secondary, so
 * the eye lands on the number first. Honest by construction: the band is
 * hatched until validated (n=0) and never prints a fabricated accuracy figure.
 */

import * as React from "react";
import { HelpCircle, SlidersHorizontal, TriangleAlert } from "lucide-react";
import type { CostConfidence, CostEstimate } from "@/lib/api";
import { procLabel } from "@/lib/status";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  ConfidenceTrack,
  ConfidenceLabel,
} from "@/components/glass-box/confidence";
import { ProvenanceDot } from "@/components/glass-box/provenance";

const PROV_ORDER = ["MEASURED", "SHOP", "USER", "DEFAULT"] as const;

/** A live-centered, honest band — engine half-width + engine validation status. */
function liveConfidence(estimate: CostEstimate | null, unitCost: number): CostConfidence {
  const conf = estimate?.confidence;
  const hw = conf?.half_width_pct ?? estimate?.est_error_band_pct ?? 30;
  const point = unitCost;
  return {
    low_usd: point * (1 - hw / 100),
    high_usd: point * (1 + hw / 100),
    point_usd: point,
    level: conf?.level ?? 0.8,
    method: conf?.method ?? "assumption-band",
    validated: conf?.validated ?? false,
    n_samples: conf?.n_samples ?? 0,
    half_width_pct: hw,
    basis: conf?.basis ?? "assumption-based · not yet validated on your parts (n=0)",
    label: conf?.label ?? "assumption-based, not yet validated",
  };
}

/** Split a money value into integer + decimal so the cents ride smaller. */
function MoneyHero({ value }: { value: number }) {
  if (!Number.isFinite(value)) {
    return <span className="cv-readout-hero text-[#eaeff7]">—</span>;
  }
  const [whole, cents] = value
    .toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    .split(".");
  return (
    <span className="inline-flex items-baseline">
      <span className="cv-readout-hero text-[3.75rem] leading-[0.9] text-[#eaeff7] sm:text-[4.5rem]">
        <span className="text-[#6f8099]" style={{ fontSize: "0.4em" }}>
          $
        </span>
        {whole}
        <span className="text-[#9fb0c8]" style={{ fontSize: "0.48em" }}>
          .{cents}
        </span>
      </span>
    </span>
  );
}

export function DecisionReadout({
  process,
  unitCost,
  dfmReady,
  leadLow,
  leadHigh,
  qty,
  estimate,
  crossoverSentence,
  toolingConditional,
  onAskWhy,
  onRecalibrate,
  controlsOpen,
}: {
  process: string;
  unitCost: number;
  dfmReady: boolean;
  leadLow: number | null;
  leadHigh: number | null;
  qty: number;
  estimate: CostEstimate | null;
  crossoverSentence: string;
  toolingConditional?: { process: string; blocker?: string } | null;
  onAskWhy: () => void;
  onRecalibrate: () => void;
  controlsOpen: boolean;
}) {
  const conf = liveConfidence(estimate, unitCost);
  const [confOpen, setConfOpen] = React.useState(false);

  // which provenances actually back this estimate (reflects reality, gaps shown)
  const present = React.useMemo(() => {
    const set = new Set<string>();
    for (const d of estimate?.drivers ?? []) set.add(d.provenance);
    return PROV_ORDER.filter((p) => set.has(p));
  }, [estimate]);

  const lead =
    leadLow != null && leadHigh != null ? `${leadLow}–${leadHigh} day lead` : null;

  return (
    <div className="flex flex-col gap-7">
      {/* the decision — the only headline */}
      <div>
        <span className="cv-eyebrow">Recommended · make-vs-buy</span>
        {/* process flips → re-key so the cluster settles once (gauge needle) */}
        <div key={process} className="cv-settle mt-2.5 flex flex-wrap items-center gap-2.5">
          <h2 className="cv-display text-[1.65rem] leading-8 text-[#eaeff7]">
            Make by {procLabel(process)}
          </h2>
          <StatusBadge
            tone={dfmReady ? "pass" : "warn"}
            label={dfmReady ? "DFM-ready" : "needs redesign"}
            size="sm"
          />
        </div>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-[#9fb0c8]">
          {crossoverSentence}
        </p>
      </div>

      {/* THE monumental answer — the hero data, given room */}
      <div>
        <span className="inline-flex flex-col">
          <span className="flex items-baseline gap-2">
            <MoneyHero value={unitCost} />
            <span className="num text-base text-[#6f8099]">/ unit</span>
          </span>
          {/* datum witness line — a caliper mark seating the answer on the plate */}
          <span
            aria-hidden
            className="mt-2 h-[2px] w-20 rounded-full"
            style={{
              background:
                "linear-gradient(90deg, #3fa3e8 0%, rgba(63,163,232,0.35) 55%, rgba(63,163,232,0) 100%)",
              boxShadow: "0 0 10px rgba(63,163,232,0.45)",
            }}
          />
        </span>

        {/* quiet metaline: lead time + held quantity (replaces the two cards) */}
        <p className="num mt-3 text-xs text-[#6f8099]">
          {lead && (
            <>
              <span className="text-[#9fb0c8]">{lead}</span>
              <span className="px-1.5 text-[#33446a]">·</span>
            </>
          )}
          at <span className="text-[#9fb0c8]">{qty.toLocaleString()}</span> units
        </p>

        {/* confidence — a single quiet line, expandable to the honest band */}
        <button
          type="button"
          onClick={() => setConfOpen((o) => !o)}
          aria-expanded={confOpen}
          className="num mt-2.5 inline-flex items-center gap-1.5 rounded-sm text-[11px] text-[#6f8099] transition-colors hover:text-[#9fb0c8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8]"
        >
          <span
            className="inline-block size-2 rounded-[1px] cv-hatch"
            style={{ background: "rgba(63,163,232,0.25)" }}
            aria-hidden
          />
          ±{Math.round(conf.half_width_pct)}% · {conf.validated ? `validated · n=${conf.n_samples}` : "not yet validated"}
          <span className="text-[#3fa3e8]">{confOpen ? "hide" : "band"}</span>
        </button>
        {confOpen && (
          <div className="cv-reveal mt-2 max-w-[260px] space-y-1.5">
            <ConfidenceTrack confidence={conf} />
            <ConfidenceLabel confidence={conf} />
          </div>
        )}
      </div>

      {/* quiet honesty note — compact, only when the tooling route needs redesign */}
      {toolingConditional && (
        <p className="flex items-start gap-1.5 text-xs leading-relaxed text-[#caa25a]">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          <span>
            {procLabel(toolingConditional.process)} shown{" "}
            <span className="font-semibold">&ldquo;if redesigned,&rdquo;</span> not a
            current quote
            {toolingConditional.blocker ? ` · ${toolingConditional.blocker}` : ""}.
          </span>
        </p>
      )}

      {/* action row: provenance ledger + recalibrate + ask why (all quiet) */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#233149] pt-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {(present.length ? present : (["MEASURED", "DEFAULT"] as const)).map((p) => (
            <span key={p} className="inline-flex items-center gap-1.5 text-[11px]">
              <ProvenanceDot provenance={p} />
              <span className="num text-[#9fb0c8]">{p}</span>
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRecalibrate}
            aria-expanded={controlsOpen}
            className={[
              "inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8]",
              controlsOpen
                ? "border-[#3fa3e8] bg-[#12365a] text-[#bfe0fb]"
                : "border-[#233149] bg-[#0f1b2e] text-[#9fb0c8] hover:text-[#eaeff7]",
            ].join(" ")}
          >
            <SlidersHorizontal className="size-3.5" />
            Recalibrate
          </button>
          <button
            type="button"
            onClick={onAskWhy}
            className="inline-flex items-center gap-1.5 rounded-sm border border-[#1e3a5f] bg-[#102438] px-2.5 py-1.5 text-xs font-medium text-[#8fc8f2] transition-colors hover:bg-[#15314c] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8]"
          >
            <HelpCircle className="size-3.5" />
            Ask why
          </button>
        </div>
      </div>
    </div>
  );
}
