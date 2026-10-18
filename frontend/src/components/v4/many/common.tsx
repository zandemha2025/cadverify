"use client";

/**
 * Pieces shared by the Many parts screens: the toast line, the pilot gate
 * (board X5) for accounts without the pilot plan, a confirm dialog with focus
 * handling, the file-type thumb, and blob downloads.
 */
import * as React from "react";
import Link from "next/link";
import { listBatches } from "@/lib/api/batch";
import { TABS } from "../routes";
import { Content, Sheet, World, cx } from "../ui";
import "./many.css";

/* ------------------------------------------------------------------ */
/*  World                                                              */
/* ------------------------------------------------------------------ */

/**
 * The foundation World plus a marker that scopes this area's phone fixes
 * (many.css): no empty 3D stage above the page, and no `top` offset on the
 * content once it flows in the page.
 */
export function ManyWorld({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <World label={label}>
      <i className="mm-mark" hidden />
      {children}
    </World>
  );
}

/* ------------------------------------------------------------------ */
/*  Toast                                                              */
/* ------------------------------------------------------------------ */

/** One toast line at a time. Returns the node to render inside the World and a `show(text)` function. */
export function useToast(): [React.ReactNode, (text: string) => void] {
  const [text, setText] = React.useState("");
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const show = React.useCallback((t: string) => {
    setText(t);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setText(""), 3600);
  }, []);
  React.useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const node = (
    <div className="tst" aria-live="polite">
      {text ? (
        <div className="toast" role="status">
          {text}
        </div>
      ) : null}
    </div>
  );
  return [node, show];
}

/* ------------------------------------------------------------------ */
/*  Pilot access                                                       */
/* ------------------------------------------------------------------ */

export type PilotAccess = "loading" | "pilot" | "gated" | "unknown";

/**
 * Whether this account has the pilot plan. Many parts tools are pilot-plan only;
 * the server enforces it (403 paid_access_required), this only decides whether
 * to show the gate up front instead of letting a screen fail. An unreadable plan
 * is "unknown": the screen renders and the server answers for itself.
 */
