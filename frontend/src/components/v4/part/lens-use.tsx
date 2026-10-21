"use client";

/**
 * Use: where the part lives. The service conditions stored on the part's record
 * (every API field), the material class, and what the conditions rule out. A run
 * only reads the stored conditions; only Save writes them, and the page then says
 * the shown verdict used the previous conditions until it is re-verified.
 */
import * as React from "react";
import Link from "next/link";
import {
  conditionsChangedSinceRun,
  draftFromServiceEnvironment,
  hasServiceConditions,
  saveServiceConditions,
  serviceEnvironmentFromDraft,
  storedServiceEnvironment,
  type ServiceConditionsDraft,
} from "@/lib/verify/service-conditions";
import { envStrikes, readVerification } from "@/lib/verify/verification";
import { R } from "../routes";
import { ConfirmButton, cx } from "../ui";
import { usePart } from "./ctx";
import { MATERIAL_CLASS_LABEL, cheapestAt, money, priceAt, qtyWord } from "./model";
import { RunNotice, SheetTop, type FigItem } from "./sheet-bits";

const CLASSES: [string, string][] = [
  ["polymer", "Plastic"],
  ["stainless", "Stainless steel"],
  ["aluminum", "Aluminum"],
  ["steel", "Steel"],
  ["titanium", "Titanium"],
];

function sameDraft(a: ServiceConditionsDraft, b: ServiceConditionsDraft): boolean {
  return (Object.keys(a) as (keyof ServiceConditionsDraft)[]).every((k) => String(a[k]).trim() === String(b[k]).trim());
}

export function UseLayer() {
  const p = usePart();
  const on = p.lens === "use" && !p.interrupted;
  const env = storedServiceEnvironment(p.data.context);
  const set = hasServiceConditions(env);
  const temp = env.max_temp_c != null || env.min_temp_c != null ? [env.min_temp_c != null ? `${env.min_temp_c}` : null, env.max_temp_c != null ? `${env.max_temp_c} °C` : null].filter(Boolean).join(" to ") : null;
  const medium = [env.sour_service ? "Sour gas" : null, env.corrosive ? "corrosive" : null, env.medium && !env.sour_service ? env.medium : null].filter(Boolean).join(", ");
  const tags: { x: number; y: number; k: string; v: string | null }[] = [
    { x: 120, y: 200, k: "Medium", v: medium || null },
    { x: 692, y: 196, k: "Temperature", v: temp ? (env.min_temp_c == null ? `Up to ${temp}` : temp) : null },
    { x: 110, y: 556, k: "Pressure", v: env.pressure_bar != null ? `${env.pressure_bar} bar` : null },
    { x: 702, y: 560, k: "Standard", v: env.standard ?? null },
  ];
  return (
    <div className={cx("layer", !on && "off")} style={{ inset: 0, overflow: "hidden" }} aria-hidden={!on}>
      <div className="shopdraw">
        <svg width="948" height="944" viewBox="0 0 948 944" aria-hidden="true" style={{ position: "absolute", left: 0, top: 0 }}>
          <defs>
            <radialGradient id="v4fld" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#DCE5F0" stopOpacity="0.9" />
              <stop offset="70%" stopColor="#E6ECF3" stopOpacity="0.55" />
              <stop offset="100%" stopColor="#EDEFF2" stopOpacity="0" />
            </radialGradient>
            <pattern id="v4dots" width="14" height="14" patternUnits="userSpaceOnUse">
              <circle cx="2" cy="2" r="1.1" fill="#9FB0C4" opacity="0.45" />
            </pattern>
          </defs>
          <circle cx="475" cy="374" r="268" fill="url(#v4fld)" opacity={set ? 1 : 0} />
          <circle cx="475" cy="374" r="250" fill="url(#v4dots)" opacity={set ? 0.55 : 0} />
          <circle cx="475" cy="374" r="196" fill="none" stroke="#9AA3AE" strokeWidth="1" strokeDasharray="2 5" />
          <path d="M266 236 L336 268 M690 232 L612 268 M262 552 L336 500 M698 560 L612 500" stroke="#9AA3AE" strokeWidth="1" />
        </svg>
        {tags.map((t) => (
          <div key={t.k} className={cx("tag", !t.v && "unset")} style={{ left: t.x, top: t.y }}>
            <b>{t.v ?? "Not set"}</b>
            {t.k}
          </div>
        ))}
      </div>
    </div>
  );
}

