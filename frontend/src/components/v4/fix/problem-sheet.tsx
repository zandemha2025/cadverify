"use client";

/** K1: one problem on the part. What was measured, what each method needs, why, the fix, and what fixing it unlocks. */
import * as React from "react";
import { useRouter } from "next/navigation";
import { cx } from "../ui";
import { setPendingFile, CAD_ACCEPT } from "../pending-file";
import { R } from "../routes";
import { usePart } from "../part/ctx";
import { classLabel } from "../part/sheet-bits";
import { qtyWord } from "../part/model";
import { useFix } from "./ctx";
import { alternativeOf, fixText, plainReason, problemFigs, ruleOf, shortText, type Problem } from "./problems";
import { unlockOf, unlockQty, unlockRows } from "./rank";
import { canFixLine, fixRoute } from "./capabilities";
import "./fix.css";

export function blocksChip(p: Problem, total: number): { text: string; tone: string } {
  if (p.severity === "error") {
    if (p.universal || (total > 0 && p.blocks.length >= total)) return { text: "Blocks every method", tone: "c-bad" };
    return { text: `Blocks ${p.blocks.length} ${p.blocks.length === 1 ? "method" : "methods"}`, tone: "c-bad" };
  }
  const n = p.warns.length;
  if (p.universal && !n) return { text: "Flags every method", tone: "c-warn" };
  return { text: `Flags ${n} ${n === 1 ? "method" : "methods"}`, tone: "c-warn" };
}

/** The roving radio list: arrows move and pick, Home and End jump. */
export function roving<T>(list: T[], i: number, pick: (j: number) => void) {
  return (e: React.KeyboardEvent<HTMLButtonElement>) => {
    const k = e.key;
    const j = k === "ArrowDown" || k === "ArrowRight" ? (i + 1) % list.length : k === "ArrowUp" || k === "ArrowLeft" ? (i - 1 + list.length) % list.length : k === "Home" ? 0 : k === "End" ? list.length - 1 : -1;
    if (j < 0) return;
    e.preventDefault();
    const g = e.currentTarget.closest("[role=radiogroup]");
    pick(j);
    window.setTimeout(() => (g?.querySelectorAll<HTMLButtonElement>("[role=radio]")[j])?.focus(), 0);
  };
}

/** Upload a fixed file: it's checked like any upload and saved as a new part. */
export function useUploadFixed() {
  const router = useRouter();
  const input = React.useRef<HTMLInputElement>(null);
  const el = (
    <input
      ref={input}
      type="file"
      accept={CAD_ACCEPT}
      aria-label="Choose the fixed CAD file"
      tabIndex={-1}
      style={{ display: "none" }}
      onChange={(e) => {
        const f = e.target.files?.[0];
        e.target.value = "";
        if (!f) return;
        setPendingFile(f);
        router.push(R.check);
      }}
    />
  );
  return { el, pick: () => input.current?.click() };
}

