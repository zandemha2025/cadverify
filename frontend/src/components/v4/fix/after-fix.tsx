"use client";

/**
 * K3: after a fix. Before and after side by side, turning together; what changed;
 * the problems left; keep or discard. Every number comes from the two checks (the
 * repair's own re-check, or the new revision's check) and, for prices, from a saved
 * record of that exact file. Nothing is kept until the user chooses.
 */
import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { CostReport, StoredRepairResult, ValidationResult } from "@/lib/api";
import { createDesignRevision } from "@/lib/designs-api";
import { cx } from "../ui";
import { R } from "../routes";
import { LENSES, usePart } from "../part/ctx";
import { buildMethods, cheapestAt, money, priceAt, qtyWord, trimNum, type Method } from "../part/model";
import { loadSavedPart } from "../part/api";
import { startCheck, useSession } from "../part/store";
import { liveMesh } from "../part/check-page";
import type { MeshSource } from "../part/part-view";
import type { ViewerController, ViewerHighlight } from "../part/viewer";
import { KIND_COLOR } from "../part/model";
import { useFix } from "./ctx";
import { buildProblems, callout, familyOf, findProblem, pickMethod, tidy, type Problem } from "./problems";
import { methodLabel, rankProblems } from "./rank";
import { whoFixes, type FixOrigin } from "./capabilities";
import { clearRun, useFixRun, type RepairRun, type ServerRun, type StudioRun } from "./runs";
import { fixedFileUrl } from "./server";
import { loadPartMesh } from "../part/api";
import { methodName } from "../part/model";
import { forgetStudioOrigin } from "./origin";
import { failureText } from "./ask-dialog";
import { roving } from "./problem-sheet";
import { outcomeOf, repairHead, signedPct } from "./repair-outcome";
import { repairFailedReason } from "../part/repair";
import "./fix.css";

const PartViewer = dynamic(() => import("../part/viewer"), { ssr: false });

interface Side {
  title: string;
  right: string;
  url: string | null;
  /** Its 3D is still being fetched (a fixed copy's preview is built on the server). */
  loading?: boolean;
  kind: "glb" | "stl";
  highlight: ViewerHighlight | null;
  tagHead: string;
  tagText: string;
  tagCls: string;
  aria: string;
}

function canMake(methods: Method[]): number {
  return methods.filter((m) => m.members.length === 1 && (m.verdict === "ok" || m.verdict === "warn")).length;
}

function pinFor(p: Problem | null, label: string, aligned: boolean): ViewerHighlight | null {
  if (!p) return null;
  const m = pickMethod(p, null, null);
  return { faces: aligned ? p.faces : [], region: aligned ? p.region : null, color: p.kind ? KIND_COLOR[p.kind] : "#D92D20", label, kindClass: p.kind ? `k-${p.kind}` : "k-open", callout: callout(p, m), edges: p.id === "open" };
}

function Pair({ a, b }: { a: Side; b: Side }) {
  const c1 = React.useRef(null) as ViewerController;
  const c2 = React.useRef(null) as ViewerController;
  // Each side's viewer, so a slow or failed picture says so instead of an empty box.
  const [views, setViews] = React.useState<Record<string, string>>({});
  const keys = (e: React.KeyboardEvent) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    c1.current?.turnBy((step * Math.PI) / 18);
    c2.current?.turnBy((step * Math.PI) / 18);
  };
  const side = (s: Side, ctl: ViewerController, other: ViewerController) => (
    <div className="kside" key={s.title}>
      <div className="lab">
        <b>{s.title}</b>
        <span>{s.right}</span>
      </div>
      <button type="button" className="ktt" aria-label={s.aria} onKeyDown={keys}>
        <span className="shade" />
        {s.url ? (
          <>
            <PartViewer url={s.url} kind={s.kind} highlight={s.highlight} xray={false} controllerRef={ctl} onState={(v) => setViews((cur) => (cur[s.url!] === v ? cur : { ...cur, [s.url!]: v }))} onTurn={(az, pol) => other.current?.setAngles(az, pol)} />
            {views[s.url] === "failed" || views[s.url] === "nowebgl" ? (
              <span className="none">{views[s.url] === "nowebgl" ? "No 3D view on this device" : "This one’s 3D view didn’t load"}</span>
            ) : views[s.url] !== "ready" ? (
              <span className="none wait" role="status">Loading its 3D view…</span>
            ) : null}
          </>
        ) : (
          <span className="none" role={s.loading ? "status" : undefined}>{s.loading ? "Loading its 3D view…" : "No 3D view of this one here"}</span>
        )}
      </button>
      <div className={cx("tag", s.tagCls)}>
        <b>{s.tagHead}</b>
        {s.tagText}
      </div>
    </div>
  );
  return (
    <>
      <div className="kpair">
        {side(a, c1, c2)}
        {side(b, c2, c1)}
      </div>
      <span className="kturn">Drag either one, or use the arrow keys: both turn together</span>
    </>
  );
}

type Row = [string, string, string, "" | "ok" | "warn" | "bad"];

function Changed({ colA, colB, right, rows, foot }: { colA: string; colB: string; right: string; rows: Row[]; foot: string }) {
  return (
    <>
      <div className="gh">
        <span>What changed</span>
        <span>{right}</span>
      </div>
      <div className="kchg">
        <div className="r">
          <span />
          <span>{colA}</span>
          <span style={{ textAlign: "right" }}>{colB}</span>
        </div>
        {rows.map(([k, b, a, cls], i) => (
          <div className="r" key={`${i}:${k}`}>
            <span>{k}</span>
            <span className="b num">{b}</span>
            <span className={cx("a num", cls)}>{a}</span>
          </div>
        ))}
      </div>
      <p style={{ margin: "6px 12px 0", color: "var(--ink3)", fontSize: 12 }}>{foot}</p>
    </>
  );
}

