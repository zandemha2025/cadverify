"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { billingStatus, requestCheckout, requestPortal, SALES_MAILTO, type BillingOutcome } from "@/lib/billing";

type Props = {
  label?: string;
  className?: string;
  style?: CSSProperties;
  /** Known server-side (public pages); skips the signed-in status read. */
  checkoutAvailable?: boolean;
  /** Start checkout on mount, for /pricing?plan=pro after sign-in. */
  autoStart?: boolean;
};

function follow(outcome: BillingOutcome, setError: (message: string) => void) {
  if (outcome.kind === "redirect") window.location.assign(outcome.url);
  else if (outcome.kind === "sign_in") window.location.href = outcome.href;
  // Already on Pro: open billing instead of a second subscription.
  else if (outcome.kind === "manage") void requestPortal().then((portal) => follow(portal, setError));
  else setError(outcome.message);
}

/** One click to Stripe Checkout. Falls back to email when checkout is off. */
export function UpgradeButton({ label = "Upgrade to Pro", className, style, checkoutAvailable, autoStart = false }: Props) {
  const [available, setAvailable] = useState<boolean | null>(checkoutAvailable ?? null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (checkoutAvailable !== undefined) return;
    let live = true;
    void billingStatus().then((status) => {
      if (live && status) setAvailable(status.checkout_available);
    });
    return () => { live = false; };
  }, [checkoutAvailable]);

  async function start() {
    setError(null);
    setWorking(true);
    follow(await requestCheckout(), setError);
    setWorking(false);
  }

  useEffect(() => {
    if (autoStart && available !== false) void start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart]);

  if (available === false) {
    return <a href={SALES_MAILTO} className={className} style={style}>Email us for more checks</a>;
  }
  return <>
    <button type="button" onClick={() => void start()} disabled={working} aria-busy={working} className={className} style={style}>
      {working ? "Opening checkout…" : label}
    </button>
    {error && <span role="alert" style={{ display: "block", marginTop: 8, fontSize: 13, lineHeight: 1.5 }}>
      {error} <a href={SALES_MAILTO} style={{ textDecoration: "underline" }}>Email us</a>
    </span>}
  </>;
}

export function ManageBillingButton({ label = "Manage billing", className, style }: Omit<Props, "checkoutAvailable" | "autoStart">) {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return <>
    <button type="button" disabled={working} aria-busy={working} className={className} style={style} onClick={async () => {
      setError(null);
      setWorking(true);
      follow(await requestPortal(), setError);
      setWorking(false);
    }}>
      {working ? "Opening billing…" : label}
    </button>
    {error && <span role="alert" style={{ display: "block", marginTop: 8, fontSize: 13 }}>{error}</span>}
  </>;
}
