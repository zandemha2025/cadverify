/**
 * Pure vertex-colour computation for the CadViewer face-highlight overlay,
 * extracted from `cad-viewer.tsx` so the "locate" recolouring is unit-testable
 * WITHOUT a WebGL / three.js runtime (which the repo's `node --test` runner
 * cannot host).
 *
 * STL geometry is non-indexed, so face `i` owns the three consecutive vertices
 * `3i, 3i+1, 3i+2`. Given the vertex count, the set of highlighted face
 * indices, and the base + highlight RGB triples (each channel 0..1, matching
 * `THREE.Color`), this returns the flat `Float32Array(vertexCount * 3)` that
 * feeds the geometry `color` BufferAttribute: every vertex starts at `base`,
 * and the three vertices of each highlighted face are overwritten with
 * `highlight`.
 *
 * `THREE.Color` is structurally an `RGB` (it exposes `r`/`g`/`b`), so the
 * component passes its `Color` instances straight in; tests pass plain objects.
 */
export interface RGB {
  r: number;
  g: number;
  b: number;
}

export function computeHighlightVertexColors(
  vertexCount: number,
  highlightFaces: readonly number[],
  base: RGB,
  highlight: RGB
): Float32Array {
  const colors = new Float32Array(vertexCount * 3);
  for (let v = 0; v < vertexCount; v++) {
    colors[v * 3] = base.r;
    colors[v * 3 + 1] = base.g;
    colors[v * 3 + 2] = base.b;
  }
  for (const f of highlightFaces) {
    for (let k = 0; k < 3; k++) {
      const v = f * 3 + k;
      if (v >= 0 && v < vertexCount) {
        colors[v * 3] = highlight.r;
        colors[v * 3 + 1] = highlight.g;
        colors[v * 3 + 2] = highlight.b;
      }
    }
  }
  return colors;
}

/**
 * Per-face wall-thickness HEATMAP colour buffer — the same non-indexed
 * face→vertex path as {@link computeHighlightVertexColors} (STL face `i` owns
 * vertices `3i,3i+1,3i+2`), so the CadViewer paints a thickness heatmap through
 * the identical geometry `color` BufferAttribute the "locate" fix already wires.
 *
 * Each face colour is a linear interpolation on `[min,max]` between `thin`
 * (the hot end — the thinnest wall) and `thick` (the cool end). A face whose
 * value is `null`/`undefined` (uncomputable: open/degenerate) or non-finite is
 * left on `unmeasured` — it is NOT clamped to an end colour, so an unmeasured
 * face never masquerades as a real thin or thick reading.
 *
 * `min`/`max` are the real thickness bounds the caller derives from the map (see
 * `thicknessColorRange`); when `max <= min` every measured face collapses to
 * `thin` (a degenerate but honest single-value map). Values are clamped into
 * `[min,max]` before interpolation so an out-of-range reading can't overshoot.
 */
export function computeThicknessVertexColors(
  vertexCount: number,
  faceValues: readonly (number | null | undefined)[],
  min: number,
  max: number,
  thin: RGB,
  thick: RGB,
  unmeasured: RGB
): Float32Array {
  const colors = new Float32Array(vertexCount * 3);
  // start every vertex unmeasured; measured faces overwrite their 3 vertices
  for (let v = 0; v < vertexCount; v++) {
    colors[v * 3] = unmeasured.r;
    colors[v * 3 + 1] = unmeasured.g;
    colors[v * 3 + 2] = unmeasured.b;
  }
  const span = max - min;
  for (let f = 0; f < faceValues.length; f++) {
    const val = faceValues[f];
    if (val == null || !Number.isFinite(val)) continue; // stays unmeasured
    // t = 0 at the thinnest wall (hot), 1 at the thickest (cool)
    const clamped = val < min ? min : val > max ? max : val;
    const t = span > 0 ? (clamped - min) / span : 0;
    const r = thin.r + (thick.r - thin.r) * t;
    const g = thin.g + (thick.g - thin.g) * t;
    const b = thin.b + (thick.b - thin.b) * t;
    for (let k = 0; k < 3; k++) {
      const v = f * 3 + k;
      if (v >= 0 && v < vertexCount) {
        colors[v * 3] = r;
        colors[v * 3 + 1] = g;
        colors[v * 3 + 2] = b;
      }
    }
  }
  return colors;
}

/**
 * The real thickness bounds `[min,max]` over the finite (measured) entries of a
 * per-face value array — the honest domain for the heatmap ramp. Returns `null`
 * when NOTHING is measured (all null/non-finite), so a caller renders no heatmap
 * rather than an all-one-colour fake. Never invents a bound.
 */
export function thicknessColorRange(
  faceValues: readonly (number | null | undefined)[]
): { min: number; max: number } | null {
  let min = Infinity;
  let max = -Infinity;
  for (const v of faceValues) {
    if (v == null || !Number.isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return Number.isFinite(min) ? { min, max } : null;
}
