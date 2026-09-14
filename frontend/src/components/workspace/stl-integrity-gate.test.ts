import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./PartWorkspace.tsx", import.meta.url), "utf8");

test("/analyze validates STL integrity before setting viewer file or dispatching requests", () => {
  const gate = source.indexOf("await clientStlIntegrityError(selected)");
  const viewerAssignment = source.indexOf("setFile(selected)", gate);
  const costDispatch = source.indexOf("void runCost(selected, opts, attempt)", gate);
  assert.ok(gate >= 0);
  assert.ok(viewerAssignment > gate);
  assert.ok(costDispatch > viewerAssignment);
  assert.match(source, /setFile\(null\);[\s\S]*setCostError\(integrityError\);[\s\S]*setDfmError\(integrityError\);[\s\S]*return;/);
});
