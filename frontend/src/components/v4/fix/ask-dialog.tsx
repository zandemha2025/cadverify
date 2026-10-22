"use client";

/**
 * K2: asking before ScaleCAD tries a fix. A dialog over the part (role=dialog,
 * aria-modal; Esc and the scrim close it; focus moves in and goes back).
 *  - repair: mesh repair on a copy of an open shell, from the kept file (POST /parts/{hash}/repair)
 *    or the file in this browser (POST /validate/repair); any plan, no check;
 *  - studio: a new Design Studio revision with one parameter changed, then a check;
 *  - upload: the change in the user's CAD tool, the price after it, upload the fixed file.
 */
import * as React from "react";
import Link from "next/link";
import { cx } from "../ui";
import { R } from "../routes";
import { useShell } from "../shell";
import { usePart } from "../part/ctx";
import { money, qtyWord, trimNum } from "../part/model";
import { computeMeshHash } from "@/lib/verify/part-context";
import { useSession } from "../part/store";
import { defaultMethod, useFix } from "./ctx";
import { draftRules, fixText, ruleOf, type Problem, type ProblemMethod } from "./problems";
import { blockersByMethod, unlockOf, unlockQty } from "./rank";
import { fixRoute, studioValueProblem, type StudioParam } from "./capabilities";
import { CAD_TOOLS, cadPath, withDraftAngles } from "./cad-tools";
import type { CadToolId } from "./cad-steps";
import { markStudioDone, startRepair, startServerFix, startStudioRevision, useFixRun, type RepairRun, type ServerRun, type StudioRun } from "./runs";
import { newCheckLine } from "./all-sheet";
import type { Failure } from "../part/store";

export function failureText(f: Failure | null | undefined): string {
  if (!f) return "The check didn’t finish.";
  return "message" in f ? f.message : `${f.title}. ${f.detail}`;
}
import { useUploadFixed } from "./problem-sheet";
import { repairFailedReason } from "../part/repair";
import { keptStageWord } from "../part/kept-job-model";
import { nextSteps, openingsNote, outcomeOf, repairHead, type NextStep } from "./repair-outcome";
import "./fix.css";

const REPAIR_MAX_FACES = 500_000;
const REPAIR_TIMEOUT_S = 30;
// A large kept file is repaired on ScaleCAD's worker (backend kept_part_jobs; REPAIR_MAX_FACES_WORKER).
const WORKER_REPAIR_MAX_FACES = 5_000_000;

/** Focus in on open, back on close; Tab stays inside. */
function useDialogFocus(ref: React.RefObject<HTMLDivElement | null>) {
  React.useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    return () => {
      if (back && document.contains(back)) back.focus();
    };
  }, [ref]);
}

