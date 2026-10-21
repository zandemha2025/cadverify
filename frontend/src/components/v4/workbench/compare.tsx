"use client";

/**
 * F7 · Compare: every priced method side by side, either at the first and
 * last costed quantity, or at one quantity under each rate set (typical and
 * each shop, one real engine run each). Each cell opens in the sheet with its
 * lines and tagged drivers, and can be edited line by line.
 */
import * as React from "react";
import { cx } from "../ui";
import {
  bandPct,
  changeText,
  compareByQty,
  compareByRates,
  costedQtys,
  crossoverSentence,
  driverValue,
  estimateFor,
  governance,
  lineRows,
  nearestQty,
  provOf,
  redesignNote,
  sumCheck,
  type CompareRow,
} from "./derive";
import { currentRunsSig, recost, runRateSets, useShops, useWb } from "./session";
import { WbHead, WbLink, useNeedFile, useToast, useWbNav, wbHref } from "./chrome";
import { baseMeta, rateMeta, useShopName } from "./decision";
import { driverName, methodName, money, qtyText } from "./words";
import type { TabProps } from "./workbench";

let modeMem: "qty" | "shop" = "qty";

type Pick = { process: string; qty: number; run: string };

export function CompareTab({ part, qty, setQty }: TabProps) {
  const s = useWb();
  const { shops } = useShops();
  const { need } = useNeedFile();
  const nav = useWbNav();
  const toast = useToast();
  const shopName = useShopName();
  const report = s.report;
  const [mode, setModeState] = React.useState<"qty" | "shop">(modeMem);
  const setMode = (m: "qty" | "shop") => {
    modeMem = m;
    setModeState(m);
    setPicked(null);
  };
  const [picked, setPicked] = React.useState<Pick | null>(null);
  const qs = React.useMemo(() => (report ? costedQtys(report) : []), [report]);
  const qc = nearestQty(qs, qty ?? qs[0] ?? 1);
  const byQty = React.useMemo(() => (report ? compareByQty(report) : { qa: null, qb: null, rows: [] as CompareRow[] }), [report]);
  const curRun = s.opts.shop ?? "base";
  const runIds = ["base", ...shops.map((x) => x.id)];
  const runReport = (id: string) => (id === curRun ? report : s.runsSig === currentRunsSig() ? s.runs[id]?.report ?? null : null);
  const runPhase = (id: string) => (id === curRun ? "done" : s.runsSig === currentRunsSig() ? s.runs[id]?.phase ?? "idle" : "idle");
  const runName = (id: string) => (id === "base" ? "Typical" : shops.find((x) => x.id === id)?.name ?? id);
  const byRates = React.useMemo(
    () => (qc != null ? compareByRates(runIds.map((id) => ({ id, report: runReport(id) })), qc) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [qc, s.runs, s.runsSig, report, shops, curRun],
  );
  const missing = runIds.filter((id) => runPhase(id) === "idle" || runPhase(id) === "error");
  const running = runIds.some((id) => runPhase(id) === "running");
  const startRuns = React.useCallback(() => {
    need("price it under each rate set", () => void runRateSets(shops));
  }, [need, shops]);

  const rows = mode === "qty" ? byQty.rows : byRates;
  const defaultPick: Pick | null = rows[0]
    ? mode === "qty"
      ? { process: rows[0].process, qty: byQty.qb ?? byQty.qa ?? 0, run: curRun }
      : { process: rows[0].process, qty: qc ?? 0, run: curRun }
    : null;
  const pick = picked && rows.some((r) => r.process === picked.process) ? picked : defaultPick;
  const isPick = (p: string, q: number, run: string) => !!pick && pick.process === p && pick.qty === q && pick.run === run;

  const cellRep = pick ? runReport(pick.run) : null;
  const est = cellRep && pick ? estimateFor(cellRep, pick.process, pick.qty) : null;
  const cellEst = est && pick && est.quantity === pick.qty ? est : null;
  const name = pick ? methodName(pick.process) : "";
  const rateLabel = pick ? (pick.run === "base" ? "typical rates" : runName(pick.run)) : "";
  const red = report ? redesignNote(report) : null;
  const priced = report ? new Set(report.estimates.filter((e) => !e.environment_excluded).map((e) => e.process)).size : 0;
  const meta = [
    ...baseMeta(s),
    report ? (
      <>
        <b>{priced}</b> methods priced
      </>
    ) : (
      ""
    ),
    rateMeta(s, shopName),
  ];

  const header = mode === "qty"
    ? [byQty.qa != null ? `${qtyText(byQty.qa)} part${byQty.qa === 1 ? "" : "s"}` : "", ...(byQty.qb != null && byQty.qb !== byQty.qa ? [`${qtyText(byQty.qb)} parts`, "Change"] : [])]
    : runIds.map(runName);

  return (
    <>
      <WbHead tab="compare" part={part} meta={meta} />
      <div className="wb-main">
        <section className="panel" style={{ padding: "12px 14px" }} aria-label="Compare by">
          <div className="ctl">
            <span className="lab" id="cmp-by">
              Compare by
            </span>
            <span className="seg" role="group" aria-labelledby="cmp-by">
              <button type="button" className={cx(mode === "qty" && "on")} aria-pressed={mode === "qty"} onClick={() => setMode("qty")}>
                Quantity
              </button>
              <button type="button" className={cx(mode === "shop" && "on")} aria-pressed={mode === "shop"} onClick={() => setMode("shop")}>
                Rates
              </button>
            </span>
            <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{mode === "qty" ? "First and last costed quantity" : `Each rate set is its own engine run, at ${qc != null ? qtyText(qc) : "—"}`}
              {mode === "shop" && running ? " · pricing…" : ""}</span>
          </div>
        </section>
        <section className="panel" aria-labelledby="cmp-h">
          <div className="ph">
            <h2 id="cmp-h">
              {mode === "qty"
                ? byQty.qa != null && byQty.qb != null && byQty.qa !== byQty.qb
                  ? `Each method at ${qtyText(byQty.qa)} and ${qtyText(byQty.qb)}`
                  : `Each method at ${byQty.qa != null ? qtyText(byQty.qa) : "—"}`
                : `Each method at ${qc != null ? qtyText(qc) : "—"}, ${runIds.length} rate sets`}
            </h2>
            <span>{mode === "qty" ? "Pick a cell to open it" : "Bundled sample shops · pick a cell to open it"}</span>
          </div>
          {mode === "shop" && missing.length && !running && !runIds.some((id) => runPhase(id) === "error") ? (
            <div className="empty" style={{ padding: "22px 24px" }}>
              <b>Each rate set is a fresh engine run</b>
              <span>
                {missing.length === 1 ? "1 more run" : `${missing.length} more runs`}, one after another, each saved to Cost records.{s.file ? "" : " Needs the CAD file."}
              </span>
              <button className="btn sm ink" type="button" onClick={startRuns}>
                Price with each rate set
              </button>
            </div>
          ) : null}
          {mode === "shop" && runIds.some((id) => runPhase(id) === "error") && !running ? (
            <div className="errx" role="alert">
              <b>A rate set didn’t finish</b>
              <span>{runIds.filter((id) => runPhase(id) === "error").map(runName).join(", ")}: no numbers yet.</span>
              <span>
                <button className="btn sm ink" type="button" onClick={startRuns}>
                  Try again
                </button>
              </span>
            </div>
          ) : null}
          <div className="ctw">
            <table className="ct">
              <thead>
                <tr>
                  <th style={{ width: "36%" }}>Method</th>
                  {header.map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody aria-live="polite">
                {rows.map((r) => (
                  <tr key={r.process}>
                    <td className="nm">
                      <b>{r.name}</b>
                      <small>{r.sub}</small>
                    </td>
                    {r.cells.map((c) => {
                      const on = isPick(c.process, c.qty, mode === "qty" ? curRun : c.run);
                      const run = mode === "qty" ? curRun : c.run;
                      const busy = mode === "shop" && runPhase(c.run) === "running";
                      return (
                        <td key={`${c.run}-${c.qty}`}>
                          <button
                            type="button"
                            className={cx("cell", on && "on")}
                            aria-pressed={on}
                            disabled={c.unit == null}
                            aria-label={`Open ${r.name} at ${qtyText(c.qty)}${mode === "shop" ? `, ${runName(c.run)}` : ""} in the sheet`}
                            onClick={() => setPicked({ process: c.process, qty: c.qty, run })}
                          >
                            <b className="num">{busy ? "…" : c.unit != null ? money(c.unit) : "—"}</b>
                            <small className="num">{mode === "qty" ? (c.band != null ? `±${c.band}%` : "") : c.unit != null ? runName(c.run).split(" ")[0] : ""}</small>
                            {c.unit != null ? (
                              <span className="ar2" aria-hidden="true">
                                ›
                              </span>
                            ) : null}
                          </button>
                        </td>
                      );
                    })}
                    {mode === "qty" && byQty.qb !== byQty.qa ? (
                      <td className={cx("d num", changeText(r.change).cls)}>{changeText(r.change).text}</td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        {report ? (
          <section className="panel" aria-labelledby="lev-h">
            <div className="ph">
              <h2 id="lev-h">Negotiation lever</h2>
              <span>From the engine’s decision</span>
            </div>
            <div className="lev">
              <span>{crossoverSentence(report) || "The engine made no pick in this run."}</span>
              {red ? (
                <span>
                  <b>{red.title}.</b> Its prices assume a redesigned part.
                </span>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
      <aside className="sheet" aria-label="This cell, line by line">
        <div className="top">
          <h2 className="stitle">{pick ? `${name} at ${qtyText(pick.qty)}` : "Pick a cell"}</h2>
          <p className="smeta">
            {cellEst ? `${cellEst.material} · ${rateLabel} · ${cellEst.dfm_ready ? "can make as drawn" : "if redesigned"}` : pick ? `${rateLabel} · not priced yet` : "Each cell opens here"}
          </p>
          {cellEst ? (
            <div className="figs" aria-live="polite">
              <div className="fig">
                <span>Cost each</span>
                <b className="num">{money(cellEst.unit_cost_usd)}</b>
                <small className="num">{bandPct(cellEst) != null ? `±${bandPct(cellEst)}%` : ""}</small>
              </div>
              <div className="fig">
                <span>From your data</span>
                <b className="num">
                  {governance(cellEst.drivers).grounded} of {cellEst.drivers.length}
                </b>
                <small>drivers</small>
              </div>
              <div className="fig">
                <span>DFM</span>
                <b className={cx("num", cellEst.dfm_ready ? "ok" : "warn")} style={{ fontSize: 16 }}>
                  {cellEst.dfm_ready ? "Ready" : "Redesign"}
                </b>
              </div>
            </div>
          ) : null}
        </div>
        <div className="scroll">
          {cellEst ? (
            <>
              <div className="gh">
                <span>Lines</span>
                <span>Sum = cost each</span>
              </div>
              <div className="sig">
                {lineRows(cellEst).map((l) => (
                  <React.Fragment key={l.label}>
                    <span>{l.label}</span>
                    <b className="num">{money(l.v)}</b>
                  </React.Fragment>
                ))}
                <span className="t">Sum of the lines</span>
                <b className={cx("t num", sumCheck(cellEst).coherent ? "" : "bdt")}>{money(sumCheck(cellEst).sum)}</b>
              </div>
              <div className="gh">
                <span>Drivers</span>
                <span>Tagged</span>
              </div>
              {cellEst.drivers.map((d) => {
                const p = provOf(d.provenance);
                return (
                  <div className="dl2" key={d.name}>
                    <span>{driverName(d.name)}</span>
                    <span className={cx("src", p.cls)}>{p.label}</span>
                    <b className="num">{driverValue(d)}</b>
                  </div>
                );
              })}
              <div style={{ padding: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {pick && pick.run === curRun ? (
                  <WbLink className="btn ink sm" href={wbHref("glass", part, { proc: pick.process, q: pick.qty })}>
                    Edit line by line
                  </WbLink>
                ) : pick ? (
                  <button
                    className="btn ink sm"
                    type="button"
                    onClick={() =>
                      need(`bind ${runName(pick.run)} and edit it`, async () => {
                        const r = await recost({ ...s.opts, shop: pick.run === "base" ? null : pick.run });
                        if (r) nav(wbHref("glass", part, { proc: pick.process, q: pick.qty }));
                        else toast("Re-cost didn’t finish. The last good numbers stay.");
                      })
                    }
                  >
                    Edit line by line
                  </button>
                ) : null}
                {pick ? (
                  <WbLink className="btn sm" href={wbHref("decision", part, { q: pick.qty })} onNavigate={() => setQty(pick.qty)}>
                    See the curve
                  </WbLink>
                ) : null}
              </div>
              <p style={{ margin: "0 12px", color: "var(--ink3)", fontSize: 12.5 }}>
                Opened for the cell you picked: {name} at {pick ? qtyText(pick.qty) : ""}
                {pick && pick.run !== curRun ? `, ${runName(pick.run)}` : ""}.
              </p>
            </>
          ) : (
            <p className="smeta" style={{ margin: "8px 12px" }}>
              {running ? "Pricing each rate set…" : "Pick a priced cell to see its lines and drivers."}
            </p>
          )}
        </div>
      </aside>
    </>
  );
}
