"use client";

/**
 * N3 (and N7 on a phone): "Make it about your shop", over the part. Pick your
 * machines from the catalog; each arrives with what its maker publishes (work
 * area, materials, workpiece load), labelled "from the maker's spec" with the
 * maker's page, so an unedited pick can already say yes. Only what a yes needs
 * is asked: what it cuts and the heaviest part (a printer's work area decides
 * weight), and both are prefilled where the maker publishes them. Hourly rates
 * are optional: blank keeps the typical rate; a rate you enter is costed as a
 * machine you own. "Re-check this part" saves the machines and re-checks the
 * same file (no new check).
 */
import * as React from "react";
import Link from "next/link";
import { createMachine, type OwnedMachine } from "@/lib/verify/machine-api";
import { fetchMachineCatalog, type MachineCatalogTemplate } from "@/lib/verify/machine-catalog-api";
import { computeMeshHash } from "@/lib/verify/part-context";
import { CAD_ACCEPT } from "../pending-file";
import { R } from "../routes";
import { cx } from "../ui";
import { usePart } from "../part/ctx";
import { startCheck } from "../part/store";
import { rateSource } from "../home/data";
import { MATERIALS, catKind, catWhat, catalogGroups, draftFrom, draftMaterials, envText, machineBody, materialWord, missingFor, ownedRate, parseNum, provenanceOf, typicalRate, weightNeeded, type Draft } from "./first-run";
import { startRecheck } from "./state";
import "./onboard.css";

const CNC_CUTS = MATERIALS.filter(([k]) => k !== "polymer").concat([["polymer", "Plastic"]]);

function useCatalog() {
  const [cat, setCat] = React.useState<MachineCatalogTemplate[] | null | "failed">(null);
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setCat(null);
    fetchMachineCatalog().then(
      (c) => live && setCat(c),
      () => live && setCat("failed"),
    );
    return () => {
      live = false;
    };
  }, [n]);
  return { cat, retry: () => setN((x) => x + 1) };
}

/** The share of an entered rate treated as paid-off capital: the default card's 35%, or what a governed card sets. */
function useCapitalShare(): number | null {
  const [v, setV] = React.useState<number | null>(null);
  React.useEffect(() => {
    let live = true;
    rateSource()
      .then((r) => {
        if (!live) return;
        const p = (r as unknown as { payload?: { global?: { machine_capital_frac?: unknown } } | null }).payload;
        const g = p?.global?.machine_capital_frac;
        setV(r.using_governed ? (typeof g === "number" ? g : null) : 0.35);
      })
      .catch(() => live && setV(null));
    return () => {
      live = false;
    };
  }, []);
  return v;
}

function SourceLabel({ prov, field }: { prov: { url: string; note: string; source: string } | null; field: string }) {
  if (!prov) return <em>yours</em>;
  return (
    <em title={prov.note}>
      {prov.source === "maker_described" ? "from the maker’s description" : "from the maker’s spec"} ·{" "}
      <a href={prov.url} target="_blank" rel="noreferrer" aria-label={`The maker’s page for the ${field} (opens in a new tab)`}>
        source
      </a>{" "}
      · edit
    </em>
  );
}

