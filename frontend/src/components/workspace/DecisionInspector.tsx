"use client";

/**
 * DecisionInspector — the reframed glass box, now INFRASTRUCTURE instead of a
 * theatrical slide-up drawer. It rides alongside the L2 Decision frame as a
 * resident right panel (the cost lens keeps it open; other lenses can collapse
 * it). Four tabs express the same receipts the old `GlassBoxDrawer` showed, as
 * governance grammar:
 *
 *   • Lineage    — the directed derivation: geometry → drivers → Σ unit_cost,
 *                  nodes tinted by provenance tier (DEFAULT hollow), edges draw
 *                  in with a small stagger (the one place motion explains).
 *   • Governance — the honest posture bar (governed vs guessed) + the confidence
 *                  DATA-QUALITY track, verbatim from the engine. Never a
 *                  fabricated ±%. Plus the data-locality LOCAL badge.
 *   • Sources    — the driver table, each row provenance-tagged + sourced +
 *                  inline-overridable (re-tags USER, re-costs live).
 *   • Audit      — the applied USER overrides for this estimate (the immutable,
 *                  searchable audit log lands with Governance in Phase 2).
 *
 * Honesty rail preserved: `confidence.validated` is rendered verbatim; DEFAULT
 * is always a hollow outline ("we're guessing here").
 */

import * as React from "react";
import { Lock, PanelRightClose, PanelRightOpen } from "lucide-react";
import type { CostDriver, CostEstimate, Provenance } from "@/lib/api";
import { procLabel, provMeta } from "@/lib/status";
import {
  driverOverrideKey,
  driverRateLabel,
  driverRateUnit,
  parseDriverRate,
} from "@/lib/cost-views";
import { cn } from "@/lib/utils";
import {
  DriverBreakdown,
  ProvenanceLegend,
  ProvenanceDot,
  ConfidenceTrack,
  ConfidenceLabel,
  type DriverRateEditor,
} from "@/components/glass-box";

const USD = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

type InspectorTab = "lineage" | "governance" | "sources" | "audit";
const TABS: { id: InspectorTab; label: string }[] = [
  { id: "lineage", label: "Lineage" },
  { id: "governance", label: "Governance" },
  { id: "sources", label: "Sources" },
  { id: "audit", label: "Audit" },
];

const TIER_ORDER: Provenance[] = ["MEASURED", "SHOP", "USER", "DEFAULT"];

/** Provenance-tinted segment fills for the posture bar (filled = grounded). */
const TIER_FILL: Record<Provenance, string> = {
  MEASURED: "bg-prov-measured",
  SHOP: "bg-prov-shop",
  USER: "bg-prov-user",
  DEFAULT: "bg-prov-default/30",
};

function costDrivers(estimate: CostEstimate): CostDriver[] {
  return estimate.drivers.filter((d) => d.name !== "cycle_time");
}

function tierCounts(drivers: CostDriver[]): Record<Provenance, number> {
  const c: Record<Provenance, number> = { MEASURED: 0, SHOP: 0, USER: 0, DEFAULT: 0 };
  for (const d of drivers) c[d.provenance] = (c[d.provenance] ?? 0) + 1;
  return c;
}

