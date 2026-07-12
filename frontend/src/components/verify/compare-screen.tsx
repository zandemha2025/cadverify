"use client";

/**
 * COMPARE — the same part, two questions: which calibration, and which route.
 * Real GET /api/v1/cost-decisions/compare?ids=a,b (engine-computed structured
 * diff) for the deltas + crossover, plus each decision's /cost-decisions/{id}
 * detail for the honest confidence band on every figure (the compare endpoint
 * carries the numbers but not the bands, and DESIGN-DECISIONS is binding: a
 * figure is never presented fake-exact).
 *
 * NO fixtures: the two decisions are the user's own saved records, picked here.
 * Fewer than two records → the honest empty state, never invented rows. Every
 * ± band is read VERBATIM from the engine's per-estimate error band / confidence
 * (hatched = assumption n=0, solid = validated); a withheld band is stated, not
 * faked to an exact number.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchCostDecisions,
  fetchCostDecision,
  compareCostDecisions,
  type CostDecisionSummary,
  type CostDecisionDetail,
  type CostComparison,
} from "@/lib/api";
import { C, MONO, USD, NUM, procLabel, normProv } from "@/lib/verify/tokens";
import { fractionToQty, qtyToFraction, nearestQty, makeNowEstimate } from "@/lib/verify/derive";
import { Kicker, ProvChip, GhostButton, EmptyState, Spinner } from "./primitives";

/* ---- band lookup: process → qty → {pct, validated, n} from a detail report --- */
interface Band {
  pct: number | null;
  validated: boolean;
  n: number;
}
function bandIndex(detail: CostDecisionDetail | null): Map<string, Map<number, Band>> {
  const idx = new Map<string, Map<number, Band>>();
  for (const e of detail?.result?.estimates ?? []) {
    if (!e.process) continue;
    const inner = idx.get(e.process) ?? new Map<number, Band>();
    inner.set(e.quantity, {
      pct: Number.isFinite(e.est_error_band_pct) ? e.est_error_band_pct : null,
      validated: e.confidence?.validated ?? false,
      n: e.confidence?.n_samples ?? 0,
    });
    idx.set(e.process, inner);
  }
  return idx;
}
function bandFor(idx: Map<string, Map<number, Band>>, proc: string | null, qty: number): Band | null {
  if (!proc) return null;
  return idx.get(proc)?.get(qty) ?? null;
}
/** "$12.34 ±40% n=0" — the band read verbatim, hatched (n=…) until validated. */
function bandText(b: Band | null): string {
  if (!b || b.pct == null) return "band withheld";
  return b.validated ? `±${Math.round(b.pct)}% validated` : `±${Math.round(b.pct)}% n=${b.n}`;
}

