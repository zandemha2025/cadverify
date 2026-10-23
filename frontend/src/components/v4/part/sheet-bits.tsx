"use client";

/** Pieces every view's sheet shares: the header (question, facts, figures, how sure it is) and the run notice. */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { useShell } from "../shell";
import { cx } from "../ui";
import { usePart } from "./ctx";
import { MATERIAL_CLASS_LABEL, ratesNote } from "./model";
import { plainError } from "./plain-errors";
import { inText } from "../units/units";
import { useUnits } from "../units/use-units";
import { sureOf, type SureLens } from "./sure";
import { Banner, CheckInterruptedBanner, CostBlockedBanner, CostFailedBanner } from "../moments";
import { isQuotaErrorMessage } from "@/lib/api-recovery";
import type { ServiceEnvironment } from "@/lib/verify/part-context";
import { isMultiBody } from "@/lib/verify/bodies";
import { shopChangeText, shopChangedSince, type ShopChange } from "./shop-change";
import { ReadOnlyLine, useReadOnly } from "../read-only";
import { busyView, sheetRunNotice, viewStep } from "./busy-state";
import { BusyNotice } from "./busy-notice";

export interface FigItem {
  k: string;
  v: string;
  s?: string;
  tone?: "ok" | "warn" | "bad";
}

export function SheetTop({ title, meta, figs, sure, route = null }: { title: string; meta: string; figs: FigItem[]; sure?: SureLens; route?: string | null }) {
  // Lengths in the figures follow the person's unit (mm or in); the engine's numbers stay in mm.
  const { unit } = useUnits();
  return (
    <div className="top">
      <h2 className="stitle">{title}</h2>
      <p className="smeta">{inText(meta, unit)}</p>
      <div className="figs" aria-live="polite">
        {figs.map((g) => (
          <div className="fig" key={g.k}>
            <span>{inText(g.k, unit)}</span>
            <b className={cx("num", g.tone, !/^[$\d≈]/.test(g.v) && "t")}>{inText(g.v, unit)}</b>
            {g.s ? <small>{inText(g.s, unit)}</small> : null}
          </div>
        ))}
      </div>
      {sure ? <SureLine lens={sure} route={route} /> : null}
    </div>
  );
}

const SURE_SRC: Record<string, string> = { file: "Your file", yours: "Yours", typ: "Typical" };
const SURE_TO = { rates: R.rates, actuals: R.actuals, machines: `${R.shop}?add=1`, conditions: null } as const;

