"use client";

/**
 * ASSEMBLY CONTEXT PANEL — the right-hand surface when the upload is a real
 * multi-part assembly (>= 2 solids), in place of the single-part verdict walk.
 *
 * P2 delivered the in-design part-in-context render + part-of-interest selection.
 * P3b wires the REAL per-part analysis into it: each part row carries its true
 * quantity (a tree-counted FACT), its DFM verdict (the SAME pass/issues/fail the
 * single-part walk uses), and its should-cost unit price; the selected part opens
 * a detail area with its verdict, DFM issues, should-cost breakdown, quantity, and
 * its geometric interference/contact pairs (labelled a signal, NOT a fault). Every
 * number is rendered VERBATIM from the engine (assembly_analysis_service) — a part
 * that fails to analyse shows an honest per-part error, never a fabricated figure.
 * Same light-instrument idiom as VerifyScreen (Card / Kicker / mono evidence / the
 * pass·issues·fail status colour). The honesty `boundaries` block is surfaced, not
 * buried: quantity=FACT, annual volume=user-declared, material=DEFAULT assumption,
 * service-world=future suggestion, interface-DFM/GD&T=gated tier.
 */
import { useMemo, type ReactNode } from "react";
import { C, MONO, USD, procLabel, statusColor } from "@/lib/verify/tokens";

/** Fixed-decimal formatter for measured geometry — "—" when absent. */
function fx(n: number | null | undefined, dp: number): string {
  return n != null && Number.isFinite(n) ? n.toFixed(dp) : "—";
}
import { Card, Kicker, ProvChip, Spinner } from "./primitives";
import {
  looksLikeFastener,
  type AssemblyModel,
  type PartInstance,
  type AssemblyAnalysis,
  type PartAnalysis,
  type PartCots,
  type PartEstimate,
  type PartShouldCost,
  type InterferencePair,
} from "@/lib/verify/assembly";

/** The make-now should-cost estimate for a part — the row matching the engine's
 *  make_now_process, else the first estimate (a single quantity is costed). */
function makeNowEstimate(sc: PartShouldCost | undefined): PartEstimate | null {
  const ests = sc?.estimates ?? [];
  if (ests.length === 0) return null;
  const byProc = ests.find((e) => e.process === sc?.make_now_process);
  return byProc ?? ests[0];
}

/** The headline unit cost for a part, or null when the engine produced none
 *  (an error part or an honest GEOMETRY_INVALID refusal). Never invented. */
function unitCostOf(pa: PartAnalysis | undefined): number | null {
  if (!pa || pa.error) return null;
  const e = makeNowEstimate(pa.should_cost);
  return e?.unit_cost_usd ?? null;
}

/** verdict → light status tone. Falls back to slate for "unknown". */
function verdictColor(v: string | undefined): string {
  return v ? statusColor(v) : C.def;
}

/** The engine's lead-time band (days) → a compact string (never rendered raw:
 *  it is an OBJECT, not a string). "—" when absent. */
function leadTimeStr(lt: PartEstimate["lead_time"]): string {
  if (!lt || lt.low_days == null || lt.high_days == null) return "—";
  const lo = Number(lt.low_days);
  const hi = Number(lt.high_days);
  return lo === hi ? `${lo} days` : `${lo}–${hi} days`;
}

