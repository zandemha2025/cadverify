import { test } from "node:test";
import assert from "node:assert/strict";
import { runInNewContext } from "node:vm";
import { RB2B_SCRIPT, rb2bAllowed } from "./rb2b.ts";

test("RB2B requires consent and a public production URL without private URL material", () => {
  assert.equal(rb2bAllowed("scalecad.ai", "/pricing", "", "", true), true);
  for (const [host, path, search, hash, consent] of [
    ["scalecad.ai", "/", "", "", false],
    ["localhost", "/", "", "", true],
    ["preview.scalecad.ai", "/", "", "", true],
    ["scalecad.ai", "/signup", "", "", true],
    ["scalecad.ai", "/verify", "", "", true],
    ["scalecad.ai", "/reset-password", "?token=private", "", true],
    ["scalecad.ai", "/", "?token=private", "", true],
    ["scalecad.ai", "/", "", "#private", true],
  ] as const) assert.equal(rb2bAllowed(host, path, search, hash, consent), false);
});

test("the supplied loader asynchronously inserts the exact account script once", () => {
  const scripts: Array<{ async?: boolean; src?: string }> = [];
  const first = { parentNode: { insertBefore: (script: object) => scripts.push(script) } };
  const context = { window: {}, document: { createElement: () => ({}), getElementsByTagName: () => [first] } };
  runInNewContext(RB2B_SCRIPT, context);
  runInNewContext(RB2B_SCRIPT, context);
  assert.equal(scripts.length, 1);
  assert.equal(scripts[0].async, true);
  assert.equal(scripts[0].src, "https://ddwl4m2hdecbv.cloudfront.net/b/E63P0HY01JOW/E63P0HY01JOW.js.gz");
});
