/** A big kept part's worker job, in the work bar's and the part page's words. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { isKeptJob, keptStageWord, keptToastLine, keptWorkLine, type KeptJobStatus } from "./kept-job-model.ts";

const JOB: KeptJobStatus = {
  check_id: "01JOB",
  status: "running",
  stage: "pricing",
  progress: null,
  source: "kept",
  action: "recheck",
  filename: "housing.step",
  part_filename: "housing.step",
  mesh_hash: "a".repeat(64),
  summary: null,
  part_url: null,
  error: null,
};

test("only a kept-part job is taken for one; an answer or an upload check is not", () => {
  assert.equal(isKeptJob(JOB), true);
  assert.equal(isKeptJob({ ...JOB, source: "upload", action: "check" }), false);
  assert.equal(isKeptJob({ quantities: [10], recheck: {} }), false);
  assert.equal(isKeptJob(null), false);
});

test("a re-price reads as re-pricing, then re-priced, linking to the part", () => {
  const running = keptWorkLine(JOB);
  assert.deepEqual(running, { state: "running", label: "Re-pricing housing.step", detail: "Pricing", href: `/app/part/${"a".repeat(64)}`, progress: null });
  const done = keptWorkLine({ ...JOB, status: "done", stage: "done", summary: "Re-priced", part_url: `/app/part/${"a".repeat(64)}` });
  assert.equal(done.label, "Re-priced housing.step");
  assert.equal(done.state, "done");
});

test("a repair links to the repaired copy once done, and says how it ended", () => {
  const done = keptWorkLine({ ...JOB, action: "repair", status: "done", summary: "Not repaired", part_url: `/app/part/${"a".repeat(64)}` });
  assert.equal(done.label, "Mesh repair of housing.step");
  assert.equal(done.detail, "Not repaired");
  const copy = keptWorkLine({ ...JOB, action: "repair", status: "done", summary: "Repaired", part_url: `/app/part/${"b".repeat(64)}` });
  assert.equal(copy.href, `/app/part/${"b".repeat(64)}`);
  assert.equal(keptWorkLine({ ...JOB, action: "repair", stage: "repairing" }).label, "Repairing a copy of housing.step");
});

test("a refusal shows its first sentence; stages read in plain words", () => {
  const stopped = keptWorkLine({ ...JOB, status: "failed", error: { code: "CHECK_TOO_LARGE", message: "This file needs about 6.1 GB of memory to check; the largest STEP file ScaleCAD checks today is about 3 MB. Nothing was charged." } });
  assert.equal(stopped.state, "stopped");
  assert.equal(stopped.label, "housing.step: not re-priced");
  assert.match(stopped.detail, /^This file needs about 6\.1 GB/);
  assert.doesNotMatch(stopped.detail, /Nothing was charged/);
  assert.equal(keptStageWord("queued"), "Waiting for a worker");
  assert.equal(keptStageWord("sizing"), "Sizing the file");
  assert.equal(keptStageWord("mystery"), "Working");
  assert.equal(keptToastLine("repairing"), "a large file, on ScaleCAD’s worker: repairing a copy");
});
