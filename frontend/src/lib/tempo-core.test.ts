import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseTempoOverride,
  resolveInitialTempo,
  scaledDuration,
  WORKING_SCALE,
} from "./tempo-core.ts";

test("parseTempoOverride accepts only known registers", () => {
  assert.equal(parseTempoOverride("showcase"), "showcase");
  assert.equal(parseTempoOverride("working"), "working");
  assert.equal(parseTempoOverride("WORKING"), null);
  assert.equal(parseTempoOverride(""), null);
  assert.equal(parseTempoOverride(null), null);
  assert.equal(parseTempoOverride(undefined), null);
});

test("resolveInitialTempo: an explicit override always wins", () => {
  assert.equal(resolveInitialTempo({ override: "showcase", hasSeen: true }), "showcase");
  assert.equal(resolveInitialTempo({ override: "working", hasSeen: false }), "working");
});

test("resolveInitialTempo: returning visitor defaults to working, first-time to showcase", () => {
  assert.equal(resolveInitialTempo({ hasSeen: true }), "working");
  assert.equal(resolveInitialTempo({ hasSeen: false }), "showcase");
  // an unknown override string is ignored, so seen-state decides
  assert.equal(resolveInitialTempo({ override: "nope", hasSeen: true }), "working");
});

test("scaledDuration: working scales by 0.1, showcase is 1:1", () => {
  assert.equal(scaledDuration(340, { tempo: "showcase", reducedMotion: false }), 340);
  assert.equal(scaledDuration(340, { tempo: "working", reducedMotion: false }), 340 * WORKING_SCALE);
  assert.equal(scaledDuration(1000, { tempo: "working", reducedMotion: false }), 100);
});

test("scaledDuration: reduced motion collapses everything to 0", () => {
  assert.equal(scaledDuration(340, { tempo: "showcase", reducedMotion: true }), 0);
  assert.equal(scaledDuration(340, { tempo: "working", reducedMotion: true }), 0);
});

test("scaledDuration: negative and zero inputs clamp to 0", () => {
  assert.equal(scaledDuration(0, { tempo: "showcase", reducedMotion: false }), 0);
  assert.equal(scaledDuration(-50, { tempo: "working", reducedMotion: false }), 0);
});
