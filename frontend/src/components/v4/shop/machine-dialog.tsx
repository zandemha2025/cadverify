"use client";

/**
 * Add or edit a machine (board O9's dialog). Every value is the shop's own
 * declaration. Only the fields shown are checked when saving, and every
 * capability the form doesn't show (axes, motion mode, older keys, a catalog
 * template's extras) rides along unchanged.
 */
import * as React from "react";
import { createMachine, updateMachine, type MachineInput, type OwnedMachine } from "@/lib/verify/machine-api";
import { fetchMachineCatalog, type MachineCatalogTemplate } from "@/lib/verify/machine-catalog-api";
import {
  capitalPercentText,
  envelopeFieldsFrom,
  mergeMachineCapabilities,
  mergePrinterCapabilities,
  parseCapitalPercent,
  parseMachineNumbers,
  parsePrinterDetails,
  printerFieldsFor,
  printerFieldsFrom,
  type PrinterText,
} from "@/lib/verify/machine-form";
import { Dialog } from "./common";
import { LATHE, PROCS, machineName, procName } from "./shop-derive";

type Form = {
  name: string;
  process: string;
  count: string;
  rate: string;
  x: string;
  y: string;
  z: string;
  swing: string;
  between: string;
  kg: string;
  capital: string;
  mats: string;
  notes: string;
  printer: PrinterText;
};

type Errors = Partial<Record<"count" | "rate" | "kg" | "x" | "y" | "z" | "swing" | "between" | "capital" | keyof PrinterText, string>>;

function formFrom(m: Partial<MachineInput> | null, process = "cnc_3axis"): Form {
  const cap = (m?.capabilities ?? {}) as Record<string, unknown>;
  const env = envelopeFieldsFrom(cap);
  return {
    name: m?.name ?? "",
    process: m?.process ?? process,
    count: m?.count != null ? String(m.count) : "1",
    rate: m?.hourly_rate_usd != null ? String(m.hourly_rate_usd) : "",
    ...env,
    kg: m?.max_workpiece_kg != null ? String(m.max_workpiece_kg) : "",
    capital: capitalPercentText(m?.capital_frac),
    mats: m?.materials?.join(", ") ?? "",
    notes: m?.notes ?? "",
    printer: printerFieldsFrom(cap),
  };
}

const ENCLOSURE_LABELS: [PrinterText["enclosure"], string][] = [
  ["", "Not declared"],
  ["none", "Open"],
  ["enclosed", "Closed, not heated"],
  ["heated", "Heated chamber"],
];

