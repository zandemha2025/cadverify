import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./PartWorkspace.tsx", import.meta.url), "utf8");

test("/analyze validates STL integrity before setting viewer file or dispatching requests", () => {
  const gate = source.indexOf("await clientStlIntegrityError(selected)");
  const submit = source.slice(source.indexOf("const runAnalyses"), source.indexOf("const handleFile"));
  const costDispatch = source.indexOf("runAnalyses(selected, opts)", gate);
  assert.ok(gate >= 0);
  assert.ok(costDispatch > gate);
  assert.match(submit, /setFile\(theFile\)/);
  assert.ok(submit.indexOf("setFile(theFile)") < submit.indexOf("void runCost"));
  assert.match(source, /setFile\(null\);[\s\S]*setCostError\(integrityError\);[\s\S]*setDfmError\(integrityError\);[\s\S]*return;/);
});
