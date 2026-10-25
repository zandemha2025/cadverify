/**
 * Browser helpers for self-serve Pro: start Stripe Checkout or open the
 * billing portal through the same-origin proxy. The backend owns every price
 * and entitlement; these helpers only follow the URL it returns.
 */

type Fetcher = typeof fetch;

export const PRO_SIGN_IN_HREF = "/login?next=%2Fpricing%3Fplan%3Dpro#magic-link";
export const SALES_MAILTO = "mailto:nazeem@scalecad.ai?subject=ScaleCAD%20Pro";

export type BillingStatus = {
  checkout_available: boolean;
  plan: string;
  status: string | null;
  current_period_end: string | null;
  manage_available: boolean;
  pro_monthly_checks: number;
};

export type BillingOutcome =
  | { kind: "redirect"; url: string }
  | { kind: "sign_in"; href: string }
  | { kind: "manage" }
  | { kind: "error"; message: string };

const STRIPE_HOSTS = new Set(["checkout.stripe.com", "billing.stripe.com"]);

/** Only follow Stripe-hosted pages; anything else is treated as an error. */
export function isStripeUrl(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && STRIPE_HOSTS.has(url.hostname);
  } catch {
    return false;
  }
}

async function post(path: string, fetcher: Fetcher): Promise<{ status: number; body: unknown }> {
  const res = await fetcher(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });
  return { status: res.status, body: await res.json().catch(() => null) };
}

// Self-contained (no project imports) so any test loader can render it.
function problemMessage(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  const value = detail && typeof detail === "object" ? (detail as { message?: unknown }).message : detail ?? (body as { message?: unknown }).message;
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function code(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  const value = detail && typeof detail === "object" ? (detail as { code?: unknown }).code : (body as { code?: unknown }).code;
  return typeof value === "string" ? value : null;
}

export async function requestCheckout(fetcher: Fetcher = fetch): Promise<BillingOutcome> {
  try {
    const { status, body } = await post("/api/proxy/billing/checkout", fetcher);
    if (status === 401) return { kind: "sign_in", href: PRO_SIGN_IN_HREF };
    if (status === 409 && code(body) === "already_pro") return { kind: "manage" };
    const url = (body as { url?: unknown } | null)?.url;
    if (status === 200 && isStripeUrl(url)) return { kind: "redirect", url };
    return { kind: "error", message: problemMessage(body) ?? "Checkout didn't open. Try again, or email us and we'll set it up." };
  } catch {
    return { kind: "error", message: "Checkout didn't open. Check your connection and try again." };
  }
}

export async function requestPortal(fetcher: Fetcher = fetch): Promise<BillingOutcome> {
  try {
    const { status, body } = await post("/api/proxy/billing/portal", fetcher);
    if (status === 401) return { kind: "sign_in", href: "/login?next=%2Fhistory" };
    const url = (body as { url?: unknown } | null)?.url;
    if (status === 200 && isStripeUrl(url)) return { kind: "redirect", url };
    return { kind: "error", message: problemMessage(body) ?? "Billing didn't open. Try again shortly." };
  } catch {
    return { kind: "error", message: "Billing didn't open. Check your connection and try again." };
  }
}

let cachedStatus: Promise<BillingStatus | null> | null = null;

/** One status read per page load; null when signed out or unavailable. */
export function billingStatus(fetcher: Fetcher = fetch): Promise<BillingStatus | null> {
  cachedStatus ??= fetcher("/api/proxy/billing", { cache: "no-store" })
    .then((res) => (res.ok ? res.json() : null))
    .catch(() => null);
  return cachedStatus;
}

export function resetBillingStatusCache(): void {
  cachedStatus = null;
}

export type ProPrice = { unit_amount: number; currency: string; interval: string };

export function formatProPrice(price: ProPrice | null | undefined): string | null {
  if (!price || !Number.isFinite(price.unit_amount) || price.unit_amount < 0) return null;
  const amount = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: price.currency.toUpperCase(),
    minimumFractionDigits: price.unit_amount % 100 === 0 ? 0 : 2,
  }).format(price.unit_amount / 100);
  const interval = price.interval === "year" ? "yr" : price.interval === "month" ? "mo" : price.interval;
  return `${amount}/${interval}`;
}

/** Public plan facts from GET /billing/plans. */
export type Plans = {
  /** catalog_parts: a work-email account's free catalog-run parts (separate from its checks). */
  free: { work_checks: number; personal_checks: number; catalog_parts: number };
  pro: { checkout_available: boolean; monthly_checks: number; price: ProPrice | null };
};

export const FALLBACK_PLANS: Plans = {
  free: { work_checks: 15, personal_checks: 3, catalog_parts: 50 },
  pro: { checkout_available: false, monthly_checks: 50, price: null },
};

function count(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : fallback;
}

export function parsePlans(raw: unknown): Plans {
  const body = raw && typeof raw === "object" ? raw as { free?: Record<string, unknown>; pro?: Record<string, unknown> } : {};
  const price = body.pro?.price as Partial<ProPrice> | null | undefined;
  return {
    free: {
      work_checks: count(body.free?.work_checks, FALLBACK_PLANS.free.work_checks),
      personal_checks: count(body.free?.personal_checks, FALLBACK_PLANS.free.personal_checks),
      catalog_parts: count(body.free?.catalog_parts, FALLBACK_PLANS.free.catalog_parts),
    },
    pro: {
      checkout_available: body.pro?.checkout_available === true,
      monthly_checks: count(body.pro?.monthly_checks, FALLBACK_PLANS.pro.monthly_checks),
      price: price && typeof price.unit_amount === "number" && typeof price.currency === "string" && typeof price.interval === "string"
        ? { unit_amount: price.unit_amount, currency: price.currency, interval: price.interval }
        : null,
    },
  };
}
