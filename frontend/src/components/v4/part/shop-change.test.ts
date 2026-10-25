import test from "node:test";
import assert from "node:assert/strict";
import { asOfCheck, shopChangeText, shopChangedSince } from "./shop-change.ts";

// me-11: bracket.step checked 16:14; the Amada's heaviest part declared 23 kg at 16:12 before that check… and
// the tester's first answer (16:02) predates the 16:12 edit, which also marked it out of date.
const machines = [
  { id: "vf2", name: "Haas VF-2", process: "cnc_3axis", created_at: "2026-10-22T15:31:00Z", updated_at: "2026-10-22T15:32:35Z" },
  { id: "amada", name: "Amada HG-1003 press brake", process: "sheet_metal", created_at: "2026-10-22T15:35:00Z", updated_at: "2026-10-22T16:12:56Z" },
];

test("an answer worked out before a machine was edited says so (me-11)", () => {
  const record = { created_at: "2026-10-22T16:02:24Z", is_stale: true, stale_at: "2026-10-22T16:12:56Z", stale_reason: "machine_inventory_changed" };
  const c = shopChangedSince(machines, record, null)!;
  assert.deepEqual(c.machines.map((m) => [m.id, m.added]), [["amada", false]]);
  assert.equal(c.staleAt, "2026-10-22T16:12:56Z");
  assert.equal(shopChangeText(c), "Your Amada HG-1003 press brake was edited after this check");
});

test("an answer worked out after the edit is current; nothing is said", () => {
  assert.equal(shopChangedSince(machines, { created_at: "2026-10-22T16:14:34Z" }, null), null);
});

test("a machine added after the check, several changes, and a removed machine (only the out-of-date mark)", () => {
  const added = [...machines, { id: "laser", name: "Trumpf TruLaser", process: "sheet_metal", created_at: "2026-10-22T17:00:00Z", updated_at: "2026-10-22T17:00:00Z" }];
  const c = shopChangedSince(added, { created_at: "2026-10-22T16:14:34Z" }, null)!;
  assert.equal(shopChangeText(c), "Your Trumpf TruLaser was added after this check");
  assert.equal(shopChangeText(shopChangedSince(added, { created_at: "2026-10-22T16:00:00Z" }, null)!), "2 of your machines were added or edited after this check");
  const removed = shopChangedSince(machines, { created_at: "2026-10-22T16:14:34Z", is_stale: true, stale_at: "2026-10-22T17:30:00Z", stale_reason: "machine_inventory_changed" }, null)!;
  assert.deepEqual(removed.machines, []);
  assert.equal(shopChangeText(removed), "Your machines changed after this check");
  // Out of date for another reason (a rate card): not a shop change.
  assert.equal(shopChangedSince(machines, { created_at: "2026-10-22T16:14:34Z", is_stale: true, stale_reason: "rate_card_published" }, null), null);
  // No record time and nothing marked: unknown, nothing said.
  assert.equal(shopChangedSince(machines, null, null), null);
});

test("a changed machine's row says its reason as of the check, never next to the new value as if current", () => {
  assert.equal(
    asOfCheck("Max workpiece weight not declared. Declare it in Your shop to confirm.", true),
    "At this check: max workpiece weight not declared. Declare it in Your shop to confirm. You've changed this machine since; re-check to see it as it is now.",
  );
  assert.equal(asOfCheck("Fits its work area.", false), "Fits its work area.");
});
