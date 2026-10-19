"use client";

/**
 * Out of checks (board X3): the modal shown when a check is refused because the
 * account's checks are used up. It shows the real count (from /auth/me/usage),
 * the Pro option (Upgrade, or Email us when checkout is off), the pilot and the
 * free part review. Nothing was checked; saved results are unchanged.
 *
 * Props (all optional):
 * - `message`  the server's refusal text, read to screen readers as the reason.
 * - `onClose`  called by Esc and the scrim. Without it they go to Parts, like "Back to parts".
 * - `usage`    pass a usage object if you already have one; otherwise the shell's is used
 *              (or it is read once).
 * - `plans`    the public plan facts (`getPlans()` on the server) for the Pro price.
 *              Without it the price reads "Price shown at checkout".
 *
 * Focus moves into the dialog, Tab stays inside, Esc closes, focus returns.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UpgradeButton } from "@/components/billing/upgrade-button";
import { billingStatus, formatProPrice, SALES_MAILTO, type Plans } from "@/lib/billing";
import { useShell } from "../shell";
import { R } from "../routes";
import { cx } from "../ui";
import { PILOT_HREF } from "./pilot-gate";
import { useFocusTrap } from "./focus";
import "./moments.css";

export type CheckUsage = {
  plan: string;
  tier?: string;
  unlimited: boolean;
  used: number | null;
  cap: number | null;
  remaining?: number | null;
  resets_at?: string | null;
  window_days?: number | null;
  phone_verification_required?: boolean;
};

/** The shell's usage when present, else one read of /auth/me/usage. */
export function useUsage(given?: CheckUsage | null): CheckUsage | null {
  const shell = useShell();
  const fromShell = (shell.usage as CheckUsage | null) ?? null;
  const [own, setOwn] = React.useState<CheckUsage | null>(null);
  const need = given === undefined && !fromShell;
  React.useEffect(() => {
    if (!need) return;
    let live = true;
    fetch("/api/auth/me/usage", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((u) => live && setOwn(u))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [need]);
  return given !== undefined ? given : fromShell ?? own;
}

function resetText(u: CheckUsage | null, pro: boolean): string {
  if (u?.resets_at) {
    const d = new Date(u.resets_at);
    if (!Number.isNaN(d.getTime())) return `Resets ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
  }
  if (pro) return "They reset each billing month";
  if (u?.window_days && u.window_days > 0) return `Rolling ${u.window_days}-day allowance`;
  return "Free checks don't reset";
}

export function OutOfChecks({
  message,
  onClose,
  usage: given,
  plans,
}: {
  message?: string;
  onClose?: () => void;
  usage?: CheckUsage | null;
  plans?: Plans | null;
}) {
  const router = useRouter();
  const usage = useUsage(given);
  const ref = React.useRef<HTMLElement>(null);
  const [status, setStatus] = React.useState<{ checkout: boolean; monthly: number } | null>(null);
  const close = React.useCallback(() => (onClose ? onClose() : router.push(R.parts)), [onClose, router]);
  const onKeyDown = useFocusTrap(ref, close);

  React.useEffect(() => {
    if (plans) return;
    let live = true;
    void billingStatus().then((s) => {
      if (live && s) setStatus({ checkout: s.checkout_available, monthly: s.pro_monthly_checks });
    });
    return () => {
      live = false;
    };
  }, [plans]);

  const pro = usage?.plan === "pro";
  const cap = usage?.cap ?? 0;
  const used = usage?.used ?? cap;
  const checkout = plans ? plans.pro.checkout_available : status?.checkout;
  const monthly = plans?.pro.monthly_checks ?? status?.monthly ?? null;
  const price = formatProPrice(plans?.pro.price ?? null);

  return (
    <div className="mo-x3">
      <button type="button" className="scrim" tabIndex={-1} aria-hidden="true" onClick={close} />
      <section ref={ref} className="modal" role="dialog" aria-modal="true" aria-labelledby="oc-title" aria-describedby={message ? "oc-why" : undefined} tabIndex={-1} onKeyDown={onKeyDown}>
        <div className="hd">
          <h1 className="ptitle" id="oc-title">
            {pro ? "This month's Pro checks used" : "Free checks used"}
          </h1>
          <p className="pmeta" style={{ marginTop: 6 }}>
            {cap ? (
              <span>
                <b className="num">
                  {used} of {cap}
                </b>{" "}
                used
              </span>
            ) : null}
            <span>{resetText(usage, pro)}</span>
            <span>Saved results stay available</span>
          </p>
          {message ? (
            <p id="oc-why" className="sr">
              {message}
            </p>
          ) : null}
        </div>
        {cap ? (
          <div className="meter">
            {cap <= 30 ? (
              <div className="barn" role="img" aria-label={`${used} of ${cap} ${pro ? "Pro" : "free"} checks used`} style={{ gridTemplateColumns: `repeat(${cap}, minmax(0,1fr))` }}>
                {Array.from({ length: cap }, (_, i) => (
                  <i key={i} className={cx(i >= used && "free")} />
                ))}
              </div>
            ) : (
              <span className="track" role="progressbar" aria-label="Checks used" aria-valuemin={0} aria-valuemax={cap} aria-valuenow={used}>
                <i style={{ width: `${Math.min(100, (used / cap) * 100)}%` }} />
              </span>
            )}
            <span>1 check = one part&apos;s preview, analysis and cost. Re-running a step on the same file doesn&apos;t use another.</span>
          </div>
        ) : null}
        {!pro ? (
          <div className="opt">
            <span>
              <b>Pro</b>
              <span className="p num">{price ? price.replace(/\/mo$/, " / month").replace(/\/yr$/, " / year") : "Price shown at checkout"}</span>
            </span>
            {checkout === false ? (
              <a className="btn ink" href={SALES_MAILTO}>
                Email us
              </a>
            ) : (
              <UpgradeButton label="Upgrade" className="btn ink" checkoutAvailable={checkout} />
            )}
            <p>{monthly != null ? `${monthly} checks a month` : "Monthly checks"} · your machines and prices · cancel anytime</p>
            {checkout === false ? <p className="honest">Checkout is unavailable right now. Email us for more checks.</p> : null}
            <p className="honest">Checks only. Batch runs, Fit in context and other pilot tools aren&apos;t included.</p>
          </div>
        ) : null}
        <div className="opt">
          <span>
            <b>Pilot</b>
            <span className="p">$7,500 · 4–6 weeks · up to 500 parts</span>
          </span>
          <a className="btn" href={PILOT_HREF.plan}>
            Plan pilot
          </a>
          <p>One factory · your machines, materials and rates · all tools · credited to year one if you continue</p>
        </div>
        <div className="opt">
          <span>
            <b>Part review</b>
            <span className="p">Free · up to 25 parts</span>
          </span>
          <a className="btn" href={PILOT_HREF.request}>
            Request
          </a>
          <p>Parts from one plant · we check whether a pilot fits</p>
        </div>
        <div className="ft">
          <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <Link className="btn ghost sm" href={R.parts}>
              Back to parts
            </Link>
            <Link className="btn ghost sm" href={R.billing}>
              Review usage
            </Link>
          </span>
          <a className="btn ghost sm" href="/contact">
            Contact sales
          </a>
        </div>
      </section>
    </div>
  );
}
