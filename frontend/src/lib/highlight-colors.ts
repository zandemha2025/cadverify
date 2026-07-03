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
