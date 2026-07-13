import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  OWNED_PATH_IDS,
  parseCsv,
  writeDeterministicStoredZip,
} from "./batch-design-recovery-golden-matrix.mjs";

const sourcePath = new URL("./batch-design-recovery-golden-matrix.mjs", import.meta.url);

test("matrix owns exactly the canonical batch/design recovery IDs", () => {
  assert.deepEqual(OWNED_PATH_IDS, [
    "WORK-03",
    "WORK-04",
    "FAIL-04",
    "FAIL-05",
    "FAIL-06",
    "FAIL-07",
  ]);
});

test("deterministic ZIP writer emits one valid stored record per requested entry", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "proofshape-batch-matrix-"));
  try {
    const source = path.join(directory, "fixture.step");
    const destination = path.join(directory, "fixture.zip");
    await writeFile(source, "ISO-10303-21; deterministic release fixture\nEND-ISO-10303-21;\n");
    const names = ["alpha.step", "beta.step", "gamma.step"];
    const metadata = await writeDeterministicStoredZip(source, destination, names);
    const archive = await readFile(destination);
    const endOffset = archive.length - 22;
    assert.equal(archive.readUInt32LE(endOffset), 0x06054b50);
    assert.equal(archive.readUInt16LE(endOffset + 8), names.length);
    assert.equal(archive.readUInt16LE(endOffset + 10), names.length);
    const centralSize = archive.readUInt32LE(endOffset + 12);
    const centralOffset = archive.readUInt32LE(endOffset + 16);
    const found = [];
    let offset = centralOffset;
    while (offset < centralOffset + centralSize) {
      assert.equal(archive.readUInt32LE(offset), 0x02014b50);
      const nameLength = archive.readUInt16LE(offset + 28);
      const extraLength = archive.readUInt16LE(offset + 30);
      const commentLength = archive.readUInt16LE(offset + 32);
      const localOffset = archive.readUInt32LE(offset + 42);
      assert.equal(archive.readUInt32LE(localOffset), 0x04034b50);
      found.push(archive.subarray(offset + 46, offset + 46 + nameLength).toString("utf8"));
      offset += 46 + nameLength + extraLength + commentLength;
    }
    assert.deepEqual(found, names);
    assert.deepEqual(metadata.entries, names);
    assert.match(metadata.sha256, /^[a-f0-9]{64}$/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("CSV parser preserves exact quoted result fields", () => {
  const parsed = parseCsv(
    'filename,status,verdict,best_process,issue_count,duration_ms,analysis_url,error\n"a,part.step",failed,,,0,12.5,,"kernel, stopped"\n',
  );
  assert.deepEqual(parsed.headers, [
    "filename",
    "status",
    "verdict",
    "best_process",
    "issue_count",
    "duration_ms",
    "analysis_url",
    "error",
  ]);
  assert.deepEqual(parsed.records[0], {
    filename: "a,part.step",
    status: "failed",
    verdict: "",
    best_process: "",
    issue_count: "0",
    duration_ms: "12.5",
    analysis_url: "",
    error: "kernel, stopped",
  });
});

test("runner binds real faults, durable assertions, common evidence, and build identity", async () => {
  const source = await readFile(sourcePath, "utf8");
  assert.match(source, /makeGoldenPathEvidence\(\{/);
  assert.match(source, /validateGoldenPathMap\(OWNED_PATH_IDS, this\.goldenPaths\)/);
  assert.match(source, /captureBuildIdentity\(repoRoot\)/);
  assert.match(source, /releaseEvidence:\s*\{[\s\S]*goldenPaths: this\.goldenPaths/);
  assert.match(source, /E2E_FAULT_INJECTION_TOKEN/);
  for (const mode of ["batch_delay", "design_queue", "cad_kernel", "object_store", "batch_queue"]) {
    assert.match(source, new RegExp(`fault: ["']${mode}["']|release_test_fault[^\\n]*${mode}|${mode}`));
  }
  for (const copy of [
    "Design generation is temporarily unavailable. Retry shortly.",
    "The CAD kernel could not generate this revision. Check the dimensions and retry.",
    "The generated files could not be stored. Retry this revision.",
    "Batch was accepted but could not be scheduled (job queue unavailable). It has been marked failed; please retry.",
  ]) {
    assert.ok(source.includes(copy), `runner omitted exact copy: ${copy}`);
  }
  assert.ok(source.includes("filename,status,verdict,best_process,issue_count,duration_ms,analysis_url,error"));
  assert.match(source, /completed \+ failed \+ skipped/);
  assert.match(source, /data-batch-items-state=["']ready["']/);
  assert.match(source, /getByText\(entry, \{ exact: true \}\)\.waitFor/);
  assert.match(source, /assertRevisionHasNoArtifacts/);
  assert.match(source, /async waitForRevisionHistorySettled\(revisions\)/);
  assert.equal(source.match(/await this\.waitForRevisionHistorySettled\(revisions\)/g)?.length, 4);
  assert.match(source, /x-proofshape-e2e-token/);
  assert.match(source, /route\.continue/);
  assert.doesNotMatch(source, /route\.fulfill/);
  assert.doesNotMatch(source, /mobile-recovery-e2e/);
});
