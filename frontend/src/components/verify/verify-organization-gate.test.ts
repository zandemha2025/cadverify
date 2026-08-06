import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("./verify-app.tsx", import.meta.url), "utf8");
const pageSource = await readFile(
  new URL("../../app/(verify)/verify/page.tsx", import.meta.url),
  "utf8",
);

test("Verify resolves the authenticated organization boundary on the server", () => {
  assert.match(pageSource, /await getSessionOrganizationAccess\(\)/);
  assert.match(pageSource, /<VerifyApp organizationAccess=\{organizationAccess\}/);
});

test("Verify does not mount org-scoped readers without an active organization", () => {
  assert.match(appSource, /const hasActiveOrganization = activeOrganization !== null/);
  assert.match(appSource, /if \(!hasActiveOrganization\) \{\s*return <OrganizationAccessGate/);

  const rateEffect = appSource.indexOf("// The rail footer's bound-rate signal.");
  const rateGuard = appSource.indexOf("if (!hasActiveOrganization)", rateEffect);
  const machineRead = appSource.indexOf("listMachines().then", rateGuard);
  assert.ok(rateEffect >= 0 && rateGuard > rateEffect && machineRead > rateGuard);

  const designEffect = appSource.indexOf("// Design Studio handoff:");
  const designGuard = appSource.indexOf("if (!hasActiveOrganization) return", designEffect);
  const designRead = appSource.indexOf("importDesignStep", designGuard);
  assert.ok(designEffect >= 0 && designGuard > designEffect && designRead > designGuard);
});

test("the no-organization state gives a concrete invitation and settings path", () => {
  assert.match(appSource, /data-testid="verify-organization-gate"/);
  assert.match(appSource, /You haven’t joined an organization yet\./);
  assert.match(appSource, /Open the invitation link sent by your organization administrator/);
  assert.match(appSource, /href="\/settings\/organization"/);
  assert.match(appSource, /No organization data has been loaded or treated as empty/);
});

test("Design Studio import copy follows the real verification lifecycle", () => {
  const running = appSource.indexOf('state: "running", message: `Imported ${imported.name}. Verification is running.`');
  const verification = appSource.indexOf("await runVerify(imported)", running);
  const finished = appSource.indexOf('state: "ready", message: `Imported ${imported.name}. Verification finished.`', verification);
  assert.ok(running >= 0 && verification > running && finished > verification);
  assert.match(appSource, /designImport\.state === "loading" \|\| designImport\.state === "running"/);
});

test("phone Verify stage separates the title from the context evidence card", () => {
  assert.match(appSource, /\.cv-verify-stage-title \{[\s\S]*?top: 18px !important/);
  assert.match(appSource, /\.cv-verify-stage-title \{[\s\S]*?max-height: 108px/);
  assert.match(appSource, /\.cv-verify-stage-context-card \{[\s\S]*?top: 140px !important/);
});
