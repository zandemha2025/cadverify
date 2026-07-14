import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CANONICAL_REPORT_CONTRACTS } from "./local-100-golden-gate.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const runId = process.env.E2E_RUN_ID || `local-100-${new Date().toISOString().replace(/[:.]/g, "-")}`;
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports", runId);
const appUrl = (process.env.APP_URL || "http://localhost:3000").replace(/\/+$/, "");
const apiUrl = (process.env.API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const gitHead = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" }).trim();
const startedAt = new Date().toISOString();
const BUILD_PROBE_ATTEMPTS = 4;
const BUILD_PROBE_TIMEOUT_MS = 2_000;
const BUILD_PROBE_RETRY_MS = 500;

const runners = [
  "public-auth-verify-golden-matrix.mjs",
  "auth-role-lifecycle-golden-matrix.mjs",
  "manufacturing-cad-adversarial.mjs",
  "notification-decision-golden-matrix.mjs",
  "role-tenant-boundary-matrix.mjs",
  "compare-rfq-key-golden-matrix.mjs",
  "batch-design-recovery-golden-matrix.mjs",
  "design-studio-human-e2e.mjs",
  "enterprise-domain-runner.mjs",
  "mobile-recovery-e2e.mjs",
];

// Conservative slide mapping: a slide is build-verified only when every named
// Local gate contracts passed for this exact clean served build. Slides that also
// require the separate training-guide/deck supplement, customer data, or an
// external provider are intentionally absent.
const SLIDE_CONTRACTS = Object.freeze({
  access: ["AUTH-01", "AUTH-02", "AUTH-04", "AUTH-05"],
  "access-modes": ["AUTH-01", "AUTH-02", "AUTH-04", "AUTH-05"],
  "invite-accept": ["AUTH-03", "ROLE-03"],
  "session-security": ["AUTH-02", "AUTH-05", "AUTH-07", "AUTH-08"],
  "public-evaluator": ["PUB-01", "PUB-02", "PUB-03", "PUB-04"],
  "verify-upload": ["VER-01", "VER-02", "VER-03"],
  "verify-read": ["VER-01", "VER-04", "VER-07"],
  "verify-act": ["VER-02", "VER-03"],
  "analyze-dfm": ["WORK-02", "VER-05"],
  "verify-formats": ["VER-05", "FAIL-01", "FAIL-02"],
  "parts-triage": ["ENT-04", "ENT-05"],
  "records-history": ["VER-04", "VER-09"],
  "design-guardrails": ["DES-01", "DES-02", "DES-03"],
  "design-plate": ["DES-04", "DES-05"],
  "design-revise": ["DES-06", "DES-07", "DES-08"],
  "design-history": ["DES-09", "DES-10", "DES-11"],
  "design-archive": ["DES-12", "DES-13"],
  "design-shapes": ["DES-01", "DES-04", "DES-06"],
  "cost-direct": ["WORK-01", "WORK-03"],
  "cost-workspace": ["WORK-03", "WORK-04"],
  "decision-approve": ["WORK-05", "ROLE-04"],
  "decision-stale": ["WORK-05", "FAIL-09"],
  "compare-ab": ["WORK-06"],
  exports: ["DES-05", "DES-10", "DES-11", "WORK-06", "WORK-08"],
  "public-share": ["WORK-07"],
  "machine-floor": ["ENT-01"],
  calibration: ["ENT-02"],
  "severe-service": ["ENT-03"],
  programs: ["ENT-04"],
  batch: ["WORK-02", "WORK-11"],
  "batch-recovery": ["FAIL-04", "FAIL-05", "FAIL-10"],
  "batch-cancel": ["WORK-11", "FAIL-04"],
  rfq: ["WORK-08"],
  "api-keys": ["WORK-12"],
  "org-security": ["AUTH-03", "ROLE-01", "ROLE-03"],
  "role-boundaries": ["ROLE-01", "ROLE-02", "ROLE-03", "ROLE-04"],
  recovery: ["FAIL-01", "FAIL-02", "FAIL-03", "FAIL-04", "FAIL-05", "FAIL-06", "FAIL-07", "FAIL-08", "FAIL-09", "FAIL-10"],
  mobile: ["DES-13", "VER-09", "FAIL-03", "FAIL-08", "FAIL-10"],
});

function fail(message) {
  process.stderr.write(`LOCAL_GATE precondition failed: ${message}\n`);
  process.exit(1);
}

function filesRecursively(root) {
  if (!existsSync(root)) return [];
  const files = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const absolute = path.join(root, entry.name);
    if (entry.isDirectory()) files.push(...filesRecursively(absolute));
    else files.push(absolute);
  }
  return files;
}

