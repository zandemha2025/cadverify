"use client";

/** O11: the part over time. Its checks and decisions, where it's used, the BOM link, and its standing. */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import {
  fetchCatalog,
  fetchCostDecision,
  fetchCostDecisions,
  fetchAnalysis,
  type CatalogRowApi,
  type CostDecisionDetail,
  type CostDecisionSummary,
  type ValidationResult,
} from "@/lib/api";
import { fetchPartContext, type PartContext } from "@/lib/verify/part-context-read";
import { assignContext } from "@/lib/verify/program-api";
import { bomAnnualVolume, fetchBomAncestry, type BomAncestry } from "@/lib/verify/bom";
import { readVerification } from "@/lib/verify/verification";
import { computeMeshHash } from "@/lib/verify/part-context";
import { CAD_ACCEPT } from "../pending-file";
import { R } from "../routes";
import { ConfirmButton, Empty, Failed, Loading, cx } from "../ui";
import { startCheck } from "./store";
import { loadPartMesh, recheckStored } from "./api";
import { listMachines, ownedProcessesFrom } from "@/lib/verify/machine-api";
import { MATERIAL_CLASS_LABEL, costLines, days, dimsText, methodName, money, qtyWord, shortId, trimNum } from "./model";
import type { ViewerController } from "./viewer";
import "./part.css";

const PartViewer = dynamic(() => import("./viewer"), { ssr: false });

const DISPOSITION: Record<string, string> = { inhouse: "Make in-house", outside: "Make outside", acquire: "Acquire capability", redesign: "Redesign" };

