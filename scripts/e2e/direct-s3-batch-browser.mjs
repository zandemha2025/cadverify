import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { createRequire } from "node:module";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const { zipSync } = require("fflate");

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const s3Endpoint = process.env.E2E_S3_ENDPOINT || "http://127.0.0.1:5000";
const runId = process.env.E2E_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(outputRoot, "screenshots", `direct-s3-batch-${runId}`);
const reportPath = path.join(outputRoot, `direct-s3-batch-${runId}.json`);
const cubePath = path.join(repoRoot, "backend", "tests", "assets", "cube.step");

const terminalBatchStatuses = new Set(["completed", "failed", "cancelled"]);

function uniqueEmail(prefix) {
  return `${prefix}-${Date.now()}-${randomBytes(5).toString("hex")}@example.test`;
}

function testClientIp() {
  return `198.51.100.${20 + (randomBytes(1)[0] % 200)}`;
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function redactUrl(raw) {
  try {
    const url = new URL(raw);
    return `${url.origin}${url.pathname}`;
  } catch {
    return raw;
  }
}

async function responseJson(response) {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return { invalid_json: true, text: text.slice(0, 500) };
  }
}

async function signup(page, email) {
  await page.goto("/signup", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("Passw0rd123");
  await page.getByRole("button", { name: /^Create account$/ }).click();
  await page.waitForURL((url) => url.pathname === "/verify", { timeout: 30_000 });
}

async function apiJson(context, method, pathname) {
  const response = await context.request.fetch(pathname, { method });
  return { response, body: await responseJson(response) };
}

async function waitForBatch(context, batchId, timeoutMs = 240_000) {
  const startedAt = Date.now();
  const statuses = [];
  let latest = null;
  while (Date.now() - startedAt < timeoutMs) {
    const result = await apiJson(context, "GET", `/api/proxy/batch/${batchId}`);
    assert.equal(result.response.status(), 200, `batch status HTTP ${result.response.status()}`);
    latest = result.body;
    if (statuses.at(-1) !== latest.status) statuses.push(latest.status);
    if (terminalBatchStatuses.has(latest.status)) return { latest, statuses };
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error(`batch ${batchId} did not reach a terminal state: ${JSON.stringify(latest)}`);
}

async function main() {
  await mkdir(screenshotDir, { recursive: true });
  const tmpDir = await mkdir(path.join(os.tmpdir(), `proofshape-direct-s3-${runId}`), {
    recursive: true,
  }).then(() => path.join(os.tmpdir(), `proofshape-direct-s3-${runId}`));

  const cube = await readFile(cubePath);
  // A stored incompressible-shaped padding entry makes this a real multi-part
  // browser upload while the worker intentionally ignores the non-CAD member.
  const padding = new Uint8Array(17 * 1024 * 1024);
  for (let index = 0; index < padding.length; index += 4096) {
    padding[index] = (index / 4096) % 251;
  }
  const multipartZip = Buffer.from(
    zipSync(
      {
        "cube.step": new Uint8Array(cube),
        "ignored-padding.bin": padding,
      },
      { level: 0 },
    ),
  );
  const failureZip = Buffer.from(zipSync({ "cube.step": new Uint8Array(cube) }, { level: 0 }));
  const multipartZipPath = path.join(tmpDir, "real-multipart-batch.zip");
  const failureZipPath = path.join(tmpDir, "interrupted-batch.zip");
  await writeFile(multipartZipPath, multipartZip);
  await writeFile(failureZipPath, failureZip);

  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
  }).catch(() => chromium.launch({
    headless: true,
    args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
  }));

  const report = {
    suite: "direct-s3-batch-browser",
    runId,
    baseUrl,
    startedAt: new Date().toISOString(),
    status: "RUNNING",
    fixtures: {
      cube: { bytes: cube.length, sha256: sha256(cube) },
      multipartZip: { bytes: multipartZip.length, sha256: sha256(multipartZip) },
      failureZip: { bytes: failureZip.length, sha256: sha256(failureZip) },
    },
    steps: [],
    consoleErrors: [],
    requestFailures: [],
  };

  let context;
  try {
    context = await browser.newContext({
      baseURL: baseUrl,
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
      extraHTTPHeaders: { "x-real-ip": testClientIp() },
    });
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error" && !/favicon\.ico/i.test(message.text())) {
        report.consoleErrors.push({ url: page.url(), text: message.text() });
      }
    });
    page.on("pageerror", (error) => {
      report.consoleErrors.push({ url: page.url(), text: error.message });
    });
    page.on("requestfailed", (request) => {
      const failure = request.failure()?.errorText || "request failed";
      if (failure !== "net::ERR_ABORTED") {
        report.requestFailures.push({
          method: request.method(),
          url: redactUrl(request.url()),
          failure,
        });
      }
    });

    const email = uniqueEmail("direct-s3");
    await signup(page, email);

    const capability = await apiJson(context, "GET", "/api/proxy/uploads/capabilities");
    assert.equal(capability.response.status(), 200);
    assert.equal(capability.body?.direct_upload, true, JSON.stringify(capability.body));
    report.steps.push({ id: "S3-01", status: "PASS", capability: capability.body });

    const network = {
      capability: 0,
      initiate: [],
      refresh: [],
      complete: [],
      abort: [],
      s3Put: [],
      batchCreate: [],
    };
    page.on("response", async (response) => {
      const url = new URL(response.url());
      const method = response.request().method();
      if (method === "GET" && url.pathname.endsWith("/uploads/capabilities")) network.capability += 1;
      if (method === "POST" && url.pathname.endsWith("/uploads/multipart")) {
        const body = await responseJson(response).catch(() => null);
        network.initiate.push({
          status: response.status(),
          body: body && typeof body === "object" ? {
            direct_upload_id: body.direct_upload_id,
            status: body.status,
            part_count: body.part_count,
            part_size_bytes: body.part_size_bytes,
            exposed_keys: Object.keys(body).sort(),
            signed_part_count: Array.isArray(body.parts) ? body.parts.length : null,
          } : null,
        });
      }
      if (method === "POST" && /\/uploads\/[^/]+\/parts$/.test(url.pathname)) {
        network.refresh.push({ status: response.status() });
      }
      if (method === "POST" && /\/uploads\/[^/]+\/complete$/.test(url.pathname)) {
        network.complete.push({ status: response.status() });
      }
      if (method === "POST" && /\/uploads\/[^/]+\/abort$/.test(url.pathname)) {
        network.abort.push({ status: response.status() });
      }
      if (method === "PUT" && response.url().startsWith(s3Endpoint)) {
        network.s3Put.push({ status: response.status(), url: redactUrl(response.url()) });
      }
      if (method === "POST" && url.pathname === "/api/proxy/batch") {
        network.batchCreate.push({ status: response.status(), body: await responseJson(response).catch(() => null) });
      }
    });

    // Force one realistic expired-link response. The browser must ask the app
    // for a fresh URL for that exact part, retry it, and still finish once.
    let injectedForbidden = false;
    await page.route(`${s3Endpoint}/**`, async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      if (!injectedForbidden) {
        injectedForbidden = true;
        return route.fulfill({ status: 403, body: "expired test URL" });
      }
      await new Promise((resolve) => setTimeout(resolve, 800));
      return route.continue();
    });

    await page.goto("/batch", { waitUntil: "networkidle", timeout: 30_000 });
    await page.locator('input[type="file"][accept=".zip"]').first().setInputFiles(multipartZipPath);
    const startBatchButton = page.getByRole("button", { name: /^Start batch$/ });
    await startBatchButton.waitFor({ state: "visible", timeout: 10_000 });
    await page.waitForFunction(
      () => {
        const button = [...document.querySelectorAll("button")].find(
          (candidate) => candidate.textContent?.trim() === "Start batch",
        );
        return button instanceof HTMLButtonElement && !button.disabled;
      },
      undefined,
      { timeout: 10_000 },
    );
    await startBatchButton.click();
    const uploadState = page.locator("[data-upload-stage]");
    await uploadState.waitFor({ timeout: 20_000 });
    await page.waitForFunction(
      () => {
        const stage = document.querySelector("[data-upload-stage]")?.getAttribute("data-upload-stage");
        return stage === "uploading" || stage === "retrying";
      },
      undefined,
      { timeout: 20_000 },
    );
    const uploadScreenshot = path.join(screenshotDir, "s3-02-real-multipart-upload.png");
    await page.screenshot({ path: uploadScreenshot, fullPage: true, animations: "disabled", caret: "initial" });
    const uploadAlert = page.locator("[data-upload-error]");
    await Promise.race([
      page.waitForURL(/\/batch\/[A-Z0-9]+$/, { timeout: 90_000 }),
      uploadAlert.waitFor({ state: "visible", timeout: 90_000 }).then(async () => {
        const failureScreenshot = path.join(screenshotDir, "s3-02-upload-failure.png");
        await page.screenshot({
          path: failureScreenshot,
          fullPage: true,
          animations: "disabled",
          caret: "initial",
        });
        throw new Error(`Upload UI failed before batch creation: ${(await uploadAlert.innerText()).trim()}`);
      }),
    ]);
    const batchId = new URL(page.url()).pathname.split("/").filter(Boolean).at(-1);
    assert.match(batchId || "", /^[A-Z0-9]+$/);

    const terminal = await waitForBatch(context, batchId);
    assert.equal(terminal.latest.status, "completed", JSON.stringify(terminal.latest));
    assert.equal(terminal.latest.total_items, 1);
    assert.equal(terminal.latest.completed_items, 1);
    assert.equal(terminal.latest.failed_items, 0);
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForFunction(() => /1\s*\/\s*1\s*\(100%\)/i.test(document.body.innerText), null, {
      timeout: 30_000,
    });
    const row = page.getByRole("row").filter({ hasText: "cube.step" }).first();
    await row.getByText(/^Completed$/i).waitFor({ timeout: 20_000 });

    const csvResponse = await context.request.get(`/api/proxy/batch/${batchId}/results/csv`);
    assert.equal(csvResponse.status(), 200);
    const csv = await csvResponse.text();
    assert.match(csv, /cube\.step,completed/i);

    assert.equal(network.initiate.length, 1, JSON.stringify(network));
    const initiation = network.initiate[0].body;
    assert.equal(initiation?.part_count >= 2, true, JSON.stringify(initiation));
    for (const forbidden of ["bucket", "object_key", "multipart_upload_id"]) {
      assert.equal(initiation?.exposed_keys?.includes(forbidden), false, `${forbidden} leaked`);
    }
    assert.equal(network.refresh.length >= 1, true, JSON.stringify(network));
    assert.equal(network.complete.length, 1, JSON.stringify(network));
    assert.equal(network.batchCreate.length, 1, JSON.stringify(network));
    assert.equal(network.s3Put.filter((entry) => entry.status >= 200 && entry.status < 300).length >= 2, true);
    const directUploadId = initiation?.direct_upload_id;
    assert.match(directUploadId || "", /^[A-Z0-9]+$/);

    const directStatus = await apiJson(context, "GET", `/api/proxy/uploads/${directUploadId}`);
    assert.equal(directStatus.response.status(), 200);
    assert.equal(directStatus.body?.status, "consumed", JSON.stringify(directStatus.body));
    assert.equal(directStatus.body?.batch_id, batchId);

    const browserState = await page.evaluate(() => ({
      body: document.body.innerText,
      localStorage: Object.entries(localStorage),
      sessionStorage: Object.entries(sessionStorage),
    }));
    const persistedBrowserText = JSON.stringify(browserState);
    assert.doesNotMatch(persistedBrowserText, /AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|multipart_upload_id|object_key/i);
    const terminalScreenshot = path.join(screenshotDir, "s3-03-terminal-refresh-and-csv.png");
    // The terminal view fits inside the fixed viewport. Avoid Chromium's
    // full-page stitching here because sticky navigation can otherwise leave
    // black compositor tiles in an otherwise healthy screenshot.
    await page.screenshot({ path: terminalScreenshot, fullPage: false, animations: "disabled", caret: "initial" });
    report.steps.push({
      id: "S3-02",
      status: "PASS",
      directUploadId,
      batchId,
      batchStatuses: terminal.statuses,
      terminal: terminal.latest,
      network,
      csvSha256: sha256(Buffer.from(csv)),
      screenshots: [uploadScreenshot, terminalScreenshot],
    });

    const secondContext = await browser.newContext({
      baseURL: baseUrl,
      extraHTTPHeaders: { "x-real-ip": testClientIp() },
    });
    const secondPage = await secondContext.newPage();
    await signup(secondPage, uniqueEmail("direct-s3-isolation"));
    const foreignUpload = await apiJson(secondContext, "GET", `/api/proxy/uploads/${directUploadId}`);
    const foreignBatch = await apiJson(secondContext, "GET", `/api/proxy/batch/${batchId}`);
    assert.equal(foreignUpload.response.status(), 404);
    assert.equal(foreignBatch.response.status(), 404);
    await secondContext.close();
    report.steps.push({ id: "S3-03", status: "PASS", uploadStatus: 404, batchStatus: 404 });

    // A part that keeps failing must be retried finitely, aborted server-side,
    // leave no Batch row, and give the human a retained-file retry action.
    await page.unroute(`${s3Endpoint}/**`);
    let rejectedPuts = 0;
    await page.route(`${s3Endpoint}/**`, async (route) => {
      if (route.request().method() === "PUT") {
        rejectedPuts += 1;
        return route.fulfill({ status: 503, body: "temporary object-store outage" });
      }
      return route.continue();
    });
    const initiationsBeforeFailure = network.initiate.length;
    const batchesBeforeFailure = network.batchCreate.length;
    await page.goto("/batch", { waitUntil: "networkidle", timeout: 30_000 });
    await page.locator('input[type="file"][accept=".zip"]').first().setInputFiles(failureZipPath);
    const retryStartButton = page.getByRole("button", { name: /^Start batch$/ });
    await page.waitForFunction(
      () => {
        const button = [...document.querySelectorAll("button")].find(
          (candidate) => candidate.textContent?.trim() === "Start batch",
        );
        return button instanceof HTMLButtonElement && !button.disabled;
      },
      undefined,
      { timeout: 10_000 },
    );
    await retryStartButton.click();
    const alert = page.locator("[data-upload-error]");
    await alert.waitFor({ timeout: 45_000 });
    await alert.getByText("Upload did not finish", { exact: true }).waitFor();
    await page.getByRole("button", { name: /^Retry upload$/ }).waitFor();
    assert.equal(rejectedPuts, 4);
    assert.equal(network.initiate.length, initiationsBeforeFailure + 1);
    assert.equal(network.batchCreate.length, batchesBeforeFailure);
    assert.equal(network.abort.at(-1)?.status, 200, JSON.stringify(network.abort));
    const abortedId = network.initiate.at(-1)?.body?.direct_upload_id;
    const abortedStatus = await apiJson(context, "GET", `/api/proxy/uploads/${abortedId}`);
    assert.equal(abortedStatus.response.status(), 200);
    assert.equal(abortedStatus.body?.status, "aborted", JSON.stringify(abortedStatus.body));
    const failureScreenshot = path.join(screenshotDir, "s3-04-finite-retry-abort.png");
    await page.screenshot({ path: failureScreenshot, fullPage: true, animations: "disabled", caret: "initial" });
    report.steps.push({
      id: "S3-04",
      status: "PASS",
      directUploadId: abortedId,
      rejectedPuts,
      batchPosts: 0,
      abortStatus: network.abort.at(-1)?.status,
      screenshot: failureScreenshot,
    });

    // Chromium logs a generic console error for each deliberately fulfilled
    // non-2xx S3 response. Reconcile those one-for-one against the exact fault
    // responses observed on the object-store origin; any surplus error still
    // fails the run.
    const expectedFaultConsoleErrors = [];
    const unexpectedConsoleErrors = [...report.consoleErrors];
    for (const fault of network.s3Put.filter((entry) => [403, 503].includes(entry.status))) {
      const index = unexpectedConsoleErrors.findIndex((entry) =>
        entry.text.includes(`status of ${fault.status}`),
      );
      assert.notEqual(index, -1, `missing browser console receipt for injected S3 ${fault.status}`);
      expectedFaultConsoleErrors.push(unexpectedConsoleErrors.splice(index, 1)[0]);
    }
    report.expectedFaultConsoleErrors = expectedFaultConsoleErrors;
    report.consoleErrors = unexpectedConsoleErrors;
    assert.deepEqual(unexpectedConsoleErrors, []);
    assert.deepEqual(report.requestFailures, []);
    report.status = "PASS";
  } catch (error) {
    report.status = "FAIL";
    report.error = error instanceof Error ? error.stack || error.message : String(error);
    throw error;
  } finally {
    report.completedAt = new Date().toISOString();
    await mkdir(path.dirname(reportPath), { recursive: true });
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
    await context?.close().catch(() => {});
    await browser.close().catch(() => {});
    await rm(tmpDir, { recursive: true, force: true });
    console.log(JSON.stringify({ status: report.status, reportPath, steps: report.steps }, null, 2));
  }
}

await main();
