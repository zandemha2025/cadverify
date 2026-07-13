import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);

const artifacts = {
  json: path.join(outputRoot, `enterprise-answer-fidelity-${runId}.json`),
  md: path.join(outputRoot, `qa-report-enterprise-answer-fidelity-${runId}.md`),
};

const expected = {
  cubeSha256: "76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a",
  cubeBytes: 19030,
  annualVolume: 12000,
  procurementThresholdsUsd: {
    engineerSelfServe: 25000,
    sourcingManager: 250000,
    capitalBoard: 1000000,
  },
  serviceEnvironment: {
    max_temp_c: 120,
    sour_service: true,
    pressure_bar: 350,
  },
  machineRates: {
    "MJF 5200 - Bay 4": { process: "mjf", rate: 48 },
    "Haas VF-4SS - Energy Cell": { process: "cnc_3axis", rate: 95 },
    "Mazak Integrex i-200": { process: "cnc_5axis", rate: 142 },
    "EOS M290 - Nickel/SS Cell": { process: "dmls", rate: 185 },
  },
};

const files = {
  human: path.join(outputRoot, `human-e2e-${runId}.json`),
  enterprise: path.join(outputRoot, `enterprise-domain-${runId}.json`),
  p7: path.join(outputRoot, `p7-role-failure-${runId}.json`),
  coverage: path.join(outputRoot, `human-sim-journey-coverage-${runId}.json`),
  gauntlet: path.join(outputRoot, `synthetic-enterprise-gauntlet-${runId}.json`),
  assemblyFidelity: path.join(outputRoot, `assembly-visual-fidelity-${runId}.json`),
  cube: path.join(repoRoot, "backend/tests/assets/cube.step"),
  enterpriseRunner: path.join(repoRoot, "scripts/e2e/enterprise-domain-runner.mjs"),
  findings: path.join(repoRoot, "frontend/src/lib/findings.ts"),
  catalog: path.join(repoRoot, "frontend/src/lib/catalog.ts"),
  costPdf: path.join(repoRoot, "backend/src/services/cost_pdf_service.py"),
  materialLibrary: path.join(repoRoot, "backend/src/services/material_library_service.py"),
};

function assert(condition, detail) {
  if (!condition) throw new Error(detail);
}

function approxEqual(a, b, tolerance = 0.01) {
  return Math.abs(a - b) <= Math.max(tolerance, Math.abs(b) * 1e-9);
}

async function readJson(filename) {
  return JSON.parse(await readFile(filename, "utf8"));
}

function number(value, label) {
  assert(typeof value === "number" && Number.isFinite(value), `${label} is not a finite number`);
  return value;
}

function contains(text, ...needles) {
  const missing = needles.filter((needle) => !text.includes(needle));
  assert(missing.length === 0, `missing source text: ${missing.join(", ")}`);
}

function matches(text, ...patterns) {
  const missing = patterns.filter((pattern) => !pattern.test(text));
  assert(missing.length === 0, `missing source pattern: ${missing.map(String).join(", ")}`);
}

function getStep(report, name) {
  const step = (report.steps || []).find((item) => item.name === name);
  assert(step, `missing browser step: ${name}`);
  assert(step.status === "pass", `browser step did not pass: ${name}`);
  return step;
}

function reportIsClean(report, label) {
  const steps = report.steps || [];
  assert(report.status === "PASS", `${label} status is ${report.status}`);
  assert(steps.filter((step) => step.status === "fail").length === 0, `${label} has failed steps`);
  assert(steps.filter((step) => step.status === "skip").length === 0, `${label} has skipped steps`);
  assert((report.issues || []).length === 0, `${label} has issues`);
  assert((report.consoleErrors || []).length === 0, `${label} has console errors`);
  assert((report.requestFailures || []).length === 0, `${label} has request failures`);
}

