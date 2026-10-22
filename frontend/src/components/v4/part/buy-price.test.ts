import assert from "node:assert/strict";
import test from "node:test";
import { buyCompareText, buyPriceText, readTypedPrice } from "./buy-price.ts";

test("what you pay today reads with where it came from (oo-21)", () => {
  assert.equal(buyPriceText({ usd_each: 12.4, source: "you" }), "$12.40 each · you entered it");
  assert.equal(buyPriceText({ usd_each: 12.5, price_usd: 1250, per: 100, source: "parts_list" }), "$1,250.00 per 100 ($12.50 each) · from your parts list");
  assert.equal(buyPriceText(null), null);
});

test("making against what you pay: the saving a year, or how many times the price", () => {
  const vf2 = { usd: 38.71, machine: "Haas VF-2" };
  assert.equal(buyCompareText({ usd_each: 5.13, source: "you" }, vf2, 120), "Making it on your Haas VF-2 at $38.71 each costs 7.5× what you pay: buying it is cheaper.");
  assert.equal(buyCompareText({ usd_each: 50, source: "parts_list" }, vf2, 120), "Making it on your Haas VF-2 at $38.71 each saves $11.29 each against what you pay, $1,354.80 a year at 120 a year.");
  assert.equal(buyCompareText({ usd_each: 40, source: "you" }, vf2, null), "Making it on your Haas VF-2 at $38.71 each saves $1.29 each against what you pay.");
  assert.equal(buyCompareText({ usd_each: 30, source: "you" }, vf2, null), "Making it on your Haas VF-2 at $38.71 each costs $8.71 more than what you pay each: buying it is cheaper.");
  assert.equal(buyCompareText(null, vf2, 1), null);
});

test("a typed price is read in dollars with an optional per count", () => {
  assert.deepEqual(readTypedPrice("$1,250", "100"), { price_usd: 1250, per: 100 });
  assert.deepEqual(readTypedPrice("12.40", ""), { price_usd: 12.4, per: 1 });
  assert.equal(readTypedPrice("", ""), null);
  assert.match(String(readTypedPrice("abc", "")), /US dollars/);
  assert.match(String(readTypedPrice("3", "1.5")), /how many parts/);
});
