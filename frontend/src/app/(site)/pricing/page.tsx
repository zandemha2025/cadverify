import type { Metadata } from "next";
import { cookies } from "next/headers";
import { DocumentPage } from "@/components/site/document-page";
import { UpgradeButton } from "@/components/billing/upgrade-button";
import { formatProPrice } from "@/lib/billing";
import { getPlans } from "@/lib/plans";
import { SESSION_COOKIE } from "@/lib/session";
import { SIGNUP_HREF, signupHref } from "@/lib/site/navigation";

export const metadata: Metadata = {
  title: "Pricing — ScaleCAD",
  description: "Try ScaleCAD free on your own parts, up to 50 at once with a work email. Go monthly with Pro once it's useful. A $7,500 pilot covers one factory: up to 500 parts over 4–6 weeks.",
  alternates: { canonical: "/pricing" },
};

export default async function PricingPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const [plans, params, jar] = await Promise.all([getPlans(), searchParams, cookies()]);
  const signedIn = Boolean(jar.get(SESSION_COOKIE)?.value);
  const price = formatProPrice(plans.pro.price);
  const { work_checks: work, personal_checks: personal, catalog_parts: catalog } = plans.free;
  const phoneNeeded = ["1", "true", "yes", "on"].includes((process.env.SMS_VERIFICATION_REQUIRED || "").trim().toLowerCase());
  return <DocumentPage label="Pricing" title="Free to start." intro="Try it free on your own parts. Pay monthly once it's useful. Call us when you want it across a factory." sections={[
    {
      id: "free",
      title: "Free · $0",
      body: `${work} free checks with a work email, ${personal} with a personal one, once per person; they don't renew.${phoneNeeded ? " A mobile number confirms it's you: we text you a code once." : ""} A work email also runs its first ${catalog} catalog parts free, separate from the checks. No credit card.`,
      href: signedIn ? "/verify" : SIGNUP_HREF,
      link: signedIn ? "Open ScaleCAD" : "Try ScaleCAD free",
    },
    {
      id: "pro",
      title: price ? `Pro · ${price}` : "Pro · monthly",
      body: `${plans.pro.monthly_checks} checks every month, renewed each billing month. Every check answers against your own machines and prices, as on Free. Cancel anytime.`,
      action: <UpgradeButton label="Start Pro" className="cv-button" checkoutAvailable={plans.pro.checkout_available} autoStart={signedIn && params.plan === "pro"} />,
    },
    {
      id: "pilot",
      title: "$7,500 pilot · 4–6 weeks · up to 500 parts",
      body: "We set it up for one factory: your machines, materials and rates, up to 500 part numbers. Counts toward your first year if you continue. Scope and acceptance criteria are agreed in a signed order form.",
      bullets: [
        "Check parts against your declared equipment, materials and rates.",
        "Compare resource estimates with your buy prices and volumes; see capability gaps and candidate upgrades.",
        "Validate a held-out subset against actual outcomes, recording misses and unknowns.",
        "Get a ranked decision brief with assumptions, limits and recommended follow-up checks.",
      ],
      href: "/pilot",
      link: "Plan a pilot",
    },
    {
      id: "qualification",
      title: `Not sure yet? Run ${catalog} parts free`,
      body: `With a work email, check up to ${catalog} of your own parts at once: a folder, a ZIP or a parts list with quantities and materials. Each part is sorted against the machines you declare (make in-house, buy outside, needs a new machine, or can't be made as drawn) with machine hours, material and a model price. Prefer to work through it with us? The pilot page offers a free, team-assisted 25-part qualification.`,
      href: signedIn ? "/app/many?new=1" : signupHref("/app/many?new=1"),
      link: signedIn ? "Start a catalog run" : `Run ${catalog} parts free`,
    },
    {
      id: "annual",
      title: "Enterprise · quoted to scope",
      body: "Annual pricing after the pilot, based on sites, part volume, support and deployment. Batches up to 10,000 parts, SSO and self-hosted deployment are scoped here.",
      href: "/contact",
      link: "Talk to us",
    },
  ]} cta={false} />;
}