export function UseSheet() {
  const p = usePart();
  const key = p.data.key;
  const stored = React.useMemo(() => storedServiceEnvironment(p.data.context), [p.data.context]);
  const storedDraft = React.useMemo(() => draftFromServiceEnvironment(stored), [stored]);
  const [draft, setDraft] = React.useState<ServiceConditionsDraft>(storedDraft);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [pendMat, setPendMat] = React.useState<string | null>(null);
  const radios = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => setDraft(storedDraft), [storedDraft]);
  const parsed = serviceEnvironmentFromDraft(draft);
  const dirty = !sameDraft(draft, storedDraft);
  const runEnv = p.data.runEnvironment ?? stored;
  const stale = !!p.data.cost && conditionsChangedSinceRun(runEnv, p.data.context);
  const clearing = dirty && !hasServiceConditions(parsed.env) && hasServiceConditions(stored);
  const verification = readVerification(p.data.cost);
  const strikes = envStrikes(verification);
  const cls = p.data.cost?.material_class ?? "polymer";
  const curMat = pendMat ?? cls;

  const save = async () => {
    if (!key || parsed.errors.length || !dirty) return;
    setBusy(true);
    setErr(null);
    const res = await saveServiceConditions(key, parsed.env, p.data.context);
    setBusy(false);
    if (!res.ok) {
      setErr(res.error ?? "The conditions weren't saved.");
      return;
    }
    p.patchData({ context: res.context });
    p.toast({ text: hasServiceConditions(parsed.env) ? "Conditions saved with this part" : "Conditions cleared from this part" });
  };
  const set = (k: keyof ServiceConditionsDraft, v: string | boolean) => setDraft((d) => ({ ...d, [k]: v }));
  const c = cheapestAt(p.methods, p.q);
  const figs: FigItem[] = [];
  if (!hasServiceConditions(stored)) figs.push({ k: "Material class", v: MATERIAL_CLASS_LABEL[cls] ?? cls, s: cls === "polymer" ? "default" : "this check" });
  else {
    figs.push({ k: "Checked in", v: MATERIAL_CLASS_LABEL[cls] ?? cls, s: c ? `${c.name.toLowerCase()} survives` : "nothing survives", tone: c ? "ok" : "bad" });
    if (strikes.length) figs.push({ k: "Ruled out", v: [...new Set(strikes.map((s) => s.material))].slice(0, 3).join(", "), s: `${strikes.length} by the conditions`, tone: "bad" });
    if (c) figs.push({ k: `From, at ${qtyWord(p.q)}`, v: money(priceAt(c, p.q)), s: c.name.toLowerCase() });
  }
  const roving = (e: React.KeyboardEvent, i: number) => {
    const d = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const j = (i + d + CLASSES.length) % CLASSES.length;
    const k = CLASSES[j][0];
    setPendMat(k === cls ? null : k);
    requestAnimationFrame(() => radios.current?.querySelectorAll<HTMLButtonElement>("[role=radio]")[j]?.focus());
  };
  return (
    <>
      <SheetTop title="Service conditions" meta={hasServiceConditions(stored) ? "Saved with this part" : "Not set · nothing ruled out"} figs={figs} />
      <div className="scroll">
        <RunNotice />
        {p.interrupted ? null : (
          <div className="swap">
            {stale ? (
              <div className="note" role="status" style={{ borderColor: "#E9C46A" }}>
                <b>The verdict on this page used the previous conditions</b>
                <span>Methods, prices and machine fit update when the part is checked again with the saved conditions.</span>
                <span>
                  {p.canRecheck ? (
                    <button className="btn sm ink" type="button" onClick={() => p.recheck()}>
                      Re-verify with saved conditions
                    </button>
                  ) : (
                    <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Drop the file on the part to re-verify it with the saved conditions.</span>
                  )}
                </span>
              </div>
            ) : null}
            <div className="gh">
              <span>Where it&apos;s used</span>
              <span>{hasServiceConditions(stored) ? "Saved with this part" : "Not set"}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 10, padding: "4px 12px 6px" }}>
              <label className="field">
                Hottest, °C
                <input type="text" inputMode="decimal" value={draft.max_temp_c} placeholder="°C" onChange={(e) => set("max_temp_c", e.target.value)} />
              </label>
              <label className="field">
                Coldest, °C
                <input type="text" inputMode="decimal" value={draft.min_temp_c} placeholder="°C" onChange={(e) => set("min_temp_c", e.target.value)} />
              </label>
              <label className="field">
                Pressure, bar
                <input type="text" inputMode="decimal" value={draft.pressure_bar} placeholder="bar" onChange={(e) => set("pressure_bar", e.target.value)} />
              </label>
              <label className="field">
                Standard
                <input type="text" value={draft.standard} placeholder="for example NACE MR0175" onChange={(e) => set("standard", e.target.value)} />
              </label>
              <label className="field" style={{ gridColumn: "1 / -1" }}>
                Medium
                <input type="text" value={draft.medium} placeholder="for example sour gas (H2S), seawater" onChange={(e) => set("medium", e.target.value)} />
              </label>
            </div>
            <div style={{ display: "flex", gap: 8, padding: "2px 12px 8px", flexWrap: "wrap", alignItems: "center" }}>
              <span className="seg" role="group" aria-label="Service">
                <button type="button" className={cx(draft.sour_service && "on")} aria-pressed={draft.sour_service} onClick={() => set("sour_service", !draft.sour_service)}>
                  Sour gas, H₂S
                </button>
                <button type="button" className={cx(draft.corrosive && "on")} aria-pressed={draft.corrosive} onClick={() => set("corrosive", !draft.corrosive)}>
                  Corrosive
                </button>
              </span>
              <Link className="btn sm" href={R.fit}>
                Add the parts around it
              </Link>
            </div>
            {parsed.errors.length ? (
              <p role="alert" style={{ margin: "0 12px 6px", color: "var(--bad)", fontSize: 12.5 }}>
                {parsed.errors.join(" ")}
              </p>
            ) : null}
            <div style={{ display: "flex", gap: 8, padding: "0 12px 4px", alignItems: "center", flexWrap: "wrap" }}>
              {clearing ? (
                <ConfirmButton className="btn ink sm" label="Clear conditions" question="Clear this part's saved conditions?" confirmLabel="Clear" onConfirm={save} disabled={busy || !key} />
              ) : (
                <button className="btn ink sm" type="button" disabled={!dirty || busy || !key || parsed.errors.length > 0} onClick={() => void save()}>
                  {busy ? "Saving…" : "Save conditions"}
                </button>
              )}
              {dirty ? (
                <button className="btn sm ghost" type="button" onClick={() => setDraft(storedDraft)}>
                  Undo changes
                </button>
              ) : null}
              <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{dirty ? "Saved to this part’s record; the shown verdict changes when you re-check" : "No changes"}</span>
            </div>
            {err ? (
              <p role="alert" style={{ margin: "4px 12px 0", color: "var(--bad)", fontSize: 12.5 }}>
                {err}
              </p>
            ) : null}
            {strikes.length ? (
              <>
                <div className="gh">
                  <span>Ruled out by these conditions</span>
                  <span>{strikes.length}</span>
                </div>
                <div className="lines">
                  {strikes.map((s, i) => (
                    <div key={i} className="ln" style={{ gridTemplateColumns: "minmax(0,1fr)" }}>
                      <span>
                        <b style={{ display: "block", textAlign: "left" }}>{s.material}</b>
                        <span style={{ color: "var(--ink2)" }}>{s.reason}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </>
            ) : null}
            <div className="gh">
              <span>
                Material class <span className={cx("src", cls === "polymer" ? "s-typ" : "s-yours")} style={{ marginLeft: 6 }}>{cls === "polymer" ? "Default" : "Yours"}</span>
              </span>
              <span>each at {qtyWord(p.q)}</span>
            </div>
            <div role="radiogroup" aria-label="Material class" ref={radios}>
              {CLASSES.map(([k, name], i) => {
                const on = curMat === k;
                const checked = k === cls;
                return (
                  <button
                    key={k}
                    type="button"
                    role="radio"
                    className={cx("mrow", on && "on")}
                    aria-checked={on}
                    tabIndex={on ? 0 : -1}
                    onClick={() => setPendMat(k === cls ? null : k)}
                    onKeyDown={(e) => roving(e, i)}
                  >
                    <span className="sw" aria-hidden="true" style={checked ? undefined : { filter: "grayscale(1)", opacity: 0.6 }} />
                    <span>
                      <b>{name}</b>
                      <small>{checked ? (c ? `This check · ${c.name.toLowerCase()} cheapest` : "This check · nothing priced") : "Not checked for this part yet"}</small>
                    </span>
                    <span className="c num">{checked ? (c ? `from ${money(priceAt(c, p.q))}` : "—") : "Re-check"}</span>
                  </button>
                );
              })}
            </div>
            {pendMat ? (
              <div style={{ display: "flex", gap: 8, padding: "8px 12px 0", alignItems: "center", flexWrap: "wrap" }}>
                <button className="btn ink sm" type="button" disabled={!p.canRecheck} onClick={() => p.recheck({ materialClass: pendMat })}>
                  Re-check in {(MATERIAL_CLASS_LABEL[pendMat] ?? pendMat).toLowerCase()}
                </button>
                <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{p.canRecheck ? "Methods, prices and machines update together · same file, no extra check" : "Drop the file on the part to re-check it in another material."}</span>
              </div>
            ) : null}
            <p style={{ margin: "10px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>Conditions are saved with this part and load next time it&apos;s opened. The material class is part of each check&apos;s record.</p>
          </div>
        )}
      </div>
    </>
  );
}
