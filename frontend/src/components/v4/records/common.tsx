"use client";

/**
 * Pieces the record screens share: the toast, the part glyph, the inline
 * confirm strip (Esc cancels), the public-link block, a modal dialog, and the
 * board P8 states (loading, couldn't load, none yet, not found, load more).
 */
import * as React from "react";
import Link from "next/link";
import { World } from "../ui";
import { endDateAddedNote, linkEndText, type LinkStatus } from "../datacontrol/words";
import { ShareDialog, type MadeLink, type PartFacts, type ShareTarget } from "../share/share-dialog";
import type { LinkPayload } from "../share/words";
import "./records.css";

/** The page frame, marked so this area's phone rules (wrapping panel heads) apply only here. */
export function RecWorld({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <World label={label}>
      <i className="rc-mark" hidden />
      {children}
    </World>
  );
}

/** The right sheet. These pages have no dial under them, so it runs to the bottom (and on phones ends with a plain margin). */
export function RecSheet({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <aside className="sheet rc-sheet" aria-label={label}>
      {children}
    </aside>
  );
}

/* ── toast ──────────────────────────────────────────────────────────────── */

export function useToast(): [React.ReactNode, (msg: string) => void] {
  const [msg, setMsg] = React.useState<{ text: string; n: number } | null>(null);
  React.useEffect(() => {
    if (!msg) return;
    const t = window.setTimeout(() => setMsg(null), 3200);
    return () => window.clearTimeout(t);
  }, [msg]);
  const show = React.useCallback((text: string) => setMsg((m) => ({ text, n: (m?.n ?? 0) + 1 })), []);
  const node = (
    <div className="rc-toastwrap" aria-live="polite" role="status">
      {msg ? (
        <div className="toast" key={msg.n}>
          {msg.text}
        </div>
      ) : null}
    </div>
  );
  return [node, show];
}

/* ── part glyph (no preview images exist for lists) ─────────────────────── */

export function Glyph({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <path d="M13 2.6 22.4 8v10L13 23.4 3.6 18V8L13 2.6Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M3.6 8 13 13.4 22.4 8M13 13.4v10" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

export function Thumb({ size = 44 }: { size?: number }) {
  return (
    <span className="th" aria-hidden="true" style={{ width: size, height: size, display: "grid", placeItems: "center", color: "var(--ink3)" }}>
      <Glyph size={Math.round(size / 2)} />
    </span>
  );
}

export function FileIcon({ dashed }: { dashed?: boolean }) {
  return (
    <svg width="14" height="16" viewBox="0 0 14 16" fill="none" aria-hidden="true">
      <path d="M2 1.5h6.5L12 5v9.5H2z" stroke={dashed ? "#8A9099" : "#5F656E"} strokeWidth="1.3" strokeDasharray={dashed ? "2 2" : undefined} strokeLinejoin="round" />
      {dashed ? null : <path d="M8.5 1.5V5H12" stroke="#5F656E" strokeWidth="1.3" strokeLinejoin="round" />}
    </svg>
  );
}

/* ── inline confirm (board `.conf`) ─────────────────────────────────────── */

/** "Withdraw the outcome? Approval reopens." [Withdraw] [Cancel]. Focus moves to Cancel; Esc cancels. */
export function Confirm({
  label,
  question,
  action,
  onConfirm,
  onCancel,
  inline,
}: {
  label: string;
  question: string;
  action: string;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
  inline?: boolean;
}) {
  const [busy, setBusy] = React.useState(false);
  const cancelRef = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    cancelRef.current?.focus();
  }, []);
  return (
    <div
      className={inline ? "conf in" : "conf"}
      role="alertdialog"
      aria-label={label}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !busy) {
          e.preventDefault();
          e.stopPropagation();
          onCancel();
        }
      }}
    >
      <b>{question}</b>
      <button
        type="button"
        className="btn sm ink"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Working…" : action}
      </button>
      <button ref={cancelRef} type="button" className="btn sm" onClick={onCancel} disabled={busy}>
        Cancel
      </button>
    </div>
  );
}

/* ── public link ────────────────────────────────────────────────────────── */

export interface LinkState {
  status?: LinkStatus | null;
  expiresAt?: string | null;
  endedAt?: string | null;
  endDateAdded?: boolean;
}

/** The link fields of a record or analysis answer, as PublicLink reads them. */
export function linkStateOf(d: unknown): LinkState {
  const x = (d ?? {}) as { share_status?: LinkStatus | null; share_expires_at?: string | null; share_ended_at?: string | null; share_end_date_added?: boolean };
  return { status: x.share_status ?? null, expiresAt: x.share_expires_at ?? null, endedAt: x.share_ended_at ?? null, endDateAdded: !!x.share_end_date_added };
}

/**
 * The record's public link. Share opens the Share dialog (../share): who can
 * open it, what they will see, and how long it lasts (7 days unless 1, 30 or
 * 90 days or a date); the person who made it (or an admin)
 * can switch it off, and the server says who may.
 */