export function usePilotAccess(): [PilotAccess, () => void] {
  const [access, setAccess] = React.useState<PilotAccess>("loading");
  React.useEffect(() => {
    let live = true;
    fetch("/api/auth/me/usage", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((u: { plan?: string } | null) => {
        if (!live) return;
        if (!u || typeof u.plan !== "string") setAccess("unknown");
        else setAccess(u.plan === "pilot" ? "pilot" : "gated");
      })
      .catch(() => live && setAccess("unknown"));
    return () => {
      live = false;
    };
  }, []);
  const gate = React.useCallback(() => setAccess("gated"), []);
  return [access, gate];
}

/** True for the server's pilot-plan refusal, whatever shape the error took on the way here. */
export function isPaidAccessError(err: unknown): boolean {
  if (!err) return false;
  const e = err as { code?: string; message?: string };
  if (e.code === "paid_access_required") return true;
  return typeof e.message === "string" && /paid_access_required|part of a pilot or Enterprise plan/i.test(e.message);
}

/** "Saved results are unchanged." plus the server's message, without saying "unchanged" twice. */
export function unchanged(lead: string, msg: string | null | undefined): string {
  if (!msg) return lead;
  return /unchanged/i.test(msg) ? msg : `${lead} ${msg}`;
}

export function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

const LOCK = (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <rect x="3" y="7" width="10" height="7" rx="1.6" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

/** Board X5: what the tool does, locked, with the pilot plan and how to get it. */
export function PilotGate({
  title,
  slot,
  features,
  inputs,
  tab = 0,
}: {
  title: string;
  slot: string;
  features: { title: string; text: string; tone: string }[];
  inputs: string[];
  /** Which Many parts tab is current (0 Batches, 1 Triage, 2 Imports). */
  tab?: number;
}) {
  return (
    <ManyWorld label={title}>
      <div className="pagehead">
        <h1 className="ptitle">{title}</h1>
        <p className="pmeta" style={{ marginTop: 6 }}>
          <span>
            <b>Pilot plan</b>
          </span>
          <span>Your plan: single-part checks</span>
        </p>
        <nav className="subnav" aria-label="Many parts">
          {TABS.many.map((t, i) => (
            <Link key={t.href} href={t.href} className={cx(i === tab && "on")} aria-current={i === tab ? "page" : undefined}>
              {t.label}
            </Link>
          ))}
        </nav>
      </div>
      <Content>
        <div className="slot">
          <span className="lab">{slot}</span>
          <span className="lock">{LOCK}Pilot</span>
          <svg width="150" height="120" viewBox="0 0 150 120" fill="none" aria-hidden="true">
            <rect x="34" y="14" width="82" height="96" rx="10" fill="#fff" stroke="rgba(20,24,31,.16)" strokeWidth="2" />
            <rect x="24" y="24" width="82" height="86" rx="10" fill="#fff" stroke="rgba(20,24,31,.2)" strokeWidth="2" />
            <rect x="14" y="34" width="82" height="76" rx="10" fill="#fff" stroke="rgba(20,24,31,.28)" strokeWidth="2" />
            <path d="M34 62h42M34 74h30M34 86h36" stroke="rgba(20,24,31,.2)" strokeWidth="4" strokeLinecap="round" />
          </svg>
        </div>
        <div className="three">
          {features.map((f) => (
            <div key={f.title} className="panel">
              <i style={{ background: f.tone }} aria-hidden="true" />
              <b>{f.title}</b>
              <span>{f.text}</span>
            </div>
          ))}
        </div>
        <p className="pmeta">
          {inputs.map((x) => (
            <span key={x}>{x}</span>
          ))}
        </p>
      </Content>
      <Sheet label="Get access" style={{ bottom: "auto" }}>
        <div className="top">
          <h2 className="stitle">Pilot plan</h2>
          <p className="smeta">$7,500 · 4–6 weeks · up to 500 parts · one factory</p>
        </div>
        <div className="gh">
          <span>Includes</span>
          <span />
        </div>
        <div className="inc">
          <span>Batch runs</span>
          <span>Triage and capability changes</span>
          <span>Imports and BOM preview</span>
          <span>Fit in context</span>
          <span>Assemblies and file repair</span>
          <span>Recalibration from real costs</span>
        </div>
        <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap" }}>
          <Link className="btn ink" href="/pilot#pilot">
            Request access
          </Link>
          <Link className="btn" href="/pricing">
            Plan pilot
          </Link>
        </div>
        <p style={{ margin: "0 12px 16px", color: "var(--ink3)", fontSize: 12.5 }}>Pro adds checks only. Pilot tools aren’t included.</p>
      </Sheet>
    </ManyWorld>
  );
}

/* ------------------------------------------------------------------ */
/*  Tabs with the batch count                                          */
/* ------------------------------------------------------------------ */

/** The Many parts tabs, with the number of batches on "Batches" once it is known (and exact). */
export function useManyTabs(known?: { count: number; exact: boolean } | null) {
  const [own, setOwn] = React.useState<{ count: number; exact: boolean } | null>(null);
  const need = known === undefined;
  React.useEffect(() => {
    if (!need) return;
    let live = true;
    listBatches({ limit: 100 })
      .then((r) => live && setOwn({ count: r.batches.length, exact: !r.has_more }))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [need]);
  const c = need ? own : known;
  return TABS.many.map((t, i) => (i === 0 && c && c.exact ? { ...t, count: c.count } : t));
}

/* ------------------------------------------------------------------ */
/*  Confirm dialog                                                     */
/* ------------------------------------------------------------------ */

/**
 * A modal confirm (role=alertdialog). Focus moves to the safe choice, Tab stays
 * inside, Esc and the scrim take the safe choice, and focus returns to whatever
 * opened it.
 */
export function ConfirmDialog({
  title,
  text,
  keepLabel,
  confirmLabel,
  busy,
  onKeep,
  onConfirm,
}: {
  title: string;
  text: string;
  keepLabel: string;
  confirmLabel: string;
  busy?: boolean;
  onKeep: () => void;
  onConfirm: () => void;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const keepRef = React.useRef<HTMLButtonElement>(null);
  const tid = React.useId();
  React.useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    keepRef.current?.focus();
    return () => {
      if (back && document.contains(back)) back.focus();
    };
  }, []);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      if (!busy) onKeep();
      return;
    }
    if (e.key === "Tab" && ref.current) {
      const f = Array.from(ref.current.querySelectorAll<HTMLElement>("button:not([disabled])"));
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };
  return (
    <>
      <button className="scrim" type="button" tabIndex={-1} aria-label={keepLabel} onClick={() => !busy && onKeep()} />
      <div ref={ref} className="dlg" role="alertdialog" aria-modal="true" aria-labelledby={tid + "t"} aria-describedby={tid + "d"} onKeyDown={onKey}>
        <div className="dh">
          <h2 id={tid + "t"}>{title}</h2>
        </div>
        <div className="db">
          <p id={tid + "d"}>{text}</p>
        </div>
        <div className="df">
          <button ref={keepRef} className="btn" type="button" onClick={onKeep} disabled={busy}>
            {keepLabel}
          </button>
          <button className="btn danger" type="button" onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Small things                                                       */
/* ------------------------------------------------------------------ */

/** A file-type tile where a part picture would go (no thumbnails are stored for these parts). */
export function Thumb({ name, className }: { name: string | null | undefined; className?: string }) {
  const ext = (name ?? "").split(".").pop()?.slice(0, 4) ?? "";
  return (
    <span className={cx("th2", className)} aria-hidden="true">
      {ext && ext !== name ? ext : "CAD"}
    </span>
  );
}

/** On phone widths the sheet sits below the page: bring it into view after a pick that changes it. */
export function revealSheetOnPhone(label: string): void {
  if (typeof window === "undefined" || window.innerWidth > 900) return;
  requestAnimationFrame(() => document.querySelector(`.ob .sheet[aria-label="${label}"]`)?.scrollIntoView({ block: "start" }));
}

/** Saves a blob under `filename` through a temporary link. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** "Today 17:40", "Yesterday 09:03", "Oct 12, 09:03", "Oct 12, 2025". */
export function whenLabel(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const time = d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  if (diff === 0) return `Today ${time}`;
  if (diff === 1) return `Yesterday ${time}`;
  const sameYear = d.getFullYear() === now.getFullYear();
  return sameYear
    ? `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