export function AssemblyPanel({
  model,
  fileName,
  selectedId,
  onSelect,
  analysis,
  analyzing,
}: {
  model: AssemblyModel;
  fileName: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** The REAL P3 per-part analysis, or null while it loads / if it fails. */
  analysis: AssemblyAnalysis | null;
  /** True while the per-part analysis is in flight (render is already up). */
  analyzing: boolean;
}) {
  const selected = useMemo(
    () => model.parts.find((p) => p.id === selectedId) ?? null,
    [model.parts, selectedId]
  );

  // Order for the picker: substantive parts (largest first), then hardware.
  const ordered = useMemo(() => {
    const byVol = (a: PartInstance, b: PartInstance) =>
      (b.world?.volume ?? 0) - (a.world?.volume ?? 0);
    const main = model.parts.filter((p) => !looksLikeFastener(p)).sort(byVol);
    const hw = model.parts.filter((p) => looksLikeFastener(p)).sort(byVol);
    return [...main, ...hw];
  }, [model.parts]);

  // id -> real analysis, so each tree row + the detail read the FACTs by part id.
  const byId = useMemo(() => {
    const m = new Map<string, PartAnalysis>();
    for (const p of analysis?.per_part ?? []) m.set(p.id, p);
    return m;
  }, [analysis]);

  // id -> "not analysed" reason (a bound bit — surfaced, never silently dropped).
  const notById = useMemo(() => {
    const m = new Map<string, string>();
    for (const n of analysis?.not_analyzed ?? []) m.set(n.id, n.reason);
    return m;
  }, [analysis]);

  // The selected part's real geometric contact/interference pairs.
  const selectedPairs = useMemo(() => {
    if (!selectedId) return [] as InterferencePair[];
    return (analysis?.interference.pairs ?? []).filter(
      (pr) => pr.part_a.id === selectedId || pr.part_b.id === selectedId
    );
  }, [analysis, selectedId]);

  const uniqueDesigns = Object.keys(model.unique_designs ?? {}).length;
  const selectedAnalysis = selectedId ? byId.get(selectedId) ?? null : null;
  const selectedNotAnalyzed = selectedId ? notById.get(selectedId) ?? null : null;

  return (
    <section
      style={{
        flex: 1,
        minWidth: 0,
        overflowY: "auto",
        background: C.bg,
        padding: "26px 30px 40px",
      }}
    >
      {/* Honest header — it is an ASSEMBLY, and what we do (and don't) claim. */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
        <div>
          <Kicker>ASSEMBLY CONTEXT</Kicker>
          <h2 style={{ margin: "6px 0 0", fontSize: 20, fontWeight: 400, letterSpacing: "-0.01em", color: C.ink }}>
            {fileName ?? "assembly"}
          </h2>
        </div>
        <span style={{ fontFamily: MONO, fontSize: 11, color: C.measured, whiteSpace: "nowrap" }}>
          ● {model.part_count} parts
        </span>
      </div>

      <p style={{ margin: "10px 0 0", fontSize: 13, lineHeight: 1.55, color: C.ink55 }}>
        Real STEP assembly — {model.part_count} solids, {uniqueDesigns} unique designs, in
        their baked world positions. Pick the part of interest to highlight it in context.
      </p>

      {/* Analysis status — the honest state of the REAL per-part run. */}
      <AnalysisStatus analysis={analysis} analyzing={analyzing} />

      {/* Part-of-interest picker — the real product tree, now carrying each
          part's real quantity + DFM verdict + should-cost. */}
      <Card>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
          <Kicker>PRODUCT TREE · PART OF INTEREST</Kicker>
          <ProvChip p="MEASURED" />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {ordered.map((p) => {
            const active = p.id === selectedId;
            const fastener = looksLikeFastener(p);
            const pa = byId.get(p.id);
            const na = notById.get(p.id);
            return (
              <button
                key={p.id}
                type="button"
                data-testid="assembly-part-row"
                data-selected={active}
                onClick={() => onSelect(p.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  width: "100%",
                  textAlign: "left",
                  border: active ? `1px solid ${C.user}` : `1px solid ${C.hair}`,
                  background: active ? "rgba(122,99,201,0.08)" : "#fff",
                  borderRadius: 9,
                  padding: "9px 11px",
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                <span
                  aria-hidden
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: fastener ? 2 : "50%",
                    background: active ? C.user : C.ink35,
                    flexShrink: 0,
                  }}
                />
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span style={{ display: "block", fontSize: 13, color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {p.name || p.occurrence || p.id}
                    {p.instance > 1 && (
                      <span style={{ color: C.ink40, fontFamily: MONO, fontSize: 11 }}> ·{p.instance}</span>
                    )}
                  </span>
                  <span style={{ display: "block", fontFamily: MONO, fontSize: 10, color: C.ink40, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {p.tree_path}
                  </span>
                </span>
                {/* REAL per-part readout: quantity (FACT) · verdict · unit cost. */}
                <RowReadout pa={pa} notAnalyzed={na} loading={analyzing && !analysis} fastener={fastener} />
              </button>
            );
          })}
        </div>
      </Card>

      {/* The selected part's REAL geometry + (when analysed) verdict/cost/contact. */}
      {selected && (
        <SelectedPartCard
          part={selected}
          analysis={selectedAnalysis}
          notAnalyzed={selectedNotAnalyzed}
          loading={analyzing && !analysis}
          pairs={selectedPairs}
        />
      )}

      {/* The honesty boundaries — FACT vs assumption vs suggestion vs gated tier. */}
      {analysis && <BoundariesCard analysis={analysis} />}
    </section>
  );
}

/** The per-part readout on a tree row: quantity · verdict dot · unit cost. Shows
 *  a loading tick while the analysis is in flight, an honest error/gate marker
 *  when a part could not be costed, and just "hardware" pre-analysis. */
function RowReadout({
  pa,
  notAnalyzed,
  loading,
  fastener,
}: {
  pa: PartAnalysis | undefined;
  notAnalyzed: string | undefined;
  loading: boolean;
  fastener: boolean;
}) {
  const qty = pa?.quantity;
  const cost = unitCostOf(pa);
  const verdict = pa?.dfm_summary?.verdict;
  const errored = !!pa?.error || pa?.should_cost?.status === "GEOMETRY_INVALID";
  const cots = pa?.cots?.is_cots ? pa.cots : null;

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, fontFamily: MONO }}>
      {qty != null && (
        <span
          title="Real instance count of this design in the assembly (a tree-counted FACT)"
          style={{ fontSize: 10.5, color: C.ink50 }}
        >
          ×{qty}
        </span>
      )}
      {pa && !errored && verdict && (
        <span
          title={`DFM verdict: ${verdict}`}
          style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
        >
          <span aria-hidden style={{ width: 7, height: 7, borderRadius: "50%", background: verdictColor(verdict) }} />
        </span>
      )}
      {/* COTS part: the row shows the BUY price, not the misleading machined figure. */}
      {pa && !errored && cots && (
        <span
          data-testid="row-cots-buy"
          title={`Standard off-the-shelf ${cots.nominal_size ? `${cots.nominal_size} ` : ""}${cots.kind} — BUY, not make. Catalog estimate (DEFAULT), not a live quote.`}
          style={{ display: "inline-flex", alignItems: "center", gap: 5, minWidth: 42, justifyContent: "flex-end" }}
        >
          {cots.nominal_size && (
            <span style={{ fontFamily: MONO, fontSize: 9.5, color: C.ink45 }}>{cots.nominal_size}</span>
          )}
          <span
            style={{
              fontSize: 9,
              letterSpacing: "0.06em",
              color: C.pass,
              border: `1px solid ${C.pass}`,
              borderRadius: 999,
              padding: "0 5px",
            }}
          >
            BUY
          </span>
          <span style={{ fontSize: 11.5, color: C.ink }}>{USD(cots.buy_price_usd)}</span>
        </span>
      )}
      {pa && !errored && !cots && cost != null && (
        <span style={{ fontSize: 11.5, color: C.ink, minWidth: 42, textAlign: "right" }}>{USD(cost)}</span>
      )}
      {pa && errored && (
        <span title={pa.error?.message ?? "engine could not cost this part"} style={{ fontSize: 9.5, color: C.fail }}>
          no cost
        </span>
      )}
      {!pa && notAnalyzed && (
        <span title={notAnalyzed} style={{ fontSize: 9.5, color: C.ink40 }}>not analysed</span>
      )}
      {!pa && !notAnalyzed && loading && (
        <span style={{ fontSize: 9.5, color: C.ink40 }}>…</span>
      )}
      {!pa && !notAnalyzed && !loading && fastener && (
        <span style={{ fontSize: 9.5, color: C.ink40 }}>hardware</span>
      )}
    </span>
  );
}

/** The status strip replacing the P2 "PER-PART ANALYSIS — COMING" gate. */
function AnalysisStatus({ analysis, analyzing }: { analysis: AssemblyAnalysis | null; analyzing: boolean }) {
  if (analyzing && !analysis) {
    return (
      <div
        data-testid="assembly-analysis-status"
        style={{ margin: "16px 0 20px", border: `1px solid ${C.hair}`, borderLeft: `3px solid ${C.cond}`, background: "#fff", borderRadius: 10, padding: "12px 14px" }}
      >
        <Spinner label="ANALYSING PER-PART — running DFM + should-cost on every solid" />
        <p style={{ margin: "7px 0 0", fontSize: 12, lineHeight: 1.5, color: C.ink55 }}>
          The same single-part engine runs on each solid in its assembly context (real
          quantity from the tree, real geometric interference). ~15s on an 18-part assembly.
        </p>
      </div>
    );
  }
  if (!analysis) {
    return (
      <div
        data-testid="assembly-analysis-status"
        style={{ margin: "16px 0 20px", border: `1px solid ${C.hair}`, borderLeft: `3px solid ${C.def}`, background: "#fff", borderRadius: 10, padding: "12px 14px" }}
      >
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.1em", color: C.def }}>
          PER-PART ANALYSIS — UNAVAILABLE
        </p>
        <p style={{ margin: "6px 0 0", fontSize: 12.5, lineHeight: 1.5, color: C.ink60 }}>
          The per-part DFM + should-cost run did not return for this upload. The render and
          measured geometry below are real; no verdict or cost is asserted without the engine.
        </p>
      </div>
    );
  }
  const s = analysis.analysis_summary;
  const cc = analysis.cost_context;
  return (
    <div
      data-testid="assembly-analysis-status"
      style={{ margin: "16px 0 20px", border: `1px solid ${C.hair}`, borderLeft: `3px solid ${C.pass}`, background: "#fff", borderRadius: 10, padding: "12px 14px" }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.1em", color: C.pass }}>
          PER-PART ANALYSIS — REAL
        </p>
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink50 }}>
          {s.parts_ok}/{s.parts_total} costed · {s.interference_pairs} contact pairs · {s.elapsed_sec}s
        </span>
      </div>
      <p style={{ margin: "6px 0 0", fontSize: 12.5, lineHeight: 1.5, color: C.ink60 }}>
        Each part run through the SAME DFM + should-cost engine, costed at its real
        per-assembly quantity ({cc.quantity_basis}); {cc.material_class} · {cc.region}, a
        DEFAULT assumption. {s.parts_errored > 0 && `${s.parts_errored} part(s) returned an honest per-part error. `}
        {s.parts_not_analyzed > 0 && `${s.parts_not_analyzed} not analysed (bound reached). `}
      </p>
    </div>
  );
}

function SelectedPartCard({
  part,
  analysis,
  notAnalyzed,
  loading,
  pairs,
}: {
  part: PartInstance;
  analysis: PartAnalysis | null;
  notAnalyzed: string | null;
  loading: boolean;
  pairs: InterferencePair[];
}) {
  const gs = part.geometry_summary;
  const w = part.world;
  const dims = w?.bbox_size ?? gs?.bbox_dims ?? null;
  const verdict = analysis?.dfm_summary?.verdict;
  const errored = !!analysis?.error || analysis?.should_cost?.status === "GEOMETRY_INVALID";
  return (
    <div style={{ marginTop: 16 }}>
      <Card>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
          <Kicker color={C.user}>SELECTED PART</Kicker>
          <ProvChip p="MEASURED" />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 400, color: C.ink }}>
            {part.name || part.occurrence || part.id}
          </h3>
          {analysis && !errored && verdict && (
            <span
              style={{
                fontFamily: MONO,
                fontSize: 10,
                letterSpacing: "0.06em",
                border: `1px solid ${verdictColor(verdict)}`,
                color: verdictColor(verdict),
                borderRadius: 999,
                padding: "2px 9px",
                textTransform: "uppercase",
              }}
            >
              DFM {verdict}
            </span>
          )}
          {analysis?.cots?.is_cots && (
            <span
              data-testid="cots-header-chip"
              title={analysis.cots.note}
              style={{
                fontFamily: MONO,
                fontSize: 10,
                letterSpacing: "0.06em",
                border: `1px solid ${C.pass}`,
                color: C.pass,
                borderRadius: 999,
                padding: "2px 9px",
                textTransform: "uppercase",
              }}
            >
              COTS · BUY
            </span>
          )}
          {analysis?.quantity != null && (
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink50 }} title="Real instance count in the assembly — a FACT from the product tree">
              ×{analysis.quantity} in assembly
            </span>
          )}
        </div>
        <p style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45, overflowWrap: "anywhere" }}>
          {part.tree_path}
        </p>
        <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Stat label="bbox (mm)" value={dims ? dims.map((n) => fx(n, 1)).join(" × ") : "—"} />
          <Stat label="volume (cm³)" value={w?.volume != null ? fx(w.volume / 1000, 2) : "—"} />
          <Stat label="B-rep faces" value={gs ? String(gs.num_boundary_faces) : "—"} />
          <Stat label="triangles" value={gs ? String(gs.num_triangles) : "—"} />
          <Stat
            label="centroid (mm)"
            value={w?.centroid ? w.centroid.map((n) => fx(n, 0)).join(", ") : "—"}
          />
          <Stat label="instance" value={`#${part.instance}`} />
        </div>

        {/* REAL should-cost + DFM detail (or an honest error / loading state). */}
        {analysis ? (
          <PartAnalysisDetail analysis={analysis} />
        ) : notAnalyzed ? (
          <DetailNote tone={C.def} kicker="NOT ANALYSED" body={notAnalyzed} />
        ) : loading ? (
          <div style={{ marginTop: 16 }}><Spinner label="costing this part…" /></div>
        ) : null}
      </Card>

      {/* Interference / geometric contact for the selected part — a SIGNAL. */}
      {analysis && <InterferenceCard pairs={pairs} selectedId={part.id} />}
    </div>
  );
}

