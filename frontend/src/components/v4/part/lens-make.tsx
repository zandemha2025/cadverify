"use client";

/** Process (DFM): every way to make it, grouped and ranked, the picked one opened with its finding on the part. */
import * as React from "react";
import { closestUnconfirmedModel, identityCardModel } from "@/lib/verify/identity";
import { confirmIdentity } from "@/lib/verify/identity-api";
import { Loading, cx } from "../ui";
import { usePart } from "./ctx";
import {
  VERDICT_LABEL,
  cheapestAt,
  days,
  dfmMeta,
  fixesOf,
  makeRows,
  methodName,
  methodSub,
  methodWhy,
  money,
  plural,
  priceAt,
  priceMeta,
  qtyWord,
  shortId,
  type Method,
} from "./model";
import { RunNotice, SheetTop, classLabel, envLine, type FigItem } from "./sheet-bits";
import { useFix } from "../fix/ctx";
import { notListedKind, problemForIssue } from "../fix/problems";
import { pairAt, pickWhy, recordedChoice, enginePick } from "./choice";
import { featureCells } from "../workbench/derive";
import { useChoice } from "./choose";
import { problemsFigure, rowNote } from "./pick-words";
import { inText } from "../units/units";
import { useUnits } from "../units/use-units";

function chipTone(m: Method): string {
  return m.verdict === "out" ? "c-bad" : m.verdict === "unk" ? "c-unk" : `c-${m.verdict}`;
}

export function costCell(m: Method, q: number, opts: { pricing: boolean; costOff: boolean }): string {
  if (m.verdict === "out") return "—";
  if (opts.costOff) return m.prices.size ? "Not priced" : "Not priced";
  if (opts.pricing) return "Pricing…";
  const p = priceAt(m, q);
  return p != null ? money(p) : "Not priced";
}

function Identity() {
  const p = usePart();
  const id = p.data.identity;
  const confident = React.useMemo(() => identityCardModel(id), [id]);
  const low = React.useMemo(() => closestUnconfirmedModel(id), [id]);
  const [mode, setMode] = React.useState<"ask" | "manual" | "hidden" | "done">("ask");
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [doneText, setDoneText] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const card = confident ?? low;
  const key = p.data.key;
  if (!key || (!card && mode === "ask")) return null;
  const save = async (input: { declared_part_id?: string | null; declared_name?: string | null; program?: string | null }, label: string) => {
    setBusy(true);
    setErr(null);
    const res = await confirmIdentity({ mesh_hash: key, ...input });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    setDoneText(label);
    setMode("done");
    p.toast({ text: mode === "manual" ? `Identity saved: ${label}` : "Identity confirmed and saved to your part library" });
  };
  if (mode === "done")
    return (
      <div className="gh" style={{ paddingTop: 8 }}>
        <span style={{ color: "var(--ok)" }}>✓ Identity: {doneText}</span>
        <span>
          <button className="btn sm ghost" type="button" onClick={() => setMode("manual")} style={{ height: 24 }}>
            Change
          </button>
        </span>
      </div>
    );
  if (mode === "hidden")
    return (
      <div className="gh" style={{ paddingTop: 8 }}>
        <span>Identity not confirmed</span>
        <span>
          <button className="btn sm ghost" type="button" onClick={() => setMode("ask")} style={{ height: 24 }}>
            Show again
          </button>
        </span>
      </div>
    );
  if (mode === "manual")
    return (
      <div className="note swap" style={{ margin: "6px 12px 6px" }}>
        <b style={{ fontSize: 14 }}>What is this part?</b>
        <label className="field">
          Part number or name
          <input type="text" placeholder="for example 4471-203 rev B" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" />
        </label>
        <span style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn sm ink" type="button" disabled={!text.trim() || busy} onClick={() => void save({ declared_name: text.trim() }, `${text.trim()} · yours`)}>
            {busy ? "Saving…" : "Save identity"}
          </button>
          <button className="btn sm" type="button" onClick={() => setMode(card ? "ask" : "hidden")}>
            Cancel
          </button>
          <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Saved to your part library</span>
        </span>
        {err ? <span role="alert" style={{ color: "var(--bad)", fontSize: 12.5 }}>{err}</span> : null}
      </div>
    );
  if (!card) return null;
  const m = card.match;
  const who = (m.declared_name || m.declared_part_id || "").trim();
  const pct = card.pct;
  const bucket = confident ? confident.bucket.toLowerCase() : "low";
  const runners = id?.matches.filter((x) => x.mesh_hash !== m.mesh_hash).slice(0, 2) ?? [];
  return (
    <div className="note" style={{ margin: "6px 12px 6px", gap: 5 }}>
      <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <b style={{ fontSize: 14 }}>{confident ? "Looks like a part in your library" : "Closest in your library"}</b>
        <span className={cx("chip", confident ? "c-ok" : "c-warn")}>
          <i />
          {pct}% · {bucket}
        </span>
      </span>
      <span>
        <span className="mono" style={{ fontSize: 12.5, color: "var(--ink)" }}>
          {who}
        </span>
        {" · "}shape {Math.round(m.geometry_similarity * 100)}% · name {m.name_similarity != null ? `${Math.round(m.name_similarity * 100)}%` : "not compared"} · {plural(id?.corpus_size ?? 0, "part")} searched
      </span>
      <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>
        A suggestion to confirm, not an identity.
        {runners.length ? ` Also near: ${runners.map((r) => `${(r.declared_name || r.declared_part_id || "unnamed").trim()} ${Math.round(r.combined_confidence * 100)}%`).join(", ")}.` : ""}{" "}
        <span className="mono">{m.mesh_hash.slice(0, 8)}</span>
      </span>
      <span style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 2 }}>
        <button
          className="btn sm ink"
          type="button"
          disabled={busy}
          title="Confirm this identity onto your part library"
          onClick={() => void save({ declared_part_id: m.declared_part_id, declared_name: m.declared_name, program: m.program }, `${who} · confirmed by you`)}
        >
          {busy ? "Confirming…" : "It's this part"}
        </button>
        <button className="btn sm" type="button" onClick={() => setMode("manual")}>
          Not this
        </button>
        <button className="btn sm ghost" type="button" onClick={() => setMode("hidden")}>
          Hide
        </button>
      </span>
      {err ? <span role="alert" style={{ color: "var(--bad)", fontSize: 12.5 }}>{err}</span> : null}
    </div>
  );
}

