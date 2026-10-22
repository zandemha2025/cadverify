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
import { readSchedule, scheduleFields, scheduleText, type ScheduleText } from "./machine-hours";
import {
  KG_PER_LB,
  PRESS_BRAKE,
  SHEET,
  SHEET_CLASSES,
  SHEET_KINDS,
  T_PER_US_TON,
  backToBase,
  forceIn,
  forceUnit,
  mergeSheetCapabilities,
  parsePositive,
  sheetKindOf,
  thickMapToSave,
  thickRowsFrom,
  weightIn,
  weightUnit,
  type ThickText,
} from "./machine-kinds";

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
  /** A press brake's bend length, a cutter's bed (mm until shown). */
  bend: string;
  bedX: string;
  bedY: string;
  /** What a sheet-metal machine is ("" on an older one that never said). */
  sheetKind: string;
  /** Press force (metric t until shown). */
  tons: string;
  /** Heaviest part (kg until shown). */
  kg: string;
  /** Thickest sheet by material class (mm until shown). */
  thick: ThickText;
  capital: string;
  mats: string;
  notes: string;
  printer: PrinterText;
  /** Hours available a year (op-13): blank is the default, said as assumed. */
  hours: ScheduleText;
};

type Errors = Partial<Record<string, string>>;

function formFrom(m: Partial<MachineInput> | null, process = "cnc_3axis"): Form {
  const cap = (m?.capabilities ?? {}) as Record<string, unknown>;
  const env = envelopeFieldsFrom(cap);
  return {
    name: m?.name ?? "",
    process: m?.process ?? process,
    count: m?.count != null ? String(m.count) : "1",
    rate: m?.hourly_rate_usd != null ? String(m.hourly_rate_usd) : "",
    ...env,
    bend: typeof cap.max_bend_length_mm === "number" ? String(cap.max_bend_length_mm) : "",
    bedX: typeof cap.bed_x === "number" ? String(cap.bed_x) : "",
    bedY: typeof cap.bed_y === "number" ? String(cap.bed_y) : "",
    // A new sheet-metal machine starts as a press brake; an older one that never said keeps its work area.
    sheetKind: sheetKindOf(cap) ?? ((m?.process ?? process) === SHEET && !("x" in cap) ? PRESS_BRAKE : ""),
    tons: typeof cap.tonnage_t === "number" ? String(cap.tonnage_t) : "",
    kg: m?.max_workpiece_kg != null ? String(m.max_workpiece_kg) : "",
    thick: thickRowsFrom((m?.material_thickness_map ?? null) as Record<string, unknown> | null, "mm"),
    capital: capitalPercentText(m?.capital_frac),
    mats: m?.materials?.join(", ") ?? "",
    notes: m?.notes ?? "",
    printer: printerFieldsFrom(cap),
    hours: scheduleFields((m as { schedule?: MachineInput["schedule"] } | null)?.schedule ?? null),
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

type Base = { mm: Record<SizeField, string>; shown: Record<SizeField, string>; kg: [string, string]; tons: [string, string]; thick: ThickText };

/**
 * The form with its sizes, weight and press force in the person's units (in, lb
 * and US tons, or mm, kg and t), and what they were: the API and engine keep mm,
 * kg and t, and a value the person doesn't touch saves exactly as it was.
 */
function shownForm(f: Form, unit: LengthUnit, thickMap: Record<string, unknown> | null): { form: Form; base: Base } {
  const mm = sizesOf(f);
  const shown = sizeFieldsIn(mm, unit);
  const kg = f.kg.trim() ? weightIn(Number(f.kg), unit) : "";
  const tons = f.tons.trim() ? forceIn(Number(f.tons), unit) : "";
  const thick = thickRowsFrom(thickMap, unit);
  return { form: { ...f, ...shown, kg, tons, thick }, base: { mm, shown, kg: [f.kg, kg], tons: [f.tons, tons], thick } };
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
  const [init] = React.useState(() => shownForm(formFrom(editing ? machine : null, presetProcess), unit, editing ? machine.material_thickness_map : null));
  const [form, setForm] = React.useState<Form>(init.form);
  const sizeBase = React.useRef(init.base);
  // The thickness map the form's three rows sit in: the machine being edited, or the catalog template.
  const thickBase = React.useRef<Record<string, unknown> | null>(editing ? machine.material_thickness_map : null);
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
  const setProcess = (v: string) => {
    set("process", v);
    // A sheet-metal machine says what it is; one with no older work area starts as a press brake.
    if (v === SHEET && !form.sheetKind && !("x" in baseCap)) set("sheetKind", PRESS_BRAKE);
  };
  const setThick = (k: string, v: string) => {
    setForm((f) => ({ ...f, thick: { ...f.thick, [k]: v } }));
    setDirty(true);
    setSaveError(null);
    setErrors((e) => {
      if (!(`thick_${k}` in e)) return e;
      const n = { ...e };
      delete n[`thick_${k}`];
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
    const reset = (f: Form, thickMap: Record<string, unknown> | null) => {
      const next = shownForm(f, unit, thickMap);
      sizeBase.current = next.base;
      thickBase.current = thickMap;
      setForm(next.form);
    };
    if (!value || catalog === "failed" || !catalog) {
      reset(formFrom(null, presetProcess), null);
      setBaseCap({});
      return;
    }
    const t = catalog[Number(value)];
    if (!t) return;
    reset(formFrom(t), (t.material_thickness_map ?? null) as Record<string, unknown> | null);
    setBaseCap((t.capabilities ?? {}) as Record<string, unknown>);
  };

  const dismiss = () => {
    if (busy) return;
    if (dirty) setDiscard(true);
    else onClose();
  };

  const turning = form.process === LATHE;
  const sheet = form.process === SHEET;
  const kind = sheet ? form.sheetKind || null : null;
  const brake = kind === PRESS_BRAKE;
  const shown = printerFieldsFor(form.process);

  const save = async () => {
    // Sizes go to the API in mm, whatever unit they were typed in.
    const mm = sizeFieldsToMm(sizesOf(form), sizeBase.current.shown, sizeBase.current.mm, unit);
    // Weight and press force go in kg and metric t, whatever they were typed in (lb, US tons).
    const kgBase = backToBase(form.kg, sizeBase.current.kg[1], sizeBase.current.kg[0], unit === "in" ? KG_PER_LB : 1);
    const tonsBase = backToBase(form.tons, sizeBase.current.tons[1], sizeBase.current.tons[0], unit === "in" ? T_PER_US_TON : 1);
    const box = !turning && !kind;
    const nums = parseMachineNumbers({
      count: form.count,
      rate: form.rate,
      maxKg: kgBase,
      x: box ? mm.x : "",
      y: box ? mm.y : "",
      z: box ? mm.z : "",
      swing: mm.swing,
      between: mm.between,
      isTurning: turning,
    });
    const bend = brake ? parsePositive(mm.bend, "Bend length") : { value: null };
    const tons = brake ? parsePositive(tonsBase, "Press force") : { value: null };
    const bedX = kind && !brake ? parsePositive(mm.bedX, "Bed X") : { value: null };
    const bedY = kind && !brake ? parsePositive(mm.bedY, "Bed Y") : { value: null };
    const thick = sheet ? thickMapToSave(thickBase.current, form.thick, sizeBase.current.thick, unit) : null;
    const capital = parseCapitalPercent(form.capital);
    const printer = parsePrinterDetails(form.printer, form.process);
    const sched = readSchedule(form.hours);
    const errs: Errors = {};
    for (const [k, v] of Object.entries(sched.errors)) errs[`hours_${k}`] = v;
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
    if (bend.error) errs.bend = bend.error;
    if (tons.error) errs.tons = tons.error;
    if (bedX.error) errs.bedX = bedX.error;
    if (bedY.error) errs.bedY = bedY.error;
    for (const [k, v] of Object.entries(thick?.errors ?? {})) errs[`thick_${k}`] = v;
    if (Object.keys(errs).length || !nums.ok || !printer.ok) {
      setErrors(errs);
      setSaveError("Correct the highlighted fields. Nothing was saved.");
      return;
    }
    const cap = mergeSheetCapabilities(
      mergePrinterCapabilities(mergeMachineCapabilities(baseCap, nums.value.capabilities, turning), printer.value, form.process),
      kind,
      { bend: bend.value, tonnage: tons.value, bedX: bedX.value, bedY: bedY.value },
    );
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
      schedule: sched.value,
      ...(thick ? { material_thickness_map: thick.map } : {}),
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
  // A refused material is said at the Materials field itself, not only at the foot of the form.
  const matErr = saveError && /material/i.test(saveError) && !/thickness/i.test(saveError) ? saveError.replace(/ Your entries are still here\.$/, "") : null;

  return (
    <Dialog
      title={editing ? `Edit ${machineName(machine)}` : "Add machine"}
      onDismiss={dismiss}
      onClose={() => !busy && onClose()}
      footer={
        <>
          {/* me-01: the refusal sat under Notes, below the fold, so a save looked like nothing happened. */}
          {saveError ? (
            <p className="err" role="alert" style={{ margin: 0, fontSize: 13, flexBasis: "100%" }}>
              {saveError}
            </p>
          ) : null}
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
          <select aria-label="Process" value={form.process} onChange={(e) => setProcess(e.target.value)}>
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
      {sheet ? (
        <div className={kind ? "g3 stack" : "g2"}>
          <label className="field">
            Machine
            <select aria-label="Machine" value={form.sheetKind} onChange={(e) => set("sheetKind", e.target.value)} aria-describedby={`${ids}-kindh`}>
              {!form.sheetKind ? <option value="">Not said (work area X × Y × Z)</option> : null}
              {SHEET_KINDS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            <span className="fh" id={`${ids}-kindh`}>
              {brake ? "Bends the blank. Fit checks bend length, press force and the thickest sheet below." : kind ? "Cuts the blank. Fit checks the bed and the thickest sheet below." : "Say what it is to have fit check what decides it."}
            </span>
          </label>
          {brake ? (
            <>
              <label className="field">
                Bend length ({unit})
                <input aria-label={`Bend length (${unit})`} type="text" inputMode="decimal" value={form.bend} placeholder={unit === "in" ? "120" : "3048"} onChange={(e) => set("bend", e.target.value)} {...inv("bend")} />
                {err("bend")}
              </label>
              <label className="field">
                Press force ({forceUnit(unit)})
                <input aria-label={`Press force (${forceUnit(unit)})`} type="text" inputMode="decimal" value={form.tons} placeholder={unit === "in" ? "110" : "100"} onChange={(e) => set("tons", e.target.value)} {...inv("tons")} />
                {err("tons")}
              </label>
            </>
          ) : kind ? (
            <>
              <label className="field">
                Bed X ({unit})
                <input aria-label={`Bed X (${unit})`} type="text" inputMode="decimal" value={form.bedX} onChange={(e) => set("bedX", e.target.value)} {...inv("bedX")} />
                {err("bedX")}
              </label>
              <label className="field">
                Bed Y ({unit})
                <input aria-label={`Bed Y (${unit})`} type="text" inputMode="decimal" value={form.bedY} onChange={(e) => set("bedY", e.target.value)} {...inv("bedY")} />
                {err("bedY")}
              </label>
            </>
          ) : null}
        </div>
      ) : null}
      {sheet ? (
        <div className="g3" role="group" aria-labelledby={`${ids}-thk`}>
          <span className="full" id={`${ids}-thk`} style={{ fontWeight: 600, fontSize: 13.5, gridColumn: "1 / -1" }}>
            Thickest sheet it {brake ? "bends" : "cuts"} ({unit})
          </span>
          {SHEET_CLASSES.map(([k, label]) => (
            <label className="field" key={k}>
              {label}
              <input aria-label={`Thickest ${label.toLowerCase()} sheet (${unit})`} type="text" inputMode="decimal" value={form.thick[k] ?? ""} onChange={(e) => setThick(k, e.target.value)} {...inv(`thick_${k}`)} />
              {err(`thick_${k}`)}
            </label>
          ))}
        </div>
      ) : null}
      {sheet && kind ? null : turning ? (
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
          Heaviest part ({weightUnit(unit)})
          <input aria-label={`Heaviest part (${weightUnit(unit)})`}
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
            aria-describedby={matErr ? `${ids}-materr` : `${ids}-math`}
            aria-invalid={matErr ? true : undefined}
          />
          {matErr ? (
            <span className="err" id={`${ids}-materr`}>
              {matErr}
            </span>
          ) : null}
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
      <div className="g3" role="group" aria-labelledby={`${ids}-hrs`}>
        <span className="field" id={`${ids}-hrs`} style={{ gridColumn: "1 / -1", marginBottom: -6 }}>
          Hours available a year
        </span>
        {(
          [
            ["shifts", "Shifts a day", "2"],
            ["hours", "Hours a shift", "8"],
            ["days", "Days a year", "240"],
          ] as const
        ).map(([k, label, ph]) => (
          <label className="field" key={k}>
            {label}
            <input
              aria-label={label}
              type="text"
              inputMode="decimal"
              value={form.hours[k]}
              placeholder={ph}
              onChange={(e) => set("hours", { ...form.hours, [k]: e.target.value })}
              {...inv(`hours_${k}`)}
            />
            {err(`hours_${k}`)}
          </label>
        ))}
        <span className="fh" style={{ gridColumn: "1 / -1" }}>
          {(() => {
            const r = readSchedule(form.hours);
            const n = Number.parseInt(form.count, 10);
            return Object.keys(r.errors).length
              ? "Machine load compares the hours your make parts need with these."
              : `${scheduleText(Number.isFinite(n) && n > 0 ? n : 1, r.value)}. Machine load compares the hours your make parts need with these; it changes no price or fit.`;
          })()}
        </span>
      </div>
      <label className="field">
        Notes
        <textarea aria-label="Notes" rows={2} value={form.notes} placeholder="Throughput, fixturing, secondary ops" onChange={(e) => set("notes", e.target.value)} />
      </label>
      <span className="fh">Only the fields shown are checked when you save. A change to anything but its hours and notes marks older decisions for re-costing.</span>
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
