"use client";

/**
 * Decision lens — where the Design engineer and the Buyer land. Answer-first: the
 * recommended make-vs-buy decision is the hero, the cost carries its CONFIDENCE
 * band (never fake-exact), the live quantity slider re-costs instantly (client-
 * side, from the report's own fitted curves) and flips the recommended process at
 * the crossover. The glass box and the re-cost inputs are one click away. When the
 * tooling route currently fails DFM, the honesty banner says "if redesigned." For
 * the Buyer lens a Why-trust panel opens: method + the engine's verbatim
 * confidence honesty + the data-locality signal — never a fabricated ±X%.
 */

import { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  SlidersHorizontal,
  Boxes,
  ShieldCheck,
  Lock,
} from "lucide-react";
import type { CostOptions, CostReport } from "@/lib/api";
import { procLabel } from "@/lib/status";
import {
  deriveBreakeven,
  recommendAt,
  posToQty,
  qtyToPos,
} from "@/lib/breakeven";
import { pickEstimate } from "@/lib/cost-views";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { BreakevenChart } from "@/components/cost/BreakevenChart";
import CostDecisionCard from "@/components/CostDecisionCard";
import {
  DecisionHeadline,
  RedesignBanner,
  NumberReadout,
  ConfidenceInterval,
  type RoleDef,
} from "@/components/glass-box";
import {
  CostOptionsForm,
  validateQty,
  type SetOpt,
} from "@/components/cost/CostOptionsForm";

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

