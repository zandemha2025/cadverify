import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const hero = await readFile(new URL("./PartHero.tsx", import.meta.url), "utf8");
const workspace = await readFile(new URL("../PartWorkspace.tsx", import.meta.url), "utf8");
const viewer = await readFile(new URL("../../ui/cad-viewer.tsx", import.meta.url), "utf8");

test("analyze workspace and viewer cannot establish a wider mobile scroll container", () => {
  assert.match(hero, /min-w-0 max-w-full flex-1 overflow-x-hidden overflow-y-auto/);
  assert.match(workspace, /min-w-0 max-w-full flex-1 overflow-x-hidden overflow-y-auto/);
  assert.match(viewer, /relative h-full min-w-0 w-full max-w-full overflow-hidden/);
});

test("legacy analyze viewer grid child can shrink below its canvas intrinsic width", () => {
  assert.match(workspace, /min-w-0 space-y-3 lg:sticky lg:top-0 lg:col-span-2/);
});
