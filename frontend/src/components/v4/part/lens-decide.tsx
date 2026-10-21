"use client";

/** Decide: record what happens next on the part's record, at a computed quantity, against a real route. */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { createRfqPackage, downloadRfqPackage, shareCostDecision } from "@/lib/api";
import { R } from "../routes";
import { cx } from "../ui";
import { usePart } from "./ctx";
import { days, decideOptions, methodName, money, qtyWord, shortId, type DecideOption } from "./model";
import { putDisposition, reloadDecision } from "./api";
import { RunNotice, SheetTop, type FigItem } from "./sheet-bits";
import { useMachineViews } from "./lens-shop";
import { enginePick, pairAt, pickWhy } from "./choice";

const LABEL: Record<string, string> = { inhouse: "Make in-house", outside: "Make outside", acquire: "Acquire capability", redesign: "Redesign" };

function useOptions() {
  const p = usePart();
  const bp = p.data.decision?.disposition_basis?.process ?? null;
  const kind = p.data.decision?.user_disposition ?? null;
  return React.useMemo(() => {
    const opts = decideOptions(p.methods, p.data.cost, p.q, p.data.machines.length);
    // A process chosen in Make ("Make it this way") that isn't one of the listed outcomes: list it too, so the saved one shows.
    if ((kind === "inhouse" || kind === "outside") && bp && !opts.some((o) => o.kind === kind && o.route?.process === bp)) {
      const m = p.methods.find((x) => x.code === bp);
      const e = m?.prices.get(p.q);
      if (m && e) {
        const where = kind === "inhouse" ? `${m.inHouse ?? "your machine"} · ` : `${m.name} · `;
        const at = opts.findIndex((o) => o.kind === "acquire");
        opts.splice(at < 0 ? opts.length : at, 0, {
          id: `chosen-${m.code}`,
          kind,
          label: kind === "inhouse" ? "Make in-house" : "Make outside",
          sub: `${where}${m.short} ${e.material} · ${days(e.lead_time?.low_days, e.lead_time?.high_days)}`,
          cost: e.unit_cost_usd,
          off: false,
          route: { process: e.process, material: e.material, quantity: e.quantity },
        });
      }
    }
    return opts;
  }, [p.methods, p.data.cost, p.q, p.data.machines.length, kind, bp]);
}

/** The option the record's saved outcome points at, if it's on the list. */
function savedOption(opts: DecideOption[], disposition: string | null | undefined, basis: { process: string } | null | undefined): DecideOption | null {
  if (!disposition) return null;
  const same = opts.filter((o) => o.kind === disposition);
  const exact = same.find((o) => o.route && basis && o.route.process === basis.process);
  if (exact) return exact;
  // A recorded route that isn't priced at this quantity: don't stand another route in for it.
  return basis?.process && (disposition === "inhouse" || disposition === "outside") ? null : same[0] ?? null;
}

/** The option ScaleCAD's pick at this quantity lands on (in-house when its rule keeps your machine). */
function pickOption(opts: DecideOption[], pick: ReturnType<typeof enginePick>): DecideOption | null {
  if (!pick) return null;
  return opts.find((o) => !o.off && o.route?.process === pick.process && (o.kind === "inhouse") === pick.inHouse) ?? opts.find((o) => !o.off && o.route?.process === pick.process) ?? null;
}

export function useDecideState() {
  const p = usePart();
  const opts = useOptions();
  const gov = p.data.decision;
  const saved = savedOption(opts, gov?.user_disposition, gov?.disposition_basis ?? null);
  const picked = pickOption(opts, enginePick(p.data.cost, p.q));
  // Nothing recorded yet: ScaleCAD's pick is preselected, one click to record or another to change.
  const chosen = opts.find((o) => o.id === p.decidePick) ?? saved ?? (gov?.user_disposition ? null : picked) ?? null;
  return { opts, gov, saved, chosen, picked, setPick: p.setDecidePick };
}

export function DecideTicket() {
  const p = usePart();
  const { chosen, gov, picked } = useDecideState();
  if (p.lens !== "decide" || p.interrupted) return null;
  const isSaved = !!gov?.user_disposition && !!chosen && chosen.kind === gov.user_disposition;
  const env = p.data.runEnvironment;
  const lead = !isSaved && chosen && chosen.id === picked?.id && !p.decidePick ? "ScaleCAD’s pick · " : "";
  return (
    <div className="ticket">
      <span style={{ color: "var(--ink3)", fontSize: 13 }}>{chosen ? `${lead}${chosen.label} · ${chosen.sub.split(" · ").slice(0, 2).join(" · ")}` : "Nothing chosen yet"}</span>
      <span className="big num">{chosen?.cost != null ? `${money(chosen.cost)} each` : "—"}</span>
      <span style={{ color: "var(--ink2)", fontSize: 13.5 }}>
        {p.q === 1 ? "1 part" : `${qtyWord(p.q)} parts`}{env && (env.sour_service || env.corrosive || env.max_temp_c != null) ? " · for the declared service conditions" : ""}
      </span>
      {isSaved ? <span className="stamp">Recorded on the part&apos;s record</span> : null}
    </div>
  );
}

