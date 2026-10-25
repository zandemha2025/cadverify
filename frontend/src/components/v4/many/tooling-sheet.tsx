"use client";

/**
 * The tooling sheet (board M2, replaces today's acquisition modal): for the part
 * you clicked, from that part's own saved check, make-now against the tooled
 * route across quantity, where tooling pays back, and the org's capability
 * changes. A sheet, not a modal: Esc, "Back to Make or buy" and "Not now" return to
 * Triage, and focus goes back to the row's Tooling button.
 */
import * as React from "react";
import { Empty, Fig, Figs, Sheet, cx, usd } from "../ui";
import { errorText } from "./common";
import { fetchCostDecision, type SavedDecision } from "./many-api";
import { procName, type MakeRow } from "./makeability";
import { capCard, chartOf, nearestCosted, posToQty, qtyToPos, toolingView, type RankEntry } from "./tooling";
import type { Machine } from "./makeability";

export function ToolingSheet({
  row,
  machines,
  ranking,
  onBack,
  onSeeCapability,
}: {
  row: MakeRow;
  machines: Machine[] | null;
  ranking: RankEntry[] | null;
  onBack: () => void;
  onSeeCapability: () => void;
}) {
  const id = row.cost_decision?.id ?? null;
  const [saved, setSaved] = React.useState<SavedDecision | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [retry, setRetry] = React.useState(0);
  const [pos, setPos] = React.useState<number | null>(null);
  const backRef = React.useRef<HTMLButtonElement>(null);

  React.useEffect(() => {
    backRef.current?.focus();
  }, [row.part_key]);

  React.useEffect(() => {
    if (!id) return;
    let live = true;
    setSaved(null);
    setErr(null);
    setPos(null);
    fetchCostDecision(id).then(
      (d) => live && setSaved(d),
      (e) => live && setErr(errorText(e, "This part’s check didn’t load.")),
    );
    return () => {
      live = false;
    };
  }, [id, retry]);

  // Esc returns to Triage from anywhere on the page while the sheet is open (not while a dialog or the palette is up).
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector(".ob [aria-modal='true']")) return;
      onBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack]);

  const v = toolingView(saved?.result);
  const name = row.filename ?? saved?.filename ?? "This part";
  const metaBits = [name];
  if (v?.materialClass) metaBits.push(`${v.materialClass} check`);
  if (v?.makeProc) metaBits.push(`make now: ${procName(v.makeProc).toLowerCase()}${v.makeMat ? `, ${v.makeMat}` : ""}`);

  const startQ = v ? (v.crossover ?? v.quantities[v.quantities.length - 1] ?? 10) : 10;
  const p = pos ?? qtyToPos(startQ);
  const qv = posToQty(p);
  const near = v ? nearestCosted(v.quantities, qv) : null;
  const mu = v && near != null ? v.make.get(near) ?? null : null;
  const tu = v && near != null ? v.tool.get(near) ?? null : null;
  const mkWins = mu != null && tu != null && mu <= tu;
  const tlWins = mu != null && tu != null && tu < mu;
  const chart = v?.toolProc ? chartOf(v, qv) : null;
  const toolName = v?.toolProc ? procName(v.toolProc).toLowerCase() : "";
  const toolLabel = v?.toolProc ? `${toolName}${v.ready ? "" : v.draftDeg != null ? `, after adding ${v.draftDeg}° draft` : ", after redesign"}` : "";

  return (
    <Sheet label="Tooling alternative">
        <div className="top swap" key={row.part_key}>
          <button ref={backRef} className="btn sm" type="button" onClick={onBack} style={{ marginBottom: 10 }}>
            ‹ Back to Make or buy
          </button>
          <h2 className="stitle">{v?.toolProc ? `Tooling: ${toolName}` : saved ? "No tooling alternative" : "Tooling alternative"}</h2>
          <p className="smeta">{metaBits.join(" · ")}</p>
          {v?.toolProc ? (
            <Figs>
              <Fig k="Pays off near" v={v.crossover != null ? Math.round(v.crossover).toLocaleString("en-US") : "No crossover"} sub={v.crossover != null ? "parts" : "in the costed quantities"} />
              <Fig k="Tooling" v={v.ready ? "Ready as drawn" : "Needs redesign"} tone={v.ready ? "ok" : "warn"} />
            </Figs>
          ) : null}
        </div>
        <div className="scroll acq">
          {!id ? (
            <Empty title="No saved check for this part">Open the part and check it to compare tooling.</Empty>
          ) : err ? (
            <div className="errx" role="alert" style={{ margin: "8px 12px" }}>
              <b>This part’s check didn’t load</b>
              <span>{err}</span>
              <span>
                <button className="btn sm ink" type="button" onClick={() => setRetry((n) => n + 1)}>
                  Try again
                </button>
              </span>
            </div>
          ) : !saved ? (
            <div role="status" style={{ padding: "16px 12px", color: "var(--ink3)", fontSize: 13 }}>
              Loading this part’s check…
            </div>
          ) : !v || !v.toolProc ? (
            <Empty
              title="No tooling alternative"
              actions={
                <button className="btn sm" type="button" onClick={onBack}>
                  Back to Make or buy
                </button>
              }
            >
              {v?.makeProc ? `Make now by ${procName(v.makeProc).toLowerCase()}. ` : ""}This part’s check found no tooled route to compare.
            </Empty>
          ) : (
            <div className="swap" key={row.part_key}>
              <div className="gh">
                <span>Quantity</span>
                <span className="num">
                  {qv.toLocaleString("en-US")}
                  {near != null ? ` · nearest costed ${near.toLocaleString("en-US")}` : ""}
                </span>
              </div>
              <input
                className="qs"
                type="range"
                min={0}
                max={1000}
                step={1}
                value={p}
                onChange={(e) => setPos(Number(e.target.value))}
                aria-label="Quantity"
                aria-valuetext={`${qv.toLocaleString("en-US")} parts${near != null ? `, nearest costed ${near.toLocaleString("en-US")}` : ""}`}
              />
              <div className="qt num" aria-hidden="true">
                <span>1</span>
                <span>10</span>
                <span>100</span>
                <span>1,000</span>
                <span>10,000</span>
              </div>
              <div className="rc" aria-live="polite">
                <div className={cx(mkWins && "win")}>
                  <span>Make now · {procName(v.makeProc).toLowerCase()}</span>
                  <b className="num">{mu != null ? usd(mu) : "Not costed"}</b>
                  <em>{mkWins ? "Cheaper here" : ""}</em>
                </div>
                <div className={cx(tlWins && "win")}>
                  <span>Tooling · {toolLabel}</span>
                  <b className="num">{tu != null ? usd(tu) : "Not costed"}</b>
                  <em>{tlWins ? "Cheaper here" : ""}</em>
                </div>
              </div>
              <p style={{ margin: "2px 12px 0", color: "var(--ink3)", fontSize: 12 }}>
                Each, at the nearest costed quantity{v.quantities.length ? ` (${v.quantities.map((q) => q.toLocaleString("en-US")).join(", ")})` : ""}. Model estimate, not a quote.
              </p>
              {chart ? (
                <svg
                  width="100%"
                  viewBox="0 0 420 150"
                  role="img"
                  aria-label={`Make now and tooling cost each at the costed quantities${v.crossover != null ? `; tooling pays off near ${Math.round(v.crossover).toLocaleString("en-US")}` : "; no crossover"}.`}
                  style={{ display: "block", margin: "8px 0 0" }}
                >
                  <path d={chart.grid} stroke="rgba(20,24,31,.08)" fill="none" />
                  {chart.makePath ? <path d={chart.makePath} stroke="#146C43" strokeWidth="2" fill="none" /> : null}
                  {chart.toolPath ? <path d={chart.toolPath} stroke="#B97F0C" strokeWidth="2" strokeDasharray="5 4" fill="none" /> : null}
                  {chart.makeDots.map(([x, y]) => (
                    <circle key={`m${x}`} cx={x} cy={y} r="2.6" fill="#146C43" />
                  ))}
                  {chart.toolDots.map(([x, y]) => (
                    <circle key={`t${x}`} cx={x} cy={y} r="2.6" fill="#B97F0C" />
                  ))}
                  {chart.xLine ? <path d={chart.xLine} stroke="#141414" strokeWidth="1" strokeDasharray="2 3" fill="none" /> : null}
                  <path d={chart.qLine} stroke="#FF5B1F" strokeWidth="1.5" fill="none" />
                  <text x="14" y="146" fontSize="10" fill="#5F656E">
                    1
                  </text>
                  <text x="406" y="146" fontSize="10" fill="#5F656E" textAnchor="end">
                    10,000
                  </text>
                </svg>
              ) : null}
              <div className="legend" aria-hidden="true">
                <span style={{ color: "#146C43" }}>
                  <i />
                  <span style={{ color: "var(--ink3)" }}>Make now</span>
                </span>
                <span style={{ color: "#B97F0C" }}>
                  <i className="d" />
                  <span style={{ color: "var(--ink3)" }}>Tooling, incl. tool cost</span>
                </span>
                <span style={{ color: "#FF5B1F" }}>
                  <i />
                  <span style={{ color: "var(--ink3)" }}>Quantity</span>
                </span>
              </div>
              <div className="gh">
                <span>Capital and payback, org-wide</span>
                <span />
              </div>
              <p style={{ margin: "0 12px 6px", color: "var(--ink2)", fontSize: 13 }}>
                {v.crossover != null
                  ? `Tooling pays back near ${Math.round(v.crossover).toLocaleString("en-US")} parts. No machine or mold price in ScaleCAD.`
                  : "No payback point in the costed quantities. No machine or mold price in ScaleCAD."}
              </p>
            </div>
          )}
          <div className="gh">
            <span>Capability changes</span>
            <span>Parts to review</span>
          </div>
          {ranking && ranking.length ? (
            ranking.map((e, i) => (
              <div className="rk" key={`${e.acquisition.process}:${e.acquisition.gate ?? ""}`}>
                <i>{i + 1}</i>
                <span>{capCard(e, machines).title}</span>
                <b className="num">{e.parts_unlocked}</b>
              </div>
            ))
          ) : (
            <p style={{ margin: "0 12px 6px", color: "var(--ink3)", fontSize: 13 }}>{ranking ? "None: no part is blocked by one missing capability." : "Loading"}</p>
          )}
          <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap" }}>
            <button className="btn sm ink" type="button" onClick={onSeeCapability}>
              See capability changes
            </button>
            <button className="btn sm" type="button" onClick={onBack}>
              Not now
            </button>
          </div>
        </div>
    </Sheet>
  );
}
