"use client";

/**
 * Pieces shared by the Make and fit screens (boards F1, F2, F4, X5): the world
 * these screens render in (scoped as `.mk` so their board-local classes can't
 * meet another area's), the page head with the Make and fit tabs (Fit in context
 * carries its Pilot tag, and a tools slot sits beside the tabs), one toast line,
 * the account's plan, and the pilot gate.
 */
import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { R, TABS } from "../routes";
import { useShell } from "../shell";
import { cx } from "../ui";
import "./make.css";

export function MakeWorld({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <main className="world mk" aria-label={label}>
      <div className="stage" aria-hidden="true" />
      {children}
    </main>
  );
}

/** Title, facts, the Make and fit tabs, and optional tools on the tabs row. */
export function MakeHead({ title, meta, tools }: { title: string; meta?: React.ReactNode[]; tools?: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const current = TABS.make
    .filter((t) => pathname === t.href || pathname.startsWith(t.href + "/"))
    .sort((a, b) => b.href.length - a.href.length)[0];
  return (
    <div className="pagehead">
      <h1 className="ptitle">{title}</h1>
      {meta && meta.length ? (
        <p className="pmeta">
          {meta.map((m, i) => (
            <span key={i}>{m}</span>
          ))}
        </p>
      ) : null}
      <div className="hrow">
        <nav className="subnav" aria-label="Make and fit">
          {TABS.make.map((t) => (
            <Link key={t.href} href={t.href} className={cx(t === current && "on")} aria-current={t === current ? "page" : undefined}>
              {t.label}
              {t.href === R.fit ? <b>Pilot</b> : null}
            </Link>
          ))}
        </nav>
        {tools ? <div className="tools">{tools}</div> : null}
      </div>
    </div>
  );
}

/** One toast line at a time. Returns the node to render inside the world and `show(text)`. */
export function useToast(): [React.ReactNode, (text: string) => void] {
  const [text, setText] = React.useState("");
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const show = React.useCallback((t: string) => {
    setText(t);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setText(""), 3600);
  }, []);
  React.useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
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

/** "pilot" | "other" | null while unknown. The server stays the authority; this only picks what to show. */
export function usePlan(): "pilot" | "other" | null {
  const { usage } = useShell();
  if (!usage || typeof usage.plan !== "string") return null;
  return usage.plan === "pilot" ? "pilot" : "other";
}

/** True for the server's pilot-plan refusal, whatever shape the error took. */
export function isPaidAccessError(err: unknown): boolean {
  if (!err) return false;
  const e = err as { code?: string; message?: string; status?: number };
  if (e.code === "paid_access_required") return true;
  return typeof e.message === "string" && /paid_access_required|part of a pilot or Enterprise plan/i.test(e.message);
}

export function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export const LOCK = (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <rect x="3" y="7" width="10" height="7" rx="1.6" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

/** What the pilot plan includes (board X5), with the two ways to get it. */
export function PilotPlanCard({ includes, note = "Pro adds checks only. Pilot tools aren’t included." }: { includes: string[]; note?: string }) {
  return (
    <>
      <div className="top">
        <h2 className="stitle">Pilot plan</h2>
        <p className="smeta">$7,500 · 4–6 weeks · up to 500 parts · one factory</p>
      </div>
      <div className="gh">
        <span>Includes</span>
        <span />
      </div>
      <div className="inc">
        {includes.map((x) => (
          <span key={x}>{x}</span>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap" }}>
        <Link className="btn ink" href="/pilot#pilot">
          Request access
        </Link>
        <Link className="btn" href="/pricing">
          Plan pilot
        </Link>
      </div>
      <p className="fine" style={{ marginBottom: 16 }}>
        {note}
      </p>
    </>
  );
}

export const PILOT_INCLUDES = ["Fit in context", "Batch runs", "Assemblies", "File repair", "Design Studio", "Recalibration from real costs"];
