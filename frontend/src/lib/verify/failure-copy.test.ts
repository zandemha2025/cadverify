import { test } from "node:test";
import assert from "node:assert/strict";

import { analysisFailureCopy } from "./failure-copy.ts";

test("capacity failures never blame customer geometry", () => {
  const copy = analysisFailureCopy(
    "this organization has reached its concurrent-analysis limit of 3",
  );
  assert.equal(copy.kind, "capacity");
  assert.match(copy.title, /temporarily busy/i);
  assert.match(copy.action, /does not need to be re-exported/i);
  assert.doesNotMatch(copy.title + copy.explanation + copy.action, /tessellat/i);
});

test("unsupported files and actual mesher failures get distinct recovery copy", () => {
  assert.equal(analysisFailureCopy("Unsupported file type; use .stl").kind, "unsupported");
  assert.equal(
    analysisFailureCopy("geometry contains an unsupported surface the mesher cannot triangulate").kind,
    "geometry",
  );
});

test("unknown failures do not invent a geometry diagnosis", () => {
  const copy = analysisFailureCopy("upstream request failed (503)");
  assert.equal(copy.kind, "unknown");
  assert.match(copy.title, /could not finish/i);
  assert.doesNotMatch(copy.title + copy.explanation, /geometry|tessellat/i);
});
