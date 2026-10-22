import { test } from "node:test";
import assert from "node:assert/strict";

const { outOfChecksCopy, plainRefusal } = await import("./out-of-checks-copy.ts");

const plans = {
  free: { work_checks: 15, personal_checks: 3, catalog_parts: 50 },
  pro: { checkout_available: true, monthly_checks: 50, price: { unit_amount: 4900, currency: "usd", interval: "month" } },
};

test("Pro shows its price and monthly checks from the plans, and the refused file is kept", () => {
  assert.deepEqual(outOfChecksCopy(plans, true, "goblet.step"), {
    price: "$49 / month",
    monthly: "50 checks every month",
    kept: "goblet.step wasn’t checked and used no check. It waits on this device for 2 hours and checks as soon as you upgrade.",
  });
});

test("while the plans load nothing is guessed; with no price published it says checkout shows it", () => {
  assert.deepEqual(outOfChecksCopy(null, false, null), { price: "…", monthly: "…", kept: null });
  const noPrice = { ...plans, pro: { ...plans.pro, price: null } };
  assert.equal(outOfChecksCopy(noPrice, true, null).price, "Price shown at checkout");
  assert.equal(outOfChecksCopy(noPrice, true, null).monthly, "50 checks every month");
});

test("the refusal reads in plain words", () => {
  assert.equal(plainRefusal("Verification allowance used up. Your 3 free checks are used or in progress."), "Your 3 free checks are used or in progress.");
  assert.equal(plainRefusal(undefined), undefined);
});
