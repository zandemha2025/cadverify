import assert from "node:assert/strict";
import test from "node:test";

import { reconstructionViewModel } from "./reconstruction-result.ts";

test("unit-interval confidence is converted exactly once to a percent", () => {
  const view = reconstructionViewModel({
    reconstruction: {
      confidence: {
        score: 0.823,
        scale: "unit_interval",
        level: "high",
        message: null,
      },
      mesh: { url: "/mesh.stl", face_count: 12_345 },
      duration_ms: 100,
      method: "local",
    },
    analysis: { id: "01ANALYSIS", url: "/api/v1/analyses/01ANALYSIS" },
  });

  assert.deepEqual(view, {
    confidencePercent: 82.3,
    confidenceLevel: "high",
    analysisId: "01ANALYSIS",
    faceCount: 12_345,
  });
});

test("confidence display is bounded even if a malformed score escapes the API", () => {
  const view = reconstructionViewModel({
    reconstruction: {
      confidence: {
        score: 1.4,
        scale: "unit_interval",
        level: "high",
        message: null,
      },
      mesh: { url: "/mesh.stl", face_count: 1 },
      duration_ms: 1,
      method: "local",
    },
    analysis: null,
  });
  assert.equal(view.confidencePercent, 100);
});