function resolveScreenshotPath(screenshotPath) {
  assert(screenshotPath, "step did not record a screenshot");
  if (existsSync(screenshotPath)) return screenshotPath;
  const marker = ".gstack/qa-reports/";
  const normalized = screenshotPath.replaceAll("\\", "/");
  const index = normalized.indexOf(marker);
  if (index !== -1) {
    return path.join(outputRoot, normalized.slice(index + marker.length));
  }
  return screenshotPath;
}

function paethPredictor(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

function parsePng(buffer) {
  const signature = "89504e470d0a1a0a";
  assert(buffer.subarray(0, 8).toString("hex") === signature, "screenshot is not a PNG");
  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const idat = [];

  while (offset < buffer.length) {
    assert(offset + 8 <= buffer.length, "truncated PNG chunk header");
    const length = buffer.readUInt32BE(offset);
    const type = buffer.subarray(offset + 4, offset + 8).toString("ascii");
    const dataStart = offset + 8;
    const dataEnd = dataStart + length;
    assert(dataEnd + 4 <= buffer.length, `truncated PNG chunk ${type}`);
    const data = buffer.subarray(dataStart, dataEnd);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
    } else if (type === "IDAT") {
      idat.push(data);
    } else if (type === "IEND") {
      break;
    }
    offset = dataEnd + 4;
  }

  assert(width > 0 && height > 0, "PNG did not expose dimensions");
  assert(bitDepth === 8, `unsupported PNG bit depth ${bitDepth}`);
  const channelsByColorType = { 0: 1, 2: 3, 4: 2, 6: 4 };
  const channels = channelsByColorType[colorType];
  assert(channels, `unsupported PNG color type ${colorType}`);
  assert(idat.length > 0, "PNG has no image data");

  const inflated = inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const bpp = channels;
  const pixels = Buffer.alloc(stride * height);
  let inputOffset = 0;

  for (let y = 0; y < height; y += 1) {
    const filter = inflated[inputOffset];
    inputOffset += 1;
    const rowOffset = y * stride;
    for (let x = 0; x < stride; x += 1) {
      const raw = inflated[inputOffset];
      inputOffset += 1;
      const left = x >= bpp ? pixels[rowOffset + x - bpp] : 0;
      const up = y > 0 ? pixels[rowOffset - stride + x] : 0;
      const upLeft = y > 0 && x >= bpp ? pixels[rowOffset - stride + x - bpp] : 0;
      let prediction = 0;
      if (filter === 1) prediction = left;
      else if (filter === 2) prediction = up;
      else if (filter === 3) prediction = Math.floor((left + up) / 2);
      else if (filter === 4) prediction = paethPredictor(left, up, upLeft);
      else assert(filter === 0, `unsupported PNG row filter ${filter}`);
      pixels[rowOffset + x] = (raw + prediction) & 0xff;
    }
  }

  const colors = new Set();
  let minLuma = 255;
  let maxLuma = 0;
  const stepX = Math.max(1, Math.floor(width / 96));
  const stepY = Math.max(1, Math.floor(height / 96));
  for (let y = 0; y < height; y += stepY) {
    for (let x = 0; x < width; x += stepX) {
      const pixelOffset = y * stride + x * channels;
      let r = pixels[pixelOffset];
      let g = pixels[pixelOffset];
      let b = pixels[pixelOffset];
      if (colorType === 2 || colorType === 6) {
        r = pixels[pixelOffset];
        g = pixels[pixelOffset + 1];
        b = pixels[pixelOffset + 2];
      }
      colors.add(`${r},${g},${b}`);
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      minLuma = Math.min(minLuma, luma);
      maxLuma = Math.max(maxLuma, luma);
    }
  }

  return {
    width,
    height,
    sampledColors: colors.size,
    luminanceRange: Number((maxLuma - minLuma).toFixed(2)),
  };
}

