import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(
  new URL("../app/(app)/designs/page.tsx", import.meta.url),
  "utf8",
);

test("design studio exposes a real two-revision comparison with truth limits", () => {
  assert.match(page, /Version diff/);
  assert.match(page, /compareDesignRevisions\(selected\.id, diffFrom, diffTo\)/);
  assert.match(page, /revisionDiff\.before, revisionDiff\.after/);
  assert.match(page, /designRevisionPreviewUrl\(selected\.id, side\)/);
  assert.doesNotMatch(page, /<CadViewer src=\{side\.links\.preview\}/);
  assert.match(page, /Generated geometry changes/);
  assert.match(page, /revisionDiff\.limits/);
});