export function ProblemSheet() {
  const p = usePart();
  const fx = useFix();
  const up = useUploadFixed();
  const P = fx.problem;
  if (!P) {
    return (
      <>
        <div className="top">
          <h2 className="stitle">Not on this part</h2>
          <p className="smeta">This check didn’t report that problem.</p>
        </div>
        <div className="scroll">
          <p className="kplain">
            <button className="btn sm" type="button" onClick={() => fx.openAll()}>
              All problems on this part
            </button>
          </p>
        </div>
      </>
    );
  }
  const m = fx.method;
  const total = fx.set.processes.length || p.methods.length;
  const chip = blocksChip(P, total);
  const priced = p.methods.filter((x) => x.members.length === 1).length;
  const figs = problemFigs(P, m, priced || total);
  const rule = ruleOf(P, m);
  const fix = fixText(P, m, alternativeOf(p.data.validation, P));
  const uq = unlockQty(P, fx.set, p.methods, p.data.cost, p.q, p.qs);
  const u = unlockOf(P, fx.set, p.methods, uq);
  const route = fixRoute(P, fx.origin);
  const { rows, foot } = unlockRows(u, { cost: p.data.cost, methodsTotal: total, picked: m?.code ?? null, repairable: route?.kind === "repair", set: fx.set });
  const at = P.id === "open" ? `today: ${p.methods.filter((x) => x.prices.size > 0).length} of ${total} priced` : `at ${qtyWord(uq)} ${uq === 1 ? "part" : "parts"}, ${classLabel(p.data.cost?.material_class).toLowerCase()}`;
  const go =
    route?.kind === "repair"
      ? { label: "Repair it here", run: () => fx.openAsk(P.id, "repair") }
      : route?.kind === "studio"
        ? { label: "Fix it", run: () => fx.openAsk(P.id, "studio") }
        : { label: "How to fix it", run: () => fx.openAsk(P.id, "upload") };
  const alt =
    route?.kind === "repair"
      ? { label: "Fix it in CAD", run: () => fx.openAsk(P.id, "upload") }
      : route?.kind === "studio"
        ? { label: "Steps for your CAD tool", run: () => fx.openAsk(P.id, "upload") }
        : { label: "Upload the fixed file", run: up.pick };
  const head = P.id === "thin" ? "Same wall, by method" : P.id === "draft" ? "Same walls, by method" : "Same problem, by method";
  const list = P.universal ? [] : P.methods;
  const mi = Math.max(0, list.findIndex((x) => x.code === m?.code));
  const count = fx.set.problems.length;
  return (
    <>
      <div className="top">
        <div className="kkick">
          <span className={cx("chip", chip.tone)}>
            <i />
            {chip.text}
          </span>
          <span>
            <button className="btn sm" type="button" onClick={fx.turn} disabled={!fx.canTurn} title={fx.canTurn ? (fx.pin === "inside" ? "Turn on X-ray to see inside the part" : "Turn the part to face it") : "Needs the 3D view"}>
              Turn to it
            </button>
            <button className="btn sm ghost" type="button" onClick={() => fx.openAll(P.id)}>
              <span className="on-desk">All {count} problems</span>
              <span className="on-phone">All {count}</span>
            </button>
          </span>
        </div>
        <h2 className="stitle">{P.title}</h2>
        <p className="smeta">
          {P.where} · <span className="kcode">{P.codes.join(" · ")}</span>
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
        <div className="kgo1">
          <button className="btn ink" type="button" onClick={go.run}>
            {go.label}
          </button>
        </div>
      </div>
      <div className="scroll">
        <div className="swap" key={`${P.id}:${m?.code ?? ""}`}>
          <p className="kplain">{plainReason(P, m, total)}</p>
          <div className="krule">
            <span>Why</span>
            <span>{rule.text}</span>
            <span>Cited</span>
            <span>{rule.source}</span>
          </div>
        </div>
        <div className="gh" style={{ marginTop: 6 }}>
          <span>The fix</span>
          <span />
        </div>
        <p className="kfixt">
          {fix.fix}
          {fix.alt ? <small>{fix.alt}</small> : null}
        </p>
        <div className="gh" style={{ marginTop: 6 }}>
          <span>What fixing it unlocks</span>
          <span>{p.data.cost || P.id === "open" ? at : "not priced yet"}</span>
        </div>
        {p.data.cost || P.id === "open" ? (
          <>
            <div className="kunl">
              {rows.map((r) => (
                <div className="u" key={r.k}>
                  <b>{r.k}</b>
                  <span className={cx("v num", r.ok && "ok")}>{r.v}</span>
                  <small>{r.s}</small>
                </div>
              ))}
            </div>
            <p className="kfoot">{foot}</p>
          </>
        ) : (
          <p className="kfoot">This part has an analysis only, so there are no prices to compare. Checking it again prices every method.</p>
        )}
        {list.length > 1 ? (
          <>
            <div className="gh" style={{ marginTop: 6 }}>
              <span>{head}</span>
              <span>needs · short by</span>
            </div>
            <div role="radiogroup" aria-label={head}>
              {list.map((x, i) => {
                const on = i === mi;
                const need = x.need != null ? (x.unit === "deg" ? `${x.need}°` : x.unit === "mm" ? `${x.need.toFixed(1)} mm` : String(x.need)) : "—";
                return (
                  <button
                    key={x.code}
                    type="button"
                    role="radio"
                    className={cx("kmeth", on && "on")}
                    aria-checked={on}
                    tabIndex={on ? 0 : -1}
                    onClick={() => fx.setMethod(x.code)}
                    onKeyDown={roving(list, i, (j) => fx.setMethod(list[j].code))}
                  >
                    <span className="n">{x.name}</span>
                    <span className="nd num">{need}</span>
                    <span className={cx("q num", x.severity !== "error" && "w")}>{shortText(P, x)}</span>
                  </button>
                );
              })}
            </div>
          </>
        ) : null}
      </div>
      <div className="kact">
        <button className="btn ink kgo" type="button" onClick={go.run}>
          {go.label}
        </button>
        <button className="btn" type="button" onClick={alt.run}>
          {alt.label}
        </button>
        {up.el}
        <small>{canFixLine(P, fx.origin)}</small>
      </div>
    </>
  );
}
