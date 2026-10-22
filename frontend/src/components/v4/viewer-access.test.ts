/**
 * Viewer access: the plain line a read-only org viewer gets instead of a raw 403.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/viewer-access.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { checkBlockedLine, viewerCheckLine, viewerWriteLine, writeBlockedLine } from "./viewer-access.ts";
import { readFileSync } from "node:fs";

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

test("a viewer's write controls carry one line, never a pitch to try", () => {
  assert.equal(viewerWriteLine(), "Viewers can't change parts. Ask an admin for Member access.");
  assert.equal(writeBlockedLine({ name: "Acme", org_role: "viewer" }, "change the shop's machines"), "Viewers can't change the shop's machines. Ask an admin for Member access.");
  assert.equal(writeBlockedLine({ name: "Acme", org_role: "member" }), null);
  assert.equal(writeBlockedLine(null), null);
});

test("viewer guards sit on the write controls outside the part page", () => {
  const read = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");
  assert.match(read("./datacontrol/delete-part.tsx"), /const readOnly = useReadOnly\(\);\s+if \(readOnly\)/);
  assert.match(read("./home/library.tsx"), /disabled=\{busy \|\| !!readOnly\}/);
  assert.match(read("./shop/machines-screen.tsx"), /\{readOnly \? null : <AddTile/);
  assert.match(read("./onboard/teammate.tsx"), /checkBlocked \? \(/);
  assert.match(read("./onboard/first-run-overlay.tsx"), /const card = !checkBlocked &&/);
});
