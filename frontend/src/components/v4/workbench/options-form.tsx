"use client";

/**
 * The costing options (quantities, material class, region, CAD source units,
 * complexity, mold cavities): the Summary's "Adjust inputs", which re-costs the
 * part with them. A new part comes in through Check a part.
 */
import * as React from "react";
import { cavProblem, qtyProblem, type FormDraft } from "./derive";
import { COMPLEXITY_OPTIONS, MATERIAL_OPTIONS, REGION_OPTIONS } from "./words";

export function OptionsForm({
  form,
  setForm,
  unitsEnabled,
  unitsHint,
  idp,
  disabled,
}: {
  form: FormDraft;
  setForm: (f: FormDraft) => void;
  unitsEnabled: boolean;
  unitsHint: string;
  idp: string;
  disabled?: boolean;
}) {
  const qBad = qtyProblem(form.qty);
  const cBad = cavProblem(form.cav);
  const up = (k: keyof FormDraft) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <>
      <label className="field full">
        Quantities
        <input type="text" inputMode="numeric" value={form.qty} onChange={up("qty")} aria-invalid={!!qBad} aria-describedby={`${idp}-q`} disabled={disabled} />
        <span className={qBad ? "fe" : "fh"} id={`${idp}-q`}>
          {qBad ?? "Costed at each. The slider estimates between them."}
        </span>
      </label>
      <label className="field">
        Material class
        <select value={form.mat} onChange={up("mat")} disabled={disabled}>
          {MATERIAL_OPTIONS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        Region
        <select value={form.reg} onChange={up("reg")} disabled={disabled}>
          {REGION_OPTIONS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        CAD source units
        <select value={form.units} onChange={up("units")} disabled={disabled || !unitsEnabled} aria-describedby={`${idp}-u`}>
          <option value="mm">Millimeters</option>
          <option value="inch">Inches</option>
        </select>
        <span className="fh" id={`${idp}-u`}>
          {unitsHint}
        </span>
      </label>
      <label className="field">
        Complexity
        <select value={form.cx} onChange={up("cx")} disabled={disabled} aria-describedby={`${idp}-c`}>
          {COMPLEXITY_OPTIONS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <span className="fh" id={`${idp}-c`}>
          Tooling routes only
        </span>
      </label>
      <label className="field">
        Mold cavities
        <input type="number" min={1} step={1} value={form.cav} onChange={up("cav")} aria-invalid={!!cBad} aria-describedby={`${idp}-v`} disabled={disabled} />
        <span className={cBad ? "fe" : "fh"} id={`${idp}-v`}>
          {cBad ?? "Molds and dies only"}
        </span>
      </label>
    </>
  );
}
