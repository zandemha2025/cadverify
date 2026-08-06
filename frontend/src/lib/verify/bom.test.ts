/**
 * Unit tests for the BOM breadcrumb derivations (bom.ts) — Slice 3.
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (type-only imports, no runtime relative imports).
 *
 * Pins the honesty contract:
 *   (a) a breadcrumb is `present` ONLY when a real tree grounds the part; an
 *       absent/empty ancestry never renders an invented chain;
 *   (b) the chain is child → root verbatim, and `perVehicle` is the rolled-up
 *       multiplier from the real tree;
 *   (c) a shared part (a DAG with >1 root-path) is flagged `shared`;
 *   (d) the basis chip is BOM ROLLUP vs DECLARED, and null (omitted) for a part
 *       with no volume — never a fabricated figure.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { bomBreadcrumbView, basisChip } from "./bom.ts";
import type { BomAncestry } from "./bom.ts";

function anc(over: Partial<BomAncestry> = {}): BomAncestry {
  return {
    assembly_key: "as1",
    child_ref: "bolt",
    has_tree: true,
    ancestry: ["bolt", "nut-bolt-assembly", "l-bracket-assembly", "as1"],
    ancestry_paths: [["bolt", "nut-bolt-assembly", "l-bracket-assembly", "as1"]],
    rolled_up_multiplier: 6,
    roots: ["as1"],
    ...over,
  };
}

test("bomBreadcrumbView: real tree → present chain child→root + per-vehicle", () => {
  const v = bomBreadcrumbView(anc());
  assert.equal(v.present, true);
  assert.deepEqual(v.chain, ["bolt", "nut-bolt-assembly", "l-bracket-assembly", "as1"]);
  assert.equal(v.perVehicle, 6);
  assert.equal(v.shared, false);
});

test("bomBreadcrumbView: no tree → NOT present, never an invented chain", () => {
  const v = bomBreadcrumbView(
    anc({ has_tree: false, ancestry: [], ancestry_paths: [], rolled_up_multiplier: null })
  );
  assert.equal(v.present, false);
  assert.deepEqual(v.chain, []);
  assert.equal(v.perVehicle, null);
});

test("bomBreadcrumbView: null response → not present (honest absent)", () => {
  const v = bomBreadcrumbView(null);
  assert.equal(v.present, false);
  assert.deepEqual(v.chain, []);
});

test("bomBreadcrumbView: a shared part (DAG, >1 path) is flagged shared", () => {
  const v = bomBreadcrumbView(
    anc({
      child_ref: "nut",
      ancestry: ["nut", "rod-assembly", "as1"],
      ancestry_paths: [
        ["nut", "rod-assembly", "as1"],
        ["nut", "nut-bolt-assembly", "l-bracket-assembly", "as1"],
      ],
      rolled_up_multiplier: 8,
    })
  );
  assert.equal(v.present, true);
  assert.equal(v.shared, true);
  assert.equal(v.perVehicle, 8);
});

test("basisChip: BOM ROLLUP vs DECLARED, and omitted for no-volume", () => {
  assert.deepEqual(basisChip("bom_rollup"), { text: "BOM ROLLUP", tone: "rollup" });
  assert.deepEqual(basisChip("declared"), { text: "DECLARED", tone: "declared" });
  assert.equal(basisChip("default"), null);
  assert.equal(basisChip(null), null);
});
