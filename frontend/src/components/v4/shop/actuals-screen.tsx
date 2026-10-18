"use client";

/**
 * Real costs (board S2): send real job costs back (one job at a time or a CSV),
 * see what's logged, and recalibrate (pilot plan) once the organization has
 * enough real records. A method's range turns measured only from its own
 * held-out real results; stand-ins never count.
 */
import * as React from "react";
import Link from "next/link";
import { listMachines, type OwnedMachine } from "@/lib/verify/machine-api";
import { ApiError, groundTruthTemplate, importGroundTruthCsv, listGroundTruth, recalibrate, type GroundTruthImportSummary, type InsufficientGroundTruth } from "@/lib/verify/calibration-api";
import { R, TABS } from "../routes";
import { useShell } from "../shell";
import { Content, Loading, PageHead, Panel, Sheet, cx, usd } from "../ui";
import { Banner, ShopWorld, recordDetail, useRecords } from "./common";
import { downloadText, latestPerPart, logJob, ShopApiError, type RecordDetail } from "./shop-api";
import { PROCS, longDate, procName } from "./shop-derive";
import { headlineEstimate, headlineQty } from "./rates-derive";
import {
  JOB_KINDS,
  MATERIAL_CLASSES,
  MIN_HELD_OUT,
  MIN_REAL_RECORDS,
  bandPos,
  countRecords,
  methodRows,
  parseJob,
  rangeOf,
  type GtRecord,
  type JobErrors,
  type JobForm,
  type RecalResult,
} from "./actuals-derive";

type BannerState =
  | { kind: "ask" }
  | { kind: "refused"; n: number; min: number; reason?: string }
  | { kind: "pilot"; text: string }
  | { kind: "recalOk"; r: RecalResult }
  | { kind: "recalError"; msg: string }
  | { kind: "imported"; s: GroundTruthImportSummary }
  | { kind: "importError"; msg: string }
  | { kind: "template" }
  | { kind: "templateError"; msg: string }
  | null;

const BLANK: JobForm = { part: "", process: "", quantity: "10", cost: "", material: "aluminum", kind: "actual", source: "", date: "", machineH: "", setupH: "", laborH: "", inspectH: "" };

const lowerFirst = (t: string) => t.charAt(0).toLowerCase() + t.slice(1);

const REQUIRED_COLUMNS = 4; // part_id, process, quantity, actual_unit_cost_usd (groundtruth_service.CSV_REQUIRED_COLUMNS)

