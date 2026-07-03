/**
 * Unit tests for the CadViewer face-highlight vertex-colour core.
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping. No three.js / WebGL needed — the colour computation is pure.
 *
 * This is the code-level proof for the "locate" highlight fix: it asserts that
 * when `highlightFaces` is non-empty the colour buffer that feeds the geometry
 * `color` attribute recolours EXACTLY the three vertices of each highlighted
 * face to the highlight tone and leaves every other vertex on the base tone.
 * (The companion runtime half of the fix — flipping `material.needsUpdate` so
 * three.js recompiles with `USE_COLOR` and actually paints this buffer — lives
 * in cad-viewer.tsx and is exercised in the browser.)
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  computeHighlightVertexColors,
  computeThicknessVertexColors,
  thicknessColorRange,
} from "./highlight-colors.ts";

// Values chosen to be EXACTLY representable in float32 (the buffer's storage
// type) so `strictEqual` round-trips without epsilon fuzz.
const BASE = { r: 0.25, g: 0.5, b: 0.75 };
const HL = { r: 1, g: 0, b: 0.5 };

test("no highlighted faces → every vertex stays on the base colour", () => {
  const colors = computeHighlightVertexColors(6, [], BASE, HL);
  assert.equal(colors.length, 6 * 3);
  for (let v = 0; v < 6; v++) {
    assert.equal(colors[v * 3], BASE.r);
    assert.equal(colors[v * 3 + 1], BASE.g);
    assert.equal(colors[v * 3 + 2], BASE.b);
  }
});

test("a highlighted face recolours EXACTLY its three vertices to the highlight tone", () => {
  // 3 faces → 9 vertices. Highlight face 1 → vertices 3,4,5 (non-indexed STL).
  const colors = computeHighlightVertexColors(9, [1], BASE, HL);
  for (const v of [3, 4, 5]) {
    assert.equal(colors[v * 3], HL.r, `vertex ${v} R should be highlight`);
    assert.equal(colors[v * 3 + 1], HL.g, `vertex ${v} G should be highlight`);
    assert.equal(colors[v * 3 + 2], HL.b, `vertex ${v} B should be highlight`);
  }
  for (const v of [0, 1, 2, 6, 7, 8]) {
    assert.equal(colors[v * 3], BASE.r, `vertex ${v} should stay base`);
    assert.equal(colors[v * 3 + 1], BASE.g);
    assert.equal(colors[v * 3 + 2], BASE.b);
  }
});

test("multiple highlighted faces each light up their own vertices", () => {
  const colors = computeHighlightVertexColors(9, [0, 2], BASE, HL);
  for (const v of [0, 1, 2, 6, 7, 8]) {
    assert.equal(colors[v * 3], HL.r, `vertex ${v} R should be highlight`);
  }
  for (const v of [3, 4, 5]) {
    assert.equal(colors[v * 3], BASE.r, `vertex ${v} R should stay base`);
  }
});

test("out-of-range face indices are ignored (no buffer overflow)", () => {
  const colors = computeHighlightVertexColors(3, [99], BASE, HL);
  assert.equal(colors.length, 3 * 3);
  for (let v = 0; v < 3; v++) {
    assert.equal(colors[v * 3], BASE.r, "no face fits, everything stays base");
  }
});

/* ------------------------------------------------------------------ */
/*  Wall-thickness heatmap buffer (opt-in thin-wall map — item #3)      */
/*  RGB stops chosen to be EXACTLY representable in float32.            */
/* ------------------------------------------------------------------ */

const THIN = { r: 1, g: 0, b: 0 };      // hot end (thinnest wall)
const THICK = { r: 0, g: 0, b: 1 };     // cool end (thickest wall)
const UNMEASURED = { r: 0.5, g: 0.5, b: 0.5 };

test("thicknessColorRange: bounds over the finite entries only", () => {
  assert.deepEqual(thicknessColorRange([2, null, 5, undefined, 1]), { min: 1, max: 5 });
});

test("thicknessColorRange: null when nothing is measured (no faked range)", () => {
  assert.equal(thicknessColorRange([null, undefined, Infinity, NaN]), null);
});

test("thickness heatmap: linear ramp thin→thick, midpoint interpolates", () => {
  // 3 faces (9 verts): min-wall, mid-wall, max-wall over [1,3]
  const colors = computeThicknessVertexColors(9, [1, 2, 3], 1, 3, THIN, THICK, UNMEASURED);
  // face 0 (val=1, t=0) → THIN
  assert.equal(colors[0], 1); assert.equal(colors[2], 0);
  // face 1 (val=2, t=0.5) → midpoint (0.5, 0, 0.5)
  assert.equal(colors[3 * 3], 0.5); assert.equal(colors[3 * 3 + 2], 0.5);
  // face 2 (val=3, t=1) → THICK
  assert.equal(colors[6 * 3], 0); assert.equal(colors[6 * 3 + 2], 1);
});

test("thickness heatmap: null/non-finite faces stay UNMEASURED (never faked)", () => {
  const colors = computeThicknessVertexColors(6, [null, NaN], 1, 3, THIN, THICK, UNMEASURED);
  for (let v = 0; v < 6; v++) {
    assert.equal(colors[v * 3], UNMEASURED.r, `vertex ${v} R unmeasured`);
    assert.equal(colors[v * 3 + 2], UNMEASURED.b, `vertex ${v} B unmeasured`);
  }
});

test("thickness heatmap: out-of-range values clamp into [min,max]", () => {
  // val below min and above max clamp to the ends, not overshoot
  const colors = computeThicknessVertexColors(6, [0.1, 99], 1, 3, THIN, THICK, UNMEASURED);
  assert.equal(colors[0], 1); assert.equal(colors[2], 0);          // → THIN
  assert.equal(colors[3 * 3], 0); assert.equal(colors[3 * 3 + 2], 1); // → THICK
});

test("thickness heatmap: degenerate max<=min collapses measured faces to THIN", () => {
  const colors = computeThicknessVertexColors(3, [2], 2, 2, THIN, THICK, UNMEASURED);
  assert.equal(colors[0], 1); assert.equal(colors[2], 0);
});
