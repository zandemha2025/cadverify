import { test } from "node:test";
import assert from "node:assert/strict";
import { acquireWebGlContext } from "./webgl.ts";

// Regression: ISSUE-UX-001 — the marketing site crashed when WebGL was absent.
// Found by /qa on 2026-07-11.
// Report: .gstack/qa-reports/qa-report-journey-audit-localhost-2026-07-11.md

test("acquireWebGlContext prefers WebGL2 without probing the legacy context", () => {
  const webgl2 = { kind: "webgl2" } as unknown as WebGL2RenderingContext;
  const calls: string[] = [];
  const canvas = {
    getContext(kind: string) {
      calls.push(kind);
      return kind === "webgl2" ? webgl2 : null;
    },
  } as unknown as HTMLCanvasElement;

  assert.equal(acquireWebGlContext(canvas), webgl2);
  assert.deepEqual(calls, ["webgl2"]);
});

test("acquireWebGlContext falls back to WebGL1", () => {
  const webgl = { kind: "webgl" } as unknown as WebGLRenderingContext;
  const calls: string[] = [];
  const canvas = {
    getContext(kind: string) {
      calls.push(kind);
      return kind === "webgl" ? webgl : null;
    },
  } as unknown as HTMLCanvasElement;

  assert.equal(acquireWebGlContext(canvas), webgl);
  assert.deepEqual(calls, ["webgl2", "webgl"]);
});

test("acquireWebGlContext returns null when contexts are absent or blocked", () => {
  const absent = {
    getContext() {
      return null;
    },
  } as unknown as HTMLCanvasElement;
  const blocked = {
    getContext() {
      throw new Error("GPU policy blocked context creation");
    },
  } as unknown as HTMLCanvasElement;

  assert.equal(acquireWebGlContext(absent), null);
  assert.equal(acquireWebGlContext(blocked), null);
});
