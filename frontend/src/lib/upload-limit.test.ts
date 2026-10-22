/**
 * One upload limit, the API's own. Run:
 * node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/lib/upload-limit.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { CAD_LIMIT, CAD_MAX_BYTES, CAD_MAX_MB, overCadLimit, overCadLimitText } from "./upload-limit.ts";

const backend = new URL("../../../backend/", import.meta.url);

test("the limit is the API's default and the Fly config's", () => {
  const routes = readFileSync(new URL("src/api/routes.py", backend), "utf8");
  const fly = readFileSync(new URL("fly.toml", backend), "utf8");
  assert.match(routes, new RegExp(`os\\.getenv\\("MAX_UPLOAD_MB", "${CAD_MAX_MB}"\\)`));
  assert.match(fly, new RegExp(`MAX_UPLOAD_MB = "${CAD_MAX_MB}"`));
  assert.equal(CAD_MAX_BYTES, CAD_MAX_MB * 1024 * 1024);
  assert.equal(CAD_LIMIT, "up to 100 MB");
});

test("a file is over only past the byte the server refuses", () => {
  assert.equal(overCadLimit(CAD_MAX_BYTES), false);
  assert.equal(overCadLimit(CAD_MAX_BYTES + 1), true);
  assert.equal(overCadLimitText(150 * 1048576), "150 MB, over the 100 MB limit for one file");
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
  const stale = files.filter((f) => /up to 200 MB|200 \* 1024 \* 1024/.test(readFileSync(f, "utf8")));
  assert.deepEqual(stale, []);
});