export function MachineDialog({
  mode,
  machine,
  presetProcess,
  onClose,
  onSaved,
}: {
  mode: "add" | "edit";
  machine?: OwnedMachine | null;
  presetProcess?: string;
  onClose: () => void;
  onSaved: (m: OwnedMachine, mode: "add" | "edit") => void;
}) {
  const editing = mode === "edit" && machine;
  const [form, setForm] = React.useState<Form>(() => formFrom(editing ? machine : null, presetProcess));
  // Capabilities the form doesn't show come from here: the machine being edited, or the catalog template.
  const [baseCap, setBaseCap] = React.useState<Record<string, unknown>>(() => (editing ? machine.capabilities ?? {} : {}));
  const [pre, setPre] = React.useState("");
  const [dirty, setDirty] = React.useState(false);
  const [discard, setDiscard] = React.useState(false);
  const [errors, setErrors] = React.useState<Errors>({});
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [catalog, setCatalog] = React.useState<MachineCatalogTemplate[] | null | "failed">(null);
  const ids = React.useId();
  const discardRef = React.useRef<HTMLButtonElement>(null);

  React.useEffect(() => {
    if (mode !== "add") return;
    let live = true;
    fetchMachineCatalog().then(
      (c) => live && setCatalog(c),
      () => live && setCatalog("failed")
    );
    return () => {
      live = false;
    };
  }, [mode]);

  React.useEffect(() => {
    if (discard) discardRef.current?.focus();
  }, [discard]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setForm((f) => ({ ...f, [k]: v }));
    setDirty(true);
    setSaveError(null);
    setErrors((e) => {
      if (!(k in e)) return e;
      const n = { ...e };
      delete n[k as keyof Errors];
      return n;
    });
  };
  const setP = (k: keyof PrinterText, v: string) => {
    setForm((f) => ({ ...f, printer: { ...f.printer, [k]: v } }));
    setDirty(true);
    setSaveError(null);
    setErrors((e) => {
      if (!(k in e)) return e;
      const n = { ...e };
      delete n[k];
      return n;
    });
  };

  const prefill = (value: string) => {
    setPre(value);
    setDirty(true);
    setErrors({});
    setSaveError(null);
    if (!value || catalog === "failed" || !catalog) {
      setForm(formFrom(null, presetProcess));
      setBaseCap({});
      return;
    }
    const t = catalog[Number(value)];
    if (!t) return;
    setForm(formFrom(t));
    setBaseCap((t.capabilities ?? {}) as Record<string, unknown>);
  };

  const dismiss = () => {
    if (busy) return;
    if (dirty) setDiscard(true);
    else onClose();
  };

  const turning = form.process === LATHE;
  const shown = printerFieldsFor(form.process);

  const save = async () => {
    const nums = parseMachineNumbers({
      count: form.count,
      rate: form.rate,
      maxKg: form.kg,
      x: form.x,
      y: form.y,
      z: form.z,
      swing: form.swing,
      between: form.between,
      isTurning: turning,
    });
    const capital = parseCapitalPercent(form.capital);
    const printer = parsePrinterDetails(form.printer, form.process);
    const errs: Errors = {};
    if (!nums.ok) {
      const e = nums.errors;
      if (e.count) errs.count = "Whole number, 1 or more.";
      if (e.rate) errs.rate = e.rate;
      if (e.maxKg) errs.kg = e.maxKg.replace("Max workpiece", "Heaviest part");
      for (const k of (turning ? ["swing", "between"] : ["x", "y", "z"]) as ("x" | "y" | "z" | "swing" | "between")[]) {
        if (e[k]) errs[k] = e[k];
      }
    }
    if (capital.error) errs.capital = capital.error;
    if (!printer.ok) Object.assign(errs, printer.errors);
    if (Object.keys(errs).length || !nums.ok || !printer.ok) {
      setErrors(errs);
      setSaveError("Correct the highlighted fields. Nothing was saved.");
      return;
    }
    const cap = mergePrinterCapabilities(mergeMachineCapabilities(baseCap, nums.value.capabilities, turning), printer.value, form.process);
    const body: MachineInput = {
      name: form.name.trim() || null,
      process: form.process,
      count: nums.value.count,
      hourly_rate_usd: nums.value.rate,
      max_workpiece_kg: nums.value.maxKg,
      capital_frac: capital.value,
      materials: form.mats.trim() ? form.mats.split(",").map((s) => s.trim()).filter(Boolean) : null,
      capabilities: Object.keys(cap).length ? cap : null,
      notes: form.notes.trim() || null,
    };
    setBusy(true);
    setSaveError(null);
    try {
      const saved = editing ? await updateMachine(machine.id, body) : await createMachine(body);
      onSaved(saved, editing ? "edit" : "add");
    } catch (e) {
      setSaveError(`${e instanceof Error ? e.message : "Couldn't save."} Your entries are still here.`);
      setBusy(false);
    }
  };

  const err = (k: keyof Errors) =>
    errors[k] ? (
      <span className="err" id={`${ids}-${k}`}>
        {errors[k]}
      </span>
    ) : null;
  const inv = (k: keyof Errors) => (errors[k] ? { "aria-invalid": true as const, "aria-describedby": `${ids}-${k}` } : {});

  const stockLabel = form.process === "fdm" ? "Filament in stock" : "Resin in stock";

  return (
    <Dialog
      title={editing ? `Edit ${machineName(machine)}` : "Add machine"}
      onDismiss={dismiss}
      onClose={() => !busy && onClose()}
      footer={
        <>
          <button className="btn ink" type="button" onClick={save} disabled={busy}>
            {busy ? "Saving…" : editing ? "Save changes" : "Add machine"}
          </button>
          <button className="btn" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <span className="fh" style={{ marginLeft: "auto" }}>
            Esc closes
          </span>
        </>
      }
    >
      {!editing ? (
        catalog === "failed" ? (
          <p className="fh" style={{ margin: 0 }}>
            The catalog didn&apos;t load. Fill in the form by hand.
          </p>
        ) : (
          <label className="field">
            Start from a catalog model
            <select aria-label="Start from a catalog model" value={pre} onChange={(e) => prefill(e.target.value)} disabled={catalog == null} aria-describedby={`${ids}-pre`}>
              <option value="">{catalog == null ? "Loading the catalog…" : "Blank"}</option>
              {(catalog ?? []).map((t, i) => (
                <option key={`${t.name}-${i}`} value={String(i)}>
                  {t.name || procName(t.process)} · {procName(t.process)}
                </option>
              ))}
            </select>
            <span className="fh" id={`${ids}-pre`}>
              Fills the form; every value stays editable. Choosing Blank clears it.
            </span>
          </label>
        )
      ) : null}
      <div className="g2">
        <label className="field">
          Name
          <input type="text" value={form.name} placeholder="Haas VF-2" onChange={(e) => set("name", e.target.value)} />
        </label>
        <label className="field">
          Method
          <select aria-label="Method" value={form.process} onChange={(e) => set("process", e.target.value)}>
            {PROCS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          How many
          <input type="text" inputMode="numeric" value={form.count} onChange={(e) => set("count", e.target.value)} {...inv("count")} />
          {err("count")}
        </label>
        <label className="field">
          Hourly rate (USD)
          <input type="text" inputMode="decimal" value={form.rate} placeholder="95" onChange={(e) => set("rate", e.target.value)} {...inv("rate")} />
          {err("rate")}
        </label>
      </div>
      {turning ? (
        <div className="g2">
          <label className="field">
            Swing diameter (mm)
            <input type="text" inputMode="decimal" value={form.swing} onChange={(e) => set("swing", e.target.value)} {...inv("swing")} />
            {err("swing")}
          </label>
          <label className="field">
            Between centers (mm)
            <input type="text" inputMode="decimal" value={form.between} onChange={(e) => set("between", e.target.value)} {...inv("between")} />
            {err("between")}
          </label>
        </div>
      ) : (
        <div className="g3">
          <label className="field">
            Work area X (mm)
            <input type="text" inputMode="decimal" value={form.x} onChange={(e) => set("x", e.target.value)} {...inv("x")} />
            {err("x")}
          </label>
          <label className="field">
            Y (mm)
            <input type="text" inputMode="decimal" aria-label="Work area Y (mm)" value={form.y} onChange={(e) => set("y", e.target.value)} {...inv("y")} />
            {err("y")}
          </label>
          <label className="field">
            Z (mm)
            <input type="text" inputMode="decimal" aria-label="Work area Z (mm)" value={form.z} onChange={(e) => set("z", e.target.value)} {...inv("z")} />
            {err("z")}
          </label>
        </div>
      )}
      <div className="g2">
        <label className="field">
          Heaviest part (kg)
          <input
            type="text"
            inputMode="decimal"
            value={form.kg}
            onChange={(e) => set("kg", e.target.value)}
            {...inv("kg")}
            aria-describedby={errors.kg ? `${ids}-kg` : `${ids}-kgh`}
          />
          {err("kg")}
          <span className="fh" id={`${ids}-kgh`}>
            Needed for a yes or no on fit.
          </span>
        </label>
        <label className="field">
          <span>
            Capital fraction (%)<span className="new">New</span>
          </span>
          <input
            type="text"
            inputMode="decimal"
            aria-label="Capital fraction (%)"
            value={form.capital}
            placeholder="35% default"
            onChange={(e) => set("capital", e.target.value)}
            {...inv("capital")}
            aria-describedby={errors.capital ? `${ids}-capital` : `${ids}-caph`}
          />
          {err("capital")}
          <span className="fh" id={`${ids}-caph`}>
            Share of the rate that pays for the machine. Left out of in-house cost for owned machines.
          </span>
        </label>
        <label className="field full">
          Materials
          <input type="text" value={form.mats} placeholder="6061, 316L, PP" onChange={(e) => set("mats", e.target.value)} aria-describedby={`${ids}-math`} />
          <span className="fh" id={`${ids}-math`}>
            Comma-separated: a class (aluminum, steel, stainless, titanium, polymer), a grade (6061-T6 Aluminum, SS316L) or a shorthand (6061, 7075, 304, 316L,
            PP, 4130, 4140).
          </span>
        </label>
      </div>
      {shown.any ? (
        <div className="g2 pbox" role="group" aria-labelledby={`${ids}-prn`}>
          <span className="full" id={`${ids}-prn`} style={{ fontWeight: 600, fontSize: 13.5 }}>
            Printer<span className="new">New</span>
          </span>
          {shown.nozzle ? (
            <label className="field">
              Nozzle diameter (mm)
              <input type="text" inputMode="decimal" value={form.printer.nozzle} placeholder="0.4" onChange={(e) => setP("nozzle", e.target.value)} {...inv("nozzle")} aria-describedby={errors.nozzle ? `${ids}-nozzle` : `${ids}-nzh`} />
              {err("nozzle")}
              <span className="fh" id={`${ids}-nzh`}>
                A wall thinner than the nozzle fails fit on this printer.
              </span>
            </label>
          ) : null}
          {shown.enclosure ? (
            <label className="field">
              Enclosure
              <select aria-label="Enclosure" value={form.printer.enclosure} onChange={(e) => setP("enclosure", e.target.value)}>
                {ENCLOSURE_LABELS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {shown.layers ? (
            <>
              <label className="field">
                Finest layer (mm)
                <input type="text" inputMode="decimal" value={form.printer.layerMin} placeholder="0.08" onChange={(e) => setP("layerMin", e.target.value)} {...inv("layerMin")} />
                {err("layerMin")}
              </label>
              <label className="field">
                Thickest layer (mm)
                <input type="text" inputMode="decimal" value={form.printer.layerMax} placeholder="0.28" onChange={(e) => setP("layerMax", e.target.value)} {...inv("layerMax")} />
                {err("layerMax")}
              </label>
            </>
          ) : null}
          {shown.enclosure && form.printer.enclosure === "heated" ? (
            <label className="field">
              Max chamber temperature (°C)
              <input type="text" inputMode="decimal" value={form.printer.chamber} placeholder="60" onChange={(e) => setP("chamber", e.target.value)} {...inv("chamber")} />
              {err("chamber")}
            </label>
          ) : null}
          {shown.stocked ? (
            <label className="field full">
              {stockLabel}
              <input type="text" value={form.printer.stocked} placeholder={form.process === "fdm" ? "PETG, PLA, ABS" : "Standard Resin, Tough Resin"} onChange={(e) => setP("stocked", e.target.value)} aria-describedby={`${ids}-stk`} />
              <span className="fh" id={`${ids}-stk`}>
                Comma-separated material names from the registry, or a class. Shown on the printer; fit uses Materials.
              </span>
            </label>
          ) : null}
        </div>
      ) : null}
      <label className="field">
        Notes
        <textarea rows={2} value={form.notes} placeholder="Throughput, fixturing, secondary ops" onChange={(e) => set("notes", e.target.value)} />
      </label>
      <span className="fh">Only the fields shown are checked when you save. Saving marks older decisions for re-costing.</span>
      {saveError ? (
        <p className="err" role="alert" style={{ margin: 0, fontSize: 13 }}>
          {saveError}
        </p>
      ) : null}
      {discard ? (
        <div className="confirm" role="alertdialog" aria-label="Discard changes" style={{ margin: 0 }}>
          <b>Discard changes?</b>
          <span className="bx">
            <button className="btn danger sm" type="button" onClick={onClose}>
              Discard
            </button>
            <button className="btn sm" type="button" ref={discardRef} onClick={() => setDiscard(false)}>
              Keep editing
            </button>
          </span>
        </div>
      ) : null}
    </Dialog>
  );
}