/** "How sure is this?": what the answer above rests on, one line by default and the detail one click away. */
function SureLine({ lens, route = null }: { lens: SureLens; route?: string | null }) {
  const p = usePart();
  const [open, setOpen] = React.useState(false);
  const id = React.useId();
  const sure = React.useMemo(
    () =>
      p.checking || p.interrupted
        ? null
        : sureOf(lens, { validation: p.data.validation, cost: p.data.cost, machines: p.data.machines, env: p.data.runEnvironment, methods: p.methods, q: p.q, route, materialClass: p.session?.materialClass ?? null }),
    [lens, p.checking, p.interrupted, p.data.validation, p.data.cost, p.data.machines, p.data.runEnvironment, p.methods, p.q, route, p.session?.materialClass],
  );
  if (!sure) return null;
  const to = sure.next ? SURE_TO[sure.next.to] : null;
  return (
    <div className="sure">
      <button type="button" className="sure-h" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <b>How sure is this?</b>
        <span>{sure.line}</span>
        <i aria-hidden="true">{open ? "▾" : "▸"}</i>
      </button>
      {open ? (
        <div className="sure-d swap" id={id}>
          {sure.items.map((x) => (
            <div key={x.k} className="sure-r">
              <span className={cx("src", `s-${x.kind}`)}>{SURE_SRC[x.kind]}</span>
              <span>
                <b>{x.k}</b> {x.v}
              </span>
            </div>
          ))}
          {sure.next ? (
            <span className="sure-n">
              {to ? (
                <Link href={to}>{sure.next.text}</Link>
              ) : (
                <button className="btn sm ghost" type="button" onClick={() => p.setLens("use")} style={{ height: 24, padding: "0 6px" }}>
                  {sure.next.text}
                </button>
              )}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Interrupted check, or prices that didn't finish: the shared X11 banners, plus where usage lives. */
/** A file of several bodies, under a whole-file answer: that answer treats it as one block. */
function BodiesNotice() {
  const p = usePart();
  const pt = p.data.validation?.part_type;
  if (!p.openBodies || !isMultiBody(pt) || p.checking) return null;
  return (
    <div className="note swap" role="note" style={{ marginTop: 8 }}>
      <b>{pt.summary}</b>
      <span>These figures treat the file as one block, which is not how it would be made. Each body’s own answer is under Body by body.</span>
      <span>
        <button className="btn sm" type="button" onClick={p.openBodies}>
          Body by body
        </button>
      </span>
    </div>
  );
}

export function RunNotice() {
  return (
    <>
      <BodiesNotice />
      <RunState />
      <ShopNotice />
      <RatesNotice />
    </>
  );
}

/** What changed in Your shop after the answer on this page was worked out (me-11), or null. */
export function useShopChange(): ShopChange | null {
  const p = usePart();
  const d = p.data.decision;
  return React.useMemo(
    () => (p.checking || p.interrupted ? null : shopChangedSince(p.data.machines, d, d?.created_at ?? p.data.createdAt)),
    [p.checking, p.interrupted, p.data.machines, d, p.data.createdAt],
  );
}

/** A shop change after the check: the answer predates it, and Re-check is right here (me-11). */
function ShopNotice() {
  const p = usePart();
  const c = useShopChange();
  const ro = useReadOnly("re-check parts");
  if (!c) return null;
  return (
    <div className="note swap" role="status" style={{ marginTop: 8 }}>
      <b>{shopChangeText(c)}</b>
      <span>
        The answer on this page predates it.{ro ? "" : " "}
        {ro ? "" : p.canRecheck ? "Re-check works it out again on the machines you have now, from the file kept with this part. No check used." : "Drop the file on the part to check it on the machines you have now."}
      </span>
      {ro ? <ReadOnlyLine line={ro} style={{ margin: 0 }} /> : p.canRecheck ? (
        <span>
          <button className="btn sm ink" type="button" onClick={() => p.recheck()}>
            Re-check
          </button>
        </span>
      ) : null}
    </div>
  );
}

/** A saved record priced at older rates says so near its price, with the way to re-price it (ce-10). */
function RatesNotice() {
  const p = usePart();
  const text = p.checking || p.interrupted ? null : ratesNote(p.data.decision);
  const ro = useReadOnly("re-check parts");
  if (!text) return null;
  return (
    <div className="note swap" role="status" style={{ marginTop: 8 }}>
      <b>{text}</b>
      {ro ? <ReadOnlyLine line={ro} style={{ margin: 0 }} /> : <span>{p.canRecheck ? "Re-cost prices it again from the file kept with this part, at your rates now. No check used." : "Drop the file on the part to price it at your rates now."}</span>}
      {!ro && p.canRecheck ? (
        <span>
          <button className="btn sm ink" type="button" onClick={() => p.recheck()}>
            Re-cost
          </button>
        </span>
      ) : null}
    </div>
  );
}

/** Why prices didn't finish, in plain words (me-12: "gmsh could not mesh the geometry [rung 2 exceeded 15s cap]"). */
function costFailedText(err: string | null | undefined): string {
  const plain = plainError("cost", 0, err ?? null);
  return plain.detail ? plain.text : ["The process checks are ready.", err].filter(Boolean).join(" ");
}

function RunState() {
  const p = usePart();
  const shell = useShell();
  const usage = (
    <p className="pmeta" style={{ marginTop: 6 }}>
      <Link href={R.billing}>Usage and plans</Link>
    </p>
  );
  // A busy server: the one calm state, counting down to the next try, then "Still busy" with Try again.
  // Not an interruption, not about usage or the file.
  const bv = busyView(p.session);
  // While busy the progress panel is on screen whenever it's open (check and part pages), with the same
  // notice over this sheet; one is enough. Hidden, its button above the tab bar counts down instead.
  const s = p.session;
  const which = sheetRunNotice({ busy: bv, panelOpen: !!s?.panel, checking: p.checking, interrupted: p.interrupted, costOff: p.costOff, costRetrying: !!s?.costRetrying });
  if (which === "panel") return null;
  if (bv && which === "busy") {
    const retry = bv.phase !== "waiting" ? (viewStep(bv) === "cost" ? p.retryPrices : () => p.recheck()) : undefined;
    return (
      <div className="swap run-busy" style={{ marginTop: 8 }}>
        <BusyNotice view={bv} onRetry={retry} />
      </div>
    );
  }
  if (p.interrupted) {
    return (
      <div className="swap" style={{ marginTop: 8 }}>
        <CheckInterruptedBanner onRetry={() => p.recheck()} detail="No result. The process checks and cost didn’t start. Wait a moment and retry; the file doesn’t need re-exporting. Saved results are unchanged." />
        {usage}
      </div>
    );
  }
  // Try again was pressed on prices: pricing again, calmly, not "Cost didn't finish" while it runs.
  if (p.costOff && s?.costRetrying) {
    return (
      <div className="swap" style={{ marginTop: 8 }}>
        <Banner tone="info" spin name="pricing" title="Pricing again…" meta="The process checks are ready; this prices the same file once more." />
      </div>
    );
  }
  if (p.costOff) {
    const err = p.data.costError;
    return (
      <div className="swap" style={{ marginTop: 8 }}>
        {isQuotaErrorMessage(err) ? (
          <CostBlockedBanner pro={shell.usage?.plan === "pro"} />
        ) : (
          <CostFailedBanner
            onRetryCost={p.retryPrices}
            onRerun={() => p.recheck()}
            detail={p.session?.costRetrying ? "Retrying cost…" : costFailedText(err)}
          />
        )}
        {usage}
      </div>
    );
  }
  return null;
}

export function classLabel(cls: string | null | undefined): string {
  return cls ? MATERIAL_CLASS_LABEL[cls] ?? cls : "Plastic";
}

/** "sour gas, corrosive, up to 120 °C, NACE MR0175" from the stored conditions. */
export function envLine(env: ServiceEnvironment | null | undefined): string | null {
  if (!env) return null;
  const parts: string[] = [];
  if (env.sour_service) parts.push("sour gas");
  if (env.corrosive) parts.push("corrosive");
  if (env.medium && !(env.sour_service && /sour|h2s|h₂s/i.test(env.medium))) parts.push(env.medium);
  if (env.max_temp_c != null) parts.push(`up to ${env.max_temp_c} °C`);
  if (env.min_temp_c != null) parts.push(`down to ${env.min_temp_c} °C`);
  if (env.pressure_bar != null) parts.push(`${env.pressure_bar} bar`);
  if (env.standard) parts.push(env.standard);
  return parts.length ? parts.join(", ") : null;
}
