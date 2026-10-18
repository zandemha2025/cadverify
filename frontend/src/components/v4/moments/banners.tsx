"use client";

/**
 * Banners and notices (board X11). One `Banner` shape, and a ready-made banner
 * for every case on the board, so every screen says the same thing the same way.
 *
 * `<Banner tone title meta? actions? onDismiss? spin? />`
 * - `tone`      "bad" | "warn" | "ok" | "info". bad/warn are announced (role=alert), ok/info politely (role=status).
 * - `title`     the bold line; `meta` the fact line under it.
 * - `actions`   buttons/links on the right (use `className="btn ink sm"` for the main one).
 * - `onDismiss` shows the × (aria-label "Dismiss: <title>"). Leave it out where the banner must stay.
 * - `spin`      a spinner instead of the tone mark (loading).
 * - `name`      optional stable hook for tests (`data-notice`).
 *
 * Ready-made (all props are plain values and callbacks):
 * - Before a check: `SignedOutBanner`, `FreeChecksUsedBanner`, `BusyBanner`, `CantReadBanner`,
 *   `DesignImportBanner` (state "loading" | "done" | "error").
 * - During and after: `CheckInterruptedBanner`, `CostFailedBanner`, `CostBlockedBanner`, `ProBanner`,
 *   `PreviewFailed` (on the stage, where the part would be).
 * - Workspace: `OrgErrorBanner`, `NoActiveOrgBanner`, `NotInOrgBanner`,
 *   `PageError` (a page that fails to load: Retry, and Review usage only for allowance errors).
 */
import * as React from "react";
import Link from "next/link";
import { UpgradeButton } from "@/components/billing/upgrade-button";
import { isLifetimeQuotaErrorMessage, isQuotaErrorMessage } from "@/lib/api-recovery";
import { distinctErrorDetail } from "@/lib/error-copy";
import { loginHrefForReturnPath } from "@/lib/safe-return-path";
import { R } from "../routes";
import { cx } from "../ui";
import "./moments.css";

export type BannerTone = "bad" | "warn" | "ok" | "info";

const MARK: Record<BannerTone, string> = { bad: "!", warn: "!", ok: "✓", info: "i" };

