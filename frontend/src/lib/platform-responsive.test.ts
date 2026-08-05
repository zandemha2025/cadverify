import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("platform layout uses responsive classes instead of fixed inline columns", async () => {
  const page = await readFile(
    new URL("../app/(site)/platform/page.tsx", import.meta.url),
    "utf8",
  );

  for (const className of [
    "st-platform-moat-grid",
    "st-platform-pair-grid",
    "st-platform-split",
    "st-platform-split-wide",
    "st-platform-positioning-grid",
    "st-platform-portfolio-row",
  ]) {
    assert.match(page, new RegExp(className));
  }
  assert.doesNotMatch(page, /gridTemplateColumns/);
});

test("platform grids collapse and cards retain readable mobile spacing", async () => {
  const css = await readFile(
    new URL("../app/(site)/site-theater.css", import.meta.url),
    "utf8",
  );

  assert.match(
    css,
    /@media \(max-width: 820px\)[\s\S]*?\.st-platform-moat-grid,[\s\S]*?\.st-platform-split-wide \{\s*grid-template-columns: minmax\(0, 1fr\);/,
  );
  assert.match(css, /\.st-platform-section \{\s*padding: 0 18px 46px;/);
  assert.match(
    css,
    /\.st-platform-panel-moat,[\s\S]*?\.st-platform-position-card \{\s*padding: 22px;/,
  );
  assert.match(css, /\.st-platform-portfolio-head \{\s*display: none;/);
  assert.match(
    css,
    /\.st-platform-portfolio-row \{\s*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/,
  );
});
