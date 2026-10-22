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
import { LATHE, PROCS, SIZE_FIELDS, machineName, procName, sizeFieldsIn, sizeFieldsToMm, type SizeField } from "./shop-derive";
import { useUnits } from "../units/use-units";
import type { LengthUnit } from "../units/units";
import { runningRateLine } from "./running-rate";

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

/** What a machine's method takes in Materials, as the server resolves it (machine_inventory_service._METHOD_NAMES). */
const MATERIAL_HINT: Record<string, [string, string]> = {
  fdm: ["PLA, PETG, TPU", "Comma-separated, as on the spool: PLA, PETG, ABS, Nylon, TPU, CF-Nylon, PEEK. Product names such as PLA Basic or PETG HF count as their polymer. Or the class polymer."],
  sla: ["Standard Resin, Tough Resin", "Comma-separated: Standard, Tough, Flexible, Castable or Dental Model Resin, or the class polymer."],
  dlp: ["Standard Resin, Tough Resin", "Comma-separated: Standard, Tough, Flexible, Castable or Dental Model Resin, or the class polymer."],
  sls: ["PA12, PA11", "Comma-separated: PA12, PA11, Glass-filled PA12, TPU, or the class polymer."],
  mjf: ["PA12, PP", "Comma-separated: PA12, PA11, PP, or the class polymer."],
};
const METAL_HINT: [string, string] = [
  "6061, 316L, PP",
  "Comma-separated: a class (aluminum, steel, stainless, titanium, polymer), a grade (6061-T6 Aluminum, SS316L) or a shorthand (6061, 7075, 304, 316L, PP, 4130, 4140).",
];

const ENCLOSURE_LABELS: [PrinterText["enclosure"], string][] = [
  ["", "Not declared"],
  ["none", "Open"],
  ["enclosed", "Closed, not heated"],
  ["heated", "Heated chamber"],
];

function sizesOf(f: Form): Record<SizeField, string> {
  return Object.fromEntries(SIZE_FIELDS.map((k) => [k, f[k]])) as Record<SizeField, string>;
}

/**
 * The form with its sizes in the person's unit, and what they were in mm: the
 * API and engine keep mm, and a size the person doesn't touch saves exactly as it was.
 */
