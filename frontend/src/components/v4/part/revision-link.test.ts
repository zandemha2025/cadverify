import { test } from "node:test";
import assert from "node:assert/strict";

const { noteRevision, revisionForSession, revisionLine, setPendingRevision, takePendingRevision } = await import("./revision-link.ts");

const A = "a".repeat(64);
const B = "b".repeat(64);

test("the problem card's part reaches the check once, and the check's session keeps it", () => {
  setPendingRevision({ key: A, name: "enclosure-revA.step", problem: "draft" });
  const from = takePendingRevision();
  assert.deepEqual(from, { key: A, name: "enclosure-revA.step", problem: "draft" });
  assert.equal(takePendingRevision(), null);
  noteRevision(7, from!);
  assert.equal(revisionForSession(7)?.key, A);
  assert.equal(revisionForSession(8), null);
});

test("the new part says what it revises, the old one names its next revision, both with a Compare of A then B", () => {
  const onNew = revisionLine({ mesh_hash: B, revision_of: { mesh_hash: A, filename: "enclosure-revA.step", record_id: "01A", problem: "draft", at: null }, next: null }, "01B");
  assert.deepEqual(onNew, { lead: "Revision of", name: "enclosure-revA.step", partHref: `/app/part/${A}`, compareHref: "/app/parts/compare?a=01A&b=01B" });
  const onOld = revisionLine({ mesh_hash: A, revision_of: null, next: { mesh_hash: B, filename: "enclosure-revB.step", record_id: "01B", problem: null, at: null } }, "01A");
  assert.equal(onOld?.lead, "Next revision:");
  assert.equal(onOld?.compareHref, "/app/parts/compare?a=01A&b=01B");
  assert.equal(revisionLine({ mesh_hash: A, revision_of: null, next: null }, "01A"), null);
  assert.equal(revisionLine(null, null), null);
  assert.equal(revisionLine({ mesh_hash: B, revision_of: { mesh_hash: A, filename: "x.step", record_id: null, problem: null, at: null }, next: null }, "01B")?.compareHref, null);
});