function when(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-US", { day: "numeric", month: "short" })}, ${d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}

function dotOf(row: CatalogRowApi): string {
  if (row.unit_cost?.withheld || row.route_blocker_count > 0) return "#B42318";
  if ((row.findings?.total ?? 0) > 0 && row.lifecycle_state === "Costed") return "#B97F0C";
  return row.lifecycle_state === "Costed" ? "#146C43" : "#5F656E";
}

function rowTitle(row: CatalogRowApi): string {
  const cost = row.unit_cost;
  if (cost?.withheld) return `${row.lifecycle_state} · price withheld`;
  if (cost?.usd != null) return `${row.lifecycle_state} · ${money(cost.usd)}${cost.qty ? ` at ${qtyWord(cost.qty)}` : ""}`;
  return row.lifecycle_state;
}

/** The latest record's headline: which route, what it costs, and how sure. */
function standingOf(d: CostDecisionDetail | null, row: CatalogRowApi | null) {
  if (!d) {
    return {
      chip: "c-unk",
      verdict: "Not priced",
      title: "Analyzed, not priced yet",
      line: row?.recommended_route ? `DFM route so far: ${methodName(row.recommended_route.process).toLowerCase()}. No should-cost until it’s priced.` : "No should-cost until it’s priced.",
      rows: [] as [string, string][],
      kicker: "Analysis only · no decision record",
    };
  }
  const r = d.result;
  const qs = [...(r.quantities ?? [])].sort((a, b) => a - b);
  const q = qs.includes(10) ? 10 : qs[0];
  const rec = r.decision?.recommendation?.[String(q)] ?? null;
  const est = rec ? r.estimates.find((e) => e.quantity === q && e.process === rec.process && e.material === rec.material) ?? null : null;
  const v = readVerification(r);
  const excluded = r.estimates.length > 0 && r.estimates.every((e) => e.environment_excluded);
  const kicker = `Latest check · ${shortId(d.id)} · ${when(d.created_at)}${v?.best_machine ? ` · fits your ${v.best_machine}` : ""}`;
  if (excluded || !rec) {
    const strikes = (v?.env_exclusions ?? []).map((f) => [f.axis || "material", f.human] as [string, string]);
    return { chip: "c-bad", verdict: excluded ? "Ruled out" : "Not priced", title: excluded ? "No route survives the declared conditions" : "No route was priced", line: excluded ? "Price withheld. The declared service conditions rule out every priced route." : r.reason ?? "The record has no recommendation.", rows: strikes.slice(0, 4), kicker };
  }
  const c = est?.confidence;
  const rows: [string, string][] = [];
  const inHouse = v?.best_machine ? r.estimates.find((e) => e.quantity === q && v.per_route?.[e.process]?.best_machine === v.best_machine && !e.environment_excluded) : null;
  if (inHouse) rows.push([`In-house on your ${v!.best_machine}`, `${money(inHouse.unit_cost_usd)} at ${qtyWord(q)}`]);
  const first = r.decision?.recommendation?.[String(qs[0])];
  if (first && qs[0] !== q) rows.push([`${methodName(first.process)}, ${first.material}`, `${money(first.unit_cost_usd)} at ${qtyWord(qs[0])}`]);
  if (est) rows.push(["Lead time", days(est.lead_time?.low_days, est.lead_time?.high_days)]);
  return {
    chip: rec.dfm_verdict === "fail" ? "c-bad" : "c-ok",
    verdict: rec.dfm_verdict === "fail" ? "Can't as drawn" : "Can make",
    title: `${methodName(rec.process)}, ${rec.material}`,
    line: `${money(rec.unit_cost_usd)} each at ${qtyWord(q)}${c ? ` · ${money(c.low_usd)}–${money(c.high_usd)}, a ±${trimNum(c.half_width_pct, 0)}% ${c.validated ? "measured band" : "assumption band, not yet checked against your jobs"}` : ""} · ${r.decision?.crossover_qty ? `tooling crossover ≈ ${qtyWord(Math.round(r.decision.crossover_qty))}` : "no tooling crossover"}`,
    rows,
    kicker,
  };
}

export function HistoryPage({ partKey }: { partKey: string }) {
  const router = useRouter();
  const [row, setRow] = React.useState<CatalogRowApi | null>(null);
  const [parts, setParts] = React.useState<CatalogRowApi[]>([]);
  const [latest, setLatest] = React.useState<CostDecisionDetail | null>(null);
  const [validation, setValidation] = React.useState<ValidationResult | null>(null);
  const [ctx, setCtx] = React.useState<PartContext | null>(null);
  const [state, setState] = React.useState<"loading" | "ready" | "error">("loading");
  const [err, setErr] = React.useState<string | null>(null);
  const [reload, setReload] = React.useState(0);
  const [mesh, setMesh] = React.useState<{ url: string; faceHash: string | null; origin: "cache" | "stored" } | null>(null);
  const [kept, setKept] = React.useState<boolean | null>(null);
  const controller = React.useRef(null) as ViewerController;
  const [, setVs] = React.useState("");
  const picker = React.useRef<HTMLInputElement>(null);
  const [recheckErr, setRecheckErr] = React.useState<string | null>(null);
  const [rechecking, setRechecking] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    setState("loading");
    (async () => {
      const [cat, list, context] = await Promise.all([
        fetchCatalog({ pageSize: 100 }),
        fetchCostDecisions({ meshHash: partKey, limit: 1 }),
        fetchPartContext(partKey),
      ]);
      if (!live) return;
      const mine = cat.rows.find((r) => r.part_key === partKey) ?? (await fetchCatalog({ partKey, pageSize: 1 }).then((p) => p.rows[0] ?? null).catch(() => null));
      setParts(cat.rows);
      setRow(mine);
      setCtx(context.context);
      const id = list.cost_decisions[0]?.id ?? mine?.cost_decision?.id ?? null;
      const [d, a] = await Promise.all([id ? fetchCostDecision(id).catch(() => null) : Promise.resolve(null), mine?.analysis?.id ? fetchAnalysis(mine.analysis.id).then((x) => x.result_json).catch(() => null) : Promise.resolve(null)]);
      if (!live) return;
      setLatest(d);
      setValidation(a);
      setState("ready");
    })().catch((e) => {
      if (!live) return;
      setErr(e instanceof Error ? e.message : "This part didn't load.");
      setState("error");
    });
    return () => {
      live = false;
    };
  }, [partKey, reload]);

  React.useEffect(() => {
    let url: string | null = null;
    let live = true;
    loadPartMesh(partKey, null).then((r) => {
      if (!live) return;
      setKept(r.kept);
      if (!r.mesh) return;
      url = URL.createObjectURL(r.mesh.blob);
      setMesh({ url, faceHash: r.mesh.faceHash, origin: r.mesh.origin });
    });
    return () => {
      live = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [partKey]);

  if (state === "error")
    return (
      <main className="world pv" aria-label="Part history">
        <div className="pagehead wide">
          <h1 className="ptitle">Part history</h1>
        </div>
        <div className="content full">
          <Failed title="This part's history didn't load" detail={err} onRetry={() => setReload((n) => n + 1)} />
        </div>
      </main>
    );
  const file = latest?.filename ?? row?.filename ?? validation?.filename ?? "Part";
  const g = validation?.geometry;
  const cg = latest?.result.geometry;
  const st = standingOf(latest, row);
  // The kept file: re-check from it, nothing to pick and no check used (POST /parts/{hash}/recheck).
  const recheckKept = async () => {
    setRecheckErr(null);
    setRechecking(true);
    try {
      const machines = await listMachines().then((x) => x.machines).catch(() => []);
      await recheckStored(partKey, { materialClass: latest?.result.material_class ?? null, qty: latest?.result.quantities, owned: ownedProcessesFrom(machines) });
      router.push(R.part(partKey));
    } catch (e) {
      setRecheckErr(e instanceof Error ? e.message : "The re-check didn’t finish.");
      setRechecking(false);
    }
  };
  const recheck = async (f: File) => {
    setRecheckErr(null);
    const h = await computeMeshHash(f).catch(() => null);
    if (h !== partKey) {
      setRecheckErr("That's a different file from this part (its fingerprint doesn't match). Check it from Check a part to save it as its own part.");
      return;
    }
    startCheck(f, { materialClass: latest?.result.material_class ?? "polymer" });
    router.push(R.part(partKey));
  };
  return (
    <main className="world pv" aria-label="Part history">
      <section className="stage" aria-label="Part history">
        <div className="pagehead">
          <Link href={R.parts} style={{ fontSize: 12.5, textDecoration: "none" }}>
            ‹ Parts
          </Link>
          <h1 className="ptitle" style={{ overflowWrap: "anywhere" }}>
            {file}
          </h1>
          <p className="pmeta">
            {row ? <span>{row.lifecycle_state}</span> : null}
            {row?.recommended_route ? (
              <span>
                {methodName(row.recommended_route.process)}, {row.recommended_route.source === "dfm" ? "DFM pick" : "costed"}
              </span>
            ) : null}
            {row ? <span>updated {when(row.updated_at)}</span> : null}
          </p>
          {parts.length > 1 ? (
            <nav className="subnav" aria-label="Your parts" style={{ flexWrap: "nowrap", overflowX: "auto", maxWidth: "100%", scrollbarWidth: "none" }}>
              {parts.slice(0, 12).map((p) => (
                <Link key={p.part_key} href={R.partHistory(p.part_key)} className={cx(p.part_key === partKey && "on")} aria-current={p.part_key === partKey ? "page" : undefined} title={`${p.filename} · ${rowTitle(p)}`} style={{ flex: "none" }}>
                  <i style={{ width: 7, height: 7, borderRadius: 999, background: dotOf(p) }} aria-hidden="true" />
                  {p.filename}
                </Link>
              ))}
            </nav>
          ) : null}
        </div>
        <div className="content" style={{ top: parts.length > 1 ? 164 : 120 }}>
          {state === "loading" ? (
            <div className="panel">
              <Loading rows={4} label="Loading this part's history" />
            </div>
          ) : (
            <>
              <div className="panel" style={{ display: "grid", gridTemplateColumns: "auto minmax(0,1fr)", gap: "4px 16px", padding: "14px 16px" }}>
                <div className="hist-thumb" role="img" aria-label={`${file}${mesh ? (mesh.origin === "stored" ? ", rendered from the kept source file" : ", rendered from this browser's copy") : ", no 3D view here"}`}>
                  {mesh ? <PartViewer url={mesh.url} highlight={null} xray={false} controllerRef={controller} onState={setVs} /> : <span style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", color: "var(--ink3)", fontSize: 12, textAlign: "center", padding: 8 }}>No 3D view here</span>}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
                  <div className="kv" style={{ padding: 0 }}>
                    <span>Size</span>
                    <b className="num">{dimsText(g?.bounding_box_mm ?? cg?.bbox_mm) ?? "—"}</b>
                    <span>Volume</span>
                    <b className="num">{g ? `${trimNum(g.volume_mm3 / 1000, 2)} cm³` : cg ? `${trimNum(cg.volume_cm3, 2)} cm³` : "—"}</b>
                    <span>Closed solid</span>
                    <b>{(g?.is_watertight ?? cg?.watertight) == null ? "—" : g?.is_watertight ?? cg?.watertight ? "✓ watertight" : "✗ not watertight"}</b>
                    <span>Measured</span>
                    <b>from the file, {(g?.faces ?? cg?.face_count ?? 0).toLocaleString("en-US")} faces</b>
                    <span>File</span>
                    <b>
                      {(latest?.file_type ?? row?.file_type ?? "").toUpperCase()} · {kept ? "kept with the record · " : ""}fingerprint <span className="mono">{partKey.slice(0, 8)}</span>
                    </b>
                  </div>
                  <span style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
                    <Link className="btn ink sm" href={R.part(partKey)}>
                      Open the part
                    </Link>
                    <button className="btn sm" type="button" disabled={rechecking} onClick={() => (kept ? void recheckKept() : picker.current?.click())}>
                      {rechecking ? "Re-checking…" : "Re-check this part"}
                    </button>
                    <input
                      ref={picker}
                      type="file"
                      accept={CAD_ACCEPT}
                      aria-label="Choose this part's file to re-check it"
                      tabIndex={-1}
                      style={{ display: "none" }}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        e.target.value = "";
                        if (f) void recheck(f);
                      }}
                    />
                    {latest ? (
                      <Link className="btn sm" href={`${R.compare}?a=${encodeURIComponent(latest.id)}`}>
                        Compare
                      </Link>
                    ) : null}
                  </span>
                  <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>
                    {kept
                      ? "Re-check prices this part again with today’s machines and rates, from the file kept with the record · nothing to pick · no check used"
                      : "Re-check runs this part again with today’s machines and rates · choose its file · the same file doesn’t use another check"}
                  </span>
                  {recheckErr ? (
                    <span role="alert" style={{ color: "var(--bad)", fontSize: 12.5 }}>
                      {recheckErr}
                    </span>
                  ) : null}
                </div>
              </div>
              <WhereUsed partKey={partKey} file={file} ctx={ctx} onCtx={setCtx} />
              <div className="panel">
                <div className="ph">
                  <h2>Standing</h2>
                  <span>{st.kicker}</span>
                </div>
                <div style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <span className={`chip ${st.chip}`}>
                      <i />
                      {st.verdict}
                    </span>
                    <b style={{ fontSize: 16, fontWeight: 600 }}>{st.title}</b>
                  </span>
                  <span style={{ color: "var(--ink2)", fontSize: 13.5 }}>{st.line}</span>
                  {st.rows.length ? (
                    <div className="lines" style={{ margin: 0 }}>
                      {st.rows.map(([k, v]) => (
                        <div className="ln" key={k} style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
                          <span>{k}</span>
                          <b className="num">{v}</b>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {latest ? (
                      <>
                        <Link className="btn sm ink" href={st.verdict === "Ruled out" ? `${R.part(partKey)}?lens=use` : R.part(partKey)}>
                          {st.verdict === "Ruled out" ? "Change the conditions or material" : "Open the part"}
                        </Link>
                        <Link className="btn sm" href={R.record(latest.id)}>
                          Open the record
                        </Link>
                      </>
                    ) : (
                      <button className="btn sm ink" type="button" onClick={() => picker.current?.click()}>
                        Price it
                      </button>
                    )}
                  </span>
                </div>
              </div>
            </>
          )}
        </div>
      </section>
      <HistorySheet partKey={partKey} />
    </main>
  );
}

function WhereUsed({ partKey, file, ctx, onCtx }: { partKey: string; file: string; ctx: PartContext | null; onCtx: (c: PartContext) => void }) {
  const [open, setOpen] = React.useState(false);
  const [asm, setAsm] = React.useState(ctx?.bom_assembly_key ?? "");
  const [ref, setRef] = React.useState(ctx?.bom_child_ref ?? "");
  const [yr, setYr] = React.useState(ctx?.bom_roots_per_year?.toString() ?? "");
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<{ t: string; bad: boolean } | null>(null);
  const [anc, setAnc] = React.useState<BomAncestry | null>(null);
  const [bomErr, setBomErr] = React.useState(false);
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    setAsm(ctx?.bom_assembly_key ?? "");
    setRef(ctx?.bom_child_ref ?? "");
    setYr(ctx?.bom_roots_per_year?.toString() ?? "");
  }, [ctx?.bom_assembly_key, ctx?.bom_child_ref, ctx?.bom_roots_per_year]);
  React.useEffect(() => {
    if (!ctx?.bom_assembly_key || !ctx.bom_child_ref) {
      setAnc(null);
      return;
    }
    setBomErr(false);
    fetchBomAncestry(ctx.bom_assembly_key, ctx.bom_child_ref)
      .then(setAnc)
      .catch(() => setBomErr(true));
  }, [ctx?.bom_assembly_key, ctx?.bom_child_ref, n]);
  const yrN = yr.trim() === "" ? null : Number(yr);
  const yrBad = yrN !== null && !(Number.isInteger(yrN) && yrN >= 1 && yrN <= 2147483647);
  const canSave = !!asm.trim() && !!ref.trim() && !yrBad && !busy;
  const linked = !!(ctx?.bom_assembly_key && ctx?.bom_child_ref);
  const save = async () => {
    if (!canSave) return;
    setBusy(true);
    setMsg(null);
    try {
      const a = await fetchBomAncestry(asm.trim(), ref.trim());
      if (!a?.has_tree || a.error || a.rolled_up_multiplier == null) throw new Error(a?.error || "This saved assembly doesn't contain that part. Check the assembly name and the exact BOM reference.");
      if (yrN !== null && bomAnnualVolume(a.rolled_up_multiplier, yrN) === null) throw new Error("That yearly demand is too large to count exactly.");
      const res = await assignContext(partKey, { bom_assembly_key: asm.trim(), bom_child_ref: ref.trim(), bom_roots_per_year: yrN });
      onCtx(res.context);
      setMsg({ t: `BOM link saved. Yearly volume now rolls up from ${asm.trim()}.`, bad: false });
    } catch (e) {
      setMsg({ t: e instanceof Error ? e.message : "The BOM link wasn't saved.", bad: true });
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    try {
      const res = await assignContext(partKey, { bom_assembly_key: null, bom_child_ref: null, bom_roots_per_year: null });
      onCtx(res.context);
      setAsm("");
      setRef("");
      setYr("");
      setMsg({ t: "BOM link removed.", bad: false });
    } catch (e) {
      setMsg({ t: e instanceof Error ? e.message : "The BOM link wasn't removed.", bad: true });
    }
  };
  const perYear = anc?.rolled_up_multiplier != null ? bomAnnualVolume(anc.rolled_up_multiplier, ctx?.bom_roots_per_year ?? null) : null;
  return (
    <div className="panel">
      <div className="ph">
        <h2>Where it&apos;s used</h2>
        <span>program → assembly → part</span>
      </div>
      <div style={{ padding: "0 16px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 13.5 }}>
          <span className={cx("tag", !ctx?.program && "unset")} style={{ position: "static", padding: "4px 10px" }}>
            {ctx?.program ? <b style={{ fontSize: 13 }}>{ctx.program}</b> : "No program"}
          </span>
          →
          <span className={cx("tag", !ctx?.parent_assembly && !anc?.has_tree && "unset")} style={{ position: "static", padding: "4px 10px" }}>
            {ctx?.parent_assembly ? <b style={{ fontSize: 13 }}>{ctx.parent_assembly}</b> : anc?.has_tree ? <b style={{ fontSize: 13 }}>{anc.ancestry.slice(1).join(" › ")}</b> : "No assembly"}
          </span>
          →
          <span className="tag" style={{ position: "static", padding: "4px 10px" }}>
            <b style={{ fontSize: 13 }}>{file}</b>
          </span>
          <Link href={R.programs} style={{ marginLeft: "auto" }}>
            {ctx?.program ? "Open the program" : "Assign to a program"}
          </Link>
        </span>
        <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>
          {ctx?.program ? `${ctx.resolved_annual_volume ? `${qtyWord(ctx.resolved_annual_volume)} a year` : "No yearly volume"}${ctx.annual_volume_basis === "bom_rollup" ? ", from the BOM" : ctx.annual_volume_basis === "declared" ? ", declared" : ""}.` : "Exposure across programs computes once the part has a home."}
        </span>
        {bomErr ? (
          <span className="swap" role="alert" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 12, background: "var(--bad-bg)", fontSize: 13 }}>
            BOM unavailable: the BOM service didn&apos;t answer.
            <button className="btn sm" type="button" onClick={() => setN((x) => x + 1)} style={{ marginLeft: "auto" }}>
              Retry
            </button>
          </span>
        ) : null}
        {linked ? (
          <span className="swap" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", padding: "8px 12px", borderRadius: 12, background: "rgba(20,24,31,.04)", fontSize: 13 }}>
            <span className="src s-yours">Declared</span>
            <span>
              {ctx!.bom_assembly_key} › {ctx!.bom_child_ref}
              {ctx?.bom_roots_per_year ? ` · ${qtyWord(ctx.bom_roots_per_year)} root assemblies a year` : " · no yearly volume"}
              {perYear != null ? ` · ${qtyWord(perYear)} of this part a year` : ""}
            </span>
          </span>
        ) : null}
        <span>
          <button className="btn sm" type="button" aria-expanded={open} aria-controls="bomform" onClick={() => setOpen((o) => !o)}>
            {linked ? "Edit BOM link" : "Link to a saved BOM"}
          </button>
        </span>
        {open ? (
          <form
            id="bomform"
            className="swap"
            aria-label="Part BOM link"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
            style={{ display: "flex", flexDirection: "column", gap: 10, padding: 12, borderRadius: 14, background: "#fff", border: "1px solid var(--rule)" }}
          >
            <span style={{ color: "var(--ink2)", fontSize: 13 }}>Point this part at its line in a BOM you saved or imported from Windchill. Its yearly volume then rolls up from the tree.</span>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
              <label className="field">
                Saved BOM assembly
                <input type="text" required value={asm} onChange={(e) => { setAsm(e.target.value); setMsg(null); }} placeholder="for example PUMP-200" />
              </label>
              <label className="field">
                Part reference in the BOM
                <input type="text" required value={ref} onChange={(e) => { setRef(e.target.value); setMsg(null); }} placeholder="for example 1200-BLK" />
              </label>
              <label className="field">
                Root assemblies a year
                <input type="number" min={1} max={2147483647} step={1} inputMode="numeric" value={yr} onChange={(e) => { setYr(e.target.value); setMsg(null); }} placeholder="optional" />
              </label>
            </div>
            {yrBad || msg ? (
              <span role={yrBad || msg?.bad ? "alert" : "status"} style={{ fontSize: 13, color: yrBad || msg?.bad ? "var(--bad)" : "var(--ok)" }}>
                {yrBad ? "Root assemblies a year must be a whole number from 1 to 2,147,483,647." : msg?.t}
              </span>
            ) : null}
            <span style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button className="btn ink sm" type="submit" disabled={!canSave}>
                {busy ? "Saving…" : "Save BOM link"}
              </button>
              <ConfirmButton label="Remove BOM link" question="Remove the link? A yearly volume you declared on its own stays." confirmLabel="Remove" onConfirm={remove} disabled={!linked} />
            </span>
          </form>
        ) : null}
      </div>
    </div>
  );
}

function HistorySheet({ partKey }: { partKey: string }) {
  const [rows, setRows] = React.useState<CostDecisionSummary[]>([]);
  const [cursor, setCursor] = React.useState<string | null>(null);
  const [more, setMore] = React.useState(false);
  const [state, setState] = React.useState<"loading" | "ready" | "error">("loading");
  const [open, setOpen] = React.useState<string | null>(null);
  const [details, setDetails] = React.useState<Record<string, CostDecisionDetail | "error">>({});
  const [n, setN] = React.useState(0);
  const load = React.useCallback(
    async (after: string | null) => {
      try {
        const page = await fetchCostDecisions({ meshHash: partKey, limit: 5, cursor: after ?? undefined });
        setRows((r) => (after ? [...r, ...page.cost_decisions] : page.cost_decisions));
        setCursor(page.next_cursor);
        setMore(!!page.has_more);
        setState("ready");
        if (!after && page.cost_decisions[0]) setOpen(page.cost_decisions[0].id);
      } catch {
        setState("error");
      }
    },
    [partKey],
  );
  React.useEffect(() => {
    setState("loading");
    void load(null);
  }, [load, n]);
  React.useEffect(() => {
    if (!open || details[open]) return;
    fetchCostDecision(open)
      .then((d) => setDetails((x) => ({ ...x, [open]: d })))
      .catch(() => setDetails((x) => ({ ...x, [open]: "error" })));
  }, [open, details]);
  const outcomes = rows.filter((r) => r.user_disposition).length;
  return (
    <aside className="sheet" aria-label="Decision history">
      <div className="top">
        <h2 className="stitle">Decisions</h2>
        <p className="smeta">{state === "ready" ? `${rows.length}${more ? "+" : ""} saved for this file · newest first` : "Loading…"}</p>
        <div className="figs">
          <div className="fig">
            <span>Checks</span>
            <b className="num">{rows.length}{more ? "+" : ""}</b>
            <small>{rows[0] ? `latest ${when(rows[0].created_at)}` : ""}</small>
          </div>
          <div className="fig">
            <span>Outcomes recorded</span>
            <b className="num">{outcomes}</b>
            <small>{rows.filter((r) => r.approval_status === "approved").length ? "some approved" : "none approved"}</small>
          </div>
        </div>
      </div>
      <div className="scroll">
        {state === "error" ? (
          <div className="note swap" role="alert">
            <b>History unavailable</b>
            <span>The saved decisions didn&apos;t load. The part and its latest standing are unaffected.</span>
            <span>
              <button className="btn sm" type="button" onClick={() => setN((x) => x + 1)}>
                Retry
              </button>
            </span>
          </div>
        ) : state === "loading" ? (
          <Loading rows={4} label="Loading decisions" />
        ) : !rows.length ? (
          <Empty title="No saved decisions">Each priced check saves a decision record. This part has an analysis only.</Empty>
        ) : (
          <>
            <div className="list" style={{ padding: "4px 0" }}>
              {rows.map((r) => {
                const d = details[r.id];
                const det = d && d !== "error" ? d : null;
                const qs = [...(r.quantities ?? [])].sort((a, b) => a - b);
                const q = qs.includes(10) ? 10 : qs[0];
                const rec = det?.result.decision?.recommendation?.[String(q)] ?? null;
                const est = rec && det ? det.result.estimates.find((e) => e.quantity === q && e.process === rec.process && e.material === rec.material) ?? null : null;
                const isOpen = open === r.id;
                const cls = det?.result.material_class;
                return (
                  <React.Fragment key={r.id}>
                    <button type="button" className={cx("mr", isOpen && "on")} aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : r.id)}>
                      <span>
                        <b>{when(r.created_at)}</b>
                        <small>
                          {[cls ? MATERIAL_CLASS_LABEL[cls] ?? cls : null, r.make_now_process ? methodName(r.make_now_process) : "no route priced", qs.length ? `${qtyWord(qs[0])}–${qtyWord(qs[qs.length - 1])}` : null, r.is_stale ? "stale" : null].filter(Boolean).join(" · ")}
                        </small>
                      </span>
                      <span className={`chip ${r.user_disposition ? "c-ok" : r.make_now_process ? "c-unk" : "c-bad"}`}>
                        <i />
                        {r.user_disposition ? DISPOSITION[r.user_disposition] ?? r.user_disposition : r.make_now_process ? "No outcome" : "Not priced"}
                      </span>
                      <span className="c num">{rec ? money(rec.unit_cost_usd) : ""}</span>
                    </button>
                    {isOpen ? (
                      <div className="det swap">
                        {d === "error" ? (
                          <span role="alert">This record didn&apos;t load.</span>
                        ) : !det ? (
                          <span>Loading…</span>
                        ) : (
                          <>
                            <span className="num" style={{ color: "var(--ink2)" }}>
                              {rec ? `${methodName(rec.process)}, ${rec.material} · ${money(rec.unit_cost_usd)} a part at ${qtyWord(q)}` : "No route priced"} · {r.approval_status === "approved" ? "approved" : "unreviewed"}
                            </span>
                            <span className="num" style={{ color: "var(--ink3)" }}>
                              {est ? `Largest drivers: ${costLines(est).slice(0, 4).map((l) => `${l.name.split(",")[0]} ${money(l.value)}`).join(" · ")}` : "No per-driver breakdown on this record"}
                            </span>
                            {r.disposition_note ? <span style={{ color: "var(--ink2)" }}>“{r.disposition_note}”</span> : null}
                            <span style={{ display: "flex", gap: 12, fontSize: 13, flexWrap: "wrap" }}>
                              <Link href={R.record(r.id)}>Open record {shortId(r.id)}</Link>
                              <span style={{ color: "var(--ink3)" }}>{r.crossover_qty ? `crossover ≈ ${qtyWord(Math.round(r.crossover_qty))}` : "no tooling crossover"}</span>
                            </span>
                          </>
                        )}
                      </div>
                    ) : null}
                  </React.Fragment>
                );
              })}
            </div>
            {more && cursor ? (
              <div style={{ padding: "4px 12px" }}>
                <button className="btn sm" type="button" onClick={() => void load(cursor)}>
                  Load older decisions
                </button>
              </div>
            ) : null}
            <p style={{ margin: "10px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>Each check saves a decision record with its quantities, drivers and engine version. Recording an outcome is done on the part&apos;s Decide step.</p>
          </>
        )}
      </div>
    </aside>
  );
}
