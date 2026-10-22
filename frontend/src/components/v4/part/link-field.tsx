"use client";

/**
 * "Paste a link": a share link to one CAD file (Google Drive, Dropbox,
 * OneDrive or SharePoint, an S3 presigned URL) instead of a file from this
 * computer. The server fetches it and checks it on the worker
 * (stored-check.ts startLinkCheck); nothing downloads to this browser.
 *
 * The field names the link's source as it is pasted and says at once when a
 * link plainly can't be imported (the server applies the real rules). Shown
 * only where the server has link import on (GET /uploads/from-link).
 */
import * as React from "react";
import { API_BASE } from "@/lib/api-base";
import { readLink } from "@/lib/link-import";
import { cx } from "../ui";
import "./link-field.css";

let enabledOnce: Promise<boolean> | null = null;

function fetchEnabled(): Promise<boolean> {
  enabledOnce ??= fetch(`${API_BASE}/uploads/from-link`, { cache: "no-store", signal: AbortSignal.timeout(10_000) })
    .then((r) => (r.ok ? r.json() : null))
    .then((b: { enabled?: boolean } | null) => b?.enabled === true)
    .catch(() => {
      enabledOnce = null; // ask again next time
      return false;
    });
  return enabledOnce;
}

/** Whether this server imports from links (asked once per page load). */
export function useLinkImportEnabled(): boolean {
  const [on, setOn] = React.useState(false);
  React.useEffect(() => {
    let live = true;
    void fetchEnabled().then((v) => live && setOn(v));
    return () => {
      live = false;
    };
  }, []);
  return on;
}

export function LinkForm({
  onSubmit,
  onCancel,
  className,
  compact,
}: {
  onSubmit: (url: string) => void;
  onCancel: () => void;
  className?: string;
  /** Home's drop box: one line of help, smaller controls. */
  compact?: boolean;
}) {
  const [url, setUrl] = React.useState("");
  const [tried, setTried] = React.useState(false);
  const field = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => field.current?.focus(), []);
  const read = url.trim() ? readLink(url) : null;
  const problem = read && !read.ok ? read.message : null;
  const showProblem = !!problem && (tried || /^https?:\/\/\S+\.\S+/i.test(url.trim()));
  const hint = read?.ok
    ? `${read.label} link${read.nameHint ? ` · ${read.nameHint}` : ""} · ScaleCAD fetches it on the server`
    : "Google Drive, Dropbox, OneDrive or SharePoint share link, or an S3 presigned URL";
  return (
    <form
      className={cx("lf", compact && "lf-compact", className)}
      aria-label="Paste a link"
      onSubmit={(e) => {
        e.preventDefault();
        setTried(true);
        if (read?.ok) onSubmit(url.trim());
        else field.current?.focus();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onCancel();
      }}
    >
      <label className="lf-row">
        <span className="sr">Share link</span>
        <input
          ref={field}
          type="url"
          inputMode="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.dropbox.com/s/…/bracket.step"
          spellCheck={false}
          autoComplete="off"
          aria-invalid={showProblem}
          aria-describedby="lf-hint"
        />
      </label>
      <em id="lf-hint" className={cx("lf-hint", showProblem && "bad")} role={showProblem ? "alert" : undefined}>
        {showProblem ? problem : hint}
      </em>
      <span className="lf-acts">
        <button className={cx("btn ink", compact && "sm")} type="submit" disabled={!url.trim()}>
          Check it
        </button>
        <button className={cx("btn", compact && "sm")} type="button" onClick={onCancel}>
          Cancel
        </button>
      </span>
      {compact ? null : <em className="lf-note">The file must be shared so anyone with the link can open it.</em>}
    </form>
  );
}
