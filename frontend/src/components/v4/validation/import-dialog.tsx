"use client";

/**
 * Import your actuals the way you have them: a CSV or Excel export. Two steps:
 * which column is which (prefilled from the header names, with the first rows
 * of the file beside it, and the method each process value means), then every
 * row: what it matched and how, which rows fit more than one part (you choose;
 * ScaleCAD never guesses), and what didn't match and why. Import brings in the
 * matched rows; nothing else changes.
 */
import * as React from "react";
import { Dialog } from "../shop/common";
import { PROCS } from "../shop/shop-derive";
import { cx } from "../ui";
import { importActuals, previewActuals, type FieldKey, type ImportResult, type Mapping, type PartPick, type Preview, type PreviewRow } from "./api";
import { basisWord, hoursWord, methodWord, moneyWord } from "./words";
import "./validation.css";

const IDENTITY: { key: FieldKey; label: string }[] = [
  { key: "part_number", label: "Part number" },
  { key: "file_name", label: "File name" },
  { key: "part", label: "Part number or file name" },
  { key: "file_hash", label: "File hash (SHA-256)" },
];
const DETAILS: { key: FieldKey; label: string }[] = [
  { key: "process", label: "Process" },
  { key: "machine", label: "Machine" },
  { key: "date", label: "Date" },
  { key: "reference", label: "Job, PO or invoice no." },
  { key: "notes", label: "Notes" },
  { key: "kind", label: "Kind (actual, quote, test)" },
];

const letter = (i: number) => {
  let s = "";
  let n = i + 1;
  while (n > 0) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
};

type Filter = "all" | "matched" | "ambiguous" | "unmatched" | "error";

function setCol(m: Mapping, key: FieldKey, v: string): Mapping {
  const columns = { ...m.columns };
  if (v === "") delete columns[key];
  else {
    const i = Number(v);
    // One column feeds one field.
    for (const k of Object.keys(columns) as FieldKey[]) if (columns[k] === i) delete columns[k];
    columns[key] = i;
  }
  return { ...m, columns };
}

function partName(p: PartPick): string {
  const pn = p.part_numbers.length ? ` · ${p.part_numbers.slice(0, 2).join(", ")}` : "";
  const when = p.checked_at ? ` · checked ${p.checked_at.slice(0, 10)}` : "";
  return `${p.file_name}${pn}${when}`;
}

