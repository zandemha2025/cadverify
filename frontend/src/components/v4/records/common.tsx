"use client";

/**
 * Pieces the record screens share: the toast, the part glyph, the inline
 * confirm strip (Esc cancels), the public-link block, a modal dialog, and the
 * board P8 states (loading, couldn't load, none yet, not found, load more).
 */
import * as React from "react";
import { World } from "../ui";
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

export function PublicLink({
  shareUrl,
  canShare,
  blurb,
  onCreate,
  onTurnOff,
  toast,
}: {
  shareUrl: string | null;
  canShare: boolean;
  blurb: string;
  onCreate: () => Promise<unknown>;
  onTurnOff: () => Promise<unknown>;
  toast: (m: string) => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [asking, setAsking] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const full = shareUrl ? (typeof window !== "undefined" && shareUrl.startsWith("/") ? window.location.origin + shareUrl : shareUrl) : null;
  React.useEffect(() => {
    setCopied(false);
    setAsking(false);
  }, [shareUrl]);

  const create = async () => {
    setBusy(true);
    setErr(null);
    try {
      await onCreate();
      toast("Link created");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The link wasn't created.");
    } finally {
      setBusy(false);
    }
  };
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
      toast("Link turned off");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The link is still on.");
      setAsking(false);
    }
  };

  return (
    <>
      <div className="gh">
        <span>Public link</span>
        <span>{shareUrl ? "On" : "Off"}</span>
      </div>
      {!shareUrl ? (
        canShare ? (
          <div className="bar2">
            <button type="button" className="btn sm" onClick={create} disabled={busy}>
              {busy ? "Creating…" : "Create link"}
            </button>
            <span>{blurb}</span>
          </div>
        ) : (
          <p className="ro-note">No public link. Analysts and admins create links.</p>
        )
      ) : (
        <>
          <label className="link">
            Link
            <input type="text" readOnly value={full ?? ""} onFocus={(e) => e.currentTarget.select()} />
          </label>
          {asking ? (
            <Confirm label="Turn off link" question="Turn off the link? It stops working right away." action="Turn off" onConfirm={off} onCancel={() => setAsking(false)} />
          ) : (
            <div className="bar2">
              <button type="button" className="btn sm" onClick={copy}>
                {copied ? "Copied" : "Copy link"}
              </button>
              <a className="btn sm" href={full ?? "#"} target="_blank" rel="noopener noreferrer">
                Open
              </a>
              {canShare ? (
                <button type="button" className="btn sm ghost" onClick={() => setAsking(true)}>
                  Turn off
                </button>
              ) : null}
            </div>
          )}
        </>
      )}
      {err ? (
        <p className="err2" role="alert">
          {err}
        </p>
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
