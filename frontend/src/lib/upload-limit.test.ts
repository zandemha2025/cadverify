/**
 * One set of upload limits, the API's own. Run:
 * node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/lib/upload-limit.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  CAD_LIMIT,
  CAD_MAX_BYTES,
  CAD_MAX_MB,
  FORM_MAX_BYTES,
  FORM_MAX_MB,
  MEMORY_HEADROOM,
  STEP_MEMORY_POINTS,
  STORED_CHECK_FROM_BYTES,
  WEB_CHECK_MEMORY_BUDGET_BYTES,
  estimateStepMemoryBytes,
  needsStoredCheck,
  overWebCheckMemory,
  overCadLimit,
  overCadLimitText,
  overFormLimit,
  sizeText,
} from "./upload-limit.ts";

const backend = new URL("../../../backend/", import.meta.url);

test("one file: the API's single-part upload cap, on every plan", () => {
  const service = readFileSync(new URL("src/services/direct_upload_service.py", backend), "utf8");
  assert.match(service, /DEFAULT_PART_MAX_BYTES = 2 \* 1024\*\*3/);
  assert.equal(CAD_MAX_BYTES, 2 * 1024 ** 3);
  assert.equal(CAD_MAX_MB * 1024 * 1024, CAD_MAX_BYTES);
  assert.equal(CAD_LIMIT, "up to 2 GB");
});

test("a web request's own limit is the API default and the Fly config's", () => {
  const routes = readFileSync(new URL("src/api/routes.py", backend), "utf8");
  const fly = readFileSync(new URL("fly.toml", backend), "utf8");
  assert.match(routes, new RegExp(`os\\.getenv\\("MAX_UPLOAD_MB", "${FORM_MAX_MB}"\\)`));
  assert.match(fly, new RegExp(`MAX_UPLOAD_MB = "${FORM_MAX_MB}"`));
  assert.equal(FORM_MAX_BYTES, FORM_MAX_MB * 1024 * 1024);
  assert.ok(STORED_CHECK_FROM_BYTES < FORM_MAX_BYTES, "a big file goes to the worker before the web limit");
});

test("a file is over only past the byte the server refuses", () => {
  assert.equal(overCadLimit(CAD_MAX_BYTES), false);
  assert.equal(overCadLimit(CAD_MAX_BYTES + 1), true);
  assert.equal(overCadLimitText(2.4 * 1024 ** 3), "2.4 GB, over the 2 GB limit for one file");
  assert.equal(overFormLimit(FORM_MAX_BYTES + 1), true);
  assert.equal(sizeText(650 * 1024 * 1024), "650 MB");
  assert.equal(sizeText(400 * 1024), "0.4 MB");
});

test("big and compressed parts are checked from storage on the worker", () => {
  assert.equal(needsStoredCheck({ name: "bracket.step", size: 2 * 1024 * 1024 }), false);
  assert.equal(needsStoredCheck({ name: "bracket.stl", size: 5 * 1024 * 1024 }), false);
  assert.equal(needsStoredCheck({ name: "bracket.step", size: STORED_CHECK_FROM_BYTES }), true);
  assert.equal(needsStoredCheck({ name: "bracket.step.gz", size: 1024 }), true);
  assert.equal(needsStoredCheck({ name: "bracket.zip", size: 1024 }), true);
});

test("no screen states another upload size for a CAD file", () => {
  const root = new URL("../", import.meta.url).pathname;
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.tsx?$/.test(name) && !/\.test\.ts$/.test(name)) files.push(p);
    }
  };
  walk(join(root, "components/v4"));
  walk(join(root, "lib"));
  const stale = files.filter((f) => /up to (100|200) MB|200 \* 1024 \* 1024|Up to \$\{CAD_MAX_MB\} MB/.test(readFileSync(f, "utf8")));
  assert.deepEqual(stale, []);
});

test("a STEP or IGES file over the web process's memory goes to the worker (the backend's model)", () => {
  const service = readFileSync(new URL("src/services/stored_check_service.py", backend), "utf8");
  const pts = service.match(/STEP_MEMORY_POINTS[^=]*=\s*\(([\s\S]*?)\n\)/);
  assert.ok(pts, "STEP_MEMORY_POINTS in stored_check_service.py");
  const backendPoints = [...pts![1].matchAll(/\(([\d.]+),\s*([\d.]+)\)/g)].map((m) => [Number(m[1]), Number(m[2])]);
  assert.deepEqual(backendPoints, STEP_MEMORY_POINTS.map(([x, y]) => [x, y]));
  assert.match(service, new RegExp(`MEMORY_HEADROOM = ${MEMORY_HEADROOM.toFixed(2)}`));
  assert.match(service, /IGES_MEMORY_POINTS = STEP_MEMORY_POINTS/);
  assert.match(service, /os\.getenv\("CHECK_MEMORY_FRACTION", "0\.6"\)/);
  const fly = readFileSync(new URL("fly.toml", backend), "utf8");
  assert.match(fly, /\[\[vm\]\]\s*\n\s*processes = \["web"\]\s*\n\s*memory = "4gb"/);
  assert.equal(WEB_CHECK_MEMORY_BUDGET_BYTES, Math.floor(0.6 * 4096 * 1024 * 1024));

  // The same numbers the backend's _interp gives (MB of file -> MB, times 1.1).
  const MB = 1024 * 1024;
  // A small STEP or IGES can tessellate to the mesher's 250,000-face budget: 820 MB at least.
  assert.equal(estimateStepMemoryBytes(0), Math.floor(820 * 1.1 * MB));
  assert.equal(estimateStepMemoryBytes(0.09 * MB), Math.floor(820 * 1.1 * MB));
  assert.equal(estimateStepMemoryBytes(1.52 * MB), Math.floor(820 * 1.1 * MB));
  const three = 820 + ((1531 - 820) * (3 - 1.52)) / (4.92 - 1.52);
  assert.equal(estimateStepMemoryBytes(3 * MB), Math.floor(three * 1.1 * MB));
  const five = 1531 + ((2396 - 1531) * (5 - 4.92)) / (10.07 - 4.92);
  assert.equal(estimateStepMemoryBytes(5 * MB), Math.floor(five * 1.1 * MB));
  const twenty = 2396 + ((2396 - 1531) * (20 - 10.07)) / (10.07 - 4.92);
  assert.equal(estimateStepMemoryBytes(20 * MB), Math.floor(twenty * 1.1 * MB));

  // On a 4 GB web machine: about 9 MB of STEP or IGES is the most a web check holds.
  assert.equal(overWebCheckMemory({ name: "asm.step", size: 5 * MB }), false);
  assert.equal(overWebCheckMemory({ name: "asm.step", size: 8.9 * MB }), false);
  assert.equal(overWebCheckMemory({ name: "asm.STP", size: 9.3 * MB }), true);
  assert.equal(overWebCheckMemory({ name: "plate.igs", size: 12 * MB }), true);
  assert.equal(overWebCheckMemory({ name: "plate.iges", size: 1 * MB }), false);
  // STL is sized by triangles on the server; the 20 MB rule and the server's 413 cover it.
  assert.equal(overWebCheckMemory({ name: "mesh.stl", size: 15 * MB }), false);
  assert.equal(needsStoredCheck({ name: "asm.step", size: 12 * MB }), true);
});