export function ActualsScreen() {
  const { usage } = useShell();
  const [records, setRecords] = React.useState<GtRecord[] | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [machines, setMachines] = React.useState<OwnedMachine[]>([]);
  const [banner, setBanner] = React.useState<BannerState>(null);
  const [busy, setBusy] = React.useState<"recal" | "csv" | null>(null);
  const [recal, setRecal] = React.useState<RecalResult | null>(null);
  const [columns, setColumns] = React.useState<string[] | null>(null);
  const csvRef = React.useRef<HTMLInputElement>(null);
  const askRef = React.useRef<HTMLButtonElement>(null);
  const recalBtn = React.useRef<HTMLButtonElement>(null);
  const recs = useRecords();
  const [details, setDetails] = React.useState<RecordDetail[] | null>(null);

  const load = React.useCallback(async (): Promise<GtRecord[] | null> => {
    setLoadError(null);
    try {
      const page = await listGroundTruth();
      setRecords(page.records as GtRecord[]);
      return page.records as GtRecord[];
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Couldn't load real costs.");
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

  React.useEffect(() => {
    if (!recs.data) return;
    let live = true;
    const parts = latestPerPart(recs.data).slice(0, 12);
    Promise.allSettled(parts.map((r) => recordDetail(r.id))).then((res) => {
      if (live) setDetails(res.filter((x): x is PromiseFulfilledResult<RecordDetail> => x.status === "fulfilled").map((x) => x.value));
    });
    return () => {
      live = false;
    };
  }, [recs.data]);

  React.useEffect(() => {
    if (banner?.kind === "ask") askRef.current?.focus();
  }, [banner]);

  const { real, standIn } = countRecords(records);
  const estimates = React.useMemo(() => (details ?? []).map(headlineEstimate), [details]);
  const rows = methodRows({
    machines,
    records: records ?? [],
    savedProcesses: latestPerPart(recs.data ?? []).map((r) => r.make_now_process),
    estimates,
    recal,
  });
  const anyMeasured = rows.some((r) => r.measured);
  const pilot = usage ? usage.plan === "pilot" : null;

  const askRecal = () => {
    if (pilot === false) {
      setBanner({ kind: "pilot", text: "Recalibration is part of a pilot plan. Your plan covers single-part checks." });
      return;
    }
    setBanner({ kind: "ask" });
  };

  const doRecal = async () => {
    setBusy("recal");
    try {
      const r = (await recalibrate()) as unknown as RecalResult;
      setRecal(r);
      setBanner({ kind: "recalOk", r });
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        const d = (e.body as { detail?: InsufficientGroundTruth } | null)?.detail;
        setBanner({ kind: "refused", n: d?.n_real ?? real, min: d?.min_real ?? MIN_REAL_RECORDS });
      } else if (e instanceof ApiError && e.status === 403) {
        setBanner({ kind: "pilot", text: e.message || "Recalibration is part of a pilot plan." });
      } else {
        setBanner({ kind: "recalError", msg: e instanceof Error ? e.message : "Recalibration failed." });
      }
    } finally {
      setBusy(null);
      recalBtn.current?.focus();
    }
  };

  const onCsv = async (file: File) => {
    setBusy("csv");
    setBanner(null);
    try {
      const s = await importGroundTruthCsv(file);
      setBanner({ kind: "imported", s });
      await load();
    } catch (e) {
      setBanner({ kind: "importError", msg: e instanceof Error ? e.message : "Import failed." });
    } finally {
      setBusy(null);
    }
  };

  const onTemplate = async () => {
    try {
      downloadText(await groundTruthTemplate(), "ground-truth-template.csv");
      setBanner({ kind: "template" });
    } catch (e) {
      setBanner({ kind: "templateError", msg: e instanceof Error ? e.message : "Couldn't download the template." });
    }
  };

  const nOf = records ? (real > MIN_REAL_RECORDS ? `${real} real` : `${real} of ${MIN_REAL_RECORDS}`) : "…";

  return (
    <ShopWorld label="Real costs">
      <PageHead
        title="Real costs"
        actions={
          <>
            <button className="btn sm" type="button" onClick={() => csvRef.current?.click()} disabled={busy === "csv"}>
              {busy === "csv" ? "Importing…" : "Import CSV"}
            </button>
            <button className="btn sm" type="button" onClick={onTemplate}>
              Download template<span className="new">New</span>
            </button>
            <button className="btn ink sm" type="button" ref={recalBtn} onClick={askRecal} disabled={busy === "recal"}>
              {busy === "recal" ? "Recalibrating…" : "Recalibrate"} <span className="pilot">Pilot</span>
            </button>
          </>
        }
        meta={[
          <>
            Real records <b className="num">{records ? real : "…"}</b>
          </>,
          <>
            Stand-ins <b className="num">{records ? standIn : "…"}</b>
          </>,
          <>
            Floor <b>{MIN_REAL_RECORDS} real</b>
          </>,
          <>
            Range <b>{anyMeasured ? "Measured" : "Typical"}</b>
          </>,
        ]}
        tabs={TABS.shop}
        tabsLabel="Your shop"
      />
      <input
        ref={csvRef}
        type="file"
        accept=".csv,text/csv"
        aria-label="Choose a real costs CSV to import"
        tabIndex={-1}
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void onCsv(f);
        }}
      />
      <Content>
        {banner?.kind === "ask" ? (
          <div className="banner" role="alertdialog" aria-label="Recalibrate">
            <span>
              <b>
                Recalibrate from {real} real {real === 1 ? "record" : "records"}?
              </b> Results are held out by part. Stand-ins don&apos;t count.
            </span>
            <span className="bx">
              <button className="btn ink sm" type="button" onClick={() => void doRecal()} disabled={busy === "recal"}>
                {busy === "recal" ? "Recalibrating…" : "Recalibrate"}
              </button>
              <button className="btn sm" type="button" ref={askRef} onClick={() => setBanner(null)} disabled={busy === "recal"}>
                Cancel
              </button>
            </span>
          </div>
        ) : null}
        {banner?.kind === "refused" ? (
          <Banner tone="bad" alert onDismiss={() => setBanner(null)}>
            <b>
              Recalibration refused: {banner.n} real of {banner.min} needed.
            </b>{" "}
            Stand-in and synthetic records never count. Add real jobs and retry.
          </Banner>
        ) : null}
        {banner?.kind === "pilot" ? (
          <Banner
            tone="warn"
            alert
            onDismiss={() => setBanner(null)}
            actions={
              <a className="btn sm ink" href="/pilot">
                Plan pilot
              </a>
            }
          >
            <b>Pilot plan.</b> {banner.text} Logging jobs and importing CSVs work on every plan.
          </Banner>
        ) : null}
        {banner?.kind === "recalOk" ? (
          <Banner tone={banner.r.validated ? "ok" : "warn"} onDismiss={() => setBanner(null)}>
            {banner.r.validated ? (
              <>
                <b>Recalibrated.</b> Measured range for {(banner.r.validated_processes ?? []).map(procName).join(", ")} from{" "}
                {(banner.r.validated_processes ?? []).reduce((n, p) => n + (banner.r.heldout_metrics_real?.per_process?.[p]?.n ?? 0), 0)} held-out results.
              </>
            ) : (
              <>
                <b>Recalibrated.</b> No method has {MIN_HELD_OUT} held-out real results yet, so ranges stay typical.
              </>
            )}
            {banner.r.n_skipped ? (
              <ul>
                {(banner.r.skipped ?? []).slice(0, 5).map((s, i) => (
                  <li key={i}>
                    {s.part_id} · {procName(s.process)} × {s.quantity}: {s.reason}
                  </li>
                ))}
                {banner.r.n_skipped > 5 ? <li>{banner.r.n_skipped - 5} more couldn&apos;t be costed.</li> : null}
              </ul>
            ) : null}
          </Banner>
        ) : null}
        {banner?.kind === "recalError" ? (
          <Banner tone="bad" alert onDismiss={() => setBanner(null)}>
            <b>Recalibration failed.</b> {banner.msg}
          </Banner>
        ) : null}
        {banner?.kind === "imported" ? (
          <Banner tone={banner.s.errors.length ? "warn" : "ok"} onDismiss={() => setBanner(null)}>
            <b>
              {banner.s.imported} imported · {banner.s.skipped} skipped · {banner.s.total} total
            </b>
            {banner.s.errors.length ? (
              <ul>
                {banner.s.errors.map((er, i) => (
                  <li key={i}>
                    Line {er.line}: {er.reason}
                  </li>
                ))}
              </ul>
            ) : null}
          </Banner>
        ) : null}
        {banner?.kind === "importError" ? (
          <Banner tone="bad" alert onDismiss={() => setBanner(null)}>
            <b>Import failed.</b> {banner.msg} Nothing already logged was changed.
          </Banner>
        ) : null}
        {banner?.kind === "template" ? (
          <Banner tone="ok" onDismiss={() => setBanner(null)}>
            <b>ground-truth-template.csv downloaded.</b> Header row and one example line.
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
            <b>Couldn&apos;t load real costs.</b> {loadError}
          </Banner>
        ) : null}

        <LogJob
          parts={latestPerPart(recs.data ?? [])}
          machines={machines}
          onSaved={async () => countRecords(await load()).real}
        />

        <Panel title="Calibration" note={`${MIN_REAL_RECORDS} real records to recalibrate · ${MIN_HELD_OUT} held-out results per method for a measured range`}>
          <div className="floorrow">
            <b style={{ fontSize: 13, fontWeight: 600 }}>Real records</b>
            <span className="slots8" role="img" aria-label={`${real} of ${MIN_REAL_RECORDS} real records`}>
              {Array.from({ length: MIN_REAL_RECORDS }, (_, i) => (
                <span key={i} className={cx(real > i && "on")} />
              ))}
            </span>
            <span className="num" style={{ textAlign: "right", fontWeight: 600 }}>
              {nOf}
            </span>
          </div>
          <div className="tr th" style={{ gridTemplateColumns: "minmax(0,1fr) 110px 150px 120px" }}>
            <span>Method</span>
            <span>Real records</span>
            <span>Held-out results</span>
            <span>Range</span>
          </div>
          {rows.length === 0 ? (
            <p className="fh" style={{ margin: "4px 16px 12px" }}>
              Methods show here once you add a machine or log a job.
            </p>
          ) : (
            rows.map((r) => (
              <div className="tr" key={r.process} style={{ gridTemplateColumns: "minmax(0,1fr) 110px 150px 120px" }}>
                <span>
                  <b>{procName(r.process)}</b>
                  <small>
                    {[r.machines.join(", ") || "No machine", r.savedParts ? `${r.savedParts} saved part${r.savedParts === 1 ? "" : "s"}` : "no saved parts"].join(" · ")}
                  </small>
                </span>
                <span className="num">
                  <span className="sr">Real records </span>
                  {r.real}
                </span>
                <span className="num">
                  <span className="sr">Held-out results </span>
                  {r.heldOut == null ? "Not run" : `${r.heldOut} of ${MIN_HELD_OUT}`}
                </span>
                <span className={cx("chip", r.measured ? "c-ok" : "c-unk")} style={{ justifySelf: "start" }}>
                  <i aria-hidden="true" />
                  {r.measured ? "Measured" : "Typical"}
                </span>
              </div>
            ))
          )}
        </Panel>

        <LoggedJobs records={records} error={loadError} />

        <Panel title="CSV columns" note="Header row, any order, lower case">
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
    </ShopWorld>
  );
}

