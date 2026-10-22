"use client";

/** "At the machine": the sizes, setups, stock and machine an operator sets the job up from (me-16). */
import * as React from "react";
import { usePart } from "./ctx";
import { factLine, factRows, machineFacts, type MachineFacts } from "./at-machine";
import { enginePick, pairAt } from "./choice";
import { methodName } from "./model";
import { normalizeSpecs, toleranceText } from "./specs";
import { inText } from "../units/units";
import { useUnits } from "../units/use-units";

/** The part's facts at the machine the page's answer is on (the in-house pick, else ScaleCAD's pick). */
export function useMachineFacts(): MachineFacts | null {
  const p = usePart();
  return React.useMemo(() => {
    const v = p.data.validation;
    const cost = p.data.cost;
    if (!v && !cost) return null;
    const pair = pairAt(cost, p.q);
    const pick = enginePick(cost, p.q);
    const proc = pair?.in_house.process ?? pick?.process ?? null;
    const estimate = proc ? p.methods.find((m) => m.code === proc)?.prices.get(p.q) ?? null : null;
    const machine = pair
      ? `${pair.in_house.machine ?? methodName(pair.in_house.process)}, in-house (${methodName(pair.in_house.process).toLowerCase()})`
      : pick
        ? `${methodName(pick.process)}, ${pick.inHouse && pick.machine ? `on your ${pick.machine}` : "outside"}`
        : null;
    const rot = cost?.routing?.drivers?.rotational;
    return machineFacts({
      features: v?.features ?? null,
      size: v?.geometry.bounding_box_mm ?? cost?.geometry.bbox_mm ?? null,
      rotational: typeof rot === "boolean" ? rot : null,
      estimate,
      machine,
      tolerance: toleranceText(normalizeSpecs(p.data.context?.part_specs ?? null)?.general_tolerance),
    });
  }, [p.data.validation, p.data.cost, p.data.context, p.methods, p.q]);
}

export function AtMachine() {
  const facts = useMachineFacts();
  const { unit } = useUnits();
  const [open, setOpen] = React.useState(false);
  if (!facts) return null;
  const line = factLine(facts);
  return (
    <>
      <div className="gh" style={{ marginTop: 6 }}>
        <span>At the machine</span>
        <span>
          <button className="btn sm ghost" type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} style={{ height: 24 }}>
            {open ? "Hide" : "Show"}
          </button>
        </span>
      </div>
      {open ? (
        <div className="swap" style={{ margin: "0 12px", display: "flex", flexDirection: "column", gap: 6, fontSize: 13, color: "var(--ink2)" }}>
          <div className="kv" style={{ padding: 0 }}>
            {factRows(facts).map((r, i) => (
              <React.Fragment key={i}>
                <span>{r.k}</span>
                <b className="num">{inText(r.v, unit)}</b>
              </React.Fragment>
            ))}
          </div>
          <span style={{ color: "var(--ink3)" }}>Sizes are measured from the file. The setups are ScaleCAD’s plan from the measured steps, not a CAM program.</span>
        </div>
      ) : line ? (
        <p style={{ margin: "0 12px", fontSize: 13, color: "var(--ink2)" }} className="num">
          {inText(line, unit)}
        </p>
      ) : null}
    </>
  );
}