const X = (
  <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

export function Banner({
  tone,
  title,
  meta,
  actions,
  onDismiss,
  spin,
  className,
  style,
  name,
}: {
  tone: BannerTone;
  title: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  onDismiss?: () => void;
  spin?: boolean;
  className?: string;
  style?: React.CSSProperties;
  name?: string;
}) {
  const label = typeof title === "string" ? title : "notice";
  return (
    <div className={cx("mo-bn", tone, onDismiss && "hx", className)} role={tone === "bad" || tone === "warn" ? "alert" : "status"} style={style} data-notice={name}>
      <span className={cx("ic", spin && "spin")} aria-hidden="true">
        {spin ? "" : MARK[tone]}
      </span>
      <span className="tx">
        <b>{title}</b>
        {meta ? <span>{meta}</span> : null}
      </span>
      {onDismiss ? (
        <button className="x" type="button" onClick={onDismiss} aria-label={`Dismiss: ${label}`}>
          {X}
        </button>
      ) : null}
      {actions ? <span className="acts">{actions}</span> : null}
    </div>
  );
}

/* ── Before a check ─────────────────────────────────────────────────── */

/** Upload refused because the session ended. `next` is where sign-in returns to (default: Check a part). */
export function SignedOutBanner({ fileName, next = R.check, onDismiss }: { fileName?: string; next?: string; onDismiss?: () => void }) {
  const href = loginHrefForReturnPath(next);
  return (
    <Banner
      tone="bad"
      name="signed-out"
      title="Signed out"
      meta={`${fileName ? `${fileName} wasn’t checked` : "Nothing was checked"}. No record was made.`}
      onDismiss={onDismiss}
      actions={
        <a className="btn ink sm" href={href}>
          Sign in again
        </a>
      }
    />
  );
}

/**
 * Upload refused: free checks used. `onUpgrade` opens the Out of checks dialog
 * (X3); without it the button starts checkout directly (Email us when checkout is off).
 */
export function FreeChecksUsedBanner({
  fileName,
  used,
  cap,
  onUpgrade,
  checkoutAvailable,
  onDismiss,
}: {
  fileName?: string;
  used?: number | null;
  cap?: number | null;
  onUpgrade?: () => void;
  checkoutAvailable?: boolean;
  onDismiss?: () => void;
}) {
  const count = cap ? `${used ?? cap} of ${cap} · ` : "";
  return (
    <Banner
      tone="warn"
      name="free-checks-used"
      title="Free checks used"
      meta={`${count}${fileName ? `${fileName} wasn’t checked` : "Nothing was checked"}. Your files and saved results are unchanged.`}
      onDismiss={onDismiss}
      actions={
        <>
          {onUpgrade ? (
            <button className="btn ink sm" type="button" onClick={onUpgrade}>
              Upgrade
            </button>
          ) : (
            <UpgradeLink checkoutAvailable={checkoutAvailable} />
          )}
          <Link className="btn ghost sm" href={R.billing}>
            Review usage
          </Link>
        </>
      }
    />
  );
}

function UpgradeLink({ checkoutAvailable }: { checkoutAvailable?: boolean }) {
  // UpgradeButton renders "Email us for more checks" itself when checkout is off.
  return <UpgradeButton label="Upgrade" className="btn ink sm" checkoutAvailable={checkoutAvailable} />;
}

/** Upload refused: the service is busy. The file is kept; `onRetry` sends it again. */
export function BusyBanner({ fileName, onRetry, onDismiss }: { fileName?: string; onRetry: () => void; onDismiss?: () => void }) {
  return (
    <Banner
      tone="warn"
      name="busy"
      title="Busy right now"
      meta={`${fileName ? `${fileName} wasn’t checked` : "Nothing was checked"}. Wait a moment and retry. No need to re-export.`}
      onDismiss={onDismiss}
      actions={
        <button className="btn ink sm" type="button" onClick={onRetry}>
          Retry upload
        </button>
      }
    />
  );
}

/** Upload refused: the file can't be read. `detail` replaces the default fix line. */
export function CantReadBanner({ fileName, detail, onChooseFile, onDismiss }: { fileName?: string; detail?: string; onChooseFile: () => void; onDismiss?: () => void }) {
  return (
    <Banner
      tone="bad"
      name="cant-read"
      title="Can’t read this file"
      meta={[fileName, detail ?? "Export it as STEP, STL or IGES."].filter(Boolean).join(" · ")}
      onDismiss={onDismiss}
      actions={
        <button className="btn ink sm" type="button" onClick={onChooseFile}>
          Choose another file
        </button>
      }
    />
  );
}

/** Opened from Design Studio (?design=&revision=): loading, imported, or a bad link. */
export function DesignImportBanner({
  state,
  name,
  revision,
  detail,
  onDismiss,
}: {
  state: "loading" | "done" | "error";
  name?: string | null;
  revision?: number | string | null;
  detail?: string;
  onDismiss?: () => void;
}) {
  const rev = revision != null && revision !== "" ? `revision ${revision}` : null;
  if (state === "loading")
    return <Banner name="design-loading" tone="info" spin title={`Loading ${name ?? "the design"}${rev ? `, ${rev}` : ""}`} meta="STEP from Design Studio" />;
  if (state === "done")
    return <Banner name="design-done" tone="ok" title={`Imported ${name ?? "the design"}`} meta={detail ?? [rev ? rev[0].toUpperCase() + rev.slice(1) : null, "Check finished"].filter(Boolean).join(" · ")} onDismiss={onDismiss} />;
  return (
    <Banner
      tone="bad"
      name="design-error"
      title="Design link not valid"
      meta={detail ?? "Open the design again from Design Studio."}
      actions={
        <Link className="btn ink sm" href={R.studio}>
          Return to Design Studio
        </Link>
      }
    />
  );
}

/* ── During and after a check ───────────────────────────────────────── */

/** The check stopped before any result. Shown in the sheet; stays until retried. */
export function CheckInterruptedBanner({ onRetry, detail }: { onRetry: () => void; detail?: string }) {
  return (
    <Banner
      tone="bad"
      name="check-interrupted"
      title="Check interrupted"
      meta={detail ?? "No result. Routing, checks and cost didn’t start. The file doesn’t need re-exporting."}
      actions={
        <button className="btn ink sm" type="button" onClick={onRetry}>
          Retry check
        </button>
      }
    />
  );
}

/** Cost failed after routing finished. */
export function CostFailedBanner({ onRetryCost, onRerun, detail }: { onRetryCost: () => void; onRerun: () => void; detail?: string }) {
  return (
    <Banner
      tone="warn"
      name="cost-failed"
      title="Cost didn’t finish"
      meta={detail ?? "Routing and process checks are ready."}
      actions={
        <>
          <button className="btn ink sm" type="button" onClick={onRetryCost}>
            Retry cost
          </button>
          <button className="btn sm" type="button" onClick={onRerun}>
            Rerun everything
          </button>
        </>
      }
    />
  );
}

/** Cost wasn't run because the check allowance is used up. `onUpgrade` opens X3. */
export function CostBlockedBanner({ onUpgrade, checkoutAvailable, pro }: { onUpgrade?: () => void; checkoutAvailable?: boolean; pro?: boolean }) {
  return (
    <Banner
      tone="warn"
      name="cost-blocked"
      title="Cost not run"
      meta={`${pro ? "This month’s Pro checks used" : "Free checks used"}. Routing and process checks are ready.`}
      actions={
        <>
          {pro ? null : onUpgrade ? (
            <button className="btn ink sm" type="button" onClick={onUpgrade}>
              Upgrade
            </button>
          ) : (
            <UpgradeLink checkoutAvailable={checkoutAvailable} />
          )}
          <Link className="btn ghost sm" href={R.billing}>
            Review usage
          </Link>
        </>
      }
    />
  );
}

/** Back from checkout (?upgraded=1). Counts come from usage; say nothing you don't know. */
export function ProBanner({ monthlyChecks, email, onDismiss }: { monthlyChecks?: number | null; email?: string | null; onDismiss?: () => void }) {
  const facts = [monthlyChecks ? `${monthlyChecks} checks this month` : "Your monthly checks are ready", email ? `Receipt sent to ${email}` : "Your receipt is on its way by email"];
  return <Banner name="pro" tone="ok" title="You’re on Pro" meta={facts.join(" · ")} onDismiss={onDismiss} />;
}

/** The part preview failed to draw. Checks still run on the file. */
export function PreviewFailed({ onRetry, onChooseFile }: { onRetry: () => void; onChooseFile: () => void }) {
  return (
    <div className="mo-nodraw" role="status">
      <b>Can&apos;t draw this part</b>
      <span>Checks still run on the file.</span>
      <span className="acts">
        <button className="btn sm" type="button" onClick={onRetry}>
          Retry preview
        </button>
        <button className="btn ghost sm" type="button" onClick={onChooseFile}>
          Choose another file
        </button>
      </span>
    </div>
  );
}

/* ── Workspace ──────────────────────────────────────────────────────── */

/** The organization check failed; shown instead of organization data. */
export function OrgErrorBanner({ onRetry, detail }: { onRetry: () => void; detail?: string }) {
  return (
    <Banner
      tone="bad"
      name="org-error"
      title="Can’t confirm your organization"
      meta={detail ?? "Nothing from your organization was loaded."}
      actions={
        <>
          <button className="btn ink sm" type="button" onClick={onRetry}>
            Retry
          </button>
          <Link className="btn ghost sm" href={R.org}>
            Open organization settings
          </Link>
        </>
      }
    />
  );
}

/** A member of one or more organizations, but none is chosen. */
export function NoActiveOrgBanner({ orgName, onRetry }: { orgName?: string | null; onRetry: () => void }) {
  return (
    <Banner
      tone="warn"
      name="org-none"
      title="No active organization"
      meta={`Choose ${orgName ?? "an organization"} in organization settings to open its parts and tools.`}
      actions={
        <>
          <Link className="btn ink sm" href={R.org}>
            Open organization settings
          </Link>
          <button className="btn ghost sm" type="button" onClick={onRetry}>
            Retry
          </button>
        </>
      }
    />
  );
}

/** Not in any organization yet. */
export function NotInOrgBanner({ email, onRetry }: { email?: string | null; onRetry: () => void }) {
  return (
    <Banner
      tone="info"
      name="org-join"
      title="Not in an organization"
      meta={`Open the invite link from your admin, or ask them to invite ${email ?? "you"}.`}
      actions={
        <>
          <Link className="btn sm" href={R.org}>
            Open organization settings
          </Link>
          <button className="btn ghost sm" type="button" onClick={onRetry}>
            Retry
          </button>
        </>
      }
    />
  );
}

/**
 * A page that failed to load. Retry re-runs it; Review usage shows only for
 * allowance errors, and a used-up lifetime allowance offers Upgrade instead of
 * a retry that can't succeed.
 */
export function PageError({
  title = "Something went wrong",
  message,
  digest,
  onRetry,
  name,
}: {
  title?: string;
  message?: string | null;
  digest?: string | null;
  onRetry?: () => void;
  name?: string;
}) {
  const text = message?.trim() || "Couldn’t load this page.";
  const detail = distinctErrorDetail(title, text);
  const lifetime = isLifetimeQuotaErrorMessage(text);
  const quota = isQuotaErrorMessage(text);
  return (
    <div className="mo-errc" role="alert" data-notice={name ?? "page-error"}>
      <b className="stitle">{title}</b>
      {detail ? <span className="msg">{detail}</span> : null}
      {digest ? <span className="id">Error ID {digest}</span> : null}
      <span className="acts">
        {lifetime ? <UpgradeLink /> : onRetry ? (
          <button className="btn ink sm" type="button" onClick={onRetry}>
            Retry
          </button>
        ) : null}
        {quota ? (
          <Link className="btn ghost sm" href={R.billing}>
            Review usage
          </Link>
        ) : null}
      </span>
    </div>
  );
}
