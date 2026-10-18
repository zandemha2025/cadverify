"use client";

/**
 * Page frame for the Account screens: the v4 world (stage backdrop) with a
 * phone fix (the stage stays a backdrop instead of a 480px block), the page
 * head with the Account tabs, and small shared pieces (banner, inline confirm,
 * part glyph, copy button). Same markup as `World` in ../ui.tsx plus a class.
 */
import * as React from "react";
import { PageHead, cx } from "../ui";
import { TABS } from "../routes";
import "./account.css";

export function AccountFrame({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <main className="world a-page" aria-label={label}>
      <div className="stage" aria-hidden="true" />
      {children}
    </main>
  );
}

export function AccountHead({ title, meta, wide }: { title: string; meta?: React.ReactNode[]; wide?: boolean }) {
  return <PageHead title={title} meta={meta} tabs={TABS.account} tabsLabel="Account" wide={wide} />;
}

/** A page-level message with optional buttons on the right. */
export function Banner({
  tone = "bad",
  title,
  children,
  actions,
  alert = true,
}: {
  tone?: "bad" | "ok" | "plain";
  title: string;
  children?: React.ReactNode;
  actions?: React.ReactNode;
  alert?: boolean;
}) {
  return (
    <div className={cx("a-banner", tone !== "plain" && tone)} role={alert ? "alert" : "status"}>
      <span>
        <b>{title}</b> {children}
      </span>
      {actions ? <span className="a-bx">{actions}</span> : null}
    </div>
  );
}

/**
 * The boards' inline confirm: a question, what happens, the action and Cancel.
 * Focus moves to the confirm button when it opens; Esc cancels.
 */
export function Confirm({
  label,
  question,
  detail,
  confirmLabel,
  danger,
  busy,
  blocked,
  error,
  onConfirm,
  onCancel,
}: {
  label: string;
  question: string;
  detail?: React.ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  /** The action can't succeed (say why in `error`); only Cancel is offered. */
  blocked?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = React.useRef<HTMLButtonElement>(null);
  const cancelRef = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    (blocked ? cancelRef : ref).current?.focus();
    // Focus once, when the confirm opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div
      className="a-confirm"
      role="alertdialog"
      aria-label={label}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !busy) {
          e.stopPropagation();
          onCancel();
        }
      }}
    >
      <b>{question}</b>
      {detail ? <span>{detail}</span> : null}
      {error ? (
        <span className="a-err" role="alert">
          {error}
        </span>
      ) : null}
      <span className="a-bx">
        {blocked ? null : (
          <button ref={ref} className={cx("btn sm", danger ? "a-danger" : "ink")} type="button" onClick={onConfirm} disabled={busy} aria-busy={busy}>
            {busy ? "Working…" : confirmLabel}
          </button>
        )}
        <button ref={cancelRef} className="btn sm" type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </span>
    </div>
  );
}

/** Copy a value; the label turns to "Copied" for a moment. */
export function CopyButton({ value, label = "Copy", ariaLabel, className = "btn sm" }: { value: string; label?: string; ariaLabel?: string; className?: string }) {
  const [state, setState] = React.useState<"idle" | "copied" | "failed">("idle");
  React.useEffect(() => {
    if (state === "idle") return;
    const t = window.setTimeout(() => setState("idle"), 1600);
    return () => window.clearTimeout(t);
  }, [state]);
  return (
    <button
      className={className}
      type="button"
      aria-label={ariaLabel}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setState("copied");
        } catch {
          setState("failed");
        }
      }}
    >
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : label}
    </button>
  );
}

/** The neutral part glyph where a part's preview would go (lists don't fetch meshes). */
export function PartGlyph({ large }: { large?: boolean }) {
  const s = large ? 28 : 22;
  return (
    <span className={cx("a-th", large && "lg")} aria-hidden="true">
      <svg width={s} height={s} viewBox="0 0 26 26" fill="none">
        <path d="M13 2.6 22.4 8v10L13 23.4 3.6 18V8L13 2.6Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        <path d="M3.6 8 13 13.4 22.4 8M13 13.4v10" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

/** "Admins only" body for a panel the viewer's role can't use. */
export function AdminsOnly({ what, role }: { what: string; role?: string | null }) {
  return (
    <div className="empty" style={{ padding: "18px 24px" }}>
      <b>Admins only</b>
      <span>
        {what}
        {role ? ` Your org role is ${role}.` : ""}
      </span>
    </div>
  );
}
