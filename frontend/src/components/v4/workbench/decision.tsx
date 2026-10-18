"use client";

/**
 * F5 · Decision: the order-quantity slider (log 1 to a whole decade), cost
 * each by quantity on log scales, the pick at that quantity, the tooling
 * crossover, re-cost with new inputs, and the saved decision's exports,
 * supplier package and share link. Between costed quantities the numbers are
 * read off the app's breakeven curves and labelled "About".
 */
import * as React from "react";
import { useSearchParams } from "next/navigation";
import {
  createRfqPackage,
  downloadCostPdf,
  exportCostCsv,
  exportCostJson,
  shareCostDecision,
} from "@/lib/api";
import { deriveBreakeven } from "@/lib/breakeven";
import { fileExt } from "@/lib/cad-file";
import { parseCalibration } from "@/lib/cost-views";
import { R } from "../routes";
import { Empty, cx } from "../ui";
import {
  CHART_H,
  chartModel,
  costsAt,
  crossText,
  decadeTicks,
  decisionAt,
  formProblem,
  formToOptions,
  optionsToForm,
  posToQ,
  qToPos,
  redesignNote,
  sameForm,
  scaleMax,
  type FormDraft,
} from "./derive";
import { findPackage, markShared, recost, retryCost, setPackage, useShops, useWb, type WbState } from "./session";
import { Dialog, WbHead, WbLink, useLens, useNeedFile, useToast, wbHref } from "./chrome";
import { OptionsForm } from "./new-part";
import { Turntable } from "./turntable";
import { daysRange, materialName, money, qtyListText, qtyText } from "./words";
import type { TabProps } from "./workbench";

export function rateMeta(s: WbState, shopName: string | null): string {
  return shopName ? `Rates: ${shopName}` : "Rates: typical";
}

/** The bound shop's name: the option we sent, else the report's own calibration note. */
export function useShopName(): string | null {
  const s = useWb();
  const { shops } = useShops();
  const fromOpts = s.opts.shop ? shops.find((x) => x.id === s.opts.shop)?.name ?? null : null;
  const cal = s.report ? parseCalibration(s.report) : null;
  return fromOpts ?? cal?.shopName ?? null;
}

export function baseMeta(s: WbState): React.ReactNode[] {
  return [s.filename ?? s.report?.filename ?? "", s.report ? materialName(s.report.material_class) : "", s.env ?? ""];
}

function unitsHint(filename: string | null): { enabled: boolean; hint: string } {
  const ext = filename ? fileExt(filename) : null;
  if (!ext || ext === "stl") return { enabled: true, hint: "STL only. STEP and IGES carry their own units." };
  const kind = ext === "igs" || ext === "iges" ? "IGES" : "STEP";
  return { enabled: false, hint: `${kind} carries its own units. Applies to STL only.` };
}