export function CompareScreen({ nav }: { nav: (s: string) => void }) {
  const [records, setRecords] = useState<CostDecisionSummary[] | null>(null);
  const [listErr, setListErr] = useState<string | null>(null);
  const [idA, setIdA] = useState<string | null>(null);
  const [idB, setIdB] = useState<string | null>(null);

  const [cmp, setCmp] = useState<CostComparison | null>(null);
  const [detA, setDetA] = useState<CostDecisionDetail | null>(null);
  const [detB, setDetB] = useState<CostDecisionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [cmpErr, setCmpErr] = useState<string | null>(null);

  const [qty, setQty] = useState<number | null>(null); // panel-1 chosen qty
  const [routeSide, setRouteSide] = useState<"a" | "b">("a"); // panel-2 which decision's routes
  const [scrubFrac, setScrubFrac] = useState(0.5);
  const reqRef = useRef(0);

  // 1) the record picker — the org's own saved decisions (most recent first).
  useEffect(() => {
    fetchCostDecisions({ limit: 100 }).then(
      (page) => {
        setRecords(page.cost_decisions);
        if (page.cost_decisions.length >= 2) {
          setIdA(page.cost_decisions[0].id);
          setIdB(page.cost_decisions[1].id);
        }
      },
      (e) => {
        setRecords([]);
        setListErr(e instanceof Error ? e.message : "Could not load records");
      }
    );
  }, []);

  // 2) load the engine-computed diff + both details whenever the pair changes.
  useEffect(() => {
    if (!idA || !idB || idA === idB) {
      setCmp(null);
      setDetA(null);
      setDetB(null);
      return;
    }
    const seq = ++reqRef.current;
    setLoading(true);
    setCmpErr(null);
    Promise.all([
      compareCostDecisions(idA, idB),
      fetchCostDecision(idA),
      fetchCostDecision(idB),
    ]).then(
      ([c, a, b]) => {
        if (seq !== reqRef.current) return;
        setCmp(c);
        setDetA(a);
        setDetB(b);
        setQty(null); // reset to the default (largest shared qty) below
        setLoading(false);
      },
      (e) => {
        if (seq !== reqRef.current) return;
        setCmpErr(e instanceof Error ? e.message : "Could not build the comparison");
        setCmp(null);
        setDetA(null);
        setDetB(null);
        setLoading(false);
      }
    );
  }, [idA, idB]);

  const idxA = useMemo(() => bandIndex(detA), [detA]);
  const idxB = useMemo(() => bandIndex(detB), [detB]);

  // shared quantities where BOTH decisions were costed (engine points, no interpolation).
  const sharedQtys = useMemo(() => {
    if (!cmp) return [];
    return cmp.unit_cost_by_qty
      .filter((r) => r.a?.unit_cost_usd != null && r.b?.unit_cost_usd != null)
      .map((r) => r.quantity)
      .sort((x, y) => x - y);
  }, [cmp]);
  const effQty = qty ?? (sharedQtys.length ? sharedQtys[sharedQtys.length - 1] : null);

  const onScrub = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setScrubFrac(Number(e.target.value) / 1000);
  }, []);

  // ---- gates: loading list / empty / errors -------------------------------
  if (records === null) {
    return (
      <Frame>
        <div style={{ marginTop: 24 }}><Spinner label="loading your records…" /></div>
      </Frame>
    );
  }
  if (records.length < 2) {
    return (
      <Frame>
        <div style={{ marginTop: 24, maxWidth: 640 }}>
          <EmptyState
            title={records.length === 0 ? "Nothing to compare yet." : "Compare needs two records."}
            body={
              records.length === 0
                ? "A comparison is two verified decisions held side by side — same part under two calibrations, or two routes across the crossover. Verify a part to make your first record."
                : "You have one saved decision. Verify the same part under a different calibration (or a second part) and this page will diff them — every figure banded, the delta engine-computed."
            }
          >
            <GhostButton primary onClick={() => nav("verify")}>Verify a part</GhostButton>
            <GhostButton onClick={() => nav("records")} style={{ marginLeft: 8 }}>See records</GhostButton>
          </EmptyState>
        </div>
        {listErr && <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>couldn&apos;t load records — {listErr}</p>}
      </Frame>
    );
  }

  const labelOf = (id: string | null) => {
    const r = records.find((x) => x.id === id);
    return r ? (r.label || r.filename) : "—";
  };

  return (
    <Frame nav={nav}>
      {/* the pair picker — real records, A vs B */}
      <div style={{ marginTop: 20, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, maxWidth: 1100 }}>
        <Kicker color={C.ink45}>PICK TWO RECORDS</Kicker>
        <RecordSelect label="A" value={idA} onChange={setIdA} records={records} disabledId={idB} />
        <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink40 }}>vs</span>
        <RecordSelect label="B" value={idB} onChange={setIdB} records={records} disabledId={idA} />
      </div>

      {idA === idB && (
        <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.cond }}>
          pick two different records — a decision compared to itself has no delta.
        </p>
      )}
      {cmpErr && <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>couldn&apos;t compare — {cmpErr}</p>}
      {loading && <div style={{ marginTop: 20 }}><Spinner label="building the comparison…" /></div>}

      {cmp && detA && detB && !loading && (
        <div style={{ marginTop: 22, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, maxWidth: 1100, alignItems: "start" }}>
          <CalibrationPanel
            cmp={cmp}
            detA={detA}
            detB={detB}
            idxA={idxA}
            idxB={idxB}
            labelA={labelOf(idA)}
            labelB={labelOf(idB)}
            sharedQtys={sharedQtys}
            qty={effQty}
            onQty={setQty}
          />
          <RoutePanel
            cmp={cmp}
            idxA={idxA}
            idxB={idxB}
            labelA={labelOf(idA)}
            labelB={labelOf(idB)}
            side={routeSide}
            onSide={setRouteSide}
            scrubFrac={scrubFrac}
            onScrub={onScrub}
          />
        </div>
      )}
    </Frame>
  );
}

