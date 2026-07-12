"use client";

/**
 * DecisionColumn — the co-primary DECISION column of the part hero (D5 FE-2).
 *
 * Answer-first, never fake-exact: the make-vs-buy VERDICT, the unit cost as a
 * tempo-aware ODOMETER (rolls up on the reveal / re-flip), the HONEST HATCH (the
 * confidence band drawn provisional when the engine says `validated:false`), the
 * make-vs-buy CROSSOVER chart (the existing, theme-aware BreakevenChart re-housed
 * here), and the keepable ARTIFACT actions (the existing CostArtifactBar).
 *
 * The quantity scrubber is the "aha": it re-derives the recommendation client-
 * side from the report's OWN fitted curves (lib/breakeven) — no server round-trip,
 * no invented figure — and live-flips the recommended process at the crossover.
 * The full driver breakdown + overrides live one click deeper in the Decision
 * depth panel (the glass box), via onOpenGlassBox.
 */

import * as React from "react";
import { Boxes, ChevronRight, Crosshair } from "lucide-react";
import type { CostReport } from "@/lib/api";
import type { IndexedIssue } from "@/lib/dfm-scope";
import type { Breakeven } from "@/lib/breakeven";
import { recommendAt, posToQty, qtyToPos } from "@/lib/breakeven";
import { pickEstimate } from "@/lib/cost-views";
import { procLabel } from "@/lib/status";
import { costPersistUiEnabled } from "@/lib/cost-decision";
import { Card, CardContent } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Odometer } from "@/components/ui/odometer";
import { BreakevenChart } from "@/components/cost/BreakevenChart";
import CostDecisionCard from "@/components/CostDecisionCard";
import { CostArtifactBar } from "@/components/instrument/CostArtifactBar";
import { DecisionHeadline, RedesignBanner, NumberReadout } from "@/components/glass-box";

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

