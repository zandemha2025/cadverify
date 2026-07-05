"use client";

/**
 * ACQUISITION CONSIDERATION — the not-owned route, stated as a capital question.
 *
 * The founder-approved "light instrument" modal recreated in the production stack
 * and wired to the REAL cost decision. It is a deeper view of the same make-vs-buy
 * the Verdict walk already surfaces: capex against marginal, org-wide, anchored on
 * the ENGINE's crossover.
 *
 * HONESTY (binding): the only figures presented as real are read off the persisted
 * CostReport decision — `crossover_qty` (the tooling break-even quantity), the
 * make-now (owned → marginal) and tooling (not-owned → acquire) PROCESS identities,
 * and the per-quantity unit costs the engine actually computed (`estimates`, the
 * same numbers the Verdict walk shows, tagged ○ MODEL because hours/costs are
 * MODEL). NO capex is invented: the standalone tool price, payback period, and the
 * shared-cell amortization / "which acquisition unlocks the most parts" org ranking
 * are NOT built — they render as explicit IN DEVELOPMENT, never fabricated. When
 * there is no cost, no decision, or no not-owned route, the honest empty state
 * shows — never a fake chart.
 */
import { useState } from "react";
import { C, MONO, USD, NUM, procLabel } from "@/lib/verify/tokens";
import type { VerifyResult } from "@/lib/verify/run";
import {
  makeNowEstimate,
  toolingEstimate,
  unitCostByQty,
  nearestQty,
  fractionToQty,
  qtyToFraction,
} from "@/lib/verify/derive";
import { Kicker, ProvChip, InDev, GhostButton, EmptyState } from "./primitives";

type Nav = (screen: string) => void;

interface Props {
  onClose: () => void;
  result: VerifyResult | null;
  nav: Nav;
}

// The chart's log quantity axis matches the derive helpers (1 → 10,000) so the
// crossover marker and the scrub agree with the Verdict walk exactly.
const Q_MIN = 1;
const Q_MAX = 10000;

export function AcquisitionModal({ onClose, result, nav }: Props) {
  const cost = result?.cost ?? null;
  const decision = cost?.decision ?? null;
  const makeProc = decision?.make_now_process ?? null;
  const toolProc = decision?.tooling_process ?? null;
  const crossover =
    decision?.crossover_qty != null && Number.isFinite(decision.crossover_qty)
      ? decision.crossover_qty
      : null;

  // Scrub starts at the crossover (the decision's hinge) when it exists.
  const [scrubFrac, setScrubFrac] = useState<number>(
    crossover ? qtyToFraction(crossover, Q_MIN, Q_MAX) : 0.5
  );

  return (
    <Overlay onClose={onClose}>
      <Header onClose={onClose} />

      {!cost ? (
        <div style={{ marginTop: 18 }}>
          <EmptyState
            title="No cost decision to consider yet"
            body="An acquisition consideration is computed from a part's cost decision — capex against your owned marginal route. Verify a part first; if it needs capability you don't own, its consideration is stated here."
          >
            <GhostButton primary onClick={onClose}>
              Go to Verify →
            </GhostButton>
          </EmptyState>
        </div>
      ) : !toolProc ? (
        <NoNotOwnedRoute makeProc={makeProc} note={decision?.note ?? null} onClose={onClose} />
      ) : (
        <FullConsideration
          cost={cost}
          makeProc={makeProc}
          toolProc={toolProc}
          crossover={crossover}
          scrubFrac={scrubFrac}
          setScrubFrac={setScrubFrac}
          toolingDfmReady={decision?.tooling_dfm_ready ?? false}
          note={decision?.note ?? null}
          nav={nav}
          onClose={onClose}
        />
      )}
    </Overlay>
  );
}

function Header({ onClose }: { onClose: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Kicker color={C.shop}>ACQUISITION CONSIDERATION — CAPABILITY YOU DON&apos;T OWN</Kicker>
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        style={{ marginLeft: "auto", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 14, color: C.ink40 }}
      >
        ✕
      </button>
    </div>
  );
}