function canonicalReports() {
  const suites = new Set(CANONICAL_REPORT_CONTRACTS.map((item) => item.suite));
  const found = [];
  for (const file of filesRecursively(outputRoot).filter((item) => item.endsWith(".json"))) {
    try {
      const data = JSON.parse(readFileSync(file, "utf8"));
      if (suites.has(data?.suite) && data?.runId === runId) found.push({ file, suite: data.suite });
    } catch {
      // Non-report JSON artifacts are intentionally ignored.
    }
  }
  return found;
}

function probeErrorMessage(error) {
  const message = error instanceof Error ? error.message : String(error);
  const cause = error && typeof error === "object" ? error.cause : null;
  if (!cause) return message;
  const causeCode = cause && typeof cause === "object" && "code" in cause ? cause.code : null;
  const causeMessage = cause instanceof Error ? cause.message : String(cause);
  return `${message}${causeCode ? ` [${causeCode}]` : ""}: ${causeMessage}`;
}

async function fetchServedBuilds() {
  const builds = {};
  const errors = [];
  for (const [label, url] of [["frontend", `${appUrl}/status`], ["backend", `${apiUrl}/health`]]) {
    let lastError = null;
    for (let attempt = 1; attempt <= BUILD_PROBE_ATTEMPTS; attempt += 1) {
      try {
        const response = await fetch(url, {
          headers: {
            "connection": "close",
            "x-real-ip": "198.51.100.199",
          },
          signal: AbortSignal.timeout(BUILD_PROBE_TIMEOUT_MS),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (label === "frontend") {
          const build = response.headers.get("x-proofshape-build");
          if (!build) throw new Error("missing x-proofshape-build response header");
          builds.frontend = build;
        } else {
          const body = await response.json();
          if (body?.status !== "ok") throw new Error(`health was not ok: ${JSON.stringify(body)}`);
          if (!body?.build_id) throw new Error("health response omitted build_id");
          builds.backend = body.build_id;
        }
        lastError = null;
        break;
      } catch (error) {
        lastError = probeErrorMessage(error);
        if (attempt < BUILD_PROBE_ATTEMPTS) {
          await new Promise((resolve) => setTimeout(resolve, BUILD_PROBE_RETRY_MS));
        }
      }
    }
    if (lastError) {
      errors.push(`${label} could not verify ${url} after ${BUILD_PROBE_ATTEMPTS} attempts: ${lastError}`);
    }
  }
  return { builds, errors };
}

function sha256(relativePath) {
  return createHash("sha256").update(readFileSync(path.join(repoRoot, relativePath))).digest("hex");
}

const dirty = execFileSync("git", ["status", "--porcelain", "--untracked-files=normal"], {
  cwd: repoRoot,
  encoding: "utf8",
}).trim();
if (dirty) fail("the checkout is dirty; commit first so evidence maps to reproducible source");

if (!process.env.E2E_FAULT_INJECTION_TOKEN) {
  fail("E2E_FAULT_INJECTION_TOKEN is required to exercise bounded recovery paths");
}
for (const [key, expected] of [
  ["PRODUCTION_AUTH_PROXY_REQUIRED", "1"],
  ["WORKER_STRICT_HEALTH", "1"],
  ["ASYNC_STRICT_HEALTH", "1"],
  ["RATE_LIBRARY_ENABLED", "1"],
]) {
  if (process.env[key] !== expected) fail(`${key} must equal ${expected}`);
}
if (!process.env.DATABASE_URL) fail("DATABASE_URL must name the real release-test PostgreSQL database");
if (!process.env.REDIS_URL) fail("REDIS_URL must name the real release-test Redis service");

if (existsSync(outputRoot) && readdirSync(outputRoot).length > 0) {
  fail(`artifact directory must be new or empty: ${outputRoot}`);
}
mkdirSync(outputRoot, { recursive: true });

const initialPreflight = await fetchServedBuilds();
if (initialPreflight.errors.length > 0) fail(initialPreflight.errors.join("; "));
const servedBuilds = initialPreflight.builds;
for (const [service, servedBuild] of Object.entries(servedBuilds)) {
  if (servedBuild !== gitHead) {
    fail(`${service} serves build ${JSON.stringify(servedBuild)} but the clean checkout is ${gitHead}`);
  }
}

const childEnv = {
  ...process.env,
  APP_URL: appUrl,
  API_URL: apiUrl,
  E2E_ARTIFACT_DIR: outputRoot,
  E2E_BUILD_ID: gitHead,
  E2E_RUN_ID: runId,
};
const runnerFailures = [];
for (const [index, runner] of runners.entries()) {
  process.stdout.write(`\n[LOCAL_GATE ${index + 1}/${runners.length}] ${runner}\n`);
  const result = spawnSync(process.execPath, [path.join(__dirname, runner)], {
    cwd: repoRoot,
    env: { ...childEnv, E2E_CLIENT_IP: `198.51.100.${100 + index}` },
    stdio: "inherit",
  });
  if (result.status !== 0) runnerFailures.push({ runner, status: result.status, signal: result.signal });
}

const reports = canonicalReports();
const expectedSuites = CANONICAL_REPORT_CONTRACTS.map((item) => item.suite).sort();
const actualSuites = reports.map((item) => item.suite).sort();
if (JSON.stringify(actualSuites) !== JSON.stringify(expectedSuites)) {
  process.stderr.write(`Canonical reports differ. Expected ${JSON.stringify(expectedSuites)}, got ${JSON.stringify(actualSuites)}\n`);
}

const gateOutput = path.join(outputRoot, `local-100-gate-${runId}.json`);
const gate = reports.length === CANONICAL_REPORT_CONTRACTS.length
  ? spawnSync(process.execPath, [
      path.join(__dirname, "local-100-golden-gate.mjs"),
      "--run-id", runId,
      "--output", gateOutput,
      ...reports.map((item) => item.file),
    ], { cwd: repoRoot, env: childEnv, stdio: "inherit" })
  : { status: 1 };

const finalDirtyText = execFileSync("git", ["status", "--porcelain", "--untracked-files=normal"], {
  cwd: repoRoot,
  encoding: "utf8",
}).trim();
const finalPreflight = await fetchServedBuilds();
const finalBuildProblems = [...finalPreflight.errors];
for (const [service, servedBuild] of Object.entries(finalPreflight.builds)) {
  if (servedBuild !== gitHead) {
    finalBuildProblems.push(`${service} serves ${JSON.stringify(servedBuild)} after the run; expected ${gitHead}`);
  }
}
let gateResult = null;
if (existsSync(gateOutput)) {
  try {
    gateResult = JSON.parse(readFileSync(gateOutput, "utf8"));
  } catch (error) {
    finalBuildProblems.push(`gate output could not be parsed: ${error instanceof Error ? error.message : String(error)}`);
  }
}
const suiteSetExact = JSON.stringify(actualSuites) === JSON.stringify(expectedSuites);
const releasePass = (
  runnerFailures.length === 0
  && gate.status === 0
  && gateResult?.status === "PASS"
  && gateResult?.claim === "LOCAL_GATE_PASS"
  && suiteSetExact
  && finalDirtyText === ""
  && finalBuildProblems.length === 0
  && finalPreflight.builds.frontend === gitHead
  && finalPreflight.builds.backend === gitHead
);
const passedIds = new Set(Object.keys(gateResult?.validation?.evidence || gateResult?.sources || {}));
const slideEvidence = Object.fromEntries(Object.entries(SLIDE_CONTRACTS).map(([slide, contracts]) => [slide, {
  status: releasePass && contracts.every((id) => passedIds.has(id)) ? "PASS" : "FAIL",
  contracts,
}]));
const releaseManifest = {
  schemaVersion: 1,
  status: releasePass ? "PASS" : "FAIL",
  claim: releasePass ? "LOCAL_GATE_PASS" : null,
  runId,
  generatedAt: new Date().toISOString(),
  startedAt,
  gitHead,
  clean: !dirty && finalDirtyText === "",
  initialServedBuilds: servedBuilds,
  servedBuilds: finalPreflight.builds,
  servedBuildProblems: finalBuildProblems,
  fixtures: {
    "cube-step": sha256("backend/tests/assets/cube.step"),
    "ground-truth-mixed.csv": sha256("docs/training/fixtures/ground-truth-mixed.csv"),
    "parts-manifest-mixed.csv": sha256("docs/training/fixtures/parts-manifest-mixed.csv"),
    "parts-master-map.csv": sha256("docs/training/fixtures/parts-master-map.csv"),
    "sap-s4hana-sandbox.json": sha256("docs/training/fixtures/sap-s4hana-sandbox.json"),
    "windchill-sandbox.json": sha256("docs/training/fixtures/windchill-sandbox.json"),
    "wire-only-unmeshable.step": sha256("docs/training/fixtures/wire-only-unmeshable.step"),
  },
  canonicalReports: reports.map((item) => ({ suite: item.suite, file: item.file })),
  runnerFailures,
  gate: {
    processStatus: gate.status,
    output: gateOutput,
    status: gateResult?.status || null,
    claim: gateResult?.claim || null,
    counts: gateResult?.counts || null,
  },
  slides: Object.fromEntries(Object.entries(slideEvidence).map(([slide, evidence]) => [slide, evidence.status])),
  slideEvidence,
};
const releaseManifestPath = path.join(outputRoot, `release-manifest-${runId}.json`);
writeFileSync(releaseManifestPath, `${JSON.stringify(releaseManifest, null, 2)}\n`);

process.stdout.write(`${JSON.stringify({
  runId,
  buildId: gitHead,
  servedBuilds,
  outputRoot,
  canonicalReports: reports.length,
  runnerFailures,
  gateStatus: gate.status,
  gateOutput,
  releaseStatus: releaseManifest.status,
  releaseManifest: releaseManifestPath,
}, null, 2)}\n`);

if (!releasePass) {
  process.exitCode = 1;
}
