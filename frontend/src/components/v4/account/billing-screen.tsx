"use client";

/**
 * Plan and billing (board A4): the allowance strip, the three plans (free
 * checks by email tier, Pro from Stripe, the pilot), Pro checkout and the
 * Stripe portal. The Pro price is the one the billing API reads from Stripe;
 * when it isn't available the card says the price shows at checkout instead
 * of guessing. Checkout and the portal return here (or to /app?upgraded=1).
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { SALES_MAILTO, type Plans } from "@/lib/billing";
import { Chip, Content } from "../ui";
import { AccountFrame, AccountHead, Banner } from "./frame";
import * as api from "./api";
import { allowanceLine, dayLabel, planName, proPrice, type Usage } from "./derive";

const PILOT_HREF = "/pilot#pilot";

export function BillingScreen({ plans }: { plans: Plans }) {
  const router = useRouter();
  const [usage, setUsage] = React.useState<Usage | null>(null);
  const [usageLoaded, setUsageLoaded] = React.useState(false);
  const [billing, setBilling] = React.useState<api.BillingStatus | null>(null);
  const [going, setGoing] = React.useState<"checkout" | "portal" | null>(null);
  const [err, setErr] = React.useState<{ kind: "checkout" | "portal"; message: string } | null>(null);
  const [cancelled, setCancelled] = React.useState(false);

  React.useEffect(() => {
    fetch("/api/auth/me/usage", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((u) => setUsage(u), () => setUsage(null))
      .finally(() => setUsageLoaded(true));
    api.getBilling().then(setBilling, () => setBilling(null));
    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") === "cancelled") {
      setCancelled(true);
      params.delete("checkout");
      const rest = params.toString();
      window.history.replaceState(null, "", `${window.location.pathname}${rest ? `?${rest}` : ""}`);
    }
  }, []);

  const plan = billing?.plan ?? usage?.plan ?? null;
  const pro = plan === "pro";
  const pilot = plan === "pilot" || !!usage?.unlimited;
  const free = !!plan && !pro && !pilot;
  const checkoutOff = !(billing?.checkout_available ?? plans.pro.checkout_available);
  const monthly = billing?.pro_monthly_checks ?? plans.pro.monthly_checks;
  const price = proPrice(plans.pro.price);
  const manageable = !!billing?.manage_available;
  const name = planName(usage, billing?.plan) ?? "—";

  async function open(kind: "checkout" | "portal") {
    setErr(null);
    setGoing(kind);
    const out = await api.billingLink(kind);
    if (out.kind === "redirect") {
      window.location.assign(out.url);
      return;
    }
    if (out.kind === "sign_in") {
      router.push("/login?next=%2Fapp%2Faccount%2Fbilling");
      return;
    }
    if (out.kind === "manage") {
      await open("portal");
      return;
    }
    setErr({ kind, message: out.message });
    setGoing(null);
  }

  const upLabel = going === "checkout" ? "Opening checkout…" : "Upgrade to Pro";
  const manageLabel = going === "portal" ? "Opening billing…" : "Manage billing";
  const upgradeButton = (cls: string) => (
    <button className={cls} type="button" onClick={() => void open("checkout")} disabled={going != null} aria-busy={going === "checkout"}>
      {upLabel}
    </button>
  );
  const manageButton = (cls: string) => (
    <button className={cls} type="button" onClick={() => void open("portal")} disabled={going != null} aria-busy={going === "portal"}>
      {manageLabel}
    </button>
  );
  const mailButton = (cls: string) => (
    <a className={cls} href={SALES_MAILTO}>
      Email us for more checks
    </a>
  );

  const allowWord = pro ? "Checks a month" : pilot ? "Checks" : "Free checks";
  const allowCap = pro ? (usage?.cap ?? monthly) : pilot ? "Not counted" : usage?.cap ?? null;

  return (
    <AccountFrame label="Plan and billing">
      <AccountHead
        title="Plan and billing"
        wide
        meta={[
          <span key="p">Plan <b>{name}</b></span>,
          <span key="a">
            {allowWord} <b className="num">{allowCap ?? "—"}</b>
          </span>,
          <span key="b">Billing <b>Stripe</b></span>,
        ]}
      />
      <Content full>
        <div className="a-strip" role="status">
          <span>{allowanceLine(usage, usageLoaded)}</span>
          <span className="a-bx">
            {free && usage && !checkoutOff ? upgradeButton("btn go sm") : null}
            {free && checkoutOff ? mailButton("btn sm") : null}
            {pro ? manageButton("btn sm") : null}
          </span>
        </div>
        {cancelled ? (
          <Banner tone="plain" alert={false} title="Checkout cancelled." actions={<button className="btn sm" type="button" onClick={() => setCancelled(false)}>Dismiss</button>}>
            Nothing was charged.
          </Banner>
        ) : null}
        {err ? (
          <Banner
            title={err.kind === "checkout" ? "Couldn’t open checkout." : "Couldn’t open billing."}
            actions={
              <>
                <a className="btn sm" href={SALES_MAILTO}>
                  Email us
                </a>
                <button className="btn sm" type="button" onClick={() => void open(err.kind)}>
                  Try again
                </button>
              </>
            }
          >
            {err.message}
          </Banner>
        ) : null}
        <div className="a-plans">
          <section className={`panel a-plan${free ? " cur" : ""}`} aria-label="Free trial">
            <h2>
              Free trial
              {free ? <Chip tone="unk">Your plan</Chip> : null}
            </h2>
            <span className="a-price">$0</span>
            <ul>
              <li>
                <i aria-hidden="true">✓</i>
                {plans.free.work_checks} checks with a work email, {plans.free.personal_checks} with a personal one
              </li>
              <li>
                <i aria-hidden="true">✓</i>Methods, cost and findings per part
              </li>
              <li>
                <i aria-hidden="true">✓</i>Machines, service conditions, decisions, records
              </li>
              <li>
                <i aria-hidden="true">✓</i>Fixes ScaleCAD makes, mesh repair, Design Studio, Fit in assembly: no check used
              </li>
            </ul>
            <div className="a-act">
              <span className="a-fh">Sample part: no check used</span>
            </div>
          </section>
          <section className={`panel a-plan${pro ? " cur" : ""}`} aria-label="Pro">
            <h2>
              Pro
              {pro ? <Chip tone="ok">Your plan</Chip> : null}
            </h2>
            {price ? (
              <span className="a-price">
                {price.amount} <small>{price.per}</small>
              </span>
            ) : (
              <span className="a-price t">
                Monthly <small>price shown at checkout</small>
              </span>
            )}
            <ul>
              <li>
                <i aria-hidden="true">✓</i>
                {monthly} checks a month
              </li>
              <li>
                <i aria-hidden="true">✓</i>Everything in the free trial
              </li>
              <li>
                <i aria-hidden="true">✓</i>Card, invoices and cancellation in Stripe
              </li>
            </ul>
            <div className="a-act">
              {pro ? (
                <>
                  {manageButton("btn")}
                  <span className="a-fh">
                    Change card, see invoices or cancel.
                    {billing?.current_period_end ? ` Renews ${dayLabel(billing.current_period_end)}.` : ""}
                  </span>
                </>
              ) : pilot ? (
                <span className="a-fh">Your pilot already includes unlimited checks.</span>
              ) : checkoutOff ? (
                <>
                  {mailButton("btn")}
                  <span className="a-fh">Online checkout is off.</span>
                </>
              ) : (
                <>
                  {upgradeButton("btn go")}
                  <span className="a-fh">Stripe Checkout. Saved results stay.</span>
                </>
              )}
            </div>
          </section>
          <section className={`panel a-plan${pilot ? " cur" : ""}`} aria-label="Pilot">
            <h2>
              Pilot
              {pilot ? <Chip tone="ok">Your plan</Chip> : null}
            </h2>
            <span className="a-price">
              $7,500 <small>one factory</small>
            </span>
            <ul>
              <li>
                <i aria-hidden="true">✓</i>Up to 500 parts, 4–6 weeks
              </li>
              <li>
                <i aria-hidden="true">✓</i>Batches, assemblies, Photo to 3D
              </li>
              <li>
                <i aria-hidden="true">✓</i>Recalibration from real jobs
              </li>
            </ul>
            <div className="a-act">
              <Link className="btn" href={PILOT_HREF}>
                Talk to us
              </Link>
            </div>
          </section>
        </div>
        <div className="a-g2">
          <section className="panel" aria-label="Tools by plan">
            <div className="ph">
              <h2>Tools by plan</h2>
              <span />
            </div>
            <div className="kv" style={{ padding: "0 16px 14px", gridTemplateColumns: "110px minmax(0,1fr)" }}>
              <span>Every plan</span>
              <b style={{ textAlign: "left" }}>Fixes ScaleCAD makes, mesh repair, Design Studio, Fit in assembly. The free trial has an hourly and daily limit on them</b>
              <span>Pro adds</span>
              <b style={{ textAlign: "left" }}>Monthly checks, and no free-trial limit on those tools</b>
              <span>Pilot only</span>
              <b style={{ textAlign: "left" }}>Batches, assemblies, Photo to 3D, recalibration</b>
            </div>
          </section>
          <section className="panel" aria-label="Payment and invoices">
            <div className="ph">
              <h2>Payment and invoices</h2>
              <span>In Stripe</span>
            </div>
            <div className="kv" style={{ padding: "0 16px 10px" }}>
              <span>Card, invoices, cancellation</span>
              <b>Stripe portal</b>
              <span>Available</span>
              <b>{manageable ? "Now" : pilot ? "Not used on a pilot" : "On Pro"}</b>
            </div>
            <div style={{ padding: "0 16px 14px" }}>
              {manageable ? (
                manageButton("btn sm")
              ) : (
                <button className="btn sm" type="button" aria-disabled="true" style={{ opacity: 0.45, cursor: "default" }} aria-describedby="a-portal-h">
                  Manage billing
                </button>
              )}
              {manageable ? null : (
                <span className="a-fh" id="a-portal-h" style={{ marginLeft: 8 }}>
                  {pilot ? "Pilot plans don’t use the Stripe portal." : "Opens once you’re on Pro."}
                </span>
              )}
            </div>
          </section>
        </div>
      </Content>
    </AccountFrame>
  );
}
