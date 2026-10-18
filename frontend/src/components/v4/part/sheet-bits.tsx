"use client";

/** Pieces every lens sheet shares: the header (question, facts, figures) and the run notice. */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { cx } from "../ui";
import { usePart } from "./ctx";
import { MATERIAL_CLASS_LABEL } from "./model";
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

/** Interrupted check, or prices that didn't finish: what's kept and how to retry. */
export function RunNotice() {
  const p = usePart();
  if (p.interrupted) {
    return (
      <div className="note swap" role="alert" style={{ marginTop: 8 }}>
        <b>The service was busy</b>
        <span>This check didn’t start routing, DFM or prices. Wait a moment and retry; the file doesn’t need re-exporting. Saved results are unchanged.</span>
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn ink sm" type="button" onClick={() => p.recheck()} disabled={!p.canRecheck}>
            Retry check
          </button>
          <Link className="btn sm ghost" href={R.billing}>
            Usage and plans
          </Link>
        </span>
      </div>
    );
  }
  if (p.costOff) {
    return (
      <div className="note swap" role="alert" style={{ marginTop: 8 }}>
        <b>Prices didn’t finish</b>
        <span>Methods, findings and machine fit are ready and kept. Only prices need another try.</span>
        {p.data.costError ? <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{p.data.costError}</span> : null}
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn ink sm" type="button" onClick={p.retryPrices} disabled={!p.canRecheck || !!p.session?.costRetrying}>
            {p.session?.costRetrying ? "Retrying prices…" : "Retry prices"}
          </button>
          <button className="btn sm" type="button" onClick={() => p.recheck()} disabled={!p.canRecheck}>
            Check again from the start
          </button>
          <Link className="btn sm ghost" href={R.billing}>
            Usage and plans
          </Link>
        </span>
        {!p.canRecheck ? <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Drop the file on the part to retry; this page doesn’t keep it.</span> : null}
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
