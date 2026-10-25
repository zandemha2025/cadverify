import assert from "node:assert/strict";
import test from "node:test";
import {
  CHOICES_KEY,
  LEGACY_KEY,
  NONE,
  choicesSummary,
  effectiveChoices,
  readChoices,
  saveChoices,
  trackingFreePath,
  withdrawn,
} from "./privacy-choices.ts";

function memory(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
}

test("nothing is chosen, so nothing runs (it-23: all default off)", () => {
  assert.equal(readChoices(memory()), null);
  assert.deepEqual(effectiveChoices(null, false), NONE);
});

test("three separate choices: analytics without the business visitor tool, and the reverse", () => {
  const kv = memory();
  saveChoices({ analytics: true, recordings: false, visitors: false }, kv);
  assert.deepEqual(readChoices(kv), { analytics: true, recordings: false, visitors: false });
  saveChoices({ analytics: false, recordings: false, visitors: true }, kv);
  assert.deepEqual(readChoices(kv), { analytics: false, recordings: false, visitors: true });
});

test("recordings need analytics (PostHog records them)", () => {
  const kv = memory();
  assert.deepEqual(saveChoices({ analytics: false, recordings: true, visitors: false }, kv), NONE);
  kv.setItem(CHOICES_KEY, JSON.stringify({ analytics: false, recordings: true, visitors: false }));
  assert.equal(readChoices(kv)?.recordings, false);
});

test("the bundled v2 choice carries over as exactly what was chosen", () => {
  assert.deepEqual(readChoices(memory({ [LEGACY_KEY]: "yes" })), { analytics: true, recordings: true, visitors: true });
  assert.deepEqual(readChoices(memory({ [LEGACY_KEY]: "no" })), NONE);
  // A new choice wins over the old key.
  const kv = memory({ [LEGACY_KEY]: "yes" });
  saveChoices({ analytics: true, recordings: false, visitors: false }, kv);
  assert.deepEqual(readChoices(kv), { analytics: true, recordings: false, visitors: false });
});

test("Do Not Track turns everything off whatever is stored", () => {
  assert.deepEqual(effectiveChoices({ analytics: true, recordings: true, visitors: true }, true), NONE);
});

test("withdrawing a choice stops that vendor; only RB2B needs a reload", () => {
  const all = { analytics: true, recordings: true, visitors: true };
  assert.deepEqual(withdrawn(all, { analytics: true, recordings: false, visitors: true }), { stopAnalytics: false, stopRecordings: true, reload: false });
  assert.deepEqual(withdrawn(all, { analytics: true, recordings: true, visitors: false }), { stopAnalytics: false, stopRecordings: false, reload: true });
  assert.deepEqual(withdrawn(all, NONE), { stopAnalytics: true, stopRecordings: true, reload: true });
  assert.deepEqual(withdrawn(NONE, all), { stopAnalytics: false, stopRecordings: false, reload: false });
});

test("supplier share pages load nothing and ask nothing", () => {
  assert.equal(trackingFreePath("/s/abc123"), true);
  assert.equal(trackingFreePath("/s/cost/abc"), true);
  assert.equal(trackingFreePath("/security"), false);
  assert.equal(trackingFreePath("/sample"), false);
});

test("the menu line says what is on", () => {
  assert.equal(choicesSummary(null), "Not chosen: all off");
  assert.equal(choicesSummary({ analytics: true, recordings: false, visitors: false }), "Analytics on · Recordings off · Visitor ID off");
});
