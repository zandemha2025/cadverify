import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspace = await readFile(new URL("./PartWorkspace.tsx", import.meta.url), "utf8");
const hero = await readFile(new URL("./hero/PartHero.tsx", import.meta.url), "utf8");
const api = await readFile(new URL("../../lib/api.ts", import.meta.url), "utf8");

test("Analyze preserves the canonical geometry refusal over a sibling transport failure", () => {
  const dfm = workspace.slice(
    workspace.indexOf("const runDfm"),
    workspace.indexOf("const handleFile"),
  );
  const cost = workspace.slice(
    workspace.indexOf("const runCost"),
    workspace.indexOf("const runDfm"),
  );
  assert.match(dfm, /dfmTerminalFailureRef\.current = message/);
  assert.match(dfm, /setCostError\(message\)/);
  assert.match(dfm, /setCostLoading\(false\)/);
  assert.match(dfm, /setDfmLoading\(false\)/);
  assert.match(dfm, /attempt !== analysisAttemptRef\.current/);
  assert.match(cost, /dfmTerminalFailureRef\.current \?\?/);
  assert.match(cost, /attempt !== analysisAttemptRef\.current/);
});

test("Analyze retains concurrent work for accepted geometry", () => {
  const handler = workspace.slice(
    workspace.indexOf("const handleFile"),
    workspace.indexOf("Seed from a caller-provided file"),
  );
  assert.match(handler, /const attempt = \+\+analysisAttemptRef\.current/);
  assert.match(handler, /void runCost\(selected, opts, attempt\)/);
  assert.match(handler, /void runDfm\(selected, opts\.units, attempt\)/);
});

test("Analyze maps terminal geometry failures to refusal and replacement guidance", () => {
  assert.match(hero, /analysisFailureCopy\(dfmError \|\| costError\)/);
  assert.match(hero, /label="Geometry refused"/);
  assert.match(hero, /analysisFailure\.explanation/);
  assert.match(hero, /analysisFailure\.action/);
});

test("cost transport exceptions do not blame the user's network", () => {
  const costStart = api.indexOf("async function _costEstimate");
  const costEnd = api.indexOf("export function costEstimate", costStart);
  const implementation = api.slice(costStart, costEnd);
  assert.doesNotMatch(implementation, /Check your network/);
  assert.match(implementation, /networkRecoveryMessage\("verification"\)/);
});
