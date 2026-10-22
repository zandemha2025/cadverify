import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { headEnd } from "./page-head.ts";

const here = new URL(".", import.meta.url);
const read = (p: string) => readFileSync(new URL(p, here), "utf8");

test("content starts under the page head as it is drawn, never above the design's offset (G1 follow-up)", () => {
  // A head as drawn (top 20, 104 tall) and a shorter one keep the 132 px the boards place content at.
  assert.equal(headEnd(20, 104), 132);
  assert.equal(headEnd(20, 90), 132);
  // A head that wraps (a long run name, its facts and tools on two rows) pushes the content below it.
  assert.equal(headEnd(20, 160), 188);
  assert.equal(headEnd(20, 160, 178), 188);
  assert.equal(headEnd(20, 100, 178), 178);
});

test("every page with a page head and Content gets the measured offset from one place", () => {
  const ui = read("ui.tsx");
  const css = read("v4.css");
  // Content measures the page head before it (World, the Account frame and every area wrapper alike).
  assert.match(ui, /export function Content\([\s\S]*?useUnderHead\(/);
  assert.match(ui, /data-under-head/);
  // Desktop only: phones flow the head and the content, so no offset applies there.
  assert.match(css, /@media \(min-width:901px\)\{\.ob \.content\[data-under-head\]\{top:max\(var\(--content-top,132px\),var\(--head-end,0px\)\)\}\}/);
  // A long unbroken name (a ZIP called Ridgeline_spares_and_customer_supplied_parts_2026Q3_rev_C…) wraps
  // inside the head instead of running off a phone's screen.
  assert.match(css, /\.ob \.ptitle\{[^}]*overflow-wrap:anywhere/);
  // Your shop's own copy (8b17369) is folded into the shared one.
  assert.doesNotMatch(read("shop/common.tsx"), /--shp-head/);
  assert.doesNotMatch(read("shop/shop.css"), /--shp-head/);
});
