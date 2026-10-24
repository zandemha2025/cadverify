"use client";

/** O10: a file with several bodies. The product tree, part by part, in context. */
import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import type { InterferencePair, PartAnalysis, PartEstimate, PartInstance } from "@/lib/verify/assembly";
import { R } from "../routes";
import { cx } from "../ui";
import { retryAssemblyAnalysis, retryAssemblyView, type CheckSession } from "./store";
import { assemblyViews, serverStepText } from "./busy-state";
import { BusyNotice } from "./busy-notice";
import { MATERIAL_CLASS_LABEL, methodName, money, qtyWord, trimNum } from "./model";
import { SheetTop, type FigItem } from "./sheet-bits";
import "./part.css";

const StageCanvas = dynamic(() => import("@/components/verify/stage-canvas"), { ssr: false });

interface Design {
  key: string;
  name: string;
  instances: PartInstance[];
  analysis: PartAnalysis | null;
}

function makeNow(pa: PartAnalysis | null): PartEstimate | null {
  const ests = pa?.should_cost?.estimates ?? [];
  return ests.find((e) => e.process === pa?.should_cost?.make_now_process) ?? ests[0] ?? null;
}

function verdictOf(pa: PartAnalysis | null, ready: boolean): { chip: string; label: string } {
  if (!ready || !pa) return { chip: "c-unk", label: "Not analysed" };
  if (pa.error) return { chip: "c-bad", label: "Didn't analyse" };
  if (pa.cots?.is_cots) return { chip: "c-unk", label: "Buy" };
  const v = pa.dfm_summary?.verdict;
  return v === "pass" ? { chip: "c-ok", label: "Make" } : v === "fail" ? { chip: "c-bad", label: "Can't as drawn" } : { chip: "c-warn", label: "Make, check" };
}

function pairValue(p: InterferencePair): string {
  if (p.type === "contact") return p.min_gap_mm != null ? `${trimNum(p.min_gap_mm, 2)} mm` : "touching";
  if (p.penetration_vertices > 0) return `${p.penetration_vertices.toLocaleString("en-US")} points inside`;
  return p.min_gap_mm != null ? `gap ${trimNum(p.min_gap_mm, 2)} mm` : "overlap";
}