function SavedCard({ filename }: { filename: string }) {
  const s = useWb();
  const toast = useToast();
  const [busy, setBusy] = React.useState<string | null>(null);
  const [pkgBusy, setPkgBusy] = React.useState(false);
  const [share, setShare] = React.useState<{ url: string; msg: string; bad: boolean; copied: boolean } | null>(null);
  const id = s.decision?.id ?? null;
  React.useEffect(() => {
    if (!id || s.pkgId) return;
    let live = true;
    findPackage(id).then((p) => live && p && setPackage(p), () => {});
    return () => {
      live = false;
    };
  }, [id, s.pkgId]);
  if (!id) {
    return (
      <div className="saved">
        <div className="row1">
          <span>Not saved to Records</span>
        </div>
        <p style={{ margin: 0, color: "var(--ink3)", fontSize: 12.5 }}>This run wasn’t kept, so it can’t be exported or shared. Re-cost to save it.</p>
      </div>
    );
  }
  const stem = filename.replace(/\.[^.]+$/, "");
  const run = async (kind: "pdf" | "json" | "csv") => {
    setBusy(kind);
    try {
      if (kind === "pdf") await downloadCostPdf(id, filename);
      if (kind === "json") await exportCostJson(id, filename);
      if (kind === "csv") await exportCostCsv(id, filename);
      toast(`Downloaded ${stem}-${kind === "pdf" ? "cost-report.pdf" : `cost.${kind}`}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "The download didn’t finish.");
    } finally {
      setBusy(null);
    }
  };
  const build = async () => {
    if (pkgBusy) return;
    setPkgBusy(true);
    try {
      const pkg = await createRfqPackage({ decisionIds: [id], title: `RFQ package - ${filename}` });
      setPackage(pkg.id);
      toast("Package built: the decision and its sources, without the CAD file.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "The package didn’t build.");
    } finally {
      setPkgBusy(false);
    }
  };
  const openShare = async () => {
    setBusy("share");
    try {
      const r = s.decision?.share_url ? { share_url: s.decision.share_url } : await shareCostDecision(id);
      const url = /^https?:/.test(r.share_url) ? r.share_url : `${window.location.origin}${r.share_url}`;
      markShared(r.share_url);
      setShare({ url, msg: "", bad: false, copied: false });
    } catch (e) {
      toast(e instanceof Error ? e.message : "The share link didn’t open.");
    } finally {
      setBusy(null);
    }
  };
  const copy = async () => {
    if (!share) return;
    try {
      await navigator.clipboard.writeText(share.url);
      setShare({ ...share, copied: true, msg: "Link copied.", bad: false });
    } catch {
      setShare({ ...share, copied: false, msg: "Couldn’t copy. Select the link and copy it.", bad: true });
    }
  };
  const label = s.report?.estimates.find((e) => e.confidence)?.confidence?.label;
  return (
    <div className="saved">
      <div className="row1">
        <span>
          <b>✓ Saved to Records</b> · decision {id.slice(0, 8)}
        </span>
        <a className="lk" href={R.record(id)}>
          Open
        </a>
      </div>
      <div className="acts">
        <button className="btn sm" type="button" onClick={() => void run("pdf")} disabled={!!busy}>
          {busy === "pdf" ? "…" : "PDF"}
        </button>
        <button className="btn sm" type="button" onClick={() => void run("json")} disabled={!!busy}>
          {busy === "json" ? "…" : "JSON"}
        </button>
        <button className="btn sm" type="button" onClick={() => void run("csv")} disabled={!!busy}>
          {busy === "csv" ? "…" : "CSV"}
        </button>
        {s.pkgId ? (
          <a className="btn sm" href={R.pkg(s.pkgId)}>
            Open package
          </a>
        ) : (
          <button className="btn sm" type="button" onClick={() => void build()} aria-disabled={pkgBusy}>
            {pkgBusy ? "Building…" : "Build package"}
          </button>
        )}
        <button className="btn sm ink" type="button" onClick={() => void openShare()} disabled={busy === "share"}>
          {busy === "share" ? "…" : "Share"}
        </button>
      </div>
      {s.pkgId ? <div className="pkg">Package built for this decision · building again opens it</div> : null}
      <p style={{ margin: 0, color: "var(--ink3)", fontSize: 12.5 }}>{label ? label[0].toUpperCase() + label.slice(1) + "." : "Assumption-based, not yet validated."}</p>
      {share ? (
        <Dialog labelledBy="sh-t" onClose={() => setShare(null)}>
          <div className="dh">
            <h2 id="sh-t">Share this decision</h2>
            <button className="btn sm" type="button" onClick={() => setShare(null)} aria-label="Close">
              ✕
            </button>
          </div>
          <div className="db">
            <p>Anyone with the link sees a read-only copy: sources, tags and range. Not a validated quote.</p>
            <label className="field">
              Public link
              <span className="lf">
                <input type="text" readOnly value={share.url} onFocus={(e) => e.currentTarget.select()} />
                <button className="btn ink" type="button" onClick={() => void copy()}>
                  {share.copied ? "Copied" : "Copy link"}
                </button>
              </span>
            </label>
            {share.msg ? (
              <span className={cx("cpy", share.bad && "bad")} role="status">
                {share.msg}
              </span>
            ) : null}
          </div>
          <div className="df">
            <button className="btn" type="button" onClick={() => setShare(null)}>
              Done
            </button>
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}

export function DecisionTab({ part, qty, setQty }: TabProps) {
  const s = useWb();
  const sp = useSearchParams();
  const lens = useLens();
  const toast = useToast();
  const { need, choose } = useNeedFile();
  const shopName = useShopName();
  const report = s.report;
  const be = React.useMemo(() => (report ? deriveBreakeven(report) : null), [report]);
  const max = scaleMax(be);
  const q = qty ?? 1;
  const at = report && be ? decisionAt(report, be, q) : null;
  const rows = be ? costsAt(be, q).slice(0, 5) : [];
  const [chartW, setChartW] = React.useState(880);
  const chartBox = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const el = chartBox.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setChartW(Math.max(300, Math.min(1200, Math.round(e.contentRect.width)))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [report]);
  const chart = be ? chartModel(be, q, at?.curve.process ?? null, max, chartW) : null;
  const red = report ? redesignNote(report) : null;
  const [trust, setTrust] = React.useState(sp.get("trust") === "1" || lens === "buyer");
  const [adj, setAdj] = React.useState(false);
  const base = React.useMemo(() => optionsToForm(s.opts), [s.opts]);
  const [form, setForm] = React.useState<FormDraft>(base);
  React.useEffect(() => setForm(base), [base]);
  const dirty = !sameForm(form, base);
  const bad = formProblem(form);
  const recosting = s.cost.phase === "running";
  const off = !!bad || !dirty || recosting;
  const units = unitsHint(s.filename);
  const filename = s.filename ?? report?.filename ?? "part";

  const doRecost = () => {
    if (off) return;
    const next = formToOptions(form, s.opts);
    need("re-cost with these inputs", async () => {
      const r = await recost(next);
      toast(r ? "Re-costed with the new inputs." : "Re-cost didn’t finish. The last good numbers stay.");
    });
  };

  const meta = [...baseMeta(s), report ? `Quantities ${qtyListText(report.quantities)}` : "", rateMeta(s, shopName)];
  const head = <WbHead tab="decision" part={part} meta={meta} />;
  const turntable = (
    <Turntable
      file={s.file}
      filename={s.filename}
      units={s.opts.units}
      label={`${filename}${report ? ` in ${materialName(report.material_class).toLowerCase()}` : ""}.`}
      onChooseFile={choose}
    />
  );

  if (!report) {
    return (
      <>
        {head}
        <div className="wb-main full">
          {s.cost.geom ? (
            <div className="errc" role="alert">
              <b>No cost: the mesh isn’t closed</b>
              <span>{s.cost.geom.reason ?? "The geometry isn’t watertight."} Repair the mesh, then cost it again.</span>
            </div>
          ) : s.cost.phase === "running" ? (
            <div className="panel">
              <Empty title="Costing">Pricing every method at {qtyListText(s.opts.qty.split(",").map(Number))}.</Empty>
            </div>
          ) : (
            <div className="panel">
              <Empty
                title="Not costed yet"
                actions={
                  <button className="btn ink sm" type="button" onClick={() => need("cost it", () => void recost(s.opts))}>
                    Cost this part
                  </button>
                }
              >
                {s.cost.error ?? "This part has a saved check but no saved cost decision."}
              </Empty>
            </div>
          )}
        </div>
      </>
    );
  }

  return (
    <>
      {head}
      <div className={cx("wb-main", recosting && "busy")}>
        <div className="wb-dtop">
          {turntable}
          <section className="panel qp" aria-labelledby="oq-h">
            <div className="ph">
              <h2 id="oq-h">Order quantity</h2>
              <span className="num">{crossText(report)}</span>
            </div>
            {be ? (
              <>
                <div className="qv">
                  <b className="num">{qtyText(q)}</b>
                  <span>parts</span>
                </div>
                <input
                  className="qs"
                  type="range"
                  min={0}
                  max={1000}
                  step={1}
                  value={qToPos(q, max)}
                  onChange={(e) => setQty(posToQ(Number(e.target.value), max))}
                  aria-label="Order quantity"
                  aria-valuetext={`${qtyText(q)} parts`}
                />
                <div className="qt num" aria-hidden="true">
                  {decadeTicks(max).map((t) => (
                    <span key={t}>{qtyText(t)}</span>
                  ))}
                </div>
                <div className="at" role="list" aria-label="Cost each at this quantity" aria-live="polite">
                  {rows.map((r) => (
                    <div key={r.process + r.material} className={cx(r.pick && "pick")} role="listitem">
                      <span>{r.name}</span>
                      <span className={cx("chip", r.chip)}>
                        <i />
                        {r.tag}
                      </span>
                      <b className="num">{money(r.unit)}</b>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="smeta">No method is priced for this part, so there’s nothing to slide across.</p>
            )}
          </section>
        </div>
        <section className="panel chart" aria-labelledby="ch-h">
          <div className="ph">
            <h2 id="ch-h">Cost each by quantity</h2>
            <span>Log scales · approximate between costed quantities</span>
          </div>
          {chart ? (
            <div ref={chartBox}>
              <svg viewBox={`0 0 ${chartW} ${CHART_H}`} role="img" aria-label={chart.aria}>
                <path d={chart.grid} stroke="rgba(20,24,31,.08)" strokeWidth="1" fill="none" />
                <path d={chart.others} stroke="#C3C8CF" strokeWidth="1.5" fill="none" strokeLinejoin="round" />
                <path d={chart.notReady} stroke="#D9A54A" strokeWidth="1.5" strokeDasharray="5 4" fill="none" strokeLinejoin="round" />
                <path d={chart.rec} stroke="#141414" strokeWidth="2.5" fill="none" strokeLinejoin="round" />
                <path d={chart.recDots} stroke="#141414" strokeWidth="7" strokeLinecap="round" fill="none" />
                <path d={chart.qLine} stroke="#FF5B1F" strokeWidth="1.5" fill="none" />
                <text x={chart.qx} y="14" fontSize="12" fontWeight="600" fill="#C2410C" textAnchor={chart.qAnchor}>
                  {qtyText(q)}
                </text>
                {chart.xTicks.map((t) => (
                  <text key={t.label} x={t.x} y={CHART_H - 8} fontSize="11" fill="#5F656E" textAnchor={t.anchor}>
                    {t.label}
                  </text>
                ))}
                {chart.yTicks.map((t) => (
                  <text key={t.label} x="4" y={t.y} fontSize="11" fill="#5F656E">
                    {t.label}
                  </text>
                ))}
              </svg>
              <div className="lgd">
                {at ? (
                  <span>
                    <i style={{ borderColor: "#141414" }} />
                    {at.name}, {at.ready ? "cheapest ready" : "cheapest, needs a design change"} at {qtyText(q)}
                  </span>
                ) : null}
                <span>
                  <i style={{ borderColor: "#C3C8CF" }} />
                  Other methods
                </span>
                {chart.notReadyNames.length ? (
                  <span>
                    <i style={{ borderColor: "#D9A54A", borderTopStyle: "dashed" }} />
                    {chart.notReadyNames.join(", ")} · if redesigned
                  </span>
                ) : null}
              </div>
            </div>
          ) : (
            <Empty title="No decision in this run">{report.notes?.find((n) => /no eligible|no environment-valid|excludes/i.test(n)) ?? "The engine priced no method it could recommend."}</Empty>
          )}
        </section>
      </div>
      <aside className="sheet" aria-label="The decision">
        <div className="top">
          <h2 className="stitle">{at ? `Make by ${at.name}` : "No make-now pick"}</h2>
          <p className="smeta">
            {at ? `${at.curve.material} · ${qtyText(q)} parts · ${at.ready ? "can make as drawn" : "needs a design change"}` : "No method clears the part’s conditions in this run"}
          </p>
          {at ? (
            <div className="figs" aria-live="polite">
              <div className="fig">
                <span>{at.exact ? "Cost each" : "About, each"}</span>
                <b className="num">{money(at.unit)}</b>
                <small className="num">{at.band != null ? `±${at.band}%` : "No stated range"}</small>
              </div>
              <div className="fig">
                <span>Lead time</span>
                <b className="num">{daysRange(at.leadLo, at.leadHi)}</b>
                <small>days{at.estimate && at.estimate.quantity !== q ? ` · at ${qtyText(at.estimate.quantity)}` : ""}</small>
              </div>
              <div className="fig">
                <span>Range</span>
                <b className="num" style={{ fontSize: 16 }}>
                  {at.lo != null && at.hi != null ? `${money(at.lo)}–${money(at.hi)}` : "—"}
                </b>
              </div>
            </div>
          ) : null}
        </div>
        <div className="scroll">
          {s.cost.phase === "error" || (recosting && s.cost.error) ? (
            <div className="errx" role="alert">
              <b>Re-cost didn’t finish</b>
              <span>The last good numbers stay above. Try again sends the same inputs.</span>
              {s.cost.error ? <span className="fh">{s.cost.error}</span> : null}
              <span>
                <button className="btn sm ink" type="button" onClick={() => need("re-cost", () => void retryCost())} disabled={recosting}>
                  {recosting ? "Re-costing…" : "Try again"}
                </button>
              </span>
            </div>
          ) : null}
          {report.unit_warnings?.length ? (
            <div className="red" role="note">
              <b>Check the units</b>
              {report.unit_warnings.map((w) => (
                <span key={w.code}>{w.message}</span>
              ))}
              <span>Set CAD source units in Adjust inputs, then re-cost.</span>
            </div>
          ) : null}
          {red ? (
            <div className="red" role="note">
              <b>{red.title}</b>
              <span>{red.text}</span>
              <WbLink className="lk" href={wbHref("routing", part)}>
                See routing and DFM
              </WbLink>
            </div>
          ) : null}
          <div style={{ padding: "8px 2px 0" }}>
            <WbLink className="dis" href={wbHref("glass", part)}>
              <span>
                Glass box <small>· every line, its source, its rate</small>
              </span>
              <span className="car" aria-hidden="true">
                ›
              </span>
            </WbLink>
          </div>
          <button type="button" className="dis" aria-expanded={trust} onClick={() => setTrust(!trust)}>
            <span>
              Why trust this <small>· method and range</small>
            </span>
            <span className="car" aria-hidden="true">
              ▾
            </span>
          </button>
          {trust && at ? (
            <div className="dbody">
              <p>
                Each line is a stated formula on your file’s measured geometry, with typical, shop or your rates.{" "}
                {at.estimate?.confidence?.validated
                  ? `The range is measured against ${at.estimate.confidence.n_samples} real jobs.`
                  : at.band != null
                    ? `The range is the stated ±${at.band}% assumption band. No real jobs behind it yet.`
                    : "No range is stated for this estimate."}
              </p>
              {at.lo != null && at.hi != null ? (
                <>
                  <div className="bandl num">
                    <span>{money(at.lo)}</span>
                    <span>{money(at.unit)}</span>
                    <span>{money(at.hi)}</span>
                  </div>
                  <div className={cx("band", at.estimate?.confidence?.validated && "val")} role="img" aria-label={`Range ${money(at.lo)} to ${money(at.hi)}`}>
                    <i />
                  </div>
                </>
              ) : null}
              <p>Uploaded CAD and analysis evidence are kept for your organization.</p>
            </div>
          ) : trust ? (
            <div className="dbody">
              <p>There’s no pick in this run, so there’s no range to show.</p>
            </div>
          ) : null}
          <button type="button" className="dis" aria-expanded={adj} onClick={() => setAdj(!adj)}>
            <span>
              Adjust inputs <small>· material, region, quantities</small>
            </span>
            <span className="car" aria-hidden="true">
              ▾
            </span>
          </button>
          {adj ? (
            <div className="dbody">
              <div className="frm">
                <OptionsForm form={form} setForm={setForm} unitsEnabled={units.enabled} unitsHint={units.hint} idp="dc" disabled={recosting} />
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button className={cx("btn ink sm", off && "off")} type="button" aria-disabled={off} onClick={doRecost}>
                  {recosting ? "Re-costing…" : "Re-cost"}
                </button>
                <span className="fh">{bad ? bad : dirty ? "Changes apply on re-cost" : "Showing these inputs"}</span>
              </div>
            </div>
          ) : null}
          <SavedCard filename={filename} />
        </div>
      </aside>
    </>
  );
}
