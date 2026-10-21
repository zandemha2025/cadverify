import { test } from "node:test";
import assert from "node:assert/strict";

import { billingStatus, formatProPrice, isStripeUrl, parsePlans, FALLBACK_PLANS, requestCheckout, requestPortal, resetBillingStatusCache, PRO_SIGN_IN_HREF } from "./billing.ts";

function fake(status: number, body: unknown, calls: Array<{ url: string; init?: RequestInit }> = []) {
  return (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
}

test("checkout follows only Stripe-hosted URLs", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const ok = await requestCheckout(fake(200, { url: "https://checkout.stripe.com/c/pay/cs_1" }, calls));
  assert.deepEqual(ok, { kind: "redirect", url: "https://checkout.stripe.com/c/pay/cs_1" });
  assert.equal(calls[0].url, "/api/proxy/billing/checkout");
  assert.equal(calls[0].init?.method, "POST");
  const hijacked = await requestCheckout(fake(200, { url: "https://evil.example/pay" }));
  assert.equal(hijacked.kind, "error");
  assert.equal(isStripeUrl("http://checkout.stripe.com/x"), false);
  assert.equal(isStripeUrl("https://billing.stripe.com/p/session/x"), true);
});

test("checkout routes signed-out, already-Pro and unavailable states", async () => {
  assert.deepEqual(await requestCheckout(fake(401, {})), { kind: "sign_in", href: PRO_SIGN_IN_HREF });
  assert.deepEqual(await requestCheckout(fake(409, { detail: { code: "already_pro", message: "x" } })), { kind: "manage" });
  const off = await requestCheckout(fake(503, { detail: { code: "billing_unavailable", message: "Online checkout isn't available right now. Email us and we'll set up Pro for you." } }));
  assert.deepEqual(off, { kind: "error", message: "Online checkout isn't available right now. Email us and we'll set up Pro for you." });
  const offline = await requestCheckout((async () => { throw new TypeError("offline"); }) as unknown as typeof fetch);
  assert.equal(offline.kind, "error");
});

test("portal opens Stripe's billing page", async () => {
  assert.deepEqual(await requestPortal(fake(200, { url: "https://billing.stripe.com/p/session/x" })), { kind: "redirect", url: "https://billing.stripe.com/p/session/x" });
  assert.equal((await requestPortal(fake(404, { detail: { message: "There's no billing on this account yet." } }))).kind, "error");
});

test("billing status is read once per page", async () => {
  resetBillingStatusCache();
  const calls: Array<{ url: string }> = [];
  const fetcher = fake(200, { checkout_available: true }, calls);
  await billingStatus(fetcher);
  await billingStatus(fetcher);
  assert.equal(calls.length, 1);
  resetBillingStatusCache();
  assert.equal(await billingStatus(fake(401, {})), null);
});

test("Pro price reads like a price tag", () => {
  assert.equal(formatProPrice({ unit_amount: 14900, currency: "usd", interval: "month" }), "$149/mo");
  assert.equal(formatProPrice({ unit_amount: 14950, currency: "usd", interval: "month" }), "$149.50/mo");
  assert.equal(formatProPrice({ unit_amount: 149000, currency: "usd", interval: "year" }), "$1,490/yr");
  assert.equal(formatProPrice(null), null);
});

test("plan facts fall back to documented defaults when the API is partial", () => {
  assert.deepEqual(parsePlans({ free: { work_checks: 20, catalog_parts: 40 }, pro: { checkout_available: true, monthly_checks: 60, price: { unit_amount: 14900, currency: "usd", interval: "month" } } }), {
    free: { work_checks: 20, personal_checks: 3, catalog_parts: 40 },
    pro: { checkout_available: true, monthly_checks: 60, price: { unit_amount: 14900, currency: "usd", interval: "month" } },
  });
  assert.deepEqual(parsePlans(null), FALLBACK_PLANS);
  assert.equal(parsePlans({ pro: { checkout_available: "yes", price: { unit_amount: "149" } } }).pro.checkout_available, false);
});