export function PublicLink({
  shareUrl,
  canShare,
  blurb,
  target,
  loadPart,
  onCreate,
  onTurnOff,
  toast,
  link,
}: {
  shareUrl: string | null;
  canShare: boolean;
  blurb: string;
  /** What is shared (a record or a check), for the Share dialog. */
  target: ShareTarget;
  /** Reads a record's facts, so the dialog prefills its quantity and CAD. */
  loadPart?: () => Promise<PartFacts | null>;
  onCreate: (link: LinkPayload) => Promise<MadeLink>;
  onTurnOff: () => Promise<unknown>;
  toast: (m: string) => void;
  link?: LinkState;
}) {
  const [asking, setAsking] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const [dialog, setDialog] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const full = shareUrl ? (typeof window !== "undefined" && shareUrl.startsWith("/") ? window.location.origin + shareUrl : shareUrl) : null;
  React.useEffect(() => {
    setCopied(false);
    setAsking(false);
  }, [shareUrl]);

  const copy = async () => {
    if (!full) return;
    try {
      await navigator.clipboard.writeText(full);
      setCopied(true);
      toast("Link copied");
    } catch {
      toast("Copy didn't work. Select the link and copy it.");
    }
  };
  const off = async () => {
    setErr(null);
    try {
      await onTurnOff();
      setAsking(false);
      toast("Link switched off");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The link is still on.");
      setAsking(false);
    }
  };
  const ended = !shareUrl && (link?.status === "expired" || link?.status === "off");

  return (
    <>
      <div className="gh">
        <span>Public link</span>
        <span>{shareUrl ? (link?.status ? linkEndText("active", link.expiresAt ?? null) : "On") : ended ? linkEndText(link?.status, link?.expiresAt, link?.endedAt) : "Off"}</span>
      </div>
      {!shareUrl ? (
        canShare ? (
          <>
            {ended ? <p className="ro-note">{link?.status === "expired" ? "The last link has ended." : "The last link was switched off."} Anyone who opens it sees that.</p> : null}
            <div className="bar2">
              <button type="button" className="btn sm" onClick={() => setDialog(true)}>
                Share
              </button>
              <span>{blurb}</span>
            </div>
          </>
        ) : (
          <p className="ro-note">{ended ? `${linkEndText(link?.status, link?.expiresAt, link?.endedAt)}. ` : "No public link. "}Analysts and admins create links.</p>
        )
      ) : (
        <>
          <label className="link">
            Link
            <input type="text" readOnly value={full ?? ""} onFocus={(e) => e.currentTarget.select()} />
          </label>
          {link?.endDateAdded ? <p className="ro-note">{endDateAddedNote(link.expiresAt)}</p> : null}
          {asking ? (
            <Confirm label="Switch off link" question="Switch off the link? It stops working right away; anyone who opens it sees that it was switched off." action="Switch off" onConfirm={off} onCancel={() => setAsking(false)} />
          ) : (
            <div className="bar2">
              <button type="button" className="btn sm" onClick={copy}>
                {copied ? "Copied" : "Copy link"}
              </button>
              <a className="btn sm" href={full ?? "#"} target="_blank" rel="noopener noreferrer">
                Open
              </a>
              {canShare ? (
                <button type="button" className="btn sm ghost" onClick={() => setDialog(true)}>
                  New link
                </button>
              ) : null}
              {canShare ? (
                <button type="button" className="btn sm ghost" onClick={() => setAsking(true)}>
                  Switch off
                </button>
              ) : null}
              <Link className="btn sm ghost" href="/app/account/links">
                All your links
              </Link>
            </div>
          )}
        </>
      )}
      {err ? (
        <p className="err2" role="alert">
          {err}
        </p>
      ) : null}
      {dialog ? (
        <ShareDialog
          target={target}
          loadPart={loadPart}
          current={shareUrl ? { expiresAt: link?.expiresAt ?? null } : null}
          create={onCreate}
          onClose={() => setDialog(false)}
        />
      ) : null}
    </>
  );
}

/* ── dialog ─────────────────────────────────────────────────────────────── */

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const id = React.useId();
  React.useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button")?.focus();
    return () => back?.focus?.();
  }, []);
  return (
    <div className="rc-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        className="rc-dlg"
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onClose();
          }
          if (e.key === "Tab" && ref.current) {
            const f = [...ref.current.querySelectorAll<HTMLElement>("a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex='-1'])")];
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
        }}
      >
        <div className="hd">
          <h2 className="stitle" id={id}>
            {title}
          </h2>
          <button type="button" className="btn sm" onClick={onClose}>
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/* ── states (board P8): the shared ones from Home, plus this area's list footer ── */

export { ListFailed as LoadFailed, NoneYet, NotFound, Skeleton } from "../home/states";

/** "20 of 20 records" (or "50 shown") with Load more while the server has more. */
export function ListFoot({
  shown,
  loaded,
  noun,
  more,
  loading,
  onMore,
  error,
  hint,
}: {
  shown: number;
  loaded: number;
  noun: string;
  more: boolean;
  loading?: boolean;
  onMore: () => void;
  error?: string | null;
  hint?: string;
}) {
  return (
    <div className="foot num">
      <span aria-live="polite">
        {shown.toLocaleString("en-US")} of {loaded.toLocaleString("en-US")}
        {more ? "+" : ""} {noun}
        {more ? " loaded" : ""}
        {hint ? ` · ${hint}` : ""}
      </span>
      {more ? (
        <button type="button" className="btn sm" onClick={onMore} disabled={loading}>
          {loading ? "Loading…" : "Load more"}
        </button>
      ) : null}
      {error ? (
        <span role="alert" style={{ color: "var(--bad)", width: "100%" }}>
          {error}
        </span>
      ) : null}
    </div>
  );
}