export function AssemblyView({ session, onPick }: { session: CheckSession; onPick: (f: File) => void }) {
  const a = session.assembly!;
  const model = a.model;
  const analysis = a.analysis;
  const ready = !!analysis;
  // Busy, or stopped on ScaleCAD's side: the analysis (sheet) and the 3D view (stage), as a part's are.
  const av = assemblyViews(session.busy, a);
  const sheetHeld = av.sheet ? (av.sheet.phase === "server" ? serverStepText(av.sheet.status).toLowerCase() : "waiting for room") : null;
  const [pick, setPick] = React.useState<string | null>(null);
  const [xray, setXray] = React.useState(false);
  const input = React.useRef<HTMLInputElement>(null);
  const designs = React.useMemo<Design[]>(() => {
    const byId = new Map((analysis?.per_part ?? []).map((p) => [p.id, p]));
    const groups = new Map<string, Design>();
    for (const inst of model.parts) {
      const k = inst.name || inst.occurrence || inst.id;
      const g = groups.get(k) ?? { key: k, name: k, instances: [], analysis: null };
      g.instances.push(inst);
      g.analysis = g.analysis ?? byId.get(inst.id) ?? null;
      groups.set(k, g);
    }
    return [...groups.values()].sort((x, y) => (y.instances[0]?.world?.volume ?? 0) - (x.instances[0]?.world?.volume ?? 0));
  }, [model.parts, analysis]);
  const sel = designs.find((d) => d.key === pick) ?? designs.find((d) => !d.analysis?.cots?.is_cots) ?? designs[0];
  const inst = sel?.instances[0] ?? null;
  const pa = sel?.analysis ?? null;
  const est = makeNow(pa);
  const qty = sel?.instances.length ?? 0;
  const pairs = (analysis?.interference.pairs ?? []).filter((p) => inst && (p.part_a.id === inst.id || p.part_b.id === inst.id));
  const cls = analysis?.cost_context.material_class ?? null;
  const sum = ready ? designs.reduce((n, d) => n + (d.analysis?.cots?.is_cots ? d.analysis.cots.buy_price_usd : makeNow(d.analysis)?.unit_cost_usd ?? 0) * d.instances.length, 0) : null;
  const made = designs.filter((d) => d.analysis && !d.analysis.cots?.is_cots);
  const bought = designs.filter((d) => d.analysis?.cots?.is_cots);
  const figs: FigItem[] = ready
    ? [
        { k: "Make", v: String(made.reduce((n, d) => n + d.instances.length, 0)), s: made.map((d) => d.name).slice(0, 3).join(", ") },
        { k: "Buy", v: String(bought.reduce((n, d) => n + d.instances.length, 0)), s: bought.map((d) => `${d.instances.length} ${d.name.toLowerCase()}`).join(", ") || "no standard hardware" },
        { k: "Sum of parts", v: money(sum), s: "1 assembly, per-part figures" },
      ]
    : [
        { k: "Parts", v: String(model.part_count), s: `${designs.length} designs` },
        sheetHeld
          ? { k: "Analysed", v: `0 of ${model.part_count}`, s: sheetHeld }
          : { k: "Analysed", v: `0 of ${model.part_count}`, s: a.analysisGate ? "pilot tool" : a.analyzing ? "analysing now" : a.glbLoading ? "after the 3D view" : "needs a retry", tone: "warn" },
      ];
  const s = analysis?.analysis_summary;
  const smeta = ready && s ? `${s.parts_analyzed} of ${s.parts_total} costed · ${s.interference_pairs} touching pairs · ${trimNum(s.elapsed_sec, 1)} s` : `${model.part_count} parts in the tree · ${sheetHeld ?? (a.analyzing ? "analysing…" : "not analysed")}`;
  const size = model.assembly ? model.assembly.bbox_max.map((v, i) => v - model.assembly.bbox_min[i]) : null;
  const bounds: [string, string, string, string][] = [
    ["Quantity", analysis?.boundaries.quantity ?? "True instance count of each design, counted from the product tree", "Fact", "s-file"],
    ["Yearly volume", analysis?.boundaries.annual_volume ?? "Quantity × assemblies a year; not in the geometry, so not shown", "Yours", "s-yours"],
    ["Material", analysis?.boundaries.material_class ?? "STEP carries no material: the class is a stated default", "Default", "s-typ"],
    ["Interference", analysis?.boundaries.interference ?? "Measured on the positioned meshes; a signal, not a verdict", "Measured", "s-file"],
    ["Service world", analysis?.boundaries.service_world ?? "Not inferred from position or role", "Not built", "s-typ"],
    ["Mating faces and tolerance stack-up", analysis?.boundaries.interface_dfm_and_gdt ?? "Needs AP242 and a B-rep kernel; not faked from triangles", "Pilot", "s-typ"],
  ];
  const alts = (pa?.should_cost?.estimates ?? []).filter((e) => e !== est && e.unit_cost_usd != null).sort((x, y) => (x.unit_cost_usd ?? 0) - (y.unit_cost_usd ?? 0)).slice(0, 3);
  return (
    <main className="world pv" aria-label="The assembly">
      <section className="stage" aria-label="The assembly">
        <div className="floor" />
        <div className="hud">
          <Link href={R.parts} style={{ fontSize: 12.5, textDecoration: "none", marginBottom: 2 }}>
            ‹ Parts
          </Link>
          <h1 title={session.file.name}>{session.file.name}</h1>
          <span className="num">
            Assembly · {model.part_count} parts · {designs.length} designs{size ? ` · ${size.map((n) => trimNum(n, 0)).join(" × ")} mm` : ""} · {model.source_suffix.toUpperCase()}
          </span>
          <span>
            Material {cls ? (MATERIAL_CLASS_LABEL[cls] ?? cls).toLowerCase() : "not set"}, a default: STEP carries none · quantities counted from the product tree
          </span>
        </div>
        <div className="ptools">
          <button className={cx("btn sm", xray && "ink")} type="button" aria-pressed={xray} aria-disabled={!a.glbUrl} onClick={() => a.glbUrl && setXray((x) => !x)} title={a.glbUrl ? "See through the parts" : "X-ray needs the 3D view"}>
            X-ray
          </button>
          <button className="btn sm" type="button" disabled title="Assemblies aren't saved as a record yet">
            Share
          </button>
          <button className="btn sm" type="button" disabled title="Assemblies aren't saved as a record yet">
            Export PDF
          </button>
        </div>
        {a.glbUrl ? (
          <div className="obj" role="img" aria-label={`The assembly with the ${sel?.name.toLowerCase() ?? "part"} highlighted. Drag to turn it.`} style={{ left: "calc(33% - 280px)", top: 140, width: 560, height: 560 }}>
            <span className="shade" />
            <StageCanvas renderUrl={null} renderKind={null} assemblyUrl={a.glbUrl} assemblySelectedId={inst?.id ?? null} bbox={null} xray={xray} hostile={false} autoOrbit={false} />
          </div>
        ) : av.stage ? (
          <div className="no3d">
            <b>No 3D view of the assembly yet</b>
            <BusyNotice view={av.stage} onRetry={av.stage.phase !== "waiting" ? () => retryAssemblyView(session.id) : undefined} />
            <span>The product tree is on the right.</span>
          </div>
        ) : a.glbLoading ? (
          <div className="no3d">
            <b>3D view loading…</b>
            <span>The product tree is on the right.</span>
          </div>
        ) : (
          <div className="no3d">
            <b>No 3D view of the assembly</b>
            <span>{a.gate === "pilot" ? "The assembly view is a pilot tool. The product tree is on the right." : a.glbError ?? "The 3D view couldn't be built."}</span>
          </div>
        )}
        {sel ? (
          <div style={{ position: "absolute", left: "calc(33% - 230px)", top: 716, width: 460, display: "flex", justifyContent: "center", gap: 8, flexWrap: "wrap" }}>
            <span className="tag" style={{ position: "static", flexDirection: "row", gap: 8, alignItems: "center", padding: "6px 12px" }}>
              <b style={{ fontSize: 13 }}>{sel.name}</b>instance 1 of {qty}
            </span>
            {pairs.length ? (
              <span className="tag" style={{ position: "static", flexDirection: "row", gap: 10, alignItems: "center", padding: "6px 12px" }}>
                <span>{pairs.filter((p) => p.type !== "contact").length} overlap</span>
                <span>{pairs.filter((p) => p.type === "contact").length} contact</span>
              </span>
            ) : null}
          </div>
        ) : null}
      </section>
      <aside className="sheet" aria-label="The assembly, part by part">
        <SheetTop title="Assembly" meta={smeta} figs={figs} />
        <div className="scroll">
          {av.sheet ? (
            <div className="swap" style={{ marginTop: 8 }}>
              <BusyNotice view={av.sheet} onRetry={av.sheet.phase !== "waiting" ? () => retryAssemblyAnalysis(session.id) : undefined} />
            </div>
          ) : a.analysisGate === "pilot" ? (
            <div className="note swap" role="alert" style={{ marginTop: 8 }}>
              <b>Assembly analysis is a pilot tool</b>
              <span>This plan covers single-part checks. The tree is here; per-part DFM, cost and interference come with a pilot or Enterprise plan.</span>
              <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <a className="btn ink sm" href="/contact">
                  Talk to us
                </a>
                <Link className="btn sm" href={R.billing}>
                  Plans
                </Link>
              </span>
            </div>
          ) : a.analysisError && !a.analyzing ? (
            <div className="note swap" role="alert" style={{ marginTop: 8 }}>
              <b>Per-part analysis didn’t finish</b>
              <span>The product tree{a.glbUrl ? " and the 3D view are" : " is"} ready. DFM, cost and interference need another try.</span>
              <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{a.analysisError}</span>
              <span>
                <button className="btn ink sm" type="button" onClick={() => retryAssemblyAnalysis(session.id)}>
                  Retry analysis
                </button>
              </span>
            </div>
          ) : null}
          <div className="gh">
            <span>Product tree</span>
            <span>each, at the counted quantity</span>
          </div>
          {designs.map((d) => {
            const v = verdictOf(d.analysis, ready);
            const e = makeNow(d.analysis);
            const on = sel?.key === d.key;
            const sub = !ready || !d.analysis
              ? d.instances[0]?.tree_path ?? ""
              : d.analysis.cots?.is_cots
                ? `Standard fastener · ${d.analysis.cots.identity?.designation ?? d.analysis.cots.nominal_size ?? d.analysis.cots.kind}`
                : `${methodName(e?.process)} · ${e?.material ?? ""} · DFM ${d.analysis.dfm_summary?.verdict ?? "—"}`;
            const cost = !ready || !d.analysis ? "—" : d.analysis.cots?.is_cots ? money(d.analysis.cots.buy_price_usd) : money(e?.unit_cost_usd);
            return (
              <button key={d.key} type="button" className={cx("mr", on && "on")} aria-pressed={on} onClick={() => setPick(d.key)}>
                <span>
                  <b>
                    {d.name}{" "}
                    <span className="num" style={{ fontWeight: 500, color: "var(--ink3)" }}>
                      × {d.instances.length}
                    </span>
                  </b>
                  <small>{sub}</small>
                </span>
                <span className={`chip ${v.chip}`}>
                  <i />
                  {v.label}
                </span>
                <span className="c num">{cost}</span>
              </button>
            );
          })}
          {sel && inst ? (
            <div className="swap">
              <div className="gh">
                <span>
                  {sel.name} · instance 1 of {qty}
                </span>
                <span />
              </div>
              <p className="mono" style={{ margin: "0 12px 2px", fontSize: 11.5, color: "var(--ink3)", overflowWrap: "anywhere" }}>
                {inst.tree_path}
              </p>
              <div className="kv">
                <span>Size</span>
                <b className="num">{inst.world?.bbox_size ? `${inst.world.bbox_size.map((n) => trimNum(n, 1)).join(" × ")} mm` : "—"}</b>
                <span>Volume</span>
                <b className="num">{inst.world?.volume != null ? `${Math.round(inst.world.volume).toLocaleString("en-US")} mm³` : "—"}</b>
                <span>B-rep faces</span>
                <b className="num">{inst.geometry_summary?.num_boundary_faces ?? "—"}</b>
                <span>Triangles</span>
                <b className="num">{inst.geometry_summary?.num_triangles?.toLocaleString("en-US") ?? "—"}</b>
                <span>Centroid, mm</span>
                <b className="num">{inst.world?.centroid ? inst.world.centroid.map((n) => trimNum(n, 1)).join(", ") : "—"}</b>
                <span>In this assembly</span>
                <b className="num">{qty}, counted from the tree</b>
              </div>
              {ready && pa && !pa.cots?.is_cots && est ? (
                <div className="note" style={{ marginTop: 4 }}>
                  <b>
                    {money(est.unit_cost_usd)} each at {pa.should_cost?.cost_quantity ?? est.quantity ?? qty} · {methodName(est.process)} · {est.material}
                  </b>
                  <span>
                    {est.lead_time ? `${Math.round(est.lead_time.low_days)}–${Math.round(est.lead_time.high_days)} days · ` : ""}
                    {est.est_error_band_pct != null ? `±${trimNum(est.est_error_band_pct, 0)}%, typical values` : "typical values"}
                    {pa.should_cost?.crossover_qty ? ` · tooling crossover ≈ ${qtyWord(Math.round(pa.should_cost.crossover_qty))} parts` : " · no tooling crossover"}
                  </span>
                  {alts.length ? (
                    <span className="kv" style={{ padding: "2px 0 0" }}>
                      {alts.map((x) => (
                        <React.Fragment key={`${x.process}-${x.material}`}>
                          <span>
                            {methodName(x.process)}, {x.material}
                            {x.dfm_verdict === "fail" ? " (after redesign)" : ""}
                          </span>
                          <b className="num">{money(x.unit_cost_usd)}</b>
                        </React.Fragment>
                      ))}
                    </span>
                  ) : null}
                </div>
              ) : null}
              {ready && pa?.cots?.is_cots ? (
                <div className="note" style={{ marginTop: 4 }}>
                  <b>Buy it, don&apos;t make it</b>
                  <span>
                    {pa.cots.identity?.designation ?? pa.cots.nominal_size ?? pa.cots.kind} · {money(pa.cots.buy_price_usd)} each, {money(pa.cots.buy_price_range_usd[0])}–{money(pa.cots.buy_price_range_usd[1])} · {qty} in this assembly
                  </span>
                  <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Catalog estimate for a common size and grade, single unit; not a quote. Size read from the geometry, not a thread spec.</span>
                </div>
              ) : null}
              {ready && pa?.error ? (
                <div className="note" role="alert" style={{ marginTop: 4 }}>
                  <b>This part didn&apos;t analyse</b>
                  <span>{pa.error.message}</span>
                </div>
              ) : null}
              {ready && pa?.dfm_summary ? (
                <>
                  <div className="gh">
                    <span>DFM</span>
                    <span>
                      <span className={`chip ${pa.dfm_summary.verdict === "pass" ? "c-ok" : pa.dfm_summary.verdict === "fail" ? "c-bad" : "c-warn"}`}>
                        <i />
                        {pa.dfm_summary.verdict === "pass" ? "Pass" : pa.dfm_summary.verdict === "fail" ? "Fail" : "Issues"}
                      </span>
                    </span>
                  </div>
                  <p style={{ margin: "0 12px", color: "var(--ink2)", fontSize: 13 }}>
                    {pa.dfm_summary.top_issues.length ? pa.dfm_summary.top_issues.slice(0, 2).map((i) => i.message).join(" ") : pa.dfm_summary.verdict === "pass" ? "Passes DFM." : "No individual findings listed for this design."}
                    {pa.dfm_summary.best_process ? ` Most makeable: ${methodName(pa.dfm_summary.best_process).toLowerCase()}.` : ""}
                  </p>
                </>
              ) : null}
              {ready ? (
                <>
                  <div className="gh">
                    <span>Touching parts, instance 1</span>
                    <span>{pairs.length} pairs</span>
                  </div>
                  {pairs.length ? (
                    <div className="lines">
                      {pairs.slice(0, 8).map((p, i) => {
                        const other = p.part_a.id === inst.id ? p.part_b : p.part_a;
                        return (
                          <div className="ln" key={i}>
                            <span>{other.name}</span>
                            <span className={`chip ${p.type === "contact" ? "c-unk" : "c-warn"}`} style={{ height: 20 }}>
                              <i />
                              {p.type === "contact" ? "contact" : "overlap"}
                            </span>
                            <b className="num">{pairValue(p)}</b>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                  <p style={{ margin: "6px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>Measured on the positioned meshes. A bolt through a hole or a nut on a thread is expected to overlap; this is a signal to read, not a fault.</p>
                </>
              ) : null}
            </div>
          ) : null}
          <div className="gh" style={{ marginTop: 6 }}>
            <span>What these numbers rest on</span>
            <span />
          </div>
          <div className="lines">
            {bounds.map(([k, t, tag, c]) => (
              <div className="ln" key={k} style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
                <span>
                  <b style={{ display: "block", textAlign: "left" }}>{k}</b>
                  <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{t}</span>
                </span>
                <span className={`src ${c}`}>{tag}</span>
              </div>
            ))}
          </div>
          <div className="note">
            <b>Yearly volume not declared</b>
            <span>Costs are at the per-assembly quantity only. Declare assemblies a year on the part&apos;s BOM link to see yearly figures.</span>
            <span>{session.key ? <Link className="btn sm" href={R.partHistory(session.key)}>Declare</Link> : null}</span>
          </div>
          <div className="gh" style={{ marginTop: 6 }}>
            <span>Check one part on its own</span>
            <span />
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "0 12px 8px" }}>
            <button className="btn sm" type="button" onClick={() => input.current?.click()}>
              Choose file
            </button>
            <input
              ref={input}
              type="file"
              accept=".step,.stp,.stl,.iges,.igs"
              aria-label="Choose a CAD file to check"
              tabIndex={-1}
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) onPick(f);
              }}
            />
          </div>
        </div>
      </aside>
    </main>
  );
}
