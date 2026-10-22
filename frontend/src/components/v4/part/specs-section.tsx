"use client";

/**
 * Specs on the Conditions view: surface finish (named finishes and Ra), heat
 * treatment, inspection, and the certifications whoever makes the part must
 * hold. Saved with the part (part_contexts.part_specs); the engine prices each
 * op, rules out the routes that can't deliver them, and checks your shop's
 * declared capabilities for in-house. A run only reads the saved specs; the
 * page says when the shown prices used different ones.
 */
import * as React from "react";
import "./specs.css";
import { ConfirmButton, cx } from "../ui";
import { usePart } from "./ctx";
import { recheckingLabel, useStoredRecheck } from "./recheck-state";
import { costLines, methodName, money, qtyWord } from "./model";
import {
  CERTIFICATIONS,
  FINISHES,
  HEAT_TREATMENTS,
  INSPECTIONS,
  ISO_2768,
  NADCAP_PROCESSES,
  derivedNadcap,
  draftFrom,
  hasSpecs,
  mustHold,
  normalizeSpecs,
  sameSpecs,
  specExclusions,
  specLines,
  specsChangedSinceRun,
  specsFromDraft,
  toggle,
  type SpecsDraft,
} from "./specs";
import { savePartSpecs } from "./specs-api";
import { ReadOnlyLine, useReadOnly } from "../read-only";
import { useUnits } from "../units/use-units";

function Pick({ label, options, values, onToggle, derived }: { label: string; options: [string, string][]; values: string[]; onToggle: (v: string) => void; derived?: string[] }) {
  return (
    <div className="pickset" role="group" aria-label={label}>
      <span className="lab">{label}</span>
      {options.map(([k, name]) => {
        const auto = !values.includes(k) && !!derived?.includes(k);
        const on = values.includes(k) || auto;
        return (
          <button key={k} type="button" aria-pressed={on} onClick={() => onToggle(k)} title={auto ? "From the declared finish or heat treatment" : undefined}>
            {name}
            {auto ? <span className="from">from the specs</span> : null}
          </button>
        );
      })}
    </div>
  );
}