export function DecisionInspector({
  estimate,
  process,
  qty,
  materialClass,
  overrideKeys,
  onOverride,
  defaultTab = "sources",
  open,
  onToggle,
  className,
}: {
  estimate: CostEstimate | null;
  process: string;
  qty: number;
  materialClass: string;
  /** dotted override keys currently applied (for the Audit tab) */
  overrideKeys: string[];
  /** dotted engine key → value → real re-cost */
  onOverride: (key: string, value: number) => void;
  defaultTab?: InspectorTab;
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  const [tab, setTab] = React.useState<InspectorTab>(defaultTab);
  React.useEffect(() => setTab(defaultTab), [defaultTab]);

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

  // collapsed rail — a thin spine that reopens the Inspector
  if (!open) {
    return (
      <div className="flex w-9 shrink-0 flex-col items-center border-l border-border bg-background py-3">
        <button
          type="button"
          onClick={onToggle}
          aria-label="Open Inspector"
          className="inline-flex size-7 items-center justify-center rounded-[var(--radius-sm)] text-subtle-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <PanelRightOpen className="size-4" />
        </button>
        <span
          className="mt-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-subtle-foreground"
          style={{ writingMode: "vertical-rl" }}
        >
          Inspector
        </span>
      </div>
    );
  }

  const drivers = estimate ? costDrivers(estimate) : [];
  const counts = tierCounts(drivers);
  const total = drivers.length;
  const governed = total - counts.DEFAULT;

  return (
    <aside
      className={cn(
        "flex w-[var(--inspector-w)] shrink-0 flex-col overflow-hidden border-l border-border bg-background",
        className
      )}
      aria-label="Inspector"
    >
      {/* header + tabs */}
      <div className="flex items-center justify-between gap-2 px-3 pt-3">
        <span className="cv-eyebrow">Inspector</span>
        <button
          type="button"
          onClick={onToggle}
          aria-label="Collapse Inspector"
          className="inline-flex size-6 items-center justify-center rounded-[var(--radius-sm)] text-subtle-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <PanelRightClose className="size-4" />
        </button>
      </div>
      <div className="flex items-center gap-1 border-b border-border px-3 pt-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? "true" : undefined}
            className={cn(
              "relative px-1.5 pb-2 text-xs font-medium transition-colors",
              tab === t.id ? "text-foreground" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {t.label}
            {tab === t.id && (
              <span className="absolute inset-x-0 -bottom-px h-[2px] rounded-full bg-primary" aria-hidden />
            )}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {!estimate ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No costed estimate for this process at this quantity.
          </p>
        ) : tab === "lineage" ? (
          <LineageView estimate={estimate} process={process} qty={qty} />
        ) : tab === "governance" ? (
          <GovernanceView estimate={estimate} governed={governed} total={total} counts={counts} />
        ) : tab === "sources" ? (
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground">
              Why{" "}
              <span className="num font-semibold text-foreground">
                {USD(estimate.unit_cost_usd)}
              </span>{" "}
              for {procLabel(process)} at{" "}
              <span className="num text-foreground">{qty.toLocaleString()}</span> units — each
              driver tagged + sourced, editable.
            </p>
            <DriverBreakdown
              estimate={estimate}
              onOverride={onDriverOverride}
              rateEditorFor={rateEditorFor}
            />
            <div className="border-t border-border pt-3">
              <ProvenanceLegend />
            </div>
          </div>
        ) : (
          <AuditView overrideKeys={overrideKeys} />
        )}
      </div>
    </aside>
  );
}

/* ── Lineage — a directed derivation column: geometry → drivers → Σ. ───────── */
function LineageView({
  estimate,
  process,
  qty,
}: {
  estimate: CostEstimate;
  process: string;
  qty: number;
}) {
  const drivers = costDrivers(estimate);
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Directed derivation of{" "}
        <span className="num font-semibold text-foreground">{USD(estimate.unit_cost_usd)}</span> —
        column-lineage on a cost decision.
      </p>

      <LineageNode label="geometry.step" sub="measured input" provenance="MEASURED" index={0} />
      <LineageEdge />
      <div className="space-y-1.5">
        {drivers.map((d, i) => (
          <LineageNode
            key={d.name}
            label={d.name}
            sub={d.unit === "$" ? USD(d.value) : `${d.value} ${d.unit}`}
            provenance={d.provenance}
            index={i + 1}
            indent
          />
        ))}
      </div>
      <LineageEdge converge />
      <LineageNode
        label={`Σ unit_cost · ${procLabel(process)}`}
        sub={`${USD(estimate.unit_cost_usd)} at qty ${qty.toLocaleString()}`}
        provenance="SHOP"
        index={drivers.length + 1}
        emphasize
      />
      <p className="pt-1 num text-micro text-muted-foreground">
        Hollow node = DEFAULT (ungoverned — a guess). Filled = grounded.
      </p>
    </div>
  );
}

function LineageNode({
  label,
  sub,
  provenance,
  index,
  indent,
  emphasize,
}: {
  label: string;
  sub: string;
  provenance: Provenance;
  index: number;
  indent?: boolean;
  emphasize?: boolean;
}) {
  const m = provMeta(provenance);
  return (
    <div
      className="cv-reveal flex items-center gap-2"
      style={{ animationDelay: `${Math.min(index, 8) * 40}ms`, marginLeft: indent ? 14 : 0 }}
    >
      <ProvenanceDot provenance={provenance} />
      <div
        className={cn(
          "min-w-0 flex-1 rounded-[var(--radius-sm)] border px-2.5 py-1.5",
          emphasize ? "border-primary/40 bg-accent-subtle" : "border-border bg-card"
        )}
      >
        <p className="num truncate text-xs font-medium text-foreground">{label}</p>
        <p className={cn("num text-[10px]", m.fg)}>{sub}</p>
      </div>
    </div>
  );
}

function LineageEdge({ converge }: { converge?: boolean }) {
  return (
    <div className="flex pl-[3px]" aria-hidden>
      <span className={cn("w-px bg-border", converge ? "ml-[10px] h-4" : "ml-1 h-3")} />
    </div>
  );
}

/* ── Governance — honest posture + data-quality track + locality. ─────────── */
function GovernanceView({
  estimate,
  governed,
  total,
  counts,
}: {
  estimate: CostEstimate;
  governed: number;
  total: number;
  counts: Record<Provenance, number>;
}) {
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1.5 flex items-baseline justify-between">
          <span className="cv-eyebrow">Governance posture</span>
          <span className="num text-xs text-muted-foreground">
            {governed}/{total} governed
          </span>
        </div>
        {/* provenance-tinted posture bar — the breakdown IS the lineage */}
        <div className="flex h-2.5 w-full overflow-hidden rounded-full border border-border bg-muted">
          {TIER_ORDER.map((t) =>
            counts[t] > 0 ? (
              <span
                key={t}
                className={cn("h-full", TIER_FILL[t])}
                style={{ width: `${(counts[t] / Math.max(total, 1)) * 100}%` }}
                title={`${t} · ${counts[t]}`}
              />
            ) : null
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
          {TIER_ORDER.filter((t) => counts[t] > 0).map((t) => {
            const m = provMeta(t);
            return (
              <span key={t} className="inline-flex items-center gap-1.5 text-[11px]">
                <ProvenanceDot provenance={t} />
                <span className={cn("num font-medium", m.fg)}>{m.label}</span>
                <span className="num text-muted-foreground">{counts[t]}</span>
              </span>
            );
          })}
        </div>
      </div>

      {estimate.confidence ? (
        <div className="space-y-1.5">
          <span className="cv-eyebrow">Data quality</span>
          <ConfidenceTrack confidence={estimate.confidence} />
          <ConfidenceLabel confidence={estimate.confidence} />
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Data-quality track lives in the engine — surfacing it through the API is a build gap. No
          fabricated ±% is shown in its place.
        </p>
      )}

      <div className="rounded-[var(--radius-sm)] border border-prov-shop-border bg-prov-shop-bg px-2.5 py-2">
        <p className="flex items-center gap-1.5 text-[11px] font-medium text-prov-shop">
          <Lock className="size-3" aria-hidden />
          data-locality: LOCAL · zero-egress
        </p>
        <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
          The CAD is parsed and discarded in-process on the cost/DFM path — CAD-as-IP, audited.
        </p>
      </div>
    </div>
  );
}

/* ── Audit — the applied USER overrides for this estimate. ────────────────── */
function AuditView({ overrideKeys }: { overrideKeys: string[] }) {
  return (
    <div className="space-y-3">
      <span className="cv-eyebrow">Overrides · this session</span>
      {overrideKeys.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No overrides applied. Edit any driver&apos;s rate in Sources → it re-tags{" "}
          <span className="num text-prov-user">USER</span> and re-costs live.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {overrideKeys.map((k) => (
            <li
              key={k}
              className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-prov-user-border bg-prov-user-bg px-2.5 py-1.5"
            >
              <ProvenanceDot provenance="USER" />
              <span className="num min-w-0 flex-1 truncate text-xs text-foreground">{k}</span>
              <span className="num text-[10px] text-prov-user">USER</span>
            </li>
          ))}
        </ul>
      )}
      <p className="border-t border-border pt-2.5 text-[11px] leading-relaxed text-subtle-foreground">
        The immutable, searchable, exportable audit log (who changed / ran / exported what) lands
        with the Governance zone in Phase 2.
      </p>
    </div>
  );
}
