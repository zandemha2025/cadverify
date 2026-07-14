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