/** The should-cost breakdown + DFM issues for the selected part. */
function PartAnalysisDetail({ analysis }: { analysis: PartAnalysis }) {
  if (analysis.error) {
    return (
      <DetailNote
        tone={C.fail}
        kicker={`PER-PART ERROR · ${analysis.error.code}`}
        body={analysis.error.message}
      />
    );
  }
  const sc = analysis.should_cost;
  if (sc?.status === "GEOMETRY_INVALID") {
    return (
      <DetailNote
        tone={C.cond}
        kicker="SHOULD-COST WITHHELD · GEOMETRY_INVALID"
        body={sc.reason ?? "The engine refused a cost for this part's geometry (volume ≤ 0 / non-watertight). Withheld, never faked."}
      />
    );
  }
  const est = makeNowEstimate(sc);
  const dfm = analysis.dfm_summary;
  const cots = analysis.cots?.is_cots ? analysis.cots : null;
  return (
    <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 14 }}>
      {/* should-cost headline. For a COTS fastener the BUY story (with an
          approximate size) leads; the wrong machined figure is dropped entirely. */}
      {cots ? (
        <CotsShouldCost cots={cots} sc={sc} />
      ) : (
      <div style={{ border: `1px solid ${C.hair}`, borderRadius: 12, padding: "13px 14px", background: C.sunken }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <Kicker>SHOULD-COST</Kicker>
          <ProvChip p="MODEL" />
        </div>
        {est ? (
          <>
            <div style={{ margin: "10px 0 0", display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontFamily: MONO, fontSize: 22, color: C.ink }}>{USD(est.unit_cost_usd)}</span>
              <span style={{ fontSize: 12, color: C.ink45 }}>/unit on {procLabel(est.process)}</span>
              {est.est_error_band_pct != null && (
                <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>±{Math.round(est.est_error_band_pct)}%</span>
              )}
            </div>
            <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <Stat label="quantity (fact)" value={sc?.cost_quantity != null ? `${sc.cost_quantity} @ per-assembly` : String(est.quantity ?? "—")} />
              <Stat label="material" value={est.material ?? sc?.make_now_material ?? "—"} />
              <Stat label="fixed / variable" value={`${USD(est.fixed_cost_usd)} / ${USD(est.variable_cost_usd)}`} />
              <Stat label="lead time" value={leadTimeStr(est.lead_time)} />
              <Stat label="crossover qty" value={sc?.crossover_qty != null ? String(sc.crossover_qty) : "—"} />
              <Stat label="make-now" value={procLabel(sc?.make_now_process)} />
            </div>
            <p style={{ margin: "11px 0 0", fontSize: 11.5, lineHeight: 1.5, color: C.ink55 }}>
              Recommendation: make in-house on {procLabel(sc?.make_now_process)}
              {sc?.make_now_material ? ` in ${sc.make_now_material}` : ""} at the per-assembly
              quantity{sc?.crossover_qty != null ? ` (crossover ≈ ${sc.crossover_qty})` : ""}.
            </p>
          </>
        ) : (
          <p style={{ margin: "8px 0 0", fontSize: 12, color: C.ink55 }}>No should-cost estimate returned for this part.</p>
        )}
      </div>
      )}

      {/* DFM summary — the same issues the single-part walk surfaces. */}
      {dfm && (
        <div style={{ border: `1px solid ${C.hair}`, borderRadius: 12, padding: "13px 14px", background: "#fff" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <Kicker>DFM</Kicker>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: verdictColor(dfm.verdict) }}>
              {dfm.verdict} · {dfm.issue_count} issue{dfm.issue_count === 1 ? "" : "s"}
            </span>
          </div>
          {/* A COTS part's recommendation is BUY (see the BUY card). A machined
              "best process" on standard hardware is incoherent noise — a thin hex
              nut is not sheet metal — so we do NOT present it for COTS parts. The
              geometric DFM findings below still show. */}
          <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink55 }}>
            {cots
              ? "best process n/a — standard part, BUY (see BUY card)"
              : `best process ${procLabel(dfm.best_process)}`}
          </p>
          {dfm.top_issues.length > 0 ? (
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 7 }}>
              {dfm.top_issues.map((i, k) => (
                <div key={`${i.code}-${k}`} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                  <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: statusColor(i.severity), flexShrink: 0, marginTop: 5 }} />
                  <span style={{ fontSize: 12, lineHeight: 1.45, color: C.ink70 }}>
                    <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink45 }}>{i.code}</span> — {i.message}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ margin: "8px 0 0", fontSize: 12, color: C.ink55 }}>No DFM issues flagged for this part.</p>
          )}
        </div>
      )}
    </div>
  );
}