export function DecideSheet() {
  const p = usePart();
  const { user } = useAuth();
  const { opts, gov, chosen, picked, setPick } = useDecideState();
  const views = useMachineViews();
  const [note, setNote] = React.useState<string>(gov?.disposition_note ?? "");
  const [noteDirty, setNoteDirty] = React.useState(false);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [askW, setAskW] = React.useState(false);
  const groupRef = React.useRef<HTMLDivElement>(null);
  const id = p.data.decisionId;
  React.useEffect(() => {
    setNote(gov?.disposition_note ?? "");
    setNoteDirty(false);
  }, [gov?.disposition_note, gov?.user_disposition]);

  const oqOff = !!p.oq && Number(p.oq) > 0 && !p.qs.includes(Number(p.oq));
  const offAt = oqOff || p.costOff || !p.data.cost;
  const loadErr = !!p.data.decisionError;
  const isSaved = !!gov?.user_disposition && !!chosen && chosen.kind === gov.user_disposition && (!chosen.route || !gov.disposition_basis || (chosen.route.process === gov.disposition_basis.process && gov.disposition_basis.quantity === p.q));
  const saveOff = !chosen || chosen.off || offAt || loadErr || !id || (isSaved && !noteDirty) || !!busy;
  const saveLabel = isSaved && noteDirty ? "Save note" : isSaved ? "Recorded" : "Record decision";

  const record = async () => {
    if (saveOff || !chosen || !id) return;
    setBusy("save");
    setErr(null);
    try {
      const wasSaved = isSaved;
      const res = await putDisposition(id, { disposition: chosen.kind, note, quantity: p.q, process: chosen.route?.process, material: chosen.route?.material });
      p.patchData({ decision: p.data.decision ? { ...p.data.decision, ...res } : ({ ...res } as never) });
      setNoteDirty(false);
      p.toast({ text: wasSaved ? `Note saved to record ${shortId(id)}` : `Recorded on record ${shortId(id)}`, link: { label: "Open", href: R.record(id) } });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The outcome wasn't saved.");
    } finally {
      setBusy(null);
    }
  };
  const withdraw = async () => {
    if (!id) return;
    setBusy("withdraw");
    setErr(null);
    try {
      const res = await putDisposition(id, { disposition: null });
      p.patchData({ decision: p.data.decision ? { ...p.data.decision, ...res } : ({ ...res } as never) });
      setPick(null);
      setAskW(false);
      p.toast({ text: "Decision withdrawn. The record stays." });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The outcome wasn't withdrawn.");
    } finally {
      setBusy(null);
    }
  };
  const retryLoad = async () => {
    if (!id) return;
    try {
      const d = await reloadDecision(id);
      p.patchData({ decision: d, decisionError: null });
    } catch (e) {
      p.patchData({ decisionError: e instanceof Error ? e.message : "Still didn't load." });
    }
  };
  const share = async () => {
    if (!id) return;
    setBusy("share");
    try {
      const r = await shareCostDecision(id);
      const url = new URL(r.share_url, window.location.origin).toString();
      await navigator.clipboard?.writeText(url).catch(() => undefined);
      p.toast({ text: "Share link copied. View only, no sign-in needed.", link: { label: "Preview", href: r.share_url } });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The share link wasn't made.");
    } finally {
      setBusy(null);
    }
  };
  const pkg = async () => {
    if (!id) return;
    setBusy("zip");
    try {
      const made = await createRfqPackage({ decisionIds: [id], title: `RFQ package - ${p.data.fileName}` });
      await downloadRfqPackage(made.id, made.title);
      p.toast({ text: "Supplier package downloaded.", link: { label: "Packages", href: R.pkg(made.id) } });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The package wasn't made.");
    } finally {
      setBusy(null);
    }
  };

  const ih = views.find((v) => v.tone === "ok" && v.cost != null);
  const out = opts.find((o) => o.kind === "outside" && !o.off);
  const pair = pairAt(p.data.cost, p.q);
  const figs: FigItem[] = [];
  if (pair && !p.costOff) {
    // The engine's own comparison: the cheapest route on a machine of yours next to the cheapest outside one.
    const mine = pair.in_house;
    figs.push({ k: `In-house at ${qtyWord(p.q)}`, v: money(mine.unit_cost_usd), s: `${mine.machine ?? methodName(mine.process)} · ${days(mine.lead_low_days, mine.lead_high_days)}${pair.pick === "in_house" ? " · ScaleCAD’s pick" : ""}`, tone: "ok" });
    if (pair.outside) figs.push({ k: "Cheapest outside", v: money(pair.outside.unit_cost_usd), s: `${methodName(pair.outside.process)} · ${days(pair.outside.lead_low_days, pair.outside.lead_high_days)}${pair.pick === "outside" ? " · ScaleCAD’s pick" : ""}` });
  } else {
    if (ih) figs.push({ k: `In-house at ${qtyWord(p.q)}`, v: money(ih.cost), s: ih.name });
    else figs.push({ k: "In-house", v: "None", s: p.data.machines.length ? "nothing of yours can make it" : "no machines declared", tone: "bad" });
    if (out?.cost != null) figs.push({ k: "Cheapest outside", v: money(out.cost), s: out.sub.split(" · ")[0] });
  }
  const owner = user?.email ?? "you";
  const crossover = p.data.cost?.decision?.crossover_qty;
  const enabled = opts.filter((o) => !o.off && !offAt);
  const roving = (e: React.KeyboardEvent, o: DecideOption) => {
    const d = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0;
    if (!d || !enabled.length) return;
    e.preventDefault();
    const i = enabled.indexOf(o);
    const next = enabled[(i + d + enabled.length) % enabled.length];
    setPick(next.id);
    requestAnimationFrame(() => groupRef.current?.querySelector<HTMLButtonElement>(`[data-opt="${next.id}"]`)?.focus());
  };
  const focusId = chosen && !chosen.off ? chosen.id : enabled[0]?.id;
  // What follows from the outcome shown (recorded, or about to be).
  const inHouseName = chosen?.kind === "inhouse" ? chosen.sub.split(" · ")[0] : null;
  const next: { text: string; link?: string; href?: string } | null =
    !chosen || chosen.off || offAt
      ? null
      : chosen.kind === "inhouse"
        ? { text: `make it on your ${inHouseName}, then log the hours and cost so the estimate is checked against the job.`, link: "Log a finished job", href: R.actuals }
        : chosen.kind === "outside"
          ? { text: "download the supplier package below and send it for quotes. ScaleCAD doesn’t send it." }
          : chosen.kind === "acquire"
            ? { text: "weigh the machine against your other parts.", link: "Parts it would unlock", href: R.triage }
            : { text: "fix what blocks it (see Make), then check the revised file." };
  const basis = gov?.disposition_basis;
  const recText = gov?.user_disposition
    ? `${LABEL[gov.user_disposition] ?? gov.user_disposition}${basis ? `, ${methodName(basis.process).toLowerCase()}` : ""} · ${gov.disposition_updated_at ? new Date(gov.disposition_updated_at).toLocaleDateString("en-US", { day: "numeric", month: "short" }) : ""} · ${basis ? `${qtyWord(basis.quantity)} parts · ` : ""}${shortId(id)}`
    : "";
  return (
    <>
      <SheetTop title="Decision" meta={`Owner ${owner} · recorded on this part’s record`} figs={figs} sure="decide" />
      <div className="scroll">
        <RunNotice />
        {p.interrupted ? null : (
          <div className="swap">
            <div className="gh">
              <span>Outcome</span>
              <span>each at {qtyWord(p.q)}</span>
            </div>
            {pair && !p.costOff ? (
              <p style={{ margin: "0 12px 6px", color: "var(--ink2)", fontSize: 13 }}>
                <b style={{ fontWeight: 600 }}>ScaleCAD’s pick:</b> {pickWhy(pair, p.q)}
              </p>
            ) : null}
            <div role="radiogroup" aria-label="Outcome" ref={groupRef}>
              {opts.map((o) => {
                const on = chosen?.id === o.id;
                const off = o.off || offAt;
                return (
                  <button
                    key={o.id}
                    type="button"
                    role="radio"
                    data-opt={o.id}
                    className={cx("mr", on && "on", o.off && "out")}
                    aria-checked={on}
                    aria-disabled={off}
                    tabIndex={o.id === focusId ? 0 : -1}
                    onClick={() => {
                      if (!off) {
                        setPick(o.id);
                        setAskW(false);
                      }
                    }}
                    onKeyDown={(e) => roving(e, o)}
                    style={offAt && !o.off ? { opacity: 0.55, cursor: "default" } : undefined}
                  >
                    <span>
                      <b>{o.label}</b>
                      <small>
                        {o.sub}
                        {picked?.id === o.id && !offAt ? " · ScaleCAD’s pick" : ""}
                      </small>
                    </span>
                    <span />
                    <span className="c num">{p.costOff || o.cost == null ? "" : money(o.cost)}</span>
                  </button>
                );
              })}
            </div>
            {offAt ? (
              <p className="gate" role="status">
                {p.costOff || !p.data.cost ? "Prices are needed to record a decision. Retry prices first." : `Pick ${p.qs.map(qtyWord).join(", ").replace(/, ([^,]*)$/, " or $1")} to record a decision. ${p.oq} is between computed points.`}
              </p>
            ) : null}
            {!id ? <p className="gate">This check wasn&apos;t saved as a record, so an outcome can&apos;t be recorded here.</p> : null}
            <div style={{ padding: "8px 12px 0", display: "flex", flexDirection: "column", gap: 8 }}>
              {gov?.user_disposition && !askW && !loadErr ? (
                <div className="swap" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 13 }}>
                  <span style={{ color: "var(--ok)", fontWeight: 600 }}>✓ {recText}</span>
                  <button className="btn sm ghost" type="button" aria-label={`Withdraw ${LABEL[gov.user_disposition] ?? "decision"}`} onClick={() => setAskW(true)} style={{ height: 26, marginLeft: "auto" }}>
                    Withdraw
                  </button>
                </div>
              ) : null}
              {askW ? (
                <div className="swap" role="alertdialog" aria-label="Withdraw the decision" style={{ padding: "10px 12px", borderRadius: 12, background: "var(--bad-bg)", display: "flex", flexDirection: "column", gap: 8, fontSize: 13 }}>
                  <span>Withdraw this outcome? The record and its numbers stay; only the decision clears.</span>
                  <span style={{ display: "flex", gap: 6 }}>
                    <button className="btn sm ink" type="button" onClick={() => void withdraw()} disabled={busy === "withdraw"}>
                      {busy === "withdraw" ? "Withdrawing…" : "Withdraw"}
                    </button>
                    <button className="btn sm" type="button" onClick={() => setAskW(false)} autoFocus>
                      Keep
                    </button>
                  </span>
                </div>
              ) : null}
              {loadErr ? (
                <div className="swap" role="alert" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 12, background: "var(--bad-bg)", fontSize: 13 }}>
                  <span>Couldn&apos;t load the saved outcome.</span>
                  <button className="btn sm" type="button" onClick={() => void retryLoad()} style={{ marginLeft: "auto" }}>
                    Retry
                  </button>
                </div>
              ) : null}
              <label className="field">
                <span style={{ display: "flex", justifyContent: "space-between" }}>
                  Why, and what would change it
                  <span className="num" style={{ color: "var(--ink3)" }} aria-live="polite">
                    {note.length} / 1000
                  </span>
                </span>
                <textarea
                  maxLength={1000}
                  value={note}
                  placeholder="In-house for the first 10 while we compare binder jetting. Revisit at 100."
                  onChange={(e) => {
                    setNote(e.target.value);
                    setNoteDirty(true);
                  }}
                />
              </label>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button className="btn ink" type="button" onClick={() => void record()} disabled={saveOff}>
                  {busy === "save" ? "Recording…" : saveLabel}
                </button>
                <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>
                  Owner {owner}
                  {crossover ? ` · look again at ${qtyWord(Math.round(crossover))} parts` : ""}
                </span>
              </div>
              {err ? (
                <p role="alert" style={{ margin: 0, color: "var(--bad)", fontSize: 13 }}>
                  {err}
                </p>
              ) : null}
              {next ? (
                <p style={{ margin: 0, fontSize: 13, color: "var(--ink2)" }}>
                  <b style={{ fontWeight: 600 }}>Next:</b> {next.text}{" "}
                  {next.href ? <Link href={next.href}>{next.link}</Link> : null}
                </p>
              ) : null}
              <span style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 13 }}>
                {id ? <Link href={R.record(id)}>Open the record</Link> : null}
                <Link href={R.actuals}>How estimates get checked</Link>
              </span>
            </div>
            <div className="gh" style={{ marginTop: 8 }}>
              <span>Get it quoted</span>
              <span />
            </div>
            <div className="note" style={{ marginTop: 2 }}>
              <span>ZIP: estimate, material and conditions, quantities, findings. Original CAD only for parts checked in a batch. Not sent by ScaleCAD; replies aren&apos;t tracked.</span>
              <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="btn sm" type="button" disabled={!id || busy === "zip"} onClick={() => void pkg()}>
                  {busy === "zip" ? "Building…" : "Download package (ZIP)"}
                </button>
                <button className="btn sm" type="button" disabled={!id || busy === "share"} onClick={() => void share()}>
                  Copy a share link
                </button>
              </span>
            </div>
            <div className="gh" style={{ marginTop: 8 }}>
              <span>Real costs</span>
              <span />
            </div>
            <div className="note" style={{ marginTop: 2 }}>
              <span>
                Log hours and cost after the job. A method&apos;s range turns measured with 3 held-out jobs. Recalibration needs 8 real jobs <small style={{ color: "var(--ink3)" }}>Pilot</small>
              </span>
              <span>
                <Link className="btn sm" href={R.actuals}>
                  Log a finished job
                </Link>
              </span>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
