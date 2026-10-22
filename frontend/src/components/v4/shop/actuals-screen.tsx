"use client";

/**
 * Actual costs (board S2, and the validation moment): bring your shop's real
 * numbers in the way you have them (a CSV or Excel export, one job at a time),
 * see how close ScaleCAD came on each part and overall ("checked against your
 * real numbers", every plan), and calibrate ScaleCAD with them (applying it is
 * part of the pilot; who applied it and when is recorded, and it can be
 * undone). Stand-in and test rows never count.
 */
import * as React from "react";
import Link from "next/link";
import { listMachines, type OwnedMachine } from "@/lib/verify/machine-api";
import { groundTruthTemplate, listGroundTruth } from "@/lib/verify/calibration-api";
import { R, TABS } from "../routes";
import { Content, Loading, PageHead, Panel, Sheet, cx, usd } from "../ui";
import { AccuracyPanel } from "../validation/accuracy-panel";
import { CalibrationPanel } from "../validation/calibration-panel";
import { ImportDialog } from "../validation/import-dialog";
import type { ImportResult } from "../validation/api";
import { basisWord, hoursWord } from "../validation/words";
import { Banner, ShopWorld, usePartRecords } from "./common";
import { downloadText, logJob, ShopApiError, type RecordDetail } from "./shop-api";
import { PROCS, longDate, procName } from "./shop-derive";
import { headlineEstimate, headlineQty } from "./rates-derive";
import {
  JOB_KINDS,
  MATERIAL_CLASSES,
  MIN_HELD_OUT,
  MIN_REAL_RECORDS,
  bandPos,
  countRecords,
  parseJob,
  rangeOf,
  type GtRecord,
  type JobErrors,
  type JobForm,
} from "./actuals-derive";

type BannerState =
  | { kind: "imported"; r: ImportResult }
  | { kind: "template" }
  | { kind: "templateError"; msg: string }
  | null;

const BLANK: JobForm = { part: "", process: "", quantity: "10", cost: "", material: "aluminum", kind: "actual", source: "", date: "", machineH: "", setupH: "", laborH: "", inspectH: "" };

const lowerFirst = (t: string) => t.charAt(0).toLowerCase() + t.slice(1);

const REQUIRED_COLUMNS = 4; // part_id, process, quantity, actual_unit_cost_usd (groundtruth_service.CSV_REQUIRED_COLUMNS)

