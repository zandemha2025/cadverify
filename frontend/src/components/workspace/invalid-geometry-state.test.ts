import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspace = await readFile(new URL("./PartWorkspace.tsx", import.meta.url), "utf8");
const hero = await readFile(new URL("./hero/PartHero.tsx", import.meta.url), "utf8");
const api = await readFile(new URL("../../lib/api.ts", import.meta.url), "utf8");

test("Analyze keeps request states independent and preserves the geometry diagnosis when both fail", () => {
  const dfm = workspace.slice(
    workspace.indexOf("const runDfm"),
    workspace.indexOf("const handleFile"),
  );
  const cost = workspace.slice(
    workspace.indexOf("const runCost"),
    workspace.indexOf("const runDfm"),
  );
  assert.doesNotMatch(dfm, /setCostError|setCostLoading/);
  assert.match(dfm, /setDfmError\(message\)/);
  assert.match(dfm, /setDfmLoading\(false\)/);
  assert.match(dfm, /attempt !== analysisAttemptRef\.current/);
  assert.doesNotMatch(cost, /setDfmError|setDfmLoading/);
  assert.match(workspace, /title=\{dfmError \? analysisFailureCopy\(dfmError\).title : "Cost estimate failed"\}/);
  assert.match(cost, /attempt !== analysisAttemptRef\.current/);
});

test("Analyze retains concurrent work for accepted geometry", () => {
  const submit = workspace.slice(
    workspace.indexOf("const runAnalyses"),
    workspace.indexOf("const handleFile"),
  );
  const handler = workspace.slice(
    workspace.indexOf("const handleFile"),
    workspace.indexOf("Seed from a caller-provided file"),
  );
  assert.match(handler, /runAnalyses\(selected, opts\)/);
  assert.match(submit, /const attempt = \+\+analysisAttemptRef\.current/);
  assert.match(submit, /void runCost\(theFile, theOpts, attempt\)/);
  assert.match(submit, /void runDfm\(theFile, theOpts\.units, attempt\)/);
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
