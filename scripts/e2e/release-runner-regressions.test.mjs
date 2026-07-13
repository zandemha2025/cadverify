import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [authRunner, manufacturingRunner, roleRunner, glassBox] = await Promise.all([
  readFile(new URL("./auth-role-lifecycle-golden-matrix.mjs", import.meta.url), "utf8"),
  readFile(new URL("./manufacturing-cad-adversarial.mjs", import.meta.url), "utf8"),
  readFile(new URL("./role-tenant-boundary-matrix.mjs", import.meta.url), "utf8"),
  readFile(new URL("../../frontend/src/components/workspace/GlassBoxView.tsx", import.meta.url), "utf8"),
]);

test("invitation runners follow the live accessible dialog and accept route", () => {
  assert.match(authRunner, /getByRole\("alertdialog"\)/);
  assert.doesNotMatch(authRunner, /const dialog = owner\.page\.getByRole\("dialog"\)/);
  assert.match(roleRunner, /acceptLink\.pathname, "\/orgs\/accept"/);
  assert.match(roleRunner, /acceptLink\.searchParams\.get\("token"\)/);
  assert.doesNotMatch(roleRunner, /\/invite\\\/accept/);
});

test("role evidence supplies the canonical generation timestamp", () => {
  assert.match(roleRunner, /generatedAt: new Date\(finishedAt\)\.toISOString\(\)/);
});

test("cost process controls expose and use one semantic accessible group", () => {
  assert.match(glassBox, /role="group" aria-label=\{label\}/);
  assert.match(manufacturingRunner, /getByRole\("tab", \{ name: "Glass Box", exact: true \}\)\.click\(\)/);
  assert.match(manufacturingRunner, /getByRole\("group", \{ name: "Process", exact: true \}\)/);
});

test("DFM evidence accepts structured citation fields without inventing prose", () => {
  assert.match(manufacturingRunner, /function hasStructuredCitation\(citation\)/);
  assert.match(manufacturingRunner, /\["text", "standard", "clause", "rule_id"\]/);
  assert.match(manufacturingRunner, /issues\.every\(isStructuredDfmIssue\)/);
  assert.doesNotMatch(manufacturingRunner, /!issue\.citation \|\| typeof issue\.citation\?\.text === "string"/);
});