/** The honest outcome when the engine found NO not-owned route: nothing to acquire. */
function NoNotOwnedRoute({
  makeProc,
  note,
  onClose,
}: {
  makeProc: string | null;
  note: string | null;
  onClose: () => void;
}) {
  return (
    <div style={{ marginTop: 14 }}>
      <h2 style={{ margin: 0, fontSize: 22, fontWeight: 300, letterSpacing: "-0.015em" }}>
        No acquisition needed
      </h2>
      <p style={{ margin: "8px 0 0", fontSize: 13, lineHeight: 1.6, color: C.ink55 }}>
        The engine routed this part on capability you already own
        {makeProc ? (
          <>
            {" "}—{" "}
            <span style={{ fontWeight: 500, color: C.ink }}>{procLabel(makeProc)}</span>, owned → marginal
          </>
        ) : null}
        . There is no not-owned route to weigh as a capital consideration.
      </p>
      {note && (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, lineHeight: 1.6, color: C.ink40 }}>
          engine note: {note}
        </p>
      )}
      <div style={{ marginTop: 18, display: "flex", justifyContent: "flex-end" }}>
        <GhostButton onClick={onClose}>Back to the verdict</GhostButton>
      </div>
    </div>
  );
}

function FullConsideration({
  cost,
  makeProc,
  toolProc,
  crossover,
  scrubFrac,
  setScrubFrac,
  toolingDfmReady,
  note,
  nav,
  onClose,
}: {
  cost: NonNullable<VerifyResult["cost"]>;
  makeProc: string | null;
  toolProc: string;
  crossover: number | null;
  scrubFrac: number;
  setScrubFrac: (f: number) => void;
  toolingDfmReady: boolean;
  note: string | null;
  nav: Nav;
  onClose: () => void;
}) {
  const scrubQty = fractionToQty(scrubFrac, Q_MIN, Q_MAX);
  const snappedQty = nearestQty(cost.quantities, scrubQty);
  const makeAt = makeNowEstimate(cost, snappedQty);
  const toolAt = toolingEstimate(cost, snappedQty);

  // Real per-quantity curves — only the points the engine actually costed.
  const makePts = [...unitCostByQty(cost, makeProc)]
    .map(([q, c]) => ({ q, c }))
    .sort((a, b) => a.q - b.q);
  const toolPts = [...unitCostByQty(cost, toolProc)]
    .map(([q, c]) => ({ q, c }))
    .sort((a, b) => a.q - b.q);

  // Which route wins at the scrubbed quantity — compared on the real numbers when
  // both are present, else falls back to the crossover position. Withheld if
  // neither the numbers nor a crossover exist.
  const below =
    makeAt && toolAt
      ? makeAt.unit_cost_usd <= toolAt.unit_cost_usd
      : crossover != null
        ? snappedQty <= crossover
        : null;

  return (
    <>
      <h2 style={{ margin: "14px 0 0", fontSize: 24, fontWeight: 300, letterSpacing: "-0.015em" }}>
        {procLabel(toolProc)} — capability you don&apos;t own
      </h2>
      <p style={{ margin: "8px 0 0", fontSize: 13, lineHeight: 1.6, color: C.ink55 }}>
        {crossover != null ? (
          <>
            Capex against marginal: the {procLabel(toolProc)} tool amortizes past{" "}
            <span style={{ fontWeight: 500, color: C.ink }}>{NUM(crossover)} units</span>
            {makeProc ? (
              <>
                {" "}vs your owned <span style={{ fontWeight: 500, color: C.ink }}>{procLabel(makeProc)}</span> route
              </>
            ) : (
              " vs your owned route"
            )}
            .
          </>
        ) : (
          <>
            The engine found no break-even at the quantities considered ({NUM(Q_MIN)}–{NUM(Q_MAX)}) — the{" "}
            {procLabel(toolProc)} tool does not pay back against your owned
            {makeProc ? <> {procLabel(makeProc)}</> : ""} route in this range.
          </>
        )}
        {!toolingDfmReady && (
          <>
            {" "}
            <span style={{ color: C.cond }}>Conditional on a DFM redesign of the tooling route.</span>
          </>
        )}
      </p>

      {/* ── the crossover chart — REAL points only ─────────────────────────── */}
      <CrossoverChart
        makePts={makePts}
        toolPts={toolPts}
        crossover={crossover}
        qtyMarker={snappedQty}
      />

      <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: "6px 18px", fontFamily: MONO, fontSize: 10.5, color: C.ink50 }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span aria-hidden style={{ width: 12, height: 2, background: C.pass }} />
          owned {procLabel(makeProc)} — marginal
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span aria-hidden style={{ width: 12, height: 2, background: C.shop, backgroundImage: `repeating-linear-gradient(90deg, ${C.shop} 0 5px, transparent 5px 8px)` }} />
          acquire {procLabel(toolProc)} — incl. amortized tooling
        </span>
        <span style={{ marginLeft: "auto" }}>
          {crossover != null ? <>crossover ≈ {NUM(crossover)}</> : "no crossover"}
        </span>
      </div>

      {/* ── scrub + per-unit readout at the selected quantity ──────────────── */}
      <div style={{ marginTop: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <span style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em", color: C.ink45 }}>
            AT QUANTITY <span style={{ color: C.ink }}>{NUM(snappedQty)}</span>
            <span style={{ color: C.ink40 }}> · nearest real point</span>
          </span>
          <ProvChip p="MODEL" />
        </div>
        <input
          type="range"
          min={0}
          max={1000}
          step={1}
          value={Math.round(scrubFrac * 1000)}
          onChange={(e) => setScrubFrac(Number(e.target.value) / 1000)}
          aria-label="Quantity"
          style={{ width: "100%", marginTop: 8, accentColor: C.ink }}
        />
        <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <RouteCell
            label={`${procLabel(makeProc)} — OWNED → MARGINAL`}
            color={C.pass}
            unit={makeAt?.unit_cost_usd}
            sub="/unit marginal"
            wins={below === true}
            border="rgba(31,138,91,0.35)"
            bg="rgba(31,138,91,0.02)"
          />
          <RouteCell
            label={`${procLabel(toolProc)} — NOT OWNED → ACQUIRE`}
            color={C.shop}
            unit={toolAt?.unit_cost_usd}
            sub="/unit incl. tooling"
            wins={below === false}
            border="rgba(176,120,24,0.35)"
            bg="rgba(176,120,24,0.03)"
          />
        </div>
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 9.5, lineHeight: 1.6, color: C.ink40 }}>
          both figures are engine cost-model outputs (○ MODEL — hours &amp; rates modeled from your calibration, not
          measured). The tooling figure amortizes the engine&apos;s fixed tool cost into each unit.
        </p>
      </div>

      {/* ── org-wide capex planning — HONEST IN DEVELOPMENT (no invented capex) ── */}
      <div style={{ marginTop: 16, border: `1px solid ${C.hair}`, borderRadius: 12, background: C.bg, padding: "14px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <p style={{ margin: 0, fontSize: 13.5, fontWeight: 500 }}>Capital &amp; payback, org-wide</p>
          <InDev />
        </div>
        <p style={{ margin: "8px 0 0", fontSize: 12.5, lineHeight: 1.6, color: C.ink60 }}>
          The engine computes the break-even quantity{crossover != null ? <> (<span style={{ fontFamily: MONO }}>{NUM(crossover)}</span> units)</> : ""}. The
          standalone tool price, payback period, and shared-cell amortization across the rest of your BOM —
          which parts one acquisition unlocks, and how the fixed cost spreads — are designed and not yet wired.
          No capex figure is invented here.
        </p>
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
          binds to the capability-investment ranking (parts × shared cell) — decision.crossover_qty is live today
        </p>
      </div>

      {note && (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, lineHeight: 1.6, color: C.ink40 }}>
          engine note: {note}
        </p>
      )}

      {/* ── actions ──────────────────────────────────────────────────────── */}
      <div style={{ marginTop: 18, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <GhostButton onClick={() => nav("triage")}>See parts that need new capability →</GhostButton>
        <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8 }}>
          <InDev label="ADD TO CAPABILITY PLAN — PENDING" />
        </span>
        <GhostButton onClick={onClose}>Not now</GhostButton>
      </div>
    </>
  );
}

