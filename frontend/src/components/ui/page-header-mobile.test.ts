import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const header = await readFile(new URL("./page-header.tsx", import.meta.url), "utf8");
const repair = await readFile(new URL("../RepairButton.tsx", import.meta.url), "utf8");

test("record actions wrap within the mobile page header", () => {
  assert.match(header, /flex min-w-0 w-full flex-wrap items-center gap-2 sm:w-auto sm:shrink-0/);
});

test("retained-file-free repair says that it opens a file picker", () => {
  assert.match(repair, /Choose file to repair/);
  assert.match(repair, /opens a file picker/);
});
