import { createRequire } from "node:module";
import { randomBytes } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");
const { zipSync } = require("fflate");

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

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function uniqueEmail() {
  return `training-guide-${Date.now()}-${process.pid}-${randomBytes(4).toString("hex")}@example.com`;
}

function slug(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
}

async function main() {
  await mkdir(screenshotDir, { recursive: true });
  const cubeBytes = await readFile(path.join(repoRoot, "backend", "tests", "assets", "cube.step"));
  await writeFile(batchZipPath, zipSync({ "cube.step": new Uint8Array(cubeBytes) }));
  const browser = await pw.chromium.launch({ channel: "chrome", headless: true }).catch(() =>
    pw.chromium.launch({ headless: true })
  );
  const context = await browser.newContext({
    baseURL: baseUrl,
    viewport: { width: 1440, height: 960 },
    reducedMotion: "reduce",
    acceptDownloads: true,
  });
  const page = await context.newPage();
  const steps = [];
  const consoleErrors = [];
  const requestFailures = [];
  const screenshots = [];

  page.on("console", (message) => {
    if (message.type() === "error" && !/favicon\.ico|ResizeObserver loop limit exceeded/i.test(message.text())) {
      consoleErrors.push({ url: page.url(), text: message.text() });
    }
  });
  page.on("pageerror", (error) => consoleErrors.push({ url: page.url(), text: error.message }));
  page.on("requestfailed", (request) => {
    const url = request.url();
    const error = request.failure()?.errorText || "request failed";
    if (/favicon\.ico|vercel\/speed-insights|\/_next\/webpack-hmr/i.test(url)) return;
    if (error === "net::ERR_ABORTED" && /[?&]_rsc=/.test(url)) return;
    requestFailures.push({ method: request.method(), url, error });
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
      await page.locator('input[type="file"][accept*=".stl"]').first().setInputFiles(
        path.join(repoRoot, "backend", "tests", "assets", "cube.step")
      );
      await page.waitForFunction(() => {
        const text = document.body.innerText;
        return /computed from POST \/validate\/cost|What it really takes|unit cost|bbox/i.test(text) && !/measuring geometry/i.test(text);
      }, null, { timeout: cadUploadTimeoutMs });
      const text = await page.locator("body").innerText();
      assert(!/Cost request failed|Validation failed|Network error|Geometry invalid|repair required/i.test(text), "STEP verification ended in an error state");
      assert(/cost-decision|unit cost|What it really takes/i.test(text), "durable cost evidence was not visible");
      return { screenshot: await shot("verified-step-result") };
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
      const downloadPromise = page.waitForEvent("download", { timeout: 20_000 });
      await page.getByRole("button", { name: "Download CSV" }).click();
      const download = await downloadPromise;
      await download.saveAs(batchCsvPath);
      const file = await stat(batchCsvPath);
      assert(file.size > 20, `batch CSV was unexpectedly small (${file.size} bytes)`);
      return { csvBytes: file.size, url: page.url(), screenshot: await shot("batch-complete") };
    });

    await step("sourcing user generates an RFQ package from the saved decision", async () => {
      await page.goto("/rfq-packages", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await page.getByRole("heading", { name: "RFQ packages" }).waitFor({ timeout: 12_000 });
      await page.getByText("New package", { exact: true }).waitFor({ timeout: 12_000 });
      const decision = page.getByRole("checkbox", { name: /Include .* in the RFQ package/i }).first();
      await decision.waitFor({ timeout: 15_000 });
      await decision.check();
      await page.getByPlaceholder("Pump RFQ package").fill(rfqTitle);
      await page.getByRole("button", { name: /Generate package \(1\)/ }).click();
      await page.getByText("RFQ package generated").waitFor({ timeout: 20_000 });
      await page.getByText(rfqTitle, { exact: true }).waitFor({ timeout: 12_000 });
      return { title: rfqTitle, screenshot: await shot("rfq-package-generated") };
    });

    await step("generated RFQ opens and downloads a nonempty ZIP", async () => {
      await page.getByText(rfqTitle, { exact: true }).click();
      await page.waitForURL(/\/rfq-packages\/[A-Z0-9]+$/, { timeout: 12_000 });
      await page.getByText(/1 decisions/i).waitFor({ timeout: 12_000 });
      const downloadPromise = page.waitForEvent("download", { timeout: 20_000 });
      await page.getByRole("button", { name: /Download ZIP/i }).click();
      const download = await downloadPromise;
      await download.saveAs(zipPath);
      const file = await stat(zipPath);
      assert(file.size > 100, `RFQ ZIP was unexpectedly small (${file.size} bytes)`);
      return { bytes: file.size, url: page.url(), screenshot: await shot("rfq-package-detail") };
    });
  } finally {
    await browser.close();
  }

  const failed = steps.filter((item) => item.status !== "PASS");
  const status = failed.length === 0 && consoleErrors.length === 0 && requestFailures.length === 0 ? "PASS" : "NEEDS_FIXES";
  const data = {
    status,
    generatedAt: new Date().toISOString(),
    runId,
    baseUrl,
    account: { email },
    steps,
    failed,
    consoleErrors,
    requestFailures,
    screenshots,
    rfqZip: zipPath,
  };
  await writeFile(reportJson, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(reportMd, `# Training guide E2E\n\n- Status: ${status}\n- Steps: ${steps.length - failed.length}/${steps.length}\n- Console errors: ${consoleErrors.length}\n- Request failures: ${requestFailures.length}\n- RFQ ZIP: ${zipPath}\n\n${steps.map((item) => `- ${item.status}: ${item.name}`).join("\n")}\n`);
  console.log(JSON.stringify({
    status,
    passed: steps.length - failed.length,
    failed: failed.length,
    consoleErrors: consoleErrors.length,
    requestFailures: requestFailures.length,
    report: reportMd,
    screenshots: screenshotDir,
  }, null, 2));
  if (status !== "PASS") process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