async function inspectScreenshot(report, stepName, label) {
  const step = getStep(report, stepName);
  const resolved = resolveScreenshotPath(step.screenshot);
  const buffer = await readFile(resolved);
  const info = parsePng(buffer);
  const fileStat = await stat(resolved);
  assert(fileStat.size > 15000, `${label} screenshot is too small to be credible (${fileStat.size} bytes)`);
  assert(info.width >= 900, `${label} screenshot width is too small (${info.width})`);
  assert(info.height >= 600, `${label} screenshot height is too small (${info.height})`);
  assert(info.sampledColors >= 24, `${label} screenshot appears visually blank or collapsed`);
  assert(info.luminanceRange >= 20, `${label} screenshot lacks enough contrast to prove display`);
  return {
    label,
    step: stepName,
    originalPath: step.screenshot,
    resolvedPath: resolved,
    bytes: fileStat.size,
    ...info,
  };
}

async function runCheck(id, domain, fn) {
  try {
    return { id, domain, status: "PASS", evidence: await fn() };
  } catch (error) {
    return { id, domain, status: "FAIL", error: error.message || String(error) };
  }
}

async function main() {
  const [
    human,
    enterprise,
    p7,
    coverage,
    gauntlet,
    assemblyFidelity,
    cubeBuffer,
    enterpriseRunner,
    findingsSource,
    catalogSource,
    costPdfSource,
    materialSource,
  ] = await Promise.all([
    readJson(files.human),
    readJson(files.enterprise),
    readJson(files.p7),
    readJson(files.coverage),
    readJson(files.gauntlet),
    readJson(files.assemblyFidelity),
    readFile(files.cube),
    readFile(files.enterpriseRunner, "utf8"),
    readFile(files.findings, "utf8"),
    readFile(files.catalog, "utf8"),
    readFile(files.costPdf, "utf8"),
    readFile(files.materialLibrary, "utf8"),
  ]);

  const portfolio = enterprise.evidence?.portfolio || {};

  const checks = [
    await runCheck("REPORT-CLEAN-001", "Upstream browser evidence", async () => {
      reportIsClean(human, "human web journey");
      reportIsClean(enterprise, "enterprise CAD org journey");
      reportIsClean(p7, "P7 role/failure journey");
      assert(coverage.status === "PASS", "journey coverage did not pass");
      assert(coverage.requiredBranches === coverage.coveredBranches, "journey coverage is incomplete");
      assert(gauntlet.status === "PASS", "synthetic enterprise gauntlet did not pass");
      return {
        humanSteps: human.steps.length,
        enterpriseSteps: enterprise.steps.length,
        p7Steps: p7.steps.length,
        requiredBranches: coverage.requiredBranches,
        gauntletScenarios: gauntlet.scenarios.length,
      };
    }),

    await runCheck("INPUT-INTEGRITY-001", "CAD fixture and answer inputs", async () => {
      const cubeSha256 = createHash("sha256").update(cubeBuffer).digest("hex");
      assert(cubeSha256 === expected.cubeSha256, `cube.step hash drifted: ${cubeSha256}`);
      assert(cubeBuffer.length === expected.cubeBytes, `cube.step byte length drifted: ${cubeBuffer.length}`);
      assert(enterprise.evidence?.meshHash === expected.cubeSha256, "enterprise mesh hash did not match cube.step");
      assert(portfolio.mesh_hash === expected.cubeSha256, "portfolio evidence did not carry the verified mesh hash");
      assert(portfolio.filename === "cube.step", `verified filename drifted: ${portfolio.filename}`);
      return {
        filename: portfolio.filename,
        bytes: cubeBuffer.length,
        sha256: cubeSha256,
        meshHash: enterprise.evidence.meshHash,
      };
    }),

    await runCheck("METHODOLOGY-HONESTY-001", "Methodology and caveat fidelity", async () => {
      contains(findingsSource, "assumption band, not a validated quote", "estimate.confidence.validated = false");
      contains(costPdfSource, "assumption-based, not yet validated", "never");
      matches(catalogSource, /validated["`]? only when/i, /not\s+reachable[\s\S]{0,80}today/i);
      contains(materialSource, "\"validated\": False", "never flips a decision to ``validated``");
      assert(enterprise.evidence?.rateCard?.source === "governed_rate_card", "rate card source was not governed");
      assert(enterprise.evidence?.rateCard?.validated === false, "governed rate card was mislabeled validated");
      assert(enterprise.evidence?.groundTruth?.n_real === 4, "ground-truth n_real drifted");
      assert(enterprise.evidence?.groundTruth?.min_real === 8, "ground-truth validation floor drifted");
      return {
        rateCardSource: enterprise.evidence.rateCard.source,
        rateCardValidated: enterprise.evidence.rateCard.validated,
        groundTruth: enterprise.evidence.groundTruth,
        caveatSources: ["findings.ts", "cost_pdf_service.py", "catalog.ts", "material_library_service.py"],
      };
    }),

    await runCheck("CALCULATION-FIDELITY-001", "Cost and procurement math", async () => {
      const unitCost = number(portfolio.annualized_unit_cost_usd, "portfolio.annualized_unit_cost_usd");
      const basisQuantity = number(portfolio.annualized_unit_cost_qty, "portfolio.annualized_unit_cost_qty");
      const annualVolume = number(portfolio.annual_volume, "portfolio.annual_volume");
      const annualized = number(portfolio.annualized_cost_usd, "portfolio.annualized_cost_usd");
      const expectedAnnualized = unitCost * annualVolume;
      assert(annualVolume === expected.annualVolume, `annual volume drifted: ${annualVolume}`);
      assert(basisQuantity === annualVolume, `annualized basis quantity drifted: ${basisQuantity}`);
      assert(portfolio.annualized_unit_cost_basis === "decision.recommendation", "annualized basis was not the engine recommendation");
      assert(approxEqual(annualized, expectedAnnualized), `annualized cost mismatch: ${annualized} vs ${expectedAnnualized}`);
      assert(
        approxEqual(number(portfolio.expected_annualized_cost_usd, "portfolio.expected_annualized_cost_usd"), expectedAnnualized),
        "recorded expected annualized cost does not match unit * volume"
      );
      assert(portfolio.withheld_before_volume === true, "portfolio did not prove annualized exposure was withheld before volume");
      assert(/no declared annual_volume/i.test(portfolio.withheld_reason || ""), "withheld reason does not explain missing volume");
      assert(portfolio.withheld_until_exact_reverification === true, "portfolio did not withhold the unmatched declared quantity");
      assert(/re-verify this CAD/i.test(portfolio.exact_reverification_reason || ""), "portfolio did not record the exact-quantity recovery step");
      assert(
        annualized >= expected.procurementThresholdsUsd.engineerSelfServe,
        "annualized exposure did not exceed the engineer self-serve threshold"
      );
      assert(
        annualized < expected.procurementThresholdsUsd.sourcingManager,
        "annualized exposure did not remain in the sourcing-manager approval band"
      );
      return {
        exactUnitCostUsd: unitCost,
        exactBasisQuantity: basisQuantity,
        annualVolume,
        annualizedCostUsd: annualized,
        expectedAnnualizedCostUsd: expectedAnnualized,
        withheldBeforeVolume: portfolio.withheld_before_volume,
        requiredApproval: "sourcing_manager",
        engineerSelfServeThresholdUsd: expected.procurementThresholdsUsd.engineerSelfServe,
        sourcingManagerThresholdUsd: expected.procurementThresholdsUsd.sourcingManager,
      };
    }),

    await runCheck("ENVIRONMENT-CONTEXT-001", "Service environment and org context", async () => {
      contains(enterpriseRunner, "serviceEnvironment = {", "max_temp_c: 120", "sour_service: true", "pressure_bar: 350");
      assert(portfolio.context_provenance === "user", `context provenance drifted: ${portfolio.context_provenance}`);
      assert(portfolio.parent_assembly === "Cryogenic pump skid", `parent assembly drifted: ${portfolio.parent_assembly}`);
      assert(portfolio.units_per_parent === 2, `units per parent drifted: ${portfolio.units_per_parent}`);
      assert(
        portfolio.service_environment?.max_temp_c === expected.serviceEnvironment.max_temp_c,
        "service max_temp_c did not survive artifact evidence"
      );
      assert(
        portfolio.service_environment?.sour_service === expected.serviceEnvironment.sour_service,
        "service sour_service did not survive artifact evidence"
      );
      assert(
        portfolio.service_environment?.pressure_bar === expected.serviceEnvironment.pressure_bar,
        "service pressure_bar did not survive artifact evidence"
      );
      return {
        program: portfolio.program,
        parentAssembly: portfolio.parent_assembly,
        unitsPerParent: portfolio.units_per_parent,
        contextProvenance: portfolio.context_provenance,
        serviceEnvironment: portfolio.service_environment,
      };
    }),

    await runCheck("MACHINE-TRUTH-001", "Machine floor and calibration truth", async () => {
      const machines = enterprise.evidence?.machineFloor || [];
      assert(machines.length === Object.keys(expected.machineRates).length, `machine count drifted: ${machines.length}`);
      for (const machine of machines) {
        const expectedMachine = expected.machineRates[machine.name];
        assert(expectedMachine, `unexpected machine in evidence: ${machine.name}`);
        assert(machine.process === expectedMachine.process, `${machine.name} process drifted`);
        assert(machine.rate === expectedMachine.rate, `${machine.name} rate drifted`);
        assert(machine.provenance === "user", `${machine.name} provenance was not user`);
      }
      assert(enterprise.evidence?.groundTruth?.total === 4, "ground-truth total drifted");
      assert(enterprise.evidence?.groundTruth?.n_real === 4, "ground-truth real count drifted");
      assert(enterprise.evidence?.groundTruth?.min_real === 8, "ground-truth validation floor drifted");
      return {
        machines,
        groundTruth: enterprise.evidence.groundTruth,
      };
    }),

    await runCheck("DISPLAY-FIDELITY-001", "Part and environment display screenshots", async () => {
      const screenshots = [];
      screenshots.push(
        await inspectScreenshot(human, "Verify processes a real STEP file upload", "human STEP result")
      );
      screenshots.push(
        await inspectScreenshot(
          enterprise,
          "CAD engineer verifies a real STEP file in a declared service world",
          "enterprise STEP result"
        )
      );
      screenshots.push(
        await inspectScreenshot(
          enterprise,
          "portfolio computes exact server-side exposure after declared-volume re-verification",
          "portfolio math result"
        )
      );
      screenshots.push(
        await inspectScreenshot(
          enterprise,
          "Verify stage renders declared parent context in product UI",
          "declared parent context product stage"
        )
      );
      screenshots.push(
        await inspectScreenshot(
          enterprise,
          "Programs UI and cost history show the verified enterprise part",
          "program and cost-history result"
        )
      );
      screenshots.push(
        await inspectScreenshot(
          enterprise,
          "Verify UI shows declared machines and governed truth honestly",
          "machine and calibration result"
        )
      );
      return {
        screenshotCount: screenshots.length,
        screenshots,
        limitation: "PNG sanity proves nonblank varied browser render evidence; it is not a third-party geometric certification.",
      };
    }),

    await runCheck("ASSEMBLY-CONTEXT-FIDELITY-001", "Populated assembly and environment render fidelity", async () => {
      assert(assemblyFidelity.status === "PASS", `assembly fidelity status ${assemblyFidelity.status}`);
      getStep(enterprise, "Verify stage renders declared parent context in product UI");
      assert(
        enterprise.evidence?.productStageContext?.parent_assembly === portfolio.parent_assembly,
        "product Verify stage did not render the same parent assembly as portfolio context"
      );
      assert(/service world/i.test(enterprise.evidence?.productStageContext?.strip || ""), "product Verify stage did not expose service world");
      assert((assemblyFidelity.cases || []).length >= 2, "assembly/context corpus does not cover multiple fixtures");
      assert(/parent assembly identity/.test(assemblyFidelity.boundary || ""), "assembly boundary lost parent context");
      assert(/not customer proprietary CAD/.test(assemblyFidelity.boundary || ""), "assembly boundary lost external truth line");
      const evidence = [];
      for (const item of assemblyFidelity.cases || []) {
        assert(item.status === "PASS", `${item.fixtureId} did not pass`);
        assert(item.parentAssemblyId, `${item.fixtureId} parent assembly id missing`);
        assert(item.partId, `${item.fixtureId} part id missing`);
        assert(item.placement?.maxAnchorErrorMm <= item.placement?.toleranceMm, `${item.fixtureId} placement tolerance failed`);
        assert(item.render?.after?.full?.nonBackgroundRatio >= 0.18, `${item.fixtureId} seated render is mostly blank`);
        assert(item.render?.visualDelta?.changedSampledPixels > 0, `${item.fixtureId} seat interaction did not change pixels`);
        assert(item.screenshots?.before && item.screenshots?.after, `${item.fixtureId} screenshots missing`);
        evidence.push({
          fixtureId: item.fixtureId,
          parentAssemblyId: item.parentAssemblyId,
          partId: item.partId,
          maxAnchorErrorMm: item.placement.maxAnchorErrorMm,
          toleranceMm: item.placement.toleranceMm,
          visualDelta: item.render.visualDelta,
          screenshots: item.screenshots,
        });
      }
      return {
        fixtureCases: evidence.length,
        evidence,
        productStageContext: enterprise.evidence.productStageContext,
        limitation: "Synthetic fixture-driven assembly render proof; it does not certify proprietary customer assemblies or native CAD kernels.",
      };
    }),

    await runCheck("INTERACTION-FIDELITY-001", "Human-flow and enterprise-control interactions", async () => {
      const requiredSteps = [
        [human, "command palette jumps to Triage"],
        [human, "notifications inbox opens and derives state"],
        [enterprise, "Developer settings creates and reveals an API key exactly once"],
        [p7, "cost-decision detail approves and reopens from UI"],
        [p7, "cost-decision detail shows stale warning after governed rate publish"],
        [p7, "low-role admin API is denied"],
      ];
      for (const [report, stepName] of requiredSteps) getStep(report, stepName);
      assert(p7.evidence?.lowRoleAdminUsers?.status === 403, "viewer admin denial status drifted");
      assert(p7.evidence?.governanceApproval?.reopened_status === "unreviewed", "approval reopen status drifted");
      assert(/rate_library_published/.test(p7.evidence?.governanceStale?.stale_reason || ""), "stale reason drifted");
      return {
        requiredInteractions: requiredSteps.map(([, stepName]) => stepName),
        viewerAdminStatus: p7.evidence.lowRoleAdminUsers.status,
        reopenedStatus: p7.evidence.governanceApproval.reopened_status,
        staleReason: p7.evidence.governanceStale.stale_reason,
      };
    }),
  ];

  const failed = checks.filter((check) => check.status !== "PASS");
  const data = {
    status: failed.length === 0 ? "PASS" : "NEEDS_FIXES",
    generatedAt: new Date().toISOString(),
    runId,
    boundary:
      "This verifies the simulated enterprise lab output fidelity. It does not certify a live Exxon, SAP, PLM, supplier, SSO provider, auditor, or procurement counterparty.",
    checks,
    failed,
  };

  await mkdir(outputRoot, { recursive: true });
  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));

  console.log(
    JSON.stringify(
      {
        status: data.status,
        checks: checks.length,
        passed: checks.length - failed.length,
        failed: failed.map((item) => ({ id: item.id, error: item.error })),
        report: artifacts.md,
      },
      null,
      2
    )
  );

  if (data.status !== "PASS") process.exitCode = 1;
}

function markdown(data) {
  const rows = data.checks
    .map((check) => `| ${check.status} | ${check.id} | ${check.domain} | ${check.error || "pass"} |`)
    .join("\n");

  return `# Enterprise Answer Fidelity

- Date: ${data.runId}
- Status: ${data.status}
- Boundary: ${data.boundary}

## Checks

| Result | ID | Domain | Evidence |
| --- | --- | --- | --- |
${rows}

## Failed

\`\`\`json
${JSON.stringify(data.failed, null, 2)}
\`\`\`
`;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
