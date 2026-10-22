"use client";

/** Pieces every view's sheet shares: the header (question, facts, figures, how sure it is) and the run notice. */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { useShell } from "../shell";
import { cx } from "../ui";
import { usePart } from "./ctx";
import { MATERIAL_CLASS_LABEL } from "./model";
import { inText } from "../units/units";
import { useUnits } from "../units/use-units";
import { sureOf, type SureLens } from "./sure";
import { CheckInterruptedBanner, CostBlockedBanner, CostFailedBanner } from "../moments";
import { isQuotaErrorMessage } from "@/lib/api-recovery";
import type { ServiceEnvironment } from "@/lib/verify/part-context";

export interface FigItem {
  k: string;
  v: string;
  s?: string;
  tone?: "ok" | "warn" | "bad";
}

export function SheetTop({ title, meta, figs, sure }: { title: string; meta: string; figs: FigItem[]; sure?: SureLens }) {
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
      {sure ? <SureLine lens={sure} /> : null}
    </div>
  );
}

const SURE_SRC: Record<string, string> = { file: "Your file", yours: "Yours", typ: "Typical" };
const SURE_TO = { rates: R.rates, actuals: R.actuals, machines: `${R.shop}?add=1`, conditions: null } as const;

/** "How sure is this?": what the answer above rests on, one line by default and the detail one click away. */
function SureLine({ lens }: { lens: SureLens }) {
  const p = usePart();
  const [open, setOpen] = React.useState(false);
  const id = React.useId();
  const sure = React.useMemo(
    () => (p.checking || p.interrupted ? null : sureOf(lens, { validation: p.data.validation, cost: p.data.cost, machines: p.data.machines, env: p.data.runEnvironment, methods: p.methods, q: p.q })),
    [lens, p.checking, p.interrupted, p.data.validation, p.data.cost, p.data.machines, p.data.runEnvironment, p.methods, p.q],
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
export function RunNotice() {
  const p = usePart();
  const shell = useShell();
  const usage = (
    <p className="pmeta" style={{ marginTop: 6 }}>
      <Link href={R.billing}>Usage and plans</Link>
    </p>
  );
  if (p.interrupted) {
    return (
      <div className="swap" style={{ marginTop: 8 }}>
        <CheckInterruptedBanner onRetry={() => p.recheck()} detail="No result. The process checks and cost didn’t start. Wait a moment and retry; the file doesn’t need re-exporting. Saved results are unchanged." />
        {usage}
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
            detail={p.session?.costRetrying ? "Retrying cost…" : ["The process checks are ready.", err].filter(Boolean).join(" ")}
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
