import { createRequire } from "node:module";
import { createHash, randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { configuredClientIp } from "./run-scoped-client-ip.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");
const { strFromU8, unzipSync, zipSync } = require("fflate");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(outputRoot, "screenshots", `training-guide-e2e-${runId}`);
const reportJson = path.join(outputRoot, `training-guide-e2e-${runId}.json`);
const reportMd = path.join(outputRoot, `qa-report-training-guide-e2e-${runId}.md`);
const zipPath = path.join(outputRoot, `training-guide-rfq-${runId}.zip`);
const batchZipPath = path.join(outputRoot, `training-guide-batch-${runId}.zip`);
const batchCsvPath = path.join(outputRoot, `training-guide-batch-${runId}.csv`);
const cadUploadTimeoutMs = Number.parseInt(process.env.E2E_CAD_UPLOAD_TIMEOUT_MS || "150000", 10);
const cubePath = path.join(repoRoot, "backend", "tests", "assets", "cube.step");
const pinnedCube = {
  bytes: 19_030,
  sha256: "76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a",
  bboxMmSorted: [10, 15, 20],
  // The cost-report/browser contract serializes geometry to two decimal places.
  volumeCm3: 2.72,
  surfaceAreaCm2: 14.32,
  quantities: [1, 100, 1000, 2000, 5000, 10000],
  estimates: 48,
  makeNowProcess: "fdm",
  crossoverQty: 923,
  recommendation: {
    1: ["fdm", 30.0],
    100: ["mjf", 3.62],
    1000: ["mjf", 3.48],
    2000: ["mjf", 3.48],
    5000: ["mjf", 3.48],
    10000: ["mjf", 3.48],
  },
};

export function redactRequestUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return `${url.origin}${url.pathname}`;
  } catch {
    return "<invalid-url>";
  }
}

export function recoverableUploadAbortKey(method, rawUrl, appUrl = baseUrl) {
  let url;
  let appOrigin;
  try {
    url = new URL(rawUrl);
    appOrigin = new URL(appUrl).origin;
  } catch {
    return null;
  }
  if (
    method === "PUT" &&
    url.origin !== appOrigin &&
    url.pathname.includes("/direct-uploads/") &&
    url.searchParams.has("uploadId") &&
    url.searchParams.has("partNumber")
  ) {
    return [
      "multipart-part",
      url.origin,
      url.pathname,
      url.searchParams.get("uploadId"),
      url.searchParams.get("partNumber"),
    ].join("|");
  }
  if (
    method === "POST" &&
    url.origin === appOrigin &&
    /^\/api\/proxy\/uploads\/[A-Z0-9]+\/complete$/i.test(url.pathname)
  ) {
    return ["multipart-complete", url.origin, url.pathname].join("|");
  }
  return null;
}

export function reconcileSuccessfulUploadAborts(pending, successfulResponses) {
  const expected = [];
  const failures = [];
  for (const item of pending) {
    const recoveredStatus = successfulResponses.get(item.key) ?? null;
    if (recoveredStatus != null) {
      expected.push({ ...item.evidence, recoveredStatus });
    } else {
      failures.push({ ...item.evidence, reason: "no exact matching successful HTTP response" });
    }
  }
  return { expected, failures };
}
const batchCsvHeaders = [
  "filename",
  "status",
  "verdict",
  "best_process",
  "issue_count",
  "duration_ms",
  "analysis_url",
  "error",
];
const rfqLineItemHeaders = [
  "decision_id",
  "filename",
  "approval_status",
  "is_stale",
  "unvalidated_confidence",
  "make_now_process",
  "crossover_qty",
  "manifest_part_id",
  "program",
  "raw_cad_included",
];
const costDriverHeaders = [
  "process",
  "material",
  "quantity",
  "unit_cost_usd",
  "fixed_cost_usd",
  "variable_cost_usd",
  "est_error_band_pct",
  "confidence_low_usd",
  "confidence_high_usd",
  "confidence_label",
  "confidence_validated",
  "dfm_ready",
  "approval_status",
  "approved_by_user_id",
  "approved_at",
  "approval_note",
  "user_disposition",
  "user_disposition_label",
  "disposition_note",
  "disposition_updated_at",
  "disposition_updated_by_user_id",
  "line_items",
];
const durableCostFields = [
  "filename",
  "status",
  "reason",
  "geometry",
  "material_class",
  "quantities",
  "estimates",
  "engine_feasibility",
  "routing",
  "notes",
  "assumptions",
  "decision",
  "verification",
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function approxEqual(actual, expected, tolerance) {
  return Number.isFinite(actual) && Math.abs(actual - expected) <= tolerance;
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stable(value[key])])
    );
  }
  return value;
}

function assertJsonEqual(actual, expected, label) {
  const actualJson = JSON.stringify(stable(actual));
  const expectedJson = JSON.stringify(stable(expected));
  assert(actualJson === expectedJson, `${label} did not round-trip exactly`);
}

function assertHeaders(actual, expected, label) {
  assert(
    JSON.stringify(actual) === JSON.stringify(expected),
    `${label} headers were ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`
  );
}

/** RFC 4180-shaped parser kept local so artifact assertions do not depend on app code. */
function parseCsv(text, label) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"' && field.length === 0) {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field.endsWith("\r") ? field.slice(0, -1) : field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }

  assert(!quoted, `${label} ended inside a quoted CSV field`);
  if (field.length > 0 || row.length > 0) {
    row.push(field.endsWith("\r") ? field.slice(0, -1) : field);
    rows.push(row);
  }
  assert(rows.length >= 2, `${label} must contain a header and at least one data row`);
  const headers = rows[0];
  assert(new Set(headers).size === headers.length, `${label} contains duplicate headers`);
  const records = rows.slice(1).map((values, index) => {
    assert(
      values.length === headers.length,
      `${label} row ${index + 2} has ${values.length} columns, expected ${headers.length}`
    );
    return Object.fromEntries(headers.map((header, column) => [header, values[column]]));
  });
  return { headers, records };
}

