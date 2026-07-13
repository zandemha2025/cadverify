import { randomBytes } from "node:crypto";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  makeGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const sharp = require("sharp");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const clientIp = process.env.E2E_CLIENT_IP || "198.51.100.84";
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(outputRoot, "screenshots", `mobile-recovery-${runId}`);
const reportPath = path.join(outputRoot, `mobile-recovery-${runId}.json`);
const trackedCubeFixture = path.join(repoRoot, "backend", "tests", "assets", "cube.step");
const batchFixture = path.join(screenshotDir, "fixture-cube-step.zip");
const invalidStepFixture = path.join(screenshotDir, "invalid-magic.step");

const OWNED_PATH_IDS = [
  "DES-13",
  "VER-09",
  "FAIL-01",
  "FAIL-03",
  "FAIL-08",
  "FAIL-09",
  "FAIL-10",
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function assertion(name, expected, actual, pass = expected === actual) {
  return { name, expected, actual, pass };
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

async function writeDeterministicStoredZip(sourcePath, destinationPath, entryName) {
  const data = await readFile(sourcePath);
  const name = Buffer.from(entryName, "utf8");
  const checksum = crc32(data);
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0);
  local.writeUInt16LE(20, 4);
  local.writeUInt16LE(0, 6);
  local.writeUInt16LE(0, 8);
  local.writeUInt16LE(0, 10);
  local.writeUInt16LE(0x21, 12);
  local.writeUInt32LE(checksum, 14);
  local.writeUInt32LE(data.length, 18);
  local.writeUInt32LE(data.length, 22);
  local.writeUInt16LE(name.length, 26);
  local.writeUInt16LE(0, 28);

  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0);
  central.writeUInt16LE(20, 4);
  central.writeUInt16LE(20, 6);
  central.writeUInt16LE(0, 8);
  central.writeUInt16LE(0, 10);
  central.writeUInt16LE(0, 12);
  central.writeUInt16LE(0x21, 14);
  central.writeUInt32LE(checksum, 16);
  central.writeUInt32LE(data.length, 20);
  central.writeUInt32LE(data.length, 24);
  central.writeUInt16LE(name.length, 28);
  central.writeUInt16LE(0, 30);
  central.writeUInt16LE(0, 32);
  central.writeUInt16LE(0, 34);
  central.writeUInt16LE(0, 36);
  central.writeUInt32LE(0, 38);
  central.writeUInt32LE(0, 42);

  const localRecord = Buffer.concat([local, name, data]);
  const centralRecord = Buffer.concat([central, name]);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(1, 8);
  end.writeUInt16LE(1, 10);
  end.writeUInt32LE(centralRecord.length, 12);
  end.writeUInt32LE(localRecord.length, 16);
  end.writeUInt16LE(0, 20);
  await writeFile(destinationPath, Buffer.concat([localRecord, centralRecord, end]));
  return { bytes: data.length, zipBytes: localRecord.length + centralRecord.length + end.length, crc32: checksum };
}