export function ActualsScreen() {
  const [records, setRecords] = React.useState<GtRecord[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [machines, setMachines] = React.useState<OwnedMachine[]>([]);
  const [banner, setBanner] = React.useState<BannerState>(null);
  const [columns, setColumns] = React.useState<string[] | null>(null);
  const [file, setFile] = React.useState<File | null>(null);
  const [tick, setTick] = React.useState(0);
  const [ask, setAsk] = React.useState(0);
  const fileRef = React.useRef<HTMLInputElement>(null);
  // One request per load: every part's newest record, the newest 12 with details.
  const recs = usePartRecords(12);
  const details: RecordDetail[] | null = recs.data?.details ?? null;

  const load = React.useCallback(async (): Promise<GtRecord[] | null> => {
    setLoadError(null);
    try {
      const page = await listGroundTruth();
      setRecords(page.records as unknown as GtRecord[]);
      return page.records as unknown as GtRecord[];
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Couldn't load your actuals.");
      return null;
    }
  }, []);

  React.useEffect(() => {
    void load();
    listMachines().then(
      (p) => setMachines(p.machines),
      () => setMachines([])
    );
    groundTruthTemplate().then(
      (t) => setColumns(t.split(/\r?\n/)[0].split(",").map((c) => c.trim()).filter(Boolean)),
      () => setColumns([])
    );
  }, [load]);

  const { real, standIn } = countRecords(records);
  const matchedParts = new Set((records ?? []).filter((r) => !r.stand_in && r.evidence_sha256).map((r) => r.evidence_sha256)).size;

  const onTemplate = async () => {
    try {
      downloadText(await groundTruthTemplate(), "ground-truth-template.csv");
      setBanner({ kind: "template" });
    } catch (e) {
      setBanner({ kind: "templateError", msg: e instanceof Error ? e.message : "Couldn't download the template." });
    }
  };

  const changed = async () => {
    await load();
    setTick((t) => t + 1);
  };

  return (
    <ShopWorld label="Actual costs">
      <PageHead
        title="Actual costs"
        actions={
          <>
            <button className="btn sm" type="button" onClick={() => fileRef.current?.click()}>
              Import actuals
            </button>
            <button className="btn sm" type="button" onClick={onTemplate}>
              Download template<span className="new">New</span>
            </button>
            <button className="btn ink sm" type="button" onClick={() => setAsk((n) => n + 1)}>
              Recalibrate <span className="pilot">Pilot</span>
            </button>
          </>
        }
        meta={[
          <>
            Parts with actuals <b className="num">{records ? matchedParts : "…"}</b>
          </>,
          <>
            Actuals <b className="num">{records ? real : "…"}</b>
          </>,
          <>
            Test <b className="num">{records ? standIn : "…"}</b>
          </>,
          <>
            Fair picture <b>{MIN_REAL_RECORDS} parts</b>
          </>,
        ]}
        tabs={TABS.shop}
        tabsLabel="Your shop"
      />
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        aria-label="Choose a CSV or Excel file of your actuals"
        tabIndex={-1}
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) {
            setBanner(null);
            setFile(f);
          }
        }}
      />
      <Content>
        {banner?.kind === "imported" ? (
          <Banner tone={banner.r.not_imported.length ? "warn" : "ok"} onDismiss={() => setBanner(null)}>
            <b>
              {banner.r.imported} {banner.r.imported === 1 ? "actual" : "actuals"} imported for {banner.r.parts} {banner.r.parts === 1 ? "part" : "parts"}
              {banner.r.test ? ` (${banner.r.test} test)` : ""}
              {banner.r.not_imported.length ? ` · ${banner.r.not_imported.length} not imported` : ""}
            </b>
            {banner.r.not_imported.length ? (
              <ul>
                {banner.r.not_imported.slice(0, 8).map((er, i) => (
                  <li key={i}>
                    {er.line ? `Row ${er.line}: ` : ""}
                    {er.reason}
                  </li>
                ))}
                {banner.r.not_imported.length > 8 ? <li>{banner.r.not_imported.length - 8} more.</li> : null}
              </ul>
            ) : null}
          </Banner>
        ) : null}
        {banner?.kind === "template" ? (
          <Banner tone="ok" onDismiss={() => setBanner(null)}>
            <b>ground-truth-template.csv downloaded.</b> Header row and one example line. Any export works with Import actuals: you pick the columns.
          </Banner>
        ) : null}
        {banner?.kind === "templateError" ? (
          <Banner tone="bad" alert onDismiss={() => setBanner(null)}>
            <b>Couldn&apos;t download the template.</b> {banner.msg}
          </Banner>
        ) : null}
        {loadError ? (
          <Banner
            tone="bad"
            alert
            actions={
              <button className="btn sm" type="button" onClick={() => void load()}>
                Retry
              </button>
            }
          >
            <b>Couldn&apos;t load your actuals.</b> {loadError}
          </Banner>
        ) : null}

        <AccuracyPanel tick={tick} onImport={() => fileRef.current?.click()} />

        <CalibrationPanel ask={ask} onChanged={() => setTick((t) => t + 1)} />

        <LogJob
          parts={recs.data?.parts ?? []}
          machines={machines}
          onSaved={async () => {
            const r = await load();
            setTick((t) => t + 1);
            return countRecords(r).real;
          }}
        />

        <LoggedJobs records={records} error={loadError} />

        <Panel title="CSV columns" note="For the template; Import actuals takes any export">
          {columns == null ? (
            <Loading rows={1} label="Loading the CSV columns" />
          ) : columns.length === 0 ? (
            <p className="fh" style={{ margin: "0 16px 12px" }}>
              Couldn&apos;t read the template. Download it to see the columns.
            </p>
          ) : (
            <div className="cols" aria-label={`${columns.length} columns, the first ${REQUIRED_COLUMNS} required`}>
              {columns.map((c, i) => (
                <code key={c} className={cx(i >= REQUIRED_COLUMNS && "opt")} title={i < REQUIRED_COLUMNS ? "Required" : "Optional"}>
                  {c}
                </code>
              ))}
            </div>
          )}
          <p className="fh" style={{ margin: 0, padding: "0 16px 14px" }}>
            source_type synthetic, seed, demo or stand_in imports as a stand-in and never counts.
          </p>
        </Panel>
      </Content>
      <Sheet label="Range for one part" style={{ bottom: 20 }}>
        <PartRangeSheet details={details} real={real} standIn={standIn} loadError={recs.error} />
      </Sheet>
      {file ? (
        <ImportDialog
          file={file}
          onClose={() => setFile(null)}
          onImported={(r) => {
            setFile(null);
            setBanner({ kind: "imported", r });
            void changed();
          }}
        />
      ) : null}
    </ShopWorld>
  );
}

