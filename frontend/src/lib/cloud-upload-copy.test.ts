import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const files = [
  new URL("../components/landing/PartDoor.tsx", import.meta.url),
  new URL("../components/workspace/PartWorkspace.tsx", import.meta.url),
];

test("cloud upload surfaces do not claim zero egress", () => {
  for (const file of files) {
    const source = readFileSync(file, "utf8");
    assert.match(source, /Uploaded to ProofShape for in-process parsing/);
    assert.match(source, /source CAD is discarded after analysis/);
    assert.doesNotMatch(source, /zero egress|zero-egress/i);
  }
});
