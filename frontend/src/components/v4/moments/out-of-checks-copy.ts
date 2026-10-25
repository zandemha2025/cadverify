/**
 * Out of checks (X3), the words: Pro's price and monthly checks from the
 * public plans (GET /billing/plans, the same facts the pricing page shows), and
 * what happens to the file that was just refused. Pure, for node --test.
 */
import { formatProPrice, type Plans } from "../../../lib/billing.ts";

export type OutOfChecksCopy = { price: string; monthly: string; kept: string | null };

export function outOfChecksCopy(plans: Plans | null, loaded: boolean, fileName: string | null): OutOfChecksCopy {
  const formatted = formatProPrice(plans?.pro.price ?? null);
  const price = formatted ? formatted.replace(/\/mo$/, " / month").replace(/\/yr$/, " / year") : loaded ? "Price shown at checkout" : "…";
  const monthly = plans ? `${plans.pro.monthly_checks} checks every month` : loaded ? "Checks every month" : "…";
  const kept = fileName
    ? `${fileName} wasn’t checked and used no check. It waits on this device for 2 hours and checks as soon as you upgrade.`
    : null;
  return { price, monthly, kept };
}

/** The server's refusal without the old "Verification allowance used up." lead-in. */
export function plainRefusal(message: string | undefined): string | undefined {
  return message?.replace(/^Verification allowance used up(?: for now)?\.\s*/, "") || undefined;
}
