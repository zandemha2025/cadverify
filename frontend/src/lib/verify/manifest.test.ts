/**
 * Pure tests for the declared-manifest render-model (lib/verify/manifest) — run
 * under the repo's `node --test` type-stripping runner. No React, no fetch, no DB.
 *
 * The whole point of these helpers is HONESTY: coverage is never overstated, and a
 * declared part with no geometry is never given a cost or verdict.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  readManifestCoverage,
  coverageHeadline,
  allAwaitingGeometry,
  awaitingGeometryLabel,
  hasDeclared,
  partMetaBits,
  type ManifestCoverage,
  type ManifestPart,
} from "./manifest.ts";

const COV_ALL_DECLARED: ManifestCoverage = {
  org_id: "org_1",
  total_declared: 8,
  by_program: [{ program: "GreenField-Phase1", count: 8 }],
  geometry: { with_geometry: 0, without_geometry: 8, match: "normalized-stem, exact" },
};

test("headline: 8 declared / 0 geometry says every one awaits a part upload (never rounded up)", () => {
  assert.equal(
    coverageHeadline(COV_ALL_DECLARED),
    "8 declared parts · none have geometry yet — all 8 await a part upload before they can be costed."
  );
});

test("headline: a partial split states both sides honestly", () => {
  const cov: ManifestCoverage = {
    ...COV_ALL_DECLARED,
    geometry: { with_geometry: 3, without_geometry: 5, match: "normalized-stem, exact" },
  };
  assert.equal(
    coverageHeadline(cov),
    "8 declared parts · 3 with geometry (costed above) · 5 still awaiting geometry."
  );
});

test("headline: all-with-geometry and empty are both honest", () => {
  const all: ManifestCoverage = {
    ...COV_ALL_DECLARED,
    geometry: { with_geometry: 8, without_geometry: 0, match: "normalized-stem, exact" },
  };
  assert.equal(coverageHeadline(all), "8 declared parts · all 8 have matching geometry and are costed in the buckets above.");
  const empty: ManifestCoverage = { ...COV_ALL_DECLARED, total_declared: 0, by_program: [], geometry: { with_geometry: 0, without_geometry: 0, match: "x" } };
  assert.equal(coverageHeadline(empty), "No declared parts yet — import a BOM to register your inventory.");
});

test("headline: 1 declared part reads singular", () => {
  const one: ManifestCoverage = {
    ...COV_ALL_DECLARED,
    total_declared: 1,
    geometry: { with_geometry: 0, without_geometry: 1, match: "x" },
  };
  assert.equal(coverageHeadline(one), "1 declared part · none have geometry yet — all 1 await a part upload before they can be costed.");
});

test("allAwaitingGeometry: true only when zero parts have geometry", () => {
  assert.equal(allAwaitingGeometry(COV_ALL_DECLARED), true);
  assert.equal(
    allAwaitingGeometry({ ...COV_ALL_DECLARED, geometry: { with_geometry: 1, without_geometry: 7, match: "x" } }),
    false
  );
});

test("awaitingGeometryLabel: uses the without_geometry count, pluralized", () => {
  assert.equal(awaitingGeometryLabel(COV_ALL_DECLARED), "Declared · awaiting geometry — 8 parts");
  assert.equal(
    awaitingGeometryLabel({ ...COV_ALL_DECLARED, geometry: { with_geometry: 7, without_geometry: 1, match: "x" } }),
    "Declared · awaiting geometry — 1 part"
  );
});

test("hasDeclared: true when the org has any declared part, false on null/empty", () => {
  assert.equal(hasDeclared(COV_ALL_DECLARED), true);
  assert.equal(hasDeclared(null), false);
  assert.equal(hasDeclared({ ...COV_ALL_DECLARED, total_declared: 0 }), false);
});

test("readManifestCoverage: coerces a real body, filters zero-count programs, rejects a non-body", () => {
  const parsed = readManifestCoverage({
    org_id: "org_1",
    total_declared: 8,
    by_program: [
      { program: "GreenField-Phase1", count: 8 },
      { program: "(unassigned)", count: 0 },
    ],
    geometry: { with_geometry: 0, without_geometry: 8, match: "normalized-stem, exact" },
  });
  assert.ok(parsed);
  assert.equal(parsed?.total_declared, 8);
  assert.equal(parsed?.by_program.length, 1);
  assert.equal(parsed?.geometry.without_geometry, 8);
  assert.equal(readManifestCoverage(null), null);
  assert.equal(readManifestCoverage({ nope: true }), null);
});

test("partMetaBits: lists ONLY declared fields — nothing fabricated for absent metadata", () => {
  const bare: ManifestPart = {
    id: "u1", part_id: "AR-1", description: null, material_class: null, program: null,
    parent_assembly: null, units_per_parent: null, annual_volume: null, quantity: null,
    region: null, source: null, notes: null, created_at: null, updated_at: null,
  };
  assert.deepEqual(partMetaBits(bare), []);
  const full: ManifestPart = { ...bare, material_class: "steel", quantity: 4, annual_volume: 120, parent_assembly: "PMP-ASSY-01", region: "SA" };
  assert.deepEqual(partMetaBits(full), ["steel", "qty 4", "120/yr", "↳ PMP-ASSY-01", "SA"]);
});
