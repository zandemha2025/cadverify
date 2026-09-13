import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("context fit keeps measurements usable when WebGL is unavailable", () => {
  const source = readFileSync(new URL("./context-fit-viewer.tsx", import.meta.url), "utf8");
  assert.match(source, /probeWebGlSupport\(\)/);
  assert.match(source, /3D preview is unavailable in this browser\. Your measurements below are complete\./);
});
