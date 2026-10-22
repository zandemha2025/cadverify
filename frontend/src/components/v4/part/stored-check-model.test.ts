/**
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/part/stored-check-model.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { failedStep, overallFraction, storedSteps, type StoredStateIn } from "./stored-check-model.ts";

const GB = 1024 ** 3;
const base: StoredStateIn = {
  name: "frame.step", size: 1.2 * GB, phase: "uploading", sent: 0.4 * GB, resumed: 0, frac: null, checkId: null,
  partName: null, partBytes: null, memory: null, geometryInvalid: null, failure: null,
};

const states = (c: StoredStateIn) => storedSteps(c).map((s) => `${s.key}:${s.state}`);

test("uploading: the upload is the step now, with bytes sent of the file", () => {
  const steps = storedSteps(base);
  assert.deepEqual(steps.map((s) => s.key), ["upload", "verify", "size", "measure", "price"]);
  assert.equal(steps[0].state, "now");
  assert.match(steps[0].d, /^410 MB of 1\.2 GB · resumes if the connection drops$/);
  assert.match(storedSteps({ ...base, resumed: 3 })[0].d, /3 parts were already there/);
});

test("a compressed part gets an unpack step and says what was inside", () => {
  const c = { ...base, name: "frame.step.gz", phase: "sizing" as const, checkId: "C", partName: "frame.step", partBytes: 3 * GB / 2 };
  assert.deepEqual(states(c), ["upload:done", "verify:done", "unpack:done", "size:now", "measure:wait", "price:wait"]);
  assert.equal(storedSteps(c)[2].d, "frame.step · 1.5 GB");
});

test("the worker's stages move the steps along, and done is done", () => {
  assert.deepEqual(states({ ...base, phase: "measuring", checkId: "C" }), ["upload:done", "verify:done", "size:done", "measure:now", "price:wait"]);
  const done = { ...base, phase: "done" as const, checkId: "C", memory: { need_bytes: 0.9 * GB, budget_bytes: 1.2 * GB } };
  assert.deepEqual(states(done), ["upload:done", "verify:done", "size:done", "measure:done", "price:done"]);
  // Plain words in the step; the worker's memory and the fingerprint only under Details.
  assert.equal(storedSteps(done)[2].d, "It fits");
  assert.equal(storedSteps(done)[2].tech, "Memory: about 922 MB of the 1.2 GB one check may use on this worker");
  assert.equal(storedSteps(done)[1].t, "Upload checked");
  assert.match(storedSteps(done)[1].tech ?? "", /SHA-256/);
  assert.ok(storedSteps(done).every((x) => !/SHA-256|worker has|memory/i.test(`${x.t} ${x.d}`)));
  const open = { ...done, geometryInvalid: "the mesh has 12 open edges" };
  assert.equal(storedSteps(open)[4].state, "skip");
});

test("a failure lands on the step it belongs to, with the server's words", () => {
  const tooBig = { ...base, phase: "failed" as const, checkId: "C", failure: { title: "Too large", detail: "This file needs about 6.1 GB of memory to check; the largest STEP file ScaleCAD checks today is about 40 MB.", code: "CHECK_TOO_LARGE" } };
  assert.deepEqual(states(tooBig), ["upload:done", "verify:done", "size:bad", "measure:wait", "price:wait"]);
  assert.equal(storedSteps(tooBig)[2].d, tooBig.failure.detail);
  assert.equal(failedStep("DIRECT_UPLOAD_CHECKSUM_MISMATCH", true), "verify");
  assert.equal(failedStep("ARCHIVE_MANY_PARTS", true), "unpack");
  assert.equal(failedStep("user_validation_cap_exceeded", true), "measure");
  assert.equal(failedStep("network", false), "upload");
});

test("the bar moves with the upload, then the worker", () => {
  assert.equal(overallFraction({ ...base, phase: "hashing", sent: 0 }), 0);
  const mid = overallFraction(base)!;
  assert.ok(mid > 0.2 && mid < 0.3, String(mid));
  const measuring = overallFraction({ ...base, phase: "measuring", checkId: "C" })!;
  assert.ok(measuring > 0.65 && measuring < 0.98);
  assert.equal(overallFraction({ ...base, phase: "done" }), 1);
});

test("a share link: one fetch step, on the server, then the worker's stages", () => {
  const link = { ...base, name: "File from Dropbox", size: 0, sent: 0, phase: "starting" as const, linkLabel: "Dropbox", fetchedBytes: null };
  assert.deepEqual(states(link), ["fetch:now", "size:wait", "measure:wait", "price:wait"]);
  assert.equal(storedSteps(link)[0].t, "From Dropbox");
  assert.equal(storedSteps(link)[0].d, "Sending the link");
  assert.equal(storedSteps({ ...link, phase: "queued", checkId: "C" })[0].d, "Waiting for a worker");
  const fetching = { ...link, phase: "fetching" as const, checkId: "C", frac: 0.5 };
  assert.match(storedSteps(fetching)[0].d, /^Fetching on the server · nothing downloads to this browser$/);
  const f = overallFraction(fetching)!;
  assert.ok(f > 0.3 && f < 0.6, String(f));
  const measuring = { ...link, name: "bracket.step", phase: "measuring" as const, checkId: "C", fetchedBytes: 12 * 1024 * 1024 };
  assert.deepEqual(states(measuring), ["fetch:done", "size:done", "measure:now", "price:wait"]);
  assert.equal(storedSteps(measuring)[0].d, "12 MB fetched · checked as it arrived");
  const zipped = { ...measuring, name: "bracket.step.gz", phase: "unpacking" as const };
  assert.deepEqual(states(zipped), ["fetch:done", "unpack:now", "size:wait", "measure:wait", "price:wait"]);
});

test("a link's failure lands on the fetch step with the server's words", () => {
  const failed = {
    ...base, name: "File from Dropbox", size: 0, phase: "failed" as const, checkId: "C", linkLabel: "Dropbox", fetchedBytes: null,
    failure: { title: "The link opens a page, not a file", detail: "That link opens a page, not a file. Share the file itself, or download it and upload the file. Nothing was charged.", code: "LINK_IS_A_PAGE" },
  };
  assert.deepEqual(states(failed), ["fetch:bad", "size:wait", "measure:wait", "price:wait"]);
  assert.equal(storedSteps(failed)[0].d, failed.failure.detail);
  // Refused before a check existed (a link off the allowlist): the fetch step too.
  assert.equal(failedStep("LINK_NOT_SUPPORTED", false, true), "fetch");
  assert.equal(failedStep("CHECK_TOO_LARGE", true, true), "size");
  assert.equal(failedStep("CHECK_UNREADABLE", true, true), "measure");
});