function LogJob({
  parts,
  machines,
  onSaved,
}: {
  parts: { filename: string; make_now_process: string | null; label: string | null; mesh_hash?: string }[];
  machines: OwnedMachine[];
  onSaved: () => Promise<number>;
}) {
  const [f, setF] = React.useState<JobForm>(BLANK);
  // The checked part picked (its file hash), so the job is compared with that part's estimate.
  const [partKey, setPartKey] = React.useState<string>("");
  const [errors, setErrors] = React.useState<JobErrors>({});
  const [busy, setBusy] = React.useState(false);
  const [saved, setSaved] = React.useState<string | null>(null);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const ids = React.useId();
  const picks = parts.filter((p) => p.mesh_hash);
  const twice = new Set(picks.map((p) => p.filename).filter((n, i, a) => a.indexOf(n) !== i));
  const owned = Array.from(new Set(machines.map((m) => m.process)));
  const set = (k: keyof JobForm, v: string) => {
    setF((x) => ({ ...x, [k]: v }));
    setSaved(null);
    setSaveError(null);
    setErrors((e) => {
      if (!e[k]) return e;
      const n = { ...e };
      delete n[k];
      return n;
    });
  };
  const pickPart = (key: string) => {
    const rec = picks.find((p) => p.mesh_hash === key);
    setPartKey(key);
    setF((x) => ({ ...x, part: rec?.filename ?? "", process: x.process || rec?.make_now_process || owned[0] || "" }));
    setSaved(null);
    setErrors((e) => ({ ...e, part: undefined }));
  };
  const save = async () => {
    const r = parseJob(f);
    if (!r.ok) {
      setErrors(r.errors);
      return;
    }
    setBusy(true);
    setSaveError(null);
    try {
      await logJob(partKey ? { ...r.body, evidence_sha256: partKey, match_basis: "chosen" } : r.body);
      const n = await onSaved();
      setSaved(`Saved. ${n} ${n === 1 ? "actual" : "actuals"}.`);
      setF((x) => ({ ...BLANK, part: x.part, process: x.process, material: x.material, kind: x.kind }));
    } catch (e) {
      setSaveError(e instanceof ShopApiError && e.status === 422 ? `Check the values: ${e.message}` : e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setBusy(false);
    }
  };
  const err = (k: keyof JobForm) =>
    errors[k] ? (
      <span className="err" id={`${ids}-${k}`}>
        {errors[k]}
      </span>
    ) : null;
  const inv = (k: keyof JobForm) => (errors[k] ? { "aria-invalid": true as const, "aria-describedby": `${ids}-${k}` } : {});
  const others = PROCS.filter(([p]) => !owned.includes(p));
  return (
    <Panel
      title={
        <>
          Log a job<span className="new">New</span>
        </>
      }
      note="Cost each, machine hours each, or both · same part, method and quantity replaces the earlier entry"
    >
      <div className="frow" style={{ gridTemplateColumns: "2fr 1.3fr 0.8fr 1fr 1fr" }}>
        <label className="field">
          Part
          {picks.length ? (
            <select aria-label="Part" value={partKey} onChange={(e) => pickPart(e.target.value)} {...inv("part")}>
              <option value="">Pick a part</option>
              {picks.map((p) => (
                <option key={p.mesh_hash} value={p.mesh_hash}>
                  {p.filename}
                  {p.label ? ` · ${p.label}` : twice.has(p.filename) ? ` · ${p.mesh_hash!.slice(0, 8)}` : ""}
                </option>
              ))}
            </select>
          ) : (
            <input aria-label="Part" type="text" placeholder="widget-a.stl" value={f.part} onChange={(e) => set("part", e.target.value)} {...inv("part")} />
          )}
          {err("part")}
        </label>
        <label className="field">
          Method
          <select aria-label="Method" value={f.process} onChange={(e) => set("process", e.target.value)} {...inv("process")}>
            <option value="">Pick a process</option>
            {owned.length ? (
              <optgroup label="Your machines">
                {owned.map((p) => (
                  <option key={p} value={p}>
                    {procName(p)}
                  </option>
                ))}
              </optgroup>
            ) : null}
            <optgroup label={owned.length ? "Other methods" : "Methods"}>
              {others.map(([p, l]) => (
                <option key={p} value={p}>
                  {l}
                </option>
              ))}
            </optgroup>
          </select>
          {err("process")}
        </label>
        <label className="field">
          Quantity
          <input aria-label="Quantity" type="text" inputMode="numeric" value={f.quantity} onChange={(e) => set("quantity", e.target.value)} {...inv("quantity")} />
          {err("quantity")}
        </label>
        <label className="field">
          Cost each (USD)
          <input aria-label="Cost each (USD)" type="text" inputMode="decimal" placeholder="opt." value={f.cost} onChange={(e) => set("cost", e.target.value)} {...inv("cost")} />
          {err("cost")}
        </label>
        <label className="field">
          Material
          <select aria-label="Material" value={f.material} onChange={(e) => set("material", e.target.value)}>
            {MATERIAL_CLASSES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="frow" style={{ gridTemplateColumns: "1fr 1.3fr 1fr 0.8fr 0.8fr 0.8fr 0.8fr", paddingTop: 0 }}>
        <label className="field">
          Kind
          <select aria-label="Kind" value={f.kind} onChange={(e) => set("kind", e.target.value)}>
            {JOB_KINDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Source
          <input aria-label="Source" type="text" placeholder="PO, invoice or quote no." value={f.source} onChange={(e) => set("source", e.target.value)} />
        </label>
        <label className="field">
          Invoice date
          <input aria-label="Invoice date" type="text" placeholder="YYYY-MM-DD" value={f.date} onChange={(e) => set("date", e.target.value)} {...inv("date")} />
          {err("date")}
        </label>
        <label className="field">
          Machine h each
          <input aria-label="Machine hours per part" type="text" inputMode="decimal" placeholder="opt." value={f.machineH} onChange={(e) => set("machineH", e.target.value)} {...inv("machineH")} />
          {err("machineH")}
        </label>
        <label className="field">
          Setup h
          <input aria-label="Setup hours" type="text" inputMode="decimal" placeholder="opt." value={f.setupH} onChange={(e) => set("setupH", e.target.value)} {...inv("setupH")} />
          {err("setupH")}
        </label>
        <label className="field">
          Labor h
          <input aria-label="Labor hours" type="text" inputMode="decimal" placeholder="opt." value={f.laborH} onChange={(e) => set("laborH", e.target.value)} {...inv("laborH")} />
          {err("laborH")}
        </label>
        <label className="field">
          Inspect h
          <input aria-label="Inspection hours" type="text" inputMode="decimal" placeholder="opt." value={f.inspectH} onChange={(e) => set("inspectH", e.target.value)} {...inv("inspectH")} />
          {err("inspectH")}
        </label>
      </div>
      <div className="pact">
        <button className="btn ink sm" type="button" onClick={() => void save()} disabled={busy}>
          {busy ? "Saving…" : "Save job"}
        </button>
        <span aria-live="polite">
          {saved ? (
            <span className="toast swap" role="status" style={{ position: "static", display: "inline-flex" }}>
              {saved}
            </span>
          ) : null}
        </span>
        {saveError ? (
          <span className="err" role="alert">
            {saveError}
          </span>
        ) : null}
        <span className="fh" style={{ marginLeft: "auto" }}>
          Region, shop, cycle time and evidence link go in the CSV.
        </span>
      </div>
    </Panel>
  );
}

function LoggedJobs({ records, error }: { records: GtRecord[] | null; error: string | null }) {
  const shown = (records ?? []).slice(0, 25);
  const cols = "minmax(0,1fr) 80px 100px 100px 96px";
  return (
    <Panel title="Logged actuals" note={records ? String(records.length) : undefined}>
      {error ? null : records == null ? (
        <Loading rows={2} label="Loading logged actuals" />
      ) : records.length === 0 ? (
        <p className="fh" style={{ margin: "0 16px 12px" }}>
          Nothing logged yet. Import an export of your jobs or log one above.
        </p>
      ) : (
        <>
          <div className="tr th" style={{ gridTemplateColumns: cols }}>
            <span>Part and method</span>
            <span>Quantity</span>
            <span>Machine h each</span>
            <span>Cost each</span>
            <span>Counts</span>
          </div>
          {shown.map((r, i) => (
            <div className="tr" key={`${r.part_id}-${r.process}-${r.quantity}-${i}`} style={{ gridTemplateColumns: cols }}>
              <span style={{ minWidth: 0 }}>
                {r.evidence_sha256 ? (
                  <Link href={R.part(r.evidence_sha256)} style={{ fontWeight: 600, overflowWrap: "anywhere", color: "inherit" }}>
                    {r.part_id}
                  </Link>
                ) : (
                  <b style={{ overflowWrap: "anywhere" }}>{r.part_id}</b>
                )}
                <small>
                  {[
                    r.part_number,
                    procName(r.process),
                    r.machine ? `on ${r.machine}` : null,
                    r.source && !/STAND-IN/i.test(r.source) ? r.source : null,
                    r.invoice_date ? longDate(r.invoice_date) : r.created_at ? `logged ${longDate(r.created_at)}` : null,
                    r.match_basis ? `matched by ${basisWord(r.match_basis)}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </small>
              </span>
              <span className="num">
                <span className="sr">Quantity </span>
                {r.quantity}
              </span>
              <span className="num">
                <span className="sr">Machine hours each </span>
                {r.actual_machine_hours != null ? hoursWord(r.actual_machine_hours) : "—"}
              </span>
              <span className="num">
                <span className="sr">Cost each </span>
                {r.actual_unit_cost_usd != null ? usd(r.actual_unit_cost_usd) : "—"}
              </span>
              <span className={cx("chip", r.stand_in ? "c-unk" : "c-ok")} style={{ justifySelf: "start" }}>
                <i aria-hidden="true" />
                {r.stand_in ? "Test" : "Real"}
              </span>
            </div>
          ))}
          {records.length > shown.length ? (
            <p className="fh" style={{ margin: "6px 16px 12px" }}>
              Newest {shown.length} of {records.length}.
            </p>
          ) : (
            <div style={{ height: 8 }} />
          )}
        </>
      )}
    </Panel>
  );
}

function PartRangeSheet({ details, real, standIn, loadError }: { details: RecordDetail[] | null; real: number; standIn: number; loadError: string | null }) {
  const cur = (details ?? []).map((d) => ({ d, e: headlineEstimate(d) })).find((x) => rangeOf(x.e)) ?? null;
  const r = cur ? rangeOf(cur.e) : null;
  const facts = (
    <div className="kv">
      <span>Actuals</span>
      <b className="num">{real}</b>
      <span>Test</span>
      <b className="num">{standIn}</b>
      <span>Fair picture</span>
      <b>{MIN_REAL_RECORDS} parts with actuals</b>
      <span>Per method</span>
      <b>{MIN_HELD_OUT} actuals before its figure says much</b>
      <span>Held out</span>
      <b>By part, so one part never grades itself</b>
      <span>Never count</span>
      <b>Synthetic, seed, demo, stand-in</b>
      <span>Apply a calibration</span>
      <b>Pilot plan</b>
      <span>Import and compare</span>
      <b>Members and admins, all plans</b>
    </div>
  );
  if (!cur || !r)
    return (
      <>
        <div className="top">
          <h2 className="stitle">Range for one part</h2>
          <p className="smeta">{loadError ? `Couldn't load your checks: ${loadError}` : details == null ? "Reading your checks…" : "Shown on one of your parts after a check is costed."}</p>
        </div>
        <div className="scroll">{facts}</div>
      </>
    );
  const qty = headlineQty(cur.d.quantities);
  const pctText = r.pct != null ? `±${Math.round(r.pct)}%` : "—";
  return (
    <>
      <div className="top">
        <h2 className="stitle">{cur.d.label || cur.d.filename}</h2>
        <p className="smeta">
          {procName(cur.e!.process)} · {cur.e!.material} · each at {qty}
        </p>
        <div className="figs">
          <div className="fig">
            <span>Estimate</span>
            <b className="num">{usd(r.point)}</b>
            <small>{r.measured ? "measured" : "typical"}</small>
          </div>
          <div className="fig">
            <span>Range</span>
            <b className="num">{pctText}</b>
            <small>
              {usd(r.low)}–{usd(r.high)}
            </small>
          </div>
          <div className="fig">
            <span>Actuals</span>
            <b className="num">{real}</b>
            <small>{standIn ? `${standIn} test` : "your whole organization"}</small>
          </div>
        </div>
      </div>
      <div className="scroll">
        <div
          className="band"
          role="img"
          aria-label={r.measured ? `Measured range from ${usd(r.low)} to ${usd(r.high)}, from ${r.n} held-out real results` : `Typical range from ${usd(r.low)} to ${usd(r.high)} around an estimate of ${usd(r.point)}`}
        >
          <span className="ax" />
          <span className={cx("rg", r.measured ? "meas" : "typ")} style={{ left: "6%", width: "88%" }} />
          <span className="pt" style={{ left: `${bandPos(r, r.point)}%` }} />
          <span className="lb num l" style={{ left: "6%" }}>
            {usd(r.low)}
          </span>
          <span className="lb num" style={{ left: `${bandPos(r, r.point)}%` }}>
            {usd(r.point)}
          </span>
          <span className="lb num r" style={{ left: "94%" }}>
            {usd(r.high)}
          </span>
        </div>
        <p style={{ margin: "6px 12px 0", color: "var(--ink2)", fontSize: 13.5 }}>
          {r.measured
            ? "Measured from your held-out real records."
            : `Typical: the band ScaleCAD states for ${lowerFirst(procName(cur.e!.process))}. How often your actuals fall inside it is under Checked against your real numbers.`}
        </p>
        <div className="gh" style={{ marginTop: 12 }}>
          <span>Legend</span>
          <span />
        </div>
        <div className="legend">
          <span>
            <i style={{ border: "2px dashed var(--ink3)" }} aria-hidden="true" />
            {r.measured || r.pct == null ? "Typical: default rates" : `Typical: default rates, ±${Math.round(r.pct)}% for ${lowerFirst(procName(cur.e!.process))}`}
          </span>
          <span>
            <i style={{ border: "2px solid var(--file)", background: "rgba(31,79,196,.08)" }} aria-hidden="true" />
            Measured: from your held-out real records
          </span>
        </div>
        {facts}
        <p className="sh-note">
          <Link href={R.record(cur.d.id)}>Open this record</Link>
        </p>
      </div>
    </>
  );
}
