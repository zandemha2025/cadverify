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
});

test("the guided example explains the result and offers a next action", () => {
  assert.match(appSource, /Example complete: this is a manufacturing answer/);
  assert.match(appSource, /CAD health, manufacturing method, estimated cost, and what is still uncertain/);
  assert.match(appSource, /Check my CAD next/);
  assert.match(resultSource, /Here is the manufacturing answer\./);
  assert.match(resultSource, /Did ProofShape understand the CAD\?/);
  assert.match(resultSource, /How would it be made\?/);
  assert.match(resultSource, /What should it cost\?/);
  assert.match(resultSource, /What is still uncertain\?/);
  assert.match(resultSource, /Your shop-specific fit and price/);
  assert.match(resultSource, /Show full technical result/);
  assert.match(appSource, /guided=\{guidedSampleState !== "idle"\}/);
  assert.match(pipelineSource, /Turning this CAD file into four useful answers\./);
  assert.match(pipelineSource, /Your own CAD files use the same engine\./);
});

test("the empty home leads with plain-language value and executable starts", () => {
  assert.match(homeSource, /What would you like to do\?/);
  assert.match(homeSource, /Choose one\. Nothing else needs to be set up first\./);
  assert.match(homeSource, /onClick=\{onSample\}/);
  assert.match(homeSource, /onClick=\{onPickFile\}/);
  assert.match(homeSource, /href="\/designs"/);
});

test("help can be reopened after dismissal", () => {
  assert.match(appSource, />\s*Start here\s*</);
  assert.match(appSource, /onClick=\{\(\) => setWelcomeOpen\(true\)\}/);
});
