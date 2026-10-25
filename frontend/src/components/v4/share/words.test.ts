import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_LINK_DAYS, LINK_DAYS, dateBounds, endsText, linkPayload, madeText, replacesText, seesLines } from "./words.ts";

const NOW = new Date(2026, 9, 22, 15, 0);
const SHOWS = { includeCost: false, includeCad: false, note: "", quantity: "" };

test("a link lasts 7 days unless 1, 30 or 90 days or a date is picked (it-22, buyer-12)", () => {
  assert.equal(DEFAULT_LINK_DAYS, 7);
  assert.deepEqual(LINK_DAYS.map((c) => c.value), [1, 7, 30, 90]);
  assert.equal(endsText({ days: 7, date: null }, NOW), "Works for 7 days, until 29 Oct 2026.");
  assert.equal(endsText({ days: 1, date: null }, NOW), "Works for 1 day, until 23 Oct 2026.");
  assert.equal(endsText({ days: null, date: "2026-11-05" }, NOW), "Works until the end of 5 Nov 2026.");
  assert.equal(endsText({ days: null, date: null }, NOW), "Pick a day.");
  assert.deepEqual(dateBounds(NOW), { min: "2026-10-22", max: "2027-10-22" });
});

test("the request a part's link sends: no cost and no CAD unless chosen", () => {
  assert.deepEqual(linkPayload("record", { days: 7, date: null }, SHOWS, NOW), {
    ok: true, body: { expires_in_days: 7, include_cost: false, include_cad: false, note: null, quantity: null } });
  assert.deepEqual(linkPayload("record", { days: null, date: "2026-11-05" }, { includeCost: true, includeCad: true, note: " Quote by Nov 5 ", quantity: "250" }, NOW), {
    ok: true, body: { expires_on: "2026-11-05", include_cost: true, include_cad: true, note: "Quote by Nov 5", quantity: 250 } });
  assert.deepEqual(linkPayload("package", { days: 30, date: null }, null, NOW), { ok: true, body: { expires_in_days: 30 } });
  assert.deepEqual(linkPayload("record", { days: null, date: "2026-10-01" }, SHOWS, NOW), { ok: false, error: "That day has passed. Pick today or a later day." });
  assert.deepEqual(linkPayload("record", { days: null, date: "2028-01-01" }, SHOWS, NOW), { ok: false, error: "A link lasts a year at most. Pick an earlier day." });
  assert.deepEqual(linkPayload("record", { days: 7, date: null }, { ...SHOWS, quantity: "2.5" }, NOW), { ok: false, error: "Quantity is a whole number from 1 to 10,000,000." });
});

test("what the supplier will see, as the sharer picks it", () => {
  const specs = ["Finish: Anodize, Type II, Ra 1.6 µm", "Supplier must hold: AS9100"];
  assert.deepEqual(seesLines({ kind: "record", name: "plate.step", specs, shows: SHOWS }), [
    "plate.step: its size and material", "Finish: Anodize, Type II, Ra 1.6 µm · Supplier must hold: AS9100"]);
  assert.deepEqual(seesLines({ kind: "record", name: "plate.step", specs: [], shows: { includeCost: true, includeCad: true, note: "x", quantity: "250" } }), [
    "plate.step: its size and material", "Specs: none declared on the part", "Quantity: 250", "Your note", "The CAD file, to download",
    "Your cost estimate: the price per part, its lines and the process it picks"]);
  assert.deepEqual(seesLines({ kind: "package", name: "RFQ-1022", parts: 2, cadParts: 2, packageHasCost: false }), [
    "The request for quote: 2 parts, each with material, quantity and specs, your note and reply-by date",
    "CAD files for 2 of 2, and the whole package as a ZIP", "None of your cost: the package was built without it"]);
  assert.deepEqual(seesLines({ kind: "check", name: "bracket.stl" }), ["bracket.stl: its size, the findings and measurements", "No prices and no file"]);
});

test("after the link is made, and when one is already on", () => {
  assert.equal(madeText("2026-10-29T15:00:00+00:00"), "Link copied. Anyone with it can open it without signing in, until 29 Oct 2026.");
  assert.equal(madeText(null), "Link copied. Anyone with it can open it without signing in. It has no end date.");
  assert.equal(replacesText("2026-11-21T00:00:00+00:00"), "A link is already on, until 21 Nov 2026. A new link switches that one off.");
});