/* ---- screen frame: title + subtitle in the light-instrument register -------- */
function Frame({ children, nav }: { children: React.ReactNode; nav?: (s: string) => void }) {
  return (
    <main style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "30px 34px", background: C.bg }}>
      {nav && (
        <button type="button" onClick={() => nav("records")} style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 11, letterSpacing: "0.1em", color: C.ink45 }}>← RECORDS</button>
      )}
      <h1 style={{ margin: nav ? "14px 0 0" : 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>Compare</h1>
      <p style={{ margin: "8px 0 0", maxWidth: 640, fontSize: 14, lineHeight: 1.6, color: C.ink55 }}>
        Same part, two questions: which calibration, and which route. Every figure is the engine&apos;s — banded, never fake-exact.
      </p>
      {children}
    </main>
  );
}

function RecordSelect({
  label,
  value,
  onChange,
  records,
  disabledId,
}: {
  label: string;
  value: string | null;
  onChange: (id: string) => void;
  records: CostDecisionSummary[];
  disabledId: string | null;
}) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
      <span style={{ fontFamily: MONO, fontSize: 11, color: C.ink50 }}>{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        style={{ maxWidth: 300, background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 8, padding: "8px 12px", fontFamily: MONO, fontSize: 12, color: C.ink, cursor: "pointer" }}
      >
        {records.map((r) => (
          <option key={r.id} value={r.id} disabled={r.id === disabledId}>
            {(r.label || r.filename)}{r.make_now_process ? ` · ${procLabel(r.make_now_process)}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

/* ============================ PANEL 1 — calibration ========================= */
function CalibrationPanel({
  cmp,
  detA,
  detB,
  idxA,
  idxB,
  labelA,
  labelB,
  sharedQtys,
  qty,
  onQty,
}: {
  cmp: CostComparison;
  detA: CostDecisionDetail;
  detB: CostDecisionDetail;
  idxA: Map<string, Map<number, Band>>;
  idxB: Map<string, Map<number, Band>>;
  labelA: string;
  labelB: string;
  sharedQtys: number[];
  qty: number | null;
  onQty: (q: number) => void;
}) {
  // per-process cost under A vs B at the chosen qty — from unit_costs_by_process.
  const procs = useMemo(() => {
    const set = new Set<string>([
      ...Object.keys(cmp.unit_costs_by_process.a),
      ...Object.keys(cmp.unit_costs_by_process.b),
    ]);
    return [...set].sort();
  }, [cmp]);

  const q = qty;
  const qs = q != null ? String(q) : null;
  const rows = procs
    .map((p) => {
      const a = qs ? cmp.unit_costs_by_process.a[p]?.[qs] ?? null : null;
      const b = qs ? cmp.unit_costs_by_process.b[p]?.[qs] ?? null : null;
      const delta = a != null && b != null && a !== 0 ? Math.round((100 * (b - a)) / a) : null;
      return { p, a, b, delta, bandA: q != null ? bandFor(idxA, p, q) : null, bandB: q != null ? bandFor(idxB, p, q) : null };
    })
    .filter((r) => r.a != null || r.b != null);

  // the engine's own recommended-route delta at this qty (never client-computed).
  const recRow = cmp.unit_cost_by_qty.find((r) => r.quantity === q) ?? null;

  const divergent = useMemo(() => topDivergentDriver(detA, detB, q ?? undefined), [detA, detB, q]);

  return (
    <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Kicker color={C.ink45}>CALIBRATION VS CALIBRATION</Kicker>
        {sharedQtys.length > 0 ? (
          <div style={{ marginLeft: "auto", display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
            {sharedQtys.map((sq) => (
              <button
                key={sq}
                type="button"
                onClick={() => onQty(sq)}
                style={{ border: `1px solid ${sq === q ? C.ink : C.hair}`, background: sq === q ? C.ink : "transparent", color: sq === q ? "#fff" : C.ink55, borderRadius: 999, padding: "4px 11px", fontFamily: MONO, fontSize: 10.5, cursor: "pointer" }}
              >
                {NUM(sq)}
              </button>
            ))}
          </div>
        ) : (
          <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10, color: C.cond }}>no shared quantity — pick two runs costed at the same qtys</span>
        )}
      </div>
      <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>{labelA} vs {labelB} · QTY {q != null ? NUM(q) : "—"}</p>

      <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr 64px", gap: 10, fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", color: C.ink40, paddingBottom: 8, borderBottom: `1px solid ${C.hair2}` }}>
        <span>PROCESS</span><span style={{ textAlign: "right" }}>A</span><span style={{ textAlign: "right" }}>B</span><span style={{ textAlign: "right" }}>Δ</span>
      </div>
      {rows.length === 0 ? (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>no per-process figures at this quantity.</p>
      ) : (
        rows.map((r) => (
          <div key={r.p} style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr 64px", gap: 10, padding: "10px 0", borderBottom: `1px solid #f0f0f3`, fontFamily: MONO, fontSize: 11.5, alignItems: "baseline" }}>
            <span style={{ color: C.ink }}>{procLabel(r.p)}</span>
            <Figure cost={r.a} band={r.bandA} />
            <Figure cost={r.b} band={r.bandB} />
            <span style={{ textAlign: "right", color: r.delta == null ? C.ink35 : r.delta < 0 ? C.pass : C.shop }}>
              {r.delta == null ? "—" : `${r.delta > 0 ? "+" : ""}${r.delta}%`}
            </span>
          </div>
        ))
      )}

      {recRow && recRow.delta_pct != null && (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink55 }}>
          recommended route Δ at qty {NUM(recRow.quantity)}: <span style={{ color: recRow.delta_pct < 0 ? C.pass : C.shop }}>{recRow.delta_pct > 0 ? "+" : ""}{recRow.delta_pct}%</span>
          {recRow.delta_usd != null ? ` (${recRow.delta_usd >= 0 ? "+" : "−"}${USD(Math.abs(recRow.delta_usd))}/unit)` : ""} · engine-computed
        </p>
      )}

      {divergent ? (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.shop, display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 6 }}>
          divergent driver: {divergent.label} {NUM(divergent.aVal)}{divergent.unit ? ` ${divergent.unit}` : ""}
          <ProvChip p={divergent.aProv} /> vs {NUM(divergent.bVal)}{divergent.unit ? ` ${divergent.unit}` : ""}
          <ProvChip p={divergent.bProv} /> — the rest track within noise
        </p>
      ) : (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>drivers track closely across both — the gap is mostly quantity effects</p>
      )}
      <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink35 }}>negotiate the driver, not the total</p>
    </section>
  );
}

