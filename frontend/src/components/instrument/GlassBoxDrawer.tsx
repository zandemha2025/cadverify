"use client";

/**
 * GlassBoxDrawer — the drivers, revealed on demand (never dumped). Slides up over
 * the instrument and shows the OPEN model behind the held cost: every driver
 * provenance-tagged + sourced, Σ line-items = unit cost, each row drillable and
 * overridable (a real server re-cost that re-tags the touched rate USER). This is
 * the "why" the Ask-why affordance opens — the glass box, not a chatbot.
 */

import * as React from "react";
import { X } from "lucide-react";
import type { CostDriver, CostEstimate } from "@/lib/api";
import { procLabel } from "@/lib/status";
import {
  DriverBreakdown,
  type DriverRateEditor,
} from "@/components/glass-box/driver-breakdown";
import { ProvenanceLegend } from "@/components/glass-box/provenance";
import {
  driverOverrideKey,
  driverRateLabel,
  driverRateUnit,
  parseDriverRate,
} from "@/lib/cost-views";

const USD = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function GlassBoxDrawer({
  open,
  onClose,
  estimate,
  process,
  qty,
  materialClass,
  onOverride,
}: {
  open: boolean;
  onClose: () => void;
  estimate: CostEstimate | null;
  process: string;
  qty: number;
  materialClass: string;
  /** dotted engine key → value → real re-cost */
  onOverride: (key: string, value: number) => void;
}) {
  const rateEditorFor = React.useCallback(
    (d: CostDriver): DriverRateEditor | null => {
      const key = driverOverrideKey(d.name, process, materialClass);
      if (!key) return null;
      return {
        label: driverRateLabel(d.name),
        unit: driverRateUnit(d.name),
        prefill: parseDriverRate(d),
      };
    },
    [process, materialClass]
  );

  const onDriverOverride = React.useCallback(
    (d: CostDriver, value: number) => {
      const key = driverOverrideKey(d.name, process, materialClass);
      if (key) onOverride(key, value);
    },
    [process, materialClass, onOverride]
  );

  return (
    <div
      aria-hidden={!open}
      className="pointer-events-none absolute inset-x-0 bottom-0 z-20"
      style={{
        transform: open ? "translateY(0)" : "translateY(101%)",
        transition: "transform var(--duration-panel) var(--ease-instrument)",
      }}
    >
      <div
        role="dialog"
        aria-label="Glass box — cost drivers"
        className="cv-faceplate pointer-events-auto mx-3 mb-3 max-h-[64vh] overflow-hidden rounded-[var(--radius-lg)]"
      >
        <div className="flex items-center justify-between gap-3 border-b border-[#2a3e5e] px-4 py-3">
          <div className="min-w-0">
            <span className="cv-eyebrow">The number, traced</span>
            <p className="mt-1 text-sm text-[#9fb0c8]">
              Why{" "}
              <span className="num font-semibold text-[#eaeff7]">
                {estimate ? USD(estimate.unit_cost_usd) : "—"}
              </span>{" "}
              for{" "}
              <span className="text-[#eaeff7]">{procLabel(process)}</span> at{" "}
              <span className="num text-[#eaeff7]">{qty.toLocaleString()}</span> units
              <span className="ml-1 text-[#6f8099]">
                (costed at {estimate?.quantity?.toLocaleString() ?? "—"})
              </span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close glass box"
            className="shrink-0 rounded-sm border border-[#2a3e5e] bg-[#0f1b2e] p-1.5 text-[#9fb0c8] hover:text-[#eaeff7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8]"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="max-h-[calc(64vh-64px)] overflow-y-auto px-4 py-3">
          {estimate ? (
            <>
              <DriverBreakdown
                estimate={estimate}
                onOverride={onDriverOverride}
                rateEditorFor={rateEditorFor}
              />
              <div className="mt-4 border-t border-[#233149] pt-3">
                <ProvenanceLegend />
              </div>
            </>
          ) : (
            <p className="py-8 text-center text-sm text-[#9fb0c8]">
              No costed estimate for this process at this quantity.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
