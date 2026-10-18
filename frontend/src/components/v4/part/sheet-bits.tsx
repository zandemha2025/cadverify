"use client";

/** Pieces every lens sheet shares: the header (question, facts, figures) and the run notice. */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { useShell } from "../shell";
import { cx } from "../ui";
import { usePart } from "./ctx";
import { MATERIAL_CLASS_LABEL } from "./model";
import { CheckInterruptedBanner, CostBlockedBanner, CostFailedBanner } from "../moments";
import { isQuotaErrorMessage } from "@/lib/api-recovery";
import type { ServiceEnvironment } from "@/lib/verify/part-context";

export interface FigItem {
  k: string;
  v: string;
  s?: string;
  tone?: "ok" | "warn" | "bad";
}

export function SheetTop({ title, meta, figs }: { title: string; meta: string; figs: FigItem[] }) {
  return (
    <div className="top">
      <h2 className="stitle">{title}</h2>
      <p className="smeta">{meta}</p>
      <div className="figs" aria-live="polite">
        {figs.map((g) => (
          <div className="fig" key={g.k}>
            <span>{g.k}</span>
            <b className={cx("num", g.tone, !/^[$\d≈]/.test(g.v) && "t")}>{g.v}</b>
            {g.s ? <small>{g.s}</small> : null}
          </div>
        ))}
      </div>
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
        <CheckInterruptedBanner onRetry={() => p.recheck()} detail="No result. Routing, checks and cost didn’t start. Wait a moment and retry; the file doesn’t need re-exporting. Saved results are unchanged." />
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
            detail={p.session?.costRetrying ? "Retrying cost…" : ["Routing and process checks are ready.", err].filter(Boolean).join(" ")}
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
