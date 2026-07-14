import assert from "node:assert/strict";
import test from "node:test";

import { reconstructionAttempt } from "./reconstruction-attempt.ts";

test("an ambiguous retry of the same files reuses its submission ID", () => {
  const files = [new File(["one"], "one.png", { type: "image/png" })];
  let generated = 0;
  const makeId = () => `ID-${++generated}`;

  const first = reconstructionAttempt(null, files, makeId);
  const retry = reconstructionAttempt(first, files, makeId);

  assert.equal(first.submissionId, "ID-1");
  assert.equal(retry, first);
  assert.equal(generated, 1);
});

test("changing a file starts a new reconstruction submission", () => {
  const firstFile = new File(["one"], "one.png", { type: "image/png" });
  const replacement = new File(["two"], "two.png", { type: "image/png" });
  let generated = 0;
  const makeId = () => `ID-${++generated}`;

  const first = reconstructionAttempt(null, [firstFile], makeId);
  const changed = reconstructionAttempt(first, [replacement], makeId);

  assert.equal(changed.submissionId, "ID-2");
});