/** The should-cost card for a COTS / standard-hardware part (bolt, nut, screw…).
 *  The BUY story LEADS (a labelled DEFAULT catalog estimate, not a live quote);
 *  the machined figure is DEMOTED to a clearly-labelled fabrication upper-bound —
 *  it is NOT the recommendation. This is the whole point of the fix: a $0.75 bolt
 *  must read BUY, never "$23.99 make-in-house". */
function CotsShouldCost({
  cots,
  sc,
}: {
  cots: PartCots;
  sc: PartShouldCost | undefined;
}) {
  const [low, high] = cots.buy_price_range_usd ?? [null, null];
  const size = cots.nominal_size ?? null;
  // The honest "fabrication not modeled" line, verbatim from the engine when present.
  const fabNote =
    sc?.cost_basis_note ??
    "Made-in-house fabrication is not modeled for standard hardware — source it as a catalog part.";
  return (
    <div
      data-testid="cots-should-cost"
      style={{ border: `1px solid ${C.hair}`, borderLeft: `3px solid ${C.pass}`, borderRadius: 12, padding: "13px 14px", background: C.sunken }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <Kicker>SHOULD-COST · BUY (STANDARD HARDWARE)</Kicker>
        <ProvChip p="DEFAULT" />
      </div>

      {/* PRIMARY: the BUY headline, LED by the approximate size so the buy price is
          sanity-checkable (≈M8 bolt · BUY ~$0.75/unit). */}
      <div style={{ margin: "11px 0 0", display: "flex", alignItems: "baseline", gap: 9, flexWrap: "wrap" }}>
        {size && (
          <span
            data-testid="cots-nominal-size"
            title={cots.nominal_size_note ?? "Approximate size inferred from geometry — not a verified thread spec."}
            style={{ fontFamily: MONO, fontSize: 13, color: C.ink, borderBottom: `1px dotted ${C.ink45}` }}
          >
            {size}
          </span>
        )}
        <span
          style={{ fontSize: 9.5, letterSpacing: "0.08em", color: C.pass, border: `1px solid ${C.pass}`, borderRadius: 999, padding: "2px 9px", fontFamily: MONO }}
        >
          BUY
        </span>
        <span style={{ fontFamily: MONO, fontSize: 22, color: C.ink }}>~{USD(cots.buy_price_usd)}</span>
        <span style={{ fontSize: 12, color: C.ink45 }}>/unit</span>
      </div>
      {size && (
        <p style={{ margin: "5px 0 0", fontSize: 10.5, lineHeight: 1.5, color: C.ink45 }}>
          {cots.nominal_size_note ??
            "Approximate size (≈) from geometry — a rough envelope, not a verified thread spec. No grade implied."}
        </p>
      )}
      <p style={{ margin: "8px 0 0", fontSize: 12.5, lineHeight: 1.5, color: C.ink70 }}>
        Standard off-the-shelf {cots.kind} — <b style={{ fontWeight: 500, color: C.ink }}>do not machine in-house</b>.
        {low != null && high != null && (
          <>
            {" "}Catalog range <span style={{ fontFamily: MONO, color: C.ink }}>{USD(low)}–{USD(high)}</span>.
          </>
        )}
      </p>

      {/* Honest provenance chip — a DEFAULT catalog estimate, NOT a live quote. */}
      <div style={{ marginTop: 10 }}>
        <span
          data-testid="cots-prov-chip"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontFamily: MONO,
            fontSize: 10,
            letterSpacing: "0.04em",
            color: C.def,
            border: `1px solid ${C.hair}`,
            borderRadius: 999,
            padding: "3px 10px",
            background: "#fff",
          }}
        >
          <span aria-hidden style={{ color: C.def }}>○</span>
          DEFAULT · catalog estimate ({cots.confidence} confidence), not a live quote
        </span>
      </div>

      {/* NO machined fab figure: an aluminium/sheet-metal cost for a steel fastener
          mis-models the physics, so we drop it and say so honestly instead. */}
      <div
        data-testid="cots-fab-not-modeled"
        style={{ marginTop: 12, border: `1px dashed ${C.hair}`, borderRadius: 9, padding: "9px 11px", background: "#fff" }}
      >
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 9, letterSpacing: "0.08em", color: C.ink40 }}>
          MADE-IN-HOUSE · NOT MODELED
        </p>
        <p style={{ margin: "4px 0 0", fontSize: 12, lineHeight: 1.5, color: C.ink55 }}>
          {fabNote}
        </p>
      </div>

      {/* The recommendation reads BUY — verbatim from the engine. */}
      <p style={{ margin: "11px 0 0", fontSize: 11.5, lineHeight: 1.5, color: C.ink60 }}>
        Recommendation: <b style={{ fontWeight: 500, color: C.pass }}>{cots.recommendation}</b>
      </p>
    </div>
  );
}

