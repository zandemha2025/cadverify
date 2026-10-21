"use client";

/**
 * F3 · Line by line: one method at one costed quantity, every cost driver with
 * its source and tag, the lines that sum to the unit cost, the confidence
 * band, the assumptions, and overrides that re-cost for real (POST
 * /validate/cost with the override; the engine tags touched lines Yours).
 * The Details sheet traces the same estimate: how it adds up, how sure it is, sources and
 * the session's overrides.
 */
import * as React from "react";
import { useSearchParams } from "next/navigation";
import type { CostDriver, CostOptions } from "@/lib/api";
import { canOverrideDriver, costOverrideError, driverOverrideKey, driverRateLabel, driverRateUnit, parseDriverRate } from "@/lib/cost-views";
import { deriveBreakeven } from "@/lib/breakeven";
import { Empty, cx } from "../ui";
import {
  EDITABLE_ASSUMPTIONS,
  assumptionKey,
  bandPct,
  costedQtys,
  decisionAt,
  driverValue,
  estimateFor,
  governance,
  lineRows,
  methodsAt,
  nearestQty,
  provOf,
  scenarioLabel,
  sumCheck,
} from "./derive";
import { addScenario, recost, useWb } from "./session";
import { WbHead, useNeedFile, useToast, useWbNav, wbHref } from "./chrome";
import { baseMeta, useShopName } from "./decision";
import { assumptionName, assumptionValue, driverName, money, qtyListText, qtyText } from "./words";
import type { TabProps } from "./workbench";

type Edit = { row: string; key: string; vname: string; label: string; unit: string; draft: string; err: string };

// The Details sheet's open state and tab are remembered for this tab's session.
const inspMem: { open: boolean; tab: "lin" | "gov" | "src" | "aud" } = { open: true, tab: "src" };
function remember(patch: Partial<typeof inspMem>) {
  Object.assign(inspMem, patch);
}

function Pencil() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M10.5 2.5 13.5 5.5 6 13H3v-3l7.5-7.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function Editor({ edit, setEdit, apply }: { edit: Edit; setEdit: (e: Edit | null) => void; apply: () => void }) {
  return (
    <>
      <div className="ed">
        <label className="field">
          {edit.label}, {edit.unit}
          <input
            type="text"
            inputMode="decimal"
            value={edit.draft}
            aria-invalid={!!edit.err}
            autoFocus
            onChange={(e) => setEdit({ ...edit, draft: e.target.value, err: "" })}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                apply();
              } else if (e.key === "Escape") {
                e.preventDefault();
                e.stopPropagation();
                setEdit(null);
              }
            }}
          />
        </label>
        <button className="ib ok" type="button" aria-label="Apply override" onClick={apply}>
          ✓
        </button>
        <button className="ib" type="button" aria-label="Cancel override" onClick={() => setEdit(null)}>
          ✕
        </button>
      </div>
      {edit.err ? (
        <p className="err" role="alert">
          {edit.err}
        </p>
      ) : null}
    </>
  );
}

