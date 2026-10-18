import assert from "node:assert/strict";
import test from "node:test";

import {
  envelopeOf,
  isoBox,
  machineStatus,
  opOn,
  perHour,
  procName,
  rateCardView,
  tileSub,
  toggleOp,
  versionInEffect,
} from "./shop-derive.ts";

const vf2 = {
  name: "Haas VF-2",
  process: "cnc_3axis",
  count: 1,
  hourly_rate_usd: 85,
  max_workpiece_kg: 200,
  capabilities: { x: 762, y: 406, z: 508, axes: 3 },
};

test("every method has a plain name; unknown ids pass through", () => {
  assert.equal(procName("cnc_turning"), "Lathe (CNC turning)");
  assert.equal(procName("mjf"), "Nylon powder printing (MJF)");
  assert.equal(procName("plasma"), "plasma");
});

test("status says owned with or without a declared rate", () => {
  assert.deepEqual(machineStatus(vf2), { label: "Owned · rate declared", rated: true });
  assert.deepEqual(machineStatus({ hourly_rate_usd: null }), { label: "Owned · no rate", rated: false });
  // A declared rate of 0 is still a declaration.
  assert.equal(machineStatus({ hourly_rate_usd: 0 }).rated, true);
});

test("envelope reads the keys the API stores, lathe swing first", () => {
  assert.equal(envelopeOf(vf2)?.text, "762 × 406 × 508 mm");
  const lathe = envelopeOf({ process: "cnc_turning", capabilities: { swing_dia: 254, between_centers: 533 } });
  assert.equal(lathe?.text, "Ø254 × 533 mm");
  assert.equal(lathe?.label, "Swing × between centers");
  // A lathe saved before the swing keys still shows what was declared, labelled as such.
  const legacy = envelopeOf({ process: "cnc_turning", capabilities: { x: 254, y: 254, z: 533 } });
  assert.equal(legacy?.label, "Work area (declared X × Y × Z)");
  assert.equal(envelopeOf({ process: "cnc_3axis", capabilities: {} }), null);
  assert.equal(envelopeOf({ process: "cnc_3axis", capabilities: { x: "762", y: 406 } }), null);
});

test("the drawing fits the 300 × 150 view box for very different shapes", () => {
  for (const [w, d, h] of [[762, 406, 508], [256, 256, 256], [1800, 1000, 700], [50, 50, 1000], [1000, 1000, 5]]) {
    const nums = Object.values(isoBox(w, d, h)).join(" ").match(/-?\d+(\.\d+)?/g)!.map(Number);
    const xs = nums.filter((_, i) => i % 2 === 0);
    const ys = nums.filter((_, i) => i % 2 === 1);
    assert.ok(Math.min(...xs) >= 0 && Math.max(...xs) <= 300, `x in box for ${w}×${d}×${h}`);
    assert.ok(Math.min(...ys) >= 0 && Math.max(...ys) <= 150, `y in box for ${w}×${d}×${h}`);
  }
});

test("tile line never invents a rate or weight", () => {
  assert.equal(tileSub(vf2), "3-axis milling · ×1 · $85/h · 200 kg max");
  assert.equal(tileSub({ ...vf2, process: "cnc_turning", hourly_rate_usd: null, max_workpiece_kg: null, count: null }), "Lathe · ×1 · no rate");
  assert.equal(perHour(85.5), "$85.50/h");
});

test("shop ops: toggling one keeps the others and a declared limits object", () => {
  const ops = { hip: { dia_mm: 300, height_mm: 600 }, grinding: true, anodize: true, sinter: false };
  assert.equal(opOn(ops, "hip"), true);
  assert.equal(opOn(ops, "sinter"), false);
  assert.deepEqual(toggleOp(ops, "sinter"), { ...ops, sinter: true });
  const off = toggleOp(ops, "grinding");
  assert.deepEqual(off, { hip: { dia_mm: 300, height_mm: 600 }, anodize: true, sinter: false });
});

test("rate card: default v0 with nothing authored", () => {
  const v = rateCardView({ using_governed: false, flag_enabled: true }, []);
  assert.equal(v?.chip, "Default v0");
  assert.equal(v?.chipLong, "Default v0 · none authored");
  assert.equal(v?.aria, "Rate card: default v0, none authored. Show details");
  assert.equal(v?.counts, "Built-in default rates. 0 versions authored, 0 published.");
  assert.equal(rateCardView(null, []), null);
});

test("rate card: authored drafts are not in effect until published", () => {
  const v = rateCardView({ using_governed: false, flag_enabled: true }, [{ id: 2, version: 2, status: "draft" }, { id: 1, version: 1, status: "draft" }]);
  assert.equal(v?.chipLong, "Default v0 · 2 authored, none in effect");
  assert.equal(v?.drafts, 2);
});

test("rate card: governed names the version in effect now", () => {
  const now = Date.parse("2026-10-18T12:00:00Z");
  const versions = [
    { id: 3, version: 3, status: "published", effective_from: "2026-11-01T00:00:00Z" },
    { id: 2, version: 2, status: "published", effective_from: "2026-10-01T00:00:00Z" },
    { id: 1, version: 1, status: "archived", effective_from: "2026-09-01T00:00:00Z" },
  ];
  assert.equal(versionInEffect(versions, now)?.version, 2);
  const v = rateCardView({ using_governed: true, flag_enabled: true }, versions, now);
  assert.equal(v?.chip, "Governed · 2 published");
  assert.equal(v?.chipLong, "Governed · v2 in effect");
  assert.equal(v?.title, "Rate card v2");
});