export function ImportDialog({ file, onClose, onImported }: { file: File; onClose: () => void; onImported: (r: ImportResult) => void }) {
  const [step, setStep] = React.useState<"columns" | "rows">("columns");
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [mapping, setMapping] = React.useState<Mapping | null>(null);
  const [choices, setChoices] = React.useState<Record<string, string>>({});
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [importing, setImporting] = React.useState(false);
  const [filter, setFilter] = React.useState<Filter>("all");
  const seq = React.useRef(0);
  const fromServer = React.useRef(false);
  const ids = React.useId();

  React.useEffect(() => {
    if (fromServer.current) {
      fromServer.current = false;
      return;
    }
    const my = ++seq.current;
    setLoading(true);
    const t = setTimeout(
      () => {
        previewActuals(file, mapping, choices).then(
          (p) => {
            if (my !== seq.current) return;
            setPreview(p);
            setError(null);
            setLoading(false);
            if (!mapping) {
              fromServer.current = true;
              setMapping(p.mapping);
            }
          },
          (e) => {
            if (my !== seq.current) return;
            setError(e instanceof Error ? e.message : "The file couldn’t be read.");
            setLoading(false);
          }
        );
      },
      mapping ? 250 : 0
    );
    return () => clearTimeout(t);
  }, [file, mapping, choices]);

  const m = mapping;
  const s = preview?.summary;
  const headers = preview?.headers ?? [];
  const colSelect = (key: FieldKey, label: string, value?: number | undefined) => (
    <label className="field" key={key}>
      {label}
      <select aria-label={label} value={value ?? (m?.columns[key] ?? "")} onChange={(e) => m && setMapping(setCol(m, key, e.target.value))} disabled={!m}>
        <option value="">Not in this file</option>
        {headers.map((h, i) => (
          <option key={i} value={i}>
            {letter(i)}: {h || "(no name)"}
          </option>
        ))}
      </select>
    </label>
  );

  const hoursKey: FieldKey | null = m ? (m.columns.machine_hours != null ? "machine_hours" : m.columns.machine_hours_total != null ? "machine_hours_total" : null) : null;
  const costKey: FieldKey | null = m ? (m.columns.cost_each != null ? "cost_each" : m.columns.cost_total != null ? "cost_total" : null) : null;
  const moveCol = (from: FieldKey | null, to: FieldKey) => {
    if (!m || !from || from === to) return;
    const columns = { ...m.columns };
    columns[to] = columns[from];
    delete columns[from];
    setMapping({ ...m, columns });
  };
  const pickCol = (pair: [FieldKey, FieldKey], current: FieldKey | null, v: string) => {
    if (!m) return;
    let next = { ...m, columns: { ...m.columns } };
    delete next.columns[pair[0]];
    delete next.columns[pair[1]];
    if (v !== "") next = setCol(next, current ?? pair[0], v);
    setMapping(next);
  };

  const rows = (preview?.rows ?? []).filter((r) => filter === "all" || r.status === filter);
  const ready = s ? s.matched : 0;
  const unresolved = (preview?.rows ?? []).filter((r) => r.status === "ambiguous").length;

  const doImport = async () => {
    if (!m) return;
    setImporting(true);
    setError(null);
    try {
      const r = await importActuals(file, m, choices);
      onImported(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The import didn’t finish. Nothing was saved.");
    } finally {
      setImporting(false);
    }
  };

  const footer =
    step === "columns" ? (
      <>
        <button className="btn ink sm" type="button" onClick={() => setStep("rows")} disabled={!preview || loading}>
          {preview ? `Check ${preview.summary.rows} ${preview.summary.rows === 1 ? "row" : "rows"}` : "Reading…"}
        </button>
        <button className="btn sm" type="button" onClick={onClose}>
          Cancel
        </button>
        <span className="fh" style={{ marginLeft: "auto" }} aria-live="polite">
          {loading ? "Matching…" : s ? `${s.matched} matched · ${s.ambiguous} to choose · ${s.unmatched} not matched · ${s.error} with a problem` : ""}
        </span>
      </>
    ) : (
      <>
        <button className="btn ink sm" type="button" onClick={() => void doImport()} disabled={!ready || importing || loading}>
          {importing ? "Importing…" : `Import ${ready} ${ready === 1 ? "row" : "rows"}`}
        </button>
        <button className="btn sm" type="button" onClick={() => setStep("columns")} disabled={importing}>
          Back to columns
        </button>
        <button className="btn sm" type="button" onClick={onClose} disabled={importing}>
          Cancel
        </button>
        <span className="fh" style={{ marginLeft: "auto" }} aria-live="polite">
          {loading ? "Matching…" : unresolved ? `${unresolved} ${unresolved === 1 ? "row fits" : "rows fit"} more than one part: choose or skip ${unresolved === 1 ? "it" : "them"}.` : "Rows not matched stay out; nothing else changes."}
        </span>
      </>
    );

  return (
    <div className="val-dlg-host">
      <Dialog title="Import actuals" onDismiss={onClose} onClose={onClose} footer={footer}>
        <p className="val-steps" aria-label="Steps">
          <span>{step === "columns" ? <b>1 Columns</b> : "1 Columns"}</span>
          <span aria-hidden="true">›</span>
          <span>{step === "rows" ? <b>2 Rows</b> : "2 Rows"}</span>
        </p>
        <p className="fh" style={{ margin: 0 }}>
          <b style={{ color: "var(--ink)" }}>{file.name}</b>
          {preview ? ` · ${preview.file.rows} ${preview.file.rows === 1 ? "row" : "rows"} · ${preview.file.kind === "xlsx" ? "first sheet of the workbook" : "CSV"} · ${preview.parts_checked} checked ${preview.parts_checked === 1 ? "part" : "parts"} to match against` : ""}
        </p>
        {preview?.file.notes.map((n) => (
          <p key={n} className="fh" style={{ margin: 0 }}>
            {n}
          </p>
        ))}
        {error ? (
          <div className="banner bad" role="alert">
            <span>
              <b>{preview ? "Couldn’t update." : "This file can’t be read."}</b> {error}
            </span>
          </div>
        ) : null}
        {!preview && !error ? <p className="fh">Reading the file…</p> : null}

        {preview && m && step === "columns" ? (
          <>
            <div className="val-sample" role="region" aria-label="The first rows of the file" tabIndex={0}>
              <table>
                <thead>
                  <tr>
                    {headers.map((h, i) => (
                      <th key={i} scope="col">
                        <i>{letter(i)}</i>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample.slice(0, 3).map((r, ri) => (
                    <tr key={ri}>
                      {headers.map((_, i) => (
                        <td key={i}>{r[i]}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="val-map">
              <p className="val-grp">Which part (one is enough; more narrow it down)</p>
              {IDENTITY.map((f) => colSelect(f.key, f.label))}
              <p className="val-grp">Numbers</p>
              {colSelect("quantity", "Quantity")}
              <div className="field">
                <label htmlFor={`${ids}-h`}>Machine hours</label>
                <select id={`${ids}-h`} value={hoursKey ? m.columns[hoursKey] ?? "" : ""} onChange={(e) => pickCol(["machine_hours", "machine_hours_total"], hoursKey, e.target.value)}>
                  <option value="">Not in this file</option>
                  {headers.map((h, i) => (
                    <option key={i} value={i}>
                      {letter(i)}: {h || "(no name)"}
                    </option>
                  ))}
                </select>
                {hoursKey ? (
                  <span className="opts">
                    <span className="seg" role="group" aria-label="Machine hours are">
                      <button type="button" className={cx(hoursKey === "machine_hours" && "on")} aria-pressed={hoursKey === "machine_hours"} onClick={() => moveCol(hoursKey, "machine_hours")}>
                        Per part
                      </button>
                      <button type="button" className={cx(hoursKey === "machine_hours_total" && "on")} aria-pressed={hoursKey === "machine_hours_total"} onClick={() => moveCol(hoursKey, "machine_hours_total")}>
                        Whole quantity
                      </button>
                    </span>
                    <span className="seg" role="group" aria-label="Machine time unit">
                      <button type="button" className={cx(m.hours_unit === "h" && "on")} aria-pressed={m.hours_unit === "h"} onClick={() => setMapping({ ...m, hours_unit: "h" })}>
                        Hours
                      </button>
                      <button type="button" className={cx(m.hours_unit === "min" && "on")} aria-pressed={m.hours_unit === "min"} onClick={() => setMapping({ ...m, hours_unit: "min" })}>
                        Minutes
                      </button>
                    </span>
                  </span>
                ) : null}
              </div>
              <div className="field">
                <label htmlFor={`${ids}-c`}>Cost (US dollars)</label>
                <select id={`${ids}-c`} value={costKey ? m.columns[costKey] ?? "" : ""} onChange={(e) => pickCol(["cost_each", "cost_total"], costKey, e.target.value)}>
                  <option value="">Not in this file</option>
                  {headers.map((h, i) => (
                    <option key={i} value={i}>
                      {letter(i)}: {h || "(no name)"}
                    </option>
                  ))}
                </select>
                {costKey ? (
                  <span className="opts">
                    <span className="seg" role="group" aria-label="Cost is">
                      <button type="button" className={cx(costKey === "cost_each" && "on")} aria-pressed={costKey === "cost_each"} onClick={() => moveCol(costKey, "cost_each")}>
                        Per part
                      </button>
                      <button type="button" className={cx(costKey === "cost_total" && "on")} aria-pressed={costKey === "cost_total"} onClick={() => moveCol(costKey, "cost_total")}>
                        Whole quantity
                      </button>
                    </span>
                  </span>
                ) : null}
              </div>
              <p className="val-grp">Details</p>
              {DETAILS.map((f) => colSelect(f.key, f.label))}
            </div>
            {m.columns.date != null ? (
              <div className="val-check">
                Dates like 03/04/2026 are
                <span className="seg" role="group" aria-label="Date order">
                  <button type="button" className={cx(m.date_order === "mdy" && "on")} aria-pressed={m.date_order === "mdy"} onClick={() => setMapping({ ...m, date_order: "mdy" })}>
                    Month first
                  </button>
                  <button type="button" className={cx(m.date_order === "dmy" && "on")} aria-pressed={m.date_order === "dmy"} onClick={() => setMapping({ ...m, date_order: "dmy" })}>
                    Day first
                  </button>
                </span>
              </div>
            ) : null}
            {preview.process_values.length ? (
              <>
                <p className="val-grp" style={{ margin: 0 }}>
                  The method each process means
                </p>
                <div className="val-pv">
                  {preview.process_values.map((pv) => {
                    const val = m.process_map[pv.key] ?? pv.method ?? "";
                    const lid = `${ids}-pv-${pv.key || "blank"}`;
                    return (
                      <React.Fragment key={pv.key}>
                        <label htmlFor={lid}>
                          <b>{pv.value || "No process given"}</b>
                          <span className="fh">
                            {" "}
                            · {pv.rows} {pv.rows === 1 ? "row" : "rows"}
                            {pv.guess && !m.process_map[pv.key] ? " · read from the words" : ""}
                          </span>
                        </label>
                        <select id={lid} value={val} onChange={(e) => setMapping({ ...m, process_map: { ...m.process_map, [pv.key]: e.target.value } })}>
                          <option value="">Pick the method…</option>
                          <option value="pick">ScaleCAD’s pick for each part</option>
                          {PROCS.map(([c, l]) => (
                            <option key={c} value={c}>
                              {l}
                            </option>
                          ))}
                        </select>
                      </React.Fragment>
                    );
                  })}
                </div>
              </>
            ) : null}
            <label className="val-check">
              <input type="checkbox" checked={m.test} onChange={(e) => setMapping({ ...m, test: e.target.checked })} />
              These are test numbers. They show here, labelled Test, and never count toward accuracy or calibration.
            </label>
          </>
        ) : null}

        {preview && m && step === "rows" ? (
          <>
            <div className="val-chips" role="group" aria-label="Show rows">
              {(
                [
                  ["all", `All ${s!.rows}`],
                  ["matched", `${s!.matched} matched`],
                  ["ambiguous", `${s!.ambiguous} to choose`],
                  ["unmatched", `${s!.unmatched} not matched`],
                  ["error", `${s!.error} with a problem`],
                ] as [Filter, string][]
              ).map(([k, l]) => (
                <button key={k} type="button" className={cx("btn sm", filter === k ? "ink" : "ghost")} aria-pressed={filter === k} onClick={() => setFilter(k)}>
                  {l}
                </button>
              ))}
              {s!.test ? <span className="fh" style={{ alignSelf: "center" }}>{s!.test} test</span> : null}
            </div>
            {rows.length ? (
              <div className="val-rows" role="list" aria-label="Rows of the file">
                {rows.slice(0, 300).map((r) => (
                  <RowView key={r.line} r={r} parts={preview.parts ?? []} choice={choices[String(r.line)]} onChoose={(v) => setChoices((c) => {
                    const next = { ...c };
                    if (v) next[String(r.line)] = v;
                    else delete next[String(r.line)];
                    return next;
                  })} />
                ))}
              </div>
            ) : (
              <p className="fh">No rows here.</p>
            )}
            {rows.length > 300 ? <p className="fh">First 300 of {rows.length} shown; all {ready} matched rows import.</p> : null}
          </>
        ) : null}
      </Dialog>
    </div>
  );
}

function RowView({ r, parts, choice, onChoose }: { r: PreviewRow; parts: PartPick[]; choice: string | undefined; onChoose: (v: string) => void }) {
  const v = r.values;
  const who = [v.part_number, v.file_name, v.file_hash ? `hash ${v.file_hash.slice(0, 10)}…` : null].filter(Boolean).join(" · ") || "No part given";
  const nums = [
    v.quantity != null ? `${v.quantity.toLocaleString("en-US")} ${v.quantity === 1 ? "part" : "parts"}` : null,
    v.hours_each != null ? `${hoursWord(v.hours_each)} each` : null,
    v.cost_each != null ? `${moneyWord(v.cost_each)} each` : null,
  ].filter(Boolean);
  const tone = r.status === "matched" ? "c-ok" : r.status === "ambiguous" ? "c-warn" : r.status === "error" ? "c-bad" : "c-unk";
  const word = r.status === "matched" ? (v.test ? "Matched · test" : "Matched") : r.status === "ambiguous" ? "Choose" : r.status === "error" ? "Problem" : "Not matched";
  const sid = `row-${r.line}`;
  return (
    <div className="val-row" role="listitem">
      <span className="ln">Row {r.line}</span>
      <span>
        <b>{who}</b>
        <small>{[...nums, v.process ? methodWord(v.process) : null, v.machine, v.date].filter(Boolean).join(" · ")}</small>
      </span>
      <span>
        <span className={cx("chip", tone)}>
          <i aria-hidden="true" />
          {word}
        </span>
        {r.status === "matched" && r.part ? (
          <small>
            {r.part.file_name}
            {r.basis ? ` · by ${basisWord(r.basis)}` : ""}
          </small>
        ) : null}
        {r.status !== "matched" && r.reason ? <small>{r.reason}</small> : null}
        {r.errors.map((e) => (
          <small key={e} className="why">
            {e}
          </small>
        ))}
        {r.warnings.map((e) => (
          <small key={e}>{e}</small>
        ))}
      </span>
      <span>
        {r.status === "ambiguous" || (r.status === "matched" && r.basis === "chosen") ? (
          <>
            <label htmlFor={sid} className="fh">
              Which part is it?
            </label>
            <select id={sid} value={choice ?? ""} onChange={(e) => onChoose(e.target.value)}>
              <option value="">Choose…</option>
              {(r.candidates.length ? r.candidates : parts).map((p) => (
                <option key={p.key} value={p.key}>
                  {partName(p)}
                </option>
              ))}
              <option value="skip">Skip this row</option>
            </select>
          </>
        ) : r.status === "unmatched" && r.reason !== "Skipped" && parts.length ? (
          <>
            <label htmlFor={sid} className="fh">
              Match it to a part
            </label>
            <select id={sid} value={choice ?? ""} onChange={(e) => onChoose(e.target.value)}>
              <option value="">Leave it out</option>
              {parts.map((p) => (
                <option key={p.key} value={p.key}>
                  {partName(p)}
                </option>
              ))}
            </select>
          </>
        ) : r.reason === "Skipped" ? (
          <button className="btn sm ghost" type="button" onClick={() => onChoose("")}>
            Don’t skip
          </button>
        ) : null}
      </span>
    </div>
  );
}
