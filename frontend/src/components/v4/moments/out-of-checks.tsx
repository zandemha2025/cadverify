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
 *              Without it they are read from /api/billing/plans (the pricing page's source).
 * - `file`     the file that was just refused. It waits on this device for this
 *              account and checks after an upgrade (Checkout returns to the app).
 *
 * Focus moves into the dialog, Tab stays inside, Esc closes, focus returns.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/ui/auth-provider";
import { parsePlans, SALES_MAILTO, type Plans } from "@/lib/billing";
import { browserPendingPartStore, holdPendingPart } from "@/lib/pending-part";
import { billingLink } from "../account/api";
import { useShell } from "../shell";
import { R } from "../routes";
import { cx } from "../ui";
import { PILOT_HREF } from "./pilot-gate";
import { useFocusTrap } from "./focus";
import { outOfChecksCopy, plainRefusal } from "./out-of-checks-copy";
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

/** The public plans as given, else one read of /api/billing/plans; `loaded` once known either way. */
function usePlans(given: Plans | null | undefined): { plans: Plans | null; loaded: boolean } {
  const [own, setOwn] = React.useState<{ plans: Plans | null; loaded: boolean }>({ plans: null, loaded: false });
  React.useEffect(() => {
    if (given) return;
    let live = true;
    fetch("/api/billing/plans", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => live && setOwn({ plans: b ? parsePlans(b) : null, loaded: true }))
      .catch(() => live && setOwn({ plans: null, loaded: true }));
    return () => {
      live = false;
    };
  }, [given]);
  return given ? { plans: given, loaded: true } : own;
}

/** Checkout from inside the app, so Stripe sends the person back here (/app?upgraded=1). */
function UpgradeHere() {
  const router = useRouter();
  const [working, setWorking] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  return (
    <>
      <button
        className="btn ink"
        type="button"
        disabled={working}
        aria-busy={working}
        onClick={async () => {
          setWorking(true);
          setError(null);
          const out = await billingLink("checkout");
          if (out.kind === "redirect") window.location.assign(out.url);
          else if (out.kind === "manage") router.push(R.billing);
          else if (out.kind === "sign_in") router.push(`/login?next=${encodeURIComponent(R.billing)}`);
          else {
            setError(out.message);
            setWorking(false);
          }
        }}
      >
        {working ? "Opening checkout…" : "Upgrade"}
      </button>
      {error ? (
        <p className="honest" role="alert">
          {error} <a href={SALES_MAILTO}>Email us</a>
        </p>
      ) : null}
    </>
  );
}

export function OutOfChecks({
  message,
  onClose,
  usage: given,
  plans: givenPlans,
  file,
}: {
  message?: string;
  onClose?: () => void;
  usage?: CheckUsage | null;
  plans?: Plans | null;
  file?: File | null;
}) {
  const router = useRouter();
  const { user } = useAuth();
  const usage = useUsage(given);
  const { plans, loaded } = usePlans(givenPlans);
  const ref = React.useRef<HTMLElement>(null);
  const close = React.useCallback(() => (onClose ? onClose() : router.push(R.parts)), [onClose, router]);
  const onKeyDown = useFocusTrap(ref, close);
  const [held, setHeld] = React.useState(false);

  // The refused file waits for this account; after Checkout the app checks it.
  React.useEffect(() => {
    if (!file || !user?.email) return;
    let live = true;
    void holdPendingPart(browserPendingPartStore(), file, user.email).then((ok) => live && setHeld(ok));
    return () => {
      live = false;
    };
  }, [file, user?.email]);

  const pro = usage?.plan === "pro";
  const cap = usage?.cap ?? 0;
  const used = usage?.used ?? cap;
  const checkout = plans ? plans.pro.checkout_available : undefined;
  const copy = outOfChecksCopy(plans, loaded, file && held ? file.name : null);
  const why = plainRefusal(message);

  return (
    <div className="mo-x3">
      <button type="button" className="scrim" tabIndex={-1} aria-hidden="true" onClick={close} />
      <section ref={ref} className="modal" role="dialog" aria-modal="true" aria-labelledby="oc-title" aria-describedby={why ? "oc-why" : undefined} tabIndex={-1} onKeyDown={onKeyDown}>
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
          {why ? (
            <p id="oc-why" className="sr">
              {why}
            </p>
          ) : null}
          {copy.kept ? (
            <p className="smeta" role="status" style={{ marginTop: 8, overflowWrap: "anywhere" }}>
              {copy.kept}
            </p>
          ) : file ? (
            <p className="smeta" style={{ marginTop: 8, overflowWrap: "anywhere" }}>
              {file.name} wasn’t checked and used no check. It stays picked on this page.
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
            <span>Without checks you can still open saved parts, run the sample, and use ScaleCAD&apos;s fixes, mesh repair, Design Studio and Fit in assembly.</span>
          </div>
        ) : null}
        {!pro ? (
          <div className="opt">
            <span>
              <b>Pro</b>
              <span className="p num">{copy.price}</span>
            </span>
            {checkout === false ? (
              <a className="btn ink" href={SALES_MAILTO}>
                Email us
              </a>
            ) : (
              <UpgradeHere />
            )}
            <p>{copy.monthly} · your machines and prices · cancel anytime</p>
            {checkout === false ? <p className="honest">Checkout is unavailable right now. Email us for more checks.</p> : null}
            <p className="honest">More checks. Batch runs, assemblies and other pilot tools aren&apos;t included.</p>
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