function RouteCell({
  label,
  color,
  unit,
  sub,
  wins,
  border,
  bg,
}: {
  label: string;
  color: string;
  unit: number | null | undefined;
  sub: string;
  wins: boolean;
  border: string;
  bg: string;
}) {
  return (
    <div style={{ border: `1.5px solid ${wins ? border : C.hair}`, borderRadius: 12, padding: "13px 15px", background: wins ? bg : C.panel }}>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.08em", color }}>
        {label}
        {wins && <span style={{ color: C.ink }}> · WINS HERE</span>}
      </p>
      <p style={{ margin: "8px 0 0", fontSize: 24, fontWeight: 300, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>
        {USD(unit)} <span style={{ fontSize: 12, color: C.ink45 }}>{sub}</span>
      </p>
    </div>
  );
}

interface Pt {
  q: number;
  c: number;
}

/** The crossover chart. Draws the engine's REAL costed points as polylines (a dot
 *  at each real quantity), plus the crossover and current-quantity markers. Nothing
 *  is interpolated into a fabricated formula — the line only connects real points.
 *  y-axis auto-scales to the owned route's range so the crossover is legible; a very
 *  tall tooling point at low volume clips at the top rather than flattening the
 *  chart (the same readable framing the design used). */
function CrossoverChart({
  makePts,
  toolPts,
  crossover,
  qtyMarker,
}: {
  makePts: Pt[];
  toolPts: Pt[];
  crossover: number | null;
  qtyMarker: number;
}) {
  const clampQ = (q: number) => Math.min(Q_MAX, Math.max(Q_MIN, q));
  const xOf = (q: number) => 24 + (Math.log10(clampQ(q)) / 4) * 330;

  const makeMax = makePts.length ? Math.max(...makePts.map((p) => p.c)) : 0;
  const toolMin = toolPts.length ? Math.min(...toolPts.map((p) => p.c)) : 0;
  const base = makeMax > 0 ? makeMax : toolMin > 0 ? toolMin : 1;
  const yMax = base * 1.9;
  const yOf = (c: number) => 128 - (Math.min(yMax, Math.max(0, c)) / yMax) * 122;

  const path = (pts: Pt[]) =>
    pts.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(p.q).toFixed(1)} ${yOf(p.c).toFixed(1)}`).join(" ");

  return (
    <svg viewBox="0 0 360 150" style={{ width: "100%", display: "block", marginTop: 16 }} role="img" aria-label="Make-vs-acquire crossover">
      {/* axes */}
      <line x1="24" y1="6" x2="24" y2="128" stroke={C.hair} strokeWidth="1" />
      <line x1="24" y1="128" x2="354" y2="128" stroke={C.hair} strokeWidth="1" />

      {/* crossover marker (real) */}
      {crossover != null && (
        <line x1={xOf(crossover)} y1="6" x2={xOf(crossover)} y2="128" stroke="rgba(23,24,26,0.3)" strokeWidth="1" strokeDasharray="3 3" />
      )}

      {/* owned (marginal) — solid green */}
      {makePts.length > 1 && <path d={path(makePts)} fill="none" stroke={C.pass} strokeWidth="1.8" />}
      {makePts.map((p) => (
        <circle key={`m${p.q}`} cx={xOf(p.q)} cy={yOf(p.c)} r="2.4" fill={C.pass} />
      ))}

      {/* acquire (incl. tooling) — dashed orange */}
      {toolPts.length > 1 && <path d={path(toolPts)} fill="none" stroke={C.shop} strokeWidth="1.8" strokeDasharray="5 3" />}
      {toolPts.map((p) => (
        <circle key={`t${p.q}`} cx={xOf(p.q)} cy={yOf(Math.min(yMax, p.c))} r="2.4" fill={C.shop} />
      ))}

      {/* current quantity marker (solid ink) */}
      <line x1={xOf(qtyMarker)} y1="6" x2={xOf(qtyMarker)} y2="128" stroke={C.ink} strokeWidth="1.2" />

      {/* axis endpoints */}
      <text x="24" y="146" fontFamily={MONO} fontSize="8.5" fill="rgba(23,24,26,0.35)" textAnchor="start">1</text>
      <text x="354" y="146" fontFamily={MONO} fontSize="8.5" fill="rgba(23,24,26,0.35)" textAnchor="end">10,000</text>
    </svg>
  );
}

function Overlay({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div
      data-screen-label="Acquisition consideration"
      style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(23,24,26,0.4)", backdropFilter: "blur(3px)", WebkitBackdropFilter: "blur(3px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 30 }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: 600, maxWidth: "100%", maxHeight: "88vh", overflowY: "auto", background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 18, boxShadow: "0 18px 60px -18px rgba(23,24,26,0.4)", padding: "26px 28px", animation: "vscreenIn 220ms cubic-bezier(0.2,0,0,1) both" }}
      >
        {children}
      </div>
    </div>
  );
}