function zipText(entries, name) {
  assert(entries[name], `RFQ ZIP is missing ${name}`);
  return strFromU8(entries[name]);
}

function zipJson(entries, name) {
  const text = zipText(entries, name);
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${name} is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function isProxyResponse(response, method, pathname) {
  const url = new URL(response.url());
  return response.request().method() === method && url.pathname === `/api/proxy${pathname}`;
}

function assertCostReport(report) {
  assert(report?.status === "OK", `cost status was ${report?.status || "missing"}`);
  assert(report.filename === "cube.step", `cost filename was ${report.filename}`);
  assert(report.saved?.id, "cost response did not expose a durable decision id");
  assert(
    report.saved.url === `/api/v1/cost-decisions/${report.saved.id}`,
    `saved decision URL did not match id ${report.saved.id}`
  );

  const geometry = report.geometry || {};
  const sortedBbox = [...(geometry.bbox_mm || [])].sort((a, b) => a - b);
  assert(sortedBbox.length === 3, "cost geometry did not contain a three-axis bounding box");
  pinnedCube.bboxMmSorted.forEach((expected, index) => {
    assert(
      approxEqual(sortedBbox[index], expected, 0.1),
      `cube bbox axis ${index} was ${sortedBbox[index]}, expected ${expected} ±0.1 mm`
    );
  });
  assert(
    approxEqual(geometry.volume_cm3, pinnedCube.volumeCm3, 0.005),
    `cube volume was ${geometry.volume_cm3} cm³, expected ${pinnedCube.volumeCm3} ±0.005`
  );
  assert(
    approxEqual(geometry.surface_area_cm2, pinnedCube.surfaceAreaCm2, 0.02),
    `cube area was ${geometry.surface_area_cm2} cm², expected ${pinnedCube.surfaceAreaCm2} ±0.02`
  );
  assert(geometry.watertight === true, "cube geometry was not watertight");
  assert(report.decision?.make_now_process === pinnedCube.makeNowProcess, `make-now process was ${report.decision?.make_now_process}`);
  assertJsonEqual(report.quantities, pinnedCube.quantities, "pinned cube quantity ladder");
  assert(report.estimates?.length === pinnedCube.estimates, `pinned cube had ${report.estimates?.length} estimates, expected ${pinnedCube.estimates}`);
  assert(approxEqual(report.decision.crossover_qty, pinnedCube.crossoverQty, 0.001), `crossover was ${report.decision.crossover_qty}`);

  let maxLineItemDelta = 0;
  for (const estimate of report.estimates) {
    assert(report.quantities.includes(estimate.quantity), `estimate quantity ${estimate.quantity} was outside the quantity ladder`);
    assert(estimate.process && estimate.material, "cost estimate lost process or material");
    assert(Number.isFinite(estimate.unit_cost_usd), "cost estimate unit price was not finite");
    const lineItemSum = Object.values(estimate.line_items || {}).reduce((sum, value) => sum + Number(value), 0);
    const lineItemDelta = Math.abs(lineItemSum - estimate.unit_cost_usd);
    maxLineItemDelta = Math.max(maxLineItemDelta, lineItemDelta);
    assert(
      lineItemDelta < 0.02,
      `${estimate.process} qty ${estimate.quantity} line items differ from unit cost by ${lineItemDelta}`
    );
    assert(Array.isArray(estimate.drivers) && estimate.drivers.length > 0, `${estimate.process} qty ${estimate.quantity} has no cost drivers`);
    for (const driver of estimate.drivers) {
      assert(driver.name && driver.provenance && driver.source, `${estimate.process} qty ${estimate.quantity} has an ungrounded driver`);
    }
    const confidence = estimate.confidence;
    assert(confidence, `${estimate.process} qty ${estimate.quantity} has no confidence band`);
    assert(
      confidence.low_usd <= confidence.point_usd && confidence.point_usd <= confidence.high_usd,
      `${estimate.process} qty ${estimate.quantity} confidence point is outside its bounds`
    );
    assert(
      approxEqual(confidence.point_usd, estimate.unit_cost_usd, 0.02),
      `${estimate.process} qty ${estimate.quantity} confidence point differs from unit cost`
    );
    assert(confidence.label && typeof confidence.validated === "boolean", `${estimate.process} qty ${estimate.quantity} confidence provenance is incomplete`);
  }

  for (const quantity of report.quantities) {
    const recommendation = report.decision.recommendation?.[String(quantity)];
    assert(recommendation, `decision has no recommendation for quantity ${quantity}`);
    const sourceEstimate = report.estimates.find(
      (estimate) => estimate.quantity === quantity && estimate.process === recommendation.process
    );
    assert(sourceEstimate, `quantity ${quantity} recommendation has no matching cost estimate`);
    assert(
      approxEqual(sourceEstimate.unit_cost_usd, recommendation.unit_cost_usd, 0.001),
      `quantity ${quantity} recommendation price differs from its estimate`
    );
    const [expectedProcess, expectedUnitCost] = pinnedCube.recommendation[quantity];
    assert(recommendation.process === expectedProcess, `quantity ${quantity} process was ${recommendation.process}, expected ${expectedProcess}`);
    assert(approxEqual(recommendation.unit_cost_usd, expectedUnitCost, 0.001), `quantity ${quantity} unit cost was ${recommendation.unit_cost_usd}, expected ${expectedUnitCost}`);
  }

  return {
    decisionId: report.saved.id,
    makeNowProcess: report.decision.make_now_process,
    quantities: report.quantities,
    estimates: report.estimates.length,
    geometry: {
      bboxMm: geometry.bbox_mm,
      volumeCm3: geometry.volume_cm3,
      surfaceAreaCm2: geometry.surface_area_cm2,
      watertight: geometry.watertight,
    },
    maxLineItemDeltaUsd: Number(maxLineItemDelta.toFixed(6)),
  };
}

function assertDurableCostEqual(live, persisted) {
  for (const field of durableCostFields) {
    assertJsonEqual(persisted[field] ?? null, live[field] ?? null, `durable cost field ${field}`);
  }
}

function uniqueEmail() {
  return `training-guide-${Date.now()}-${process.pid}-${randomBytes(4).toString("hex")}@example.com`;
}

function slug(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
}

function markdownReport(data) {
  const stepRows = data.steps.map((item) => {
    const evidence = item.evidence
      ? JSON.stringify(item.evidence).slice(0, 240)
      : item.error || "";
    return `| ${item.status} | ${item.name} | ${item.durationMs} | ${evidence.replaceAll("|", "\\|")} |`;
  }).join("\n");
  const oracleJson = JSON.stringify(data.outcomeOracles, null, 2);
  return `# Training guide E2E

- Status: ${data.status}
- Steps: ${data.steps.length - data.failed.length}/${data.steps.length}
- Console errors: ${data.consoleErrors.length}
- Request failures: ${data.requestFailures.length}
- Reconciled successful upload aborts: ${data.expectedRequestAborts.length}
- Fatal error: ${data.fatalError || "none"}
- Batch CSV: ${data.batchCsv}
- RFQ ZIP: ${data.rfqZip}

## Browser steps

| Result | Journey | Duration ms | Evidence |
| --- | --- | ---: | --- |
${stepRows}

## Outcome-oracle evidence

The JSON below is emitted only after the browser reopened/refreshed durable records and the downloaded artifacts passed semantic validation.

\`\`\`json
${oracleJson}
\`\`\`
`;
}

async function main() {
  await mkdir(screenshotDir, { recursive: true });
  const cubeBytes = await readFile(cubePath);
  const cubeSha256 = sha256(cubeBytes);
  assert(cubeBytes.length === pinnedCube.bytes, `cube.step was ${cubeBytes.length} bytes, expected ${pinnedCube.bytes}`);
  assert(cubeSha256 === pinnedCube.sha256, `cube.step SHA-256 drifted to ${cubeSha256}`);
  await writeFile(batchZipPath, zipSync({ "cube.step": new Uint8Array(cubeBytes) }));
  const browser = await pw.chromium.launch({ channel: "chrome", headless: true }).catch(() =>
    pw.chromium.launch({ headless: true })
  );
  const context = await browser.newContext({
    baseURL: baseUrl,
    viewport: { width: 1440, height: 960 },
    reducedMotion: "reduce",
    acceptDownloads: true,
    // The hardened production auth boundary accepts client identity only from
    // the first-party ingress. Fly and the regulated ingress provide one of
    // these trusted headers in deployment; direct localhost traffic does not,
    // so the human-sim runner supplies the same ingress contract explicitly.
    extraHTTPHeaders: {
      "x-real-ip": configuredClientIp(runId, "training-guide"),
    },
  });
  const page = await context.newPage();
  const steps = [];
  const consoleErrors = [];
  const requestFailures = [];
  const pendingSuccessAborts = [];
  const successfulAbortableResponses = new Map();
  const expectedRequestAborts = [];
  const screenshots = [];

  page.on("console", (message) => {
    if (message.type() === "error" && !/favicon\.ico|ResizeObserver loop limit exceeded/i.test(message.text())) {
      consoleErrors.push({ url: page.url(), text: message.text() });
    }
  });
  page.on("pageerror", (error) => consoleErrors.push({ url: page.url(), text: error.message }));
  page.on("response", (response) => {
    const key = recoverableUploadAbortKey(
      response.request().method(),
      response.url(),
      baseUrl,
    );
    if (key && response.status() >= 200 && response.status() < 300) {
      successfulAbortableResponses.set(key, response.status());
    }
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    const error = request.failure()?.errorText || "request failed";
    if (/favicon\.ico|vercel\/speed-insights|\/_next\/webpack-hmr/i.test(url)) return;
    if (error === "net::ERR_ABORTED" && /[?&]_rsc=/.test(url)) return;
    const evidence = {
      method: request.method(),
      url: redactRequestUrl(url),
      error,
    };
    const key = recoverableUploadAbortKey(request.method(), url, baseUrl);
    if (error === "net::ERR_ABORTED" && key) {
      pendingSuccessAborts.push({ key, evidence });
      return;
    }
    requestFailures.push(evidence);
  });

  async function shot(name) {
    const file = path.join(screenshotDir, `${String(screenshots.length + 1).padStart(2, "0")}-${slug(name)}.png`);
    await page.screenshot({ path: file, fullPage: true });
    screenshots.push(file);
    return file;
  }

  async function step(name, fn) {
    const started = Date.now();
    try {
      const evidence = await fn();
      steps.push({ name, status: "PASS", durationMs: Date.now() - started, evidence });
      return evidence;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      steps.push({ name, status: "FAIL", durationMs: Date.now() - started, error: message, screenshot: await shot(`${name}-failure`) });
      throw error;
    }
  }

  const email = uniqueEmail();
  const password = "ProofShape123";
  const rfqTitle = `Training guide RFQ ${runId}`;
  const rfqSupplier = "Training guide supplier";
  const rfqNote = "Pinned cube decision for semantic RFQ package validation.";
  let liveCostReport = null;
  let durableCostDetail = null;
  let cadEvidence = null;
  let batchEvidence = null;
  let rfqPackage = null;
  let rfqArchiveEvidence = null;
  let fatalError = null;

  try {
    await step("zero-instruction signup reaches Day Zero", async () => {
      await page.goto("/signup", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(password);
      await page.getByRole("button", { name: /^Create account$/ }).click();
      await page.waitForURL((url) => url.pathname === "/verify", { timeout: 20_000 });
      await page.getByText("DAY ZERO SETUP").waitFor({ timeout: 12_000 });
      return { url: page.url(), screenshot: await shot("signup-day-zero") };
    });

    await step("real STEP verification creates a durable cost decision", async () => {
      await page.locator('button[title="Verify"]').click();
      const costResponsePromise = page.waitForResponse(
        (response) => isProxyResponse(response, "POST", "/validate/cost"),
        { timeout: cadUploadTimeoutMs }
      );
      await page.locator('input[type="file"][accept*=".stl"]').first().setInputFiles(cubePath);
      const costResponse = await costResponsePromise;
      assert(costResponse.ok(), `cost response returned HTTP ${costResponse.status()}`);
      liveCostReport = await costResponse.json();
      const costSummary = assertCostReport(liveCostReport);
      await page.waitForFunction(() => {
        const text = document.body.innerText;
        return /computed from POST \/validate\/cost|What it really takes|unit cost|bbox/i.test(text) && !/measuring geometry/i.test(text);
      }, null, { timeout: cadUploadTimeoutMs });
      const text = await page.locator("body").innerText();
      assert(!/Cost request failed|Validation failed|Network error|Geometry invalid|repair required/i.test(text), "STEP verification ended in an error state");
      assert(/cost-decision|unit cost|What it really takes/i.test(text), "durable cost evidence was not visible");
      const bboxLabel = liveCostReport.geometry.bbox_mm.map((value) => value.toFixed(1)).join(" × ");
      assert(text.includes(`${bboxLabel} mm`), `live Verify UI did not show the measured bbox ${bboxLabel} mm`);
      assert(text.includes(`${liveCostReport.geometry.volume_cm3.toFixed(2)} cm³`), "live Verify UI did not show the measured volume");
      assert(/watertight true/i.test(text), "live Verify UI did not show watertight true");
      assert(text.includes(pinnedCube.sha256), "live Verify UI did not show the exact source SHA-256");
      const liveScreenshot = await shot("verified-step-result");

      await page.goto("/cost-decisions", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await page.getByRole("heading", { name: "Cost history" }).waitFor({ timeout: 12_000 });
      const historyRow = page.getByRole("row").filter({ hasText: "cube.step" }).first();
      await historyRow.waitFor({ timeout: 15_000 });
      const detailResponsePromise = page.waitForResponse(
        (response) => isProxyResponse(response, "GET", `/cost-decisions/${liveCostReport.saved.id}`),
        { timeout: 20_000 }
      );
      await historyRow.click();
      await page.waitForURL(
        (url) => url.pathname === `/cost-decisions/${liveCostReport.saved.id}`,
        { timeout: 12_000 }
      );
      const detailResponse = await detailResponsePromise;
      assert(detailResponse.ok(), `durable cost detail returned HTTP ${detailResponse.status()}`);
      durableCostDetail = await detailResponse.json();
      assert(durableCostDetail.id === liveCostReport.saved.id, "reopened decision id differs from the live saved id");
      assert(durableCostDetail.filename === "cube.step", "reopened decision filename differs from the upload");
      assert(durableCostDetail.mesh_hash === pinnedCube.sha256, `reopened decision source hash was ${durableCostDetail.mesh_hash}`);
      assert(durableCostDetail.make_now_process === liveCostReport.decision.make_now_process, "reopened make-now process drifted");
      assertJsonEqual(durableCostDetail.quantities, liveCostReport.quantities, "reopened quantity ladder");
      assertDurableCostEqual(liveCostReport, durableCostDetail.result);
      let detailText = await page.locator("body").innerText();
      assert(/Decision governance/i.test(detailText), "reopened decision did not render governance state");
      assert(/Make by/i.test(detailText), "reopened decision did not render its recommendation");
      assert(/Recommendation by quantity/i.test(detailText), "reopened decision did not render the quantity ladder");
      assert(/Cost drivers/i.test(detailText), "reopened decision did not render cost drivers");
      const reopenedScreenshot = await shot("cost-decision-reopened");

      const refreshResponsePromise = page.waitForResponse(
        (response) => isProxyResponse(response, "GET", `/cost-decisions/${liveCostReport.saved.id}`),
        { timeout: 20_000 }
      );
      await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
      const refreshResponse = await refreshResponsePromise;
      assert(refreshResponse.ok(), `refreshed cost detail returned HTTP ${refreshResponse.status()}`);
      const refreshedDetail = await refreshResponse.json();
      assertJsonEqual(refreshedDetail, durableCostDetail, "refreshed durable cost decision");
      detailText = await page.locator("body").innerText();
      assert(/Recommendation by quantity/i.test(detailText), "refreshed decision lost its quantity recommendations");

      cadEvidence = {
        fixture: { bytes: cubeBytes.length, sha256: cubeSha256 },
        ...costSummary,
        durableRecord: {
          id: durableCostDetail.id,
          route: `/cost-decisions/${durableCostDetail.id}`,
          approvalStatus: durableCostDetail.approval_status,
          fieldsCompared: durableCostFields,
          historyReopened: true,
          refreshExact: true,
        },
        screenshots: { live: liveScreenshot, reopened: reopenedScreenshot },
      };
      return cadEvidence;
    });

    await step("valid one-part ZIP batch completes and exports CSV", async () => {
      await page.goto("/batch", { waitUntil: "domcontentloaded", timeout: 30_000 });
      const zipInput = page.locator('input[type="file"][accept=".zip"]').first();
      await zipInput.setInputFiles(batchZipPath);
      await page.getByRole("button", { name: "Start batch" }).click();
      await page.waitForURL(/\/batch\/[A-Z0-9]+$/, { timeout: 20_000 });
      await page.waitForFunction(() => {
        const text = document.body.innerText;
        return /1\s*\/\s*1\s*\(100%\)/i.test(text) && /completed/i.test(text);
      }, null, { timeout: 180_000 });
      const text = await page.locator("body").innerText();
      assert(!/1 failed|Could not load progress|Failed to create batch/i.test(text), "batch finished with a visible failure");
      const batchPath = new URL(page.url()).pathname;
      const batchId = batchPath.split("/").filter(Boolean).at(-1);
      assert(/^[A-Z0-9]+$/.test(batchId || ""), `batch route did not expose a durable id: ${batchPath}`);

      async function readBatchUiRow({ requireCompleted = true } = {}) {
        await page.waitForFunction(() => {
          const body = document.body.innerText;
          return /1\s*\/\s*1\s*\(100%\)/i.test(body) && /completed/i.test(body) && /cube\.step/i.test(body);
        }, null, { timeout: 30_000 });
        const row = page.getByRole("row").filter({ hasText: "cube.step" }).first();
        await row.waitFor({ timeout: 12_000 });
        if (requireCompleted) {
          await row.getByText(/^Completed$/i).waitFor({ timeout: 12_000 });
        }
        const cells = row.getByRole("cell");
        assert((await cells.count()) >= 5, "batch item row did not expose the expected UI columns");
        const values = await cells.allInnerTexts();
        const viewLink = row.getByRole("link", { name: "View" });
        const hasView = await viewLink.isVisible().catch(() => false);
        if (requireCompleted) {
          assert(values[1].trim().toLowerCase() === "completed", `refreshed batch item status was ${values[1].trim()}`);
          assert(hasView, "completed batch item did not expose its View link");
        }
        return {
          filename: values[0].trim(),
          status: values[1].trim().toLowerCase(),
          priority: values[2].trim(),
          duration: values[3].trim(),
          viewHref: hasView ? await viewLink.getAttribute("href") : null,
        };
      }

      const preRefreshUiRow = await readBatchUiRow();
      assert(
        preRefreshUiRow.status === "completed",
        `terminal batch summary left the mounted item row at ${preRefreshUiRow.status}`,
      );
      await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
      const firstUiRow = await readBatchUiRow();
      assert(firstUiRow.filename === "cube.step", `batch UI filename was ${firstUiRow.filename}`);
      assert(firstUiRow.status === "completed", `batch UI status was ${firstUiRow.status}`);

      await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
      const refreshedUiRow = await readBatchUiRow();
      assertJsonEqual(refreshedUiRow, firstUiRow, "refreshed batch UI row");

      await page.getByRole("button", { name: /Back to batches/i }).click();
      await page.waitForURL((url) => url.pathname === "/batch", { timeout: 12_000 });
      const listRow = page.getByRole("row").filter({ hasText: batchId.slice(0, 12) }).first();
      await listRow.waitFor({ timeout: 15_000 });
      assert(/completed/i.test(await listRow.innerText()), "batch list did not preserve the completed status");
      await listRow.click();
      await page.waitForURL((url) => url.pathname === batchPath, { timeout: 12_000 });
      const reopenedUiRow = await readBatchUiRow();
      assertJsonEqual(reopenedUiRow, firstUiRow, "reopened batch UI row");

      const downloadPromise = page.waitForEvent("download", { timeout: 20_000 });
      await page.getByRole("button", { name: "Download CSV" }).click();
      const download = await downloadPromise;
      await download.saveAs(batchCsvPath);
      const file = await stat(batchCsvPath);
      assert(file.size > 20, `batch CSV was unexpectedly small (${file.size} bytes)`);
      const csvBytes = await readFile(batchCsvPath);
      const parsed = parseCsv(csvBytes.toString("utf8"), "batch results CSV");
      assertHeaders(parsed.headers, batchCsvHeaders, "batch results CSV");
      assert(parsed.records.length === 1, `batch CSV contained ${parsed.records.length} rows, expected one`);
      const csvRow = parsed.records[0];
      assert(csvRow.filename === firstUiRow.filename, `batch CSV filename ${csvRow.filename} differs from UI ${firstUiRow.filename}`);
      assert(csvRow.status.toLowerCase() === firstUiRow.status, `batch CSV status ${csvRow.status} differs from UI ${firstUiRow.status}`);
      assert(/^(pass|issues|fail)$/i.test(csvRow.verdict), `batch CSV verdict was ${csvRow.verdict}`);
      assert(csvRow.best_process.length > 0, "batch CSV best_process was empty for a completed item");
      assert(Number.isInteger(Number(csvRow.issue_count)) && Number(csvRow.issue_count) >= 0, `batch CSV issue_count was ${csvRow.issue_count}`);
      assert(Number(csvRow.duration_ms) > 0, `batch CSV duration_ms was ${csvRow.duration_ms}`);
      assert(
        `${(Number(csvRow.duration_ms) / 1000).toFixed(1)} s` === firstUiRow.duration,
        `batch CSV duration ${csvRow.duration_ms} ms differs from UI ${firstUiRow.duration}`
      );
      assert(/^\/api\/v1\/analyses\/[A-Z0-9]+$/.test(csvRow.analysis_url), `batch CSV analysis_url was ${csvRow.analysis_url}`);
      assert(firstUiRow.viewHref?.startsWith("/analyses/"), `batch UI View link was ${firstUiRow.viewHref}`);
      assert(csvRow.error === "", `completed batch CSV row contained error ${csvRow.error}`);

      batchEvidence = {
        id: batchId,
        route: batchPath,
        refreshExact: true,
        listReopenExact: true,
        preRefreshUiRow,
        uiRow: firstUiRow,
        csv: {
          path: batchCsvPath,
          bytes: file.size,
          sha256: sha256(csvBytes),
          headers: parsed.headers,
          row: csvRow,
        },
        screenshot: await shot("batch-complete-reopened"),
      };
      return batchEvidence;
    });

    await step("sourcing user generates an RFQ package from the saved decision", async () => {
      await page.goto("/rfq-packages", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await page.getByRole("heading", { name: "RFQ packages" }).waitFor({ timeout: 12_000 });
      await page.getByText("New package", { exact: true }).waitFor({ timeout: 12_000 });
      const decision = page.getByRole("checkbox", { name: /Include cube\.step in the RFQ package/i }).first();
      await decision.waitFor({ timeout: 15_000 });
      await decision.check();
      await page.getByPlaceholder("Pump RFQ package").fill(rfqTitle);
      await page.getByPlaceholder("optional").fill(rfqSupplier);
      await page.getByPlaceholder("Buyer note").fill(rfqNote);
      const createResponsePromise = page.waitForResponse(
        (response) => isProxyResponse(response, "POST", "/rfq-packages"),
        { timeout: 30_000 }
      );
      await page.getByRole("button", { name: /Generate package \(1\)/ }).click();
      const createResponse = await createResponsePromise;
      assert(createResponse.status() === 201, `RFQ create returned HTTP ${createResponse.status()}`);
      rfqPackage = (await createResponse.json()).package;
      assert(rfqPackage?.id, "RFQ create response did not expose a durable package id");
      assert(rfqPackage.title === rfqTitle, "RFQ create response title drifted");
      assert(rfqPackage.supplier_name === rfqSupplier, "RFQ create response supplier drifted");
      assert(rfqPackage.item_count === 1 && rfqPackage.items?.length === 1, "RFQ create response did not contain exactly one decision");
      assert(rfqPackage.items[0].decision.id === durableCostDetail.id, "RFQ create response linked a different decision");
      assert(rfqPackage.items[0].decision.filename === "cube.step", "RFQ create response linked a different filename");
      assert(rfqPackage.live_supplier_send === false, "RFQ package incorrectly claimed a live supplier send");
      assert(rfqPackage.metadata?.contract === "should_cost_evidence_not_supplier_quote", "RFQ contract boundary was missing");
      await page.getByText("RFQ package generated").waitFor({ timeout: 20_000 });
      await page.getByText(rfqTitle, { exact: true }).waitFor({ timeout: 12_000 });
      await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
      const packageRow = page.getByRole("row").filter({ hasText: rfqTitle }).first();
      await packageRow.waitFor({ timeout: 15_000 });
      const packageRowText = await packageRow.innerText();
      assert(/1/.test(packageRowText), "refreshed RFQ list lost its item count");
      assert(new RegExp(String(rfqPackage.warnings.length)).test(packageRowText), "refreshed RFQ list lost its warning count");
      return {
        id: rfqPackage.id,
        title: rfqPackage.title,
        decisionId: durableCostDetail.id,
        warningCodes: rfqPackage.warnings.map((warning) => warning.code),
        listRefreshDurable: true,
        screenshot: await shot("rfq-package-generated-refreshed"),
      };
    });

    await step("generated RFQ opens and downloads a nonempty ZIP", async () => {
      const detailResponsePromise = page.waitForResponse(
        (response) => isProxyResponse(response, "GET", `/rfq-packages/${rfqPackage.id}`),
        { timeout: 20_000 }
      );
      await page.getByText(rfqTitle, { exact: true }).click();
      await page.waitForURL((url) => url.pathname === `/rfq-packages/${rfqPackage.id}`, { timeout: 12_000 });
      const detailResponse = await detailResponsePromise;
      assert(detailResponse.ok(), `RFQ detail returned HTTP ${detailResponse.status()}`);
      const rfqDetail = (await detailResponse.json()).package;
      assertJsonEqual(rfqDetail, rfqPackage, "reopened RFQ package detail");
      await page.getByText(/1 decisions/i).waitFor({ timeout: 12_000 });
      const detailRow = page.getByRole("row").filter({ hasText: "cube.step" }).first();
      await detailRow.waitFor({ timeout: 12_000 });
      const detailRowText = (await detailRow.innerText()).toLowerCase();
      assert(detailRowText.includes(rfqDetail.items[0].decision.make_now_process.toLowerCase()), "RFQ detail UI lost the decision process");
      assert(detailRowText.includes(rfqDetail.items[0].decision.approval_status.toLowerCase()), "RFQ detail UI lost the approval status");

      const refreshResponsePromise = page.waitForResponse(
        (response) => isProxyResponse(response, "GET", `/rfq-packages/${rfqPackage.id}`),
        { timeout: 20_000 }
      );
      await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
      const refreshResponse = await refreshResponsePromise;
      assert(refreshResponse.ok(), `refreshed RFQ detail returned HTTP ${refreshResponse.status()}`);
      const refreshedDetail = (await refreshResponse.json()).package;
      assertJsonEqual(refreshedDetail, rfqDetail, "refreshed RFQ package detail");
      await page.getByRole("row").filter({ hasText: "cube.step" }).first().waitFor({ timeout: 12_000 });

      const downloadPromise = page.waitForEvent("download", { timeout: 20_000 });
      await page.getByRole("button", { name: /Download ZIP/i }).click();
      const download = await downloadPromise;
      await download.saveAs(zipPath);
      const file = await stat(zipPath);
      assert(file.size > 100, `RFQ ZIP was unexpectedly small (${file.size} bytes)`);
      const zipBytes = await readFile(zipPath);
      const entries = unzipSync(new Uint8Array(zipBytes));
      const filenames = Object.keys(entries).sort();
      const requiredRootFiles = [
        "package_manifest.json",
        "line-items.csv",
        "supplier-brief.md",
        "cost-decisions.json",
      ];
      requiredRootFiles.forEach((name) => assert(entries[name], `RFQ ZIP is missing required file ${name}`));

      const manifest = zipJson(entries, "package_manifest.json");
      assert(manifest.id === rfqDetail.id, "RFQ manifest package id differs from the reopened package");
      assert(manifest.title === rfqTitle, "RFQ manifest title differs from the reopened package");
      assert(manifest.supplier_name === rfqSupplier, "RFQ manifest supplier differs from the UI input");
      assert(manifest.item_count === 1, `RFQ manifest item_count was ${manifest.item_count}`);
      assert(manifest.live_supplier_send === false, "RFQ manifest incorrectly claims a live supplier send");
      requiredRootFiles.forEach((name) => assert(manifest.included_files.includes(name), `RFQ manifest omitted included file ${name}`));
      assertJsonEqual(manifest.warnings, rfqDetail.warnings, "RFQ manifest warnings");
      assert(manifest.metadata?.note === rfqNote, "RFQ manifest lost the buyer note");
      assert(manifest.metadata?.contract === "should_cost_evidence_not_supplier_quote", "RFQ manifest lost the evidence-only contract");

      const packagedItems = zipJson(entries, "cost-decisions.json");
      assert(Array.isArray(packagedItems) && packagedItems.length === 1, "RFQ cost-decisions.json did not contain one item");
      const packagedItem = packagedItems[0];
      assertJsonEqual(packagedItem, rfqDetail.items[0], "RFQ packaged decision envelope");
      assert(packagedItem.decision.id === durableCostDetail.id, "RFQ packaged decision id differs from the durable record");
      assert(packagedItem.decision.filename === durableCostDetail.filename, "RFQ packaged filename differs from the durable record");
      assertJsonEqual(packagedItem.cost_decision, durableCostDetail.result, "RFQ packaged cost decision content");

      const lineItems = parseCsv(zipText(entries, "line-items.csv"), "RFQ line-items.csv");
      assertHeaders(lineItems.headers, rfqLineItemHeaders, "RFQ line-items.csv");
      assert(lineItems.records.length === 1, `RFQ line-items.csv contained ${lineItems.records.length} rows`);
      const lineItem = lineItems.records[0];
      assert(lineItem.decision_id === durableCostDetail.id, "RFQ line item links a different decision id");
      assert(lineItem.filename === durableCostDetail.filename, "RFQ line item links a different filename");
      assert(lineItem.approval_status === rfqDetail.items[0].decision.approval_status, "RFQ line item approval status drifted");
      assert(lineItem.is_stale.toLowerCase() === String(Boolean(rfqDetail.items[0].decision.is_stale)), "RFQ line item stale flag drifted");
      assert(
        lineItem.unvalidated_confidence.toLowerCase() === String(Boolean(rfqDetail.items[0].decision.unvalidated_confidence)),
        "RFQ line item confidence flag drifted"
      );
      assert(lineItem.make_now_process === durableCostDetail.make_now_process, "RFQ line item make-now process drifted");
      if (durableCostDetail.crossover_qty == null) {
        assert(lineItem.crossover_qty === "", "RFQ line item invented a crossover quantity");
      } else {
        assert(
          approxEqual(Number(lineItem.crossover_qty), Number(durableCostDetail.crossover_qty), 0.000001),
          `RFQ line item crossover ${lineItem.crossover_qty} differs from ${durableCostDetail.crossover_qty}`
        );
      }
      assert(lineItem.raw_cad_included.toLowerCase() === "false", "RFQ line item unexpectedly claimed raw CAD");

      const supplierBrief = zipText(entries, "supplier-brief.md");
      assert(supplierBrief.includes(`# ${rfqTitle}`), "supplier brief lost the package title");
      assert(supplierBrief.includes(`Supplier target: ${rfqSupplier}`), "supplier brief lost the supplier target");
      assert(supplierBrief.includes("Decisions included: 1"), "supplier brief lost its decision count");
      assert(supplierBrief.includes("Live supplier send: no"), "supplier brief lost the no-live-send boundary");
      assert(supplierBrief.includes(rfqNote), "supplier brief lost the buyer note");
      assert(/not a supplier quote/i.test(supplierBrief), "supplier brief lost the evidence-only warning");
      for (const warning of rfqDetail.warnings) {
        assert(supplierBrief.includes(warning.code), `supplier brief omitted warning ${warning.code}`);
      }

      const decisionJsonFiles = filenames.filter((name) => /decisions\/[^/]+\/cost-decision\.json$/.test(name));
      assert(decisionJsonFiles.length === 1, `RFQ ZIP contained ${decisionJsonFiles.length} per-decision JSON files`);
      const decisionPrefix = decisionJsonFiles[0].replace(/cost-decision\.json$/, "");
      const pdfFile = `${decisionPrefix}should-cost-report.pdf`;
      const requiredDecisionFiles = [
        `${decisionPrefix}cost-decision.json`,
        `${decisionPrefix}cost-drivers.csv`,
        pdfFile,
        `${decisionPrefix}raw-cad-unavailable.txt`,
      ];
      requiredDecisionFiles.forEach((name) => assert(entries[name], `RFQ ZIP is missing required decision file ${name}`));
      assertJsonEqual(zipJson(entries, `${decisionPrefix}cost-decision.json`), durableCostDetail.result, "per-decision cost-decision.json");

      const drivers = parseCsv(zipText(entries, `${decisionPrefix}cost-drivers.csv`), "RFQ cost-drivers.csv");
      assertHeaders(drivers.headers, costDriverHeaders, "RFQ cost-drivers.csv");
      assert(
        drivers.records.length === pinnedCube.estimates && drivers.records.length === durableCostDetail.result.estimates.length,
        `RFQ cost-drivers.csv had ${drivers.records.length} rows; expected ${pinnedCube.estimates}`
      );
      const governanceColumns = [
        "approval_status",
        "approved_by_user_id",
        "approved_at",
        "approval_note",
        "user_disposition",
        "user_disposition_label",
        "disposition_note",
        "disposition_updated_at",
        "disposition_updated_by_user_id",
      ];
      for (const estimate of durableCostDetail.result.estimates) {
        const row = drivers.records.find(
          (record) => record.process === estimate.process && Number(record.quantity) === estimate.quantity
        );
        assert(row, `RFQ cost-drivers.csv is missing ${estimate.process} qty ${estimate.quantity}`);
        assert(approxEqual(Number(row.unit_cost_usd), estimate.unit_cost_usd, 0.001), `RFQ driver unit cost drifted for ${estimate.process} qty ${estimate.quantity}`);
        assert(row.confidence_label === estimate.confidence.label, `RFQ driver confidence label drifted for ${estimate.process} qty ${estimate.quantity}`);
        assert(row.confidence_validated.toLowerCase() === String(Boolean(estimate.confidence.validated)), `RFQ driver validation flag drifted for ${estimate.process} qty ${estimate.quantity}`);
        assert(row.dfm_ready.toLowerCase() === String(Boolean(estimate.dfm_ready)), `RFQ driver DFM flag drifted for ${estimate.process} qty ${estimate.quantity}`);
        for (const field of governanceColumns) {
          assert(
            row[field] === String(durableCostDetail[field] ?? ""),
            `RFQ driver governance ${field} drifted for ${estimate.process} qty ${estimate.quantity}`,
          );
        }
        for (const [key, value] of Object.entries(estimate.line_items || {})) {
          assert(row.line_items.includes(`${key}=${value}`), `RFQ driver row omitted line item ${key}=${value}`);
        }
      }

      const pdfBytes = entries[pdfFile];
      assert(pdfBytes.length > 1_000, `RFQ should-cost PDF was only ${pdfBytes.length} bytes`);
      assert(strFromU8(pdfBytes.slice(0, 5)).startsWith("%PDF-"), "RFQ should-cost report is not a PDF");
      const extractedPdf = path.join(outputRoot, `training-guide-should-cost-${runId}.pdf`);
      await writeFile(extractedPdf, pdfBytes);
      let pdfText;
      try {
        pdfText = execFileSync("pdftotext", [extractedPdf, "-"], { encoding: "utf8" });
      } catch (error) {
        throw new Error(`pdftotext is required for semantic RFQ validation: ${error instanceof Error ? error.message : String(error)}`);
      }
      const normalizedPdf = pdfText.replace(/\s+/g, " ");
      for (const expected of [
        "Should-Cost & Make-vs-Buy Report",
        durableCostDetail.filename,
        String(durableCostDetail.result.geometry.volume_cm3),
        String(durableCostDetail.result.geometry.surface_area_cm2),
        `Make now: ${pinnedCube.makeNowProcess}`,
        `Crossover quantity: ≈ ${pinnedCube.crossoverQty}.0 units`,
        "Assumption-based should-cost",
        "not a quote",
      ]) {
        assert(normalizedPdf.includes(expected), `RFQ PDF text omitted ${JSON.stringify(expected)}`);
      }
      for (const [quantity, [process, unitCost]] of Object.entries(pinnedCube.recommendation)) {
        assert(normalizedPdf.includes(String(quantity)), `RFQ PDF omitted quantity ${quantity}`);
        assert(normalizedPdf.includes(process), `RFQ PDF omitted process ${process}`);
        assert(normalizedPdf.includes(`$${unitCost.toFixed(2)}/unit`), `RFQ PDF omitted $${unitCost.toFixed(2)}/unit`);
      }
      const pdfEvidence = { mode: "pdf-semantic", bytes: pdfBytes.length, sha256: sha256(pdfBytes), textChecks: 8 + Object.keys(pinnedCube.recommendation).length * 3 };
      const rawCadBoundary = zipText(entries, `${decisionPrefix}raw-cad-unavailable.txt`);
      assert(/not included/i.test(rawCadBoundary), "RFQ raw-CAD boundary did not explain that CAD was not included");

      assert(packagedItem.part_context, "RFQ package omitted the verified part context");
      const contextFile = `${decisionPrefix}part-context.json`;
      assert(entries[contextFile], "RFQ decision has context but the ZIP omitted part-context.json");
      assertJsonEqual(zipJson(entries, contextFile), packagedItem.part_context, "RFQ part context");

      rfqArchiveEvidence = {
        id: rfqDetail.id,
        route: `/rfq-packages/${rfqDetail.id}`,
        decisionId: durableCostDetail.id,
        detailRefreshExact: true,
        zip: {
          path: zipPath,
          bytes: file.size,
          sha256: sha256(zipBytes),
          files: filenames,
          requiredRootFiles,
          requiredDecisionFiles,
        },
        manifest: {
          itemCount: manifest.item_count,
          warningCodes: manifest.warnings.map((warning) => warning.code),
          liveSupplierSend: manifest.live_supplier_send,
          contract: manifest.metadata.contract,
        },
        lineItem,
        driverRows: drivers.records.length,
        pdf: pdfEvidence,
        partContextIncluded: Boolean(packagedItem.part_context),
        screenshot: await shot("rfq-package-detail-refreshed"),
      };
      return rfqArchiveEvidence;
    });
  } catch (error) {
    fatalError = error instanceof Error ? error.message : String(error);
  } finally {
    await browser.close();
  }

  const reconciledAborts = reconcileSuccessfulUploadAborts(
    pendingSuccessAborts,
    successfulAbortableResponses,
  );
  expectedRequestAborts.push(...reconciledAborts.expected);
  requestFailures.push(...reconciledAborts.failures);

  const failed = steps.filter((item) => item.status !== "PASS");
  const status = !fatalError && failed.length === 0 && consoleErrors.length === 0 && requestFailures.length === 0 ? "PASS" : "NEEDS_FIXES";
  const data = {
    status,
    generatedAt: new Date().toISOString(),
    runId,
    baseUrl,
    account: { email },
    steps,
    failed,
    fatalError,
    consoleErrors,
    requestFailures,
    expectedRequestAborts,
    screenshots,
    batchCsv: batchCsvPath,
    rfqZip: zipPath,
    outcomeOracles: {
      cadAndDurableCost: cadEvidence,
      batchCsv: batchEvidence,
      rfqPackage: rfqArchiveEvidence,
    },
  };
  await writeFile(reportJson, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(reportMd, markdownReport(data));
  console.log(JSON.stringify({
    status,
    passed: steps.length - failed.length,
    failed: failed.length,
    consoleErrors: consoleErrors.length,
    requestFailures: requestFailures.length,
    expectedRequestAborts: expectedRequestAborts.length,
    fatalError,
    report: reportMd,
    screenshots: screenshotDir,
  }, null, 2));
  if (status !== "PASS") {
    process.exitCode = 1;
    if (fatalError) console.error(fatalError);
  }
}

const invokedAsScript = process.argv[1] && path.resolve(process.argv[1]) === __filename;
if (invokedAsScript) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
