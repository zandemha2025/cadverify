"use client";

/**
 * What the shop declares about the ops part specs ask for: finishing, heat
 * treatment and inspection done in-house or sent out, and the certifications it
 * holds. Not said is unknown, never "no": a part that needs one can't be
 * confirmed in-house until it's declared. Sent out isn't a gap: the part is made
 * on your machine and that step is bought outside (priced as an outside service).
 */
import * as React from "react";
import { cx } from "../ui";

export const SPEC_OPS: { group: string; kind: "op" | "cert"; items: [string, string][] }[] = [
  {
    group: "Finishing",
    kind: "op",
    items: [
      ["bead_blast", "Bead blast"],
      ["anodize_ii", "Anodize, Type II"],
      ["anodize_iii", "Hard anodize, Type III"],
      ["passivate", "Passivation"],
      ["electropolish", "Electropolish"],
      ["powder_coat", "Powder coat"],
      ["plating", "Plating"],
    ],
  },
  {
    group: "Heat treatment",
    kind: "op",
    items: [
      ["solution_age", "Solution treat and age"],
      ["quench_temper", "Quench and temper"],
      ["case_harden", "Case hardening"],
    ],
  },
  {
    group: "Inspection",
    kind: "op",
    items: [
      ["fai_as9102", "First article, AS9102"],
      ["cmm_report", "CMM report"],
      ["full_100", "100% inspection"],
    ],
  },
  {
    group: "Certifications your shop holds",
    kind: "cert",
    items: [
      ["as9100", "AS9100"],
      ["iso9001", "ISO 9001"],
      ["itar", "ITAR registration"],
      ["nadcap_chemical_processing", "NADCAP, chemical processing"],
      ["nadcap_heat_treating", "NADCAP, heat treating"],
      ["nadcap_nondestructive_testing", "NADCAP, nondestructive testing"],
      ["nadcap_coatings", "NADCAP, coatings"],
      ["nadcap_welding", "NADCAP, welding"],
      ["nadcap_measurement_inspection", "NADCAP, measurement and inspection"],
    ],
  },
];

type Tri = true | false | undefined;

export function triOf(ops: Record<string, unknown> | null, key: string): Tri {
  const v = ops?.[key];
  if (v === false) return false;
  if (v === true || (typeof v === "object" && v !== null)) return true;
  return undefined;
}

/** How many of these the shop has declared either way. */
export function declaredCount(ops: Record<string, unknown> | null): number {
  return SPEC_OPS.flatMap((g) => g.items).filter(([k]) => triOf(ops, k) !== undefined).length;
}

export function SpecCaps({ ops, saving, onSet }: { ops: Record<string, unknown> | null; saving: string | null; onSet: (key: string, value: Tri, label: string) => void }) {
  const n = declaredCount(ops);
  return (
    <details className="speccaps" style={{ margin: "0 16px 12px" }}>
      <summary style={{ cursor: "pointer", fontSize: 13.5, fontWeight: 600 }}>
        Finishing, heat treatment, inspection and certifications <span style={{ color: "var(--ink3)", fontWeight: 500 }}>· {n ? `${n} declared` : "none declared"}</span>
      </summary>
      <p className="fh" style={{ margin: "6px 0 8px" }}>
        Parts whose specs need one of these are checked against what you declare here. Not said stays unknown, so the part can&apos;t be confirmed in-house until you say.
      </p>
      {SPEC_OPS.map((g) => (
        <div key={g.group} role="group" aria-label={g.group} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink3)", margin: "4px 0" }}>{g.group}</div>
          {g.items.map(([key, label]) => {
            const v = triOf(ops, key);
            const choices: [Tri, string][] = g.kind === "op" ? [[true, "In-house"], [false, "Sent out"], [undefined, "Not said"]] : [[true, "Held"], [false, "Not held"], [undefined, "Not said"]];
            return (
              <div key={key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "3px 0", flexWrap: "wrap" }}>
                <span style={{ fontSize: 13 }}>{saving === key ? "Saving…" : label}</span>
                <span className="seg" role="group" aria-label={label} style={{ padding: 2 }}>
                  {choices.map(([cv, cl]) => (
                    <button
                      key={cl}
                      type="button"
                      className={cx(v === cv && "on")}
                      aria-pressed={v === cv}
                      aria-disabled={!ops || saving != null}
                      style={{ height: 24, padding: "0 9px", fontSize: 12 }}
                      onClick={() => ops && saving == null && v !== cv && onSet(key, cv, label)}
                    >
                      {cl}
                    </button>
                  ))}
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </details>
  );
}
