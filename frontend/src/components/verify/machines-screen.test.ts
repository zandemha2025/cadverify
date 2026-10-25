import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("./machines-screen.tsx", import.meta.url), "utf8");

// Regression: catalog prefill kept only x/y/z, and an edit deleted every
// envelope key the visible layout did not show. The merge itself is unit-tested
// in lib/verify/machine-form.test.ts; this pins the screen to it.
test("machine form submits the template or stored capability bag through the shared merge", () => {
  const apply = source.indexOf("const applyTemplate");
  assert.ok(apply >= 0);
  assert.match(source.slice(apply, source.indexOf("const submit", apply)), /setBaseCap\(cap\)/);
  assert.match(source, /mergeMachineCapabilities\(baseCap, parsed\.value\.capabilities, isTurning\)/);
  assert.doesNotMatch(source, /delete cap\.x/);
});

// Regression: "Delete machine" removed the machine on a single click.
test("deleting a machine goes through a destructive confirmation", () => {
  assert.match(source, /onDelete=\{\(\) => setPendingDelete\(detail\)\}/);
  assert.match(source, /<AlertDialog[\s\S]*confirmLabel="Delete machine"[\s\S]*onConfirm=/);
  assert.doesNotMatch(source, /onDelete=\{\(\) => onDelete\(detail\)\}/);
});
