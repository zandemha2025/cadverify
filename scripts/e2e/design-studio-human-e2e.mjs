import { createHash, randomBytes } from "node:crypto";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const sharp = require("sharp");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(outputRoot, "screenshots", `design-studio-e2e-${runId}`);
const artifacts = {
  json: path.join(outputRoot, `design-studio-e2e-${runId}.json`),
  md: path.join(outputRoot, `qa-report-design-studio-e2e-${runId}.md`),
};

const forbiddenSuccessCopy = [
  /verification is temporarily busy/i,
  /this part couldn.t be tessellated/i,
  /geometry invalid/i,
  /cost request failed/i,
  /validation failed/i,
  /not implemented/i,
  /coming soon/i,
];

function uniqueEmail() {
  return `design-e2e-${Date.now()}-${process.pid}-${randomBytes(4).toString("hex")}@example.com`;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

class DesignStudioE2E {
  constructor() {
    this.steps = [];
    this.issues = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.successfulResponses = new Set();
    this.startedAt = Date.now();
  }

  async start() {
    await mkdir(screenshotDir, { recursive: true });
    this.browser = await chromium.launch({
      channel: "chrome",
      headless: true,
      args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
    });
    this.context = await this.browser.newContext({
      baseURL: baseUrl,
      viewport: { width: 1440, height: 960 },
      acceptDownloads: true,
    });
    this.page = await this.context.newPage();
    this.page.on("console", (message) => {
      if (message.type() === "error") this.consoleErrors.push(message.text());
    });
    this.page.on("pageerror", (error) => this.consoleErrors.push(error.message));
    this.page.on("response", (response) => {
      this.successfulResponses.add(`${response.request().method()} ${response.url()}`);
    });
    this.page.on("requestfailed", (request) => {
      const failure = request.failure()?.errorText || "request failed";
      const url = request.url();
      if (failure === "net::ERR_ABORTED" && /[?&]_rsc=/.test(url)) return;
      if (
        failure === "net::ERR_ABORTED" &&
        request.method() === "GET" &&
        /\/api\/proxy\/(?:machine-inventory|cost-decisions\?limit=8|rate-library|governance\/change-requests|designs\/[^/]+\/revisions\/\d+\/download\.step)/.test(url)
      ) return;
      if (/favicon\.ico|vercel\/speed-insights|\/_next\/webpack-hmr/i.test(url)) return;
      const key = `${request.method()} ${url}`;
      this.requestFailures.push({ key, message: `${key}: ${failure}` });
    });
  }

  async shot(name, fullPage = false) {
    const filename = path.join(
      screenshotDir,
      `${String(this.steps.length + 1).padStart(2, "0")}-${name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.png`,
    );
    await this.page.screenshot({ path: filename, fullPage });
    return filename;
  }

  async step(name, fn) {
    const started = Date.now();
    try {
      const result = (await fn()) || {};
      this.steps.push({
        name,
        status: "pass",
        url: this.page.url(),
        durationMs: Date.now() - started,
        ...result,
      });
      return result;
    } catch (error) {
      const screenshot = await this.shot(`${name}-failure`, true).catch(() => null);
      this.steps.push({
        name,
        status: "fail",
        url: this.page.url(),
        durationMs: Date.now() - started,
        error: error instanceof Error ? error.message : String(error),
        screenshot,
      });
      throw error;
    }
  }

  async text() {
    return (await this.page.locator("body").innerText()).replace(/\s+/g, " ").trim();
  }

  async expectText(pattern, label) {
    const text = await this.text();
    assert(pattern.test(text), `${label} missing ${pattern}`);
    return text;
  }

  async expectCleanSuccess(label) {
    const text = await this.text();
    for (const pattern of forbiddenSuccessCopy) {
      assert(!pattern.test(text), `${label} exposed failure/non-final copy ${pattern}`);
    }
    return text;
  }

  async assertCadPreviewVisible(label) {
    const fallback = this.page.getByText("Interactive 3D is unavailable in this browser.");
    if ((await fallback.count()) > 0) return { mode: "explicit-fallback" };
    const canvas = this.page.locator("canvas").last();
    await canvas.waitFor({ state: "visible", timeout: 15_000 });
    for (let attempt = 0; attempt < 24; attempt += 1) {
      const png = await canvas.screenshot();
      const { data, info } = await sharp(png)
        .removeAlpha()
        .raw()
        .toBuffer({ resolveWithObject: true });
      let bright = 0;
      for (let offset = 0; offset < data.length; offset += info.channels) {
        const luminance =
          data[offset] * 0.2126 +
          data[offset + 1] * 0.7152 +
          data[offset + 2] * 0.0722;
        if (luminance >= 80) bright += 1;
      }
      const brightFraction = bright / (info.width * info.height);
      if (brightFraction >= 0.003) {
        return { mode: "interactive", brightFraction };
      }
      await this.page.waitForTimeout(250);
    }
    throw new Error(`${label} CAD canvas stayed visually blank after the STL loaded`);
  }

  async signup() {
    const email = uniqueEmail();
    await this.page.goto("/signup", { waitUntil: "domcontentloaded" });
    await this.page.getByLabel("Email").fill(email);
    await this.page.getByLabel("Password").fill("ProofShape2026Secure");
    await this.page.getByRole("button", { name: /^Create account$/ }).click();
    await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: 20_000 });
    this.account = email;
  }

  async gotoStudio() {
    await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
    await this.page.getByRole("heading", { name: "ProofShape Design Studio" }).waitFor();
  }

  async waitForDesignReady(name) {
    const pattern = new RegExp(`${escapeRegExp(name)}\\s+Ready`, "i");
    const card = this.page.getByRole("button", { name: pattern }).first();
    await card.waitFor({ state: "visible", timeout: 90_000 });
    await card.click();
    await this.page.getByRole("heading", { name, exact: true }).waitFor();
  }

  async downloadHash(revision) {
    const link = this.page.getByRole("link", {
      name: new RegExp(`^Download R${revision} STEP$`),
    });
    const [download] = await Promise.all([
      this.page.waitForEvent("download", { timeout: 20_000 }),
      link.click(),
    ]);
    const filename = await download.path();
    assert(filename, `R${revision} STEP download did not produce a local file`);
    const bytes = await readFile(filename);
    assert(bytes.length > 128, `R${revision} STEP download is unexpectedly empty`);
    return { hash: sha256(bytes), bytes: bytes.length };
  }

  async generateCurrentForm(name, expectedEnvelope, expectedVolume) {
    await this.page.getByLabel("Design name").fill(name);
    await this.page.getByRole("button", { name: /^Generate design$/ }).click();
    await this.waitForDesignReady(name);
    await this.expectText(new RegExp(escapeRegExp(expectedEnvelope)), `${name} envelope`);
    await this.expectText(new RegExp(escapeRegExp(expectedVolume)), `${name} volume`);
    await this.expectText(/Ready.*Viewing revision 1.*current/i, `${name} ready state`);
    const text = await this.expectCleanSuccess(name);
    const visual = await this.assertCadPreviewVisible(name);
    const hashPrefix = text.match(/Evidence hash\s+([a-f0-9]{12})/i)?.[1];
    assert(hashPrefix, `${name} did not display an evidence hash prefix`);
    const downloaded = await this.downloadHash(1);
    assert(downloaded.hash.startsWith(hashPrefix), `${name} displayed hash does not match downloaded STEP`);
    return { ...downloaded, visual };
  }

  async verifySelectedRevision({
    revision,
    filenamePattern,
    envelope,
    volume,
    turningMustFail = false,
    expectedRouteHint = null,
  }) {
    const link = this.page.getByRole("link", {
      name: new RegExp(`^Verify revision ${revision}$`),
    });
    const href = await link.getAttribute("href");
    assert(href?.includes(`revision=${revision}`), `Verify link does not preserve revision ${revision}`);
    await link.click();
    await this.page.waitForURL((url) => url.pathname === "/verify" && url.searchParams.get("revision") === String(revision));
    await this.page.getByText(/Verification complete — deterministic/i).waitFor({ timeout: 150_000 });
    const text = await this.expectCleanSuccess(`Verify R${revision}`);
    assert(filenamePattern.test(text), `Verify did not retain the selected revision filename`);
    assert(text.includes(envelope), `Verify measured envelope does not equal ${envelope}`);
    assert(text.includes(volume), `Verify measured volume does not equal ${volume}`);
    assert(/watertight true/i.test(text), `Verify did not report watertight geometry`);
    assert(/SHOULD-COST COMPUTED/i.test(text), `Verify did not compute should-cost`);
    if (turningMustFail) {
      assert(!/CNC Turning\s+pass/i.test(text), `Non-rotational template incorrectly passes CNC turning`);
      assert(!/route hint aluminum/i.test(text), `Non-rotational polymer template still exposes the old aluminum turning hint`);
    }
    if (expectedRouteHint) {
      assert(
        new RegExp(`route hint ${escapeRegExp(expectedRouteHint)}`, "i").test(text),
        `Expected ${expectedRouteHint} route hint`,
      );
    }
    return { screenshot: await this.shot(`verify-r${revision}`, true) };
  }

  async run() {
    await this.step("Design Studio account signs up through the real web form", async () => {
      await this.signup();
      return { screenshot: await this.shot("signup-to-verify") };
    });

    await this.step("Design Studio loads inside the unified ProofShape shell", async () => {
      await this.gotoStudio();
      await this.page.getByRole("link", { name: "Verify workspace" }).first().waitFor();
      await this.page.getByRole("link", { name: "Design Studio" }).first().waitFor();
      await this.expectText(/Safe parametric CAD.*real, revisioned CAD/i, "Design Studio shell");
      return { screenshot: await this.shot("unified-shell") };
    });

    await this.step("Unsupported freeform geometry is rejected without approximation", async () => {
      await this.page.getByLabel("Describe a starting shape").fill(
        "Make a turbine blade with organic cooling channels",
      );
      await this.page.getByRole("button", { name: "Interpret safely" }).click();
      await this.page.getByText(
        "Choose a supported starting shape: plate, L bracket, or open enclosure.",
      ).waitFor();
      await this.expectText(/Unsupported geometry is never approximated here/i, "unsupported geometry boundary");
      return { screenshot: await this.shot("unsupported-freeform") };
    });

    await this.step("Incomplete enclosure description asks for exact missing dimensions", async () => {
      await this.page.getByLabel("Describe a starting shape").fill("open enclosure 100 × 60 mm");
      await this.page.getByRole("button", { name: "Interpret safely" }).click();
      await this.page.getByText(/need: height, wall thickness/i).waitFor();
      assert((await this.page.getByLabel("Width").inputValue()) === "100", "Width prefill drifted");
      assert((await this.page.getByLabel("Depth").inputValue()) === "60", "Depth prefill drifted");
      return { screenshot: await this.shot("missing-dimensions") };
    });

    let plateR1;
    await this.step("Plate description prefills exact clean millimetre values", async () => {
      await this.page.getByLabel("Describe a starting shape").fill(
        "120 × 70 × 8 mm plate with four 10 mm corner holes",
      );
      await this.page.getByRole("button", { name: "Interpret safely" }).click();
      await this.page.getByText(/Safe dimensions extracted/i).waitFor();
      const values = await Promise.all([
        this.page.getByLabel("Width").inputValue(),
        this.page.getByLabel("Depth").inputValue(),
        this.page.getByLabel("Thickness").inputValue(),
        this.page.getByLabel("Diameter").inputValue(),
        this.page.getByLabel("Edge inset").inputValue(),
      ]);
      assert(JSON.stringify(values) === JSON.stringify(["120", "70", "8", "10", "8.4"]), `Unexpected interpreted values ${values}`);
      return { screenshot: await this.shot("plate-prefill") };
    });

    await this.step("Unsafe plate hole margin is blocked before generation", async () => {
      await this.page.getByLabel("Edge inset").fill("5");
      await this.page.getByRole("button", { name: /^Generate design$/ }).click();
      await this.page.getByText("Hole inset must leave at least 1 mm of material at the edge.").waitFor();
      await this.page.getByRole("button", { name: "Dismiss" }).click();
      await this.page.getByLabel("Edge inset").fill("8.4");
      return { screenshot: await this.shot("unsafe-hole-margin") };
    });

    await this.step("Golden mounting plate generates real CAD with exact geometry and hash", async () => {
      plateR1 = await this.generateCurrentForm(
        "Golden mounting plate",
        "120.0 × 70.0 × 8.0 mm",
        "64.69 cm³",
      );
      return { screenshot: await this.shot("plate-r1-ready", true), evidence: plateR1 };
    });

    let plateR2;
    await this.step("Plate revision is immutable and historical STEP bytes remain exact", async () => {
      await this.page.getByRole("button", { name: "Revise" }).click();
      await this.page.getByRole("heading", { name: /Create revision 2/ }).waitFor();
      await this.page.getByLabel("Width").fill("130");
      await this.page.getByLabel("Design note (optional)").fill("Increase width by 10 mm");
      await this.page.getByRole("button", { name: "Generate new revision" }).click();
      await this.waitForDesignReady("Golden mounting plate");
      await this.page.getByRole("button", { name: /R2 ready current/i }).waitFor();
      await this.expectText(/130\.0 × 70\.0 × 8\.0 mm.*70\.29 cm³/i, "R2 geometry");
      plateR2 = await this.downloadHash(2);
      assert(plateR2.hash !== plateR1.hash, "R2 STEP hash did not change after a width revision");

      await this.page.getByRole("button", { name: /^R1 ready$/i }).click();
      await this.expectText(/Viewing revision 1 · current is 2/i, "historical revision marker");
      await this.expectText(/120\.0 × 70\.0 × 8\.0 mm.*64\.69 cm³/i, "historical R1 geometry");
      const plateR1Again = await this.downloadHash(1);
      assert(plateR1Again.hash === plateR1.hash, "Historical R1 bytes changed after R2 generation");
      return { screenshot: await this.shot("plate-revision-history", true), evidence: { plateR1, plateR2 } };
    });

    await this.step("Historical plate revision enters Verify with the exact measured result", async () =>
      this.verifySelectedRevision({
        revision: 1,
        filenamePattern: /Golden_mounting_plate-r1\.step/i,
        envelope: "120.0 × 70.0 × 8.0 mm",
        volume: "64.69 cm³",
        expectedRouteHint: "polymer",
      }),
    );

    await this.step("Golden L bracket generates as a recognizable prismatic template", async () => {
      await this.gotoStudio();
      await this.page.getByRole("button", { name: "L bracket" }).click();
      const downloaded = await this.generateCurrentForm(
        "Golden L bracket",
        "80.0 × 50.0 × 60.0 mm",
        "40.20 cm³",
      );
      return { screenshot: await this.shot("bracket-ready", true), evidence: downloaded };
    });

    await this.step("L bracket Verify rejects CNC turning and completes DFM plus cost", async () =>
      this.verifySelectedRevision({
        revision: 1,
        filenamePattern: /Golden_L_bracket-r1\.step/i,
        envelope: "80.0 × 50.0 × 60.0 mm",
        volume: "40.20 cm³",
        turningMustFail: true,
        expectedRouteHint: "polymer",
      }),
    );

    await this.step("Golden open enclosure generates with an open thin-wall cavity", async () => {
      await this.gotoStudio();
      await this.page.getByRole("button", { name: "Open enclosure" }).click();
      const downloaded = await this.generateCurrentForm(
        "Golden open enclosure",
        "80.0 × 50.0 × 60.0 mm",
        "54.41 cm³",
      );
      return { screenshot: await this.shot("enclosure-ready", true), evidence: downloaded };
    });

    await this.step("Open enclosure routes as thin-wall geometry and rejects CNC turning", async () =>
      this.verifySelectedRevision({
        revision: 1,
        filenamePattern: /Golden_open_enclosure-r1\.step/i,
        envelope: "80.0 × 50.0 × 60.0 mm",
        volume: "54.41 cm³",
        turningMustFail: true,
        expectedRouteHint: "polymer",
      }),
    );

    await this.step("Archive confirmation supports cancel and irreversible confirm branches", async () => {
      await this.gotoStudio();
      await this.page.getByRole("button", { name: /Golden open enclosure Ready/ }).click();
      this.page.once("dialog", async (dialog) => {
        assert(/audit evidence will be retained/i.test(dialog.message()), "Archive dialog omits evidence retention");
        await dialog.dismiss();
      });
      await this.page.getByRole("button", { name: "Archive design" }).click();
      await this.page.getByRole("button", { name: /Golden open enclosure Ready/ }).waitFor();

      this.page.once("dialog", async (dialog) => dialog.accept());
      await this.page.getByRole("button", { name: "Archive design" }).click();
      await this.page.getByRole("button", { name: /Golden open enclosure Ready/ }).waitFor({ state: "detached" });
      return { screenshot: await this.shot("archive-confirmed") };
    });

    await this.step("Design Studio remains usable on a mobile viewport with WebGL fallback", async () => {
      await this.page.setViewportSize({ width: 390, height: 844 });
      await this.gotoStudio();
      await this.page.getByRole("button", { name: /Golden mounting plate Ready/ }).click();
      const fallback = this.page.getByText("Interactive 3D is unavailable in this browser.");
      const canvas = this.page.locator("canvas");
      assert((await fallback.count()) > 0 || (await canvas.count()) > 0, "Neither interactive CAD nor explicit fallback is visible");
      await this.page.getByRole("link", { name: /Download R2 STEP/ }).waitFor();
      await this.page.getByRole("link", { name: /Verify revision 2/ }).waitFor();
      return { screenshot: await this.shot("mobile-design-studio", true) };
    });
  }

  markdown(data) {
    const rows = data.steps
      .map((step) => `| ${step.status.toUpperCase()} | ${step.name} | ${step.durationMs} | ${step.screenshot || ""} |`)
      .join("\n");
    return `# Design Studio Human-Simulated E2E\n\n- Date: ${runId}\n- Status: ${data.status}\n- Health: ${data.health}/100\n- Account: ${this.account || "not created"}\n- Console errors: ${data.consoleErrors.length}\n- Request failures: ${data.requestFailures.length}\n\n| Result | Human journey | ms | Screenshot |\n| --- | --- | ---: | --- |\n${rows}\n`;
  }

  async finish(runError = null) {
    const requestFailures = this.requestFailures
      .filter((failure) => !this.successfulResponses.has(failure.key))
      .map((failure) => failure.message);
    const failed = this.steps.filter((step) => step.status === "fail").length;
    const unexpected = this.consoleErrors.length + requestFailures.length;
    const status = failed === 0 && unexpected === 0 && !runError ? "PASS" : "NEEDS_FIXES";
    const health = status === "PASS" ? 100 : Math.max(0, 100 - failed * 15 - unexpected * 5);
    const data = {
      status,
      health,
      generatedAt: new Date().toISOString(),
      runId,
      durationMs: Date.now() - this.startedAt,
      steps: this.steps,
      issues: this.issues,
      consoleErrors: this.consoleErrors,
      requestFailures,
      error: runError instanceof Error ? runError.message : runError ? String(runError) : null,
    };
    await mkdir(outputRoot, { recursive: true });
    await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
    await writeFile(artifacts.md, this.markdown(data));
    await this.browser?.close();
    console.log(JSON.stringify({
      status,
      health,
      passed: this.steps.filter((step) => step.status === "pass").length,
      failed,
      consoleErrors: this.consoleErrors.length,
      requestFailures: requestFailures.length,
      report: artifacts.md,
      screenshots: screenshotDir,
    }, null, 2));
    if (status !== "PASS") process.exitCode = 1;
  }
}

const runner = new DesignStudioE2E();
let runError = null;
try {
  await runner.start();
  await runner.run();
} catch (error) {
  runError = error;
} finally {
  await runner.finish(runError);
}
