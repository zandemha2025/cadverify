"use client";

/**
 * Empty, loading and error states for v4 list pages (board P8). Generic: any
 * screen (Home, Parts, Records, Analyses, Compare, Packages, Programs, shared
 * links) can use them. Copy is facts, not apology; every failed load can retry.
 */
import * as React from "react";
import Link from "next/link";
import "./home.css";

/** Part of a page didn't load: names what's missing, says the rest is complete, offers Retry. */
export function PartialAlert({ missing, rest, onRetry, busy }: { missing: string[]; rest?: string; onRetry: () => void; busy?: boolean }) {
  if (!missing.length) return null;
  return (
    <div className="h-alert" role="alert">
      <b>Couldn&apos;t load {joinAnd(missing)}.</b>
      {rest ? <span>{rest}</span> : null}
      <span className="h-row">
        <button type="button" className="btn sm ink" onClick={onRetry} disabled={busy}>
          {busy ? "Retrying…" : "Retry"}
        </button>
      </span>
    </div>
  );
}

/** A whole list failed: "Couldn't load records" + the server's message + Retry. */
export function ListFailed({ what, detail, onRetry }: { what: string; detail?: string | null; onRetry: () => void }) {
  return (
    <div className="empty" role="alert">
      <b>Couldn&apos;t load {what}</b>
      {detail ? <span>{detail}</span> : null}
      <span style={{ display: "flex", gap: 8, marginTop: 6 }}>
        <button type="button" className="btn sm ink" onClick={onRetry}>
          Retry
        </button>
      </span>
    </div>
  );
}

/** A compact failed-load strip inside a panel ("Couldn't load parts." + Retry). */
export function InlineFailed({ what, detail, onRetry }: { what: string; detail?: string | null; onRetry: () => void }) {
  return (
    <div className="h-alert" role="alert">
      <b>Couldn&apos;t load {what}.</b>
      {detail ? <span>{detail}</span> : null}
      <span className="h-row">
        <button type="button" className="btn sm ink" onClick={onRetry}>
          Retry
        </button>
      </span>
    </div>
  );
}

/** Nothing yet: what will appear here and the one action that makes it appear. */
export function NoneYet({ title, children, actions }: { title: string; children?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {children ? <span>{children}</span> : null}
      {actions ? <span style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap", justifyContent: "center" }}>{actions}</span> : null}
    </div>
  );
}

/** A link to one thing that isn't there: "Record not found" + Back + Retry. */
export function NotFound({ title, children, back, onRetry }: { title: string; children?: React.ReactNode; back: { label: string; href: string }; onRetry?: () => void }) {
  return (
    <div className="empty" role="alert">
      <b>{title}</b>
      {children ? <span>{children}</span> : null}
      <span style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap", justifyContent: "center" }}>
        <Link className="btn sm" href={back.href}>
          {back.label}
        </Link>
        {onRetry ? (
          <button type="button" className="btn sm ink" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </span>
    </div>
  );
}

/** Footer of a paged list: "50 shown" (or "50 of 120") and Load more while there's more. */
export function LoadMore({ shown, total, more, loading, onMore, label = "Load more" }: { shown: number; total?: number | null; more: boolean; loading?: boolean; onMore: () => void; label?: string }) {
  return (
    <div className="h-more">
      <span className="num" aria-live="polite">
        {total != null ? `${shown.toLocaleString("en-US")} of ${total.toLocaleString("en-US")}` : `${shown.toLocaleString("en-US")} shown`}
      </span>
      {more ? (
        <button type="button" className="btn sm" onClick={onMore} disabled={loading}>
          {loading ? "Loading…" : label}
        </button>
      ) : null}
    </div>
  );
}

/** Any list loading: a few pulsing bars, announced once. */
export function Skeleton({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  const widths = [70, 52, 64, 40, 58, 46];
  return (
    <div className="h-skel" role="status" aria-busy="true" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="h-sk" style={{ width: `${widths[i % widths.length]}%` }} aria-hidden="true" />
      ))}
    </div>
  );
}

/** A public shared link that was turned off (or never existed). No app nav: these pages are public. */
export type LinkOffReason = "off" | "expired" | "missing" | "error";

/** Why a shared link shows nothing: switched off, expired, unknown, or not reachable. No record data. */
export function linkOffWords(reason: LinkOffReason, endedOn: string): { title: string; body: string } {
  if (reason === "expired") return { title: "This link has expired", body: `${endedOn ? `It ended on ${endedOn}. ` : ""}Ask whoever sent it for a new one.` };
  if (reason === "off") return { title: "This link was switched off", body: `${endedOn ? `It was switched off on ${endedOn}. ` : ""}Ask whoever sent it for a new one.` };
  if (reason === "error") return { title: "This link couldn't be opened", body: "ScaleCAD didn't answer. Try again in a minute." };
  return { title: "This link isn't available", body: "It may have ended, been switched off, or the part was deleted. Ask whoever sent it for a new one." };
}

/** `cta={false}` on a supplier's page: the link was the buyer's, so no "Go to ScaleCAD" (buyer-14). */
export function LinkOff({ home = "/", reason = "off", endedOn = "", cta = true }: { home?: string; reason?: LinkOffReason; endedOn?: string; cta?: boolean }) {
  const w = linkOffWords(reason, endedOn);
  return (
    <div className="empty" role="alert">
      <b>{w.title}</b>
      <span>{w.body}</span>
      {cta ? (
        <span style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <Link className="btn sm ink" href={home}>
            Go to ScaleCAD
          </Link>
        </span>
      ) : null}
    </div>
  );
}

export function joinAnd(xs: string[]): string {
  if (xs.length <= 1) return xs.join("");
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}
