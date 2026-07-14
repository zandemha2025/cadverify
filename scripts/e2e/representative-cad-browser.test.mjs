import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  mkdirSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  MAX_SUPPORTED_CASES,
  OPTIONAL_COVERAGE,
  REQUIRED_COVERAGE,
  assertTruthfulTerminalCase,
  dispositionForCost,
  fixtureSetBindingSha256,
  isExpectedNextRscPrefetchAbort,
  loadRepresentativeManifest,
  waitForVerificationPipeline,
} from "./representative-cad-browser.mjs";

test("request failure filter ignores only same-origin Next RSC prefetch cancellation", () => {
  const appUrl = "http://localhost:3001";
  const expected = {
    url: "http://localhost:3001/designs?_rsc=abc123",
    method: "GET",
    resourceType: "fetch",
    error: "net::ERR_ABORTED",
  };
  assert.equal(isExpectedNextRscPrefetchAbort(expected, appUrl), true);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, url: "https://other.example/designs?_rsc=abc123" }, appUrl), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, url: "http://localhost:3001/designs" }, appUrl), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, method: "POST" }, appUrl), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, resourceType: "document" }, appUrl), false);
  assert.equal(isExpectedNextRscPrefetchAbort({ ...expected, error: "net::ERR_CONNECTION_RESET" }, appUrl), false);
});

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const corpusScript = path.join(repoRoot, "scripts", "prehuman", "real_cad_corpus.py");
const runnerPath = path.join(repoRoot, "scripts", "e2e", "representative-cad-browser.mjs");
const BINDING_FIELDS = [
  "id",
  "relative_path",
  "file_sha256",
  "bytes",
  "support_status",
  "expected_browser_outcome",
  "source_ref",
];
const ARCHIVES = [
  {
    id: "nist_pmi_step",
    zip_sha256: "8fa78429e6d8d9b0d7681d223b6aa9ec98c3772185c55b1a0e3679b21c181911",
    zip_bytes: 13_976_599,
  },
  {
    id: "nist_mtc_assembly",
    zip_sha256: "9aeb53e54f682ea1732857d06a7f0513c71667a2d84407396325fa6ce5340bbc",
    zip_bytes: 15_861_580,
  },
];

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function pythonExecutable() {
  if (process.env.CADVERIFY_PYTHON) return process.env.CADVERIFY_PYTHON;
  const venv = path.join(repoRoot, "backend", ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

function readBrowserPlan() {
  const result = spawnSync(pythonExecutable(), [corpusScript, "--browser-plan"], {
    cwd: repoRoot,
    encoding: "utf8",
    timeout: 20_000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout);
}

test("deterministic Python browser plan covers every required family while the full corpus stays exhaustive", () => {
  const first = readBrowserPlan();
  const second = readBrowserPlan();
  assert.deepEqual(second, first);
  assert.equal(first.exhaustive_nist_step_case_count, 33);
  assert.deepEqual(first.required_coverage, [...REQUIRED_COVERAGE]);
  assert.deepEqual(first.optional_coverage, [...OPTIONAL_COVERAGE]);
  assert.equal(first.selections.length, 8);

  const covered = new Set(first.selections.flatMap((item) => item.coverage_tags));
  for (const family of [...REQUIRED_COVERAGE, ...OPTIONAL_COVERAGE]) {
    assert.equal(covered.has(family), true, `missing ${family}`);
  }
  const supported = first.selections.filter((item) => item.support_status === "supported");
  assert.equal(supported.length, MAX_SUPPORTED_CASES);
  assert.deepEqual(
    first.selections.filter((item) => item.schema_edition?.startsWith("AP242")).map((item) => item.schema_edition),
    ["AP242 e1", "AP242 e2", "AP242 e3"],
  );
  const tessellated = first.selections.find((item) => item.id === "BROWSER-AP242-E1-TESSELLATED");
  assert.deepEqual(tessellated.coverage_tags, ["ap242_e1", "ap242_embedded_tessellation"]);
  const native = first.selections.find((item) => item.support_status === "unsupported");
  assert.equal(native.expected_browser_outcome, "unsupported_native_assembly");
  assert.match(native.filename, /\.sldasm$/i);
  assert.equal(new Set(first.selections.map((item) => item.id)).size, first.selections.length);
});

test("Python and browser runner compute the same language-neutral fixture binding", () => {
  const fixtures = [
    {
      id: "b",
      relative_path: "files/b.step",
      file_sha256: "b".repeat(64),
      bytes: 2,
      support_status: "supported",
      expected_browser_outcome: "verified_and_saved",
      source_ref: "unit:b",
    },
    {
      id: "a",
      relative_path: "files/a.step",
      file_sha256: "a".repeat(64),
      bytes: 1,
      support_status: "supported",
      expected_browser_outcome: "verified_and_saved",
      source_ref: "unit:a",
    },
  ];
  const code = [
    "import importlib.util,json,sys",
    `spec=importlib.util.spec_from_file_location('real_cad_corpus', ${JSON.stringify(corpusScript)})`,
    "module=importlib.util.module_from_spec(spec)",
    "spec.loader.exec_module(module)",
    "print(module.fixture_set_binding_sha256(json.load(sys.stdin)))",
  ].join(";");
  const result = spawnSync(pythonExecutable(), ["-c", code], {
    cwd: repoRoot,
    encoding: "utf8",
    input: JSON.stringify(fixtures),
    timeout: 20_000,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.equal(result.stdout.trim(), fixtureSetBindingSha256(fixtures));
});

function makeFixture(root, { id, filename, coverageTags, unsupported = false }) {
  const relativePath = `files/${filename}`;
  const bytes = Buffer.from(`fixture:${id}\n`, "utf8");
  const absolutePath = path.join(root, relativePath);
  mkdirSync(path.dirname(absolutePath), { recursive: true });
  writeFileSync(absolutePath, bytes);
  return {
    id,
    order: 1,
    filename,
    relative_path: relativePath,
    file_sha256: sha256(bytes),
    bytes: bytes.length,
    family: "unit",
    schema: unsupported ? "native_solidworks" : "STEP",
    schema_edition: unsupported ? "SolidWorks native assembly" : "unit",
    cad_category: unsupported ? "native_assembly_control" : "unit",
    coverage_tags: coverageTags,
    support_status: unsupported ? "unsupported" : "supported",
    expected_browser_outcome: unsupported ? "unsupported_native_assembly" : "verified_and_saved",
    source_ref: `unit:${id}`,
    source: { kind: "unit" },
  };
}

function writeUnitManifest(root) {
  const fixtures = [
    makeFixture(root, { id: "ap203-geometry", filename: "01.stp", coverageTags: ["ap203_geometry"] }),
    makeFixture(root, { id: "ap203-pmi", filename: "02.stp", coverageTags: ["ap203_pmi"] }),
    makeFixture(root, { id: "ap242-e1-tess", filename: "03.stp", coverageTags: ["ap242_e1", "ap242_embedded_tessellation"] }),
    makeFixture(root, { id: "ap242-e2", filename: "04.stp", coverageTags: ["ap242_e2"] }),
    makeFixture(root, { id: "ap242-e3", filename: "05.stp", coverageTags: ["ap242_e3"] }),
    makeFixture(root, { id: "periodic", filename: "06.stp", coverageTags: ["tracked_periodic_step"] }),
    makeFixture(root, { id: "native", filename: "07.sldasm", coverageTags: ["native_assembly_unsupported"], unsupported: true }),
  ];
  const coverage = Object.fromEntries(
    [...REQUIRED_COVERAGE, ...OPTIONAL_COVERAGE].map((tag) => [
      tag,
      fixtures.filter((fixture) => fixture.coverage_tags.includes(tag)).map((fixture) => fixture.id),
    ]),
  );
  const manifest = {
    schema_version: 1,
    set_id: "nist-representative-browser-v1",
    binding_fields: BINDING_FIELDS,
    source_archives: ARCHIVES,
    fixtures,
    coverage,
    omissions: [{ id: "iges", coverage_tags: ["iges"], reason: "gmsh unavailable in unit fixture" }],
  };
  manifest.fixture_set_sha256 = fixtureSetBindingSha256(fixtures);
  const manifestPath = path.join(root, "representative-cad-manifest.json");
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  return { manifest, manifestPath };
}

test("manifest loader verifies the set binding, every file hash, path confinement, and unsupported truth label", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "representative-cad-manifest-test-"));
  try {
    const { manifest, manifestPath } = writeUnitManifest(root);
    const loaded = loadRepresentativeManifest(manifestPath);
    assert.equal(loaded.supported.length, 6);
    assert.equal(loaded.unsupported.length, 1);
    assert.equal(loaded.manifest.fixture_set_sha256, fixtureSetBindingSha256(manifest.fixtures));

    const firstPath = path.join(root, manifest.fixtures[0].relative_path);
    writeFileSync(firstPath, "tampered");
    assert.throws(() => loadRepresentativeManifest(manifestPath), /byte count changed|SHA-256 changed/);

    writeFileSync(firstPath, Buffer.from(`fixture:${manifest.fixtures[0].id}\n`));
    const escaped = structuredClone(manifest);
    escaped.fixtures[0].relative_path = "../escape.stp";
    escaped.fixture_set_sha256 = fixtureSetBindingSha256(escaped.fixtures);
    writeFileSync(manifestPath, `${JSON.stringify(escaped)}\n`);
    assert.throws(() => loadRepresentativeManifest(manifestPath), /escapes the materialized fixture directory/);

    const fabricated = structuredClone(manifest);
    const native = fabricated.fixtures.find((fixture) => fixture.id === "native");
    native.support_status = "supported";
    native.expected_browser_outcome = "verified_and_saved";
    fabricated.fixture_set_sha256 = fixtureSetBindingSha256(fabricated.fixtures);
    writeFileSync(manifestPath, `${JSON.stringify(fabricated)}\n`);
    assert.throws(() => loadRepresentativeManifest(manifestPath), /marked supported with unsupported suffix/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("terminal lifecycle helper requires the real dialog to become visible and then hidden", async () => {
  const calls = [];
  const page = {
    getByRole(role, options) {
      assert.equal(role, "dialog");
      assert.deepEqual(options, { name: "Verification pipeline", exact: true });
      return {
        async waitFor(options) {
          calls.push(options);
        },
      };
    },
  };
  const result = await waitForVerificationPipeline(page, { timeoutMs: 90_000 });
  assert.deepEqual(calls, [
    { state: "visible", timeout: 15_000 },
    { state: "hidden", timeout: 90_000 },
  ]);
  assert.deepEqual(result, { appeared: true, disappeared: true });
});

function truthfulFixture() {
  return {
    id: "truthful-case",
    filename: "truthful.stp",
    support_status: "supported",
    expected_browser_outcome: "verified_and_saved",
  };
}

function truthfulResponses() {
  return {
    validation: {
      filename: "truthful.stp",
      overall_verdict: "PASS",
      geometry: {
        bounding_box_mm: [20, 20, 20],
        volume_mm3: 8000,
        surface_area_mm2: 2400,
        is_watertight: true,
      },
    },
    cost: {
      status: "OK",
      geometry: {
        bbox_mm: [20, 20, 20],
        volume_cm3: 8,
        face_count: 12,
        watertight: true,
      },
      decision: { make_now_process: "cnc_3axis" },
      assumptions: [{ provenance: "DEFAULT" }],
      estimates: [
        {
          unit_cost_usd: 12.34,
          line_items: { material: 2.34, machine: 10 },
          drivers: [
            { name: "machine_rate", provenance: "DEFAULT" },
          ],
        },
      ],
      saved: { id: "01REPRESENTATIVEDECISION" },
    },
    visibleText:
      "truthful.stp · VERDICT · SHOULD-COST COMPUTED · Should-cost $12.34/unit · " +
      "20.0 × 20.0 × 20.0 mm · 8.00 cm³ · watertight true · MEASURED · DEFAULT · What it really takes",
  };
}

test("truth oracle accepts measured geometry/cost/provenance and rejects fabricated terminal success", () => {
  const fixture = truthfulFixture();
  const valid = truthfulResponses();
  const evidence = assertTruthfulTerminalCase({ fixture, ...valid });
  assert.equal(evidence.savedDecisionId, "01REPRESENTATIVEDECISION");
  assert.equal(evidence.costGeometry.volumeCm3, 8);
  assert.deepEqual(evidence.provenance, ["DEFAULT"]);

  const zeroGeometry = structuredClone(valid);
  zeroGeometry.validation.geometry.volume_mm3 = 0;
  assert.throws(() => assertTruthfulTerminalCase({ fixture, ...zeroGeometry }), /volume_mm3 is not positive/);

  const missingSave = structuredClone(valid);
  missingSave.cost.saved = null;
  assert.throws(() => assertTruthfulTerminalCase({ fixture, ...missingSave }), /durable saved decision id/);

  const mismatchedCost = structuredClone(valid);
  mismatchedCost.cost.estimates[0].unit_cost_usd = 99;
  assert.throws(() => assertTruthfulTerminalCase({ fixture, ...mismatchedCost }), /does not reconcile to line items/);

  const inventedProvenance = structuredClone(valid);
  inventedProvenance.cost.estimates[0].drivers[0].provenance = "INFERRED";
  assert.throws(() => assertTruthfulTerminalCase({ fixture, ...inventedProvenance }), /unexpected provenance/);

  const failureOnScreen = structuredClone(valid);
  failureOnScreen.visibleText += " Cost request failed";
  assert.throws(() => assertTruthfulTerminalCase({ fixture, ...failureOnScreen }), /terminal UI contains failure copy/);

  const unsupported = { ...fixture, support_status: "unsupported", expected_browser_outcome: "unsupported_native_assembly" };
  assert.throws(() => assertTruthfulTerminalCase({ fixture: unsupported, ...valid }), /not a supported browser case/);
});

test("human outcome follows selected-route DFM instead of recording a blocked route in-house", () => {
  const pass = truthfulResponses().cost;
  assert.deepEqual(dispositionForCost(pass), { key: "inhouse", label: "Make in-house" });

  const blocked = structuredClone(pass);
  blocked.estimates[0].process = blocked.decision.make_now_process;
  blocked.estimates[0].dfm_ready = false;
  blocked.estimates[0].dfm_verdict = "fail";
  blocked.estimates[0].dfm_blockers = ["Envelope exceeded"];
  assert.deepEqual(dispositionForCost(blocked), { key: "redesign", label: "Redesign" });
});

test("live orchestration is pinned to the real uploader, refresh + Records reopen, screenshots, and strict error accounting", () => {
  const source = readFileSync(runnerPath, "utf8");
  assert.match(source, /getByTestId\("verify-part-cad-input"\)/);
  assert.match(source, /input\.setInputFiles\(fixture\.absolutePath\)/);
  assert.match(source, /waitForVerificationPipeline\(this\.page/);
  assert.match(source, /waitForSettledHome\(this\.page/);
  assert.match(source, /loading…\|checking/);
  assert.match(source, /state: "hidden"/);
  assert.match(source, /this\.page\.reload\(\{ waitUntil: "domcontentloaded"/);
  assert.match(source, /getByRole\("button", \{ name: "Records", exact: true \}\)/);
  assert.match(source, /record\.id === truth\.savedDecisionId/);
  assert.match(source, /dispositionForCost\(cost\)/);
  assert.match(source, /reopenedAfterRefresh: true/);
  assert.match(source, /terminal: terminalScreenshot/);
  assert.match(source, /recordsAfterRefresh: recordsScreenshot/);
  assert.match(source, /zeroConsoleErrors/);
  assert.match(source, /zeroRequestFailures/);
  assert.match(source, /zeroUnexpectedHttpErrors/);
  assert.match(source, /assemblyResponse\.status\(\) === 200/);
  assert.doesNotMatch(source, /expected_brep_assembly_probe_fallback/);
  assert.match(source, /expectedHttpBoundaries/);
  assert.match(source, /await input\.setInputFiles\(fixture\.absolutePath\)/);
  assert.match(source, /getByTestId\("verify-upload-rejection"\)/);
  assert.match(source, /networkUploadAttempted: false/);
  assert.match(source, /computeRequests\.length === 0/);
  assert.match(source, /STEP AP242/);
  assert.match(source, /successClaimed: false/);
});