export function CostDecisionView({
  report,
  opts,
  setOpt,
  onRecost,
  recosting,
  role,
  onOpenGlassBox,
  onSeeRouting,
}: {
  report: CostReport;
  opts: CostOptions;
  setOpt: SetOpt;
  onRecost: () => void;
  recosting: boolean;
  role: RoleDef;
  onOpenGlassBox: () => void;
  onSeeRouting: () => void;
}) {
  const breakeven = useMemo(() => deriveBreakeven(report), [report]);

  // slider position [0,1]; default to the crossover (the decision boundary)
  // clamped into range, else the largest costed quantity.
  const [pos, setPos] = useState(() => {
    if (!breakeven) return 1;
    const dflt =
      breakeven.crossoverQty ??
      Math.max(...(report.quantities.length ? report.quantities : [1]));
    return qtyToPos(breakeven, dflt);
  });

  const [showInputs, setShowInputs] = useState(false);
  // the Buyer lens opens the trust panel by default; others can expand it.
  const [showTrust, setShowTrust] = useState(role.id === "buyer");
  useEffect(() => setShowTrust(role.id === "buyer"), [role.id]);

  const qtyError = validateQty(opts.qty);

  if (!breakeven || !report.decision) {
    // GEOMETRY_INVALID or no decision -> the breakdown card renders the repair UI
    return <CostDecisionCard report={report} />;
  }

  const qty = posToQty(breakeven, pos);
  const rec = recommendAt(breakeven, qty);
  const dec = report.decision;

  // the estimate behind the currently-recommended process at this quantity —
  // the source of the confidence band shown under the hero cost.
  const recEstimate = rec
    ? pickEstimate(report, rec.curve.process, qty)
    : null;
  const recConfidence = recEstimate?.confidence ?? null;

  // the tooling route is conditional when it currently fails DFM
  const toolingConditional =
    !!dec.tooling_process && dec.tooling_dfm_ready === false;
  const toolingBlocker = dec.tooling_process
    ? pickEstimate(report, dec.tooling_process)?.dfm_blockers?.[0]
    : undefined;

  return (
    <div className="space-y-5">
      {/* ── THE ANSWER (hero, above the fold) ───────────────────────── */}
      <Card className="overflow-hidden">
        <DecisionHeadline
          title={rec ? `Make by ${procLabel(rec.curve.process)}` : "—"}
          dfmReady={rec?.dfmReady ?? false}
          sentence={crossoverSentence(report)}
        />
        <CardContent compact className="grid grid-cols-1 gap-5 sm:grid-cols-3">
          <NumberReadout
            label="Cost / unit"
            value={rec ? USD.format(rec.unitCost) : "—"}
            accent
            confidence={recConfidence ?? undefined}
          />
          <NumberReadout
            label="Lead time"
            size="md"
            value={
              rec && rec.curve.leadLow != null && rec.curve.leadHigh != null
                ? `${rec.curve.leadLow}–${rec.curve.leadHigh}`
                : "—"
            }
            unit="days"
          />
          <NumberReadout
            label="At quantity"
            size="md"
            value={qty.toLocaleString()}
            unit="units"
          />
        </CardContent>
      </Card>

      {/* if-redesigned honesty: never assert a process the part currently fails */}
      {toolingConditional && dec.tooling_process && (
        <RedesignBanner
          process={procLabel(dec.tooling_process)}
          blocker={toolingBlocker}
          onSeeRouting={onSeeRouting}
        />
      )}

      {/* ── Quantity slider (live-flips the recommendation) ─────────── */}
      <Card>
        <CardContent compact className="space-y-3">
          <div className="flex items-baseline justify-between">
            <label className="cv-eyebrow">Order quantity</label>
            <span className="num text-sm font-semibold text-foreground">
              {qty.toLocaleString()} units
            </span>
          </div>
          <Slider
            value={[pos * 1000]}
            min={0}
            max={1000}
            step={1}
            onValueChange={([v]) => setPos(v / 1000)}
            aria-label="Order quantity"
          />
          <div className="num flex justify-between text-[11px] text-muted-foreground">
            <span>{breakeven.qtyMin.toLocaleString()}</span>
            {breakeven.crossoverQty != null && (
              <span className="text-accent-text">
                crossover ≈ {Math.round(breakeven.crossoverQty).toLocaleString()}
              </span>
            )}
            <span>{breakeven.qtyMax.toLocaleString()}</span>
          </div>
        </CardContent>
      </Card>

      {/* ── Breakeven chart ─────────────────────────────────────────── */}
      <Card>
        <CardContent compact>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-base font-semibold leading-[22px] text-foreground">
              Make-vs-buy breakeven
            </h3>
            <span className="text-xs text-muted-foreground">
              $/unit vs quantity
            </span>
          </div>
          <BreakevenChart
            breakeven={breakeven}
            qty={qty}
            recommendedProcess={rec?.curve.process ?? breakeven.makeNowProcess}
          />
          {dec.note && (
            <p className="mt-2 text-xs text-muted-foreground">{dec.note}</p>
          )}
        </CardContent>
      </Card>

      {/* ── Open the glass box (drill the answer into its drivers) ───── */}
      <Card>
        <button
          type="button"
          onClick={onOpenGlassBox}
          className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Boxes className="size-4 text-accent-text" />
          <span className="flex-1">
            <span className="text-sm font-semibold text-foreground">
              View glass box
            </span>
            <span className="ml-2 hidden text-xs text-muted-foreground sm:inline">
              drivers · provenance · Σ = unit cost · confidence
            </span>
          </span>
          <ChevronRight className="size-4 text-muted-foreground" />
        </button>
      </Card>

      {/* ── Adjust inputs & re-cost (the tweak-rerun loop) ──────────── */}
      <Disclosure
        open={showInputs}
        onToggle={() => setShowInputs((s) => !s)}
        icon={SlidersHorizontal}
        title="Adjust inputs & re-cost"
        hint="material · region · complexity · cavities · costed quantities"
      >
        <div className="space-y-4 pt-1">
          <CostOptionsForm
            opts={opts}
            setOpt={setOpt}
            qtyError={qtyError}
            disabled={recosting}
          />
          <Button onClick={onRecost} loading={recosting} disabled={!!qtyError}>
            Re-cost with these inputs
          </Button>
        </div>
      </Disclosure>

      {/* ── Why trust this (open for the Buyer lens) ────────────────── */}
      <Card>
        <button
          type="button"
          onClick={() => setShowTrust((s) => !s)}
          aria-expanded={showTrust}
          className="flex w-full items-center gap-3 px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="text-muted-foreground">
            {showTrust ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </span>
          <ShieldCheck className="size-4 text-prov-shop" />
          <span className="flex-1 text-sm font-semibold text-foreground">
            Why trust this
          </span>
        </button>
        {showTrust && (
          <div className="space-y-3 border-t border-border px-4 pb-4 pt-3">
            <p className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">Method.</span> A
              glass-box should-cost — every driver visible, provenance-tagged and
              sourced — calibrated to your shop&apos;s real rates, with error
              measured on held-out real parts.
            </p>
            {recConfidence ? (
              <ConfidenceInterval confidence={recConfidence} />
            ) : (
              <p className="text-xs text-muted-foreground">
                A calibrated confidence band exists but isn&apos;t shown here yet.
                Until it is, treat this cost as an estimate, not a validated quote.
              </p>
            )}
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Lock className="mt-px size-3.5 shrink-0 text-prov-shop" aria-hidden />
              Your CAD is read and discarded on this machine — it never leaves,
              nothing is uploaded.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}

function Disclosure({
  open,
  onToggle,
  icon: Icon,
  title,
  hint,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  icon?: typeof SlidersHorizontal;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <span className="text-muted-foreground">
          {open ? (
            <ChevronDown className="size-4" />
          ) : (
            <ChevronRight className="size-4" />
          )}
        </span>
        {Icon && <Icon className="size-4 text-muted-foreground" />}
        <span className="flex-1">
          <span className="text-sm font-semibold text-foreground">{title}</span>
          {hint && (
            <span className="ml-2 hidden text-xs text-muted-foreground sm:inline">
              {hint}
            </span>
          )}
        </span>
      </button>
      {open && <div className="border-t border-border px-4 pb-4">{children}</div>}
    </Card>
  );
}

function crossoverSentence(report: CostReport): string {
  const dec = report.decision;
  if (!dec) return "";
  if (dec.crossover_qty != null) {
    const n = Math.round(dec.crossover_qty).toLocaleString();
    const make = procLabel(dec.make_now_process);
    if (dec.tooling_process) {
      return `Make below ~${n} units with ${make}; tool up with ${procLabel(
        dec.tooling_process
      )} above it.`;
    }
    return `${make} wins below ~${n} units; tooling amortizes above it.`;
  }
  return `${procLabel(dec.make_now_process)} stays cheapest at every quantity tested.`;
}
