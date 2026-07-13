import { createHash, randomBytes } from "node:crypto";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { captureBuildIdentity, makeReleaseEvidence } from "./human-sim-release-evidence.mjs";
import { makeGoldenPathEvidence, validateGoldenPathMap } from "./golden-path-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const sharp = require("sharp");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const clientIp = process.env.E2E_CLIENT_IP || "198.51.100.85";
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(outputRoot, "screenshots", `design-studio-e2e-${runId}`);
const artifacts = {
  json: path.join(outputRoot, `design-studio-e2e-${runId}.json`),
  md: path.join(outputRoot, `qa-report-design-studio-e2e-${runId}.md`),
};
const requiredGoldenIds = Array.from({ length: 12 }, (_, index) => `DES-${String(index + 1).padStart(2, "0")}`);

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

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function same(expected, actual) {
  return stableJson(expected) === stableJson(actual);
}

class DesignStudioE2E {
  constructor() {
    this.steps = [];
    this.issues = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.successfulResponses = new Set();
    this.designMutationResponses = [];
    this.archiveMutationResponses = [];
    this.startedAt = Date.now();
    this.criticalPaths = {};
    this.assertions = Object.fromEntries(requiredGoldenIds.map((id) => [id, []]));
    this.goldenInputs = {};
  }

  check(id, name, expected, actual, pass = same(expected, actual)) {
    const evidenceValue = (value) => value === null ? "<null>" : value;
    const assertion = {
      name,
      expected: evidenceValue(expected),
      actual: evidenceValue(actual),
      pass,
    };
    this.assertions[id].push(assertion);
    assert(pass, `[${id}] ${name}: expected ${stableJson(expected)}, got ${stableJson(actual)}`);
    return actual;
  }

  truth(id, name, actual, expected = true) {
    return this.check(id, name, expected, actual, actual === expected);
  }

  recordGoldenPath(id, input) {
    this.goldenInputs[id] = input;
  }

  buildGoldenPaths(requestFailures) {
    return Object.fromEntries(
      requiredGoldenIds
        .filter((id) => this.goldenInputs[id])
        .map((id) => [id, makeGoldenPathEvidence({
          id,
          status: "PASS",
          ...this.goldenInputs[id],
          consoleErrors: this.consoleErrors,
          requestFailures,
          assertions: this.assertions[id],
        })]),
    );
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
      extraHTTPHeaders: { "x-real-ip": clientIp },
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
      const pathname = new URL(response.url()).pathname;
      if (
        response.request().method() === "POST" &&
        (/^\/api\/proxy\/designs$/.test(pathname) || /^\/api\/proxy\/designs\/[^/]+\/revisions$/.test(pathname))
      ) {
        this.designMutationResponses.push({ pathname, status: response.status() });
      }
      if (
        response.request().method() === "DELETE" &&
        /^\/api\/proxy\/designs\/[^/]+$/.test(pathname)
      ) {
        this.archiveMutationResponses.push({ pathname, status: response.status() });
      }
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

  async api(endpoint, options = {}) {
    const response = await this.context.request.fetch(new URL(endpoint, baseUrl).toString(), {
      method: options.method || "GET",
      data: options.data,
      failOnStatusCode: false,
      timeout: options.timeout || 60_000,
    });
    const bytes = await response.body();
    const contentType = response.headers()["content-type"] || "";
    let body = bytes;
    if (/json/i.test(contentType)) body = JSON.parse(bytes.toString("utf8"));
    else if (/text|csv|html/i.test(contentType)) body = bytes.toString("utf8");
    return { status: response.status(), headers: response.headers(), body, bytes };
  }

  async listDesigns() {
    const response = await this.api("/api/proxy/designs?limit=100");
    assert(response.status === 200, `Design list returned ${response.status}`);
    return { status: response.status, designs: response.body.designs || [] };
  }

  async findDesign(name) {
    const listed = await this.listDesigns();
    const design = listed.designs.find((item) => item.name === name);
    assert(design, `Persisted design ${name} was absent from the authenticated API`);
    return { ...listed, design };
  }

  async revisionArtifact(designId, revision) {
    const response = await this.api(`/api/proxy/designs/${designId}/revisions/${revision}/download.step`);
    assert(response.status === 200, `R${revision} artifact returned ${response.status}`);
    const hash = sha256(response.bytes);
    const headerHash = (response.headers["x-geometry-sha256"] || "").toLowerCase();
    assert(hash === headerHash, `R${revision} API artifact bytes differ from the response hash`);
    return { status: response.status, bytes: response.bytes.length, hash, headerHash };
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
    const href = await link.getAttribute("href");
    assert(href, `R${revision} STEP download link omitted href`);
    const [download] = await Promise.all([
      this.page.waitForEvent("download", { timeout: 20_000 }),
      link.click(),
    ]);
    const filename = await download.path();
    assert(filename, `R${revision} STEP download did not produce a local file`);
    const bytes = await readFile(filename);
    assert(bytes.length > 128, `R${revision} STEP download is unexpectedly empty`);
    const hash = sha256(bytes);
    const evidenceResponse = await this.context.request.get(new URL(href, baseUrl).toString());
    assert(evidenceResponse.ok(), `R${revision} evidence download returned ${evidenceResponse.status()}`);
    const responseBytes = await evidenceResponse.body();
    const responseHash = sha256(responseBytes);
    const responseHeaderSha256 = evidenceResponse.headers()["x-geometry-sha256"]?.toLowerCase() || "";
    assert(responseHash === hash, `R${revision} browser download differs from evidence response bytes`);
    assert(responseHeaderSha256 === hash, `R${revision} response SHA header differs from downloaded STEP`);
    return {
      hash,
      bytes: bytes.length,
      responseHash,
      responseHeaderSha256,
      hashesMatch: responseHash === hash && responseHeaderSha256 === hash,
    };
  }

  async generateCurrentForm(name, expectedEnvelope, expectedVolume) {
    await this.page.getByLabel("Design name").fill(name);
    const createResponsePromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/designs",
      { timeout: 20_000 },
    );
    await this.page.getByRole("button", { name: /^Generate design$/ }).click();
    const createResponse = await createResponsePromise;
    assert(createResponse.status() === 202, `${name} create returned ${createResponse.status()}`);
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
    const persisted = await this.findDesign(name);
    return {
      ...downloaded,
      visual,
      createStatus: createResponse.status(),
      design: persisted.design,
      listStatus: persisted.status,
      hashPrefix,
      visibleText: text,
    };
  }