/** A banded figure — cost with its ± band, never fake-exact. Withheld ≠ zero. */
function Figure({ cost, band }: { cost: number | null; band: Band | null }) {
  if (cost == null) return <span style={{ textAlign: "right", color: C.ink35 }}>—</span>;
  return (
    <span style={{ textAlign: "right", color: C.ink70, display: "inline-flex", flexDirection: "column", alignItems: "flex-end", lineHeight: 1.35 }}>
      <span>{USD(cost)}</span>
      <span style={{ fontSize: 9.5, color: band?.validated ? C.pass : C.cond }}>{bandText(band)}</span>
    </span>
  );
}

/* ============================== PANEL 2 — routes =========================== */
function RoutePanel({
  cmp,
  idxA,
  idxB,
  labelA,
  labelB,
  side,
  onSide,
  scrubFrac,
  onScrub,
}: {
  cmp: CostComparison;
  idxA: Map<string, Map<number, Band>>;
  idxB: Map<string, Map<number, Band>>;
  labelA: string;
  labelB: string;
  side: "a" | "b";
  onSide: (s: "a" | "b") => void;
  scrubFrac: number;
  onScrub: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  const sideIdx = side === "a" ? 0 : 1;
  const idx = side === "a" ? idxA : idxB;
  const makeProc = cmp.diff.make_now_process[sideIdx];
  const toolProc = cmp.diff.tooling_process[sideIdx];
  const crossover = cmp.diff.crossover_qty[sideIdx];
  const costs = side === "a" ? cmp.unit_costs_by_process.a : cmp.unit_costs_by_process.b;

  const makeCurve = useMemo(() => toPoints(makeProc ? costs[makeProc] : undefined), [costs, makeProc]);
  const toolCurve = useMemo(() => toPoints(toolProc ? costs[toolProc] : undefined), [costs, toolProc]);

  const quantities = useMemo(() => {
    const s = new Set<number>([...makeCurve.map((p) => p.q), ...toolCurve.map((p) => p.q)]);
    return [...s].sort((x, y) => x - y);
  }, [makeCurve, toolCurve]);

  const sideToggle = (
    <div style={{ marginLeft: "auto", display: "inline-flex", gap: 4 }}>
      {(["a", "b"] as const).map((s) => (
        <button key={s} type="button" onClick={() => onSide(s)} style={{ border: `1px solid ${s === side ? C.ink : C.hair}`, background: s === side ? C.ink : "transparent", color: s === side ? "#fff" : C.ink55, borderRadius: 999, padding: "4px 11px", fontFamily: MONO, fontSize: 10.5, cursor: "pointer" }}>
          {s.toUpperCase()}
        </button>
      ))}
    </div>
  );

  const header = (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <Kicker color={C.ink45}>ROUTE VS ROUTE</Kicker>
      {sideToggle}
    </div>
  );

  const label = side === "a" ? labelA : labelB;

  // No acquire/tooling alternative → honest: nothing crosses over.
  if (!toolProc || toolCurve.length === 0 || makeCurve.length === 0) {
    return (
      <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
        {header}
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>{label}</p>
        <div style={{ marginTop: 16, border: "1.5px dashed #d3d3d8", borderRadius: 12, padding: "22px 18px", textAlign: "center" }}>
          <p style={{ margin: 0, fontSize: 13.5, fontWeight: 500 }}>No acquire route to cross over.</p>
          <p style={{ margin: "7px 0 0", fontSize: 12, lineHeight: 1.6, color: C.ink50 }}>
            The engine offers make-now {makeProc ? `(${procLabel(makeProc)})` : ""} only for this decision — there is no
            tooling/acquisition route, so no crossover is computed. It is withheld, not invented.
          </p>
        </div>
      </section>
    );
  }

  // chart geometry (viewBox 0 0 360 150)
  const X0 = 24, X1 = 354, Y0 = 6, Y1 = 128;
  const minQ = quantities[0], maxQ = quantities[quantities.length - 1];
  const allCosts = [...makeCurve.map((p) => p.c), ...toolCurve.map((p) => p.c)];
  const minC = Math.min(...allCosts), maxC = Math.max(...allCosts);
  const xOf = (q: number) => X0 + qtyToFraction(q, minQ, maxQ) * (X1 - X0);
  const yOf = (c: number) => (maxC === minC ? (Y0 + Y1) / 2 : Y1 - ((c - minC) / (maxC - minC)) * (Y1 - Y0));
  const pathOf = (pts: { q: number; c: number }[]) => pts.map((p, i) => `${i === 0 ? "M" : "L"} ${xOf(p.q).toFixed(1)} ${yOf(p.c).toFixed(1)}`).join(" ");

  const snapQty = nearestQty(quantities, fractionToQty(scrubFrac, minQ, maxQ));
  const makeAt = makeCurve.find((p) => p.q === snapQty)?.c ?? null;
  const toolAt = toolCurve.find((p) => p.q === snapQty)?.c ?? null;
  const makeBand = bandFor(idx, makeProc, snapQty);
  const toolBand = bandFor(idx, toolProc, snapQty);
  const makeWins = makeAt != null && toolAt != null ? makeAt <= toolAt : null;
  const noteColor = makeWins == null ? C.ink50 : makeWins ? C.pass : C.cond;
  const note =
    makeWins == null
      ? "one route has no figure at this qty"
      : makeWins
      ? `make-now ${procLabel(makeProc)} is cheaper here`
      : `acquire ${procLabel(toolProc)} is cheaper here`;

  const crossX = crossover != null && crossover >= minQ && crossover <= maxQ ? xOf(crossover) : null;

  return (
    <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
      {header}
      <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
        {label} · <span style={{ color: C.pass }}>{procLabel(makeProc)}</span> (make-now) vs <span style={{ color: C.cond }}>{procLabel(toolProc)}</span> (acquire)
      </p>

      <svg viewBox="0 0 360 150" style={{ width: "100%", display: "block", marginTop: 14 }}>
        <line x1={X0} y1={Y0} x2={X0} y2={Y1} stroke={C.hair} strokeWidth={1} />
        <line x1={X0} y1={Y1} x2={X1} y2={Y1} stroke={C.hair} strokeWidth={1} />
        {crossX != null && <line x1={crossX} y1={Y0} x2={crossX} y2={Y1} stroke="rgba(23,24,26,0.3)" strokeWidth={1} strokeDasharray="3 3" />}
        <path d={pathOf(makeCurve)} fill="none" stroke={C.pass} strokeWidth={1.8} />
        <path d={pathOf(toolCurve)} fill="none" stroke={C.cond} strokeWidth={1.8} strokeDasharray="5 3" />
        <line x1={xOf(snapQty)} y1={Y0} x2={xOf(snapQty)} y2={Y1} stroke={C.ink} strokeWidth={1.2} />
      </svg>

      <input
        type="range"
        min={0}
        max={1000}
        step={1}
        value={Math.round(scrubFrac * 1000)}
        onChange={onScrub}
        aria-label="Quantity"
        style={{ width: "100%", marginTop: 10, accentColor: C.ink }}
      />
      <div style={{ marginTop: 4, display: "flex", justifyContent: "space-between", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
        <span>{NUM(minQ)}</span>
        <span>{crossover != null ? `crossover ≈ ${NUM(crossover)}` : "no crossover computed"}</span>
        <span>{NUM(maxQ)}</span>
      </div>

      <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 11, color: noteColor }}>qty {NUM(snapQty)} — {note}</p>
      <div style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink55, display: "flex", flexWrap: "wrap", gap: "2px 10px" }}>
        <span><span style={{ color: C.pass }}>make</span> {makeAt != null ? USD(makeAt) : "—"} <span style={{ color: makeBand?.validated ? C.pass : C.cond }}>{bandText(makeBand)}</span>/unit</span>
        <span><span style={{ color: C.cond }}>acquire</span> {toolAt != null ? USD(toolAt) : "—"} <span style={{ color: toolBand?.validated ? C.pass : C.cond }}>{bandText(toolBand)}</span>/unit</span>
      </div>
      <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
        the scrub snaps to computed quantities — costs between engine points are not interpolated
      </p>
    </section>
  );
}