function shownForm(f: Form, unit: LengthUnit): { form: Form; base: { mm: Record<SizeField, string>; shown: Record<SizeField, string> } } {
  const mm = sizesOf(f);
  const shown = sizeFieldsIn(mm, unit);
  return { form: { ...f, ...shown }, base: { mm, shown } };
}

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
  // Sizes in the person's unit (mm or in), fixed while the dialog is open.
  const { unit: liveUnit } = useUnits();
  const [unit] = React.useState<LengthUnit>(liveUnit);
  const [init] = React.useState(() => shownForm(formFrom(editing ? machine : null, presetProcess), unit));
  const [form, setForm] = React.useState<Form>(init.form);
  const sizeBase = React.useRef(init.base);
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
    const reset = (f: Form) => {
      const next = shownForm(f, unit);
      sizeBase.current = next.base;
      setForm(next.form);
    };
    if (!value || catalog === "failed" || !catalog) {
      reset(formFrom(null, presetProcess));
      setBaseCap({});
      return;
    }
    const t = catalog[Number(value)];
    if (!t) return;
    reset(formFrom(t));
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
    // Sizes go to the API in mm, whatever unit they were typed in.
    const mm = sizeFieldsToMm(sizesOf(form), sizeBase.current.shown, sizeBase.current.mm, unit);
    const nums = parseMachineNumbers({
      count: form.count,
      rate: form.rate,
      maxKg: form.kg,
      x: mm.x,
      y: mm.y,
      z: mm.z,
      swing: mm.swing,
      between: mm.between,
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
          <input aria-label="Name" type="text" value={form.name} placeholder="Haas VF-2" onChange={(e) => set("name", e.target.value)} />
        </label>
        <label className="field">
          Process
          <select aria-label="Process" value={form.process} onChange={(e) => set("process", e.target.value)}>
            {PROCS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          How many
          <input aria-label="How many" type="text" inputMode="numeric" value={form.count} onChange={(e) => set("count", e.target.value)} {...inv("count")} />
          {err("count")}
        </label>
        <label className="field">
          Hourly rate (USD)
          <input aria-label="Hourly rate (USD)" type="text" inputMode="decimal" value={form.rate} placeholder="95" onChange={(e) => set("rate", e.target.value)} {...inv("rate")} />
          {err("rate")}
        </label>
      </div>
      {turning ? (
        <div className="g2">
          <label className="field">
            Swing diameter ({unit})
            <input aria-label={`Swing diameter (${unit})`} type="text" inputMode="decimal" value={form.swing} onChange={(e) => set("swing", e.target.value)} {...inv("swing")} />
            {err("swing")}
          </label>
          <label className="field">
            Between centers ({unit})
            <input aria-label={`Between centers (${unit})`} type="text" inputMode="decimal" value={form.between} onChange={(e) => set("between", e.target.value)} {...inv("between")} />
            {err("between")}
          </label>
        </div>
      ) : (
        <div className="g3">
          <label className="field">
            Work area X ({unit})
            <input aria-label={`Work area X (${unit})`} type="text" inputMode="decimal" value={form.x} onChange={(e) => set("x", e.target.value)} {...inv("x")} />
            {err("x")}
          </label>
          <label className="field">
            Y ({unit})
            <input type="text" inputMode="decimal" aria-label={`Work area Y (${unit})`} value={form.y} onChange={(e) => set("y", e.target.value)} {...inv("y")} />
            {err("y")}
          </label>
          <label className="field">
            Z ({unit})
            <input type="text" inputMode="decimal" aria-label={`Work area Z (${unit})`} value={form.z} onChange={(e) => set("z", e.target.value)} {...inv("z")} />
            {err("z")}
          </label>
        </div>
      )}
      <div className="g2">
        <label className="field">
          Heaviest part (kg)
          <input aria-label="Heaviest part (kg)"
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
            {/* What the in-house prices will use, worked out as you type (buyer-03: $87 typed, $56.55 shown). */}
            {runningRateLine(Number(form.rate.trim()) || null, form.capital.trim() ? Number(form.capital.replace("%", "").trim()) : null) ??
              "Share of the rate that pays for the machine. Left out of in-house cost for owned machines."}
          </span>
        </label>
        <label className="field full">
          Materials
          <input
            aria-label="Materials"
            type="text"
            value={form.mats}
            placeholder={(MATERIAL_HINT[form.process] ?? METAL_HINT)[0]}
            onChange={(e) => set("mats", e.target.value)}
            aria-describedby={`${ids}-math`}
            aria-invalid={!!saveError && /material/i.test(saveError) ? true : undefined}
          />
          <span className="fh" id={`${ids}-math`}>
            {(MATERIAL_HINT[form.process] ?? METAL_HINT)[1]}
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
              <input aria-label="Nozzle diameter (mm)" type="text" inputMode="decimal" value={form.printer.nozzle} placeholder="0.4" onChange={(e) => setP("nozzle", e.target.value)} {...inv("nozzle")} aria-describedby={errors.nozzle ? `${ids}-nozzle` : `${ids}-nzh`} />
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
                <input aria-label="Finest layer (mm)" type="text" inputMode="decimal" value={form.printer.layerMin} placeholder="0.08" onChange={(e) => setP("layerMin", e.target.value)} {...inv("layerMin")} />
                {err("layerMin")}
              </label>
              <label className="field">
                Thickest layer (mm)
                <input aria-label="Thickest layer (mm)" type="text" inputMode="decimal" value={form.printer.layerMax} placeholder="0.28" onChange={(e) => setP("layerMax", e.target.value)} {...inv("layerMax")} />
                {err("layerMax")}
              </label>
            </>
          ) : null}
          {shown.enclosure && form.printer.enclosure === "heated" ? (
            <label className="field">
              Max chamber temperature (°C)
              <input aria-label="Max chamber temperature (°C)" type="text" inputMode="decimal" value={form.printer.chamber} placeholder="60" onChange={(e) => setP("chamber", e.target.value)} {...inv("chamber")} />
              {err("chamber")}
            </label>
          ) : null}
          {shown.stocked ? (
            <label className="field full">
              {stockLabel}
              <input type="text" aria-label={stockLabel} value={form.printer.stocked} placeholder={form.process === "fdm" ? "PETG, PLA, ABS" : "Standard Resin, Tough Resin"} onChange={(e) => setP("stocked", e.target.value)} aria-describedby={`${ids}-stk`} />
              <span className="fh" id={`${ids}-stk`}>
                Comma-separated material names from the registry, or a class. Shown on the printer; fit uses Materials.
              </span>
            </label>
          ) : null}
        </div>
      ) : null}
      <label className="field">
        Notes
        <textarea aria-label="Notes" rows={2} value={form.notes} placeholder="Throughput, fixturing, secondary ops" onChange={(e) => set("notes", e.target.value)} />
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
