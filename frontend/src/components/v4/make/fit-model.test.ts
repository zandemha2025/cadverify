/**
 * Fit in assembly rules: access is decided before any file moves, file kinds and
 * units, the nudge, seating words, and how the measured result reads.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/make/fit-model.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { FitResult } from "../../../lib/verify/context-fit";
import {
  bandText,
  callout,
  canPaintFaces,
  figures,
  fileKind,
  fileSub,
  goHint,
  isFitFile,
  mm,
  needsUnits,
  nudgeInvalid,
  nudgeValues,
  resolveAccess,
  seatMeta,
  seatingLine,
  seatingWord,
  translation,
} from "./fit-model.ts";

const cap = (over: Partial<{ enabled: boolean; paid_access: boolean; can_submit: boolean }>) => ({
  kind: "ok" as const,
  cap: { enabled: true, paid_access: true, can_submit: true, available: true, ...over },
});

test("access: the server setting, then the role; the plan never gates it", () => {
  assert.equal(resolveAccess({ kind: "loading" }, true), "loading");
  assert.equal(resolveAccess(cap({ enabled: false }), true), "off");
  assert.equal(resolveAccess(cap({ can_submit: false }), false), "viewer");
  assert.equal(resolveAccess(cap({}), false), "viewer");
  assert.equal(resolveAccess(cap({}), true), "on");
  assert.equal(resolveAccess({ kind: "error", message: "x" }, true), "error");
  // A free trial account: the probe answers paid_access true; even an older
  // server's false no longer shows a gate (the measurement says what it says).
  assert.equal(resolveAccess(cap({ paid_access: false }), true), "on");
});

test("a server without the probe offers no fit", () => {
  assert.equal(resolveAccess({ kind: "missing" }, true), "off");
  assert.equal(resolveAccess({ kind: "missing" }, false), "off");
});

test("file kinds and units", () => {
  assert.equal(isFitFile("a.STL"), true);
  assert.equal(isFitFile("a.3mf"), true);
  assert.equal(isFitFile("a.igs"), true);
  assert.equal(isFitFile("a.zip"), false);
  assert.equal(needsUnits("part.obj"), true);
  assert.equal(needsUnits("part.step"), false);
  assert.equal(fileKind("x.stp"), "STEP");
  assert.equal(fileKind("x.igs"), "IGES");
  assert.equal(fileSub({ name: "b.stl", size: 1536 }, null), "STL · 2 KB");
  assert.equal(fileSub({ name: "b.stl", size: 1536 }, 33992), "STL · 33,992 faces");
  assert.equal(fileSub({ name: "a.step", size: 3 * 1024 * 1024 }, null), "STEP · 3.0 MB");
});

test("nudge: every offset must be a finite number", () => {
  assert.deepEqual(nudgeInvalid(["0", "1.5", "-2"]), [false, false, false]);
  assert.deepEqual(nudgeInvalid(["", "abc", "Infinity"]), [true, true, true]);
  assert.deepEqual(nudgeValues(["0", "1.5", "-2"]), [0, 1.5, -2]);
  assert.deepEqual(translation([1, 2, 3]), [
    [1, 0, 0, 1],
    [0, 1, 0, 2],
    [0, 0, 1, 3],
    [0, 0, 0, 1],
  ]);
});

const base: FitResult = {
  coordinate_frame: "part_a_source_frame",
  seating: { method: "shared_frame", accepted: true, reason: "", transform: translation([0, 0, 0]), manual_nudge_mm: [0, 0, 0] },
  collision: { intersects: false, volume_mm3: 0, method: "m", region: null },
  clearance: { closest_sampled_gap_mm: 0.3, method: "s", tight_zone: { region_center: [1, 2, 3], part_a_faces: [4, 5], part_b_faces: [], sample_count: 20 } },
  timing_ms: { collision_boolean: 1, sampled_clearance: 2, pair_total: 3 },
  limits: [],
};
const overlap: FitResult = {
  ...base,
  collision: {
    intersects: true,
    volume_mm3: 960,
    method: "m",
    region: { region_center: [0, 0, 0], part_a_faces: [], part_b_faces: [], render_geometry: { available: true, data: "x" } },
  },
  clearance: { ...base.clearance, closest_sampled_gap_mm: 0 },
};

test("seating words", () => {
  assert.equal(seatMeta("shared_frame"), "Seated from the assembly file");
  assert.equal(seatMeta("auto"), "Seated automatically");
  assert.equal(seatingLine(null), "Results withheld until this pair is checked.");
  assert.equal(seatingLine(base), "Shared CAD frame: both files keep their own coordinates.");
  assert.equal(seatingLine({ seating: { ...base.seating, manual_nudge_mm: [0, 0, 2] } }), "Position set by you.");
  assert.equal(seatingLine({ seating: { ...base.seating, method: "auto_planar", manual_nudge_mm: [1, 0, 0] } }), "Automatically aligned, then offset by you.");
  assert.match(seatingLine({ seating: { ...base.seating, method: "auto_planar", accepted: false } }), /Couldn’t seat this/);
  assert.equal(seatingWord(null), "—");
  assert.equal(seatingWord({ seating: { ...base.seating, method: "auto_planar" } }), "Aligned");
});

test("figures and callouts read the measured result, never estimate it", () => {
  assert.deepEqual(figures(null), { volume: "—", gap: "—", seating: "—", overlap: false });
  assert.deepEqual(figures(base), { volume: "0.00", gap: "0.300", seating: "Shared frame", overlap: false });
  assert.deepEqual(figures(overlap), { volume: "960.00", gap: "0.00", seating: "Shared frame", overlap: true });
  assert.equal(mm(1234.5), "1,234.50");
  assert.equal(mm(Number.NaN), "—");
  assert.equal(callout(overlap, "col", true).value, "960.00 mm³ measured overlap");
  assert.equal(callout(base, "col", true).value, "No measured overlap");
  assert.equal(callout(base, "gap", true).next, "Blue faces are within 0.05 mm of the closest gap.");
  assert.equal(callout(base, "gap", false).next, "The blue marker is the centre of the closest-gap zone.");
  assert.equal(callout(overlap, "gap", true).value, "0.00 mm · the parts overlap");
  const noShell: FitResult = { ...overlap, collision: { ...overlap.collision, region: { ...overlap.collision.region!, render_geometry: { available: false } } } };
  assert.match(callout(noShell, "col", true).next, /marker shows its centre/);
  assert.equal(bandText({ ...base, clearance: { ...base.clearance, tight_zone: { ...base.clearance.tight_zone, band_mm: 0.12 } as FitResult["clearance"]["tight_zone"] } }), "0.12");
});

test("faces are painted only on the exact measured mesh", () => {
  assert.equal(canPaintFaces(null), false);
  assert.equal(canPaintFaces({ decimated: true }), false);
  assert.equal(canPaintFaces({ decimated: false }), true);
});

test("the hint beside Check fit", () => {
  const s = { measured: false, running: false, hasFiles: true, nudgeBad: false, changed: false };
  assert.equal(goHint({ ...s, running: true }), "Overlap volume and closest gap");
  assert.equal(goHint({ ...s, measured: true }), "Measured on the submitted files");
  assert.equal(goHint({ ...s, hasFiles: false }), "Add both files");
  assert.equal(goHint({ ...s, nudgeBad: true }), "Fix the offsets first");
  assert.equal(goHint({ ...s, changed: true }), "Inputs changed since the last check");
});
