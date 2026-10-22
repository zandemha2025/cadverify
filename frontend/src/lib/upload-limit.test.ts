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
  STORED_CHECK_FROM_BYTES,
  needsStoredCheck,
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
  assert.equal(needsStoredCheck({ name: "bracket.step", size: 3 * 1024 * 1024 }), false);
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