/** The name of the OTHER part in a pair (the neighbour the selected part touches). */
function otherPart(pair: InterferencePair, selectedId: string) {
  return pair.part_a.id === selectedId ? pair.part_b : pair.part_a;
}

/** The selected part's geometric contact/interference — HONESTLY a signal. */
function InterferenceCard({ pairs, selectedId }: { pairs: InterferencePair[]; selectedId: string }) {
  const neighbours = useMemo(() => {
    const names = new Set<string>();
    for (const pr of pairs) names.add(otherPart(pr, selectedId).name);
    return [...names];
  }, [pairs, selectedId]);
  return (
    <div style={{ marginTop: 16 }}>
      <Card>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
          <Kicker>GEOMETRIC CONTACT · INTERFERENCE</Kicker>
          <ProvChip p="MEASURED" />
        </div>
        {pairs.length === 0 ? (
          <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.5, color: C.ink55 }}>
            No geometric contact or interpenetration detected between this part and its
            neighbours (bbox-overlap prefilter → real mesh check cleared).
          </p>
        ) : (
          <>
            <p style={{ margin: "0 0 10px", fontSize: 12, lineHeight: 1.5, color: C.ink60 }}>
              Geometric contact with{" "}
              <b style={{ fontWeight: 500, color: C.ink }}>{neighbours.join(", ")}</b>. For
              fasteners (a bolt through a hole, a nut on a thread) this overlap is EXPECTED —
              it is a signal an engineer reads, NOT a fault verdict.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {pairs.map((pr, k) => (
                <InterferenceRow key={k} pair={pr} other={otherPart(pr, selectedId)} />
              ))}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function InterferenceRow({ pair, other }: { pair: InterferencePair; other: { name: string } }) {
  const tone = pair.type === "interpenetration" ? C.cond : C.measured;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        border: `1px solid ${C.hair}`,
        borderRadius: 8,
        padding: "8px 11px",
        background: C.sunken,
      }}
    >
      <span aria-hidden style={{ width: 7, height: 7, borderRadius: "50%", background: tone, flexShrink: 0 }} />
      <span style={{ flex: 1, minWidth: 0, fontSize: 12.5, color: C.ink }}>
        contact with {other.name}
      </span>
      <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink50, whiteSpace: "nowrap" }}>
        {pair.type}
        {pair.type === "contact" && pair.min_gap_mm != null ? ` · ${pair.min_gap_mm.toFixed(2)}mm` : ""}
        {pair.type === "interpenetration" ? ` · ${pair.penetration_vertices} v` : ""}
      </span>
    </div>
  );
}