/** Find and fix: every problem on the part, ranked by what fixing it unlocks (board K4). */
function ProblemsEntry() {
  const fx = useFix();
  const n = fx.set.problems.length;
  if (!n) return null;
  const blocking = fx.set.problems.filter((x) => x.severity === "error").length;
  return (
    <div className="gh" style={{ marginTop: 6 }}>
      <span>
        {plural(n, "problem")} on this part{blocking ? ` · ${blocking} ${blocking === 1 ? "stops" : "stop"} processes` : ""}
      </span>
      <span>
        <button className="btn sm ghost" type="button" onClick={() => fx.openAll()} style={{ height: 24 }}>
          All problems
        </button>
      </span>
    </div>
  );
}

function Fixes() {
  const p = usePart();
  const [open, setOpen] = React.useState(false);
  const fixes = fixesOf(p.data.validation);
  if (!fixes.length) return null;
  return (
    <>
      <div className="gh" style={{ marginTop: 6 }}>
        <span>
          {plural(fixes.length, "suggested fix", "suggested fixes")} across processes, most important first
        </span>
        <span>
          <button className="btn sm ghost" type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} style={{ height: 24 }}>
            {open ? "Hide" : "Show all"}
          </button>
        </span>
      </div>
      {open ? (
        <div className="lines swap">
          {fixes.map((x) => (
            <div key={x.n} className="ln" style={{ gridTemplateColumns: "22px minmax(0,1fr) auto", alignItems: "start" }}>
              <span className="num" style={{ color: "var(--ink3)" }}>
                {x.n}
              </span>
              <span>
                <b style={{ textAlign: "left", display: "block" }}>{x.where}</b>
                <span style={{ color: "var(--ink2)" }}>{x.fix}</span>
              </span>
              <span className={`chip c-${x.tone}`}>
                <i />
                {x.sev}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}

export function makeTop(p: ReturnType<typeof usePart>, problems: { severity: string }[]): { title: string; meta: string; figs: FigItem[] } {
  const v = p.data.validation;
  const cls = p.data.cost?.material_class ?? null;
  if (p.interrupted) return { title: "Check interrupted", meta: "Nothing computed · the file is kept", figs: [{ k: "Processes", v: "Not checked", tone: "warn" }, { k: "File", v: "Kept", s: "no re-export needed" }] };
  const singles = p.methods;
  if (p.checking) {
    const gp = singles.find((m) => m.geometryPick);
    return {
      title: "Checking",
      meta: `Shape and walls, then ${v ? v.process_scores.length : 21} processes, then prices · about 30 s`,
      figs: [
        // The design-rule best so far, not a pick: ScaleCAD's pick comes with the prices.
        v && gp
          ? { k: "Highest design score", v: gp.name, s: `${gp.short} · DFM ${gp.dfm ?? "—"} · the pick comes with prices` }
          : { k: "Highest design score", v: "Measuring…" },
        { k: "Processes checked", v: v ? `${v.process_scores.length} of ${v.process_scores.length}` : "Waiting" },
        { k: "Priced", v: "Pricing…", s: "arrives with the record" },
      ],
    };
  }
  const can = singles.filter((m) => m.verdict === "ok" || m.verdict === "warn").length;
  const env = envLine(p.data.runEnvironment);
  const figs: FigItem[] = [{ k: "Can make", v: `${can} of ${singles.length}`, s: "processes", tone: can ? "ok" : "bad" }];
  // The same count as the problem list below (not the engine's per-process fixes and overall verdict).
  const fixesFig: FigItem = problemsFigure(problems);
  const meta = `${classLabel(cls)} · ${env ?? "no service conditions set"}`;
  const c = cheapestAt(p.methods, p.q);
  // Your choice, else ScaleCAD's pick, next to the other side when a machine of yours can make it.
  const choice = recordedChoice(p.data.decision);
  const chosen = choice ? p.methods.find((m) => m.code === choice.process) ?? null : null;
  const pair = pairAt(p.data.cost, p.q);
  const pick = enginePick(p.data.cost, p.q);
  if (!p.costOff && chosen && chosen.prices.has(p.q)) {
    const e = chosen.prices.get(p.q)!;
    figs.push({ k: `Your choice at ${qtyWord(p.q)}`, v: money(e.unit_cost_usd), s: `${chosen.name}${chosen.inHouse ? ` · your ${chosen.inHouse}` : " · outside"} · ${days(e.lead_time?.low_days, e.lead_time?.high_days)}` });
    if (c && c.code !== chosen.code) figs.push({ k: `Cheapest at ${qtyWord(p.q)}`, v: money(priceAt(c, p.q)), s: `${c.name} · ${c.short}` });
    else figs.push(fixesFig);
    return { title: "Ways to make it", meta, figs };
  }
  if (!p.costOff && pair && pick) {
    const mine = pair.in_house;
    const out = pair.outside;
    if (pair.pick === "in_house") {
      figs.push({ k: `In-house at ${qtyWord(p.q)}`, v: money(mine.unit_cost_usd), s: `ScaleCAD’s pick · ${mine.machine ?? methodName(mine.process)} · ${days(mine.lead_low_days, mine.lead_high_days)}`, tone: "ok" });
      if (out) figs.push({ k: "Cheapest outside", v: money(out.unit_cost_usd), s: `${methodName(out.process)} · ${days(out.lead_low_days, out.lead_high_days)}` });
    } else {
      if (out) figs.push({ k: `Outside at ${qtyWord(p.q)}`, v: money(out.unit_cost_usd), s: `ScaleCAD’s pick · ${methodName(out.process)} · ${days(out.lead_low_days, out.lead_high_days)}` });
      figs.push({ k: `On your ${mine.machine ?? "machine"}`, v: money(mine.unit_cost_usd), s: `in-house · ${days(mine.lead_low_days, mine.lead_high_days)}` });
    }
    return { title: "Ways to make it", meta, figs };
  }
  if (p.costOff) figs.push({ k: "Prices", v: "Didn’t finish", s: "processes are ready", tone: "warn" });
  else if (c) figs.push({ k: `Cheapest at ${qtyWord(p.q)}`, v: money(priceAt(c, p.q)), s: `${c.name} · ${c.short}` });
  else if (!p.data.cost) figs.push({ k: "Prices", v: "Not priced yet", s: "this part has an analysis only" });
  const ih = p.methods.find((m) => m.inHouse && m.prices.has(p.q));
  if (ih && !p.costOff) figs.push({ k: ih.inHouse!, v: money(priceAt(ih, p.q)), s: `in-house · ${ih.short} ${ih.prices.get(p.q)!.material}` });
  else figs.push(fixesFig);
  return { title: "Ways to make it", meta, figs };
}

/** "your choice" / "ScaleCAD's pick" after a row's sub line: one pick; the design best and the usual route are evidence. */
function rowTag(m: Method, ch: ReturnType<typeof useChoice>): string {
  return rowNote(m, ch.choice?.process ?? null, ch.pick?.process ?? null);
}

/** The problem a process's row stands for: its own finding, else the first one that stops it. */
function problemOfMethod(fx: ReturnType<typeof useFix>, m: Method) {
  return problemForIssue(fx.set, m.finding?.issue.code) ?? fx.set.problems.find((x) => m.members.some((c) => x.blocks.includes(c))) ?? null;
}

/** How the process was chosen (it was the cost breakdown's DFM tab): the route, its reasons, rules and detected features. */
function HowJudged() {
  const p = usePart();
  const [open, setOpen] = React.useState(false);
  const r = p.data.cost?.routing ?? null;
  const v = p.data.validation;
  const cells = featureCells(v?.features);
  if (!r && !v) return null;
  const drv = r?.drivers ?? {};
  const rows: [string, string][] = [];
  if (r) rows.push(["Recommended process", `${methodName(r.recommended_process)} · confidence ${r.confidence.toFixed(1)}`]);
  if (r?.alternatives?.length) rows.push(["Alternatives", r.alternatives.map(methodName).join(", ")]);
  if (typeof drv.nominal_wall_mm === "number") rows.push(["Nominal wall", `${(drv.nominal_wall_mm as number).toFixed(1)} mm`]);
  if (typeof drv.rotational === "boolean") rows.push(["Round", drv.rotational ? "Yes" : "No"]);
  if (typeof drv.sheet_like === "boolean") rows.push(["Sheet-like", drv.sheet_like ? "Yes" : "No"]);
  rows.push(["Design rules", v?.rule_pack ? `Rule pack ${v.rule_pack.name} ${v.rule_pack.version}` : "Typical limits per process, cited on each problem"]);
  return (
    <>
      <div className="gh" style={{ marginTop: 6 }}>
        <span>How the process was chosen</span>
        <span>
          <button className="btn sm ghost" type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} style={{ height: 24 }}>
            {open ? "Hide" : "Show"}
          </button>
        </span>
      </div>
      {open ? (
        <div className="swap" style={{ margin: "0 12px", display: "flex", flexDirection: "column", gap: 8, fontSize: 13, color: "var(--ink2)" }}>
          {r?.reasoning ? <p style={{ margin: 0 }}>{r.reasoning}</p> : null}
          <div className="kv" style={{ padding: 0 }}>
            {rows.map(([k, val]) => (
              <React.Fragment key={k}>
                <span>{k}</span>
                <b className="num">{val}</b>
              </React.Fragment>
            ))}
          </div>
          {cells.length ? <span style={{ color: "var(--ink3)" }}>Detected features: {cells.map((c) => `${c.n} ${c.label.toLowerCase()}`).join(" · ")}</span> : null}
        </div>
      ) : null}
    </>
  );
}

export function MakeSheet() {
  const p = usePart();
  const fx = useFix();
  const ch = useChoice();
  const top = makeTop(p, fx.set.problems);
  const pricing = p.checking && !p.data.cost;
  const rows = makeRows(p.rows, p.q);
  return (
    <>
      <SheetTop {...top} sure="make" />
      <div className="scroll">
        <RunNotice />
        {!p.interrupted ? (
          <div className="swap">
            {!p.checking ? <Identity /> : null}
            {!p.checking && !p.costOff ? <PickNote ch={ch} /> : null}
            {!p.data.validation && !p.data.cost ? (
              <Loading rows={6} label="Checking the ways to make it" />
            ) : (
              rows.map((r, i) => {
                if (r.kind === "group")
                  return (
                    <div className="gh" key={`g${i}`}>
                      <span>{r.label}</span>
                      <span>{r.right}</span>
                    </div>
                  );
                const m = r.method!;
                const on = p.sel?.code === m.code;
                return (
                  <React.Fragment key={m.code}>
                    <button
                      type="button"
                      className={cx("mr", on && "on", m.verdict === "out" && "out")}
                      onClick={() => {
                        p.setSel(m.code);
                        // A process that can't make it as drawn opens why, on the part, in one click.
                        const why = m.verdict === "bad" && !p.checking ? problemOfMethod(fx, m) : null;
                        if (why) fx.openProblem(why.id, m.members.length === 1 ? m.code : null);
                      }}
                      aria-pressed={on}
                      title={m.verdict === "bad" && !p.checking && problemOfMethod(fx, m) ? "Opens why, on the part" : undefined}
                    >
                      <span>
                        <b>{m.name}</b>
                        <small>
                          {methodSub({ ...m, geometryPick: false, routePick: false })}
                          {rowTag(m, ch)}
                        </small>
                      </span>
                      <span className={cx("chip", chipTone(m))}>
                        <i />
                        {VERDICT_LABEL[m.verdict]}
                      </span>
                      <span className="c num">{costCell(m, p.q, { pricing, costOff: p.costOff })}</span>
                    </button>
                    {on ? <Detail m={m} pricing={pricing} ch={ch} /> : null}
                  </React.Fragment>
                );
              })
            )}
            {p.data.cost && p.data.cost.material_class === "polymer" && p.rows.some((m) => m.members.length > 1) ? null : null}
            {!p.checking ? <ProblemsEntry /> : null}
            <Fixes />
            {!p.checking ? <HowJudged /> : null}
          </div>
        ) : null}
      </div>
    </>
  );
}

function Detail({ m, pricing, ch }: { m: Method; pricing: boolean; ch: ReturnType<typeof useChoice> }) {
  const p = usePart();
  const fx = useFix();
  // The problem behind this process's finding, or the first one that stops it.
  const problem = problemOfMethod(fx, m);
  // A setup, precision or paperwork note on a process that can make it isn't a design problem: one quiet line, the text a click away.
  const noteOnly = m.verdict === "ok" && !!m.finding && notListedKind(m.finding.issue) != null;
  const { unit } = useUnits();
  const [noteOpen, setNoteOpen] = React.useState(false);
  const kind = m.finding?.kind ?? null;
  const lit = !!kind && (m.finding?.faces.length ?? 0) > 0;
  const price = !pricing && !p.costOff ? priceMeta(m, p.q) : null;
  const meta = [dfmMeta(m), price].filter(Boolean).join(" · ");
  const why = inText(methodWhy(m, p.data.cost?.material_class ?? null), unit);
  return (
    <div className="det swap">
      <div className="f">
        <i className={`k-${lit ? kind : "none"}`} aria-hidden="true">
          {lit ? "1" : "i"}
        </i>
        <span>{noteOnly ? "Nothing stops it as drawn." : why}</span>
      </div>
      {noteOnly ? (
        <span>
          <button className="btn sm ghost" type="button" aria-expanded={noteOpen} onClick={() => setNoteOpen((o) => !o)} style={{ height: 24, padding: "0 6px" }}>
            {noteOpen ? "Hide the note" : "1 note, not a design problem"}
          </button>
          {noteOpen ? <span className="swap" style={{ display: "block", marginTop: 4, color: "var(--ink3)" }}>{why}</span> : null}
        </span>
      ) : null}
      <span style={{ color: "var(--ink3)" }}>{meta}</span>
      {m.members.length > 1 ? <span style={{ color: "var(--ink3)" }}>{m.members.map(methodName).join(", ")}</span> : null}
      {!p.checking ? <ChooseRow m={m} ch={ch} /> : null}
      {(lit && p.canTurn) || (problem && !p.checking && !noteOnly) ? (
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {lit && p.canTurn ? (
            <button className="btn sm" type="button" onClick={p.turnTo}>
              Turn to it
            </button>
          ) : null}
          {problem && !p.checking && !noteOnly ? (
            <button className="btn sm fwhy" type="button" onClick={() => fx.openProblem(problem.id, m.members.length === 1 ? m.code : null)}>
              {m.verdict === "bad" ? "Why it can’t, on the part" : m.verdict === "warn" ? "The warning, on the part" : "See it on the part"}
            </button>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}

/** Make it this way, or say it's your choice with the way back to ScaleCAD's pick. */
function ChooseRow({ m, ch }: { m: Method; ch: ReturnType<typeof useChoice> }) {
  const p = usePart();
  const mine = ch.choice?.process === m.code;
  if (!mine && !ch.canChoose(m)) return null;
  const where = m.inHouse ? `on your ${m.inHouse}` : "outside";
  return (
    <span style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
      {mine ? (
        <>
          <span style={{ color: "var(--ok)", fontWeight: 600, fontSize: 13 }}>✓ Your choice, {where}</span>
          <button className="btn sm ghost" type="button" disabled={!!ch.busy} onClick={() => void ch.backToPick()}>
            {ch.busy === "back" ? "Going back…" : "Back to ScaleCAD’s pick"}
          </button>
        </>
      ) : (
        <button className="btn sm ink" type="button" disabled={!!ch.busy} onClick={() => void ch.makeThisWay(m)} title={`Save ${m.name.toLowerCase()} ${where} as the way to make this part. Prices, lead time and next steps follow it.`}>
          {ch.busy === m.code ? "Saving…" : `Make it this way, ${where}`}
        </button>
      )}
      {!mine && ch.pick?.process === m.code ? <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>ScaleCAD’s pick at {qtyWord(p.q)}</span> : null}
      {ch.err ? (
        <span role="alert" style={{ color: "var(--bad)", fontSize: 12.5, flexBasis: "100%" }}>
          {ch.err}
        </span>
      ) : null}
    </span>
  );
}

/** When a machine of yours can make it: what ScaleCAD picked at this quantity and why, in its own numbers. */
export function PickNote({ ch }: { ch: ReturnType<typeof useChoice> }) {
  const p = usePart();
  const [rule, setRule] = React.useState(false);
  const pair = ch.pair;
  if (ch.earlier) return <EarlierNote ch={ch} />;
  if (!pair || ch.choice) return null;
  const inHouse = pair.pick === "in_house";
  const title = inHouse
    ? `ScaleCAD’s pick at ${qtyWord(p.q)}: ${methodName(pair.in_house.process).toLowerCase()} on your ${pair.in_house.machine ?? "machine"}`
    : `ScaleCAD’s pick at ${qtyWord(p.q)}: ${methodName(pair.outside?.process).toLowerCase()} outside`;
  return (
    <div className="note" style={{ margin: "6px 12px 6px" }}>
      <b>{title}</b>
      <span>{pickWhy(pair, p.q)}</span>
      <span style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button className="btn sm ghost" type="button" aria-expanded={rule} onClick={() => setRule((r) => !r)} style={{ height: 24 }}>
          {rule ? "Hide the rule" : "How ScaleCAD picks"}
        </button>
        <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Open any process below to make it that way instead.</span>
      </span>
      {rule && p.data.cost?.decision?.rule ? <span className="swap" style={{ color: "var(--ink2)", fontSize: 12.5 }}>{p.data.cost.decision.rule}</span> : null}
    </div>
  );
}

/** A way to make it chosen on an earlier check of this part: keep it on this check, or not. */
function EarlierNote({ ch }: { ch: ReturnType<typeof useChoice> }) {
  const p = usePart();
  const e = ch.earlier!;
  const m = ch.earlierMethod;
  const where = e.kind === "inhouse" ? `on your ${m?.inHouse ?? "machine"}` : "outside";
  const when = e.at ? new Date(e.at).toLocaleDateString("en-US", { day: "numeric", month: "short" }) : null;
  const why = !m
    ? "That process isn't in this check."
    : !m.prices.has(p.q)
      ? `It isn't priced at ${qtyWord(p.q)} in this check.`
      : e.kind === "inhouse" && !m.inHouse
        ? "None of your machines clears it in this check."
        : !ch.canKeep
          ? "It can't make the part as checked now."
          : `${money(priceAt(m, p.q))} each at ${qtyWord(p.q)} in this check.`;
  return (
    <div className="note" style={{ margin: "6px 12px 6px" }}>
      <b>
        Your choice on an earlier check: {methodName(e.process).toLowerCase()} {where}
      </b>
      <span>
        {[when, `record ${shortId(e.recordId)}`].filter(Boolean).join(" · ")}. This check made a new record. {why}
      </span>
      <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn sm ink" type="button" disabled={!ch.canKeep || !!ch.busy} onClick={() => void ch.keepEarlier()}>
          {ch.busy && m && ch.busy === m.code ? "Saving…" : "Keep it on this check"}
        </button>
        <span style={{ color: "var(--ink3)", fontSize: 12.5, alignSelf: "center" }}>Or open any process below to make it another way.</span>
      </span>
      {ch.err ? (
        <span role="alert" style={{ color: "var(--bad)", fontSize: 12.5 }}>
          {ch.err}
        </span>
      ) : null}
    </div>
  );
}
