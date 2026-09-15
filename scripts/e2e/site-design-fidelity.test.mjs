import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./site-design-fidelity.mjs", import.meta.url), "utf8");
const homeHtml = await readFile(new URL("../../frontend/src/app/(site)/home-v2-html.ts", import.meta.url), "utf8");

function homeSpec() {
  const start = source.indexOf('route: "/"');
  const end = source.indexOf('\n  {\n    route: "/method"', start);
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}

test("route / is re-baselined to the accepted HOME v2 signals", () => {
  const home = homeSpec();
  for (const signal of [
    "Stop losing weeks to failed prints",
    "See it work",
    "THE VERDICT",
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./site-design-fidelity.mjs", import.meta.url), "utf8");
const homeHtml = await readFile(new URL("../../frontend/src/app/(site)/home-v2-html.ts", import.meta.url), "utf8");

function homeSpec() {
  const start = source.indexOf('route: "/"');
  const end = source.indexOf('\n  {\n    route: "/method"', start);
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}

test("route / is re-baselined to the accepted HOME v2 signals", () => {
  const home = homeSpec();
  for (const signal of [
    "Stop losing weeks to failed prints",
    "See it work",
    "THE VERDICT",
    "THE FIX",
    "THE PRICE",
    "THE RECORD",
    "Verdicts before prints",
  ]) assert.ok(home.includes(signal), `missing HOME v2 signal: ${signal}`);
  assert.match(home, /register: "home-v2"/);
  assert.match(home, /navSignals: \[\/ProofShape\/i, \/Developers\/i, \/Check your first part free\/i\]/);
  assert.doesNotMatch(home, /Direction - Cinematic|Can it be made/);
});

test("HOME v2 retains structural and image proof without a receipt line", () => {
  const start = source.indexOf("async assertHomeV2()");
  const end = source.indexOf("async assertDesignRegister", start);
  const helper = source.slice(start, end);
  for (const token of [
    'a.btn.ghost[href="#chapters"]',
    "STL \\u00B7 STEP \\u00B7 IGES IN \\u00B7 VERDICT WITH EVIDENCE OUT",
    "chapterImages[index].complete",
    "chapterImages[index].naturalWidth > 0",
    "outcomeBackground",
    'img[src*="ps-captures/"]',
    "g01-verdict-red.png",
    "g04-verdict-green.png",
    "g05-cost.png",
    "g06-ledger.png",
    "section.closer svg.ridge",
    "footer .ftag",
    "!home.visibleReceipt",
  ]) assert.ok(helper.includes(token), `HOME v2 structural proof missing: ${token}`);
});

test("every non-home route keeps the dark-theater assertion", () => {
  assert.match(source, /spec\.register === "home-v2" \? this\.assertHomeV2\(\) : this\.assertDarkTheater\(\)/);
  assert.equal((source.match(/register: "home-v2"/g) || []).length, 1);
  assert.match(source, /missing \.site-theater dark-register wrapper/);
});


test("HOME v2 does not inherit old multi-route navigation copy", () => {
  assert.match(source, /spec\.navSignals \?\? desktopNavSignals/);
  assert.equal((source.match(/navSignals:/g) || []).length, 1);
});


test("HOME v2 does not claim unsupported assembly ingestion or cloud zero-egress", () => {
  assert.doesNotMatch(homeHtml, /native assembly|assembly (?:file|data|ingestion)/i);
  assert.doesNotMatch(homeHtml, /zero network egress|cloud[^\n;]*zero[^\n;]*egress/i);
  assert.match(source, /register: "home-v2"/);
});
