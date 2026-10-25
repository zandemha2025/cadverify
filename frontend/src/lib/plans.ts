/**
 * Public plan facts (SERVER ONLY): free tier sizes and the Pro price, read
 * from the backend so pages always match what the API enforces and Stripe
 * charges. Falls back to the documented defaults if the API is unreachable,
 * with checkout marked unavailable.
 */
import { backendUrl } from "./api-base";
import { FALLBACK_PLANS, parsePlans, type Plans } from "./billing";

export async function getPlans(): Promise<Plans> {
  try {
    const res = await fetch(backendUrl("/billing/plans"), {
      next: { revalidate: 300 },
      // Public pages must not wait on the API: fall back fast, refresh in the background.
      signal: AbortSignal.timeout(1_500),
    });
    if (!res.ok) return FALLBACK_PLANS;
    return parsePlans(await res.json());
  } catch {
    return FALLBACK_PLANS;
  }
}
