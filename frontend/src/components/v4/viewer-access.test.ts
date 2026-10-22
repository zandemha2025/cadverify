/**
 * Viewer access: the plain line a read-only org viewer gets instead of a raw 403.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/viewer-access.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { checkBlockedLine, viewerCheckLine } from "./viewer-access.ts";

const ACME = "You're a viewer in Acme Tooling: you can open its parts and records. Ask an admin for member access to check new parts.";

test("a viewer's line names the org", () => {
  assert.equal(viewerCheckLine("Acme Tooling"), ACME);
  assert.equal(
    viewerCheckLine("  "),
    "You're a viewer in this organization: you can open its parts and records. Ask an admin for member access to check new parts.",
  );
});

test("only a viewer is blocked; members, admins and an unknown role may check", () => {
  assert.equal(checkBlockedLine({ name: "Acme Tooling", org_role: "viewer" }), ACME);
  assert.equal(checkBlockedLine({ name: "Acme Tooling", org_role: "member" }), null);
  assert.equal(checkBlockedLine({ name: "Acme Tooling", org_role: "admin" }), null);
  assert.equal(checkBlockedLine(null), null);
});
