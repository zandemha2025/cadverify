"use client";

/** Make: every way to make it, grouped and ranked, the picked one opened with its finding on the part. */
import * as React from "react";
import { closestUnconfirmedModel, identityCardModel } from "@/lib/verify/identity";
import { confirmIdentity } from "@/lib/verify/identity-api";
import { Loading, cx } from "../ui";
import { usePart } from "./ctx";
import {
  VERDICT_LABEL,
  cheapestAt,
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
  type Method,
} from "./model";
import { RunNotice, SheetTop, classLabel, envLine, type FigItem } from "./sheet-bits";
import { useFix } from "../fix/ctx";
import { problemForIssue } from "../fix/problems";

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
        {plural(n, "problem")} on this part{blocking ? ` · ${blocking} ${blocking === 1 ? "stops" : "stop"} methods` : ""}
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
          {plural(fixes.length, "fix", "fixes")} across methods, most important first · overall: {p.data.validation?.overall_verdict ?? "unknown"}
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

export function makeTop(p: ReturnType<typeof usePart>): { title: string; meta: string; figs: FigItem[] } {
  const v = p.data.validation;
  const cls = p.data.cost?.material_class ?? null;
  if (p.interrupted) return { title: "Check interrupted", meta: "Nothing computed · the file is kept", figs: [{ k: "Methods", v: "Not checked", tone: "warn" }, { k: "File", v: "Kept", s: "no re-export needed" }] };
  const singles = p.methods;
  if (p.checking) {
    const gp = singles.find((m) => m.geometryPick);
    return {
      title: "Checking",
      meta: `Shape and walls, then ${v ? v.process_scores.length : 21} methods, then prices · about 30 s`,
      figs: [
        v && gp
          ? { k: "First pick", v: gp.name, s: `${gp.short} · DFM ${gp.dfm ?? "—"} · analysis ${(v.analysis_time_ms / 1000).toFixed(1)} s` }
          : { k: "First pick", v: "Measuring…" },
        { k: "Methods checked", v: v ? `${v.process_scores.length} of ${v.process_scores.length}` : "Waiting" },
        { k: "Priced", v: "Pricing…", s: "arrives with the record" },
      ],
    };
  }
  const can = singles.filter((m) => m.verdict === "ok" || m.verdict === "warn").length;
  const env = envLine(p.data.runEnvironment);
  const figs: FigItem[] = [{ k: "Can make", v: `${can} of ${singles.length}`, s: "methods", tone: can ? "ok" : "bad" }];
  const c = cheapestAt(p.methods, p.q);
  if (p.costOff) figs.push({ k: "Prices", v: "Didn’t finish", s: "methods are ready", tone: "warn" });
  else if (c) figs.push({ k: `Cheapest at ${qtyWord(p.q)}`, v: money(priceAt(c, p.q)), s: `${c.name} · ${c.short}` });
  else if (!p.data.cost) figs.push({ k: "Prices", v: "Not priced yet", s: "this part has an analysis only" });
  const ih = p.methods.find((m) => m.inHouse && m.prices.has(p.q));
  if (ih && !p.costOff) figs.push({ k: ih.inHouse!, v: money(priceAt(ih, p.q)), s: `in-house · ${ih.short} ${ih.prices.get(p.q)!.material}` });
  else figs.push({ k: "Fixes", v: String(v?.priority_fixes?.length ?? 0), s: `overall: ${v?.overall_verdict ?? "unknown"}` });
  return { title: "Ways to make it", meta: `${classLabel(cls)} · ${env ?? "no service conditions set"}`, figs };
}

export function MakeSheet() {
  const p = usePart();
  const top = makeTop(p);
  const pricing = p.checking && !p.data.cost;
  const rows = makeRows(p.rows, p.q);
  return (
    <>
      <SheetTop {...top} />
      <div className="scroll">
        <RunNotice />
        {!p.interrupted ? (
          <div className="swap">
            {!p.checking ? <Identity /> : null}
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
                    <button type="button" className={cx("mr", on && "on", m.verdict === "out" && "out")} onClick={() => p.setSel(m.code)} aria-pressed={on}>
                      <span>
                        <b>{m.name}</b>
                        <small>{methodSub(m)}</small>
                      </span>
                      <span className={cx("chip", chipTone(m))}>
                        <i />
                        {VERDICT_LABEL[m.verdict]}
                      </span>
                      <span className="c num">{costCell(m, p.q, { pricing, costOff: p.costOff })}</span>
                    </button>
                    {on ? <Detail m={m} pricing={pricing} /> : null}
                  </React.Fragment>
                );
              })
            )}
            {p.data.cost && p.data.cost.material_class === "polymer" && p.rows.some((m) => m.members.length > 1) ? null : null}
            {!p.checking ? <ProblemsEntry /> : null}
            <Fixes />
          </div>
        ) : null}
      </div>
    </>
  );
}

function Detail({ m, pricing }: { m: Method; pricing: boolean }) {
  const p = usePart();
  const fx = useFix();
  // The problem behind this method's finding, or the first one that stops it.
  const problem = problemForIssue(fx.set, m.finding?.issue.code) ?? fx.set.problems.find((x) => m.members.some((c) => x.blocks.includes(c))) ?? null;
  const kind = m.finding?.kind ?? null;
  const lit = !!kind && (m.finding?.faces.length ?? 0) > 0;
  const price = !pricing && !p.costOff ? priceMeta(m, p.q) : null;
  const meta = [dfmMeta(m), price].filter(Boolean).join(" · ");
  return (
    <div className="det swap">
      <div className="f">
        <i className={`k-${lit ? kind : "none"}`} aria-hidden="true">
          {lit ? "1" : "i"}
        </i>
        <span>{methodWhy(m, p.data.cost?.material_class ?? null)}</span>
      </div>
      <span style={{ color: "var(--ink3)" }}>{meta}</span>
      {m.members.length > 1 ? <span style={{ color: "var(--ink3)" }}>{m.members.map(methodName).join(", ")}</span> : null}
      {(lit && p.canTurn) || (problem && !p.checking) ? (
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {lit && p.canTurn ? (
            <button className="btn sm" type="button" onClick={p.turnTo}>
              Turn to it
            </button>
          ) : null}
          {problem && !p.checking ? (
            <button className="btn sm" type="button" onClick={() => fx.openProblem(problem.id, m.members.length === 1 ? m.code : null)}>
              The problem and its fix
            </button>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}