export function GlassTab({ part, qty }: TabProps) {
  const s = useWb();
  const sp = useSearchParams();
  const nav = useWbNav();
  const toast = useToast();
  const { need } = useNeedFile();
  const shopName = useShopName();
  const report = s.report;
  const qs = React.useMemo(() => (report ? costedQtys(report) : []), [report]);
  const be = React.useMemo(() => (report ? deriveBreakeven(report) : null), [report]);
  const qParam = Number(sp.get("q"));
  const q = qs.includes(qParam) ? qParam : nearestQty(qs, qty ?? qs[0] ?? 1);
  const methods = React.useMemo(() => (report && q != null ? methodsAt(report, q) : []), [report, q]);
  const fromDecision = report && be && qty != null ? decisionAt(report, be, qty)?.curve.process : null;
  const procParam = sp.get("proc");
  const proc = (procParam && methods.find((m) => m.process === procParam)?.process) || (fromDecision && methods.find((m) => m.process === fromDecision)?.process) || methods[0]?.process || null;
  const est = report && proc && q != null ? estimateFor(report, proc, q) : null;
  const exact = est && est.quantity === q ? est : null;
  const baseEst = s.baseline && proc && q != null ? estimateFor(s.baseline, proc, q, exact?.material) : null;
  const ov = React.useMemo(() => s.opts.overrides ?? {}, [s.opts.overrides]);
  const ovKeys = Object.keys(ov);
  const recosting = s.cost.phase === "running";

  const [open, setOpen] = React.useState<string | null | undefined>(undefined);
  const [edit, setEdit] = React.useState<Edit | null>(null);
  const [insp, setInspState] = React.useState(inspMem.open);
  const setInsp = (v: boolean) => {
    remember({ open: v });
    setInspState(v);
  };
  const [itab, setItabState] = React.useState(inspMem.tab);
  const setItab = (t: typeof itab) => {
    remember({ tab: t });
    setItabState(t);
  };
  const railRef = React.useRef<HTMLButtonElement>(null);
  const collapseRef = React.useRef<HTMLButtonElement>(null);

  const pick = (p: string, qq: number) => {
    setEdit(null);
    nav(wbHref("glass", part, { proc: p, q: qq }), true);
  };

  const runWith = (next: CostOptions, done: string) => {
    need("re-cost with this change", async () => {
      const r = await recost(next);
      toast(r ? done : "Re-cost didn’t finish. The last good numbers stay.");
    });
  };

  const apply = () => {
    const e = edit;
    if (!e) return;
    const err = costOverrideError(e.vname, e.draft);
    if (err) {
      setEdit({ ...e, err });
      return;
    }
    const n = Number(e.draft);
    setEdit(null);
    if (e.key === "cavities") runWith({ ...s.opts, cavities: Math.round(n) }, `Mold cavities set to ${Math.round(n)}. Re-costed.`);
    else runWith({ ...s.opts, overrides: { ...ov, [e.key]: n } }, `Override ${e.key} = ${n}. Re-costed, tagged Yours.`);
  };

  const laborNow = ov.labor_rate ?? report?.assumptions.find((a) => a.name === "labor_rate")?.value ?? null;
  const startDriverEdit = (d: CostDriver) => {
    if (!report || !proc) return;
    const key = driverOverrideKey(d.name, proc, report.material_class);
    if (!key) return;
    const curV = ov[key] ?? (d.name === "labor_cost" || d.name === "setup_cost" ? laborNow : parseDriverRate(d));
    const unit = driverRateUnit(d.name) === "$/hr" ? "$/h" : driverRateUnit(d.name);
    const label = driverRateLabel(d.name);
    setOpen(d.name);
    setEdit({ row: `drv:${d.name}`, key, vname: key, label: label[0].toUpperCase() + label.slice(1), unit, draft: curV == null ? "" : String(curV), err: "" });
  };

  const meta = [...baseMeta(s), report ? `Quantities ${qtyListText(report.quantities)}` : ""];
  const head = <WbHead tab="glass" part={part} meta={meta} wide={!insp} />;

  if (!report || !exact || !proc || q == null) {
    return (
      <>
        {head}
        <div className="wb-main full">
          <div className="panel">
            <Empty
              title="No cost breakdown yet"
              actions={
                !report ? (
                  <button className="btn ink sm" type="button" onClick={() => need("cost it", () => void recost(s.opts))}>
                    Cost this part
                  </button>
                ) : undefined
              }
            >
              {report ? "No method is priced for this part, so there are no drivers to open." : "The lines open once the part is costed."}
            </Empty>
          </div>
        </div>
      </>
    );
  }

  const drivers = exact.drivers ?? [];
  const openRow = open === undefined ? drivers.find((d) => canOverrideDriver(d.name))?.name ?? null : open;
  const lines = lineRows(exact);
  const sum = sumCheck(exact);
  const conf = exact.confidence ?? null;
  const band = bandPct(exact);
  const lo = conf?.low_usd ?? (band != null ? exact.unit_cost_usd * (1 - band / 100) : null);
  const hi = conf?.high_usd ?? (band != null ? exact.unit_cost_usd * (1 + band / 100) : null);
  const delta = baseEst && ovKeys.length ? exact.unit_cost_usd - baseEst.unit_cost_usd : null;
  const gov = governance(drivers);
  const procLabel = methods.find((m) => m.process === proc)?.name ?? proc;
  const unit = money(exact.unit_cost_usd);
  const qLabel = qtyText(q);
  const geo = report.geometry;
  const filename = s.filename ?? report.filename;

  return (
    <>
      {head}
      <div className={cx("wb-main", !insp && "wide", recosting && "busy")}>
        <section className="panel pick" aria-label="Pick a method and quantity">
          <div className="prow">
            <span className="plab" id="gb-p">
              Process
            </span>
            <div className="pks" role="group" aria-label="Process">
              {methods.map((m) => (
                <button
                  key={m.process}
                  type="button"
                  className={cx("pk", m.process === proc && "on", !m.ready && "nr")}
                  aria-pressed={m.process === proc}
                  title={m.ready ? m.material : `${m.material} · needs a design change first`}
                  onClick={() => pick(m.process, q)}
                >
                  {m.name} <small className="vchg">{money(m.unit)}</small>
                </button>
              ))}
            </div>
          </div>
          <div className="prow">
            <span className="plab">Quantity</span>
            <span className="seg" role="group" aria-label="Quantity">
              {qs.map((x) => (
                <button key={x} type="button" className={cx(x === q && "on", "num")} aria-pressed={x === q} onClick={() => pick(proc, x)}>
                  {qtyText(x)}
                </button>
              ))}
            </span>
          </div>
        </section>
        <section className="panel" aria-labelledby="gb-h">
          <div className="ph">
            <h2 id="gb-h">
              {procLabel} at {qLabel}
            </h2>
            <span>
              {exact.material}
              {exact.dfm_ready ? "" : " · if redesigned"}
            </span>
          </div>
          <div className="big5" aria-live="polite">
            <b className="num vchg">{unit}</b>
            <span>each</span>
            {lo != null && hi != null ? (
              <span className="num">
                {money(lo)} to {money(hi)}
                {band != null ? ` · ±${band}%` : ""}
              </span>
            ) : null}
            <span className={cx("src", delta != null && Math.abs(delta) >= 0.005 ? "s-yours" : "s-typ")}>
              {delta == null || Math.abs(delta) < 0.005 ? (ovKeys.length ? "Same as without overrides" : "ScaleCAD’s estimate") : `${delta > 0 ? "+" : "−"}${money(Math.abs(delta))} vs without overrides`}
            </span>
          </div>
          <div className="gh">
            <span>Cost drivers</span>
            <span>Open one to see its source and edit its rate</span>
          </div>
          <div className="drv">
            {drivers.map((d) => {
              const p = provOf(d.provenance);
              const isOpen = openRow === d.name;
              const row = `drv:${d.name}`;
              const can = canOverrideDriver(d.name);
              const editing = edit?.row === row;
              return (
                <div key={d.name} className={cx("dr", isOpen && "open", p.kind === "typ" && "typ")}>
                  <button
                    type="button"
                    className="drh"
                    aria-expanded={isOpen}
                    onClick={() => {
                      setOpen(isOpen ? null : d.name);
                      if (editing) setEdit(null);
                    }}
                  >
                    <span className="nm">{driverName(d.name)}</span>
                    <span className={cx("src", p.cls)}>{p.label}</span>
                    <span className="bd num">{d.error_band_pct != null ? `±${d.error_band_pct}%` : ""}</span>
                    <b className="num vchg">{driverValue(d)}</b>
                    <span className="car" aria-hidden="true">
                      ▾
                    </span>
                  </button>
                  {isOpen ? (
                    <div className="drb">
                      <p className="srcx">{d.source}</p>
                      {can && !editing ? (
                        <div className="erow">
                          <button className="btn sm" type="button" onClick={() => startDriverEdit(d)}>
                            Override {driverRateLabel(d.name)}
                          </button>
                          <span className="hintx">Tags it Yours and re-costs</span>
                        </div>
                      ) : null}
                      {editing && edit ? <Editor edit={edit} setEdit={setEdit} apply={apply} /> : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </section>
        <div className="two">
          <div>
            <section className="panel" aria-labelledby="gb-sum">
              <div className="ph">
                <h2 id="gb-sum">Sum check</h2>
                <span>Lines add up to the unit cost</span>
              </div>
              <div className="sig">
                {lines.map((l) => (
                  <React.Fragment key={l.label}>
                    <span>{l.label}</span>
                    <b className="num vchg">{money(l.v)}</b>
                  </React.Fragment>
                ))}
                <span className="t">Sum of the lines</span>
                <b className={cx("t num", sum.coherent ? "okt" : "bdt")}>
                  {money(sum.sum)}
                  {sum.coherent ? " = unit cost ✓" : ` ≠ ${unit}`}
                </b>
              </div>
            </section>
            <section className="panel" aria-labelledby="gb-conf">
              <div className="ph">
                <h2 id="gb-conf">{conf ? `Confidence ${Math.round(conf.level * 100)}%` : "Range"}</h2>
                <span>{conf ? (conf.validated ? "Validated" : "Assumption-based, not validated") : "No confidence band on this estimate"}</span>
              </div>
              {lo != null && hi != null ? (
                <>
                  <div className="bandl num gbandl">
                    <span>{money(lo)}</span>
                    <span>{unit}</span>
                    <span>{money(hi)}</span>
                  </div>
                  <div className={cx("band gband", conf?.validated && "val")} role="img" aria-label={`Range ${money(lo)} to ${money(hi)}, point ${unit}`}>
                    <i />
                  </div>
                </>
              ) : null}
              <p style={{ margin: "6px 16px 14px", color: "var(--ink3)", fontSize: 12.5 }}>
                {conf?.basis ?? (band != null ? `±${band}% stated error band on the point estimate.` : "No band stated.")}
              </p>
            </section>
          </div>
          <section className="panel" aria-labelledby="gb-asm">
            <div className="ph">
              <h2 id="gb-asm">Assumptions</h2>
              <span>Pencil ones re-cost</span>
            </div>
            <div className="asm">
              {report.assumptions.map((a) => {
                const key = assumptionKey(a.name);
                const row = `asm:${a.name}`;
                const can = !!EDITABLE_ASSUMPTIONS[a.name];
                const isOv = key === "cavities" ? false : ov[key] != null;
                const p = provOf(isOv ? "USER" : a.provenance);
                const editing = edit?.row === row;
                return (
                  <div className="ar" key={a.name}>
                    <span title={a.source}>{assumptionName(a.name)}</span>
                    <b className="num">{assumptionValue(a.name, isOv ? ov[key] : a.value, a.unit)}</b>
                    <span className={cx("src", p.cls)}>{p.label}</span>
                    <span>
                      {can ? (
                        <button
                          type="button"
                          className="pen"
                          aria-label={`Override ${assumptionName(a.name)}`}
                          onClick={() =>
                            setEdit({
                              row,
                              key,
                              vname: a.name,
                              label: EDITABLE_ASSUMPTIONS[a.name][0],
                              unit: EDITABLE_ASSUMPTIONS[a.name][1],
                              draft: String(key === "cavities" ? s.opts.cavities ?? a.value : ov[key] ?? a.value),
                              err: "",
                            })
                          }
                        >
                          <Pencil />
                        </button>
                      ) : null}
                    </span>
                    {editing && edit ? (
                      <div className="are">
                        <Editor edit={edit} setEdit={setEdit} apply={apply} />
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </section>
        </div>
        <section className="panel" aria-label="Overrides and scenarios">
          <div className="foot">
            <div className="legend">
              <span className="src s-file">Your file</span>
              <span className="src s-shop">Shop</span>
              <span className="src s-yours">Yours</span>
              <span className="src s-typ">Typical</span>
              <span className="num">{ovKeys.length ? `${ovKeys.length} override${ovKeys.length === 1 ? "" : "s"} applied` : "No overrides"}</span>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {ovKeys.length ? (
                <button className="btn sm" type="button" disabled={recosting} onClick={() => runWith({ ...s.opts, overrides: {} }, "Overrides cleared. Engine numbers back.")}>
                  Reset overrides
                </button>
              ) : null}
              <button
                className="btn sm ink"
                type="button"
                disabled={recosting}
                onClick={() => {
                  addScenario({ label: scenarioLabel(shopName, ov), unit: exact.unit_cost_usd, qty: q, process: proc, opts: s.opts });
                  toast("Saved as a scenario for this session.");
                }}
              >
                Save as scenario
              </button>
            </div>
          </div>
          <div className="gh" style={{ paddingTop: 0 }}>
            <span>Scenarios this session</span>
            <span>{s.scenarios.length}</span>
          </div>
          {s.scenarios.length ? (
            <div className="scs">
              {s.scenarios.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  className="sc"
                  aria-label={`Recall ${x.label}`}
                  onClick={() =>
                    need("recall this scenario", async () => {
                      if (x.process && x.qty != null) nav(wbHref("glass", part, { proc: x.process, q: x.qty }), true);
                      const r = await recost(x.opts);
                      toast(r ? `Recalled ${x.label}. Re-costed.` : "Re-cost didn’t finish. The last good numbers stay.");
                    })
                  }
                >
                  <span>{x.label}</span>
                  <b className="num">
                    {money(x.unit)}
                    {x.qty != null ? ` at ${qtyText(x.qty)}` : ""}
                  </b>
                </button>
              ))}
            </div>
          ) : (
            <p style={{ margin: "0 16px 14px", color: "var(--ink3)", fontSize: 12.5 }}>None yet. Use a shop’s rates or override a rate, then save. Lost on refresh.</p>
          )}
        </section>
      </div>
      {insp ? (
        <aside className="sheet" aria-label="Details">
          <div className="top">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
              <div>
                <h2 className="stitle">Details</h2>
                <p className="smeta">
                  {procLabel} · {qLabel} parts · {unit} each
                </p>
              </div>
              <button
                ref={collapseRef}
                className="btn sm"
                type="button"
                aria-label="Hide details"
                onClick={() => {
                  setInsp(false);
                  window.setTimeout(() => railRef.current?.focus(), 0);
                }}
              >
                Hide
              </button>
            </div>
            <div style={{ marginTop: 12 }}>
              <span
                className="tabs4"
                role="tablist"
                aria-label="Details"
                onKeyDown={(e) => {
                  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
                  const order = ["lin", "gov", "src", "aud"] as const;
                  const i = order.indexOf(itab);
                  const next = order[(i + (e.key === "ArrowRight" ? 1 : -1) + order.length) % order.length];
                  setItab(next);
                  (e.currentTarget.querySelector(`[data-t="${next}"]`) as HTMLElement | null)?.focus();
                }}
              >
                {(
                  [
                    ["lin", "How it adds up"],
                    ["gov", "How sure"],
                    ["src", "Sources"],
                    ["aud", "Your changes"],
                  ] as const
                ).map(([k, label]) => (
                  <button
                    key={k}
                    data-t={k}
                    type="button"
                    role="tab"
                    id={`it-${k}`}
                    aria-controls="it-panel"
                    className={cx(itab === k && "on")}
                    aria-selected={itab === k}
                    tabIndex={itab === k ? 0 : -1}
                    onClick={() => setItab(k)}
                  >
                    {label}
                  </button>
                ))}
              </span>
            </div>
          </div>
          <div className="scroll" role="tabpanel" id="it-panel" aria-labelledby={`it-${itab}`}>
            {itab === "lin" ? (
              <div className="swap" key="lin">
                <div className="gh">
                  <span>How {unit} is built</span>
                  <span>
                    {procLabel} at {qLabel}
                  </span>
                </div>
                <ol className="lin">
                  <li className="lnn">
                    <i style={{ background: "#1F4FC4", borderColor: "#1F4FC4" }} />
                    <span>
                      <b>Your file</b>
                      <small>
                        {filename} · {geo.volume_cm3.toFixed(2)} cm³ · {geo.bbox_mm.map((v) => Math.round(v * 10) / 10).join(" × ")} mm
                      </small>
                    </span>
                    <span />
                  </li>
                  {drivers.map((d) => {
                    const p = provOf(d.provenance);
                    return (
                      <li className="lnn" key={d.name}>
                        <i style={{ background: p.kind === "typ" ? "#fff" : p.color, borderColor: p.color }} />
                        <span>
                          <b>{driverName(d.name)}</b>
                          <small>{p.label}</small>
                        </span>
                        <b className="num">{driverValue(d)}</b>
                      </li>
                    );
                  })}
                  <li className="lnn tot">
                    <i />
                    <span>
                      <b>Unit cost</b>
                      <small>Sum of the lines</small>
                    </span>
                    <b className="num">{unit}</b>
                  </li>
                </ol>
                <p style={{ margin: "8px 12px", color: "var(--ink3)", fontSize: 12.5 }}>Hollow: typical value. Filled: from your file, a shop or you.</p>
              </div>
            ) : null}
            {itab === "gov" ? (
              <div className="swap" key="gov">
                <div className="gnum">
                  <b className="num">{gov.grounded}</b>
                  <span>of {gov.total} cost inputs from your file, a shop or you</span>
                </div>
                <div className="gbar" role="img" aria-label={gov.aria}>
                  {gov.segs.map((g) => (
                    <i key={g.c} style={{ flex: `${g.n} 1 0`, background: g.c }} />
                  ))}
                </div>
                <div className="kv">
                  {gov.rows.map((r) => (
                    <React.Fragment key={r.label}>
                      <span>{r.label}</span>
                      <b className="num">{r.n}</b>
                    </React.Fragment>
                  ))}
                </div>
                <div className="gh">
                  <span>Data quality</span>
                  <span>{conf ? `${Math.round(conf.level * 100)}%` : "—"}</span>
                </div>
                <div className={cx("band", conf?.validated && "val")} style={{ margin: "6px 12px 4px" }} aria-hidden="true">
                  <i />
                </div>
                <p style={{ margin: "4px 12px 8px", color: "var(--ink2)", fontSize: 13 }}>
                  {conf ? `${conf.validated ? "Validated" : "Assumption-based, not validated"} · ${conf.n_samples} real job${conf.n_samples === 1 ? "" : "s"} behind it` : "No confidence band on this estimate"}
                </p>
                <div className="note">
                  <b>Your file</b>
                  <span>Your uploaded file and its analysis are kept for your organization.</span>
                </div>
              </div>
            ) : null}
            {itab === "src" ? (
              <div className="swap" key="src">
                <div className="gh">
                  <span>Why {unit}</span>
                  <span>Each line tagged and sourced</span>
                </div>
                {drivers.map((d) => {
                  const p = provOf(d.provenance);
                  return (
                    <div className="sx" key={d.name}>
                      <div>
                        <span>
                          {driverName(d.name)} <span className={cx("src", p.cls)}>{p.label}</span>
                        </span>
                        <b className="num">{driverValue(d)}</b>
                      </div>
                      <p className="srcx">{d.source}</p>
                      {canOverrideDriver(d.name) ? (
                        <button type="button" className="lk" onClick={() => startDriverEdit(d)}>
                          Override {driverRateLabel(d.name)}
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : null}
            {itab === "aud" ? (
              <div className="swap" key="aud">
                <div className="gh">
                  <span>Overrides this session</span>
                  <span>{ovKeys.length}</span>
                </div>
                {ovKeys.length ? (
                  <div className="sl2">
                    {ovKeys.map((k) => (
                      <div key={k}>
                        <span className="mono" style={{ fontSize: 12 }}>
                          {k}
                        </span>
                        <span>
                          <b className="num">{ov[k]}</b> <span className="src s-yours">Yours</span>
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p style={{ margin: "4px 12px", color: "var(--ink2)", fontSize: 13.5 }}>No overrides. Every number is ScaleCAD’s estimate.</p>
                )}
                <p style={{ margin: "10px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>PDF, JSON and CSV exports keep overrides with their tags.</p>
              </div>
            ) : null}
          </div>
        </aside>
      ) : (
        <button
          ref={railRef}
          className="irail"
          type="button"
          aria-label="Show details"
          onClick={() => {
            setInsp(true);
            window.setTimeout(() => collapseRef.current?.focus(), 0);
          }}
        >
          <span>Details</span>
        </button>
      )}
      <span className="sr" aria-live="polite">
        {recosting ? "Re-costing" : ""}
      </span>
    </>
  );
}