  async verifySelectedRevision({
    revision,
    filenamePattern,
    envelope,
    volume,
    envelopeMm = null,
    uiVolumeCm3 = null,
    artifactSha256 = null,
    criticalPathId = null,
    turningMustFail = false,
    expectedRouteHint = null,
    expectedArchetype = null,
  }) {
    const link = this.page.getByRole("link", {
      name: new RegExp(`^Verify revision ${revision}$`),
    });
    const href = await link.getAttribute("href");
    assert(href?.includes(`revision=${revision}`), `Verify link does not preserve revision ${revision}`);
    const handoffUrl = new URL(href, baseUrl);
    const designId = handoffUrl.searchParams.get("design");
    assert(designId, `Verify link omitted the design id for revision ${revision}`);
    const artifactResponsePromise = this.page.waitForResponse(
      (response) => response.request().method() === "GET" && new URL(response.url()).pathname === `/api/proxy/designs/${designId}/revisions/${revision}/download.step`,
      { timeout: 90_000 },
    );
    const validationResponsePromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/validate",
      { timeout: 150_000 },
    );
    const costResponsePromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/validate/cost",
      { timeout: 150_000 },
    );
    await link.click();
    await this.page.waitForURL((url) => url.pathname === "/verify" && url.searchParams.get("revision") === String(revision));
    await this.page.getByText(/Verification complete — deterministic/i).waitFor({ timeout: 150_000 });
    const [artifactResponse, validationResponse, costResponse] = await Promise.all([
      artifactResponsePromise,
      validationResponsePromise,
      costResponsePromise,
    ]);
    assert(artifactResponse.ok(), `Verify R${revision} artifact import returned ${artifactResponse.status()}`);
    assert(validationResponse.ok(), `Verify R${revision} validation returned ${validationResponse.status()}`);
    assert(costResponse.ok(), `Verify R${revision} cost returned ${costResponse.status()}`);
    const importedBytes = await artifactResponse.body();
    const importedArtifactSha256 = sha256(importedBytes);
    const importedHeaderSha256 = (artifactResponse.headers()["x-geometry-sha256"] || "").toLowerCase();
    const importedFilename = artifactResponse.headers()["content-disposition"]?.match(/filename="?([^";]+)"?/i)?.[1] || null;
    assert(importedArtifactSha256 === importedHeaderSha256, `Verify R${revision} imported bytes differ from their integrity header`);
    if (artifactSha256) {
      assert(importedArtifactSha256 === artifactSha256, `Verify R${revision} imported a different artifact than Design Studio exposed`);
    }
    const cost = await costResponse.json();
    const turning = (cost.engine_feasibility || []).find((item) => item.process === "cnc_turning") || null;
    const shortlist = new Set([
      cost.routing?.recommended_process,
      ...(cost.routing?.alternatives || []),
      ...Object.values(cost.decision?.recommendation || {}).map((item) => item?.process),
    ].filter(Boolean));
    const rotational = cost.routing?.drivers?.rotational;
    const measuredEnvelopeMm = cost.geometry?.bbox_mm ?? null;
    const measuredVolumeCm3 = cost.geometry?.volume_cm3 ?? null;
    const measuredUiVolumeCm3 = typeof measuredVolumeCm3 === "number"
      ? Number(measuredVolumeCm3.toFixed(2))
      : null;
    const text = await this.expectCleanSuccess(`Verify R${revision}`);
    assert(filenamePattern.test(text), `Verify did not retain the selected revision filename`);
    assert(text.includes(envelope), `Verify measured envelope does not equal ${envelope}`);
    assert(text.includes(volume), `Verify measured volume does not equal ${volume}`);
    assert(/watertight true/i.test(text), `Verify did not report watertight geometry`);
    assert(/SHOULD-COST COMPUTED/i.test(text), `Verify did not compute should-cost`);
    if (envelopeMm) {
      assert(same(envelopeMm, measuredEnvelopeMm), `Verify API envelope ${stableJson(measuredEnvelopeMm)} does not equal ${stableJson(envelopeMm)}`);
    }
    if (uiVolumeCm3 !== null) {
      assert(measuredUiVolumeCm3 === uiVolumeCm3, `Verify API volume rounded to ${measuredUiVolumeCm3}, expected ${uiVolumeCm3}`);
    }
    if (turningMustFail) {
      assert(!/CNC Turning\s+pass/i.test(text), `Non-rotational template incorrectly passes CNC turning`);
      assert(!/route hint aluminum/i.test(text), `Non-rotational polymer template still exposes the old aluminum turning hint`);
      assert(rotational === false, `Non-rotational template reported rotational=${rotational}`);
      assert(turning?.verdict === "issues", `CNC turning verdict was ${turning?.verdict || "missing"}, expected issues`);
      assert(!shortlist.has("cnc_turning"), "CNC turning appeared in the cost shortlist for a non-rotational design");
    }
    if (expectedArchetype) {
      assert(cost.routing?.archetype === expectedArchetype, `Expected routing archetype ${expectedArchetype}, got ${cost.routing?.archetype}`);
    }
    if (expectedRouteHint) {
      assert(
        new RegExp(`route hint ${escapeRegExp(expectedRouteHint)}`, "i").test(text),
        `Expected ${expectedRouteHint} route hint`,
      );
    }
    const screenshot = await this.shot(`verify-r${revision}`, true);
    const evidence = {
      revision,
      queryRevision: new URL(this.page.url()).searchParams.get("revision"),
      artifactSha256,
      designId,
      importedArtifactSha256,
      importedHeaderSha256,
      importedFilename,
      importedBytes: importedBytes.length,
      envelopeMm: measuredEnvelopeMm,
      volumeCm3: measuredVolumeCm3,
      uiVolumeCm3: measuredUiVolumeCm3,
      watertight: /watertight true/i.test(text),
      shouldCostComputed: /SHOULD-COST COMPUTED/i.test(text),
      validationStatus: validationResponse.status(),
      costStatus: costResponse.status(),
      routingArchetype: cost.routing?.archetype ?? null,
      rotational: rotational ?? null,
      turningVerdict: turning?.verdict ?? null,
      turningShortlisted: shortlist.has("cnc_turning"),
      expectedRouteHint,
      screenshot,
    };
    if (criticalPathId) this.criticalPaths[criticalPathId] = evidence;
    return { screenshot, evidence };
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
      const before = await this.listDesigns();
      const mutationsBefore = this.designMutationResponses.length;
      await this.page.getByLabel("Describe a starting shape").fill(
        "Make a turbine blade with organic cooling channels",
      );
      const responsePromise = this.page.waitForResponse(
        (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/designs/interpret",
      );
      await this.page.getByRole("button", { name: "Interpret safely" }).click();
      const response = await responsePromise;
      const interpretation = await response.json();
      const boundary = this.page.getByText(
        "Choose a supported starting shape: plate, L bracket, or open enclosure.",
      );
      await boundary.waitFor();
      await this.expectText(/Unsupported geometry is never approximated here/i, "unsupported geometry boundary");
      const after = await this.listDesigns();
      const plateEnabled = await this.page.getByRole("button", { name: "Mounting plate" }).isEnabled();
      this.check("DES-01", "interpret HTTP status", 200, response.status());
      this.check("DES-01", "unsupported response status", "needs_input", interpretation.status);
      this.check("DES-01", "unsupported response kind", null, interpretation.kind);
      this.check("DES-01", "unsupported missing fields", ["shape"], interpretation.missing_fields);
      this.check("DES-01", "exact visible boundary", interpretation.message, await boundary.innerText());
      this.check("DES-01", "design count remains zero", before.designs.length, after.designs.length);
      this.check("DES-01", "no generation endpoint called", mutationsBefore, this.designMutationResponses.length);
      this.check("DES-01", "supported recovery control remains enabled", true, plateEnabled);
      const screenshot = await this.shot("unsupported-freeform");
      this.recordGoldenPath("DES-01", {
        persona: "CAD engineer testing the safe boundary with unsupported freeform geometry",
        preconditions: ["Authenticated analyst account with an empty organization Design Studio."],
        actions: ["Entered a turbine blade with organic cooling channels.", "Selected Interpret safely.", "Inspected the exact boundary response and authenticated design list."],
        observed: {
          url: this.page.url(),
          visible: [interpretation.message, "Unsupported geometry is never approximated here."],
          persisted: { beforeDesignCount: before.designs.length, afterDesignCount: after.designs.length, generationResponses: this.designMutationResponses.length - mutationsBefore },
          numeric: { interpretStatus: response.status(), designsCreated: after.designs.length - before.designs.length, generationCalls: this.designMutationResponses.length - mutationsBefore },
          authorization: { signedIn: true, listStatus: after.status, organizationScoped: true },
          recovery: "Mounting plate remained enabled, so the engineer could choose an allowlisted template without losing the description boundary.",
        },
        screenshot,
      });
      return { screenshot };
    });

    await this.step("Incomplete enclosure description asks for exact missing dimensions", async () => {
      const before = await this.listDesigns();
      const mutationsBefore = this.designMutationResponses.length;
      await this.page.getByLabel("Describe a starting shape").fill("open enclosure 100 × 60 mm");
      const responsePromise = this.page.waitForResponse(
        (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/designs/interpret",
      );
      await this.page.getByRole("button", { name: "Interpret safely" }).click();
      const response = await responsePromise;
      const interpretation = await response.json();
      const missingCopy = this.page.getByText(/need: height, wall thickness/i);
      await missingCopy.waitFor();
      const values = {
        width: await this.page.getByLabel("Width").inputValue(),
        depth: await this.page.getByLabel("Depth").inputValue(),
        height: await this.page.getByLabel("Height").inputValue(),
        wall: await this.page.getByLabel("Wall").inputValue(),
      };
      const after = await this.listDesigns();
      this.check("DES-02", "interpret HTTP status", 200, response.status());
      this.check("DES-02", "incomplete response status", "needs_input", interpretation.status);
      this.check("DES-02", "incomplete response kind", "enclosure", interpretation.kind);
      this.check("DES-02", "exact missing fields", ["height_mm", "wall_thickness_mm"], interpretation.missing_fields);
      this.check("DES-02", "explicit width prefill", "100", values.width);
      this.check("DES-02", "explicit depth prefill", "60", values.depth);
      this.check("DES-02", "reviewable default height retained", "60", values.height);
      this.check("DES-02", "reviewable default wall retained", "3", values.wall);
      this.check("DES-02", "no persisted design", before.designs.length, after.designs.length);
      this.check("DES-02", "no generation endpoint called", mutationsBefore, this.designMutationResponses.length);
      const screenshot = await this.shot("missing-dimensions");
      this.recordGoldenPath("DES-02", {
        persona: "CAD engineer providing a partial enclosure description",
        preconditions: ["Authenticated Design Studio with no generated designs."],
        actions: ["Entered open enclosure 100 × 60 mm.", "Selected Interpret safely.", "Inspected missing fields and every visible dimension input."],
        observed: {
          url: this.page.url(),
          visible: [interpretation.message, "Width 100", "Depth 60", "Height 60", "Wall 3"],
          persisted: { interpretation, beforeDesignCount: before.designs.length, afterDesignCount: after.designs.length },
          numeric: { widthMm: Number(values.width), depthMm: Number(values.depth), defaultHeightMm: Number(values.height), defaultWallMm: Number(values.wall), designsCreated: 0 },
          authorization: { signedIn: true, listStatus: after.status, organizationScoped: true },
          recovery: "Explicit width and depth remained prefilled while height and wall stayed reviewable defaults for completion.",
        },
        screenshot,
      });
      return { screenshot };
    });

    let plateR1;
    await this.step("Plate description prefills exact clean millimetre values", async () => {
      await this.page.getByLabel("Describe a starting shape").fill(
        "120 × 70 × 8 mm plate with four 10 mm corner holes",
      );
      const responsePromise = this.page.waitForResponse(
        (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/designs/interpret",
      );
      await this.page.getByRole("button", { name: "Interpret safely" }).click();
      const response = await responsePromise;
      const interpretation = await response.json();
      await this.page.getByText(/Safe dimensions extracted/i).waitFor();
      const values = await Promise.all([
        this.page.getByLabel("Width").inputValue(),
        this.page.getByLabel("Depth").inputValue(),
        this.page.getByLabel("Thickness").inputValue(),
        this.page.getByLabel("Diameter").inputValue(),
        this.page.getByLabel("Edge inset").inputValue(),
      ]);
      this.check("DES-03", "interpret HTTP status", 200, response.status());
      this.check("DES-03", "safe interpretation status", "ready", interpretation.status);
      this.check("DES-03", "safe interpretation kind", "plate", interpretation.kind);
      this.check("DES-03", "exact clean field values", ["120", "70", "8", "10", "8.4"], values);
      this.check("DES-03", "exact plan width", 120, interpretation.plan.width_mm);
      this.check("DES-03", "exact plan depth", 70, interpretation.plan.depth_mm);
      this.check("DES-03", "exact plan thickness", 8, interpretation.plan.thickness_mm);
      this.check("DES-03", "exact plan hole count", 4, interpretation.plan.holes.length);
      this.truth("DES-03", "local no-egress review policy visible", /local rules · no AI egress · review required/i.test(await this.text()));
      const screenshot = await this.shot("plate-prefill");
      this.recordGoldenPath("DES-03", {
        persona: "CAD engineer safely extracting a complete mounting-plate plan",
        preconditions: ["Authenticated Design Studio with deterministic local interpretation enabled."],
        actions: ["Entered 120 × 70 × 8 mm plate with four 10 mm corner holes.", "Selected Interpret safely.", "Read every prefilled field and the returned plan."],
        observed: {
          url: this.page.url(),
          visible: [interpretation.message, "local rules · no AI egress · review required", "120", "70", "8", "10", "8.4"],
          persisted: { status: interpretation.status, kind: interpretation.kind, plan: interpretation.plan },
          numeric: { widthMm: 120, depthMm: 70, thicknessMm: 8, holeDiameterMm: 10, edgeInsetMm: 8.4, holeCount: interpretation.plan.holes.length },
          authorization: { signedIn: true, interpretStatus: response.status(), externalAiEgress: false },
          recovery: "All extracted values remained editable and generation still required an explicit review click.",
        },
        screenshot,
      });
      return { screenshot };
    });

    await this.step("Unsafe plate hole margin is blocked before generation", async () => {
      const before = await this.listDesigns();
      const mutationsBefore = this.designMutationResponses.length;
      await this.page.getByLabel("Edge inset").fill("5");
      await this.page.getByRole("button", { name: /^Generate design$/ }).click();
      const error = this.page.getByText("Hole inset must leave at least 1 mm of material at the edge.");
      await error.waitFor();
      const after = await this.listDesigns();
      this.check("DES-04", "exact unsafe-margin error", "Hole inset must leave at least 1 mm of material at the edge.", await error.innerText());
      this.check("DES-04", "no persisted design after validation failure", before.designs.length, after.designs.length);
      this.check("DES-04", "no generation endpoint after validation failure", mutationsBefore, this.designMutationResponses.length);
      await this.page.getByRole("button", { name: "Dismiss" }).click();
      await this.page.getByLabel("Edge inset").fill("8.4");
      this.check("DES-04", "corrected safe inset is retained", "8.4", await this.page.getByLabel("Edge inset").inputValue());
      const screenshot = await this.shot("unsafe-hole-margin");
      this.recordGoldenPath("DES-04", {
        persona: "CAD engineer prevented from generating an unsafe corner-hole layout",
        preconditions: ["A complete 120 × 70 × 8 mm four-hole plate plan is present but not generated."],
        actions: ["Changed edge inset to 5 mm.", "Selected Generate design.", "Read the exact blocking error, dismissed it, and corrected inset to 8.4 mm."],
        observed: {
          url: this.page.url(),
          visible: ["Hole inset must leave at least 1 mm of material at the edge.", "Edge inset 8.4"],
          persisted: { beforeDesignCount: before.designs.length, afterDesignCount: after.designs.length, generationResponses: this.designMutationResponses.length - mutationsBefore },
          numeric: { rejectedInsetMm: 5, correctedInsetMm: 8.4, designsCreated: 0, generationCalls: 0 },
          authorization: { signedIn: true, listStatus: after.status, mutationAuthorizedButClientBlocked: true },
          recovery: "Dismissal retained the form and a safe 8.4 mm correction, which the next golden path generated successfully.",
        },
        screenshot,
      });
      return { screenshot };
    });

    await this.step("Golden mounting plate generates real CAD with exact geometry and hash", async () => {
      plateR1 = await this.generateCurrentForm(
        "Golden mounting plate",
        "120.0 × 70.0 × 8.0 mm",
        "64.69 cm³",
      );
      const screenshot = await this.shot("plate-r1-ready", true);
      const revision = plateR1.design.revision;
      const evidence = {
        artifactSha256: plateR1.hash,
        responseHeaderSha256: plateR1.responseHeaderSha256,
        hashesMatch: plateR1.hashesMatch,
        downloadedBytes: plateR1.bytes,
        envelopeMm: revision.geometry.bbox_mm,
        uiVolumeCm3: Number(revision.geometry.volume_cm3.toFixed(2)),
        previewMode: plateR1.visual.mode,
        screenshot,
      };
      this.check("DES-05", "create HTTP status", 202, plateR1.createStatus);
      this.check("DES-05", "persisted design status", "ready", plateR1.design.status);
      this.check("DES-05", "persisted current revision", 1, plateR1.design.current_revision);
      this.check("DES-05", "persisted plan kind", "plate", revision.plan.kind);
      this.check("DES-05", "persisted width", 120, revision.plan.width_mm);
      this.check("DES-05", "persisted depth", 70, revision.plan.depth_mm);
      this.check("DES-05", "persisted thickness", 8, revision.plan.thickness_mm);
      this.check("DES-05", "persisted symmetric hole count", 4, revision.plan.holes.length);
      this.check("DES-05", "persisted envelope", [120, 70, 8], revision.geometry.bbox_mm);
      this.check("DES-05", "persisted exact volume", 64.686726, revision.geometry.volume_cm3, Math.abs(revision.geometry.volume_cm3 - 64.686726) <= 0.001);
      this.truth("DES-05", "exact UI envelope visible", plateR1.visibleText.includes("120.0 × 70.0 × 8.0 mm"));
      this.truth("DES-05", "exact UI rounded volume visible", plateR1.visibleText.includes("64.69 cm³"));
      this.truth("DES-05", "UI evidence hash prefix matches artifact", plateR1.visibleText.includes(`Evidence hash ${plateR1.hashPrefix}`));
      this.check("DES-05", "artifact hash equals persisted geometry hash", revision.geometry_hash, plateR1.hash);
      this.check("DES-05", "artifact response header equals bytes", plateR1.hash, plateR1.responseHeaderSha256);
      this.truth("DES-05", "nonblank preview or explicit fallback", ["interactive", "explicit-fallback"].includes(plateR1.visual.mode));
      this.truth("DES-05", "downloaded STEP has durable bytes", plateR1.bytes > 128);
      this.criticalPaths["DES-05"] = evidence;
      this.recordGoldenPath("DES-05", {
        persona: "CAD engineer generating the canonical four-hole mounting plate",
        preconditions: ["The exact safe plate fields are reviewed with edge inset corrected to 8.4 mm."],
        actions: ["Named the design Golden mounting plate.", "Selected Generate design.", "Waited for Ready, inspected geometry/preview, and downloaded R1 STEP."],
        observed: {
          url: this.page.url(),
          visible: ["Golden mounting plate", "Ready", "120.0 × 70.0 × 8.0 mm", "64.69 cm³", `Evidence hash ${plateR1.hashPrefix}`],
          persisted: { designId: plateR1.design.id, status: plateR1.design.status, currentRevision: plateR1.design.current_revision, revision, artifactSha256: plateR1.hash, responseHeaderSha256: plateR1.responseHeaderSha256 },
          numeric: { createStatus: plateR1.createStatus, envelopeMm: revision.geometry.bbox_mm, volumeCm3: revision.geometry.volume_cm3, uiVolumeCm3: 64.69, holeCount: revision.plan.holes.length, downloadedBytes: plateR1.bytes },
          authorization: { signedIn: true, listStatus: plateR1.listStatus, organizationScoped: true },
          recovery: "Ready state exposed preview, exact hash, STEP download, and Verify revision 1 handoff without failure copy.",
        },
        screenshot,
      });
      return { screenshot, evidence };
    });

    let plateR2;
    await this.step("Plate revision is immutable and historical STEP bytes remain exact", async () => {
      await this.page.getByRole("button", { name: "Revise" }).click();
      await this.page.getByRole("heading", { name: /Create revision 2/ }).waitFor();
      await this.page.getByLabel("Width").fill("130");
      await this.page.getByLabel("Design note (optional)").fill("Increase width by 10 mm");
      const revisionResponsePromise = this.page.waitForResponse(
        (response) => response.request().method() === "POST" && new URL(response.url()).pathname === `/api/proxy/designs/${plateR1.design.id}/revisions`,
        { timeout: 20_000 },
      );
      await this.page.getByRole("button", { name: "Generate new revision" }).click();
      const revisionResponse = await revisionResponsePromise;
      assert(revisionResponse.status() === 202, `R2 create returned ${revisionResponse.status()}`);
      await this.waitForDesignReady("Golden mounting plate");
      await this.page.getByRole("button", { name: /R2 ready current/i }).waitFor();
      await this.expectText(/130\.0 × 70\.0 × 8\.0 mm.*70\.29 cm³/i, "R2 geometry");
      const r2VisibleText = await this.text();
      plateR2 = await this.downloadHash(2);
      assert(plateR2.hash !== plateR1.hash, "R2 STEP hash did not change after a width revision");

      await this.page.getByRole("button", { name: /^R1 ready$/i }).click();
      await this.expectText(/Viewing revision 1 · current is 2/i, "historical revision marker");
      await this.expectText(/120\.0 × 70\.0 × 8\.0 mm.*64\.69 cm³/i, "historical R1 geometry");
      const r1VisibleText = await this.text();
      const plateR1Again = await this.downloadHash(1);
      assert(plateR1Again.hash === plateR1.hash, "Historical R1 bytes changed after R2 generation");
      const persisted = await this.findDesign("Golden mounting plate");
      const revisionsResponse = await this.api(`/api/proxy/designs/${plateR1.design.id}/revisions`);
      assert(revisionsResponse.status === 200, `Revision history returned ${revisionsResponse.status}`);
      const revisions = revisionsResponse.body.revisions || [];
      const r1 = revisions.find((revision) => revision.number === 1);
      const r2 = revisions.find((revision) => revision.number === 2);
      assert(r1 && r2, "Persisted revision history did not contain both R1 and R2");
      const screenshot = await this.shot("plate-revision-history", true);
      const evidence = {
        r1Sha256: plateR1.hash,
        r2Sha256: plateR2.hash,
        hashesDiffer: plateR2.hash !== plateR1.hash,
        r1RoundTripExact: plateR1Again.hash === plateR1.hash,
        r2EnvelopeMm: r2.geometry.bbox_mm,
        r2UiVolumeCm3: Number(r2.geometry.volume_cm3.toFixed(2)),
        screenshot,
      };
      this.check("DES-10", "revision create HTTP status", 202, revisionResponse.status());
      this.check("DES-10", "persisted current revision", 2, persisted.design.current_revision);
      this.check("DES-10", "persisted revision count", 2, revisions.length);
      this.check("DES-10", "R2 plan width", 130, r2.plan.width_mm);
      this.check("DES-10", "R2 envelope", [130, 70, 8], r2.geometry.bbox_mm);
      this.check("DES-10", "R2 exact volume", 70.286726, r2.geometry.volume_cm3, Math.abs(r2.geometry.volume_cm3 - 70.286726) <= 0.001);
      this.truth("DES-10", "R2 exact UI envelope visible", r2VisibleText.includes("130.0 × 70.0 × 8.0 mm"));
      this.truth("DES-10", "R2 exact UI rounded volume visible", r2VisibleText.includes("70.29 cm³"));
      this.check("DES-10", "R2 design note", "Increase width by 10 mm", r2.design_note);
      this.check("DES-10", "R2 persisted hash equals downloaded bytes", r2.geometry_hash, plateR2.hash);
      this.check("DES-10", "R1 persisted hash remains exact", r1.geometry_hash, plateR1Again.hash);
      this.check("DES-10", "R1 browser bytes remain exact", plateR1.hash, plateR1Again.hash);
      this.check("DES-10", "R1 and R2 hashes differ", false, plateR1.hash === plateR2.hash);
      this.truth("DES-10", "historical R1 is selected while R2 stays current", /Viewing revision 1 · current is 2/i.test(r1VisibleText));
      this.truth("DES-10", "historical R1 exact UI envelope remains visible", r1VisibleText.includes("120.0 × 70.0 × 8.0 mm"));
      this.truth("DES-10", "historical R1 exact UI rounded volume remains visible", r1VisibleText.includes("64.69 cm³"));
      this.criticalPaths["DES-10"] = evidence;
      this.recordGoldenPath("DES-10", {
        persona: "CAD engineer revising geometry without rewriting prior evidence",
        preconditions: ["Golden mounting plate R1 is Ready with a captured SHA-256 and downloaded bytes."],
        actions: ["Selected Revise.", "Changed width from 120 to 130 mm and entered a revision note.", "Generated R2, then selected and downloaded historical R1 again."],
        observed: {
          url: this.page.url(),
          visible: ["Viewing revision 1 · current is 2", "120.0 × 70.0 × 8.0 mm", "64.69 cm³", "R2 ready current"],
          persisted: { designId: persisted.design.id, currentRevision: persisted.design.current_revision, revisions, r1Sha256: plateR1.hash, r2Sha256: plateR2.hash, r1RoundTripSha256: plateR1Again.hash },
          numeric: { revisionCreateStatus: revisionResponse.status(), revisionCount: revisions.length, r2EnvelopeMm: r2.geometry.bbox_mm, r2VolumeCm3: r2.geometry.volume_cm3, r2UiVolumeCm3: 70.29, r1Bytes: plateR1Again.bytes, r2Bytes: plateR2.bytes },
          authorization: { signedIn: true, revisionListStatus: revisionsResponse.status, organizationScoped: true },
          recovery: "Selecting R1 after R2 preserved R2 as current while exposing byte-identical R1 download and Verify controls.",
        },
        screenshot,
      });
      return { screenshot, evidence };
    });

    await this.step("Historical plate revision enters Verify with the exact measured result", async () => {
      const result = await this.verifySelectedRevision({
        revision: 1,
        filenamePattern: /Golden_mounting_plate-r1\.step/i,
        envelope: "120.0 × 70.0 × 8.0 mm",
        volume: "64.69 cm³",
        envelopeMm: [120, 70, 8],
        uiVolumeCm3: 64.69,
        artifactSha256: plateR1.hash,
        criticalPathId: "DES-11",
        expectedRouteHint: "polymer",
      });
      const evidence = result.evidence;
      this.check("DES-11", "selected historical revision", 1, evidence.revision);
      this.check("DES-11", "query preserves historical revision", "1", evidence.queryRevision);
      this.check("DES-11", "imported filename is R1", "Golden_mounting_plate-r1.step", evidence.importedFilename);
      this.check("DES-11", "imported bytes equal R1 SHA", plateR1.hash, evidence.importedArtifactSha256);
      this.check("DES-11", "import response header equals R1 SHA", plateR1.hash, evidence.importedHeaderSha256);
      this.check("DES-11", "measured envelope", [120, 70, 8], evidence.envelopeMm);
      this.check("DES-11", "measured exact volume", 64.686726, evidence.volumeCm3, Math.abs(evidence.volumeCm3 - 64.686726) <= 0.01);
      this.check("DES-11", "UI measured volume", 64.69, evidence.uiVolumeCm3);
      this.check("DES-11", "validation HTTP status", 200, evidence.validationStatus);
      this.check("DES-11", "cost HTTP status", 200, evidence.costStatus);
      this.check("DES-11", "watertight result", true, evidence.watertight);
      this.check("DES-11", "should-cost computed", true, evidence.shouldCostComputed);
      this.recordGoldenPath("DES-11", {
        persona: "CAD engineer verifying an immutable historical revision rather than the current design",
        preconditions: ["Golden mounting plate has Ready R1 and R2 with distinct hashes, and R1 is selected."],
        actions: ["Selected Verify revision 1.", "Observed the revision query and imported filename.", "Waited for deterministic validation and cost, then compared imported bytes with R1 SHA-256."],
        observed: {
          url: this.page.url(),
          visible: ["Golden_mounting_plate-r1.step", "120.0 × 70.0 × 8.0 mm", "64.69 cm³", "watertight true", "SHOULD-COST COMPUTED"],
          persisted: { designId: evidence.designId, selectedRevision: evidence.revision, currentRevision: 2, r1ArtifactSha256: plateR1.hash, importedArtifactSha256: evidence.importedArtifactSha256, importedHeaderSha256: evidence.importedHeaderSha256 },
          numeric: { queryRevision: Number(evidence.queryRevision), envelopeMm: evidence.envelopeMm, volumeCm3: evidence.volumeCm3, uiVolumeCm3: evidence.uiVolumeCm3, importedBytes: evidence.importedBytes, validationStatus: evidence.validationStatus, costStatus: evidence.costStatus },
          authorization: { signedIn: true, artifactStatus: 200, validationStatus: evidence.validationStatus, costStatus: evidence.costStatus },
          recovery: "The historical handoff remained independently downloadable and verifiable while R2 stayed current in Design Studio.",
        },
        screenshot: result.screenshot,
      });
      return result;
    });

    let bracketR1;
    await this.step("Golden L bracket generates as a recognizable prismatic template", async () => {
      await this.gotoStudio();
      await this.page.getByRole("button", { name: "L bracket" }).click();
      bracketR1 = await this.generateCurrentForm(
        "Golden L bracket",
        "80.0 × 50.0 × 60.0 mm",
        "40.20 cm³",
      );
      const revision = bracketR1.design.revision;
      const bboxVolumeCm3 = revision.geometry.bbox_mm.reduce((product, value) => product * value, 1) / 1000;
      const solidity = revision.geometry.volume_cm3 / bboxVolumeCm3;
      this.check("DES-06", "create HTTP status", 202, bracketR1.createStatus);
      this.check("DES-06", "persisted design status", "ready", bracketR1.design.status);
      this.check("DES-06", "persisted current revision", 1, bracketR1.design.current_revision);
      this.check("DES-06", "persisted plan kind", "bracket", revision.plan.kind);
      this.check("DES-06", "persisted width", 80, revision.plan.width_mm);
      this.check("DES-06", "persisted depth", 50, revision.plan.depth_mm);
      this.check("DES-06", "persisted height", 60, revision.plan.height_mm);
      this.check("DES-06", "persisted leg thickness", 6, revision.plan.thickness_mm);
      this.check("DES-06", "persisted envelope", [80, 50, 60], revision.geometry.bbox_mm);
      this.check("DES-06", "persisted exact L volume", 40.2, revision.geometry.volume_cm3, Math.abs(revision.geometry.volume_cm3 - 40.2) <= 0.001);
      this.truth("DES-06", "exact UI envelope visible", bracketR1.visibleText.includes("80.0 × 50.0 × 60.0 mm"));
      this.truth("DES-06", "exact UI rounded volume visible", bracketR1.visibleText.includes("40.20 cm³"));
      this.truth("DES-06", "UI evidence hash prefix matches artifact", bracketR1.visibleText.includes(`Evidence hash ${bracketR1.hashPrefix}`));
      this.check("DES-06", "artifact hash equals persisted geometry hash", revision.geometry_hash, bracketR1.hash);
      this.check("DES-06", "artifact response header equals bytes", bracketR1.hash, bracketR1.responseHeaderSha256);
      this.truth("DES-06", "L geometry is not a solid bounding box", solidity < 0.2);
      this.truth("DES-06", "nonblank preview or explicit fallback", ["interactive", "explicit-fallback"].includes(bracketR1.visual.mode));
      this.truth("DES-06", "downloaded STEP has durable bytes", bracketR1.bytes > 128);
      const screenshot = await this.shot("bracket-ready", true);
      this.recordGoldenPath("DES-06", {
        persona: "CAD engineer generating the default perpendicular-leg L bracket",
        preconditions: ["Authenticated Design Studio with the L bracket template selected at its reviewed defaults."],
        actions: ["Selected L bracket.", "Named it Golden L bracket and generated the design.", "Inspected the preview, exact dimensions, volume, evidence hash, and R1 STEP download."],
        observed: {
          url: this.page.url(),
          visible: ["Golden L bracket", "bracket · revision 1", "80.0 × 50.0 × 60.0 mm", "40.20 cm³", `Evidence hash ${bracketR1.hashPrefix}`],
          persisted: { designId: bracketR1.design.id, status: bracketR1.design.status, currentRevision: bracketR1.design.current_revision, revision, artifactSha256: bracketR1.hash, responseHeaderSha256: bracketR1.responseHeaderSha256 },
          numeric: { createStatus: bracketR1.createStatus, envelopeMm: revision.geometry.bbox_mm, thicknessMm: revision.plan.thickness_mm, volumeCm3: revision.geometry.volume_cm3, boundingBoxVolumeCm3: bboxVolumeCm3, solidity, downloadedBytes: bracketR1.bytes },
          authorization: { signedIn: true, listStatus: bracketR1.listStatus, organizationScoped: true },
          recovery: "Ready state retained exact geometry, a nonblank preview or explicit fallback, and byte-bound download/Verify controls.",
        },
        screenshot,
      });
      return { screenshot, evidence: bracketR1 };
    });

    await this.step("L bracket Verify rejects CNC turning and completes DFM plus cost", async () => {
      const result = await this.verifySelectedRevision({
        revision: 1,
        filenamePattern: /Golden_L_bracket-r1\.step/i,
        envelope: "80.0 × 50.0 × 60.0 mm",
        volume: "40.20 cm³",
        envelopeMm: [80, 50, 60],
        uiVolumeCm3: 40.2,
        artifactSha256: bracketR1.hash,
        turningMustFail: true,
        expectedRouteHint: "polymer",
      });
      const evidence = result.evidence;
      this.check("DES-07", "selected bracket revision", 1, evidence.revision);
      this.check("DES-07", "imported bracket filename", "Golden_L_bracket-r1.step", evidence.importedFilename);
      this.check("DES-07", "imported bytes equal bracket SHA", bracketR1.hash, evidence.importedArtifactSha256);
      this.check("DES-07", "measured envelope", [80, 50, 60], evidence.envelopeMm);
      this.check("DES-07", "measured exact volume", 40.2, evidence.volumeCm3, Math.abs(evidence.volumeCm3 - 40.2) <= 0.01);
      this.check("DES-07", "UI measured volume", 40.2, evidence.uiVolumeCm3);
      this.check("DES-07", "validation HTTP status", 200, evidence.validationStatus);
      this.check("DES-07", "cost HTTP status", 200, evidence.costStatus);
      this.check("DES-07", "routing rotational driver", false, evidence.rotational);
      this.check("DES-07", "CNC turning verdict", "issues", evidence.turningVerdict);
      this.check("DES-07", "CNC turning excluded from shortlist", false, evidence.turningShortlisted);
      this.check("DES-07", "watertight result", true, evidence.watertight);
      this.check("DES-07", "should-cost computed", true, evidence.shouldCostComputed);
      this.recordGoldenPath("DES-07", {
        persona: "manufacturing engineer verifying a non-rotational L bracket",
        preconditions: ["Golden L bracket R1 is Ready with its persisted and downloaded SHA-256 captured."],
        actions: ["Selected Verify revision 1.", "Waited for deterministic validation and cost.", "Inspected the rotational driver, CNC Turning verdict, and complete process shortlist."],
        observed: {
          url: this.page.url(),
          visible: ["Golden_L_bracket-r1.step", "80.0 × 50.0 × 60.0 mm", "40.20 cm³", "watertight true", "SHOULD-COST COMPUTED"],
          persisted: { designId: evidence.designId, revision: evidence.revision, artifactSha256: bracketR1.hash, importedArtifactSha256: evidence.importedArtifactSha256, importedHeaderSha256: evidence.importedHeaderSha256 },
          numeric: { envelopeMm: evidence.envelopeMm, volumeCm3: evidence.volumeCm3, uiVolumeCm3: evidence.uiVolumeCm3, rotational: evidence.rotational, turningVerdict: evidence.turningVerdict, turningShortlisted: evidence.turningShortlisted, validationStatus: evidence.validationStatus, costStatus: evidence.costStatus },
          authorization: { signedIn: true, artifactStatus: 200, validationStatus: evidence.validationStatus, costStatus: evidence.costStatus },
          recovery: "Rejecting CNC Turning did not abort the workflow; DFM, routing alternatives, and should-cost still completed.",
        },
        screenshot: result.screenshot,
      });
      return result;
    });

    let enclosureR1;
    await this.step("Golden open enclosure generates with an open thin-wall cavity", async () => {
      await this.gotoStudio();
      await this.page.getByRole("button", { name: "Open enclosure" }).click();
      enclosureR1 = await this.generateCurrentForm(
        "Golden open enclosure",
        "80.0 × 50.0 × 60.0 mm",
        "54.41 cm³",
      );
      const revision = enclosureR1.design.revision;
      const innerMm = [
        revision.plan.width_mm - 2 * revision.plan.wall_thickness_mm,
        revision.plan.depth_mm - 2 * revision.plan.wall_thickness_mm,
        revision.plan.height_mm - revision.plan.wall_thickness_mm,
      ];
      this.check("DES-08", "create HTTP status", 202, enclosureR1.createStatus);
      this.check("DES-08", "persisted design status", "ready", enclosureR1.design.status);
      this.check("DES-08", "persisted current revision", 1, enclosureR1.design.current_revision);
      this.check("DES-08", "persisted plan kind", "enclosure", revision.plan.kind);
      this.check("DES-08", "persisted outer width", 80, revision.plan.width_mm);
      this.check("DES-08", "persisted outer depth", 50, revision.plan.depth_mm);
      this.check("DES-08", "persisted outer height", 60, revision.plan.height_mm);
      this.check("DES-08", "persisted wall and floor thickness", 3, revision.plan.wall_thickness_mm);
      this.check("DES-08", "persisted outer envelope", [80, 50, 60], revision.geometry.bbox_mm);
      this.check("DES-08", "derived open interior", [74, 44, 57], innerMm);
      this.check("DES-08", "persisted exact shell volume", 54.408, revision.geometry.volume_cm3, Math.abs(revision.geometry.volume_cm3 - 54.408) <= 0.001);
      this.truth("DES-08", "exact UI envelope visible", enclosureR1.visibleText.includes("80.0 × 50.0 × 60.0 mm"));
      this.truth("DES-08", "exact UI rounded volume visible", enclosureR1.visibleText.includes("54.41 cm³"));
      this.truth("DES-08", "UI evidence hash prefix matches artifact", enclosureR1.visibleText.includes(`Evidence hash ${enclosureR1.hashPrefix}`));
      this.check("DES-08", "artifact hash equals persisted geometry hash", revision.geometry_hash, enclosureR1.hash);
      this.check("DES-08", "artifact response header equals bytes", enclosureR1.hash, enclosureR1.responseHeaderSha256);
      this.truth("DES-08", "nonblank cavity preview or explicit fallback", ["interactive", "explicit-fallback"].includes(enclosureR1.visual.mode));
      this.truth("DES-08", "downloaded STEP has durable bytes", enclosureR1.bytes > 128);
      const screenshot = await this.shot("enclosure-ready", true);
      this.recordGoldenPath("DES-08", {
        persona: "CAD engineer generating the default open-top thin-wall enclosure",
        preconditions: ["Authenticated Design Studio with Open enclosure selected at the reviewed defaults."],
        actions: ["Selected Open enclosure.", "Named it Golden open enclosure and generated the design.", "Inspected the open cavity preview, exact shell dimensions/volume, hash, and R1 STEP."],
        observed: {
          url: this.page.url(),
          visible: ["Golden open enclosure", "enclosure · revision 1", "80.0 × 50.0 × 60.0 mm", "54.41 cm³", `Evidence hash ${enclosureR1.hashPrefix}`],
          persisted: { designId: enclosureR1.design.id, status: enclosureR1.design.status, currentRevision: enclosureR1.design.current_revision, revision, artifactSha256: enclosureR1.hash, responseHeaderSha256: enclosureR1.responseHeaderSha256 },
          numeric: { createStatus: enclosureR1.createStatus, outerMm: revision.geometry.bbox_mm, wallAndFloorMm: revision.plan.wall_thickness_mm, innerMm, volumeCm3: revision.geometry.volume_cm3, uiVolumeCm3: 54.41, downloadedBytes: enclosureR1.bytes },
          authorization: { signedIn: true, listStatus: enclosureR1.listStatus, organizationScoped: true },
          recovery: "Ready state preserved the cavity geometry, exact artifact identity, and download/Verify controls without approximation copy.",
        },
        screenshot,
      });
      return { screenshot, evidence: enclosureR1 };
    });

    await this.step("Open enclosure routes as thin-wall geometry and rejects CNC turning", async () => {
      const result = await this.verifySelectedRevision({
        revision: 1,
        filenamePattern: /Golden_open_enclosure-r1\.step/i,
        envelope: "80.0 × 50.0 × 60.0 mm",
        volume: "54.41 cm³",
        envelopeMm: [80, 50, 60],
        uiVolumeCm3: 54.41,
        artifactSha256: enclosureR1.hash,
        turningMustFail: true,
        expectedRouteHint: "polymer",
        expectedArchetype: "thin_wall_enclosure",
      });
      const evidence = result.evidence;
      this.check("DES-09", "selected enclosure revision", 1, evidence.revision);
      this.check("DES-09", "imported enclosure filename", "Golden_open_enclosure-r1.step", evidence.importedFilename);
      this.check("DES-09", "imported bytes equal enclosure SHA", enclosureR1.hash, evidence.importedArtifactSha256);
      this.check("DES-09", "measured envelope", [80, 50, 60], evidence.envelopeMm);
      this.check("DES-09", "measured exact volume", 54.408, evidence.volumeCm3, Math.abs(evidence.volumeCm3 - 54.408) <= 0.01);
      this.check("DES-09", "UI measured volume", 54.41, evidence.uiVolumeCm3);
      this.check("DES-09", "routing archetype", "thin_wall_enclosure", evidence.routingArchetype);
      this.check("DES-09", "routing rotational driver", false, evidence.rotational);
      this.check("DES-09", "CNC turning verdict", "issues", evidence.turningVerdict);
      this.check("DES-09", "CNC turning excluded from shortlist", false, evidence.turningShortlisted);
      this.check("DES-09", "validation HTTP status", 200, evidence.validationStatus);
      this.check("DES-09", "cost HTTP status", 200, evidence.costStatus);
      this.check("DES-09", "watertight result", true, evidence.watertight);
      this.check("DES-09", "should-cost computed", true, evidence.shouldCostComputed);
      this.recordGoldenPath("DES-09", {
        persona: "manufacturing engineer verifying an open thin-wall enclosure",
        preconditions: ["Golden open enclosure R1 is Ready with its persisted and downloaded SHA-256 captured."],
        actions: ["Selected Verify revision 1.", "Waited for deterministic DFM and should-cost.", "Inspected the archetype, rotational driver, CNC Turning verdict, and process shortlist."],
        observed: {
          url: this.page.url(),
          visible: ["Golden_open_enclosure-r1.step", "80.0 × 50.0 × 60.0 mm", "54.41 cm³", "watertight true", "SHOULD-COST COMPUTED"],
          persisted: { designId: evidence.designId, revision: evidence.revision, artifactSha256: enclosureR1.hash, importedArtifactSha256: evidence.importedArtifactSha256, importedHeaderSha256: evidence.importedHeaderSha256 },
          numeric: { envelopeMm: evidence.envelopeMm, volumeCm3: evidence.volumeCm3, uiVolumeCm3: evidence.uiVolumeCm3, routingArchetype: evidence.routingArchetype, rotational: evidence.rotational, turningVerdict: evidence.turningVerdict, turningShortlisted: evidence.turningShortlisted, validationStatus: evidence.validationStatus, costStatus: evidence.costStatus },
          authorization: { signedIn: true, artifactStatus: 200, validationStatus: evidence.validationStatus, costStatus: evidence.costStatus },
          recovery: "CNC Turning rejection remained a scoped process result; the thin-wall route, other DFM results, and cost all completed.",
        },
        screenshot: result.screenshot,
      });
      return result;
    });

    await this.step("Archive confirmation supports cancel and irreversible confirm branches", async () => {
      await this.gotoStudio();
      await this.page.getByRole("button", { name: /Golden open enclosure Ready/ }).click();
      const designId = enclosureR1.design.id;
      const activeBefore = await this.listDesigns();
      const archivesBefore = this.archiveMutationResponses.length;
      let cancelDialogMessage = null;
      this.page.once("dialog", async (dialog) => {
        cancelDialogMessage = dialog.message();
        await dialog.dismiss();
      });
      await this.page.getByRole("button", { name: "Archive design" }).click();
      await this.page.getByRole("button", { name: /Golden open enclosure Ready/ }).waitFor();
      const activeAfterCancel = await this.listDesigns();
      const retainedAfterCancel = await this.api(`/api/proxy/designs/${designId}`);
      this.check("DES-12", "exact archive confirmation", `Archive “Golden open enclosure”? Its audit evidence will be retained.`, cancelDialogMessage);
      this.check("DES-12", "cancel sends no archive mutation", archivesBefore, this.archiveMutationResponses.length);
      this.check("DES-12", "cancel keeps design in active list", true, activeAfterCancel.designs.some((design) => design.id === designId));
      this.check("DES-12", "cancel leaves active count unchanged", activeBefore.designs.length, activeAfterCancel.designs.length);
      this.check("DES-12", "cancel keeps persisted design readable", 200, retainedAfterCancel.status);
      this.check("DES-12", "cancel keeps persisted status ready", "ready", retainedAfterCancel.body.design.status);
      this.check("DES-12", "cancel keeps artifact hash exact", enclosureR1.hash, retainedAfterCancel.body.design.revision.geometry_hash);

      let confirmDialogMessage = null;
      this.page.once("dialog", async (dialog) => {
        confirmDialogMessage = dialog.message();
        await dialog.accept();
      });
      const archiveResponsePromise = this.page.waitForResponse(
        (response) => response.request().method() === "DELETE" && new URL(response.url()).pathname === `/api/proxy/designs/${designId}`,
        { timeout: 20_000 },
      );
      await this.page.getByRole("button", { name: "Archive design" }).click();
      const archiveResponse = await archiveResponsePromise;
      await this.page.getByRole("button", { name: /Golden open enclosure Ready/ }).waitFor({ state: "detached" });
      const activeAfterConfirm = await this.listDesigns();
      const retainedDesign = await this.api(`/api/proxy/designs/${designId}`);
      const retainedRevisions = await this.api(`/api/proxy/designs/${designId}/revisions`);
      const revisions = retainedRevisions.body.revisions || [];
      const retainedR1 = revisions.find((revision) => revision.number === 1);
      const retainedArtifact = await this.revisionArtifact(designId, 1);
      this.check("DES-12", "confirm repeats exact archive confirmation", cancelDialogMessage, confirmDialogMessage);
      this.check("DES-12", "archive HTTP status", 204, archiveResponse.status());
      this.check("DES-12", "confirm sends one archive mutation", archivesBefore + 1, this.archiveMutationResponses.length);
      this.check("DES-12", "active list originally contained design", true, activeBefore.designs.some((design) => design.id === designId));
      this.check("DES-12", "active list loses archived design", false, activeAfterConfirm.designs.some((design) => design.id === designId));
      this.check("DES-12", "confirm removes exactly one active design", activeBefore.designs.length - 1, activeAfterConfirm.designs.length);
      this.check("DES-12", "archived design remains directly readable", 200, retainedDesign.status);
      this.check("DES-12", "persisted status transitions to archived", "archived", retainedDesign.body.design.status);
      this.check("DES-12", "revision history remains readable", 200, retainedRevisions.status);
      this.check("DES-12", "retained revision count", 1, revisions.length);
      this.check("DES-12", "retained current revision", 1, retainedRevisions.body.current_revision);
      this.check("DES-12", "retained revision status", "ready", retainedR1?.status);
      this.check("DES-12", "retained revision hash", enclosureR1.hash, retainedR1?.geometry_hash);
      this.check("DES-12", "retained artifact HTTP status", 200, retainedArtifact.status);
      this.check("DES-12", "retained artifact bytes remain exact", enclosureR1.hash, retainedArtifact.hash);
      this.check("DES-12", "retained artifact response header remains exact", enclosureR1.hash, retainedArtifact.headerHash);
      const screenshot = await this.shot("archive-confirmed");
      this.recordGoldenPath("DES-12", {
        persona: "CAD engineer archiving an obsolete project without destroying immutable evidence",
        preconditions: ["Golden open enclosure R1 is Ready in the active organization list with a captured SHA-256."],
        actions: ["Selected Archive design and cancelled the confirmation.", "Verified the active card and persisted record remained.", "Selected Archive again, accepted the same warning, then inspected active-list removal and retained API evidence."],
        observed: {
          url: this.page.url(),
          visible: [cancelDialogMessage, "Golden open enclosure Ready after cancel", "Golden open enclosure absent after confirm"],
          persisted: { designId, statusAfterCancel: retainedAfterCancel.body.design.status, statusAfterConfirm: retainedDesign.body.design.status, currentRevision: retainedRevisions.body.current_revision, retainedRevision: retainedR1, retainedArtifactSha256: retainedArtifact.hash },
          numeric: { archiveStatus: archiveResponse.status(), archiveMutations: this.archiveMutationResponses.length - archivesBefore, activeCountBefore: activeBefore.designs.length, activeCountAfterCancel: activeAfterCancel.designs.length, activeCountAfterConfirm: activeAfterConfirm.designs.length, retainedRevisionCount: revisions.length, retainedArtifactBytes: retainedArtifact.bytes },
          authorization: { signedIn: true, cancelReadStatus: retainedAfterCancel.status, archivedReadStatus: retainedDesign.status, revisionsStatus: retainedRevisions.status, artifactStatus: retainedArtifact.status, organizationScoped: true },
          recovery: "Cancel preserved the active project; confirm removed it from the active list while its revision metadata, hash, and byte-identical STEP remained readable for audit.",
        },
        screenshot,
      });
      return { screenshot };
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
    return `# Design Studio Human-Simulated E2E\n\n- Date: ${runId}\n- Status: ${data.status}\n- Health: ${data.health}/100\n- Account: ${this.account || "not created"}\n- Structured golden paths: ${data.releaseEvidence.validation.valid}/${data.releaseEvidence.validation.total}\n- Console errors: ${data.consoleErrors.length}\n- Request failures: ${data.requestFailures.length}\n\n| Result | Human journey | ms | Screenshot |\n| --- | --- | ---: | --- |\n${rows}\n`;
  }

  async finish(runError = null) {
    const requestFailures = this.requestFailures
      .filter((failure) => !this.successfulResponses.has(failure.key))
      .map((failure) => failure.message);
    const failed = this.steps.filter((step) => step.status === "fail").length;
    const unexpected = this.consoleErrors.length + requestFailures.length;
    const goldenPaths = this.buildGoldenPaths(requestFailures);
    const validation = validateGoldenPathMap(requiredGoldenIds, goldenPaths);
    const structuredMissing = validation.total - validation.valid;
    const status = failed === 0 && unexpected === 0 && !runError && structuredMissing === 0 ? "PASS" : "NEEDS_FIXES";
    const health = status === "PASS" ? 100 : Math.max(0, 100 - failed * 15 - unexpected * 5 - structuredMissing * 5);
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
      buildIdentity: captureBuildIdentity(repoRoot),
      releaseEvidence: {
        ...makeReleaseEvidence(this.criticalPaths),
        goldenPaths,
        validation,
      },
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
      goldenPaths: `${validation.valid}/${validation.total}`,
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