function Left({ items, n, title = "Problems left" }: { items: { k: string; s: string; who: string; tone: string }[]; n: string; title?: string }) {
  return (
    <>
      <div className="gh">
        <span>{title}</span>
        <span>{n}</span>
      </div>
      <div className="kleft">
        {items.length ? (
          items.map((l) => (
            <div className="lr" key={`${l.who}:${l.k}`}>
              <b>{l.k}</b>
              <span className={cx("chip", l.tone)}>
                <i />
                {l.who}
              </span>
              <small>{l.s}</small>
            </div>
          ))
        ) : (
          <div className="lr">
            <b>None reported</b>
            <small>The check found nothing that stops or flags a process.</small>
          </div>
        )}
      </div>
    </>
  );
}

function leftItems(validation: ValidationResult | null, cost: CostReport | null, origin: FixOrigin): { k: string; s: string; who: string; tone: string }[] {
  const set = buildProblems({ validation, cost });
  const methods = buildMethods({ validation, cost, machines: [] });
  const milling = methods.some((m) => (m.code === "cnc_3axis" || m.code === "cnc_5axis") && (m.verdict === "ok" || m.verdict === "warn"));
  return rankProblems(set, methods, 10).map((u) => {
    const w = whoFixes(u.problem, origin, milling);
    return { k: u.problem.title, s: `${u.problem.where}${u.value ? ` · fixing it: ${u.value.toLowerCase()}` : ""}`, who: w.label, tone: w.tone };
  });
}

