import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const guideSource = await readFile(new URL("./welcome-guide.tsx", import.meta.url), "utf8");
const appSource = await readFile(new URL("./verify-app.tsx", import.meta.url), "utf8");
const homeSource = await readFile(new URL("./home-screen.tsx", import.meta.url), "utf8");
const resultSource = await readFile(
  new URL("./guided-result-summary.tsx", import.meta.url),
  "utf8",
);
const pipelineSource = await readFile(
  new URL("./pipeline-overlay.tsx", import.meta.url),
  "utf8",
);
const signupSource = await readFile(
  new URL("../../app/(auth)/signup/signup-form.tsx", import.meta.url),
  "utf8",
);
const onboardingSource = await readFile(
  new URL("../../app/(app)/onboarding/page.tsx", import.meta.url),
  "utf8",
);

test("new accounts enter a forced first-run guide", () => {
  assert.match(signupSource, /window\.location\.href = "\/onboarding"/);
  assert.match(onboardingSource, /redirect\("\/verify\?welcome=1"\)/);
  assert.match(appSource, /params\.get\("welcome"\) === "1"/);
});

test("the first-run guide starts from user goals, not internal platform nouns", () => {
  assert.match(guideSource, /What do you want ProofShape to help you do\?/);
  assert.match(guideSource, /Show me a real example/);
  assert.match(guideSource, /Check my CAD file/);
  assert.match(guideSource, /Create a simple part/);
  assert.match(guideSource, /Set up my shop/);
  assert.match(guideSource, /FASTEST TO YOUR ANSWER/);
  assert.match(guideSource, /Geometry and DFM\s+arrive first/);
});

test("the guided example explains the result and offers a next action", () => {
  assert.match(appSource, /Example complete: this is a manufacturing answer/);
  assert.match(appSource, /geometry and DFM first; route, first issue, resource cost, and shop fit follow/);
  assert.match(appSource, /Check my CAD next/);
  assert.match(resultSource, /The manufacturing answer, in decision order\./);
  assert.match(resultSource, /GEOMETRY \/ DFM · PRIMARY RESULT/);
  assert.match(resultSource, /RECOMMENDED ROUTE/);
  assert.match(resultSource, /FIRST ISSUE/);
  assert.match(resultSource, /MEASURED EVIDENCE/);
  assert.match(resultSource, /RESOURCE COST ·/);
  assert.match(resultSource, /SHOP FIT \/ UNCERTAINTY · NEUTRAL/);
  assert.match(resultSource, /validationGeometry = result\?\.validation\?\.geometry/);
  assert.match(resultSource, /Routing and DFM are ready\. Resource cost needs another try\./);
  assert.match(resultSource, /Show full technical result/);
  assert.match(appSource, /guided=\{guidedSampleState !== "idle"\}/);
  assert.match(pipelineSource, /The first answer appears as soon as DFM lands\./);
  assert.match(pipelineSource, /Your own CAD files use the same engine\./);
});

test("the empty home leads with plain-language value and executable starts", () => {
  assert.match(homeSource, /Drop a part\. See the best route and what blocks it\./);
  assert.match(homeSource, /Choose one\. Nothing else needs to be set up first\./);
  assert.match(homeSource, /onClick=\{onSample\}/);
  assert.match(homeSource, /onClick=\{onPickFile\}/);
  assert.match(homeSource, /onDrop=\{\(event\) =>/);
  assert.match(homeSource, /href="\/designs"/);
});

test("help can be reopened after dismissal", () => {
  assert.match(appSource, />\s*Start here\s*</);
  assert.match(appSource, /onClick=\{\(\) => setWelcomeOpen\(true\)\}/);
});