class MobileRecoveryRun {
  constructor() {
    this.goldenPaths = {};
    this.supplementalEvidence = {};
    this.steps = [];
    this.issues = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.expectedFaults = [];
    this.pathConsoleErrors = [];
    this.pathRequestFailures = [];
    this.allowExpectedNetworkFailure = false;
    this.expectedHttpStatuses = new Set();
    this.skippedPathIds = new Set(
      (process.env.E2E_SKIP_PATHS || "")
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean),
    );
    this.artifacts = {};
    this.password = "MobileRecovery2026!";
    this.email = `mobile-recovery-${Date.now()}-${randomBytes(3).toString("hex")}@example.test`;
    this.primaryDesignName = `Mobile plate ${randomBytes(3).toString("hex")}`;
    this.networkDesignName = `Recovered plate ${randomBytes(3).toString("hex")}`;
  }

  async launch(viewport = { width: 320, height: 568 }) {
    this.browser = await chromium.launch({
      channel: "chrome",
      headless: true,
      args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
    });
    await this.newContext(viewport);
  }

  async newContext(viewport) {
    this.context = await this.browser.newContext({
      baseURL: baseUrl,
      extraHTTPHeaders: { "x-real-ip": clientIp },
      viewport,
      hasTouch: true,
      isMobile: true,
      acceptDownloads: true,
    });
    this.page = await this.context.newPage();
    this.attachPageEvents();
  }

  attachPageEvents() {
    this.page.on("console", (message) => {
      if (message.type() !== "error") return;
      const value = message.text();
      if (/favicon\.ico|vercel\/speed-insights|_next\/webpack-hmr/i.test(value)) return;
      const expectedStatus = value.match(/status of (\d{3})/i)?.[1];
      if (expectedStatus && this.expectedHttpStatuses.has(Number(expectedStatus))) {
        this.expectedFaults.push(`expected HTTP ${expectedStatus} console diagnostic: ${value}`);
        return;
      }
      if (this.allowExpectedNetworkFailure && /net::ERR_INTERNET_DISCONNECTED/i.test(value)) {
        this.expectedFaults.push(`expected offline console diagnostic: ${value}`);
        return;
      }
      this.consoleErrors.push(value);
      this.pathConsoleErrors.push(value);
    });
    this.page.on("pageerror", (error) => {
      this.consoleErrors.push(error.message);
      this.pathConsoleErrors.push(error.message);
    });
    this.page.on("requestfailed", (request) => {
      const failure = request.failure()?.errorText || "request failed";
      const value = `${request.method()} ${request.url()}: ${failure}`;
      if (/favicon\.ico|vercel\/speed-insights|_next\/webpack-hmr/i.test(value)) return;
      if (failure === "net::ERR_ABORTED" && /[?&]_rsc=/.test(request.url())) return;
      if (
        failure === "net::ERR_ABORTED" &&
        request.method() === "GET" &&
        /\/api\/proxy\/designs\/[^/]+\/revisions(?:\/\d+\/(?:download\.step|preview\.stl))?(?:\?|$)/.test(request.url())
      ) {
        this.expectedFaults.push(value);
        return;
      }
      if (
        failure === "net::ERR_ABORTED" &&
        request.method() === "GET" &&
        /(?:\/icon\.svg$|\/api\/proxy\/(?:designs|batches\?limit=20|machine-inventory|rate-library(?:\/effective)?|governance\/change-requests|catalog\/portfolio|ground-truth|cost-decisions\?limit=(?:8|20))$)/.test(request.url())
      ) {
        this.expectedFaults.push(value);
        return;
      }
      if (
        failure === "net::ERR_ABORTED" &&
        request.method() === "GET" &&
        /\/api\/proxy\/batch\/[A-Z0-9]+(?:\/items\?limit=50)?$/i.test(request.url())
      ) {
        this.expectedFaults.push(value);
        return;
      }
      if (this.allowExpectedNetworkFailure) {
        this.expectedFaults.push(value);
        return;
      }
      this.requestFailures.push(value);
      this.pathRequestFailures.push(value);
    });
  }

  resetPathSignals() {
    this.pathConsoleErrors = [];
    this.pathRequestFailures = [];
  }

  async screenshot(id, suffix = "final") {
    const file = path.join(screenshotDir, `${id.toLowerCase()}-${suffix}.png`);
    await this.page.screenshot({ path: file, fullPage: false });
    return file;
  }

  async bodyText() {
    return (await this.page.locator("body").innerText()).replace(/\s+/g, " ").trim();
  }

  async waitForSavedVerification() {
    await this.page
      .getByRole("button", { name: /^Open the record/ })
      .first()
      .waitFor({ state: "visible", timeout: 150_000 });
    await this.page.waitForLoadState("networkidle", { timeout: 15_000 });
    await this.page.waitForTimeout(250);
  }

  async noHorizontalObstruction() {
    return this.page.evaluate(() => {
      const root = document.documentElement;
      const overflowPx = Math.max(0, root.scrollWidth - window.innerWidth);
      const visibleControlsOutsideViewport = [...document.querySelectorAll("button, a, input, textarea, select")]
        .filter((element) => {
          const style = window.getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
          if (rect.width === 0 || rect.height === 0) return false;
          if (rect.bottom <= 0 || rect.top >= window.innerHeight) return false;
          return rect.left < -1 || rect.right > window.innerWidth + 1;
        })
        .map((element) => (element.getAttribute("aria-label") || element.textContent || element.tagName).trim().slice(0, 80));
      return { overflowPx, visibleControlsOutsideViewport };
    });
  }

  async json(pathname) {
    const response = await this.context.request.get(new URL(pathname, baseUrl).toString());
    assert(response.ok(), `GET ${pathname} returned ${response.status()}`);
    return response.json();
  }

  async designList() {
    const payload = await this.json("/api/proxy/designs");
    return payload.designs;
  }

  async batchList() {
    const payload = await this.json("/api/proxy/batches?limit=20");
    return payload.batches;
  }

  async costDecisionList() {
    const payload = await this.json("/api/proxy/cost-decisions?limit=50");
    return payload.cost_decisions;
  }

  async runPath(id, work) {
    this.resetPathSignals();
    const startedAt = Date.now();
    try {
      const result = await work();
      assert(result?.persona, `${id} omitted persona`);
      assert(result?.preconditions?.length, `${id} omitted preconditions`);
      assert(result?.actions?.length, `${id} omitted actions`);
      assert(result?.visible?.length, `${id} omitted visible observations`);
      assert(result?.assertions?.length, `${id} omitted assertions`);
      for (const item of result.assertions) {
        assert(item.pass === true, `${id} assertion failed: ${item.name}; expected ${item.expected}, got ${item.actual}`);
      }
      assert(this.pathConsoleErrors.length === 0, `${id} console errors: ${this.pathConsoleErrors.join(" | ")}`);
      assert(this.pathRequestFailures.length === 0, `${id} request failures: ${this.pathRequestFailures.join(" | ")}`);
      const screenshot = result.screenshot || (await this.screenshot(id));
      const observed = {
        url: this.page.url(),
        visible: result.visible,
        persisted: result.persisted,
        numeric: result.numeric ?? "not applicable",
        authorization: result.authorization ?? "authenticated organization member",
        recovery: result.recovery ?? "not applicable",
      };
      const envelope = makeGoldenPathEvidence({
        id,
        status: "PASS",
        persona: result.persona,
        preconditions: result.preconditions,
        actions: result.actions,
        observed,
        screenshot,
        consoleErrors: [],
        requestFailures: [],
        assertions: result.assertions,
      });
      const evidence = {
        ...envelope,
        screenshotPath: screenshot,
        persistedOutcome: observed.persisted,
        numericOrAuthorizationOutcome: `${observed.numeric}; ${observed.authorization}`,
        recoveryResult: observed.recovery,
        consoleErrorCount: 0,
        requestFailureCount: 0,
      };
      if (OWNED_PATH_IDS.includes(id)) this.goldenPaths[id] = evidence;
      else this.supplementalEvidence[id] = evidence;
      this.steps.push({ id, status: "PASS", durationMs: Date.now() - startedAt, screenshot });
    } catch (error) {
      const screenshot = await this.screenshot(id, "failure").catch(() => null);
      const message = error instanceof Error ? error.message : String(error);
      this.steps.push({ id, status: "FAIL", durationMs: Date.now() - startedAt, screenshot, error: message });
      this.issues.push({ id, message, screenshot });
      throw error;
    }
  }

  async setViewport(width, height) {
    await this.page.setViewportSize({ width, height });
  }

  async withExpectedHttpStatuses(statuses, work) {
    for (const status of statuses) this.expectedHttpStatuses.add(status);
    try {
      return await work();
    } finally {
      for (const status of statuses) this.expectedHttpStatuses.delete(status);
    }
  }

  async openVerifyWorkspace() {
    const mobileSection = this.page.getByRole("combobox", { name: "Verify workspace section" });
    if (await mobileSection.isVisible()) {
      await mobileSection.focus();
      await this.page.keyboard.press("v");
      await this.page.waitForFunction(() => {
        const section = document.querySelector('select[aria-label="Verify workspace section"]');
        return section instanceof HTMLSelectElement && section.value === "verify";
      });
      return;
    }
    await this.page.getByRole("button", { name: "Verify", exact: true }).click();
  }

  async rapidTouch(button) {
    await button.scrollIntoViewIfNeeded();
    const box = await button.boundingBox();
    assert(box, "button has no touch target");
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    await Promise.all([
      this.page.touchscreen.tap(x, y),
      this.page.touchscreen.tap(x, y),
    ]);
  }

  async login() {
    await this.page.goto("/login", { waitUntil: "domcontentloaded" });
    await this.page.getByLabel("Email").fill(this.email);
    await this.page.getByLabel("Password").fill(this.password);
    await this.page.getByRole("button", { name: /^Log in$/ }).click();
    await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: 20_000 });
  }

  async waitForDesignReady(name, timeout = 90_000) {
    const card = this.page.getByRole("button", {
      name: new RegExp(`${escapeRegExp(name)}\\s+Ready`, "i"),
    }).first();
    await card.waitFor({ state: "visible", timeout });
    await card.click();
    return card;
  }

  async assertCadPreviewVisible(label) {
    const fallback = this.page.getByText("Interactive 3D is unavailable in this browser.");
    if ((await fallback.count()) > 0 && await fallback.first().isVisible()) {
      return { mode: "explicit-static-fallback", brightFraction: null };
    }
    const canvas = this.page.locator("canvas").last();
    await canvas.waitFor({ state: "visible", timeout: 15_000 });
    for (let attempt = 0; attempt < 24; attempt += 1) {
      const png = await canvas.screenshot();
      const { data, info } = await sharp(png).removeAlpha().raw().toBuffer({ resolveWithObject: true });
      let nonBackground = 0;
      const corner = [data[0], data[1], data[2]];
      for (let offset = 0; offset < data.length; offset += info.channels) {
        const distance = Math.abs(data[offset] - corner[0]) + Math.abs(data[offset + 1] - corner[1]) + Math.abs(data[offset + 2] - corner[2]);
        if (distance >= 36) nonBackground += 1;
      }
      const nonBackgroundFraction = nonBackground / (info.width * info.height);
      if (nonBackgroundFraction >= 0.003) {
        return { mode: "interactive-canvas", nonBackgroundFraction };
      }
      await this.page.waitForTimeout(250);
    }
    throw new Error(`${label} CAD preview remained visually blank and exposed no explicit fallback`);
  }

  async signupAndOnboard() {
    await this.runPath("MOB-01", async () => {
      await this.setViewport(320, 568);
      await this.page.goto("/signup", { waitUntil: "domcontentloaded" });
      const email = this.page.getByLabel("Email");
      const password = this.page.getByLabel("Password");
      await email.click();
      await email.pressSequentially(this.email, { delay: 4 });
      await password.click();
      await password.pressSequentially("short", { delay: 20 });
      await password.press("Enter");
      await this.page.getByText("Password must be at least 8 characters.").waitFor();
      this.artifacts.signupValidation = await this.screenshot("MOB-01", "inline-validation");
      await password.fill(this.password);
      await this.page.getByRole("button", { name: /^Create account$/ }).click();
      await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: 20_000 });
      await this.page.goto("/onboarding", { waitUntil: "domcontentloaded" });
      await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: 10_000 });
      const text = await this.bodyText();
      const layout = await this.noHorizontalObstruction();
      const screenshot = await this.screenshot("MOB-01", "authenticated-onboarding");
      return {
        persona: "new organization owner using a 320px phone",
        preconditions: ["fresh unique email", "320x568 touch viewport", "no authenticated session"],
        actions: ["typed invalid password and submitted with the keyboard", "corrected the password", "tapped Create account", "opened /onboarding and followed its redirect"],
        visible: ["Password must be at least 8 characters.", "authenticated Verify workspace after onboarding redirect"],
        persisted: `account ${this.email} was created and remained authenticated across the onboarding redirect`,
        numeric: `viewport 320x568; horizontal overflow ${layout.overflowPx}px`,
        authorization: "new account received an authenticated organization session",
        recovery: "inline validation kept the entered email and allowed correction without navigation",
        screenshot,
        assertions: [
          assertion("signup URL", "/verify", new URL(this.page.url()).pathname),
          assertion("horizontal overflow", 0, layout.overflowPx),
          assertion("visible controls outside viewport", 0, layout.visibleControlsOutsideViewport.length),
          assertion("Verify workspace visible", true, /Verify/i.test(text)),
        ],
      };
    });
  }

  async mobileNavigation() {
    await this.runPath("MOB-02", async () => {
      await this.setViewport(320, 568);
      await this.page.goto("/verify", { waitUntil: "domcontentloaded" });
      await this.page.getByRole("button", { name: "Open navigation" }).click();
      const drawerText = await this.bodyText();
      const screenshot = await this.screenshot("MOB-02", "navigation-drawer");
      await this.page.getByRole("menuitem", { name: "Design Studio" }).click();
      await this.page.waitForURL((url) => url.pathname === "/designs");
      const layout = await this.noHorizontalObstruction();
      return {
        persona: "authenticated operator navigating on a compact phone",
        preconditions: ["authenticated account", "320x568 touch viewport", "Verify workspace loaded"],
        actions: ["tapped Open navigation", "reviewed the full drawer", "tapped Design Studio"],
        visible: ["Design Studio", "Batch run", "Cost decisions", "Organization"],
        persisted: "authenticated session and organization context survived the route change",
        numeric: `drawer viewport 320x568; horizontal overflow ${layout.overflowPx}px`,
        recovery: "navigation remained available after a direct /verify reload",
        screenshot,
        assertions: [
          assertion("drawer includes Batch", true, /Batch run/i.test(drawerText)),
          assertion("drawer includes Organization", true, /Organization/i.test(drawerText)),
          assertion("destination URL", "/designs", new URL(this.page.url()).pathname),
          assertion("horizontal overflow", 0, layout.overflowPx),
        ],
      };
    });
  }

  async designStudioAndDuplicateGuard() {
    await this.runPath("MOB-03", async () => {
      await this.setViewport(375, 812);
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.page.getByRole("heading", { name: "ProofShape Design Studio" }).waitFor();
      const before = await this.designList();
      await this.page.getByLabel("Design name").fill(this.primaryDesignName);
      await this.page.getByLabel("Design note").fill("mobile recovery evidence");
      let posts = 0;
      const countPost = (request) => {
        if (request.method() === "POST" && new URL(request.url()).pathname === "/api/proxy/designs") posts += 1;
      };
      this.page.on("request", countPost);
      const responsePromise = this.page.waitForResponse(
        (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/designs",
        { timeout: 20_000 },
      );
      await this.rapidTouch(this.page.getByRole("button", { name: /^Generate design$/ }));
      await responsePromise;
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.waitForDesignReady(this.primaryDesignName);
      this.page.off("request", countPost);
      const after = await this.designList();
      const matching = after.filter((design) => design.name === this.primaryDesignName);
      const body = await this.bodyText();
      const layout = await this.noHorizontalObstruction();
      const visual = await this.assertCadPreviewVisible(this.primaryDesignName);
      const downloadLink = this.page.getByRole("link", { name: /^Download R1 STEP$/ });
      const [download] = await Promise.all([
        this.page.waitForEvent("download", { timeout: 20_000 }),
        downloadLink.click(),
      ]);
      const downloadPath = await download.path();
      assert(downloadPath, "STEP export did not produce a file");
      const stepBytes = (await readFile(downloadPath)).length;
      const screenshot = await this.screenshot("MOB-03", "ready-after-refresh");
      this.designId = matching[0]?.id;
      return {
        persona: "design engineer generating CAD from a 375px phone",
        preconditions: ["authenticated account", "375x812 touch viewport", `${before.length} designs before submission`],
        actions: ["filled design name and note", "double-tapped Generate design", "refreshed immediately after POST", "waited for Ready", "downloaded the STEP export"],
        visible: [this.primaryDesignName, "Ready", "80.0 × 50.0 × 6.0 mm", "23.32 cm³", "Download R1 STEP"],
        persisted: `exactly one ${this.primaryDesignName} project persisted and returned Ready after refresh`,
        numeric: `POST requests ${posts}; design delta ${after.length - before.length}; STEP bytes ${stepBytes}; preview ${visual.mode}`,
        recovery: "queued generation survived reload and resumed from the durable project list",
        screenshot,
        assertions: [
          assertion("design POST count after double tap", 1, posts),
          assertion("persisted design count", 1, matching.length),
          assertion("design list delta", 1, after.length - before.length),
          assertion("measured envelope visible", true, /80\.0 × 50\.0 × 6\.0 mm/.test(body)),
          assertion("measured volume visible", true, /23\.32 cm³/.test(body)),
          assertion("STEP export non-empty", true, stepBytes > 128),
          assertion("CAD preview oracle", true, visual.mode === "explicit-static-fallback" || (visual.nonBackgroundFraction ?? 0) >= 0.003),
          assertion("horizontal overflow", 0, layout.overflowPx),
        ],
      };
    });

    await this.runPath("REC-05", async () => {
      const designs = await this.designList();
      const matching = designs.filter((design) => design.name === this.primaryDesignName);
      const screenshot = await this.screenshot("REC-05", "single-persisted-project");
      return {
        persona: "mobile user prone to rapid repeated taps",
        preconditions: ["375x812 touch viewport", "two physical tap events targeted Generate design", "generation completed"],
        actions: ["issued two same-tick touch taps", "counted POST requests", "reloaded the project list", "queried persisted organization designs"],
        visible: [`one ${this.primaryDesignName} card`, "Ready revision 1"],
        persisted: "one project and one revision persisted; no duplicate project or lost result",
        numeric: `matching persisted projects ${matching.length}`,
        recovery: "reload reconciled the single durable project without replaying submission",
        screenshot,
        assertions: [
          assertion("matching projects", 1, matching.length),
          assertion("current revision", 1, matching[0]?.current_revision),
          assertion("status", "ready", matching[0]?.status),
        ],
      };
    });
  }

  async verifyDecisionAndRefresh() {
    await this.runPath("MOB-04", async () => {
      await this.setViewport(390, 844);
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.waitForDesignReady(this.primaryDesignName);
      await this.page.getByRole("link", { name: /^Verify revision 1$/ }).click();
      await this.page.waitForURL((url) => url.pathname === "/verify");
      this.allowExpectedNetworkFailure = true;
      try {
        await this.page.reload({ waitUntil: "domcontentloaded" });
      } finally {
        this.allowExpectedNetworkFailure = false;
      }
      await this.page.getByText("80.0 × 50.0 × 6.0 mm", { exact: false }).first().waitFor({ timeout: 120_000 });
      await this.page.getByText("23.32 cm³", { exact: false }).first().waitFor();
      await this.waitForSavedVerification();
      const body = await this.bodyText();
      const layout = await this.noHorizontalObstruction();
      const screenshot = await this.screenshot("MOB-04", "verified-decision");
      this.verifyUrl = this.page.url();
      return {
        persona: "manufacturing engineer verifying a generated revision on a 390px phone",
        preconditions: ["ready R1 design", "390x844 touch viewport", "no declared machine rate"],
        actions: ["tapped Verify revision 1", "reloaded during verification", "waited for measured geometry and should-cost", "reviewed the saved record action"],
        visible: ["80.0 × 50.0 × 6.0 mm", "23.32 cm³", "FDM / FFF", "Open the record"],
        persisted: "the exact design revision reopened after refresh and produced a durable verification/cost record",
        numeric: "envelope 80.0x50.0x6.0 mm; volume 23.32 cm³; quantity scenario retained",
        authorization: "record remained scoped to the authenticated organization",
        recovery: "refresh during verification resumed the imported design and completed without re-upload",
        screenshot,
        assertions: [
          assertion("Verify URL", "/verify", new URL(this.page.url()).pathname),
          assertion("measured envelope", true, /80\.0 × 50\.0 × 6\.0 mm/.test(body)),
          assertion("measured volume", true, /23\.32 cm³/.test(body)),
          assertion("record action visible", true, /Open the record/i.test(body)),
          assertion("horizontal overflow", 0, layout.overflowPx),
        ],
      };
    });

    await this.runPath("REC-01", async () => {
      const body = await this.bodyText();
      const screenshot = await this.screenshot("REC-01", "refresh-complete");
      return {
        persona: "mobile operator refreshing while a compute job is active",
        preconditions: ["verification started from a persisted design revision", "page reloaded before final result", "390x844 viewport"],
        actions: ["started verification", "reloaded the route", "waited for the restored job", "checked measured and cost outcomes"],
        visible: ["measured envelope", "measured volume", "Open the record"],
        persisted: "design ID and revision query remained in the URL and the completed result stayed available",
        numeric: "80.0x50.0x6.0 mm and 23.32 cm³ matched the generated artifact",
        recovery: "job resumed after refresh with no duplicate record action and no lost design context",
        screenshot,
        assertions: [
          assertion("design query retained", true, new URL(this.page.url()).searchParams.has("design")),
          assertion("revision query retained", "1", new URL(this.page.url()).searchParams.get("revision")),
          assertion("completion remains visible", true, /23\.32 cm³/.test(body)),
        ],
      };
    });
  }

  async designStudioMobileContract() {
    await this.runPath("DES-13", async () => {
      await this.setViewport(375, 812);
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.waitForDesignReady(this.primaryDesignName);
      const before = (await this.designList()).find((design) => design.name === this.primaryDesignName);
      assert(before?.revision?.geometry_hash, "DES-13 ready revision omitted geometry hash");
      const body = await this.bodyText();
      const visual = await this.assertCadPreviewVisible("DES-13 mobile preview");
      const layout = await this.noHorizontalObstruction();
      const [download] = await Promise.all([
        this.page.waitForEvent("download", { timeout: 20_000 }),
        this.page.getByRole("link", { name: /^Download R1 STEP$/ }).click(),
      ]);
      const exportedPath = await download.path();
      assert(exportedPath, "DES-13 mobile STEP download did not produce a file");
      const exportedBytes = (await readFile(exportedPath)).length;
      const screenshot = await this.screenshot("DES-13", "mobile-artifact-controls");
      await this.page.getByRole("link", { name: /^Verify revision 1$/ }).click();
      await this.page.waitForURL((url) => url.pathname === "/verify" && url.searchParams.get("revision") === "1");
      await this.page.getByText("23.32 cm³", { exact: false }).first().waitFor({ timeout: 120_000 });
      const verifyUrl = this.page.url();
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      const after = (await this.designList()).find((design) => design.name === this.primaryDesignName);
      return {
        persona: "design engineer using the complete Design Studio handoff on a mobile browser",
        preconditions: ["ready organization-owned R1 mounting plate", "375x812 touch viewport", "browser download support"],
        actions: ["selected the ready project", "validated the rendered CAD preview", "downloaded R1 STEP", "tapped Verify revision 1", "waited for the measured Verify outcome", "reopened Design Studio"],
        visible: [this.primaryDesignName, "80.0 × 50.0 × 6.0 mm", "23.32 cm³", before.revision.geometry_hash.slice(0, 12), "Download R1 STEP", "Verify revision 1"],
        persisted: { designId: before.id, revisionId: before.revision.id, revision: before.current_revision, geometryHashBefore: before.revision.geometry_hash, geometryHashAfter: after?.revision?.geometry_hash },
        numeric: { viewport: "375x812", exportBytes: exportedBytes, previewMode: visual.mode, horizontalOverflowPx: layout.overflowPx },
        authorization: "download and Verify handoff succeeded through the same authenticated organization session",
        recovery: "returning from Verify left the same project, revision, and artifact hash selected and available",
        screenshot,
        assertions: [
          assertion("mobile horizontal overflow", 0, layout.overflowPx),
          assertion("mobile controls outside viewport", 0, layout.visibleControlsOutsideViewport.length),
          assertion("dimensions visible", true, /80\.0 × 50\.0 × 6\.0 mm/.test(body)),
          assertion("hash prefix visible", true, body.includes(before.revision.geometry_hash.slice(0, 12))),
          assertion("CAD preview oracle", true, visual.mode === "explicit-static-fallback" || (visual.nonBackgroundFraction ?? 0) >= 0.003),
          assertion("STEP export non-empty", true, exportedBytes > 128),
          assertion("Verify revision query", "1", new URL(verifyUrl).searchParams.get("revision")),
          assertion("design identity unchanged", before.id, after?.id),
          assertion("revision identity unchanged", before.revision.id, after?.revision?.id),
          assertion("artifact hash unchanged", before.revision.geometry_hash, after?.revision?.geometry_hash),
        ],
      };
    });
  }

  async batchTablet() {
    await this.runPath("MOB-05", async () => {
      await this.setViewport(768, 1024);
      await this.page.goto("/batch", { waitUntil: "domcontentloaded" });
      const before = await this.batchList();
      const fileInput = this.page.locator('input[type="file"][accept=".zip"]').first();
      await fileInput.setInputFiles(batchFixture);
      let posts = 0;
      const countPost = (request) => {
        if (request.method() === "POST" && new URL(request.url()).pathname === "/api/proxy/batch") posts += 1;
      };
      this.page.on("request", countPost);
      await this.rapidTouch(this.page.getByRole("button", { name: /^Start batch$/ }));
      await this.page.waitForURL((url) => /^\/batch\/[A-Z0-9]+$/i.test(url.pathname), { timeout: 30_000 });
      this.page.off("request", countPost);
      this.batchId = new URL(this.page.url()).pathname.split("/").pop();
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.page.getByText(/0 \/ 1|1 \/ 1/).first().waitFor({ timeout: 30_000 });
      await this.page.getByRole("button", { name: "Download CSV" }).waitFor({ timeout: 120_000 });
      const [download] = await Promise.all([
        this.page.waitForEvent("download", { timeout: 20_000 }),
        this.page.getByRole("button", { name: "Download CSV" }).click(),
      ]);
      const csvPath = await download.path();
      assert(csvPath, "batch CSV export did not produce a file");
      const csv = await readFile(csvPath, "utf8");
      const after = await this.batchList();
      const matches = after.filter((batch) => batch.batch_ulid === this.batchId);
      const body = await this.bodyText();
      const layout = await this.noHorizontalObstruction();
      const screenshot = await this.screenshot("MOB-05", "batch-terminal");
      return {
        persona: "operations engineer running a batch on a tablet",
        preconditions: ["authenticated organization", "768x1024 touch viewport", "ZIP containing one real STEP file"],
        actions: ["selected the ZIP", "double-tapped Start batch", "reloaded the durable batch route", "waited for terminal counters", "downloaded CSV"],
        visible: [`Batch ${this.batchId.slice(0, 12)}`, "1 / 1", "Download CSV"],
        persisted: `batch ${this.batchId} remained addressable after refresh and appeared once in Recent batches`,
        numeric: `POST requests ${posts}; total items 1; CSV bytes ${Buffer.byteLength(csv)}`,
        recovery: "batch status resumed from its persisted ID after refresh",
        screenshot,
        assertions: [
          assertion("batch POST count after double tap", 1, posts),
          assertion("persisted batch count", 1, matches.length),
          assertion("batch list delta", 1, after.length - before.length),
          assertion("terminal counter", true, /1 \/ 1/.test(body)),
          assertion("CSV has filename column", true, /filename/i.test(csv)),
          assertion("horizontal overflow", 0, layout.overflowPx),
        ],
      };
    });
  }

  async tabletAndDialog() {
    await this.runPath("MOB-06", async () => {
      await this.setViewport(820, 1180);
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.waitForDesignReady(this.primaryDesignName);
      const dialogPromise = this.page.waitForEvent("dialog");
      const archiveClickPromise = this.page.getByRole("button", { name: "Archive design" }).click();
      const dialog = await dialogPromise;
      const dialogMessage = dialog.message();
      await dialog.dismiss();
      await archiveClickPromise;
      await this.page.getByRole("heading", { name: this.primaryDesignName, exact: true }).waitFor();
      const routes = ["/designs", "/batch", "/cost-decisions"];
      const routeLayouts = {};
      for (const route of routes) {
        await this.page.goto(route, { waitUntil: "domcontentloaded" });
        routeLayouts[route] = await this.noHorizontalObstruction();
      }
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.waitForDesignReady(this.primaryDesignName);
      const screenshot = await this.screenshot("MOB-06", "tablet-design-dialog-dismissed");
      return {
        persona: "tablet operator reviewing dialogs and dense workspaces",
        preconditions: ["ready design exists", "820x1180 touch viewport", "authenticated session"],
        actions: ["opened Archive design confirmation", "dismissed it", "visited Designs, Batch, and Cost decisions", "checked viewport bounds"],
        visible: [dialogMessage, this.primaryDesignName, "Ready"],
        persisted: "dismissed archive left the design and its R1 evidence unchanged",
        numeric: `overflow px: ${routes.map((route) => `${route}=${routeLayouts[route].overflowPx}`).join(", ")}`,
        recovery: "destructive dialog dismissal returned focus to the intact design",
        screenshot,
        assertions: [
          assertion("archive confirmation names retention", true, /audit evidence will be retained/i.test(dialogMessage)),
          ...routes.map((route) => assertion(`${route} horizontal overflow`, 0, routeLayouts[route].overflowPx)),
          assertion("design still persisted", 1, (await this.designList()).filter((design) => design.name === this.primaryDesignName).length),
        ],
      };
    });
  }

  async responsiveKeyboardContract() {
    await this.runPath("VER-09", async () => {
      const viewports = [
        { width: 375, height: 812 },
        { width: 768, height: 1024 },
        { width: 1440, height: 900 },
      ];
      const observations = [];
      this.artifacts.ver09Viewports = {};
      const expected = (await this.designList()).find((design) => design.name === this.primaryDesignName);
      assert(expected, "VER-09 primary design was not persisted");
      for (const viewport of viewports) {
        await this.setViewport(viewport.width, viewport.height);
        await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
        const card = this.page.getByRole("button", {
          name: new RegExp(`${escapeRegExp(this.primaryDesignName)}\\s+Ready`, "i"),
        }).first();
        await card.waitFor({ state: "visible", timeout: 30_000 });
        await card.focus();
        await this.page.keyboard.press("Enter");
        await this.page.getByRole("heading", { name: this.primaryDesignName, exact: true }).waitFor();
        const verifyLink = this.page.getByRole("link", { name: /^Verify revision 1$/ });
        await verifyLink.focus();
        await this.page.keyboard.press("Enter");
        await this.page.waitForURL((url) => url.pathname === "/verify" && url.searchParams.get("revision") === "1");
        await this.page.getByText("23.32 cm³", { exact: false }).first().waitFor({ timeout: 120_000 });
        let recordsControl;
        if (viewport.width <= 760) {
          recordsControl = this.page.getByRole("combobox", { name: "Verify workspace section" });
          await recordsControl.focus();
          await this.page.keyboard.press("r");
        } else {
          recordsControl = this.page.getByRole("button", { name: "Records", exact: true });
          await recordsControl.focus();
          await this.page.keyboard.press("Enter");
        }
        await this.page.getByRole("heading", { name: "Records", exact: true }).waitFor();
        const layout = await this.noHorizontalObstruction();
        const url = this.page.url();
        const key = `${viewport.width}x${viewport.height}`;
        const screenshot = await this.screenshot("VER-09", key);
        this.artifacts.ver09Viewports[key] = screenshot;
        observations.push({
          key,
          url,
          layout,
          recordsControl: viewport.width <= 760 ? "keyboard-operated section select" : "keyboard-operated Records button",
          design: new URL(url).searchParams.get("design"),
          revision: new URL(url).searchParams.get("revision"),
        });
      }
      const after = (await this.designList()).find((design) => design.name === this.primaryDesignName);
      const screenshot = this.artifacts.ver09Viewports["1440x900"];
      return {
        persona: "keyboard-only manufacturing reviewer moving from phone to tablet to desktop",
        preconditions: ["completed R1 verification", "same authenticated organization session", "375x812, 768x1024, and 1440x900 viewports"],
        actions: ["focused the ready design card and pressed Enter", "focused Verify revision 1 and pressed Enter", "used the responsive Records control from the keyboard", "repeated at all three viewport classes"],
        visible: observations.map(({ key }) => `${key}: ready design, Verify result, Records navigation, measured 23.32 cm³`),
        persisted: { designId: expected.id, revisionId: expected.revision?.id, afterDesignId: after?.id, afterRevisionId: after?.revision?.id },
        numeric: observations.map(({ key, layout }) => ({ viewport: key, horizontalOverflowPx: layout.overflowPx, obstructedControls: layout.visibleControlsOutsideViewport.length })),
        authorization: "the same signed-in organization record and revision remained reachable at every viewport",
        recovery: "viewport changes and keyboard navigation did not reset, duplicate, or lose the selected revision",
        screenshot,
        assertions: [
          ...observations.flatMap(({ key, layout, design, revision }) => [
            assertion(`${key} horizontal overflow`, 0, layout.overflowPx),
            assertion(`${key} obstructed controls`, 0, layout.visibleControlsOutsideViewport.length),
            assertion(`${key} design query`, expected.id, design),
            assertion(`${key} revision query`, "1", revision),
          ]),
          assertion("design identity after responsive loop", expected.id, after?.id),
          assertion("revision identity after responsive loop", expected.revision?.id, after?.revision?.id),
        ],
      };
    });
  }

  async invalidCadRecovery() {
    await this.runPath("FAIL-01", async () => {
      await this.setViewport(375, 812);
      await this.page.goto("/verify", { waitUntil: "domcontentloaded" });
      await this.openVerifyWorkspace();
      const input = this.page.locator('input[type="file"][accept*=".stl"]').first();
      const decisionsBefore = await this.costDecisionList();
      await this.withExpectedHttpStatuses([400], async () => {
        await input.setInputFiles(invalidStepFixture);
        await this.page.getByText("We couldn’t read this file.", { exact: true }).waitFor({ timeout: 120_000 });
      });
      const failureText = await this.bodyText();
      const failureScreenshot = await this.screenshot("FAIL-01", "invalid-native-format");
      this.artifacts.fail01Invalid = failureScreenshot;
      await input.setInputFiles(trackedCubeFixture);
      await this.page.getByText("20.0 × 15.0 × 10.0 mm", { exact: false }).first().waitFor({ timeout: 150_000 });
      const recoveryText = await this.bodyText();
      const decisionsAfter = await this.costDecisionList();
      const cubeDecisions = decisionsAfter.filter((decision) => decision.filename === "cube.step");
      const recoveryScreenshot = await this.screenshot("FAIL-01", "valid-step-recovered");
      this.artifacts.fail01Recovery = recoveryScreenshot;
      return {
        persona: "mobile manufacturing engineer correcting an unreadable STEP exchange export",
        preconditions: ["authenticated Verify workspace", "375x812 viewport", "a .step file with invalid magic bytes", "tracked backend/tests/assets/cube.step"],
        actions: ["selected the invalid .step file", "read the exact file-format guidance", "selected the tracked valid cube.step in the same session", "waited for measured geometry and saved outcome"],
        visible: ["We couldn’t read this file.", "Re-export the original part as a clean STL, STEP, STP, IGES, or IGS file", "20.0 × 15.0 × 10.0 mm"],
        persisted: { decisionsBefore: decisionsBefore.length, decisionsAfter: decisionsAfter.length, recoveredCubeDecisionIds: cubeDecisions.map((decision) => decision.id) },
        numeric: { invalidRowsCreated: decisionsAfter.length - decisionsBefore.length - cubeDecisions.length, recoveredCubeDecisions: cubeDecisions.length, envelopeMm: [20, 15, 10] },
        authorization: "the same authenticated organization session handled rejection and recovery",
        recovery: "the correct tracked STEP succeeded without account recreation or session replacement",
        screenshot: failureScreenshot,
        assertions: [
          assertion("invalid file title", true, /We couldn’t read this file\./.test(failureText)),
          assertion("clean export guidance", true, /re-export.*STL, STEP, STP, IGES, or IGS/i.test(failureText)),
          assertion("invalid magic not mislabeled tessellation", false, /This part couldn’t be tessellated/i.test(failureText)),
          assertion("valid cube envelope", true, /20\.0 × 15\.0 × 10\.0 mm/.test(recoveryText)),
          assertion("recovered cube decision exists", true, cubeDecisions.length >= 1),
          assertion("session stayed on Verify", "/verify", new URL(this.page.url()).pathname),
        ],
      };
    });
  }

  async verifyCapacityRecovery() {
    await this.runPath("FAIL-03", async () => {
      await this.setViewport(390, 844);
      await this.page.goto("/verify", { waitUntil: "domcontentloaded" });
      await this.openVerifyWorkspace();
      const input = this.page.locator('input[type="file"][accept*=".stl"]').first();
      const decisionsBefore = await this.costDecisionList();
      let injectedResponses = 0;
      const handler = async (route) => {
        const pathname = new URL(route.request().url()).pathname;
        const isComputeRequest =
          pathname === "/api/proxy/validate" ||
          pathname === "/api/proxy/validate/cost";
        if (route.request().method() === "POST" && isComputeRequest) {
          injectedResponses += 1;
          await route.fulfill({
            status: 429,
            headers: { "retry-after": "2" },
            contentType: "application/json",
            body: JSON.stringify({
              detail: {
                code: "org_at_capacity",
                message: "this organization has reached its concurrent-analysis limit of 1",
              },
            }),
          });
          return;
        }
        await route.continue();
      };
      await this.page.route("**/api/proxy/validate**", handler);
      await this.withExpectedHttpStatuses([429], async () => {
        await input.setInputFiles(trackedCubeFixture);
        await this.page.getByText("Verification is temporarily busy.", { exact: true }).waitFor({ timeout: 60_000 });
      });
      const failureText = await this.bodyText();
      const failureScreenshot = await this.screenshot("FAIL-03", "capacity-429");
      this.artifacts.fail03Capacity = failureScreenshot;
      await this.page.unroute("**/api/proxy/validate**", handler);
      await this.page.getByRole("button", { name: "Retry verification →" }).click();
      await this.page.getByText("20.0 × 15.0 × 10.0 mm", { exact: false }).first().waitFor({ timeout: 150_000 });
      const recoveredText = await this.bodyText();
      const decisionsAfter = await this.costDecisionList();
      const screenshot = await this.screenshot("FAIL-03", "capacity-retry-complete");
      return {
        persona: "mobile engineer retrying Verify after organization capacity is released",
        preconditions: ["tracked cube.step already selected in Verify", "390x844 viewport", "both analysis POSTs injected as 429 capacity responses"],
        actions: ["selected cube.step once", "observed capacity refusal", "restored the analysis routes", "tapped Retry verification without reopening the file picker", "waited for measured completion"],
        visible: ["Verification is temporarily busy.", "No routing, DFM, or should-cost was computed", "Retry verification →", "20.0 × 15.0 × 10.0 mm"],
        persisted: { decisionsBefore: decisionsBefore.length, decisionsAfter: decisionsAfter.length, selectedFilename: "cube.step" },
        numeric: { injected429Responses: injectedResponses, decisionDeltaAfterRetry: decisionsAfter.length - decisionsBefore.length },
        authorization: "capacity was bounded to the authenticated organization and did not disclose other work",
        recovery: "one explicit retry reused the selected CAD bytes and completed after capacity returned",
        screenshot: failureScreenshot,
        assertions: [
          assertion("both Verify compute requests rejected", 2, injectedResponses),
          assertion("capacity title", true, /Verification is temporarily busy\./.test(failureText)),
          assertion("no compute claim", true, /No routing, DFM, or should-cost was computed/i.test(failureText)),
          assertion("retry action visible", true, /Retry verification/.test(failureText)),
          assertion("retry measured cube", true, /20\.0 × 15\.0 × 10\.0 mm/.test(recoveredText)),
          assertion("no duplicate durable decision", true, decisionsAfter.length - decisionsBefore.length <= 1),
        ],
      };
    });
  }

  async costHistoryRecovery() {
    await this.runPath("FAIL-08", async () => {
      await this.setViewport(390, 844);
      const decisionsBefore = await this.costDecisionList();
      assert(decisionsBefore.length > 0, "FAIL-08 requires at least one durable decision");
      let injected = 0;
      const handler = async (route) => {
        if (route.request().method() === "GET") {
          injected += 1;
          await route.fulfill({
            status: 503,
            contentType: "application/json",
            body: JSON.stringify({ detail: { message: "Cost history is temporarily unavailable. Retry shortly." } }),
          });
          return;
        }
        await route.continue();
      };
      await this.page.route("**/api/proxy/cost-decisions**", handler);
      await this.withExpectedHttpStatuses([503], async () => {
        await this.page.goto("/cost-decisions", { waitUntil: "domcontentloaded" });
        await this.page.getByRole("button", { name: "Try again" }).waitFor({ timeout: 30_000 });
      });
      const failureText = await this.bodyText();
      const failureScreenshot = await this.screenshot("FAIL-08", "cost-history-503");
      this.artifacts.fail08Outage = failureScreenshot;
      await this.page.unroute("**/api/proxy/cost-decisions**", handler);
      await this.page.getByRole("button", { name: "Try again" }).click();
      await this.page.getByText(decisionsBefore[0].label || decisionsBefore[0].filename, { exact: true }).waitFor({ timeout: 30_000 });
      const decisionsAfter = await this.costDecisionList();
      const recoveredText = await this.bodyText();
      const screenshot = await this.screenshot("FAIL-08", "cost-history-restored");
      return {
        persona: "mobile cost reviewer recovering a durable history after API degradation",
        preconditions: [`${decisionsBefore.length} durable cost decisions`, "390x844 viewport", "cost-history GETs injected as 503"],
        actions: ["opened Cost history", "read the unavailable state", "restored the API", "tapped Try again", "compared the recovered durable list"],
        visible: ["Cost history is temporarily unavailable. Retry shortly.", "Try again", decisionsBefore[0].label || decisionsBefore[0].filename],
        persisted: { decisionIdsBefore: decisionsBefore.map((decision) => decision.id), decisionIdsAfter: decisionsAfter.map((decision) => decision.id) },
        numeric: { injected503Responses: injected, decisionsBefore: decisionsBefore.length, decisionsAfter: decisionsAfter.length },
        authorization: "only the signed-in organization history reappeared after recovery",
        recovery: "Try again restored the same durable decision IDs and never rendered an empty-history success state",
        screenshot: failureScreenshot,
        assertions: [
          assertion("503 injected", true, injected >= 1),
          assertion("unavailable copy visible", true, /temporarily unavailable/i.test(failureText)),
          assertion("no empty history lie", false, /No saved cost decisions yet/i.test(failureText)),
          assertion("recovered first decision visible", true, recoveredText.includes(decisionsBefore[0].label || decisionsBefore[0].filename)),
          assertion("decision IDs unchanged", JSON.stringify(decisionsBefore.map((decision) => decision.id)), JSON.stringify(decisionsAfter.map((decision) => decision.id))),
        ],
      };
    });
  }

  async workerStatusRecovery() {
    await this.runPath("FAIL-10", async () => {
      await this.setViewport(768, 1024);
      const statusPath = `/api/proxy/batch/${this.batchId}`;
      let injected = false;
      const handler = async (route) => {
        if (!injected && route.request().method() === "GET" && new URL(route.request().url()).pathname === statusPath) {
          injected = true;
          await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "worker status unavailable" }) });
          return;
        }
        await route.continue();
      };
      await this.page.route(`**${statusPath}`, handler);
      await this.withExpectedHttpStatuses([500], async () => {
        await this.page.goto(`/batch/${this.batchId}`, { waitUntil: "domcontentloaded" });
        await this.page.getByText("Could not load progress").waitFor({ timeout: 20_000 });
      });
      const failureCopy = await this.bodyText();
      await this.page.unroute(`**${statusPath}`, handler);
      await this.page.getByRole("button", { name: "Try again" }).first().click();
      await this.page.getByText(/1 \/ 1/).first().waitFor({ timeout: 30_000 });
      const recovered = await this.bodyText();
      const screenshot = await this.screenshot("FAIL-10", "worker-status-recovered");
      return {
        persona: "batch operator recovering from a Redis-backed worker-status degradation",
        preconditions: ["persisted terminal batch", "tablet viewport", "one injected 500 status response representing degraded status infrastructure"],
        actions: ["opened the batch", "observed actionable worker-status failure", "tapped Try again", "reloaded persisted counters"],
        visible: ["Could not load progress", "Try again", "1 / 1"],
        persisted: `batch ${this.batchId} and its one item remained unchanged across the failed poll`,
        numeric: "injected status 500; recovered counter 1/1",
        recovery: "Try again cleared the degraded state and restored live persisted progress without an orphan row",
        screenshot,
        assertions: [
          assertion("500 was injected", true, injected),
          assertion("failure copy is actionable", true, /Try again/i.test(failureCopy)),
          assertion("saved data assurance visible", true, /saved data is unchanged/i.test(failureCopy)),
          assertion("progress recovered", true, /1 \/ 1/.test(recovered)),
        ],
      };
    });
  }

  async apiFailureMatrix() {
    await this.runPath("REC-03", async () => {
      await this.setViewport(375, 812);
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      const before = await this.designList();
      const statuses = [401, 403, 404, 409, 422, 429, 500];
      const actionPattern = {
        401: /sign in again/i,
        403: /organization admin/i,
        404: /return to the list/i,
        409: /refresh the page/i,
        422: /review the input/i,
        429: /try again in 2 seconds/i,
        500: /try again/i,
      };
      const observations = {};
      this.artifacts.apiStatusScreenshots = {};
      for (const status of statuses) {
        let handled = false;
        const handler = async (route) => {
          if (!handled && route.request().method() === "POST") {
            handled = true;
            await route.fulfill({
              status,
              headers: status === 429 ? { "retry-after": "2" } : {},
              contentType: "application/json",
              body: JSON.stringify({ detail: { message: `Injected ${status}` } }),
            });
            return;
          }
          await route.continue();
        };
        await this.page.route("**/api/proxy/designs", handler);
        const alert = this.page
          .getByRole("alert")
          .filter({ has: this.page.getByRole("button", { name: "Dismiss" }) });
        await this.withExpectedHttpStatuses([status], async () => {
          await this.page.getByRole("button", { name: /^Generate design$/ }).click();
          await alert.waitFor({ timeout: 20_000 });
        });
        const text = (await alert.innerText()).replace(/\s+/g, " ").trim();
        assert(actionPattern[status].test(text), `${status} did not expose its recovery action: ${text}`);
        observations[status] = text;
        this.artifacts.apiStatusScreenshots[status] = await this.screenshot("REC-03", `status-${status}`);
        await this.page.unroute("**/api/proxy/designs", handler);
        await alert.getByRole("button", { name: "Dismiss" }).click();
      }
      const after = await this.designList();
      const screenshot = this.artifacts.apiStatusScreenshots[500];
      return {
        persona: "mobile design operator encountering API policy and service failures",
        preconditions: ["authenticated account", "375x812 viewport", "one controlled response for each 401/403/404/409/422/429/500"],
        actions: statuses.map((status) => `submitted Generate design, read the ${status} alert, and dismissed it`),
        visible: statuses.map((status) => `${status}: ${observations[status]}`),
        persisted: "all seven failed submissions left the durable design count unchanged",
        numeric: `statuses ${statuses.join(",")}; design delta ${after.length - before.length}`,
        authorization: "401 required sign-in and 403 directed the user to an organization admin",
        recovery: "every status rendered a bounded next action and returned to a usable form",
        screenshot,
        assertions: [
          ...statuses.map((status) => assertion(`${status} actionable copy`, true, actionPattern[status].test(observations[status]))),
          assertion("failed submissions persisted no designs", 0, after.length - before.length),
          assertion("status screenshots captured", statuses.length, Object.keys(this.artifacts.apiStatusScreenshots).length),
        ],
      };
    });
  }

  async networkRecovery() {
    await this.runPath("REC-04", async () => {
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      const before = await this.designList();
      await this.page.getByLabel("Design name").fill(this.networkDesignName);
      let aborted = false;
      const handler = async (route) => {
        if (!aborted && route.request().method() === "POST") {
          aborted = true;
          await route.abort("internetdisconnected");
          return;
        }
        await route.continue();
      };
      await this.page.route("**/api/proxy/designs", handler);
      this.allowExpectedNetworkFailure = true;
      await this.page.getByRole("button", { name: /^Generate design$/ }).click();
      await this.page.getByText(/Connection interrupted during the design request/i).waitFor({ timeout: 20_000 });
      this.allowExpectedNetworkFailure = false;
      this.artifacts.networkFailure = await this.screenshot("REC-04", "offline-message");
      await this.page.unroute("**/api/proxy/designs", handler);
      await this.page.getByRole("button", { name: "Dismiss" }).click();
      await this.page.getByRole("button", { name: /^Generate design$/ }).click();
      await this.waitForDesignReady(this.networkDesignName);
      const after = await this.designList();
      const matching = after.filter((design) => design.name === this.networkDesignName);
      const screenshot = await this.screenshot("REC-04", "network-retry-ready");
      return {
        persona: "mobile designer whose network drops during submit",
        preconditions: ["authenticated account", "ready Design Studio form", "first POST aborted as internet disconnected"],
        actions: ["tapped Generate design", "observed connection recovery copy", "restored network routing", "dismissed the alert", "tapped Generate design once more"],
        visible: ["Connection interrupted during the design request", this.networkDesignName, "Ready"],
        persisted: "the interrupted request created zero projects; the explicit retry created exactly one ready project",
        numeric: `design delta ${after.length - before.length}; matching recovered projects ${matching.length}`,
        recovery: "form values remained available and one retry completed without duplication",
        screenshot,
        assertions: [
          assertion("network fault injected", true, aborted),
          assertion("matching recovered designs", 1, matching.length),
          assertion("total design delta", 1, after.length - before.length),
          assertion("recovered status", "ready", matching[0]?.status),
        ],
      };
    });
  }

  async historyRecovery() {
    await this.runPath("REC-06", async () => {
      await this.setViewport(390, 844);
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.waitForDesignReady(this.primaryDesignName);
      await this.page.getByRole("link", { name: /^Verify revision 1$/ }).click();
      await this.page.waitForURL((url) => url.pathname === "/verify");
      const forwardUrl = this.page.url();
      await this.page.goBack({ waitUntil: "domcontentloaded" });
      await this.page.waitForURL((url) => url.pathname === "/designs");
      await this.waitForDesignReady(this.primaryDesignName);
      await this.page.goForward({ waitUntil: "domcontentloaded" });
      await this.page.waitForURL((url) => url.pathname === "/verify");
      await this.page.getByText("23.32 cm³", { exact: false }).first().waitFor({ timeout: 120_000 });
      await this.waitForSavedVerification();
      const restoredBody = await this.bodyText();
      const screenshot = await this.screenshot("REC-06", "history-forward-restored");
      return {
        persona: "mobile operator using browser Back and Forward during review",
        preconditions: ["ready design", "completed verification", "390x844 viewport"],
        actions: ["opened Verify revision 1", "pressed Back", "confirmed the ready design", "pressed Forward", "confirmed the verification outcome"],
        visible: [this.primaryDesignName, "Ready", "23.32 cm³", "Open the record"],
        persisted: "both the project and verification result remained available across browser history navigation",
        numeric: "revision 1; measured volume 23.32 cm³",
        recovery: "Back/Forward restored exact routes without replaying create or losing data",
        screenshot,
        assertions: [
          assertion("forward URL restored", forwardUrl, this.page.url()),
          assertion("design still exists", 1, (await this.designList()).filter((design) => design.name === this.primaryDesignName).length),
          assertion("volume restored", true, /23\.32 cm³/.test(restoredBody)),
          assertion("saved verification restored", true, /Open the record/.test(restoredBody)),
        ],
      };
    });
  }

  async expiredSessionRecovery() {
    await this.runPath("FAIL-09", async () => {
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.waitForDesignReady(this.primaryDesignName);
      await this.page.locator('[data-preview-state="ready"]').waitFor({ timeout: 30_000 });
      await this.page.waitForLoadState("networkidle", { timeout: 15_000 });
      const sessionCookie = (await this.context.cookies()).find((cookie) => cookie.name === "dash_session");
      assert(sessionCookie, "authenticated dashboard cookie was not present before logout");
      await this.page.getByRole("button", { name: "Account" }).click();
      await this.page.getByRole("menuitem", { name: "Sign out" }).click();
      await this.page.waitForURL((url) => url.pathname === "/login", { timeout: 20_000 });
      await this.context.addCookies([sessionCookie]);
      await this.withExpectedHttpStatuses([401], async () => {
        await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
        await this.page.waitForURL((url) => url.pathname === "/login", { timeout: 20_000 });
        await this.page.waitForLoadState("networkidle", { timeout: 15_000 });
        await this.page.waitForTimeout(250);
      });
      const expiredUrl = this.page.url();
      this.artifacts.expiredSession = await this.screenshot("FAIL-09", "revoked-cookie-replay-denied");
      await this.context.clearCookies();
      await this.page.getByLabel("Email").fill(this.email);
      await this.page.getByLabel("Password").fill(this.password);
      await this.page.getByRole("button", { name: /^Log in$/ }).click();
      await this.page.waitForURL((url) => url.pathname === "/designs", { timeout: 20_000 });
      await this.waitForDesignReady(this.primaryDesignName);
      const screenshot = await this.screenshot("FAIL-09", "reauthenticated-data-restored");
      return {
        persona: "returning operator signing out and attempting a stale-cookie replay",
        preconditions: ["durable design exists", "authenticated dashboard cookie captured before logout", "protected /designs requested after replay"],
        actions: ["tapped Account", "tapped Sign out", "reinserted the captured pre-logout cookie", "opened /designs", "signed in with valid credentials", "returned to Design Studio"],
        visible: ["Log in", this.primaryDesignName, "Ready"],
        persisted: "logout revoked the replayed cookie without removing the organization design or revision",
        numeric: "one persisted primary design after reauthentication",
        authorization: "the pre-logout cookie was denied at the protected route; only fresh credentials restored organization access",
        recovery: "fresh reauthentication restored the exact durable design without resubmission",
        screenshot,
        assertions: [
          assertion("replayed cookie redirect path", "/login", new URL(expiredUrl).pathname),
          assertion("next parameter", "/designs", new URL(expiredUrl).searchParams.get("next")),
          assertion("design restored", 1, (await this.designList()).filter((design) => design.name === this.primaryDesignName).length),
        ],
      };
    });
  }

  async browserRestartPersistence() {
    await this.runPath("REC-08", async () => {
      await this.context.close();
      await this.browser.close();
      await this.launch({ width: 390, height: 844 });
      await this.login();
      await this.page.goto("/designs", { waitUntil: "domcontentloaded" });
      await this.waitForDesignReady(this.primaryDesignName);
      const designs = await this.designList();
      const screenshot = await this.screenshot("REC-08", "browser-restart-persisted");
      return {
        persona: "returning operator after closing and reopening the browser",
        preconditions: ["completed design and batch persisted in shared services", "browser process and context closed", "shared services intentionally not restarted"],
        actions: ["closed the browser", "launched a new browser process", "signed in", "opened Design Studio", "queried durable organization designs"],
        visible: [this.primaryDesignName, "Ready", "revision 1"],
        persisted: "the primary design remained ready after a full browser-process restart",
        numeric: `persisted organization designs ${designs.length}`,
        authorization: "new session restored only after valid sign-in",
        recovery: "browser restart required no regeneration and no data replay",
        screenshot,
        assertions: [
          assertion("primary design count", 1, designs.filter((design) => design.name === this.primaryDesignName).length),
          assertion("primary design status", "ready", designs.find((design) => design.name === this.primaryDesignName)?.status),
          assertion("primary revision", 1, designs.find((design) => design.name === this.primaryDesignName)?.current_revision),
        ],
      };
    });
  }

  async uploadRefreshRecovery() {
    await this.runPath("REC-09", async () => {
      await this.setViewport(375, 812);
      await this.page.goto("/batch", { waitUntil: "domcontentloaded" });
      const before = await this.batchList();
      await this.page.locator('input[type="file"][accept=".zip"]').first().setInputFiles(batchFixture);
      let delayed = false;
      const handler = async (route) => {
        if (!delayed && route.request().method() === "POST") {
          delayed = true;
          await new Promise((resolve) => setTimeout(resolve, 1_000));
        }
        await route.continue().catch(() => undefined);
      };
      await this.page.route("**/api/proxy/batch", handler);
      this.allowExpectedNetworkFailure = true;
      await this.page.getByRole("button", { name: /^Start batch$/ }).click();
      await this.page.reload({ waitUntil: "domcontentloaded" });
      this.allowExpectedNetworkFailure = false;
      await this.page.unroute("**/api/proxy/batch", handler);
      await this.page.waitForTimeout(1_500);
      let after = await this.batchList();
      if (after.length === before.length) {
        await this.page.locator('input[type="file"][accept=".zip"]').first().setInputFiles(batchFixture);
        await this.page.getByRole("button", { name: /^Start batch$/ }).click();
        await this.page.waitForURL((url) => /^\/batch\/[A-Z0-9]+$/i.test(url.pathname), { timeout: 30_000 });
        await this.page.goto("/batch", { waitUntil: "domcontentloaded" });
        after = await this.batchList();
      }
      const delta = after.length - before.length;
      const screenshot = await this.screenshot("REC-09", "upload-refresh-reconciled");
      return {
        persona: "mobile batch operator refreshing during ZIP upload",
        preconditions: ["375x812 viewport", "valid one-part ZIP selected", "upload response delayed before refresh"],
        actions: ["tapped Start batch", "refreshed while the request was pending", "refreshed Recent batches", "retried only if no batch had persisted"],
        visible: ["New batch", "Recent batches", "one reconciled batch row"],
        persisted: "reconciliation produced exactly one durable batch whether the interrupted request committed or aborted",
        numeric: `batch list delta ${delta}`,
        recovery: "Recent batches was the source of truth; retry occurred only when no persisted batch existed",
        screenshot,
        assertions: [
          assertion("upload delay injected", true, delayed),
          assertion("exactly one batch reconciled", 1, delta),
        ],
      };
    });
  }

  async writeReport(error = null) {
    const validation = validateGoldenPathMap(OWNED_PATH_IDS, this.goldenPaths);
    const status = !error && validation.problems.length === 0 ? "PASS" : "FAIL";
    const report = {
      status,
      suite: "mobile-recovery-e2e",
      runId,
      health: status === "PASS" ? 100 : Math.round((validation.valid / OWNED_PATH_IDS.length) * 100),
      baseUrl,
      generatedAt: new Date().toISOString(),
      buildIdentity: captureBuildIdentity(repoRoot),
      account: { email: this.email },
      ownedPathIds: OWNED_PATH_IDS,
      skippedPathIds: [...this.skippedPathIds],
      steps: this.steps,
      issues: this.issues,
      expectedFaults: this.expectedFaults,
      consoleErrors: this.consoleErrors,
      requestFailures: this.requestFailures,
      artifacts: this.artifacts,
      supplementalEvidence: this.supplementalEvidence,
      releaseEvidence: {
        schemaVersion: 1,
        goldenPaths: this.goldenPaths,
        validation,
      },
      error: error instanceof Error ? error.stack : error ? String(error) : null,
      screenshotDir,
    };
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
    return report;
  }

  async run() {
    await mkdir(screenshotDir, { recursive: true });
    const fixture = await writeDeterministicStoredZip(trackedCubeFixture, batchFixture, "cube.step");
    await writeFile(invalidStepFixture, "this is not STEP data and has no ISO-10303-21 header\n");
    assert((await readFile(batchFixture)).length > 128, `deterministic batch fixture was not created at ${batchFixture}`);
    this.artifacts.deterministicBatchFixture = { path: batchFixture, source: trackedCubeFixture, entry: "cube.step", ...fixture };
    this.artifacts.invalidStepFixture = invalidStepFixture;
    await this.launch();
    try {
      await this.signupAndOnboard();
      await this.mobileNavigation();
      await this.designStudioAndDuplicateGuard();
      await this.verifyDecisionAndRefresh();
      await this.designStudioMobileContract();
      await this.batchTablet();
      await this.tabletAndDialog();
      await this.responsiveKeyboardContract();
      if (!this.skippedPathIds.has("FAIL-01")) await this.invalidCadRecovery();
      await this.verifyCapacityRecovery();
      await this.costHistoryRecovery();
      await this.workerStatusRecovery();
      await this.apiFailureMatrix();
      await this.networkRecovery();
      await this.historyRecovery();
      await this.expiredSessionRecovery();
      await this.browserRestartPersistence();
      await this.uploadRefreshRecovery();
      const report = await this.writeReport();
      assert(report.status === "PASS", `evidence validation failed: ${JSON.stringify(report.releaseEvidence.validation.problems)}`);
      process.stdout.write(`${JSON.stringify({ status: report.status, reportPath, validation: report.releaseEvidence.validation }, null, 2)}\n`);
    } catch (error) {
      const report = await this.writeReport(error);
      process.stderr.write(`${JSON.stringify({ status: report.status, reportPath, error: error instanceof Error ? error.message : String(error) }, null, 2)}\n`);
      process.exitCode = 1;
    } finally {
      await this.browser?.close().catch(() => undefined);
    }
  }
}

await new MobileRecoveryRun().run();