function Keep({ opts, keep, setKeep }: { opts: [string, string][]; keep: number; setKeep: (i: number) => void }) {
  return (
    <>
      <div className="gh">
        <span>Keep</span>
        <span />
      </div>
      <div role="radiogroup" aria-label="What to keep">
        {opts.map(([k, s], i) => (
          <button key={k} type="button" role="radio" className={cx("kopt", keep === i && "on")} aria-checked={keep === i} tabIndex={keep === i ? 0 : -1} onClick={() => setKeep(i)} onKeyDown={roving(opts, i, setKeep)}>
            <span className="dot2" aria-hidden="true" />
            <span>
              <b>{k}</b>
              <small>{s}</small>
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

export function AfterFixView({ mesh }: { mesh: MeshSource }) {
  const p = usePart();
  const fx = useFix();
  const run = useFixRun(p.data.key);
  const [toast, setToast] = React.useState<{ text: string; link?: { label: string; href: string } } | null>(null);
  const t = React.useRef<number | null>(null);
  const flash = React.useCallback((x: { text: string; link?: { label: string; href: string } }) => {
    setToast(x);
    if (t.current) window.clearTimeout(t.current);
    t.current = window.setTimeout(() => setToast(null), 4200);
  }, []);
  React.useEffect(() => () => {
    if (t.current) window.clearTimeout(t.current);
  }, []);
  const problem = run ? findProblem(fx.set, run.problem) : null;
  const back = () => fx.setAfter(false);
  const li = LENSES.findIndex(([k]) => k === p.lens);
  const shell = (body: React.ReactNode, sheet: React.ReactNode, meta: string) => (
    <main className="world pv" aria-label={`${p.data.fileName}, before and after`}>
      <section className="stage kstage3" aria-label="Before and after">
        <div className="floor" />
        <div className="hud">
          <button className="khud-back" type="button" onClick={back}>
            ‹ {problem?.title ?? "The problem"}
          </button>
          <h1 title={p.data.fileName}>{p.data.fileName}</h1>
          <span className="num">{meta}</span>
        </div>
        {body}
        {toast ? (
          <div className="toast ptoast" role="status">
            <span>{toast.text}</span>
            {toast.link ? (
              <Link href={toast.link.href} style={{ marginLeft: "auto" }}>
                {toast.link.label}
              </Link>
            ) : null}
          </div>
        ) : null}
      </section>
      <aside className="sheet" aria-label="The result">
        {sheet}
      </aside>
      <nav className="dial" aria-label="Questions about this part">
        <span className="ind" style={{ transform: `translateX(${Math.max(0, li) * 100}%)` }} aria-hidden="true" />
        {LENSES.map(([k, label, sub]) => (
          <button
            key={k}
            type="button"
            className={cx(k === p.lens && "on")}
            aria-pressed={k === p.lens}
            onClick={() => {
              fx.setAfter(false);
              fx.close();
              p.setLens(k);
            }}
          >
            {label}
            <small>{sub}</small>
          </button>
        ))}
      </nav>
    </main>
  );
  if (run?.kind === "repair" && run.s === "fixed") return <RepairAfter run={run} mesh={mesh} problem={problem} shell={shell} flash={flash} />;
  if (run?.kind === "studio" && run.s === "done") return <StudioAfter run={run} mesh={mesh} problem={problem} shell={shell} flash={flash} />;
  if (run?.kind === "server" && run.s === "done" && run.r.applied && run.r.fixed) return <ServerAfter run={run} mesh={mesh} problem={problem} shell={shell} />;
  return shell(
    null,
    <div className="top">
      <h2 className="stitle">Nothing to compare</h2>
      <p className="smeta">The fix isn’t finished, or it was discarded.</p>
      <p style={{ marginTop: 10 }}>
        <button className="btn sm" type="button" onClick={back}>
          Back to the problem
        </button>
      </p>
    </div>,
    "",
  );
}

type ShellFn = (body: React.ReactNode, sheet: React.ReactNode, meta: string) => React.ReactElement;

/* ── after a mesh repair ──────────────────────────────────────────────── */

function RepairAfter({ run, mesh, problem, shell, flash }: { run: Extract<RepairRun, { s: "fixed" }>; mesh: MeshSource; problem: Problem | null; shell: ShellFn; flash: (x: { text: string; link?: { label: string; href: string } }) => void }) {
  const p = usePart();
  const fx = useFix();
  const router = useRouter();
  const r = run.r;
  const d = r.repair_details;
  const v = r.repair_verification;
  const hash = run.saved?.hash ?? v?.repaired_sha256 ?? null;
  // The kept-file repair saved the copy as a part already and priced it in the same request.
  const stored = run.saved ? (r as StoredRepairResult) : null;
  const [keep, setKeep] = React.useState(0);
  const [saved, setSaved] = React.useState<{ cost: CostReport | null; name: string | null } | null | undefined>(undefined);
  const [sid, setSid] = React.useState<number | null>(null);
  const session = useSession(sid);
  // Is this exact repaired file already a priced part (same SHA-256)? Then its saved prices are real and no check is needed.
  React.useEffect(() => {
    if (!hash) return setSaved(null);
    let live = true;
    loadSavedPart(hash)
      .then((s) => live && setSaved(s.latest || s.decisions.length ? { cost: s.latest?.result ?? null, name: s.latest?.filename ?? s.decisions[0]?.filename ?? null } : null))
      .catch(() => live && setSaved(null));
    return () => {
      live = false;
    };
  }, [hash]);
  React.useEffect(() => {
    if (!session || session.status === "running" || !session.key) return;
    if (session.status === "done" || session.status === "stopped") flash({ text: `Saved as a new part: ${session.file.name}`, link: { label: "Open", href: R.part(session.key) } });
    else if (session.failure) flash({ text: `Not saved: ${failureText(session.failure)}` });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.status]);
  const before = p.data.validation ?? r.original_analysis;
  const after = r.repaired_analysis;
  const cost = session?.result?.cost ?? saved?.cost ?? null;
  const mBefore = buildMethods({ validation: before, cost: null, machines: [] });
  const mAfter = buildMethods({ validation: after, cost, machines: [] });
  const total = mAfter.filter((m) => m.members.length === 1).length || mBefore.length;
  const pct = d.volume_change_pct ?? null;
  const kind = outcomeOf(r);
  const head = repairHead(kind, pct);
  const changedShape = kind === "closed_changed";
  const cheap = (q: number) => {
    const c = cheapestAt(mAfter, q);
    return c ? `${money(priceAt(c, q))} · ${c.name.toLowerCase()} (${c.short})` : null;
  };
  // Prices of the copy: its own saved record, else what the kept-file repair priced.
  const storedPrice = (q: number) => {
    const x = stored?.prices?.after?.find((y) => y.qty === q);
    return x?.unit_cost_usd != null ? `${money(x.unit_cost_usd)} · ${methodName(x.process).toLowerCase()}` : null;
  };
  const priceOf = (q: number) => (cost ? cheap(q) : storedPrice(q));
  const priced = cost ? cost.quantities ?? [] : stored?.prices?.quantities ?? [];
  const red = cost?.decision?.if_redesigned ?? {};
  const redQ = Object.entries(red).filter(([, x]) => x).map(([k]) => Number(k)).sort((a, b) => b - a)[0];
  const rows: Row[] = [
    ["Closed solid", before?.geometry.is_watertight ? "yes" : "no", after?.geometry.is_watertight ? "yes" : "no", after?.geometry.is_watertight ? "ok" : "bad"],
    ...(d.openings ? [["Open edges", d.openings.open_edges.toLocaleString("en-US"), "0", "ok"] as Row] : []),
    ["Faces", d.original_faces?.toLocaleString("en-US") ?? "—", d.repaired_faces?.toLocaleString("en-US") ?? "—", ""],
    ["Volume", d.original_volume_mm3 != null ? `${Math.round(d.original_volume_mm3).toLocaleString("en-US")} mm³` : "unknown", d.repaired_volume_mm3 != null ? `${Math.round(d.repaired_volume_mm3).toLocaleString("en-US")} mm³${pct != null ? ` · ${signedPct(pct)}` : ""}` : "—", changedShape ? "warn" : ""],
    ["Verdict", v?.original_verdict ?? "—", v?.repaired_verdict ?? "—", v?.repaired_verdict === "fail" ? "bad" : "ok"],
    ["Processes that can make it", `${canMake(mBefore.map((m) => ({ ...m, verdict: before?.geometry.is_watertight === false ? "bad" : m.verdict })))} of ${total}`, `${canMake(mAfter)} of ${total}`, "ok"],
  ];
  for (const q of [10, 100, 1000]) if (priced.includes(q)) rows.push([`Cheapest at ${qtyWord(q)}`, "not priced", priceOf(q) ?? "none", priceOf(q) ? "ok" : "bad"]);
  if (redQ && red[String(redQ)]) rows.push([`${red[String(redQ)]!.process === "injection_molding" ? "Molding" : red[String(redQ)]!.process} at ${qtyWord(redQ)}, if redesigned`, "—", money(red[String(redQ)]!.unit_cost_usd), ""]);
  const origin: FixOrigin = { fileType: "STL", open: !after?.geometry.is_watertight, studio: null, server: null };
  const items = after ? leftItems(after, cost, origin) : [];
  if (changedShape) items.unshift({ k: pct != null ? `Volume ${signedPct(pct)} from the repair` : "A change in shape from the repair", s: "The repair’s own change. Close the opening in your CAD tool to keep the design’s shape.", who: "In your CAD", tone: "c-unk" });
  const firstQ = [10, 100, 1, ...priced].find((q) => priced.includes(q) && priceOf(q)) ?? null;
  const firstPrice = firstQ != null ? priceOf(firstQ) : null;
  const figs = [
    { k: "Processes", v: `${canMake(mAfter)} of ${total}`, s: `was ${before?.geometry.is_watertight === false ? 0 : canMake(mBefore)} of ${total}`, tone: "ok" },
    firstPrice && firstQ != null
      ? { k: `Cheapest at ${qtyWord(firstQ)}`, v: firstPrice.split(" · ")[0], s: firstPrice.split(" · ")[1], tone: "" }
      : { k: "Prices", v: run.saved ? "None" : "When saved", s: run.saved ? "nothing priced" : "saving checks and prices it", tone: "" },
    { k: "Volume", v: pct != null ? signedPct(pct) : "unknown", s: changedShape ? (pct != null ? "more than closing gaps" : "couldn’t measure before") : "closing gaps only", tone: changedShape ? "warn" : "" },
  ];
  const savedAlready = !!saved && !!hash;
  const saving = session?.status === "running";
  const downloadUrl = run.url || (run.saved ? fixedFileUrl(run.saved.hash) : "");
  const doSave = () => {
    if (run.saved) {
      if (keep === 0) {
        if (p.data.key) clearRun(p.data.key);
        router.push(R.part(run.saved.hash));
        return;
      }
      fx.setAfter(false);
      p.toast({ text: `Keeping your file. The repaired copy stays in Parts as ${run.saved.filename}.`, link: { label: "Open it", href: R.part(run.saved.hash) } });
      return;
    }
    if (keep === 1) {
      if (p.data.key) clearRun(p.data.key);
      fx.setAfter(false);
      p.toast({ text: "Repaired copy discarded. Your file is unchanged." });
      return;
    }
    if (savedAlready) {
      router.push(R.part(hash!));
      return;
    }
    if (saving) return;
    setSid(startCheck(run.file, { materialClass: p.data.cost?.material_class ?? "polymer" }));
  };
  const label = run.saved
    ? keep === 0
      ? "Open the repaired copy"
      : "Back to my file"
    : keep === 1
      ? "Discard the copy"
      : savedAlready
        ? "Open the saved copy"
        : saving
          ? "Saving: checking it…"
          : session && session.status !== "running" && session.key
            ? "Saved"
            : "Save the repaired copy";
  const keepOpts: [string, string][] = run.saved
    ? [
        ["Use the repaired copy", `It’s saved as a new part, ${run.saved.filename}, linked to your file. Open it to price, decide and share it.`],
        ["Keep using my file", "The repaired copy stays in Parts; nothing else changes."],
      ]
    : [
        ["Keep both", "Save the repaired copy as a new part next to this file. Your file and its record stay as they are."],
        ["Keep only my file", "Discard the repaired copy. Nothing is saved."],
      ];
  const body = (
    <Pair
      a={{ title: "Before", right: "your file", url: mesh.url, kind: mesh.kind, highlight: pinFor(problem, "1", mesh.faceSpace === "analysis" && !!mesh.faceHash && mesh.faceHash === p.data.validation?.analysis_mesh_hash), tagHead: "Your file", tagText: [problem?.where, `${(d.original_faces ?? before?.geometry.faces ?? 0).toLocaleString("en-US")} faces`, d.original_volume_mm3 != null ? `${Math.round(d.original_volume_mm3).toLocaleString("en-US")} mm³ with its openings capped flat` : null].filter(Boolean).join(" · "), tagCls: "", aria: `Your file, ${problem?.where ?? "open shell"}. Drag, or use the arrow keys, to turn both.` }}
      b={{ title: "After", right: "repaired copy", url: run.url || null, kind: "stl", highlight: null, tagHead: "Repaired copy", tagText: [after?.geometry.is_watertight ? "Closed" : "Still open", `${(d.repaired_faces ?? 0).toLocaleString("en-US")} faces`, d.repaired_volume_mm3 != null ? `${Math.round(d.repaired_volume_mm3).toLocaleString("en-US")} mm³${pct != null ? `, ${signedPct(pct)}` : ""}` : null].filter(Boolean).join(" · "), tagCls: changedShape ? "warn" : "ok", aria: "The repaired copy. Drag, or use the arrow keys, to turn both." }}
    />
  );
  const sheet = (
    <>
      <div className="top">
        <span className={cx("chip", head.tone)} style={{ marginBottom: 10 }}>
          <i />
          {head.chip}
        </span>
        <h2 className="stitle">{head.title}</h2>
        <p className="smeta">
          {[d.welded_edges ? `welded ${d.welded_edges.toLocaleString("en-US")} edges` : null, d.tier ? `mesh repair, ${d.tier}` : "mesh repair", d.duration_ms != null ? `${(d.duration_ms / 1000).toFixed(1)} s` : null, v?.reverified ? "checked like an upload" : null, "no check used"].filter(Boolean).join(" · ")}
        </p>
        <div className="figs" aria-live="polite">
          {figs.map((g) => (
            <div className="fig" key={g.k}>
              <span>{g.k}</span>
              <b className={cx("num", g.tone, !/^[$\d−+]/.test(g.v) && "t")}>{g.v}</b>
              <small>{g.s}</small>
            </div>
          ))}
        </div>
      </div>
      <div className="scroll">
        <div className={changedShape ? "kwarn" : "kprop"} role="note" style={{ marginTop: 8 }}>
          <b>{changedShape ? "The shape changed" : "What the repair did"}</b>
          <span>{repairFailedReason(r)}</span>
          {changedShape && d.volume_warning ? <span>{d.volume_warning}</span> : null}
        </div>
        <Changed colA="Your file" colB="Repaired copy" right={cost ? `at ${qtyWord(10)} parts, ${cost.material_class === "polymer" ? "plastic" : cost.material_class}` : stored?.prices ? `${stored.prices.material_class === "polymer" ? "plastic" : stored.prices.material_class}` : "prices when saved"} rows={rows} foot={cost ? `Model prices, not quotes${savedAlready && !session ? `, from the saved record of this exact file${saved?.name ? ` (${saved.name})` : ""}` : ""}.` : stored?.prices ? stored.prices.note : "Saving the copy checks it like an upload and prices it."} />
        <Left items={items} n={after ? `${items.length} on the repaired copy` : ""} />
        <Keep opts={keepOpts} keep={keep} setKeep={setKeep} />
        <p className="khash">SHA-256 · your file {v?.original_sha256.slice(0, 8) ?? "—"}… · repaired copy {hash?.slice(0, 8) ?? "—"}…</p>
      </div>
      <div className="kact">
        <button className="btn ink" type="button" onClick={doSave} aria-disabled={saving} style={saving ? { opacity: 0.6 } : undefined}>
          {label}
        </button>
        {downloadUrl ? (
          <a className="btn" href={downloadUrl} download={run.file.name}>
            Download the repaired STL
          </a>
        ) : null}
        <small>
          {run.saved
            ? `The repaired copy is in Parts, linked to your file. Opening it doesn’t use a check.`
            : savedAlready
              ? `This exact repaired file is already a part${saved?.name ? `: ${saved.name}` : ""}. Opening it doesn’t use a check.`
              : "The repaired copy was checked during the repair. Keeping it saves it as a new part, separate from your file. It doesn’t use a check: ScaleCAD made it from a part you checked."}{" "}
          <button className="btn sm ghost" type="button" style={{ height: 22, padding: "0 4px" }} onClick={() => (fx.setAfter(false), fx.openAsk(run.problem, "upload"))}>
            Fix it in CAD instead
          </button>
        </small>
      </div>
    </>
  );
  return shell(body, sheet, run.saved ? `Mesh repair · saved as ${run.saved.filename}` : savedAlready ? "Mesh repair · this repaired copy is already a part" : "Mesh repair · repaired copy not saved yet");
}

/* ── after a new Design Studio revision ───────────────────────────────── */

function StudioAfter({ run, mesh, problem, shell, flash }: { run: StudioRun; mesh: MeshSource; problem: Problem | null; shell: ShellFn; flash: (x: { text: string; link?: { label: string; href: string } }) => void }) {
  const p = usePart();
  const fx = useFix();
  const router = useRouter();
  const session = useSession(run.sessionId);
  const [keep, setKeep] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const after = session?.validation ?? session?.result?.validation ?? null;
  const aCost = session?.result?.cost ?? null;
  const bCost = p.data.cost;
  const before = p.data.validation;
  const mB = buildMethods({ validation: before, cost: bCost, machines: [] });
  const mA = buildMethods({ validation: after, cost: aCost, machines: [] });
  const setB = buildProblems({ validation: before, cost: bCost });
  const setA = buildProblems({ validation: after, cost: aCost });
  const changes = run.changes?.length ? run.changes : [{ problem: run.problem, param: run.param, value: run.value }];
  const pid = run.problem;
  const pB = findProblem(setB, pid);
  const pA = findProblem(setA, pid);
  const flagged = (set: typeof setA) => new Set(changes.flatMap((c) => { const x = findProblem(set, c.problem); return x ? [...x.blocks, ...x.warns] : []; })).size;
  const flaggedB = flagged(setB);
  const flaggedA = flagged(setA);
  const cleared = flaggedB - flaggedA;
  const changeWords = changes.map((c) => (c.param.unit === "°" ? "draft" : `a thicker ${c.param.label.toLowerCase()}`));
  const fmtC = (c: (typeof changes)[number], v: number) => (c.param.unit === "°" ? `${trimNum(v, 1)}°` : `${v.toFixed(1)} mm`);
  const fromText = changes.map((c) => `${c.param.label.toLowerCase()} ${fmtC(c, c.param.value)}`).join(" · ");
  const toText = changes.map((c) => `${c.param.label.toLowerCase()} ${fmtC(c, c.value)}`).join(" · ");
  const nA = run.revision ?? run.from.revision + 1;
  const nB = run.from.revision;
  const total = mA.filter((m) => m.members.length === 1).length || mB.filter((m) => m.members.length === 1).length;
  const q = [10, 100, ...(aCost?.quantities ?? [])].find((x) => aCost?.quantities?.includes(x)) ?? 10;
  const cB = cheapestAt(mB, q);
  const cA = cheapestAt(mA, q);
  const pa = cA ? priceAt(cA, q) : null;
  const pb = cB ? priceAt(cB, q) : null;
  const delta = pa != null && pb != null ? pa - pb : null;
  const rows: Row[] = [
    ...changes.map((c): Row => [c.param.label, fmtC(c, c.param.value), fmtC(c, c.value), ""]),
    [`Methods flagged for ${changes.length > 1 ? "these" : problem?.title.toLowerCase() ?? "it"}`, String(flaggedB), String(flaggedA), flaggedA < flaggedB ? "ok" : ""],
    ["Processes that can make it", `${canMake(mB)} of ${total}`, `${canMake(mA)} of ${total}`, canMake(mA) >= canMake(mB) ? "ok" : "bad"],
  ];
  if (cA || cB) rows.push([`Cheapest at ${qtyWord(q)}`, cB && pb != null ? `${money(pb)} · ${cB.short}` : "none", cA && pa != null ? `${money(pa)} · ${cA.short}${delta ? ` · ${delta > 0 ? "+" : "−"}${money(Math.abs(delta))}` : ""}` : "none", delta != null && delta > 0 ? "warn" : "ok"]);
  const shared = mA
    .filter((m) => m.members.length === 1 && m.prices.has(q) && mB.some((x) => x.code === m.code && x.prices.has(q)) && m.code !== cA?.code)
    .sort((a, b) => (priceAt(a, q) ?? 0) - (priceAt(b, q) ?? 0))
    .slice(0, 2);
  for (const m of shared) rows.push([methodLabel(m, mA.filter((x) => x.members.length === 1)), money(priceAt(mB.find((x) => x.code === m.code)!, q)), money(priceAt(m, q)), ""]);
  const redA = aCost?.decision?.if_redesigned ?? {};
  const redQ = Object.entries(redA).filter(([, x]) => x).map(([k]) => Number(k)).sort((a, b) => b - a)[0];
  if (redQ && redA[String(redQ)]) {
    const rb = bCost?.decision?.if_redesigned?.[String(redQ)];
    rows.push([`${redA[String(redQ)]!.process === "injection_molding" ? "Molding" : redA[String(redQ)]!.process} at ${qtyWord(redQ)}, if redesigned`, rb ? money(rb.unit_cost_usd) : "—", money(redA[String(redQ)]!.unit_cost_usd), ""]);
  }
  const origin: FixOrigin = { fileType: "STEP", open: false, studio: fx.origin.studio ? { ...fx.origin.studio, revision: nA, currentRevision: nA, plan: { ...run.from.plan, ...Object.fromEntries(changes.map((c) => [c.param.key, c.value])) } as typeof run.from.plan } : null, server: null };
  const items = leftItems(after, aCost, origin);
  const newKey = session?.key ?? null;
  const alignedA = !!session && session.preview.faceSpace === "analysis" && !!session.preview.faceHash && session.preview.faceHash === after?.analysis_mesh_hash;
  const alignedB = mesh.faceSpace === "analysis" && !!mesh.faceHash && mesh.faceHash === before?.analysis_mesh_hash;
  const aMesh = session ? liveMesh(session) : null;
  const doKeep = async () => {
    if (busy) return;
    if (keep === 0) {
      if (p.data.key) clearRun(p.data.key);
      if (newKey) {
        forgetStudioOrigin(newKey);
        router.push(R.part(newKey));
      } else fx.setAfter(false);
      return;
    }
    // Revisions are immutable, so going back makes a new one from revision n's plan. It isn't checked: same plan, same template.
    setBusy(true);
    try {
      const d = await createDesignRevision(run.designId, { plan: run.from.plan, design_note: `Back to revision ${nB}’s ${fromText}` });
      if (p.data.key) {
        clearRun(p.data.key);
        forgetStudioOrigin(p.data.key);
      }
      fx.setAfter(false);
      p.toast({ text: `Revision ${d.current_revision} has revision ${nB}’s plan and is current. Revision ${nA} stays in the history.`, link: { label: "Design Studio", href: R.studio } });
    } catch (e) {
      flash({ text: e instanceof Error ? e.message : "The revision wasn’t made." });
    } finally {
      setBusy(false);
    }
  };
  const body = (
    <Pair
      a={{ title: `Revision ${nB}`, right: fromText, url: mesh.url, kind: mesh.kind, highlight: pinFor(pB, "1", alignedB), tagHead: `Revision ${nB}`, tagText: [fromText.charAt(0).toUpperCase() + fromText.slice(1), run.from.volumeCm3 != null ? `${trimNum(run.from.volumeCm3, 2)} cm³` : null, pB ? pB.where : null].filter(Boolean).join(" · "), tagCls: "", aria: `Revision ${nB}. Drag, or use the arrow keys, to turn both.` }}
      b={{ title: `Revision ${nA}`, right: toText, url: aMesh?.url ?? null, kind: "glb", highlight: pA ? pinFor(pA, "1", alignedA) : null, tagHead: `Revision ${nA}`, tagText: [toText.charAt(0).toUpperCase() + toText.slice(1), run.volumeCm3 != null ? `${trimNum(run.volumeCm3, 2)} cm³` : null, "checked just now"].filter(Boolean).join(" · "), tagCls: "ok", aria: `Revision ${nA}. Drag, or use the arrow keys, to turn both.` }}
    />
  );
  const sheet = (
    <>
      <div className="top">
        <span className="chip c-ok" style={{ marginBottom: 10 }}>
          <i />
          Revision {nA} checked
        </span>
        <h2 className="stitle">{`${changeWords.join(" and ").replace(/^a /, "").replace(/^./, (c) => c.toUpperCase())}: ${cleared > 0 ? `${cleared} ${cleared === 1 ? "process" : "processes"} cleared` : "no processes cleared"}`}</h2>
        <p className="smeta">
          Same template, {fromText} → {toText}
        </p>
        <div className="figs" aria-live="polite">
          <div className="fig">
            <span>Methods</span>
            <b className="num ok">
              {canMake(mA)} of {total}
            </b>
            <small>
              was {canMake(mB)} of {total}
            </small>
          </div>
          {cA && pa != null ? (
            <div className="fig">
              <span>
                {cA.name.split(" ")[0]} at {qtyWord(q)}
              </span>
              <b className={cx("num", delta != null && delta > 0 ? "warn" : "ok")}>{money(pa)}</b>
              <small>{delta != null ? `${delta > 0 ? "+" : "−"}${money(Math.abs(delta))} each` : cA.short}</small>
            </div>
          ) : null}
          {run.volumeCm3 != null ? (
            <div className="fig">
              <span>Volume</span>
              <b className="num">{trimNum(run.volumeCm3, 2)} cm³</b>
              <small>{run.from.volumeCm3 != null ? `was ${trimNum(run.from.volumeCm3, 2)}` : ""}</small>
            </div>
          ) : null}
        </div>
      </div>
      <div className="scroll">
        <Changed colA={`Revision ${nB}`} colB={`Revision ${nA}`} right={`each at ${qtyWord(q)} unless noted`} rows={rows} foot="Model prices, not quotes." />
        <Left items={items} n={`${items.length} on revision ${nA}`} />
        <Keep
          opts={[
            [`Keep revision ${nA} as current`, `Revision ${nB} stays as it was, to download or check.`],
            [`Go back to revision ${nB}’s plan`, `Makes revision ${nA + 1} from revision ${nB}’s plan. Revision ${nA} stays in the history.`],
          ]}
          keep={keep}
          setKeep={setKeep}
        />
      </div>
      <div className="kact">
        <button className="btn ink" type="button" onClick={() => void doKeep()} aria-disabled={busy}>
          {keep === 0 ? `Keep revision ${nA}` : busy ? "Making it…" : `Make revision ${nA + 1}`}
        </button>
        {newKey ? (
          <button
            className="btn"
            type="button"
            onClick={() => {
              if (!session) return;
              startCheck(session.file, { materialClass: session.materialClass });
              router.push(R.part(newKey));
            }}
          >
            Re-check revision {nA}
          </button>
        ) : null}
        <small>
          Download the STEP from Design Studio to edit it in your CAD tool. <Link href={R.studio}>Compare in Design Studio</Link>
        </small>
      </div>
    </>
  );
  return shell(body, sheet, `Design Studio · revision ${nA} is current · revision ${nB} kept`);
}

/* ── after a fix the server made on a copy ────────────────────────────── */

const OUTCOME: Record<string, { chip: string; tone: string; title: string }> = {
  cleared: { chip: "Cleared", tone: "c-ok", title: "cleared" },
  partly_cleared: { chip: "Partly cleared", tone: "c-warn", title: "partly cleared" },
  not_cleared: { chip: "Still flagged", tone: "c-bad", title: "the re-check still shows it" },
  nothing_to_clear: { chip: "Nothing to clear", tone: "c-unk", title: "nothing to clear" },
};

function ServerAfter({ run, mesh, problem, shell }: { run: Extract<ServerRun, { s: "done" }>; mesh: MeshSource; problem: Problem | null; shell: ShellFn }) {
  const p = usePart();
  const fx = useFix();
  const router = useRouter();
  const r = run.r;
  const fixed = r.fixed!;
  const [keep, setKeep] = React.useState(0);
  const [after, setAfter] = React.useState<{ url: string | null; faceHash: string | null; aligned: boolean; validation: ValidationResult | null; cost: CostReport | null } | null>(null);
  // The copy is a saved part now: its 3D view and its own saved check.
  React.useEffect(() => {
    let live = true;
    let url: string | null = null;
    void Promise.all([loadPartMesh(fixed.mesh_hash, fixed.filename ?? null), loadSavedPart(fixed.mesh_hash).catch(() => null)]).then(([m, s]) => {
      if (!live) return;
      url = m.mesh ? URL.createObjectURL(m.mesh.blob) : null;
      const v = s?.validation ?? null;
      setAfter({ url, faceHash: m.mesh?.faceHash ?? null, aligned: !!m.mesh && m.mesh.faceSpace === "analysis" && !!v?.analysis_mesh_hash && m.mesh.faceHash === v.analysis_mesh_hash, validation: v, cost: s?.latest?.result ?? null });
    });
    return () => {
      live = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [fixed.mesh_hash, fixed.filename]);
  // Checked on a simplified mesh: the fix can't be confirmed either way.
  const o = r.verification && r.verification.comparable === false ? { chip: "Couldn’t confirm", tone: "c-warn", title: "couldn’t confirm: the copy had to be checked on a simplified mesh" } : OUTCOME[r.outcome] ?? OUTCOME.not_cleared;
  const sign = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${trimNum(Math.abs(x), 1)}%`;
  const pct = r.volume_change_pct;
  const changed = pct != null && Math.abs(pct) > 2;
  const priceRows: Row[] = [];
  for (const q of r.prices?.quantities ?? []) {
    const b = r.prices?.before?.find((x) => x.qty === q);
    const a = r.prices?.after?.find((x) => x.qty === q);
    if (!b && !a) continue;
    if (q !== 10 && q !== 1000 && q !== 10000 && (r.prices?.quantities.length ?? 0) > 3) continue;
    const t = (x: typeof a) => (x?.unit_cost_usd != null ? `${money(x.unit_cost_usd)} · ${methodName(x.process).toLowerCase()}` : "none");
    priceRows.push([`Cheapest at ${qtyWord(q)}`, t(b), t(a), a?.unit_cost_usd != null && (b?.unit_cost_usd == null || a.unit_cost_usd < b.unit_cost_usd) ? "ok" : ""]);
  }
  const rows: Row[] = [
    ["Processes that can make it", `${r.original.methods_can_make.count} of ${r.original.methods_can_make.of}`, `${fixed.methods_can_make.count} of ${fixed.methods_can_make.of}`, fixed.methods_can_make.count > r.original.methods_can_make.count ? "ok" : fixed.methods_can_make.count < r.original.methods_can_make.count ? "bad" : ""],
    ["Faces", r.original.faces?.toLocaleString("en-US") ?? "—", fixed.faces?.toLocaleString("en-US") ?? "—", ""],
    ["Volume", r.original.volume_mm3 != null ? `${Math.round(r.original.volume_mm3).toLocaleString("en-US")} mm³` : "—", fixed.volume_mm3 != null ? `${Math.round(fixed.volume_mm3).toLocaleString("en-US")} mm³${pct != null ? ` · ${sign(pct)}` : ""}` : "—", changed ? "warn" : ""],
    ["Verdict", r.verification?.original_verdict ?? "—", r.verification?.fixed_verdict ?? "—", ""],
    ...priceRows,
  ];
  const firstAfter = r.prices?.after?.find((x) => x.unit_cost_usd != null) ?? null;
  const firstBefore = firstAfter ? r.prices?.before?.find((x) => x.qty === firstAfter.qty) ?? null : null;
  const figs = [
    { k: "Processes", v: `${fixed.methods_can_make.count} of ${fixed.methods_can_make.of}`, s: `was ${r.original.methods_can_make.count} of ${r.original.methods_can_make.of}`, tone: fixed.methods_can_make.count > r.original.methods_can_make.count ? "ok" : "" },
    firstAfter
      ? { k: `Cheapest at ${qtyWord(firstAfter.qty)}`, v: money(firstAfter.unit_cost_usd), s: firstBefore?.unit_cost_usd != null ? `was ${money(firstBefore.unit_cost_usd)}` : `was none · ${methodName(firstAfter.process).toLowerCase()}`, tone: "ok" }
      : { k: "Prices", v: r.prices ? "None" : "Not priced", s: r.prices ? "nothing it doesn’t block" : "", tone: "" },
    { k: "Volume", v: pct != null ? sign(pct) : "—", s: changed ? "more than 2%" : "the shape kept", tone: changed ? "warn" : "" },
  ];
  const cleared = r.targeted?.cleared ?? [];
  const remaining = r.targeted?.remaining ?? [];
  // One line per kind of finding (the re-check reports one per method).
  const group = (list: typeof cleared, who: (f: (typeof cleared)[number]) => { who: string; tone: string }) => {
    const by = new Map<string, typeof cleared>();
    for (const f of list) {
      const t = familyOf(f.code).title;
      by.set(t, [...(by.get(t) ?? []), f]);
    }
    return [...by.entries()].map(([k, fs]) => {
      const methods = [...new Set(fs.map((f) => (f.process ? methodName(f.process) : "every process")))];
      return { k, s: `${methods.length > 3 ? `${methods.length} processes` : methods.join(", ")} · ${tidy(fs[0].message)}`, ...who(fs[0]) };
    });
  };
  const lines: { k: string; s: string; who: string; tone: string }[] = [
    ...group(r.findings_cleared.length ? r.findings_cleared : cleared, () => ({ who: "Cleared", tone: "c-ok" })),
    ...group(remaining, () => ({ who: "Still there", tone: "c-bad" })),
    ...group(r.findings_new, (f) => (f.severity === "error" ? { who: "New, blocks", tone: "c-bad" } : { who: "New", tone: "c-warn" })),
  ];
  const origin: FixOrigin = { fileType: fixed.format.toUpperCase(), open: fixed.is_watertight === false, studio: null, server: null };
  const left = after?.validation ? leftItems(after.validation, after.cost, origin) : [];
  const pB = problem;
  const setA = after?.validation ? buildProblems({ validation: after.validation, cost: after.cost }) : null;
  const pA = setA && pB ? findProblem(setA, pB.id) : null;
  const alignedB = mesh.faceSpace === "analysis" && !!mesh.faceHash && mesh.faceHash === p.data.validation?.analysis_mesh_hash;
  const done = () => {
    if (keep === 0) {
      if (p.data.key) clearRun(p.data.key);
      router.push(R.part(fixed.mesh_hash));
      return;
    }
    fx.setAfter(false);
    p.toast({ text: `Keeping your file. The fixed copy stays in Parts as ${fixed.filename ?? "a new part"}.`, link: { label: "Open it", href: R.part(fixed.mesh_hash) } });
  };
  const body = (
    <Pair
      a={{ title: "Before", right: "your file", url: mesh.url, kind: mesh.kind, highlight: pinFor(pB, "1", alignedB), tagHead: "Your file", tagText: [r.original.faces != null ? `${r.original.faces.toLocaleString("en-US")} faces` : null, r.original.volume_mm3 != null ? `${Math.round(r.original.volume_mm3).toLocaleString("en-US")} mm³` : null, pB?.where].filter(Boolean).join(" · "), tagCls: "", aria: "Your file. Drag, or use the arrow keys, to turn both." }}
      b={{ title: "After", right: "fixed copy", url: after?.url ?? null, loading: after === null, kind: "glb", highlight: pA ? pinFor(pA, "1", !!after?.aligned) : null, tagHead: "Fixed copy", tagText: [fixed.faces != null ? `${fixed.faces.toLocaleString("en-US")} faces` : null, fixed.volume_mm3 != null ? `${Math.round(fixed.volume_mm3).toLocaleString("en-US")} mm³${pct != null ? `, ${sign(pct)}` : ""}` : null, o.chip.toLowerCase()].filter(Boolean).join(" · "), tagCls: r.outcome === "cleared" && !changed ? "ok" : "warn", aria: "The fixed copy. Drag, or use the arrow keys, to turn both." }}
    />
  );
  const sheet = (
    <>
      <div className="top">
        <span className={cx("chip", o.tone)} style={{ marginBottom: 10 }}>
          <i />
          {o.chip}
        </span>
        <h2 className="stitle">
          {r.fix.label}: {o.title}
        </h2>
        <p className="smeta">{[r.fix.method, r.details.duration_ms != null ? `${(Number(r.details.duration_ms) / 1000).toFixed(1)} s` : null, r.verification?.reverified ? "checked like an upload" : null, r.verification ? (r.verification.checks_used === 0 ? "no check used" : `${r.verification.checks_used} check used`) : null].filter(Boolean).join(" · ")}</p>
        <div className="figs" aria-live="polite">
          {figs.map((g) => (
            <div className="fig" key={g.k}>
              <span>{g.k}</span>
              <b className={cx("num", g.tone, !/^[$\d−+]/.test(g.v) && "t")}>{g.v}</b>
              <small>{g.s}</small>
            </div>
          ))}
        </div>
      </div>
      <div className="scroll">
        {r.volume_warning ? (
          <div className="kwarn" role="note" style={{ marginTop: 8 }}>
            <b>The shape changed</b>
            <span>{r.volume_warning}</span>
          </div>
        ) : null}
        {r.notes.length ? (
          <div className="kwarn" role="note" style={{ marginTop: 8, background: "rgba(20,24,31,.035)", color: "var(--ink2)" }}>
            {r.notes.map((n) => (
              <span key={n}>{n}</span>
            ))}
          </div>
        ) : null}
        <Changed colA="Your file" colB="Fixed copy" right={r.prices ? `${r.prices.material_class === "polymer" ? "plastic" : r.prices.material_class}` : ""} rows={rows} foot={r.prices?.note ?? "Model prices, not quotes."} />
        <Left title="What the re-check says" items={lines} n={`${r.findings_cleared.length} findings cleared · ${r.findings_new.length} new`} />
        {after?.validation ? <Left items={left} n={`${left.length} on the copy`} /> : null}
        <Keep opts={[["Use the fixed copy", "It’s saved as a new part, linked to your file. Open it to price, decide and share it."], ["Keep using my file", "The fixed copy stays in Parts; nothing else changes."]]} keep={keep} setKeep={setKeep} />
        <p className="khash">SHA-256 · your file {r.verification?.original_sha256.slice(0, 8) ?? r.original.sha256.slice(0, 8)}… · fixed copy {fixed.sha256.slice(0, 8)}…</p>
      </div>
      <div className="kact">
        <button className="btn ink" type="button" onClick={done}>
          {keep === 0 ? "Open the fixed copy" : "Back to my file"}
        </button>
        <a className="btn" href={fixedFileUrl(fixed.mesh_hash)} download={fixed.filename ?? undefined}>
          Download the fixed {fixed.format.toUpperCase()}
        </a>
        <small>
          Your file is unchanged. The copy was checked in the same request{r.verification?.checks_used === 0 ? " and didn’t use a check" : ""}.{" "}
          <button className="btn sm ghost" type="button" style={{ height: 22, padding: "0 4px" }} onClick={() => (fx.setAfter(false), fx.openAsk(run.problem, "upload"))}>
            Steps for your CAD tool
          </button>
        </small>
      </div>
    </>
  );
  return shell(body, sheet, `${r.fix.label} · the fixed copy is saved as a new part`);
}