/** The honesty boundaries — surfaced succinctly, verbatim from the engine. */
function BoundariesCard({ analysis }: { analysis: AssemblyAnalysis }) {
  const LABELS: Record<string, string> = {
    quantity: "Quantity — FACT",
    annual_volume: "Annual volume — USER-DECLARED",
    material_class: "Material — DEFAULT assumption",
    interference: "Interference — REAL geometry, not a verdict",
    service_world: "Service world — future SUGGESTION",
    interface_dfm_and_gdt: "Interface-DFM / GD&T — GATED tier",
  };
  const order = ["quantity", "annual_volume", "material_class", "interference", "service_world", "interface_dfm_and_gdt"];
  const keys = order.filter((k) => analysis.boundaries[k]);
  return (
    <div style={{ marginTop: 16 }}>
      <Card>
        <div style={{ marginBottom: 10 }}>
          <Kicker>HONEST BOUNDARIES · FACT vs ASSUMPTION vs GATE</Kicker>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
          {keys.map((k) => (
            <div key={k}>
              <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", color: C.ink50 }}>
                {LABELS[k] ?? k.toUpperCase()}
              </p>
              <p style={{ margin: "3px 0 0", fontSize: 11.5, lineHeight: 1.5, color: C.ink60 }}>
                {analysis.boundaries[k]}
              </p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function DetailNote({ tone, kicker, body }: { tone: string; kicker: string; body: ReactNode }) {
  return (
    <div style={{ marginTop: 16, border: `1px solid ${C.hair}`, borderLeft: `3px solid ${tone}`, borderRadius: 10, padding: "11px 13px", background: "#fff" }}>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: tone }}>{kicker}</p>
      <p style={{ margin: "5px 0 0", fontSize: 12, lineHeight: 1.5, color: C.ink60 }}>{body}</p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.08em", color: C.ink40 }}>
        {label.toUpperCase()}
      </p>
      <p style={{ margin: "3px 0 0", fontFamily: MONO, fontSize: 13, color: C.ink }}>{value}</p>
    </div>
  );
}