function trapTab(e: React.KeyboardEvent<HTMLDivElement>) {
  if (e.key !== "Tab") return;
  const els = [...e.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]):not([tabindex="-1"]), [tabindex="0"]')].filter((x) => x.offsetParent !== null);
  if (!els.length) return;
  const first = els[0];
  const last = els[els.length - 1];
  if (e.shiftKey && (document.activeElement === first || document.activeElement === e.currentTarget)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

type Step = { k: string; s: string; c: "" | "now" | "wait" | "done" | "bad" };

function Steps({ steps }: { steps: Step[] }) {
  return (
    <ol className="ksteps">
      {steps.map((x, i) => (
        <li key={x.k} className={x.c}>
          <i aria-hidden="true">{x.c === "done" ? "✓" : x.c === "bad" ? "!" : i + 1}</i>
          <span>
            <b>{x.k}</b>
            {x.s}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function AskDialog({ file }: { file: File | null }) {
  const fx = useFix();
  const ask = fx.ask;
  const ref = React.useRef<HTMLDivElement>(null);
  useDialogFocus(ref);
  if (!ask) return null;
  const P = fx.set.problems.find((x) => x.id === ask.problem) ?? null;
  const close = () => fx.closeAsk({ notFixed: true });
  return (
    <>
      <button className="kscrim" type="button" aria-label="Close without fixing" tabIndex={-1} onClick={close} />
      <div
        ref={ref}
        className="kdlg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="k2-title"
        tabIndex={-1}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            close();
            return;
          }
          trapTab(e);
        }}
      >
        {!P ? (
          <div className="dh">
            <h2 id="k2-title">Not on this part</h2>
            <p>This check didn’t report that problem.</p>
          </div>
        ) : ask.variant === "repair" ? (
          <RepairBody P={P} file={file} close={close} />
        ) : ask.variant === "studio" ? (
          <StudioBody P={P} close={close} />
        ) : ask.variant === "server" ? (
          <ServerBody P={P} close={close} />
        ) : (
          <UploadBody P={P} close={close} />
        )}
      </div>
    </>
  );
}

function Head({ who, whoTone, kind, title, text, close }: { who: string; whoTone: string; kind: string; title: string; text: string; close: () => void }) {
  return (
    <div className="dh">
      <div className="kick">
        <span className={cx("chip", whoTone)}>
          <i />
          {who}
        </span>
        <span>{kind}</span>
        <button className="btn sm ghost kx" type="button" aria-label="Close" onClick={close}>
          ✕
        </button>
      </div>
      <h2 id="k2-title">{title}</h2>
      <p>{text}</p>
    </div>
  );
}

/* ── mesh repair ──────────────────────────────────────────────────────── */

function RepairBody({ P, file, close }: { P: Problem; file: File | null; close: () => void }) {
  const p = usePart();
  const fx = useFix();
  const up = useUploadFixed();
  const key = p.data.key ?? "";
  const run = useFixRun(key);
  const rr = run?.kind === "repair" ? (run as RepairRun) : null;
  const [picked, setPicked] = React.useState<File | null>(null);
  const [pickErr, setPickErr] = React.useState<string | null>(null);
  const input = React.useRef<HTMLInputElement>(null);
  const src = file ?? picked;
  // The kept file is tried first (POST /parts/{hash}/repair). Only when the server says
  // it isn't kept does the dialog ask for the file.
  const needFile = !file && !picked && rr?.s === "error" && !!rr.notKept;
  const kept = fx.origin.server != null;
  const canGo = !!key && !needFile;
  const faces = p.data.validation?.geometry.faces ?? p.data.cost?.geometry.face_count ?? null;
  const edges = P.where.match(/^([\d,]+) open edges/)?.[1] ?? null;
  const name = p.data.fileName;
  const brep = /^(step|stp|iges|igs)$/i.test(p.data.fileType) || /\.(step|stp|iges|igs)$/i.test(name);
  const heal = fx.origin.server?.byFamily[P.id];
  const canHeal = !!heal?.can && heal.fix === "heal_brep";
  const go = () => {
    if (!canGo) return;
    startRepair(key, P.id, src, { name, qty: p.qs.length ? p.qs : undefined, materialClass: p.data.cost?.material_class ?? null });
  };
  const choose = async (f: File) => {
    setPickErr(null);
    const h = await computeMeshHash(f).catch(() => null);
    if (!h) return setPickErr("This browser couldn’t read the file.");
    if (h !== key) return setPickErr("That’s a different file from this part (its fingerprint doesn’t match).");
    setPicked(f);
  };
  if (rr) {
    const result = rr.s === "fixed" || rr.s === "failed" ? rr.r : null;
    const kind = result ? outcomeOf(result) : null;
    const head = kind ? repairHead(kind, result?.repair_details.volume_change_pct) : null;
    const opened = kind ? openingsNote(kind, result?.repair_details.openings) : null;
    const done = rr.s === "fixed";
    const next = kind ? nextSteps(kind, result?.repair_details.openings, { brep, canHeal }) : [];
    const d = result?.repair_details;
    const how = [d?.welded_edges ? `welded ${d.welded_edges.toLocaleString("en-US")} edges` : null, d?.tier ? `mesh repair, ${d.tier}` : "mesh repair", d?.duration_ms != null ? `${(d.duration_ms / 1000).toFixed(1)} s` : null].filter(Boolean).join(" · ");
    const steps: Step[] =
      rr.s === "running"
        ? [
            { k: edges ? `Closing the ${edges} open edges` : "Closing the open shell", s: "joins faces that touch, then trimesh, then MeshFix", c: "now" },
            { k: "Checking the repaired copy", s: "the same processes as an upload", c: "wait" },
            { k: "Comparing both shapes", s: "faces, volume and verdict", c: "wait" },
          ]
        : rr.s === "fixed"
          ? [
              { k: kind === "closed_changed" ? "Closed, with a change in shape" : "Closed", s: how, c: kind === "closed_changed" ? "bad" : "done" },
              { k: "Checked the repaired copy", s: `verdict ${rr.r.repair_verification?.repaired_verdict ?? "—"}, was ${rr.r.repair_verification?.original_verdict ?? "—"} · no check used`, c: "done" },
              { k: rr.saved ? "Saved as a new part" : "Both shapes ready to compare", s: rr.saved ? `${rr.saved.filename}, linked to your file` : "faces, volume and verdict", c: "done" },
            ]
          : rr.s === "failed"
            ? [{ k: head?.title ?? "Not repaired", s: how, c: "bad" }]
            : [{ k: "The repair didn’t run", s: "", c: "bad" }];
    const nextBtn = (n: NextStep) =>
      n.kind === "heal" ? (
        <button className="btn sm ink" type="button" onClick={() => fx.openAsk(P.id, "server")}>
          {n.label}
        </button>
      ) : n.kind === "cad" ? (
        <button className="btn sm" type="button" onClick={() => fx.openAsk(P.id, "upload")}>
          {n.label}
        </button>
      ) : (
        <button className="btn sm" type="button" onClick={up.pick}>
          {n.label}
        </button>
      );
    return (
      <>
        <Head
          who={head?.chip ?? "ScaleCAD can try this"}
          whoTone={head?.tone ?? "c-ok"}
          kind="Mesh repair · on a copy"
          title={rr.s === "running" ? "Repairing a copy" : head?.title ?? "The repair didn’t run"}
          text={rr.s === "running" ? `Working on a copy of ${kept ? "the file kept with this part" : rr.sourceName}. Your file stays as it is.` : "Your file stays as it is."}
          close={close}
        />
        <div className="db" aria-live="polite">
          <div className="gh">
            <span>Progress</span>
            <span>{rr.worker ? (rr.s === "running" ? `On ScaleCAD’s worker · ${keptStageWord(rr.worker).toLowerCase()}` : "On ScaleCAD’s worker") : `up to ${REPAIR_TIMEOUT_S} s`}</span>
          </div>
          <Steps steps={steps} />
          {result && head ? (
            <div className={done && kind === "repaired" ? "kprop" : done ? "kwarn" : "kbad"} role={done ? "status" : "alert"}>
              <b>{head.chip}</b>
              <span>{repairFailedReason(result)}</span>
              {opened ? <span>What was open: {opened}</span> : null}
            </div>
          ) : rr.s === "error" ? (
            <div className="kbad" role="alert">
              <b>{rr.limit ? "Not now" : rr.notKept ? "The file isn’t kept with this part" : "The repair didn’t run"}</b>
              <span>{rr.msg}</span>
              {rr.limit ? (
                <span>
                  <Link href={R.billing}>Plans</Link>
                </span>
              ) : null}
            </div>
          ) : null}
          {rr.s === "error" && rr.notKept && !file ? (
            <>
              <div className="kup">
                <button className={cx("btn sm", !picked && "ink")} type="button" onClick={() => input.current?.click()}>
                  {picked ? "Choose another" : `Choose ${name}`}
                </button>
                <input
                  ref={input}
                  type="file"
                  accept=".stl,.step,.stp,.iges,.igs"
                  aria-label={`Choose ${name}`}
                  tabIndex={-1}
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) void choose(f);
                  }}
                />
                <span>{picked ? `${picked.name} · same fingerprint, ready` : "It must be the same file."}</span>
              </div>
              {pickErr ? (
                <p className="kerr" role="alert">
                  {pickErr}
                </p>
              ) : null}
            </>
          ) : null}
          {next.length ? (
            <>
              <div className="gh" style={{ marginTop: 6 }}>
                <span>{kind === "closed_changed" ? "To keep the design’s shape" : "What you can do next"}</span>
                <span />
              </div>
              <div className="kleft">
                {next.map((n) => (
                  <div className="lr" key={n.kind}>
                    <b>{n.label}</b>
                    {nextBtn(n)}
                    <small>{n.why}</small>
                  </div>
                ))}
              </div>
              {up.el}
            </>
          ) : null}
          <p style={{ margin: "10px 12px 0", color: "var(--ink3)", fontSize: 13 }}>
            {rr.s === "running" ? "You can use other pages meanwhile." : rr.s === "fixed" && rr.saved ? "The repaired copy is in Parts, linked to your file. No check was used." : done ? "Nothing is kept until you choose." : "Nothing was made or saved."}
          </p>
        </div>
        <div className="df">
          {rr.s === "running" || done ? (
            <button className="btn ink" type="button" aria-disabled={!done} onClick={() => done && (fx.closeAsk(), fx.setAfter(true))} style={!done ? { opacity: 0.45, cursor: "default" } : undefined}>
              See the result
            </button>
          ) : null}
          {rr.s === "error" && !rr.limit && (!rr.notKept || src) ? (
            <button className={cx("btn", rr.notKept && "ink")} type="button" onClick={go} disabled={!canGo}>
              {rr.notKept ? "Repair this file" : "Try again"}
            </button>
          ) : null}
          <button className="btn" type="button" onClick={() => fx.closeAsk()}>
            Close
          </button>
        </div>
      </>
    );
  }
  const big = faces != null && faces > REPAIR_MAX_FACES;
  return (
    <>
      <Head who="ScaleCAD can try this" whoTone="c-ok" kind="Mesh repair · on a copy" title="Repair this mesh?" text={`ScaleCAD can try to close the open shell on a copy of ${name}. Your file stays as it is.`} close={close} />
      <div className="db">
        <div className="gh">
          <span>What happens</span>
          <span>on a copy</span>
        </div>
        <Steps
          steps={[
            { k: edges ? `Closes the ${edges} open edges` : "Closes the open shell", s: "Joins faces that touch but aren’t joined, then caps each opening (trimesh first; MeshFix if that isn’t enough)", c: "" },
            { k: "Checks the repaired copy", s: "The same processes as an upload", c: "" },
            { k: "Says how it ended", s: "Repaired, closed with a change in shape, partly closed, or not repaired and why", c: "" },
          ]}
        />
        <div className="kwarn" role="note">
          <b>It can change the shape</b>
          <span>A cap can fill a hole, bore or pocket that belongs to the design, and a missing face is capped flat. If the volume changes by more than 2%, ScaleCAD says so and by how much before you use the copy.</span>
        </div>
        <div className="gh" style={{ marginTop: 6 }}>
          <span>Limits</span>
          <span />
        </div>
        <div className="kv">
          <span>Faces</span>
          <b className="num" style={big ? { color: "var(--bad)" } : undefined}>
            {faces != null ? `${faces.toLocaleString("en-US")} of ${REPAIR_MAX_FACES.toLocaleString("en-US")}` : `up to ${REPAIR_MAX_FACES.toLocaleString("en-US")}`}
            {kept ? ` · a large kept file: up to ${WORKER_REPAIR_MAX_FACES.toLocaleString("en-US")}, on ScaleCAD’s worker` : ""}
          </b>
          <span>Time limit</span>
          <b className="num">{REPAIR_TIMEOUT_S} s{kept ? " · a large kept file: longer, on ScaleCAD’s worker" : ""}</b>
          <span>Checks</span>
          <b>Doesn’t use one</b>
          <span>From</span>
          <b>{kept ? "The file kept with this part · nothing to upload" : file ? "The file in this browser" : "The file kept with this part; if there isn’t one, ScaleCAD asks for it"}</b>
          <span>Your file</span>
          <b>Unchanged · repair works on a copy{kept ? ", saved as a new part" : ""}</b>
        </div>
      </div>
      <div className="df">
        <button className="btn ink" type="button" aria-disabled={!canGo} onClick={go} style={!canGo ? { opacity: 0.45, cursor: "default" } : undefined}>
          Repair a copy
        </button>
        <button className="btn" type="button" onClick={close}>
          Not now
        </button>
        <button className="btn ghost sp" type="button" onClick={() => fx.openAsk(P.id, "upload")}>
          Fix it in CAD instead
        </button>
      </div>
    </>
  );
}

