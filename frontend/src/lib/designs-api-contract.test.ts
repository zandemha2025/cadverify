import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./designs-api.ts", import.meta.url), "utf8");

test("revision compare calls the scoped immutable-revision endpoint", () => {
  assert.match(
    source,
    /designs\/\$\{encodeURIComponent\(id\)\}\/revisions\/compare\?\$\{query\}/,
  );
  assert.match(source, /from: String\(fromRevision\)/);
  assert.match(source, /to: String\(toRevision\)/);
});