export function DecisionColumn({
  report,
  breakeven,
  filename,
  costBlockers,
  selectedKey,
  onLocateBlocker,
  onOpenGlassBox,
  onSeeRouting,
}: {
  report: CostReport;
  breakeven: Breakeven | null;
  filename: string;
  /** cost-side DFM blockers relinked to locatable rows (dedup across estimates);
   *  each carries the shared `cost:`-namespaced key + its face sample. */
  costBlockers?: IndexedIssue[];
  /** the currently highlighted key (shared with the CadViewer / inspection). */
  selectedKey?: string | null;
  /** light this blocker's faces on the part (toggles off when re-clicked). */
  onLocateBlocker?: (key: string | null) => void;
  /** open the glass box (drivers · provenance · Σ) — the Decision depth panel */
  onOpenGlassBox: () => void;
  /** jump to the per-process DFM audit (from the "if redesigned" honesty banner) */
  onSeeRouting: () => void;
}) {
  const dec = report.decision;

  // slider position [0,1]; default to the crossover (the decision boundary),
  // else the largest costed quantity. Mirrors the Decision lens.
  const [pos, setPos] = React.useState(() => {
    if (!breakeven) return 1;
    const dflt =
      breakeven.crossoverQty ??
      Math.max(...(report.quantities.length ? report.quantities : [1]));
    return qtyToPos(breakeven, dflt);
  });

  if (!breakeven || !dec) {
    // GEOMETRY_INVALID / no decision → the breakdown card renders the honest state
    return <CostDecisionCard report={report} />;
  }

  const qty = posToQty(breakeven, pos);
  const rec = recommendAt(breakeven, qty);
  const recEstimate = rec ? pickEstimate(report, rec.curve.process, qty) : null;
  const recConfidence = recEstimate?.confidence ?? null;

  const toolingConditional = !!dec.tooling_process && dec.tooling_dfm_ready === false;
  const toolingBlocker = dec.tooling_process
    ? pickEstimate(report, dec.tooling_process)?.dfm_blockers?.[0]
    : undefined;

  return (
    <section aria-label="Decision" className="flex min-w-0 flex-col gap-4">
      {/* ── THE ANSWER: verdict + odometer + honest hatch ─────────────── */}
      <Card className="overflow-hidden">
        <DecisionHeadline
          title={rec ? `Make by ${procLabel(rec.curve.process)}` : "—"}
          dfmReady={rec?.dfmReady ?? false}
          sentence={crossoverSentence(report)}
        />
        <CardContent compact className="space-y-4">
          <NumberReadout
            label="Cost / unit"
            value={
              rec ? (
                <Odometer value={rec.unitCost} format={(n) => USD.format(n)} />
              ) : (
                "—"
              )
            }
            accent
            confidence={recConfidence ?? undefined}
          />
          <div className="flex flex-wrap gap-x-6 gap-y-2">
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
          </div>
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

      {/* ── cost blockers, locatable on the part (the relink, surfaced) ── */}
      {costBlockers && costBlockers.length > 0 && (
        <Card>
          <CardContent compact className="space-y-2">
            <div className="flex items-baseline justify-between">
              <span className="cv-eyebrow">Cost blockers</span>
              <span className="text-micro text-muted-foreground">DFM · on this route</span>
            </div>
            <ul className="space-y-1.5">
              {costBlockers.map((b) => {
                const locatable = b.faces.length > 0;
                const active = selectedKey === b.key;
                return (
                  <li key={b.key} className="flex items-start gap-2 text-xs">
                    <span className="flex-1 leading-snug text-muted-foreground">
                      <span className="num text-foreground">{b.issue.code}</span> — {b.issue.message}
                    </span>
                    {locatable && onLocateBlocker ? (
                      <button
                        type="button"
                        aria-pressed={active}
                        onClick={() => onLocateBlocker(active ? null : b.key)}
                        className={`inline-flex shrink-0 items-center gap-1 rounded-[var(--radius-sm)] border px-1.5 py-0.5 text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                          active
                            ? "border-accent-text bg-accent/10 text-accent-text"
                            : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground"
                        }`}
                      >
                        <Crosshair className="size-3" aria-hidden />
                        {active ? "Locating" : "Locate"}
                      </button>
                    ) : (
                      // Honest: this blocker carried no face indices from the
                      // relink — it applies to the whole part, so no locate.
                      <span className="shrink-0 text-[11px] text-muted-foreground">whole part</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* ── the make-vs-buy scrubber (live-flips the recommendation) ───── */}
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

      {/* ── crossover chart (re-housed BreakevenChart) ────────────────── */}
      <Card>
        <CardContent compact>
          <div className="mb-2 flex items-center justify-between">
            <span className="cv-eyebrow">Make-vs-buy crossover</span>
            <span className="text-micro text-muted-foreground">$/unit vs quantity</span>
          </div>
          <BreakevenChart
            breakeven={breakeven}
            qty={qty}
            recommendedProcess={rec?.curve.process ?? breakeven.makeNowProcess}
          />
          {dec.note && <p className="mt-2 text-xs text-muted-foreground">{dec.note}</p>}
        </CardContent>
      </Card>

      {/* ── open the glass box (the Decision depth panel) ─────────────── */}
      <Card>
        <button
          type="button"
          onClick={onOpenGlassBox}
          className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Boxes className="size-4 text-accent-text" aria-hidden />
          <span className="flex-1">
            <span className="text-sm font-semibold text-foreground">View glass box</span>
            <span className="ml-2 hidden text-xs text-muted-foreground sm:inline">
              drivers · provenance · Σ = unit cost · confidence
            </span>
          </span>
          <ChevronRight className="size-4 text-muted-foreground" />
        </button>
      </Card>

      {/* ── keepable artifact (real save/export/share endpoints) ──────── */}
      {costPersistUiEnabled() && report.saved && (
        <CostArtifactBar saved={report.saved} filename={filename} />
      )}
    </section>
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