export function SpecsSection() {
  const p = usePart();
  const { unit } = useUnits();
  const key = p.data.key;
  const stored = React.useMemo(() => normalizeSpecs(p.data.context?.part_specs ?? null), [p.data.context]);
  const storedDraft = React.useMemo(() => draftFrom(stored), [stored]);
  const [draft, setDraft] = React.useState<SpecsDraft>(storedDraft);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  React.useEffect(() => setDraft(storedDraft), [storedDraft]);
  const parsed = specsFromDraft(draft);
  const dirty = !sameSpecs(parsed.specs, stored) || (!!draft.ra.trim() && !!parsed.errors.length);
  const clearing = dirty && !hasSpecs(parsed.specs) && hasSpecs(stored);
  const stale = !!p.data.cost && specsChangedSinceRun(p.data.cost, stored);
  const exclusions = specExclusions(p.data.cost?.estimates);
  const derived = derivedNadcap(parsed.specs);
  const set = (patch: Partial<SpecsDraft>) => setDraft((d) => ({ ...d, ...patch }));
  // it-15/it-16: a viewer reads the specs; the controls are off and one line says why, never a Save that's refused.
  const ro = useReadOnly("change a part's specs");
  const roCheck = useReadOnly("re-check parts");

  const save = async () => {
    if (!key || parsed.errors.length || !dirty) return;
    setBusy(true);
    setErr(null);
    const res = await savePartSpecs(key, parsed.specs, p.data.context);
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    p.patchData({ context: res.context });
    const marked = res.markedStale ? ` · ${res.markedStale === 1 ? "1 saved record" : `${res.markedStale} saved records`} marked out of date` : "";
    p.toast({ text: (parsed.specs ? "Specs saved with this part" : "Specs cleared from this part") + marked });
  };

  // What the shown check added for the specs, on the method in view at this quantity.
  const est = p.sel?.prices.get(p.q) ?? null;
  const added = costLines(est).filter((l) => l.key.startsWith("spec_"));
  const specDays = (est?.lead_time?.components as Record<string, number> | undefined)?.specs ?? null;
  const must = mustHold(stored);
  const running = useStoredRecheck(key);

  return (
    <>
      <div className="gh">
        <span>Specs</span>
        <span>{hasSpecs(stored) ? "Saved with this part" : "Not set"}</span>
      </div>
      {stale ? (
        <div className="note" role="status" style={{ borderColor: "#E9C46A" }}>
          <b>The prices on this page used {hasSpecs(p.data.cost?.specs?.declared) ? "the previous specs" : "no specs"}</b>
          <span>Methods, prices and machine fit update when the part is checked again with the saved specs.</span>
          <span>
            {roCheck ? (
              <ReadOnlyLine line={roCheck} style={{ margin: 0 }} />
            ) : p.canRecheck ? (
              <button className="btn sm ink" type="button" disabled={!!running} aria-live="polite" onClick={() => p.recheck()}>
                {running ? recheckingLabel(running.seconds) : "Re-verify with saved specs"}
              </button>
            ) : (
              <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Drop the file on the part to re-verify it with the saved specs.</span>
            )}
          </span>
          {running ? <span style={{ color: "var(--ink2)", fontSize: 12.5 }}>{running.worker ? "On ScaleCAD’s worker, which has more time" : "From the file kept with this part"} · no check used</span> : null}
        </div>
      ) : null}
      <fieldset disabled={!!ro} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
      <Pick label="Surface finish" options={FINISHES} values={draft.finishes} onToggle={(v) => set({ finishes: toggle(draft.finishes, v, "finishes") })} />
      <div className="ra-row">
        <label className="field">
          Roughness, Ra
          <input type="text" inputMode="decimal" value={draft.ra} placeholder={draft.raUnit === "uin" ? "for example 32" : "for example 0.8"} onChange={(e) => set({ ra: e.target.value })} aria-describedby="ra-hint" />
        </label>
        <span className="seg" role="group" aria-label="Ra unit">
          {(["um", "uin"] as const).map((u) => (
            <button key={u} type="button" className={cx(draft.raUnit === u && "on")} aria-pressed={draft.raUnit === u} onClick={() => set({ raUnit: u })}>
              {u === "um" ? "µm" : "µin"}
            </button>
          ))}
        </span>
      </div>
      <p id="ra-hint" style={{ margin: "-4px 12px 6px", color: "var(--ink3)", fontSize: 12 }}>
        The roughest the part may be, on every surface. 1 µin = 0.0254 µm.
      </p>
      <Pick label="Heat treatment" options={HEAT_TREATMENTS} values={draft.heat} onToggle={(v) => set({ heat: toggle(draft.heat, v) })} />
      <Pick label="Inspection beyond standard" options={INSPECTIONS} values={draft.inspection} onToggle={(v) => set({ inspection: toggle(draft.inspection, v) })} />
      <Pick label="Whoever makes it must hold" options={CERTIFICATIONS} values={draft.certs} onToggle={(v) => set({ certs: toggle(draft.certs, v) })} />
      {draft.certs.includes("nadcap") ? (
        <Pick label="NADCAP for" options={NADCAP_PROCESSES} values={draft.nadcap} derived={derived} onToggle={(v) => set({ nadcap: toggle(draft.nadcap, v) })} />
      ) : null}
      <div className="pickset" role="group" aria-label="General tolerance">
        <span className="lab">General tolerance, where the drawing gives none</span>
        <button type="button" aria-pressed={draft.tolKind === "none"} onClick={() => set({ tolKind: "none" })}>
          Not set
        </button>
        {ISO_2768.map(([k, name]) => (
          <button key={k} type="button" aria-pressed={draft.tolKind === "iso" && draft.tolIso === k} title={`ISO 2768-1 class ${k}, ${name}`} onClick={() => set({ tolKind: "iso", tolIso: k as "f" | "m" | "c" | "v" })}>
            ISO 2768-{k}
          </button>
        ))}
        <button type="button" aria-pressed={draft.tolKind === "pm"} onClick={() => set({ tolKind: "pm", tolUnit: draft.tolValue ? draft.tolUnit : unit })}>
          ± value
        </button>
      </div>
      {draft.tolKind === "pm" ? (
        <div className="ra-row">
          <label className="field">
            General tolerance, ±
            <input type="text" inputMode="decimal" value={draft.tolValue} placeholder={draft.tolUnit === "in" ? "for example 0.005" : "for example 0.1"} onChange={(e) => set({ tolValue: e.target.value })} />
          </label>
          <span className="seg" role="group" aria-label="Tolerance unit">
            {(["mm", "in"] as const).map((u) => (
              <button key={u} type="button" className={cx(draft.tolUnit === u && "on")} aria-pressed={draft.tolUnit === u} onClick={() => set({ tolUnit: u })}>
                {u}
              </button>
            ))}
          </span>
        </div>
      ) : null}
      {draft.tolKind !== "none" ? (
        <p style={{ margin: "-4px 12px 6px", color: "var(--ink3)", fontSize: 12 }}>Goes to the supplier with the specs. The price doesn&apos;t use it.</p>
      ) : null}
      {parsed.errors.length && (draft.ra.trim() || draft.certs.includes("nadcap") || draft.tolKind === "pm") ? (
        <p role="alert" style={{ margin: "0 12px 6px", color: "var(--bad)", fontSize: 12.5 }}>
          {parsed.errors.join(" ")}
        </p>
      ) : null}
      </fieldset>
      {ro ? (
        <ReadOnlyLine line={ro} style={{ margin: "0 12px 4px" }} />
      ) : (
      <div style={{ display: "flex", gap: 8, padding: "0 12px 4px", alignItems: "center", flexWrap: "wrap" }}>
        {clearing ? (
          <ConfirmButton className="btn ink sm" label="Clear specs" question="Clear this part's saved specs?" confirmLabel="Clear" onConfirm={save} disabled={busy || !key} />
        ) : (
          <button className="btn ink sm" type="button" disabled={!dirty || busy || !key || parsed.errors.length > 0} onClick={() => void save()}>
            {busy ? "Saving…" : "Save specs"}
          </button>
        )}
        {dirty ? (
          <button className="btn sm ghost" type="button" onClick={() => setDraft(storedDraft)}>
            Undo changes
          </button>
        ) : null}
        <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{dirty ? "Not saved yet. Saving keeps them with this part; prices change when you re-check" : "No changes"}</span>
      </div>
      )}
      {err ? (
        <p role="alert" style={{ margin: "4px 12px 0", color: "var(--bad)", fontSize: 12.5 }}>
          {err}
        </p>
      ) : null}
      {hasSpecs(stored) && !dirty ? (
        <ul className="spec-sum" aria-label="Saved specs">
          {specLines(stored).map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      ) : null}
      {!stale && added.length && est ? (
        <>
          <div className="gh">
            <span>Added for the specs · {methodName(est.process)}</span>
            <span>each at {qtyWord(p.q)}</span>
          </div>
          <div className="lines">
            {added.map((l) => (
              <div key={l.key} className="ln" title={l.how}>
                <span>
                  {l.name} <span className={cx("src", l.src.kind === "yours" ? "s-yours" : "s-typ")}>{l.src.label}</span>
                </span>
                <b className="num">{money(l.value)}</b>
              </div>
            ))}
            {specDays ? (
              <div className="ln">
                <span>Lead time for the specs</span>
                <b className="num">+{specDays} days</b>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
      {!stale && exclusions.length ? (
        <>
          <div className="gh">
            <span>Ruled out by these specs</span>
            <span>{exclusions.length}</span>
          </div>
          <div className="lines">
            {exclusions.map((x) => (
              <div key={x.process} className="ln" style={{ gridTemplateColumns: "minmax(0,1fr)" }}>
                <span>
                  <b style={{ display: "block", textAlign: "left" }}>{methodName(x.process)}</b>
                  <span style={{ color: "var(--ink2)" }}>{x.reason}</span>
                </span>
              </div>
            ))}
          </div>
        </>
      ) : null}
      {must.length ? (
        <p style={{ margin: "8px 12px 0", color: "var(--ink2)", fontSize: 12.5 }}>
          Bought outside, the supplier must hold {must.join(", ")}. It goes in the RFQ package. In-house, your shop is checked against what it declared on Your shop.
        </p>
      ) : null}
    </>
  );
}