/* ── Design Studio revision ───────────────────────────────────────────── */

/** The value to prefill: what the picked method needs (a draft gets 0.5° of margin over the limit it failed). */
function suggested(P: Problem, m: ProblemMethod | null, param: StudioParam): number {
  const needs = P.methods.map((x) => x.need).filter((x): x is number => x != null && x > param.value);
  const need = m?.need != null && m.need > param.value ? m.need : needs.length ? Math.min(...needs) : param.value;
  const v = param.unit === "°" ? Math.min(10, need + 0.5) : need;
  return Math.ceil(v * 10 - 1e-9) / 10;
}

function fmtParam(param: StudioParam, v: number): string {
  return param.unit === "°" ? `${trimNum(v, 1)}°` : `${v.toFixed(1)} mm`;
}

interface Change {
  problem: Problem;
  param: StudioParam;
}

function StudioBody({ P, close }: { P: Problem; close: () => void }) {
  const p = usePart();
  const fx = useFix();
  const shell = useShell();
  const key = p.data.key ?? "";
  const run = useFixRun(key);
  const sr = run?.kind === "studio" ? (run as StudioRun) : null;
  const session = useSession(sr?.sessionId ?? null);
  const origin = fx.origin.studio!;
  // Every problem the template can change, the asked one first: one revision, one check.
  const changes: Change[] = [P, ...fx.set.problems.filter((x) => x.id !== P.id)]
    .map((x) => ({ problem: x, route: fixRoute(x, fx.origin) }))
    .filter((x): x is { problem: Problem; route: { kind: "studio"; param: StudioParam } } => x.route?.kind === "studio")
    .map((x) => ({ problem: x.problem, param: x.route.param }));
  const [raw, setRaw] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(changes.map((c) => [c.param.key, (c.problem.id === P.id ? suggested(c.problem, fx.method, c.param) : suggested(c.problem, null, c.param)).toFixed(1)])),
  );
  const [on, setOn] = React.useState<Record<string, boolean>>(() => Object.fromEntries(changes.map((c) => [c.param.key, true])));
  React.useEffect(() => {
    if (sr?.s === "checking" && session && session.status !== "running") markStudioDone(key);
  }, [sr?.s, session, key]);
  if (!changes.length || changes[0].problem.id !== P.id) return null;
  const errs = Object.fromEntries(changes.map((c) => [c.param.key, on[c.param.key] ? studioValueProblem(origin.plan, c.param.key, raw[c.param.key] ?? "") : null]));
  const err = changes.map((c) => errs[c.param.key]).find(Boolean) ?? null;
  const val = (k: string) => Number(String(raw[k] ?? "").replace(",", "."));
  const next = origin.currentRevision + 1;
  const picked = changes.filter((c) => on[c.param.key]);
  const blockers = blockersByMethod(fx.set);
  // The check's own minimums for each change, grouped by what they need.
  const minsOf = (c: Change) => {
    const groups = new Map<number, ProblemMethod[]>();
    for (const m of c.problem.methods) if (m.need != null) (groups.get(m.need) ?? groups.set(m.need, []).get(m.need)!).push(m);
    const w = val(c.param.key);
    const bad = !!errs[c.param.key] || !on[c.param.key];
    return [...groups.entries()]
      .sort((x, y) => x[0] - y[0])
      .map(([need, ms]) => {
        const ok = !bad && w >= need - 1e-9;
        const also = [
          ...new Set(
            ms.flatMap((m) =>
              (blockers.get(m.code) ?? [])
                .filter((b) => b.id !== c.problem.id && !picked.some((x) => x.problem.id === b.id))
                .map((b) => `${m.name.charAt(0).toLowerCase()}${m.name.slice(1)} also: ${b.title.toLowerCase()}`),
            ),
          ),
        ];
        return { need, names: [...new Set(ms.map((m) => m.name))].join(", "), ok, q: [ok ? "met" : bad ? "" : `short by ${fmtParam(c.param, need - w)}`, ...also.slice(0, 2)].filter(Boolean).join(" · ") };
      });
  };
  const others = [...new Map(changes.flatMap((c) => c.problem.methods.flatMap((m) => (blockers.get(m.code) ?? []).filter((b) => !changes.some((x) => x.problem.id === b.id)))).map((b) => [b.id, b])).values()];
  if (sr) {
    const status = sr.s;
    const checkState: Step["c"] = status === "generating" ? "wait" : status === "failed" ? (sr.sessionId ? "bad" : "wait") : !session || session.status === "running" ? "now" : session.status === "failed" ? "bad" : "done";
    const ready = status === "done" && session?.status !== "failed";
    const steps: Step[] = [
      { k: `Generating revision ${sr.revision ?? next}`, s: "isolated CAD process", c: status === "generating" ? "now" : status === "failed" && !sr.sessionId ? "bad" : "done" },
      { k: `Checking revision ${sr.revision ?? next}`, s: session?.status === "failed" ? failureText(session.failure) : "the same check and prices as an upload", c: checkState },
      { k: `Comparing revisions ${sr.from.revision} and ${sr.revision ?? next}`, s: "processes, prices, problems left", c: ready ? "done" : "wait" },
    ];
    return (
      <>
        <Head who="ScaleCAD can fix this" whoTone="c-ok" kind="Design Studio part" title={status === "failed" ? `Revision ${sr.revision ?? next} wasn’t made` : ready ? `Revision ${sr.revision ?? next} checked` : `Making revision ${sr.revision ?? next}`} text={`Revision ${sr.from.revision} stays as it is.`} close={close} />
        <div className="db" aria-live="polite">
          <div className="gh">
            <span>Progress</span>
            <span>{sr.changes.map((c) => `${c.param.label.toLowerCase()} ${fmtParam(c.param, c.value)}`).join(" · ")}</span>
          </div>
          <Steps steps={steps} />
          {sr.error ? (
            <div className="kbad" role="alert">
              <b>Stopped</b>
              <span>{sr.error}</span>
            </div>
          ) : null}
          <p style={{ margin: "10px 12px 0", color: "var(--ink3)", fontSize: 13 }}>{status === "failed" && !sr.revision ? "Nothing was saved in Design Studio." : `You can leave this page. Revision ${sr.revision ?? next} is saved in Design Studio.`}</p>
        </div>
        <div className="df">
          <button className="btn ink" type="button" aria-disabled={!ready} onClick={() => ready && (fx.closeAsk(), fx.setAfter(true))} style={!ready ? { opacity: 0.45, cursor: "default" } : undefined}>
            See the result
          </button>
          <button className="btn" type="button" onClick={() => fx.closeAsk()}>
            Close
          </button>
        </div>
      </>
    );
  }
  const first = changes[0].param;
  const title = picked.length > 1 ? `Make revision ${next} with ${picked.map((c) => (c.param.unit === "°" ? "draft" : `a thicker ${c.param.label.toLowerCase()}`)).join(" and ")}?` : `Make revision ${next} with ${first.unit === "°" ? "draft" : `a thicker ${first.label.toLowerCase()}`}?`;
  return (
    <>
      <Head
        who="ScaleCAD can fix this"
        whoTone="c-ok"
        kind="Design Studio part"
        title={title}
        text={`This part was made in Design Studio, so ScaleCAD can generate it again with ${picked.length > 1 ? "these changes" : `a new ${first.label.toLowerCase()}`} and check it.`}
        close={close}
      />
      <div className="db">
        <div className="gh">
          <span>The change</span>
          <span>{origin.designName}</span>
        </div>
        <div className="kptab">
          <div className="r">
            <span>Parameter</span>
            <span>Revision {origin.revision}</span>
            <span>Revision {next}</span>
          </div>
          {changes.map((c, i) => (
            <div className="r" key={c.param.key}>
              <span>
                {i === 0 ? (
                  <b style={{ fontWeight: 600 }}>{c.param.label}</b>
                ) : (
                  <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                    <input type="checkbox" checked={!!on[c.param.key]} onChange={(e) => setOn((o) => ({ ...o, [c.param.key]: e.target.checked }))} style={{ width: 16, height: 16 }} />
                    <b style={{ fontWeight: 600 }}>{c.param.label}</b>
                    <span className="sr">: change it too, for {c.problem.title.toLowerCase()}</span>
                  </label>
                )}
              </span>
              <span className="num">{fmtParam(c.param, c.param.value)}</span>
              <label style={{ display: "block" }}>
                <span className="sr">
                  Revision {next} {c.param.label.toLowerCase()}, {c.param.unit === "°" ? "degrees" : "mm"}
                </span>
                <input
                  type="number"
                  min={c.param.unit === "°" ? 0 : 0.5}
                  max={c.param.unit === "°" ? 10 : undefined}
                  step={c.param.unit === "°" ? 0.5 : 0.1}
                  inputMode="decimal"
                  value={raw[c.param.key] ?? ""}
                  disabled={!on[c.param.key]}
                  aria-invalid={!!errs[c.param.key]}
                  aria-describedby={errs[c.param.key] ? `k2-err-${c.param.key}` : undefined}
                  onChange={(e) => setRaw((r) => ({ ...r, [c.param.key]: e.target.value }))}
                />
              </label>
            </div>
          ))}
          <div className="r same">
            <span>Everything else</span>
            <span className="num" style={{ gridColumn: "2 / 4" }}>
              {templateSize(origin.plan)} · unchanged
            </span>
          </div>
        </div>
        {changes.map((c) =>
          errs[c.param.key] ? (
            <p className="kerr" id={`k2-err-${c.param.key}`} role="alert" key={c.param.key}>
              {c.param.label}: {errs[c.param.key]}
            </p>
          ) : null,
        )}
        {picked.map((c) => {
          const mins = minsOf(c);
          if (!mins.length) return null;
          const n = mins.filter((x) => x.ok).length;
          return (
            <React.Fragment key={c.param.key}>
              <div className="gh" style={{ marginTop: 6 }}>
                <span>{picked.length > 1 ? `${c.param.label} against the check’s minimums` : "Against the check’s minimums"}</span>
                <span>{!errs[c.param.key] ? `${n} of ${mins.length} minimums met` : ""}</span>
              </div>
              <div className="kclr" aria-live="polite">
                {mins.map((x) => (
                  <div key={x.need} className={cx("c", x.ok ? "ok" : "no")}>
                    <span className="m" aria-hidden="true">
                      {x.ok ? "✓" : "✗"}
                    </span>
                    <span className="q">{fmtParam(c.param, x.need)}</span>
                    <span>
                      <span className="sr">{x.ok ? "Met: " : "Not met: "}</span>
                      {x.names}
                      <small>{x.q}</small>
                    </span>
                  </div>
                ))}
              </div>
            </React.Fragment>
          );
        })}
        <p style={{ margin: "6px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
          Minimums from the check on revision {origin.revision}; the check on revision {next} confirms them.
          {picked.some((c) => c.param.unit === "°") ? " The draft leans the walls in toward the base along +Z, the pull direction the check uses." : ""}
        </p>
        {others.length ? (
          <div className="kprop">
            <b>Not in this change: {others.map((b) => b.title.toLowerCase()).join(", ")}</b>
            <span>
              {others.some((b) => b.id === "draft") && origin.plan.kind === "bracket" ? "The bracket template has no draft parameter, so " : "These aren’t template parameters, so "}
              the processes they stop stay blocked in revision {next}. Download the STEP to change them in your CAD tool.
            </span>
          </div>
        ) : null}
        <div className="gh" style={{ marginTop: 6 }}>
          <span>What happens</span>
          <span />
        </div>
        <Steps
          steps={[
            { k: `Generates revision ${next}`, s: `Real CAD from the same template, in an isolated CAD process. Revision ${origin.revision} stays as it was, to download or check.`, c: "" },
            { k: `Checks revision ${next}`, s: newCheckLine(shell.usage, "The same check and prices as an upload"), c: "" },
            { k: "Shows both revisions", s: "What changed: processes, prices and problems left", c: "" },
          ]}
        />
      </div>
      <div className="df">
        <button
          className="btn ink"
          type="button"
          aria-disabled={!!err}
          onClick={() => {
            if (err || !key || !picked.length) return;
            startStudioRevision(
              key,
              origin,
              picked.map((c) => ({ problem: c.problem.id, param: c.param, value: val(c.param.key) })),
              p.data.cost?.material_class ?? "polymer",
            );
          }}
          style={err ? { opacity: 0.45, cursor: "default" } : undefined}
        >
          Make revision {next}
        </button>
        <button className="btn" type="button" onClick={close}>
          Not now
        </button>
        <Link className="btn ghost sp" href={R.studio}>
          Open in Design Studio
        </Link>
      </div>
    </>
  );
}

function templateSize(plan: StudioRun["from"]["plan"]): string {
  if (plan.kind === "plate") return `${plan.width_mm} × ${plan.depth_mm} mm, ${plan.holes.length} ${plan.holes.length === 1 ? "hole" : "holes"}`;
  return `${plan.width_mm} × ${plan.depth_mm} × ${plan.height_mm} mm`;
}

/* ── a fix the server makes on a copy of the kept CAD ─────────────────── */

const PARAM_LABEL: Record<string, string> = { diameter_mm: "Hole diameter", radius_mm: "Fillet radius", angle_deg: "Draft" };

function ServerBody({ P, close }: { P: Problem; close: () => void }) {
  const p = usePart();
  const fx = useFix();
  const key = p.data.key ?? "";
  const run = useFixRun(key);
  const sr = run?.kind === "server" ? (run as ServerRun) : null;
  const route = fixRoute(P, fx.origin);
  const fix = route?.kind === "server" ? route.fix : sr?.fix ?? null;
  const [raw, setRaw] = React.useState(() => (fix?.value != null ? String(fix.value) : ""));
  if (!fix) return null;
  const label = fix.label;
  const lowerLabel = label.charAt(0).toLowerCase() + label.slice(1);
  const unit = fix.unit === "deg" ? "°" : fix.unit === "mm" ? " mm" : "";
  const v = Number(raw.replace(",", "."));
  const err = fix.param ? (!raw.trim() || !Number.isFinite(v) ? "Enter a number." : fix.bounds && (v < fix.bounds[0] || v > fix.bounds[1]) ? `Use ${fix.bounds[0]} to ${fix.bounds[1]}${unit}.` : null) : null;
  const fmt = (x: number) => `${trimNum(x, 2)}${unit}`;
  // What the check asks for, by method, against the value (drain holes: 3.0 mm filament … 5.0 mm nylon powder).
  const groups = new Map<number, ProblemMethod[]>();
  for (const m of P.methods) if (m.need != null) (groups.get(m.need) ?? groups.set(m.need, []).get(m.need)!).push(m);
  const mins = fix.param ? [...groups.entries()].sort((a, b) => a[0] - b[0]) : [];
  const qty = p.qs.length ? p.qs : undefined;
  const go = () => {
    if (err || !key) return;
    startServerFix(key, P.id, fix, fix.param ? v : null, { qty, materialClass: p.data.cost?.material_class ?? null });
  };
  const alts = (
    <>
      {P.id === "open" && fx.origin.open ? (
        <button className="btn ghost" type="button" onClick={() => fx.openAsk(P.id, "repair")}>
          Try mesh repair instead
        </button>
      ) : null}
      <button className="btn ghost sp" type="button" onClick={() => fx.openAsk(P.id, "upload")}>
        Steps for your CAD tool
      </button>
    </>
  );
  if (sr) {
    const done = sr.s === "done" && sr.r.applied;
    const r = sr.s === "done" ? sr.r : null;
    const outcome = r?.outcome;
    const steps: Step[] =
      sr.s === "running"
        ? [
            { k: `${label} on a copy`, s: `${fix.method} · isolated CAD process`, c: "now" },
            { k: "Checking the copy", s: "the same check as an upload, then prices for both", c: "wait" },
            { k: "Comparing both", s: "what it cleared, what’s new, the volume", c: "wait" },
          ]
        : r && r.applied
          ? [
              { k: `${label}: done`, s: `${r.fix.method}${r.details.duration_ms != null ? ` · ${(Number(r.details.duration_ms) / 1000).toFixed(1)} s` : ""}`, c: "done" },
              { k: "Checked the copy", s: `verdict ${r.verification?.fixed_verdict ?? "—"}, was ${r.verification?.original_verdict ?? "—"}${r.verification ? ` · ${r.verification.checks_used === 0 ? "no check used" : `${r.verification.checks_used} check used`}` : ""}`, c: "done" },
              r.verification?.comparable === false
                ? { k: "Couldn’t confirm the fix", s: "the copy had to be checked on a simplified mesh", c: "bad" }
                : { k: outcome === "cleared" ? "The re-check cleared it" : outcome === "partly_cleared" ? "The re-check cleared some of it" : outcome === "nothing_to_clear" ? "Nothing to clear" : "The re-check still shows it", s: r.new_error_count ? `and found ${r.new_error_count} new ${r.new_error_count === 1 ? "error" : "errors"}: compare both` : "compare both before you use the copy", c: outcome === "cleared" || outcome === "partly_cleared" ? "done" : "bad" },
            ]
          : [{ k: "Not made", s: "", c: "bad" }];
    return (
      <>
        <Head who={sr.s === "running" || done ? "ScaleCAD can fix this" : "ScaleCAD tried this"} whoTone={sr.s === "running" || done ? "c-ok" : "c-unk"} kind={`${label} · on a copy`} title={sr.s === "running" ? `${label}: working on a copy` : done ? "Fixed copy ready" : "Not fixed"} text="Your file stays as it is." close={close} />
        <div className="db" aria-live="polite">
          <div className="gh">
            <span>Progress</span>
            <span>{sr.value != null ? fmt(sr.value) : ""}</span>
          </div>
          <Steps steps={steps} />
          {sr.s === "done" && !sr.r.applied ? (
            <div className="kbad" role="alert">
              <b>Nothing was made</b>
              <span>{sr.r.reason ?? "The fix didn’t produce a file."}</span>
            </div>
          ) : sr.s === "error" ? (
            <div className="kbad" role="alert">
              <b>The fix didn’t run</b>
              <span>{sr.msg}</span>
            </div>
          ) : null}
          {r?.applied && (outcome === "not_cleared" || outcome === "partly_cleared") && r.notes.length ? <p style={{ margin: "10px 12px 0", color: "var(--ink2)", fontSize: 13 }}>{r.notes[0]}</p> : null}
          <p style={{ margin: "10px 12px 0", color: "var(--ink3)", fontSize: 13 }}>{sr.s === "running" ? "This takes up to a minute or two: the edit, then a full check and prices for both files. You can use other pages meanwhile." : done ? "The copy is saved as a new part, linked to your file." : "Nothing was saved."}</p>
        </div>
        <div className="df">
          {sr.s === "running" || done ? (
            <button className="btn ink" type="button" aria-disabled={!done} onClick={() => done && (fx.closeAsk(), fx.setAfter(true))} style={!done ? { opacity: 0.45, cursor: "default" } : undefined}>
              See the result
            </button>
          ) : null}
          {sr.s === "error" ? (
            <button className="btn" type="button" onClick={go}>
              Try again
            </button>
          ) : null}
          <button className="btn" type="button" onClick={() => fx.closeAsk()}>
            Close
          </button>
          {sr.s !== "running" && !done ? alts : null}
        </div>
      </>
    );
  }
  return (
    <>
      <Head who="ScaleCAD can fix this" whoTone="c-ok" kind={`${label} · on a copy`} title={`${label} on a copy?`} text={`ScaleCAD can ${lowerLabel} on a copy of ${p.data.fileName}, then check the copy like an upload. Your file stays as it is.`} close={close} />
      <div className="db">
        <div className="gh">
          <span>The change</span>
          <span className="kcode">{P.codes.join(" · ")}</span>
        </div>
        {fix.param ? (
          <div className="kptab">
            <div className="r">
              <span>Parameter</span>
              <span>Check asks</span>
              <span>This copy</span>
            </div>
            <div className="r">
              <span>
                <b style={{ fontWeight: 600 }}>{PARAM_LABEL[fix.param] ?? fix.param}</b>
              </span>
              <span className="num">{mins.length ? `${fmt(mins[0][0])}–${fmt(mins[mins.length - 1][0])}`.replace(/^(.+)–\1$/, "$1") : fix.value != null ? fmt(fix.value) : "—"}</span>
              <label style={{ display: "block" }}>
                <span className="sr">
                  {PARAM_LABEL[fix.param] ?? fix.param}, {fix.unit === "deg" ? "degrees" : "mm"}
                </span>
                <input type="number" min={fix.bounds?.[0]} max={fix.bounds?.[1]} step={0.5} inputMode="decimal" value={raw} aria-invalid={!!err} aria-describedby={err ? "k2-err-srv" : undefined} onChange={(e) => setRaw(e.target.value)} />
              </label>
            </div>
          </div>
        ) : (
          <p className="kchange">
            {label}: no setting. {fix.method}.
          </p>
        )}
        {err ? (
          <p className="kerr" id="k2-err-srv" role="alert">
            {err}
          </p>
        ) : null}
        {mins.length ? (
          <>
            <div className="gh" style={{ marginTop: 6 }}>
              <span>Against the check’s minimums</span>
              <span>{!err ? `${mins.filter(([need]) => v >= need - 1e-9).length} of ${mins.length} met` : ""}</span>
            </div>
            <div className="kclr" aria-live="polite">
              {mins.map(([need, ms]) => {
                const ok = !err && v >= need - 1e-9;
                return (
                  <div key={need} className={cx("c", ok ? "ok" : "no")}>
                    <span className="m" aria-hidden="true">
                      {ok ? "✓" : "✗"}
                    </span>
                    <span className="q">{fmt(need)}</span>
                    <span>
                      <span className="sr">{ok ? "Met: " : "Not met: "}</span>
                      {[...new Set(ms.map((m) => m.name))].join(", ")}
                      <small>{ok ? "met" : err ? "" : `short by ${fmt(need - v)}`}</small>
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        ) : null}
        {fix.lastAttempt ? (
          <p style={{ margin: "8px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>Last time on this part: {fix.lastAttempt}</p>
        ) : null}
        <div className="gh" style={{ marginTop: 6 }}>
          <span>What happens</span>
          <span>on a copy</span>
        </div>
        <Steps
          steps={[
            { k: `${label} on a copy`, s: `${fix.method}, in an isolated CAD process`, c: "" },
            { k: "Checks the copy", s: "The same check as an upload, then prices for both files", c: "" },
            { k: "Shows both side by side", s: "What it cleared, anything new, the change in volume", c: "" },
          ]}
        />
        <div className="kwarn" role="note">
          <b>Compare before you use it</b>
          <span>The copy is a new part, linked to your file. If the volume changes by more than 2%, or the copy has a new problem, ScaleCAD says so.</span>
        </div>
        <div className="kv" style={{ marginTop: 6 }}>
          <span>Checks</span>
          <b>Doesn’t use one</b>
          <span>Your file</span>
          <b>Unchanged · the fix works on a copy</b>
        </div>
      </div>
      <div className="df">
        <button className="btn ink" type="button" aria-disabled={!!err} onClick={go} style={err ? { opacity: 0.45, cursor: "default" } : undefined}>
          Fix a copy
        </button>
        <button className="btn" type="button" onClick={close}>
          Not now
        </button>
        {alts}
      </div>
    </>
  );
}

/* ── uploaded CAD: steps in the user's own tool ───────────────────────── */

const TOOL_KEY = "scalecad.fix.cad-tool";

function UploadBody({ P, close }: { P: Problem; close: () => void }) {
  const p = usePart();
  const fx = useFix();
  const shell = useShell();
  const up = useUploadFixed();
  const [tool, setTool] = React.useState<CadToolId>(() => {
    try {
      const v = window.localStorage.getItem(TOOL_KEY);
      return CAD_TOOLS.find((x) => x.id === v)?.id ?? CAD_TOOLS[0].id;
    } catch {
      return CAD_TOOLS[0].id;
    }
  });
  const pickTool = (id: CadToolId) => {
    setTool(id);
    try {
      window.localStorage.setItem(TOOL_KEY, id);
    } catch {
      /* a convenience only */
    }
  };
  // The method the problem is open for, else the page's pick: its rule and source
  // (Protolabs for molding), not the first method in the list (NADCA, die casting).
  const m = fx.problem?.id === P.id ? fx.method : defaultMethod(P, fx.set, p.methods, p.q, fx.only, p.sel?.code ?? null);
  const f = fixText(P, m, null);
  const rule = ruleOf(P, m);
  const t = CAD_TOOLS.find((x) => x.id === tool) ?? CAD_TOOLS[0];
  const rawPath = cadPath(t.id, P.id);
  const rules = P.id === "draft" ? draftRules(m) : null;
  const path = P.id === "draft" && m?.need != null
    ? { ...rawPath, steps: withDraftAngles(rawPath.steps, rules?.outside ?? m.need, rules?.inside ?? m.need) }
    : rawPath;
  const uq = unlockQty(P, fx.set, p.methods, p.data.cost, p.q, p.qs);
  const u = unlockOf(P, fx.set, p.methods, uq);
  const best = u.best;
  const e = best ? best.m.prices.get(uq) ?? null : null;
  const d = p.data.cost?.decision;
  const red = d?.if_redesigned?.[String(uq)];
  const kind = fx.origin.studio ? "Design Studio part" : `Uploaded ${p.data.fileType || "file"}`;
  return (
    <>
      <Head
        who="In your CAD tool"
        whoTone="c-unk"
        kind={kind}
        title="Fix it in your CAD tool"
        text={fx.origin.studio ? "This isn’t a Design Studio parameter. Download the STEP, change it in your CAD tool, and check the file you send back." : "ScaleCAD can’t edit your CAD file. It can tell you the change, show the price after it, and check the file you send back."}
        close={close}
      />
      <div className="db">
        <div className="gh">
          <span>The change</span>
          <span className="kcode">{P.codes.join(" · ")}</span>
        </div>
        <p className="kchange">
          {f.fix}
          <small>
            {rule.text} {rule.source.replace(/ · applies to .*$/, "")}.
          </small>
        </p>
        <div className="gh" style={{ marginTop: 6 }}>
          <span>Steps in your CAD tool</span>
          <span />
        </div>
        <div className="ktools" role="group" aria-label="Your CAD tool">
          <span className="seg">
            {CAD_TOOLS.map((x) => (
              <button key={x.id} type="button" className={cx(x.id === t.id && "on")} aria-pressed={x.id === t.id} onClick={() => pickTool(x.id)}>
                {x.label}
              </button>
            ))}
          </span>
        </div>
        <div className="kpath" aria-live="polite">
          {path.noFix ? <small>No verified {t.label} steps for this change yet: make it with your tool’s own feature, then export:</small> : null}
          {!path.verified && !path.noFix ? (
            <>
              <span>
                The {t.label} steps for this change aren’t verified yet, so none are shown.
              </span>
              {path.help ? (
                <span>
                  <a href={path.help} target="_blank" rel="noopener noreferrer">
                    {t.label} help{path.feature ? `: ${path.feature}` : ""}
                  </a>
                </span>
              ) : null}
            </>
          ) : (
            path.steps.map((s, i) => (
              <div className="ps" key={i}>
                <span>{i + 1}</span>
                <span>{s}</span>
              </div>
            ))
          )}
          {path.sources.length ? (
            <small>
              Checked against {t.label} help:{" "}
              {path.sources.map((u, i) => (
                <React.Fragment key={u}>
                  {i ? ", " : ""}
                  <a href={u} target="_blank" rel="noopener noreferrer">
                    {i === 0 && path.feature ? path.feature : "STEP export"}
                  </a>
                </React.Fragment>
              ))}
            </small>
          ) : null}
        </div>
        <div className="gh" style={{ marginTop: 6 }}>
          <span>Price after the fix</span>
          <span>if redesigned · not a quote</span>
        </div>
        {best && e ? (
          <div className="kpfig">
            <div className="figs">
              <div className="fig">
                <span>{best.m.name}</span>
                <b className="num ok">{money(best.price)}</b>
                <small>
                  each at {qtyWord(uq)} · {e.material} · ±{Math.round(e.est_error_band_pct)}%
                </small>
              </div>
              {e.fixed_cost_usd > 0 && d?.tooling_process === best.m.code ? (
                <div className="fig">
                  <span>Tooling</span>
                  <b className="num">{money(e.fixed_cost_usd)}</b>
                  <small>one-off, in the price</small>
                </div>
              ) : null}
              {d?.tooling_process === best.m.code && d.crossover_qty && u.today ? (
                <div className="fig">
                  <span>Pays back from</span>
                  <b className="num">{qtyWord(Math.round(d.crossover_qty))}</b>
                  <small>parts, against {money(u.today.price)}</small>
                </div>
              ) : null}
            </div>
            <small>
              {red && red.process === best.m.code ? `From the cost engine’s price if redesigned (“${red.caveat}”). ` : "The cost engine’s price for this process on today’s shape. "}
              {u.today ? `Today’s cheapest at ${qtyWord(uq)} is ${u.today.m.name.toLowerCase()}, ${money(u.today.price)}.` : `Nothing can be ordered today at ${qtyWord(uq)}.`}
            </small>
          </div>
        ) : (
          <div className="kpfig">
            <small>
              {u.excluded.length && !u.partial.length
                ? `${u.excluded.map((m) => m.name).join(", ")} ${u.excluded.length === 1 ? "is" : "are"} ruled out by this part’s service conditions, so this fix adds no price: ${u.excluded[0].excludedReason}`
                : u.partial.length
                ? `No new price from this fix alone: each process it stops also needs ${[...new Set(u.partial.flatMap((x) => x.others.map((o) => o.title.toLowerCase())))].join(", ")}.`
                : p.data.cost
                  ? "Nothing it stops has a price at this quantity."
                  : "This part has an analysis only; the check on the fixed file prices it."}
            </small>
          </div>
        )}
        <div className="gh" style={{ marginTop: 6 }}>
          <span>Then upload the fixed file</span>
          <span />
        </div>
        <div className="kup">
          <button className="btn ink sm" type="button" onClick={up.pick}>
            Choose the fixed file
          </button>
          {up.el}
          <span>{newCheckLine(shell.usage, "Checked like any upload and saved as a new part")}</span>
        </div>
        {(() => {
          const r = fixRoute(P, fx.origin);
          if (r && r.kind !== "studio")
            return (
              <div className="kprop">
                <span className="chip c-ok">
                  <i />
                  ScaleCAD can do this itself
                </span>
                <b>{r.kind === "repair" ? "Mesh repair, on a copy" : `${r.fix.label}, on a copy`}</b>
                <span>It makes the change on a copy, checks the copy and shows both. Your file stays as it is.</span>
                <span>
                  <button className="btn sm" type="button" onClick={() => fx.openAsk(P.id, r.kind === "repair" ? "repair" : "server")}>
                    Fix it here
                  </button>
                </span>
              </div>
            );
          const why = fx.origin.server?.byFamily[P.id]?.whyNot ?? null;
          const can = fx.origin.server?.available.map((a) => a.label.toLowerCase()) ?? [];
          return (
            <div className="kprop">
              <span className="chip c-unk">
                <i />
                Not available yet
              </span>
              <b>{P.title}, fixed automatically</b>
              <span>
                {why && !/OpenCASCADE|CAD_FIX/.test(why) ? `${why} ` : P.id === "draft" ? "ScaleCAD doesn’t add draft to an uploaded file yet. " : ""}
                Today ScaleCAD fixes open meshes (mesh repair){can.length ? `; on uploaded files it can also ${can.join(", ")} where the check asks for it` : ""}; and Design Studio parts, as a new revision.
              </span>
            </div>
          );
        })()}
      </div>
      <div className="df">
        <button className="btn" type="button" onClick={close}>
          Close
        </button>
        <button className="btn ghost sp" type="button" onClick={() => (fx.closeAsk(), fx.openAll(P.id))}>
          All problems on this part
        </button>
      </div>
    </>
  );
}