/* ------------------------------ pure helpers ------------------------------- */
function toPoints(byQty: Record<string, number> | undefined): { q: number; c: number }[] {
  if (!byQty) return [];
  return Object.entries(byQty)
    .map(([k, v]) => ({ q: Number(k), c: v }))
    .filter((p) => Number.isFinite(p.q) && p.c != null && Number.isFinite(p.c))
    .sort((a, b) => a.q - b.q);
}

interface DivergentDriver {
  label: string;
  unit: string;
  aVal: number;
  bVal: number;
  aProv: ReturnType<typeof normProv>;
  bProv: ReturnType<typeof normProv>;
}
/** The make-now driver that diverges most between the two decisions — real values
 *  only, over driver names present on BOTH sides; null when nothing is comparable. */
function topDivergentDriver(
  detA: CostDecisionDetail,
  detB: CostDecisionDetail,
  qty?: number
): DivergentDriver | null {
  const ea = makeNowEstimate(detA.result, qty);
  const eb = makeNowEstimate(detB.result, qty);
  if (!ea || !eb) return null;
  const bMap = new Map(eb.drivers.map((d) => [d.name, d]));
  let best: DivergentDriver | null = null;
  let bestRel = 0.05; // ignore sub-5% noise
  for (const da of ea.drivers) {
    const db = bMap.get(da.name);
    if (!db) continue;
    const denom = Math.max(Math.abs(da.value), Math.abs(db.value));
    if (denom === 0) continue;
    const rel = Math.abs(da.value - db.value) / denom;
    if (rel > bestRel) {
      bestRel = rel;
      best = {
        label: da.name.replace(/_/g, " "),
        unit: da.unit === "usd" || da.unit === "each" ? "" : da.unit,
        aVal: da.value,
        bVal: db.value,
        aProv: normProv(da.provenance),
        bProv: normProv(db.provenance),
      };
    }
  }
  return best;
}