function LogJob({
  parts,
  machines,
  onSaved,
}: {
  parts: { filename: string; make_now_process: string | null; label: string | null }[];
  machines: OwnedMachine[];
  onSaved: () => Promise<number>;
}) {
  const [f, setF] = React.useState<JobForm>(BLANK);
  const [errors, setErrors] = React.useState<JobErrors>({});
  const [busy, setBusy] = React.useState(false);
  const [saved, setSaved] = React.useState<string | null>(null);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const ids = React.useId();
  const names = Array.from(new Set(parts.map((p) => p.filename)));
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
  const pickPart = (name: string) => {
    const rec = parts.find((p) => p.filename === name);
    setF((x) => ({ ...x, part: name, process: x.process || rec?.make_now_process || owned[0] || "" }));
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
      await logJob(r.body);
      const n = await onSaved();
      setSaved(`Saved. ${n} real.`);
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
      note="Same part, method and quantity replaces the earlier entry"
    >
      <div className="frow" style={{ gridTemplateColumns: "2fr 1.3fr 0.8fr 1fr 1fr" }}>
        <label className="field">
          Part
          {names.length ? (
            <select aria-label="Part" value={f.part} onChange={(e) => pickPart(e.target.value)} {...inv("part")}>
              <option value="">Pick a part</option>
              {names.map((n) => (
                <option key={n} value={n}>
                  {n}
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
            <option value="">Pick a method</option>
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
          <input aria-label="Cost each (USD)" type="text" inputMode="decimal" placeholder="31.80" value={f.cost} onChange={(e) => set("cost", e.target.value)} {...inv("cost")} />
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
          Machine h
          <input aria-label="Machine hours" type="text" inputMode="decimal" placeholder="opt." value={f.machineH} onChange={(e) => set("machineH", e.target.value)} {...inv("machineH")} />
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
  return (
    <Panel title="Logged jobs" note={records ? String(records.length) : undefined}>
      {error ? null : records == null ? (
        <Loading rows={2} label="Loading logged jobs" />
      ) : records.length === 0 ? (
        <p className="fh" style={{ margin: "0 16px 12px" }}>
          No jobs logged yet. Log one above or import a CSV.
        </p>
      ) : (
        <>
          <div className="tr th" style={{ gridTemplateColumns: "minmax(0,1fr) 90px 110px 110px" }}>
            <span>Part and method</span>
            <span>Quantity</span>
            <span>Cost each</span>
            <span>Counts</span>
          </div>
          {shown.map((r, i) => (
            <div className="tr" key={`${r.part_id}-${r.process}-${r.quantity}-${i}`} style={{ gridTemplateColumns: "minmax(0,1fr) 90px 110px 110px" }}>
              <span style={{ minWidth: 0 }}>
                <b style={{ overflowWrap: "anywhere" }}>{r.part_id}</b>
                <small>
                  {procName(r.process)}
                  {r.source ? ` · ${r.source}` : ""}
                  {r.invoice_date ? ` · ${longDate(r.invoice_date)}` : r.created_at ? ` · logged ${longDate(r.created_at)}` : ""}
                </small>
              </span>
              <span className="num">
                <span className="sr">Quantity </span>
                {r.quantity}
              </span>
              <span className="num">
                <span className="sr">Cost each </span>
                {usd(r.actual_unit_cost_usd)}
              </span>
              <span className={cx("chip", r.stand_in ? "c-unk" : "c-ok")} style={{ justifySelf: "start" }}>
                <i aria-hidden="true" />
                {r.stand_in ? "Stand-in" : "Real"}
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
      <span>Real records</span>
      <b className="num">{real}</b>
      <span>Stand-ins</span>
      <b className="num">{standIn}</b>
      <span>Floor</span>
      <b>{MIN_REAL_RECORDS} real, whole organization</b>
      <span>Measured range</span>
      <b>{MIN_HELD_OUT} held-out results for the method</b>
      <span>Held out</span>
      <b>By part, so one part never grades itself</b>
      <span>Never count</span>
      <b>Synthetic, seed, demo, stand-in</b>
      <span>Recalibrate</span>
      <b>Pilot plan</b>
      <span>Log and import</span>
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
            <span>Real records</span>
            <b className="num">{real}</b>
            <small>of {MIN_REAL_RECORDS}</small>
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
            : real >= MIN_REAL_RECORDS
              ? "Enough real records. Recalibrate to measure."
              : `Typical until ${MIN_REAL_RECORDS} real records and ${MIN_HELD_OUT} held-out ${lowerFirst(procName(cur.e!.process))} results.`}
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