export function ShopSheet({ onClose, onSkip }: { onClose: () => void; onSkip: () => void }) {
  const p = usePart();
  const { cat, retry } = useCatalog();
  const share = useCapitalShare();
  const [q, setQ] = React.useState("");
  const [mine, setMine] = React.useState<Draft[]>([]);
  const [rates, setRates] = React.useState(false);
  const [ask, setAsk] = React.useState(false);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [needFile, setNeedFile] = React.useState<string | null>(null);
  const ref = React.useRef<HTMLElement>(null);
  const searchRef = React.useRef<HTMLInputElement>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const back = React.useRef<HTMLElement | null>(null);
  const keepRef = React.useRef<HTMLButtonElement>(null);
  const chooseRef = React.useRef<HTMLButtonElement>(null);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  // On a phone the sheet covers the page: the page behind doesn't scroll while it's open.
  React.useEffect(() => {
    if (!window.matchMedia("(max-width:900px)").matches) return;
    const el = document.documentElement;
    const was = el.style.overflow;
    el.style.overflow = "hidden";
    return () => {
      el.style.overflow = was;
    };
  }, []);
  React.useEffect(() => {
    back.current = document.activeElement as HTMLElement | null;
    searchRef.current?.focus();
    return () => {
      const to = back.current;
      if (to && document.contains(to)) to.focus();
    };
  }, []);
  React.useEffect(() => {
    if (ask) keepRef.current?.focus();
  }, [ask]);
  React.useEffect(() => {
    if (!needFile) return;
    if (bodyRef.current) bodyRef.current.scrollTop = 0;
    chooseRef.current?.focus();
  }, [needFile]);

  const list = Array.isArray(cat) ? cat : [];
  const g = catalogGroups(list, q);
  const partCls = p.data.cost?.material_class ?? null;
  const partWord = materialWord(partCls);
  const labor = p.data.cost?.assumptions?.find((a) => a.name === "labor_rate") ?? null;
  const picked = (idx: number) => mine.some((d) => d.idx === idx);
  const toggle = (idx: number) => {
    setError(null);
    if (picked(idx)) setMine((m) => m.filter((d) => d.idx !== idx));
    else {
      setMine((m) => [...m, draftFrom(list[idx], idx)]);
      setQ("");
    }
  };
  const upd = (idx: number, patch: Partial<Draft>) => setMine((m) => m.map((d) => (d.idx === idx ? { ...d, ...patch } : d)));
  const missing = mine.reduce((n, d) => n + missingFor(list[d.idx], d).length, 0);
  const ready = mine.length > 0 && !busy;

  const close = () => {
    if (busy) return;
    if (needFile) onClose();
    else if (mine.length) setAsk(true);
    else onSkip();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      if (ask) setAsk(false);
      else close();
      return;
    }
    if (e.key !== "Tab" || !ref.current) return;
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])")).filter((n) => n.offsetParent !== null);
    if (!items.length) return;
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (e.shiftKey && i <= 0) {
      e.preventDefault();
      items[items.length - 1].focus();
    } else if (!e.shiftKey && i === items.length - 1) {
      e.preventDefault();
      items[0].focus();
    }
  };

  /** Re-check the same file: from this browser's copy, or the file chosen again (its fingerprint must match). */
  const recheckWith = (file: File | null, names: string[]) => {
    const key = p.data.key;
    const before = p.data.cost;
    if (!key || !before) return false;
    // The re-check runs against every machine the shop has, the ones already there and these.
    const all = [...p.data.machines.map((m) => m.name ?? catWhat(m.process)), ...names.filter((n) => !p.data.machines.some((m) => m.name === n))];
    startRecheck({ key, before, sessionId: null, machines: all });
    const materialClass = before.material_class ?? p.session?.materialClass ?? "polymer";
    if (file) startCheck(file, { materialClass });
    else p.recheck({ materialClass });
    return true;
  };

  const save = async () => {
    if (!ready) return;
    setError(null);
    const done: OwnedMachine[] = [];
    let left = [...mine];
    for (const d of mine) {
      const t = list[d.idx];
      setBusy(`Saving ${t.name ?? "machine"}…`);
      try {
        done.push(await createMachine(machineBody(t, d)));
        left = left.filter((x) => x.idx !== d.idx);
      } catch (e) {
        setMine(left);
        setBusy(null);
        setError(`Couldn’t save the ${t.name ?? "machine"}: ${e instanceof Error ? e.message : "try again"}.${done.length ? ` ${done.map((m) => m.name).join(", ")} ${done.length === 1 ? "is" : "are"} saved.` : " Nothing was saved."}`);
        return;
      }
    }
    setBusy(null);
    setMine([]);
    const names = done.map((m) => m.name ?? catWhat(m.process));
    if (p.canRecheck) {
      recheckWith(null, names);
      onClose();
    } else {
      // This browser doesn't hold the file (a later visit): choose it again to re-check.
      setNeedFile(names.join(", "));
    }
  };

  const onPickFile = async (f: File | undefined) => {
    if (!f || !needFile) return;
    setError(null);
    const hash = await computeMeshHash(f).catch(() => null);
    if (!hash || hash !== p.data.key) {
      setError(`That isn’t ${p.data.fileName}: its fingerprint doesn’t match this part. Choose the same file.`);
      return;
    }
    recheckWith(f, needFile.split(", "));
    onClose();
  };

  const firstRate = mine.map((d) => parseNum(d.rate)).find((r) => r != null) ?? null;
  const exampleRate = firstRate ?? 85;
  const typicalEx = mine.map((d) => typicalRate(p.data.cost, list[d.idx]?.process ?? "")).find((r) => r != null) ?? null;

  return (
    <div className="nb-over">
      <button className="nb-scrim" type="button" tabIndex={-1} aria-hidden="true" onClick={close} />
      <section ref={ref} className="nb-ss" role="dialog" aria-modal="true" aria-labelledby="ys-title" aria-describedby="ys-meta" onKeyDown={onKey}>
        <span className="grab" aria-hidden="true" />
        <div className="hd">
          <div style={{ minWidth: 0 }}>
            <h1 className="ptitle" id="ys-title">
              Make it about your shop
            </h1>
            <p className="pmeta" id="ys-meta">
              <span>About 2 minutes</span>
              {Array.isArray(cat) ? <span>{cat.length} machines in the catalog</span> : null}
              <span>Anything else: add it later in Your shop</span>
            </p>
          </div>
          <button className="btn x" type="button" onClick={close} aria-label="Close and skip for now">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="body" ref={bodyRef}>
          {needFile ? (
            <div className="nb-need swap" role="status">
              <b>Saved: {needFile}</b>
              <span>This browser doesn’t hold {p.data.fileName} any more. Choose the same file to re-check it against your machines; re-checking the same file doesn’t use a check.</span>
              <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button ref={chooseRef} className="btn ink sm" type="button" onClick={() => fileRef.current?.click()}>
                  Choose {p.data.fileName}
                </button>
              </span>
              <input ref={fileRef} type="file" accept={CAD_ACCEPT} aria-label={`Choose ${p.data.fileName} to re-check`} tabIndex={-1} hidden onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                void onPickFile(f);
              }} />
            </div>
          ) : null}

          {needFile ? null : (
            <>

              {mine.length ? (
                <section className="mine" aria-labelledby="mine-t">
                  <div className="cg" style={{ paddingTop: 0 }}>
                    <span id="mine-t">Your machines · {mine.length}</span>
                    <span>Needed for a yes: what it cuts, heaviest part</span>
                  </div>
                  {mine.map((d) => (
                    <MachineCard
                      key={d.idx}
                      t={list[d.idx]}
                      d={d}
                      partCls={partCls}
                      partWord={partWord}
                      fileName={p.data.fileName}
                      rates={rates}
                      typical={typicalRate(p.data.cost, list[d.idx].process)}
                      onChange={(patch) => upd(d.idx, patch)}
                      onRemove={() => toggle(d.idx)}
                    />
                  ))}
                  {!rates ? (
                    <div className="ratebar">
                      <span>
                        <b>Hourly rates · optional.</b> Typical rates are used until you add yours.
                      </span>
                      <button className="btn sm" type="button" aria-expanded="false" onClick={() => setRates(true)}>
                        Add rates
                      </button>
                    </div>
                  ) : (
                    <p className="fine swap">
                      {share != null ? (
                        <>
                          Each machine here is priced as one you own: {Math.round(share * 100)}% of its hourly rate is treated as paid-off capital. Blank uses the typical rate
                          {typicalEx != null ? ` ($${typicalEx}/h → $${ownedRate(typicalEx, share).toFixed(2)}/h in-house)` : ""}; a rate you enter replaces it (${exampleRate}/h → ${ownedRate(exampleRate, share).toFixed(2)}/h).
                        </>
                      ) : (
                        "Each machine here is priced as one you own, without the paid-off capital share your rate card sets. Blank uses the typical rate; a rate you enter replaces it."
                      )}
                      {labor ? ` Labor stays ${labor.provenance === "DEFAULT" ? "typical" : "yours"} ($${labor.value}/h) until you set it in Rates.` : " Labor is set in Rates."}
                    </p>
                  )}
                </section>
              ) : null}

              <div className="srch">
                <label htmlFor="ys-q">{mine.length ? "Add another machine" : "Find your machines"}</label>
                <span className="in">
                  <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.7" />
                    <path d="m14 14 3.5 3.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                  </svg>
                  <input ref={searchRef} id="ys-q" type="search" autoComplete="off" value={q} placeholder="Brand or model: Haas, Prusa, Form 4…" onChange={(e) => setQ(e.target.value)} aria-describedby="ys-cnt" />
                </span>
                <span className="cnt" id="ys-cnt" role="status">
                  {cat === null ? "Loading the catalog…" : cat === "failed" ? "The catalog didn’t load." : q.trim() ? `${g.matched} of ${g.total} match “${q.trim()}”` : `${g.total} machines · machining ${g.byKind.cnc}, printers ${g.byKind.print}`}
                </span>
              </div>

              {cat === "failed" ? (
                <div className="empty">
                  <b>The catalog didn’t load</b>
                  <span>Nothing was saved. Try again, or add a machine by hand in Your shop.</span>
                  <span style={{ display: "flex", gap: 8 }}>
                    <button className="btn sm" type="button" onClick={retry}>
                      Retry
                    </button>
                    <Link className="btn sm" href={`${R.shop}?add=1`}>
                      Add by hand
                    </Link>
                  </span>
                </div>
              ) : cat === null ? (
                <div className="cat" aria-busy="true">
                  {[0, 1, 2, 3].map((i) => (
                    <span key={i} className="nb-sk" />
                  ))}
                </div>
              ) : g.matched === 0 ? (
                <div className="empty">
                  <b>No catalog match for “{q.trim()}”</b>
                  <span>Add it by hand in Your shop: name, method, work area, materials.</span>
                  <Link className="btn sm" href={`${R.shop}?add=1`}>
                    Add by hand
                  </Link>
                </div>
              ) : (
                <div className="cat">
                  {g.groups.map((grp) => (
                    <React.Fragment key={grp.kind}>
                      <div className="cg">
                        <span>{grp.label}</span>
                        <span>
                          {grp.items.length}
                          {q.trim() ? " match" : ""}
                        </span>
                      </div>
                      {grp.items.map(({ t, idx }) => {
                        const on = picked(idx);
                        return (
                          <button key={idx} type="button" className={cx("co", on && "on")} aria-pressed={on} onClick={() => toggle(idx)}>
                            <span className="ic" aria-hidden="true">
                              {grp.kind === "cnc" ? <MillIcon /> : <PrintIcon />}
                            </span>
                            <span>
                              <b>{t.name}</b>
                              <small>{[catWhat(t.process), envText(t.capabilities)].filter(Boolean).join(" · ")}</small>
                            </span>
                            <span className="add">{on ? "✓ Added" : "+ Add"}</span>
                          </button>
                        );
                      })}
                      {grp.kind === "print" ? <p className="fine" style={{ padding: "2px 10px 6px" }}>Printer materials come from the catalog. Nozzle, layer height, enclosure and filament in stock: add them later in Your shop.</p> : null}
                    </React.Fragment>
                  ))}
                  {q.trim() ? <p className="fine" style={{ padding: "2px 10px 6px" }}>Not listed? <Link href={`${R.shop}?add=1`}>Add it by hand in Your shop</Link>: name, method, work area, materials.</p> : null}
                </div>
              )}
            </>
          )}
        </div>
        <div className="ft">
          {needFile ? (
            <>
              <span className="m" aria-live="polite">
                <b>Saved: {needFile}</b>
                <span>{error ? <span className="nb-err" role="alert">{error}</span> : `Choose ${p.data.fileName} to re-check it against ${needFile.split(", ").length === 1 ? "it" : "them"}`}</span>
              </span>
              <button className="btn ghost" type="button" onClick={onClose}>
                Later
              </button>
            </>
          ) : ask ? (
            <div className="ask2" role="alertdialog" aria-label="Discard machines" aria-describedby="ys-discard">
              <span id="ys-discard" style={{ flex: 1 }}>
                Close without saving {mine.length} {mine.length === 1 ? "machine" : "machines"}?
              </span>
              <button className="btn sm ink" type="button" onClick={onSkip}>
                Discard
              </button>
              <button ref={keepRef} className="btn sm" type="button" onClick={() => setAsk(false)}>
                Keep editing
              </button>
            </div>
          ) : (
            <>
              <span className="m" aria-live="polite">
                <b>{busy ?? (mine.length ? `Re-check ${p.data.fileName} ${p.data.machines.length ? `with ${mine.length} more` : `against ${mine.length}`} ${mine.length === 1 ? "machine" : "machines"}` : "Pick at least one machine, or skip")}</b>
                <span>
                  {error ? (
                    <span className="nb-err" role="alert">
                      {error}
                    </span>
                  ) : mine.length ? (
                    `${missing ? `${missing} ${missing === 1 ? "field" : "fields"} missing · ` : ""}re-checking the same file doesn’t use a check`
                  ) : (
                    "Answers use typical machines and rates until you add yours"
                  )}
                </span>
              </span>
              <button className="btn ghost" type="button" onClick={close} disabled={!!busy}>
                Skip for now
              </button>
              <button className={cx("btn ink", !ready && "off")} type="button" aria-disabled={!ready} onClick={() => void save()}>
                {busy ? "Saving…" : partCls ? "Re-check this part" : "Save machines"}
              </button>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

function MachineCard({
  t,
  d,
  partCls,
  partWord,
  fileName,
  rates,
  typical,
  onChange,
  onRemove,
}: {
  t: MachineCatalogTemplate;
  d: Draft;
  partCls: string | null;
  partWord: string;
  fileName: string;
  rates: boolean;
  typical: number | null;
  onChange: (p: Partial<Draft>) => void;
  onRemove: () => void;
}) {
  const ids = React.useId();
  const cnc = catKind(t.process) === "cnc";
  const name = t.name ?? catWhat(t.process);
  const miss = missingFor(t, d);
  const kgProv = provenanceOf(t, d, "max_workpiece_kg");
  const matProv = provenanceOf(t, d, "materials");
  const mats = draftMaterials(t, d);
  const needW = weightNeeded(t);
  const notForPart = cnc && partCls && mats.length > 0 && !mats.includes(partCls);
  const rate = parseNum(d.rate);
  return (
    <div className="mc">
      <div className="h">
        <span>
          <b>{name}</b>
          <small>{[catWhat(t.process), envText(t.capabilities)].filter(Boolean).join(" · ")}</small>
        </span>
        <span className="step" role="group" aria-label={`How many ${name}`}>
          <button type="button" aria-label={`One fewer ${name}`} onClick={() => onChange({ count: Math.max(1, d.count - 1) })}>
            −
          </button>
          <output aria-live="polite">{d.count}</output>
          <button type="button" aria-label={`One more ${name}`} onClick={() => onChange({ count: d.count + 1 })}>
            +
          </button>
        </span>
        <button className="xs" type="button" aria-label={`Remove ${name}`} onClick={onRemove}>
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      <div className={cx("rowf", rates && "three", !needW && "nokg")}>
        <div className="fl" role="group" aria-label={`Materials the ${name} ${cnc ? "cuts" : "prints"}`}>
          <span className="lab">
            {cnc ? "Materials it cuts" : "Materials it prints"} {miss.includes("materials") ? <em className="need">needed for a yes</em> : <SourceLabel prov={matProv} field="materials" />}
          </span>
          {cnc ? (
            <span className="cuts">
              {CNC_CUTS.map(([k, label]) => {
                const on = d.materials.includes(k);
                return (
                  <button key={k} type="button" className={cx("cut", on && "on")} aria-pressed={on} onClick={() => onChange({ materials: on ? d.materials.filter((x) => x !== k) : [...d.materials, k] })}>
                    {label}
                  </button>
                );
              })}
            </span>
          ) : (t.materials ?? []).length ? (
            <span className="pm">{(t.materials ?? []).join(", ")}</span>
          ) : (
            <span className="unit">
              <input type="text" value={d.matsText} placeholder={t.process === "fdm" ? "e.g. PLA, PETG" : t.process === "sls" || t.process === "mjf" ? "e.g. PA12" : "e.g. Standard Resin, Tough Resin"} aria-label={`Materials the ${name} prints, separated by commas`} aria-invalid={miss.includes("materials")} onChange={(e) => onChange({ matsText: e.target.value })} />
            </span>
          )}
        </div>
        {needW ? (
          <label className="fl">
            <span className="lab">
              Heaviest part {miss.includes("kg") ? <em className="need">needed for a yes</em> : <SourceLabel prov={kgProv} field="workpiece load" />}
            </span>
            <span className="unit">
              <input type="text" inputMode="decimal" value={d.kg} placeholder="e.g. 200" aria-invalid={miss.includes("kg")} onChange={(e) => onChange({ kg: e.target.value })} />
              <span className="u">kg</span>
            </span>
          </label>
        ) : (
          <div className="fl">
            <span className="lab">Heaviest part</span>
            <span className="pm nb-quiet">Not checked: the maker publishes no plate load; the work area decides.</span>
          </div>
        )}
        {rates ? (
          <label className="fl swap">
            <span className="lab">
              Hourly rate <em>optional</em>
            </span>
            <span className="unit">
              <span className="p">$</span>
              <input id={`${ids}-rate`} className="pre" type="text" inputMode="decimal" value={d.rate} placeholder={typical != null ? String(typical) : "typical"} onChange={(e) => onChange({ rate: e.target.value })} />
              <span className="u">/h</span>
            </span>
            <span className="nb-quiet">{rate != null ? `Yours${typical != null ? ` · typical is $${typical}/h` : ""}` : typical != null ? `Blank: typical $${typical}/h` : "Blank: typical"}</span>
          </label>
        ) : null}
      </div>
      {miss.includes("kg") ? <p className="miss">Without a weight limit the {name} answers “not confirmed”, never a yes.</p> : null}
      {miss.includes("materials") ? <p className="miss">Without materials the {name} answers “not confirmed”, never a yes.</p> : null}
      {notForPart ? (
        <p className="miss">
          {fileName} is priced in {partWord}. Add {partWord.replace(/^\w/, (c) => c.toUpperCase())} if the {name} {cnc ? "cuts" : "prints"} it, or it answers “not set up”.
        </p>
      ) : null}
    </div>
  );
}

function MillIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M8 2.5h4v5l-1 1.5v4.5H9V9L8 7.5v-5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M3 16.5h14M5 14h10v2.5H5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

function PrintIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <rect x="2.5" y="2.5" width="15" height="15" rx="2.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M7 6.5h6l-1.5 2.5h-3L7 6.5ZM10 9v2" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M6 14.5h8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}
