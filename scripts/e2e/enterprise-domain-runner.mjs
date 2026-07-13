import { createRequire } from "node:module";
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { captureBuildIdentity, makeReleaseEvidence } from "./human-sim-release-evidence.mjs";
import {
  makeGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const clientIp = process.env.E2E_CLIENT_IP || "198.51.100.86";
const apiBaseUrl = process.env.API_URL || "http://localhost:8000";
const loginEmail = process.env.E2E_LOGIN_EMAIL || "";
const loginPassword = process.env.E2E_LOGIN_PASSWORD || "";
const cadUploadTimeoutMs = Number.parseInt(process.env.E2E_CAD_UPLOAD_TIMEOUT_MS || "150000", 10);
const cubePath = path.join(repoRoot, "backend/tests/assets/cube.step");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const screenshotDir = path.join(
  outputRoot,
  "screenshots",
  `enterprise-domain-${runId}`
);
const artifacts = {
  json: path.join(outputRoot, `enterprise-domain-${runId}.json`),
  md: path.join(outputRoot, `qa-report-enterprise-domain-localhost-${runId}.md`),
};
const launchOptions = {
  channel: "chrome",
  headless: true,
  args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
};

const programName = "Energy Valve Actuation / Train A";
const annualVolume = 12000;
const parentAssembly = "Cryogenic pump skid";
const serviceEnvironment = {
  max_temp_c: 120,
  sour_service: true,
  pressure_bar: 350,
};
const baseQuantityLadder = [1, 100, 1000, 2000, 5000, 10000];
const annualQuantityLadder = [1, 100, 1000, 2000, 10000, 12000];
const processLabels = {
  fdm: "FDM / FFF",
  sla: "SLA Resin",
  dlp: "DLP Resin",
  sls: "SLS (Powder)",
  mjf: "MJF (HP)",
  dmls: "DMLS (Metal)",
  slm: "SLM (Metal)",
  ebm: "EBM (Metal)",
  binder_jetting: "Binder Jetting",
  ded: "DED",
  waam: "WAAM",
  cnc_3axis: "CNC 3-Axis",
  cnc_5axis: "CNC 5-Axis",
  cnc_turning: "CNC Turning",
  wire_edm: "Wire EDM",
  injection_molding: "Injection Molding",
  die_casting: "Die Casting",
  investment_casting: "Investment Casting",
  sand_casting: "Sand Casting",
  sheet_metal: "Sheet Metal",
  forging: "Forging",
};
const structuredGoldenIds = [
  "VER-06",
  "VER-08",
  "WORK-09",
  "WORK-10",
  "WORK-11",
  "ENT-02",
  "ENT-03",
  "ENT-04",
  "ENT-05",
];
const tinyPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

const forbiddenPatterns = [
  /\bCadVerify\b/i,
  /\bin development\b/i,
  /\bunder construction\b/i,
  /\bcoming soon\b/i,
  /\bnot implemented\b/i,
  /\bnot yet implemented\b/i,
  /\bTODO\b/i,
  /\bTBD\b/i,
  /\bstub\b/i,
  /\bmock(?:ed|up)?\b/i,
  /\bplaceholder\b/i,
  /\bpartial(?:ly)?\b/i,
  /S3 reference/i,
  /ComingDoor/i,
  /StubScreen/i,
];

function uniqueEmail(prefix = "cad-engineer") {
  return `${prefix}-${Date.now()}-${process.pid}-${randomBytes(4).toString("hex")}@example.com`;
}

function slug(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 90);
}

function firstMatch(text, regex) {
  const match = text.match(regex);
  if (!match || match.index == null) return null;
  const start = Math.max(0, match.index - 70);
  const end = Math.min(text.length, match.index + match[0].length + 110);
  return text.slice(start, end).replace(/\s+/g, " ").trim();
}

function isIgnorableRequestFailure(url, method, failure) {
  if (/favicon\.ico|\/_next\/webpack-hmr|vercel\/speed-insights/i.test(url)) return true;
  if (failure !== "net::ERR_ABORTED") return false;
  if (/[?&]_rsc=/.test(url)) return true;
  if (method === "GET" && /\/api\/proxy\/cost-decisions\?limit=8(?:&|$)/.test(url)) return true;
  if (
    method === "GET" &&
    /\/api\/proxy\/(?:governance\/change-requests|ground-truth|machine-inventory|rate-library(?:\/effective)?)(?:[/?#]|$)/.test(url)
  ) {
    return true;
  }
  if (method === "POST" && /\/settings\/developer(?:$|\?)/.test(url)) return true;
  return false;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isFiniteNumber(n) {
  return typeof n === "number" && Number.isFinite(n);
}

function approxEqual(a, b, tolerance = Math.max(1, Math.abs(b) * 0.002)) {
  return Math.abs(a - b) <= tolerance;
}

function sameArray(actual, expected) {
  return Array.isArray(actual) &&
    actual.length === expected.length &&
    actual.every((value, index) => value === expected[index]);
}

function assertion(name, expected, actual, pass) {
  return { name, expected, actual, pass: Boolean(pass) };
}

function exactJson(actual, expected) {
  return JSON.stringify(actual) === JSON.stringify(expected);
}

function usdDisplay(value) {
  if (!isFiniteNumber(value)) return "missing cost";
  const digits = value < 100 ? 2 : value < 1000 ? 1 : 0;
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function processDisplay(value) {
  if (!value) return "missing process";
  return processLabels[value] || value;
}

function visibleSignal(text, pattern, fallback) {
  const match = String(text || "").match(pattern);
  return match?.[0]?.replace(/\s+/g, " ").trim() || fallback;
}

function responsePath(response) {
  const url = new URL(response.url());
  return `${url.pathname}${url.search}`;
}

function isNetworkStatusConsoleMessage(text) {
  return /^Failed to load resource: the server responded with a status of [45]\d\d\b/.test(text);
}

function isExpectedHttpErrorResponse(entry) {
  if (entry.status === 422 && entry.path === "/api/proxy/ground-truth/recalibrate") return true;
  return [501, 503].includes(entry.status) && entry.path === "/api/proxy/reconstruct";
}

async function meshHashFor(filePath) {
  const buf = await readFile(filePath);
  return createHash("sha256").update(buf).digest("hex");
}

class EnterpriseDomainQA {
  constructor() {
    this.steps = [];
    this.issues = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.httpErrorResponses = [];
    this.networkStatusConsoleMessages = [];
    this.evidence = {};
  }

  async init() {
    await mkdir(screenshotDir, { recursive: true });
    try {
      this.browser = await pw.chromium.launch(launchOptions);
    } catch {
      this.browser = await pw.chromium.launch({
        headless: true,
        args: launchOptions.args,
      });
    }
    this.context = await this.browser.newContext({
      baseURL: baseUrl,
      extraHTTPHeaders: { "x-real-ip": clientIp },
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
    });
    this.page = await this.context.newPage();
    this.page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const entry = { url: this.page.url(), text: msg.text() };
      if (isNetworkStatusConsoleMessage(entry.text)) {
        this.networkStatusConsoleMessages.push(entry);
      } else {
        this.consoleErrors.push(entry);
      }
    });
    this.page.on("pageerror", (err) => {
      this.consoleErrors.push({ url: this.page.url(), text: err.message });
    });
    this.page.on("requestfailed", (request) => {
      const url = request.url();
      const failure = request.failure()?.errorText || "request failed";
      if (!isIgnorableRequestFailure(url, request.method(), failure)) {
        this.requestFailures.push({ url, method: request.method(), error: failure });
      }
    });
    this.page.on("response", (response) => {
      if (response.status() >= 400) {
        this.httpErrorResponses.push({
          method: response.request().method(),
          path: responsePath(response),
          status: response.status(),
        });
      }
    });
  }

  async close() {
    await this.browser?.close();
  }

  issue(severity, title, detail, screenshot = null) {
    this.issues.push({
      severity,
      title,
      detail,
      screenshot,
      url: this.page?.url?.() || "",
    });
  }

  unexpectedHttpErrorResponses() {
    return this.httpErrorResponses.filter((entry) => !isExpectedHttpErrorResponse(entry));
  }

  async shot(name, fullPage = false) {
    const file = path.join(
      screenshotDir,
      `${String(this.steps.length + 1).padStart(2, "0")}-${slug(name)}.png`
    );
    await this.page.screenshot({ path: file, fullPage, animations: "disabled", caret: "initial" });
    return file;
  }

  async step(name, fn) {
    const started = Date.now();
    try {
      const out = await fn();
      const screenshot = out?.screenshot || (await this.shot(name));
      this.steps.push({
        name,
        status: "pass",
        ms: Date.now() - started,
        screenshot,
        url: this.page.url(),
      });
      return out;
    } catch (error) {
      let screenshot = null;
      try {
        screenshot = await this.shot(`${name}-failure`, true);
      } catch {}
      this.steps.push({
        name,
        status: "fail",
        ms: Date.now() - started,
        screenshot,
        url: this.page.url(),
        error: error instanceof Error ? error.message : String(error),
      });
      this.issue(
        "high",
        `Step failed: ${name}`,
        error instanceof Error ? error.message : String(error),
        screenshot
      );
      return null;
    }
  }

  async visibleText() {
    return this.page.locator("body").innerText({ timeout: 10_000 });
  }

  async scanVisibleText(label) {
    const text = await this.visibleText();
    for (const pattern of forbiddenPatterns) {
      const excerpt = firstMatch(text, pattern);
      if (excerpt) {
        const screenshot = await this.shot(`${label}-forbidden-copy`);
        this.issue(
          "medium",
          `Visible non-final copy on ${label}`,
          `Matched ${pattern}: "${excerpt}"`,
          screenshot
        );
      }
    }
    return text;
  }

  async goto(pathname, label, settleMs = 700) {
    const res = await this.page.goto(pathname, {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    await this.page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
    await this.page.waitForTimeout(settleMs);
    const status = res?.status() ?? 0;
    if (status >= 400) throw new Error(`${label} returned HTTP ${status}`);
    return this.scanVisibleText(label);
  }

  async expectText(signal, label) {
    const text = await this.visibleText();
    if (!signal.test(text)) {
      throw new Error(`${label} did not expose expected text ${signal}`);
    }
    return text;
  }

  async clickRail(title) {
    await this.page.locator(`button[title="${title}"]`).first().click({ timeout: 10_000 });
    await this.page.waitForTimeout(900);
    await this.scanVisibleText(title);
  }

  async api(pathname, options = {}) {
    return this.page.evaluate(
      async ({ pathname, options }) => {
        const method = options.method || "GET";
        const headers = { ...(options.headers || {}) };
        let body;
        if (Object.prototype.hasOwnProperty.call(options, "body")) {
          headers["content-type"] = headers["content-type"] || "application/json";
          body = JSON.stringify(options.body);
        }
        const res = await fetch(`/api/proxy${pathname}`, {
          method,
          headers,
          body,
          cache: "no-store",
        });
        const text = await res.text();
        let parsed = text;
        try {
          parsed = text ? JSON.parse(text) : null;
        } catch {}
        return {
          ok: res.ok,
          status: res.status,
          body: parsed,
          headers: Object.fromEntries(res.headers.entries()),
        };
      },
      { pathname, options }
    );
  }

  async expectApiOk(pathname, options = {}) {
    const res = await this.api(pathname, options);
    if (!res.ok) {
      throw new Error(
        `${options.method || "GET"} ${pathname} returned ${res.status}: ${JSON.stringify(res.body)}`
      );
    }
    return res.body;
  }

  async signup() {
    if (loginEmail && loginPassword) {
      this.account = { email: loginEmail, password: loginPassword };
      await this.step("enterprise engineer logs in and receives an org", async () => {
        await this.goto("/login?next=/verify", "login", 500);
        await this.page.getByLabel("Email").fill(loginEmail);
        await this.page.getByLabel("Password").fill(loginPassword);
        await this.page.getByRole("button", { name: /^Log in$/ }).click();
        await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: 20_000 });
        await this.expectText(/ProofShape|Home|Verify/i, "verify shell after login");
        const members = await this.expectApiOk("/admin/users");
        assert(Array.isArray(members.users), "members response missing users");
        const self = members.users.find((u) => u.email === loginEmail);
        assert(self, "logged-in user was not visible in org members");
        assert(self.org_role === "admin", `expected org admin membership, got ${self.org_role}`);
        this.evidence.member = { email: self.email, role: self.role, org_role: self.org_role };
        return { screenshot: await this.shot("login-enterprise-org") };
      });
      return;
    }

    const email = uniqueEmail("petrovector-cad");
    const password = "Passw0rd123";
    this.account = { email, password };
    await this.step("enterprise engineer signs up and receives an org", async () => {
      await this.goto("/signup", "signup", 500);
      await this.page.getByLabel("Email").fill(email);
      await this.page.getByLabel("Password").fill(password);
      await this.page.getByRole("button", { name: /^Create account$/ }).click();
      await this.page.waitForURL(/\/verify(?:\?|$)/, { timeout: 20_000 });
      await this.expectText(/DAY ZERO SETUP/i, "first-run Verify setup");
      const members = await this.expectApiOk("/admin/users");
      assert(Array.isArray(members.users), "members response missing users");
      const self = members.users.find((u) => u.email === email);
      assert(self, "new user was not visible in org members");
      assert(self.org_role === "admin", `expected org admin membership, got ${self.org_role}`);
      this.evidence.member = { email: self.email, role: self.role, org_role: self.org_role };
      return { screenshot: await this.shot("first-run-verify-enterprise-org") };
    });
  }

  async verifyUnauthenticatedIsolation() {
    await this.step("machine inventory rejects an unauthenticated organization", async () => {
      const context = await this.browser.newContext({
        baseURL: baseUrl,
        extraHTTPHeaders: { "x-real-ip": clientIp },
      });
      const res = await context.request.get("/api/proxy/machine-inventory");
      await context.close();
      assert(
        [401, 403].includes(res.status()),
        `expected unauthenticated machine inventory to reject, got ${res.status()}`
      );
      this.evidence.unauthMachineInventoryStatus = res.status();
      return { screenshot: await this.shot("tenant-isolation-authenticated-context") };
    });
  }

  async publishGovernedRateCard() {
    await this.step("org admin publishes a governed rate card", async () => {
      const before = await this.expectApiOk("/rate-library/effective");
      assert(before.flag_enabled === true, "RATE_LIBRARY_ENABLED is not active");
      assert(before.validated === false, "default effective card must not be validated");

      const draft = await this.expectApiOk("/rate-library", {
        method: "POST",
        body: {
          name: "PetroVector 2026 governed defaults",
          change_note: "Enterprise QA: canonical v0 copied into governed org table.",
        },
      });
      assert(draft.status === "draft", `expected draft rate card, got ${draft.status}`);
      assert(draft.validated === false, "draft governed rate card must not be measured/validated");

      const published = await this.expectApiOk(`/rate-library/${draft.id}/publish`, {
        method: "POST",
        body: {},
      });
      assert(published.status === "published", `expected published, got ${published.status}`);
      assert(published.validated === false, "published governed rate card must remain DEFAULT assumptions");

      const after = await this.expectApiOk("/rate-library/effective");
      assert(after.flag_enabled === true, "rate-library flag turned off after publish");
      assert(after.using_governed === true, "engine is not using the published governed card");
      assert(after.source === "governed_rate_card", `unexpected effective source ${after.source}`);
      assert(after.provenance === "default", `governed card provenance should be default, got ${after.provenance}`);
      assert(after.validated === false, "governed card must not be labeled validated");
      this.evidence.rateCard = {
        id: published.id,
        version: published.version,
        source: after.source,
        validated: after.validated,
      };
      return { screenshot: await this.shot("rate-card-published") };
    });
  }

  async declareMachineFloor() {
    const machines = [
      {
        name: "MJF 5200 - Bay 4",
        process: "mjf",
        count: 3,
        max_workpiece_kg: 8,
        hourly_rate_usd: 48,
        capital_frac: 0.62,
        capabilities: { x: 380, y: 284, z: 380, min_layer_um: 80, min_wall_mm: 0.8 },
        materials: ["polymer"],
        notes: "Houston additive cell; declared envelope/rate for polymer bridge production.",
      },
      {
        name: "Haas VF-4SS - Energy Cell",
        process: "cnc_3axis",
        count: 2,
        max_workpiece_kg: 250,
        hourly_rate_usd: 95,
        capital_frac: 0.55,
        capabilities: {
          x: 1270,
          y: 508,
          z: 635,
          axes: 3,
          achievable_it_grade: 9,
          spindle_power_kw: 22,
          min_tool_dia_mm: 3,
        },
        materials: ["aluminum", "stainless", "steel"],
        notes: "Declared in-house mill capacity for energy hardware should-costing.",
      },
      {
        name: "Mazak Integrex i-200",
        process: "cnc_5axis",
        count: 1,
        max_workpiece_kg: 180,
        hourly_rate_usd: 142,
        capital_frac: 0.58,
        capabilities: {
          x: 660,
          y: 660,
          z: 1016,
          axes: 5,
          motion_mode: "simultaneous_5",
          achievable_it_grade: 8,
          spindle_power_kw: 26,
        },
        materials: ["stainless", "titanium", "steel"],
        notes: "Declared complex-machining cell for valve and actuator bodies.",
      },
      {
        name: "EOS M290 - Nickel/SS Cell",
        process: "dmls",
        count: 1,
        max_workpiece_kg: 20,
        hourly_rate_usd: 185,
        capital_frac: 0.65,
        capabilities: { x: 250, y: 250, z: 325, laser_power_kw: 0.4, min_layer_um: 30, min_wall_mm: 0.3 },
        materials: ["stainless", "titanium"],
        notes: "Declared metal AM cell for sour-service prototypes; qualification still user-declared.",
      },
    ];

    await this.step("CAD organization declares owned machines with rates and envelopes", async () => {
      for (const machine of machines) {
        const created = await this.expectApiOk("/machine-inventory", {
          method: "POST",
          body: machine,
        });
        assert(created.provenance === "user", `${machine.name} provenance was not user`);
        assert(created.name === machine.name, `${machine.name} did not round-trip`);
        assert(created.hourly_rate_usd === machine.hourly_rate_usd, `${machine.name} rate drifted`);
      }
      const page = await this.expectApiOk("/machine-inventory");
      assert(page.machines.length === machines.length, `expected ${machines.length} machines, got ${page.machines.length}`);
      for (const name of machines.map((m) => m.name)) {
        assert(page.machines.some((m) => m.name === name), `${name} missing from machine list`);
      }
      assert(page.machines.every((m) => m.provenance === "user"), "machine list contains non-user provenance");
      this.evidence.machineFloor = page.machines.map((m) => ({
        name: m.name,
        process: m.process,
        rate: m.hourly_rate_usd,
        provenance: m.provenance,
      }));
      return { screenshot: await this.shot("machine-floor-api-declared") };
    });
  }

  async ingestGroundTruthBelowFloor() {
    const records = [
      ["pump-bracket-A.step", "cnc_3axis", 100, 42.5, "aluminum", "RFQ-PV-1001"],
      ["valve-yoke-B.step", "cnc_5axis", 40, 188.25, "stainless", "RFQ-PV-1002"],
      ["sensor-cover-C.step", "mjf", 500, 12.8, "polymer", "RFQ-PV-1003"],
      ["impeller-trial-D.step", "dmls", 12, 510.0, "stainless", "RFQ-PV-1004"],
    ];
    await this.step("historical actuals ingest but recalibration refuses below floor", async () => {
      for (const [part_id, process, quantity, actual_unit_cost_usd, material_class, source] of records) {
        const created = await this.expectApiOk("/ground-truth", {
          method: "POST",
          body: {
            part_id,
            process,
            quantity,
            actual_unit_cost_usd,
            material_class,
            shop: "petrovector-houston-cell",
            region: "US",
            currency: "USD",
            source,
            stand_in: false,
            part_path: null,
            notes: "Enterprise QA real quote datum; geometry intentionally unavailable for floor refusal.",
          },
        });
        assert(created.stand_in === false, `${part_id} was not stored as real actual`);
      }
      const page = await this.expectApiOk("/ground-truth");
      assert(page.total === records.length, `expected ${records.length} actuals, got ${page.total}`);
      assert(page.records.every((r) => r.stand_in === false), "stand-in record appeared in real actuals test");

      const recal = await this.api("/ground-truth/recalibrate", { method: "POST", body: {} });
      assert(recal.status === 422, `below-floor recalibration should be 422, got ${recal.status}`);
      assert(recal.body?.detail?.n_real === records.length, `expected n_real ${records.length}, got ${JSON.stringify(recal.body)}`);
      assert(recal.body?.detail?.min_real === 8, `expected min_real 8, got ${JSON.stringify(recal.body)}`);
      this.evidence.groundTruth = {
        total: page.total,
        n_real: recal.body.detail.n_real,
        min_real: recal.body.detail.min_real,
        recalibration_status: recal.status,
        records: page.records.map((record) => ({
          id: record.id,
          part_id: record.part_id,
          stand_in: record.stand_in,
        })),
      };
      return { screenshot: await this.shot("ground-truth-below-floor") };
    });
  }

  async verifyGovernedUiSurfaces() {
    await this.step("Verify UI shows declared machines and governed truth honestly", async () => {
      await this.goto("/verify", "verify-shell", 1000);
      await this.clickRail("Your machines");
      let text = await this.visibleText();
      for (const name of this.evidence.machineFloor.map((m) => m.name)) {
        assert(text.includes(name), `${name} missing from Your machines UI`);
      }
      assert(/\$48\.00?\/hr|\$48\/hr|\$48\.0\/hr/.test(text), "MJF hourly rate missing from UI");
      assert(/OWNED\s*→\s*MARGINAL/i.test(text), "owned marginal status missing");
      const machineShot = await this.shot("declared-machine-floor-ui", true);

      await this.clickRail("Calibration & truth");
      text = await this.visibleText();
      assert(/GOVERNED CARD IN EFFECT/i.test(text), "governed rate card not visible in Calibration");
      assert(/DEFAULT/i.test(text), "governed card default provenance not visible");
      assert(/real records \(held-out pool\)\s*4/i.test(text), "ground-truth real count missing");
      assert(/floor to validate\s*8 real/i.test(text), "validation floor missing");
      await this.page.getByRole("button", { name: /^Recalibrate$/i }).click();
      await this.page.getByText(/recalibration refused:\s*4 real of 8 needed/i).waitFor({ timeout: 10_000 });
      text = await this.scanVisibleText("calibration-truth-ui");
      const screenshot = await this.shot("calibration-truth-refusal-ui", true);
      this.evidence.groundTruth = {
        ...this.evidence.groundTruth,
        visible_text: text.replace(/\s+/g, " ").trim(),
        url: this.page.url(),
        screenshot,
      };
      return { screenshot, extra: machineShot };
    });
  }

  async createDeveloperKey() {
    await this.step("Developer settings creates, rotates, and revokes an API key exactly once", async () => {
      await this.goto("/settings/developer", "developer-settings", 1000);
      await this.expectText(/Developer|API keys|Create key/i, "developer settings");
      await this.page.getByRole("button", { name: /^Create key$/ }).first().click();
      await this.page.getByText("Save your API key").waitFor({ timeout: 20_000 });
      const initialKey = (await this.page.locator('[role="dialog"] pre').innerText()).trim();
      assert(/^cv_live_[A-Za-z0-9_-]+$/.test(initialKey), "one-time API key secret was not revealed");
      const probe = async (token) => {
        const client = await pw.request.newContext({
          baseURL: apiBaseUrl,
          extraHTTPHeaders: { Authorization: `Bearer ${token}` },
        });
        try {
          const response = await client.get("/api/v1/analyses?limit=1");
          return response.status();
        } finally {
          await client.dispose();
        }
      };
      assert((await probe(initialKey)) === 200, "new API key was not accepted by the real API");
      await this.page.getByLabel(/saved it somewhere safe/i).check();
      await this.page.getByRole("button", { name: /^Done$/ }).click();
      await this.page.getByText("Save your API key").waitFor({ state: "hidden", timeout: 10_000 });
      await this.page.reload({ waitUntil: "networkidle" });
      let text = await this.scanVisibleText("developer-key-created");
      assert(!text.includes(initialKey), "full API key secret reappeared after reload");
      assert(/Default/i.test(text), "created API key row did not appear");
      assert(/Active/i.test(text), "created API key is not active in UI");
      assert(/cv_live_[A-Za-z0-9]{8}_/.test(text), "API key prefix row missing");

      await this.page.getByRole("button", { name: /^Rotate$/ }).first().click();
      await this.page.getByText("Save your API key").waitFor({ timeout: 20_000 });
      const rotatedKey = (await this.page.locator('[role="dialog"] pre').innerText()).trim();
      assert(
        /^cv_live_[A-Za-z0-9_-]+$/.test(rotatedKey) && rotatedKey !== initialKey,
        "rotation did not reveal a distinct replacement key",
      );
      assert((await probe(initialKey)) === 401, "rotated API key remained valid");
      assert((await probe(rotatedKey)) === 200, "replacement API key was not accepted");
      await this.page.getByLabel(/saved it somewhere safe/i).check();
      await this.page.getByRole("button", { name: /^Done$/ }).click();
      await this.page.getByText("Save your API key").waitFor({ state: "hidden", timeout: 10_000 });

      await this.page.getByRole("button", { name: /^Revoke$/ }).first().click();
      await this.page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
      await this.page.waitForTimeout(500);
      assert((await probe(rotatedKey)) === 401, "revoked API key remained valid");
      text = await this.scanVisibleText("developer-key-revoked");
      assert(!text.includes(rotatedKey), "rotated secret reappeared after revocation");
      assert(/Revoked/i.test(text), "revoked API key status did not persist in UI");
      this.evidence.apiKeyLifecycle = {
        createdAccepted: true,
        secretHiddenAfterReload: true,
        oldKeyRejectedAfterRotation: true,
        replacementAccepted: true,
        replacementRejectedAfterRevocation: true,
      };
      return { screenshot: await this.shot("developer-key-lifecycle-complete", true) };
    });
  }

  async runCadVerification() {
    await this.step("CAD engineer verifies a real STEP file in a declared service world", async () => {
      await this.goto("/verify", "cad-verify", 1000);
      await this.clickRail("Verify");
      await this.page.getByRole("button", { name: /^Stainless$/i }).click();
      await this.page.getByRole("button", { name: /120.*service/i }).click();
      await this.page.getByRole("button", { name: /sour service/i }).click();
      await this.page.getByRole("button", { name: /35 MPa pressure/i }).click();
      const costPromise = this.page.waitForResponse((response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/proxy/validate/cost"
      , { timeout: cadUploadTimeoutMs });
      const validationPromise = this.page.waitForResponse((response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/proxy/validate"
      , { timeout: cadUploadTimeoutMs });
      const input = this.page.locator('input[type="file"][accept*=".stl"]').first();
      await input.setInputFiles(cubePath);
      await this.page.waitForTimeout(3000);
      await this.shot("cad-upload-after-3s");
      await this.page
        .waitForFunction(() => {
          const text = document.body.innerText;
          return (
            /What it really takes|computed from POST \/validate\/cost|unit cost|bbox|Geometry invalid|Cost request failed|Validation failed/i.test(text) &&
            !/measuring geometry/i.test(text)
          );
        }, null, { timeout: cadUploadTimeoutMs })
        .catch(async () => {
          const text = await this.visibleText();
          throw new Error(`STEP upload did not reach a terminal result: ${text.slice(0, 700).replace(/\s+/g, " ")}`);
        });
      const text = await this.scanVisibleText("cad-step-upload-result");
      if (/Cost request failed|Validation failed|Network error|Geometry invalid|repair required/i.test(text)) {
        throw new Error(firstMatch(text, /Cost request failed|Validation failed|Network error|Geometry invalid|repair required/i) || "CAD upload failed");
      }
      assert(/world declared.*captured on this part's record|USER.*on the record/i.test(text), "declared service world was not captured on the record");
      assert(/What it really takes|computed from POST \/validate\/cost/i.test(text), "should-cost evidence missing from Verify result");
      assert(/material class\s*stainless|declared class\s*stainless/i.test(text), "stainless material class was not reflected in the result");
      this.evidence.meshHash = await meshHashFor(cubePath);
      const [costResponse, validationResponse] = await Promise.all([costPromise, validationPromise]);
      const [cost, validation] = await Promise.all([
        costResponse.json(),
        validationResponse.json(),
      ]);
      const context = await this.expectApiOk(`/part-context/${this.evidence.meshHash}`);
      const slider = this.page.getByRole("slider").first();
      if (await slider.count()) {
        await slider.press("End");
        await this.page.waitForTimeout(250);
        text = await this.visibleText();
      }
      const quantityReadout = await this.page
        .locator("span")
        .filter({ hasText: /^QUANTITY\s/i })
        .first()
        .innerText()
        .catch(() => "");
      const resourceCards = await this.page
        .locator("p")
        .filter({ hasText: /\/unit (?:at this qty|incl\. tooling)/i })
        .evaluateAll((rows) =>
          rows.map((row) => (row.parentElement?.innerText || row.textContent || "").replace(/\s+/g, " ").trim())
        );
      const screenshot = await this.shot("cad-step-upload-result", true);
      this.evidence.initialVerification = {
        url: this.page.url(),
        screenshot,
        visible_text: text.replace(/\s+/g, " ").trim(),
        cost_status: costResponse.status(),
        validation_status: validationResponse.status(),
        cost,
        validation,
        context,
        quantity_readout: quantityReadout.replace(/\s+/g, " ").trim(),
        resource_cards: resourceCards,
      };
      return { screenshot };
    });
  }

  async verifyInterruptedVerification() {
    await this.step("verification survives in-app navigation without duplicate records", async () => {
      const beforeAnalyses = await this.expectApiOk("/analyses?limit=100");
      const beforeDecisions = await this.expectApiOk("/cost-decisions?limit=100");
      const beforeAnalysisRows = beforeAnalyses.analyses.filter((row) => row.filename === "cube.step");
      const beforeDecisionRows = beforeDecisions.cost_decisions.filter((row) => row.filename === "cube.step");
      assert(beforeAnalysisRows.length === 1, `expected one analysis before repeat, got ${beforeAnalysisRows.length}`);
      assert(beforeDecisionRows.length === 1, `expected one decision before repeat, got ${beforeDecisionRows.length}`);

      await this.goto("/verify", "interrupted-verification", 500);
      await this.clickRail("Verify");
      await this.page.getByRole("button", { name: /^Stainless$/i }).click();
      await this.page.getByRole("button", { name: /120.*service/i }).click();
      await this.page.getByRole("button", { name: /sour service/i }).click();
      await this.page.getByRole("button", { name: /35 MPa pressure/i }).click();
      const costRequest = this.page.waitForRequest((request) =>
        request.method() === "POST" && new URL(request.url()).pathname === "/api/proxy/validate/cost"
      , { timeout: cadUploadTimeoutMs });
      let responseObservedAt = null;
      const costResponse = this.page.waitForResponse((response) =>
        response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/validate/cost"
      , { timeout: cadUploadTimeoutMs }).then((response) => {
        responseObservedAt = Date.now();
        return response;
      });
      await this.page.locator('input[type="file"][accept*=".stl"]').first().setInputFiles(cubePath);
      await costRequest;
      const navigationStartedAt = Date.now();
      assert(responseObservedAt == null, "cost response completed before the navigation-away branch began");
      await this.clickRail("Records");
      const repeatedResponse = await costResponse;
      const repeatedCost = await repeatedResponse.json();
      assert(repeatedResponse.status() === 200, `repeated verification HTTP ${repeatedResponse.status()}`);

      await this.clickRail("Home");
      await this.clickRail("Records");
      await this.page.getByText("cube.step", { exact: true }).first().waitFor({ timeout: 20_000 });

      const afterAnalyses = await this.expectApiOk("/analyses?limit=100");
      const afterDecisions = await this.expectApiOk("/cost-decisions?limit=100");
      const afterAnalysisRows = afterAnalyses.analyses.filter((row) => row.filename === "cube.step");
      const afterDecisionRows = afterDecisions.cost_decisions.filter((row) => row.filename === "cube.step");
      assert(afterAnalysisRows.length === 1, `interrupted repeat created ${afterAnalysisRows.length} analyses`);
      assert(afterDecisionRows.length === 1, `interrupted repeat created ${afterDecisionRows.length} decisions`);
      assert(afterAnalysisRows[0].id === beforeAnalysisRows[0].id, "analysis identity changed after interrupted repeat");
      assert(afterDecisionRows[0].id === beforeDecisionRows[0].id, "decision identity changed after interrupted repeat");
      assert(repeatedCost.saved?.id === beforeDecisionRows[0].id, "deduped response selected a different decision");

      await this.goto("/history", "interrupted-verification-history", 700);
      await this.page.getByText("cube.step", { exact: true }).first().click();
      await this.page.waitForURL(new RegExp(`/analyses/${beforeAnalysisRows[0].id}$`), { timeout: 20_000 });
      await this.page.getByText("Linked cost decisions", { exact: true }).waitFor({ timeout: 20_000 });
      const visible = (await this.visibleText()).replace(/\s+/g, " ").trim();
      const screenshot = await this.shot("interrupted-verification-deduped-result", true);
      this.evidence.interruptedVerification = {
        url: this.page.url(),
        screenshot,
        visible_text: visible,
        repeat_cost_status: repeatedResponse.status(),
        navigation_started_at_ms: navigationStartedAt,
        response_observed_at_ms: responseObservedAt,
        navigation_started_before_response: navigationStartedAt <= responseObservedAt,
        before_analysis_ids: beforeAnalysisRows.map((row) => row.id),
        after_analysis_ids: afterAnalysisRows.map((row) => row.id),
        before_decision_ids: beforeDecisionRows.map((row) => row.id),
        after_decision_ids: afterDecisionRows.map((row) => row.id),
        selected_decision_id: repeatedCost.saved?.id ?? null,
      };
      return { screenshot };
    });
  }

  async verifyIntegrationDryRunImport() {
    await this.step("integration dry-run, import, and retry preserve exact declared rows", async () => {
      const expectedRows = [
        {
          part_id: "PV-INT-001",
          description: "Valve actuator bracket",
          material_class: "stainless",
          program: "Integration QA",
          parent_assembly: "Valve train",
          units_per_parent: 2,
          annual_volume: 12000,
          quantity: 24000,
          region: "US",
          source: "SAP-QA",
          notes: "declared row one",
        },
        {
          part_id: "PV-INT-002",
          description: "Sensor mounting plate",
          material_class: "aluminum",
          program: "Integration QA",
          parent_assembly: "Valve train",
          units_per_parent: 1,
          annual_volume: 6000,
          quantity: 6000,
          region: "US",
          source: "SAP-QA",
          notes: "declared row two",
        },
      ];
      const declaredFields = Object.keys(expectedRows[0]);
      const declaredRows = (manifest) => manifest.parts
        .filter((row) => row.source === "SAP-QA")
        .map((row) => Object.fromEntries(declaredFields.map((field) => [field, row[field]])))
        .sort((a, b) => a.part_id.localeCompare(b.part_id));
      const csv = [
        "part_id,description,material_class,program,parent_assembly,units_per_parent,annual_volume,quantity,region,source,notes",
        "PV-INT-001,Valve actuator bracket,stainless,Integration QA,Valve train,2,12000,24000,US,SAP-QA,declared row one",
        "PV-INT-002,Sensor mounting plate,aluminum,Integration QA,Valve train,1,6000,6000,US,SAP-QA,declared row two",
        "",
      ].join("\n");
      const bytes = Buffer.from(csv, "utf8");
      const fileSha256 = createHash("sha256").update(bytes).digest("hex");
      const payload = { name: "sap-integration-qa.csv", mimeType: "text/csv", buffer: bytes };
      const before = await this.expectApiOk("/manifest?limit=500");

      await this.goto("/integrations", "integrations", 1000);
      await this.page.getByLabel("Connector").selectOption("sap_manifest_csv");
      const runOnce = async (mode) => {
        await this.page.getByLabel("Mode").selectOption(mode);
        await this.page.getByLabel("CSV").setInputFiles(payload);
        const responsePromise = this.page.waitForResponse((response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === "/api/proxy/integrations/runs"
        , { timeout: 30_000 });
        await this.page.getByRole("button", { name: /^Run$/ }).click();
        const response = await responsePromise;
        const body = await response.json();
        assert(response.status() === 200, `${mode} integration HTTP ${response.status()}`);
        return body.run;
      };

      const dryRun = await runOnce("dry_run");
      const afterDryRun = await this.expectApiOk("/manifest?limit=500");
      assert(afterDryRun.parts.length === before.parts.length, "dry-run changed declared manifest rows");

      const imported = await runOnce("import");
      const afterImport = await this.expectApiOk("/manifest?limit=500");
      const importedIds = afterImport.parts
        .filter((row) => row.source === "SAP-QA")
        .map((row) => row.part_id)
        .sort();
      const importedRows = declaredRows(afterImport);
      assert(sameArray(importedIds, ["PV-INT-001", "PV-INT-002"]), `unexpected imported ids ${importedIds}`);
      assert(exactJson(importedRows, expectedRows), `imported row payload drifted: ${JSON.stringify(importedRows)}`);

      const retried = await runOnce("import");
      const afterRetry = await this.expectApiOk("/manifest?limit=500");
      const retryIds = afterRetry.parts
        .filter((row) => row.source === "SAP-QA")
        .map((row) => row.part_id)
        .sort();
      const retryRows = declaredRows(afterRetry);
      assert(sameArray(retryIds, importedIds), "retry changed the declared row identity set");
      assert(exactJson(retryRows, expectedRows), `retry row payload drifted: ${JSON.stringify(retryRows)}`);
      assert(afterRetry.parts.length === afterImport.parts.length, "retry duplicated manifest rows");
      assert([dryRun, imported, retried].every((run) => run.file_sha256 === fileSha256), "run ledger hash drifted");
      assert(dryRun.imported_count === 0 && dryRun.updated_count === 0, "dry-run mutated imported/updated counts");
      assert(imported.imported_count === 2 && imported.updated_count === 0, "initial import counts drifted");
      assert(retried.imported_count === 0 && retried.updated_count === 2, "retry was not an idempotent update");
      assert([dryRun, imported, retried].every((run) => run.raw_stored === false), "raw CSV was stored");

      await this.page.getByText(`${fileSha256.slice(0, 10)}...`, { exact: true }).first().waitFor();
      const visible = (await this.visibleText()).replace(/\s+/g, " ").trim();
      const screenshot = await this.shot("integration-dry-run-import-idempotent", true);
      this.evidence.integration = {
        url: this.page.url(),
        screenshot,
        visible_text: visible,
        file_sha256: fileSha256,
        before_count: before.parts.length,
        after_dry_run_count: afterDryRun.parts.length,
        after_import_count: afterImport.parts.length,
        after_retry_count: afterRetry.parts.length,
        imported_ids: importedIds,
        retry_ids: retryIds,
        expected_rows: expectedRows,
        imported_rows: importedRows,
        retry_rows: retryRows,
        dry_run: dryRun,
        imported,
        retried,
      };
      return { screenshot };
    });
  }

  async verifyHistoryAnalysisDetail() {
    await this.step("History opens the exact persisted analysis and linked decisions", async () => {
      const list = await this.expectApiOk("/analyses?limit=100");
      const row = list.analyses.find((item) => item.filename === "cube.step");
      assert(row, "cube.step missing from analysis history API");
      await this.goto("/history", "analysis-history", 900);
      await this.page.getByText("cube.step", { exact: true }).first().click();
      await this.page.waitForURL(new RegExp(`/analyses/${row.id}$`), { timeout: 20_000 });
      await this.page.getByText("Linked cost decisions", { exact: true }).waitFor({ timeout: 20_000 });
      const detail = await this.expectApiOk(`/analyses/${row.id}`);
      const decisions = await this.expectApiOk("/cost-decisions?limit=100");
      const expectedDecisionIds = decisions.cost_decisions
        .filter((decision) => decision.filename === "cube.step")
        .map((decision) => decision.id)
        .sort();
      const linkedDecisionIds = detail.decision_links.map((decision) => decision.id).sort();
      assert(detail.id === row.id && detail.ulid === row.ulid, "history/detail analysis identity mismatch");
      assert(detail.filename === row.filename && detail.file_type === row.file_type, "history/detail file metadata mismatch");
      assert(detail.overall_verdict === row.overall_verdict, "history/detail verdict mismatch");
      assert(detail.face_count === row.face_count, "history/detail face count mismatch");
      assert(detail.analysis_time_ms === row.analysis_time_ms, "history/detail duration mismatch");
      assert(detail.created_at === row.created_at, "history/detail timestamp mismatch");
      assert(sameArray(linkedDecisionIds, expectedDecisionIds), "analysis decision links do not equal persisted decisions");
      assert(detail.result_json?.geometry, "analysis detail geometry missing");
      assert(Array.isArray(detail.result_json?.process_scores), "analysis detail process findings missing");
      const visibleDecisionLinkCount = await this.page.getByRole("button", { name: "Open decision" }).count();
      assert(visibleDecisionLinkCount === linkedDecisionIds.length, "visible decision links do not match API");
      const visible = (await this.visibleText()).replace(/\s+/g, " ").trim();
      const screenshot = await this.shot("history-analysis-detail-equality", true);
      this.evidence.historyDetail = {
        url: this.page.url(),
        screenshot,
        visible_text: visible,
        list_row: row,
        detail: {
          id: detail.id,
          ulid: detail.ulid,
          filename: detail.filename,
          file_type: detail.file_type,
          overall_verdict: detail.overall_verdict,
          face_count: detail.face_count,
          analysis_time_ms: detail.analysis_time_ms,
          created_at: detail.created_at,
          geometry: detail.result_json.geometry,
          universal_issues: detail.result_json.universal_issues,
          process_scores: detail.result_json.process_scores,
          decision_links: detail.decision_links,
        },
        expected_decision_ids: expectedDecisionIds,
        linked_decision_ids: linkedDecisionIds,
        visible_decision_link_count: visibleDecisionLinkCount,
      };
      return { screenshot };
    });
  }

  async verifyReconstructionRecovery() {
    await this.step("reconstruction returns a real mesh or an actionable upload recovery", async () => {
      await this.goto("/reconstruct", "reconstruction", 700);
      const input = this.page.locator('input[type="file"]').first();
      await input.setInputFiles({
        name: "not-an-image.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("not an image"),
      });
      await this.page.getByRole("alert").filter({ hasText: /not a supported image type/i }).waitFor();
      const invalidText = (await this.page.getByRole("alert").innerText()).replace(/\s+/g, " ").trim();

      await input.setInputFiles({ name: "one-pixel.png", mimeType: "image/png", buffer: tinyPng });
      const responsePromise = this.page.waitForResponse((response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/proxy/reconstruct"
      , { timeout: 30_000 });
      await this.page.getByRole("button", { name: /Reconstruct \(1 image\)/ }).click();
      const submitResponse = await responsePromise;
      const submitBody = await submitResponse.json().catch(() => null);
      let outcome = "actionable-unavailable";
      let meshBytes = 0;
      let job = null;
      let terminalJob = null;

      if (submitResponse.status() === 202) {
        job = submitBody;
        await this.page.waitForFunction(
          () => /Reconstruction result|Reconstruction failed/i.test(document.body.innerText),
          null,
          { timeout: 180_000 },
        );
        const terminal = await this.api(`/jobs/${submitBody.job_id}`);
        assert(terminal.status === 200, `terminal reconstruction status HTTP ${terminal.status}`);
        terminalJob = terminal.body;
        const resultVisible = await this.page.getByText("Reconstruction result", { exact: true }).count();
        if (resultVisible) {
          const mesh = await this.page.evaluate(async (jobId) => {
            const response = await fetch(`/api/proxy/reconstructions/${jobId}/mesh.stl`, { cache: "no-store" });
            const bytes = await response.arrayBuffer();
            return { status: response.status, bytes: bytes.byteLength };
          }, submitBody.job_id);
          assert(mesh.status === 200 && mesh.bytes > 0, `reconstruction mesh response ${JSON.stringify(mesh)}`);
          assert(terminalJob?.status === "done", `mesh visible but terminal job was ${terminalJob?.status}`);
          outcome = "real-mesh";
          meshBytes = mesh.bytes;
        } else {
          await this.page.getByText("Upload images", { exact: true }).waitFor();
          assert(terminalJob?.status === "failed", `failure UI but terminal job was ${terminalJob?.status}`);
          outcome = "actionable-job-failure";
        }
      } else {
        assert([501, 503].includes(submitResponse.status()), `unexpected reconstruction HTTP ${submitResponse.status()}`);
        await this.page.getByText("Reconstruction failed", { exact: true }).waitFor({ timeout: 30_000 });
        await this.page.getByText("Upload images", { exact: true }).waitFor({ timeout: 30_000 });
      }

      const visible = (await this.visibleText()).replace(/\s+/g, " ").trim();
      assert(/Reconstruction failed|Reconstruction result/i.test(visible), "reconstruction ended without an honest terminal state");
      assert(outcome === "real-mesh" || /Upload images/i.test(visible), "failure did not recover to the upload state");
      assert(outcome === "real-mesh" || !/Reconstruction result/i.test(visible), "failure displayed a fake preview");
      const screenshot = await this.shot("reconstruction-real-or-actionable", true);
      this.evidence.reconstruction = {
        url: this.page.url(),
        screenshot,
        visible_text: visible,
        invalid_text: invalidText,
        submit_status: submitResponse.status(),
        submit_body: submitBody,
        outcome,
        mesh_bytes: meshBytes,
        job,
        terminal_job: terminalJob,
      };
      return { screenshot };
    });
  }

  async declarePortfolioContext() {
    await this.step("portfolio withholds exposure until declared volume is re-verified at its exact quantity", async () => {
      const contextBefore = await this.expectApiOk(`/part-context/${this.evidence.meshHash}`);
      assert(contextBefore.provenance === "user", "part context provenance was not user");
      assert(contextBefore.service_environment?.max_temp_c === serviceEnvironment.max_temp_c, "max_temp_c did not persist");
      assert(contextBefore.service_environment?.sour_service === true, "sour_service did not persist");
      assert(contextBefore.service_environment?.pressure_bar === serviceEnvironment.pressure_bar, "pressure_bar did not persist");

      const before = await this.expectApiOk("/catalog/portfolio");
      const rowBefore = before.rows.find((r) => r.part_key === this.evidence.meshHash);
      assert(rowBefore, "verified cube.step did not appear in portfolio");
      assert(rowBefore.filename === "cube.step", `portfolio filename drifted: ${rowBefore.filename}`);
      assert(rowBefore.unit_cost && isFiniteNumber(rowBefore.unit_cost.usd), "portfolio unit cost missing");
      assert(
        approxEqual(rowBefore.unit_cost.usd, 133.58, 0.01),
        `single-part headline oracle drifted: ${rowBefore.unit_cost.usd}`,
      );
      assert(rowBefore.unit_cost.withheld !== true, "portfolio unit cost was unexpectedly withheld");
      assert(rowBefore.context?.service_environment?.sour_service === true, "portfolio lost service environment context");
      assert(rowBefore.context?.annual_volume == null, "annual volume should be absent before declaration");
      assert(rowBefore.annualized_cost_usd == null, "annualized cost was fabricated before volume declaration");
      assert(/no declared annual_volume/i.test(rowBefore.annualized_reason || ""), "missing honest no-volume reason");

      const declared = await this.expectApiOk(`/part-context/${this.evidence.meshHash}`, {
        method: "PUT",
        body: {
          program: programName,
          parent_assembly: parentAssembly,
          units_per_parent: 2,
          annual_volume: annualVolume,
          service_environment: contextBefore.service_environment,
        },
      });
      assert(declared.program === programName, "program declaration did not persist");
      assert(declared.annual_volume === annualVolume, "annual volume declaration did not persist");
      assert(declared.provenance === "user", "program context provenance was not user");

      const after = await this.expectApiOk("/catalog/portfolio");
      const rowAfter = after.rows.find((r) => r.part_key === this.evidence.meshHash);
      assert(rowAfter, "programmed row disappeared from portfolio");
      assert(rowAfter.context.program === programName, "portfolio context program mismatch");
      assert(rowAfter.context.parent_assembly === parentAssembly, "portfolio parent assembly mismatch");
      assert(rowAfter.context.provenance === "user", "portfolio context provenance mismatch");
      assert(rowAfter.annualized_unit_cost == null, "portfolio reused a non-matching quantity basis");
      assert(rowAfter.annualized_cost_usd == null, "portfolio fabricated exposure before exact-quantity verification");
      assert(
        new RegExp(`no engine-computed recommendation at annual_volume ${annualVolume}`, "i").test(rowAfter.annualized_reason || ""),
        "portfolio did not explain the missing exact-quantity recommendation"
      );
      assert(/re-verify this CAD/i.test(rowAfter.annualized_reason || ""), "portfolio did not give a re-verification recovery step");
      const rollup = after.summary.programs?.find((p) => p.program === programName);
      assert(rollup, "program rollup missing");
      assert(rollup.parts === 1, `program rollup parts expected 1, got ${rollup.parts}`);
      assert(rollup.declared_volume_parts === 1, "program rollup lost the declared-volume count");
      assert(rollup.exposed_parts === 0, "program rollup exposed a part without an exact cost point");
      assert(rollup.annualized_cost_usd == null, "program rollup fabricated exposure before re-verification");

      const screenshot = await this.shot("portfolio-awaiting-exact-reverify");
      this.evidence.portfolio = {
        filename: rowAfter.filename,
        mesh_hash: this.evidence.meshHash,
        headline_unit_cost_usd: rowAfter.unit_cost.usd,
        annual_volume: annualVolume,
        withheld_before_volume: rowBefore.annualized_cost_usd == null,
        withheld_reason: rowBefore.annualized_reason,
        withheld_until_exact_reverification: rowAfter.annualized_cost_usd == null,
        exact_reverification_reason: rowAfter.annualized_reason,
        program: programName,
        parent_assembly: rowAfter.context.parent_assembly,
        units_per_parent: rowAfter.context.units_per_parent,
        service_environment: rowAfter.context.service_environment,
        context_provenance: contextBefore.provenance,
        before_exact_screenshot: screenshot,
        before_exact_url: this.page.url(),
      };
      return { screenshot };
    });
  }

  async verifyDeclaredContextInProductStage() {
    await this.step("Verify stage renders declared parent context in product UI", async () => {
      await this.goto("/verify", "verify-stage-context", 1000);
      await this.clickRail("Verify");
      await this.page.getByRole("button", { name: /^Stainless$/i }).click();
      await this.page.getByRole("button", { name: /120.*service/i }).click();
      await this.page.getByRole("button", { name: /sour service/i }).click();
      await this.page.getByRole("button", { name: /35 MPa pressure/i }).click();
      const costPromise = this.page.waitForResponse((response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/proxy/validate/cost"
      , { timeout: cadUploadTimeoutMs });
      const validationPromise = this.page.waitForResponse((response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/proxy/validate"
      , { timeout: cadUploadTimeoutMs });
      const input = this.page.locator('input[type="file"][accept*=".stl"]').first();
      await input.setInputFiles(cubePath);
      await this.page
        .waitForFunction(() => {
          const text = document.body.innerText;
          return (
            /What it really takes|computed from POST \/validate\/cost|unit cost/i.test(text) &&
            !/measuring geometry/i.test(text)
          );
        }, null, { timeout: cadUploadTimeoutMs })
        .catch(async () => {
          const text = await this.visibleText();
          throw new Error(`STEP upload did not reach a terminal result for context UI: ${text.slice(0, 700).replace(/\s+/g, " ")}`);
        });

      const strip = this.page.locator('[data-testid="verify-stage-context"][data-context-state="declared-parent"]').first();
      await strip.waitFor({ timeout: 15_000 });
      const stripText = await strip.innerText();
      assert(stripText.includes(programName), "stage context strip did not show the declared program");
      assert(stripText.includes(parentAssembly), "stage context strip did not show the declared parent assembly");
      assert(/USER/i.test(stripText), "stage context strip did not show USER provenance");
      assert(/service world/i.test(stripText), "stage context strip did not show declared service world");
      await this.page.getByRole("button", { name: /^Seat in assembly$/i }).click();
      await this.page.waitForTimeout(1200);
      const text = await this.scanVisibleText("verify-stage-context-product-ui");
      assert(new RegExp(escapeRegExp(parentAssembly)).test(text), "declared parent assembly missing from product UI text");
      const [costResponse, validationResponse] = await Promise.all([costPromise, validationPromise]);
      const [cost, validation] = await Promise.all([
        costResponse.json(),
        validationResponse.json(),
      ]);
      const slider = this.page.getByRole("slider").first();
      let exactText = text;
      if (await slider.count()) {
        await slider.press("End");
        await this.page.waitForTimeout(250);
        exactText = await this.visibleText();
      }
      const quantityReadout = await this.page
        .locator("span")
        .filter({ hasText: /^QUANTITY\s/i })
        .first()
        .innerText()
        .catch(() => "");
      const resourceCards = await this.page
        .locator("p")
        .filter({ hasText: /\/unit (?:at this qty|incl\. tooling)/i })
        .evaluateAll((rows) =>
          rows.map((row) => (row.parentElement?.innerText || row.textContent || "").replace(/\s+/g, " ").trim())
        );
      const screenshot = await this.shot("verify-stage-declared-context-seated", true);
      this.evidence.productStageContext = {
        program: programName,
        parent_assembly: parentAssembly,
        strip: stripText.replace(/\s+/g, " ").trim(),
        seated: true,
      };
      this.evidence.exactVerification = {
        url: this.page.url(),
        screenshot,
        visible_text: exactText.replace(/\s+/g, " ").trim(),
        cost_status: costResponse.status(),
        validation_status: validationResponse.status(),
        cost,
        validation,
        quantity_readout: quantityReadout.replace(/\s+/g, " ").trim(),
        resource_cards: resourceCards,
      };
      return { screenshot };
    });
  }

  async assertExactQuantityPortfolioCorrectness() {
    await this.step("portfolio computes exact server-side exposure after declared-volume re-verification", async () => {
      const after = await this.expectApiOk("/catalog/portfolio");
      const rowAfter = after.rows.find((r) => r.part_key === this.evidence.meshHash);
      assert(rowAfter, "re-verified programmed row disappeared from portfolio");
      const basis = rowAfter.annualized_unit_cost;
      assert(basis && isFiniteNumber(basis.usd), "exact annualized unit-cost basis missing");
      assert(approxEqual(basis.usd, 10.08), `exact annualized unit-cost oracle drifted: ${basis.usd}`);
      assert(basis.qty === annualVolume, `annualized basis quantity drifted: ${basis.qty}`);
      assert(basis.basis === "decision.recommendation", `annualized basis source drifted: ${basis.basis}`);
      const expectedAnnualized = basis.usd * annualVolume;
      assert(
        approxEqual(rowAfter.annualized_cost_usd, expectedAnnualized),
        `annualized cost mismatch: got ${rowAfter.annualized_cost_usd}, expected ${expectedAnnualized}`
      );
      assert(
        approxEqual(rowAfter.annualized_cost_usd, 120_960),
        `annualized cost oracle drifted: ${rowAfter.annualized_cost_usd}`,
      );
      assert(
        !approxEqual(rowAfter.annualized_cost_usd, 133.58 * annualVolume),
        "single-part $133.58 headline was incorrectly annualized",
      );
      assert(rowAfter.context.program === programName, "portfolio context program mismatch after re-verification");
      assert(rowAfter.context.parent_assembly === parentAssembly, "portfolio parent assembly mismatch after re-verification");
      assert(rowAfter.context.provenance === "user", "portfolio context provenance mismatch after re-verification");

      const rollup = after.summary.programs?.find((p) => p.program === programName);
      assert(rollup, "program rollup missing after re-verification");
      assert(rollup.parts === 1, `program rollup parts expected 1, got ${rollup.parts}`);
      assert(rollup.declared_volume_parts === 1, "program rollup lost the declared-volume count");
      assert(rollup.exposed_parts === 1, "program rollup did not expose the exact-cost part");
      assert(
        approxEqual(rollup.annualized_cost_usd, rowAfter.annualized_cost_usd),
        "program rollup annualized cost does not match member row"
      );

      const screenshot = await this.shot("portfolio-exact-quantity-api-verified");
      this.evidence.portfolio = {
        ...this.evidence.portfolio,
        annualized_unit_cost_usd: basis.usd,
        annualized_unit_cost_qty: basis.qty,
        annualized_unit_cost_basis: basis.basis,
        annualized_cost_usd: rowAfter.annualized_cost_usd,
        expected_annualized_cost_usd: expectedAnnualized,
        exact_screenshot: screenshot,
        exact_url: this.page.url(),
        rollup,
      };
      return { screenshot };
    });
  }

  async verifyProgramUiAndHistory() {
    await this.step("Programs UI and cost history show the verified enterprise part", async () => {
      await this.goto("/verify", "programs-refresh", 1000);
      await this.clickRail("Programs");
      let text = await this.visibleText();
      assert(new RegExp(escapeRegExp(programName)).test(text), "program name missing from Programs UI");
      assert(/1 verified part assigned|1 verified parts assigned/i.test(text), "program part count missing");
      assert(/\/yr exposure/i.test(text), "program exposure missing");
      assert(!/exposure withheld/i.test(text), "program exposure still withheld after declared volume");
      const programsSummaryText = text.replace(/\s+/g, " ").trim();
      await this.page.getByRole("button", { name: /^Open/i }).first().click();
      await this.page.getByText("cube.step", { exact: true }).waitFor({ timeout: 20_000 });
      const annualVolumeInput = await this.page
        .locator('input[title^="annual volume"]')
        .first()
        .inputValue();
      assert(annualVolumeInput === String(annualVolume), `Programs annual volume input drifted: ${annualVolumeInput}`);
      text = await this.visibleText();
      assert(/\$10\.08\s*@ qty\s*12,000/i.test(text), "Programs exact annual unit-cost basis missing");
      assert(/\$120,960\/yr/i.test(text), "Programs exact annual exposure missing");
      const programsText = text.replace(/\s+/g, " ").trim();
      const programsShot = await this.shot("program-exposure-ui", true);

      await this.goto("/cost-decisions", "cost-history", 1000);
      text = await this.scanVisibleText("cost-history");
      assert(/Cost history/i.test(text), "cost history title missing");
      assert(/cube\.step/i.test(text), "verified cube.step missing from cost history");
      const decisions = await this.expectApiOk("/cost-decisions?limit=20");
      const cubeDecisions = decisions.cost_decisions?.filter((decision) => decision.filename === "cube.step") || [];
      assert(cubeDecisions.length > 0, "cost decision API missing cube.step");
      const historyShot = await this.shot("cost-history-cube-step", true);
      const portfolio = await this.expectApiOk("/catalog/portfolio");
      const row = portfolio.rows.find((item) => item.part_key === this.evidence.meshHash);
      const rollup = portfolio.summary.programs?.find((item) => item.program === programName);
      assert(row, "program source row disappeared from portfolio");
      assert(row.cost_decision?.id === cubeDecisions[0].id, "Programs source decision did not equal the newest Records decision");
      await this.page.getByText("cube.step", { exact: true }).first().click();
      await this.page.waitForURL(new RegExp(`/cost-decisions/${cubeDecisions[0].id}$`), { timeout: 20_000 });
      const recordsDetailText = (await this.visibleText()).replace(/\s+/g, " ").trim();
      const recordsDetailShot = await this.shot("program-source-decision-record", true);
      this.evidence.programRollup = {
        url: this.page.url(),
        programs_url: `${baseUrl}/verify`,
        records_list_url: `${baseUrl}/cost-decisions`,
        programs_summary_text: programsSummaryText,
        programs_text: programsText,
        programs_annual_volume_input: annualVolumeInput,
        history_text: text.replace(/\s+/g, " ").trim(),
        records_detail_text: recordsDetailText,
        programs_screenshot: programsShot,
        history_screenshot: historyShot,
        records_detail_screenshot: recordsDetailShot,
        row,
        rollup,
        decision_ids: cubeDecisions.map((decision) => decision.id),
        records_selected_decision_id: cubeDecisions[0].id,
      };
      return { screenshot: recordsDetailShot, extra: programsShot };
    });
  }

  structuredPath({ id, persona, preconditions, actions, observed, screenshot, assertions }) {
    const unexpectedHttpErrors = this.unexpectedHttpErrorResponses();
    const exactAssertions = [
      ...assertions,
      assertion(
        "browser screenshot captured",
        "existing PNG screenshot path",
        screenshot || "missing screenshot",
        typeof screenshot === "string" && /\.png$/i.test(screenshot),
      ),
      assertion("unexpected browser console errors", 0, this.consoleErrors.length, this.consoleErrors.length === 0),
      assertion("unexpected browser request failures", 0, this.requestFailures.length, this.requestFailures.length === 0),
      assertion("unexpected HTTP error responses", 0, unexpectedHttpErrors.length, unexpectedHttpErrors.length === 0),
    ];
    const status = exactAssertions.every((item) => item.pass) ? "PASS" : "FAIL";
    return makeGoldenPathEvidence({
      id,
      status,
      persona,
      preconditions,
      actions,
      observed,
      screenshot: screenshot || "",
      consoleErrors: this.consoleErrors,
      requestFailures: this.requestFailures,
      assertions: exactAssertions,
    });
  }

  buildGoldenPaths() {
    const member = this.evidence.member || {};
    const authorization = {
      email: member.email || "missing authenticated email",
      platformRole: member.role || "missing platform role",
      organizationRole: member.org_role || "missing organization role",
    };
    const authAssertion = () => assertion(
      "authenticated organization role",
      "admin",
      member.org_role || "missing",
      member.org_role === "admin",
    );

    const initial = this.evidence.initialVerification || {};
    const exact = this.evidence.exactVerification || {};
    const initialText = initial.visible_text || "";
    const exactText = exact.visible_text || "";
    const initialRecommendation = initial.cost?.decision?.recommendation?.["10000"] || null;
    const exactRecommendation = exact.cost?.decision?.recommendation?.["10000"] || null;
    const annualRecommendation = exact.cost?.decision?.recommendation?.[String(annualVolume)] || null;
    const recommendationCard = (stage, recommendation) => {
      const process = processDisplay(recommendation?.process);
      const cost = usdDisplay(recommendation?.unit_cost_usd);
      return stage.resource_cards?.find((card) => card.includes(process) && card.includes(cost)) ||
        `missing resource card for ${process} at ${cost}`;
    };
    const initialCard = recommendationCard(initial, initialRecommendation);
    const exactCard = recommendationCard(exact, exactRecommendation);

    const interrupted = this.evidence.interruptedVerification || {};
    const integration = this.evidence.integration || {};
    const history = this.evidence.historyDetail || {};
    const reconstruction = this.evidence.reconstruction || {};
    const groundTruth = this.evidence.groundTruth || {};
    const verification = initial.cost?.verification || {};
    const exclusions = Array.isArray(verification.env_exclusions) ? verification.env_exclusions : [];
    const excludedEstimates = Array.isArray(initial.cost?.estimates)
      ? initial.cost.estimates.filter((estimate) => estimate.environment_excluded === true)
      : [];
    const exclusionReasons = exclusions
      .map((item) => item?.human)
      .filter((item) => typeof item === "string" && item.length > 0);
    const excludedEstimateReasons = excludedEstimates
      .map((item) => item?.environment_exclusion_reason)
      .filter((item) => typeof item === "string" && item.length > 0);
    const portfolio = this.evidence.portfolio || {};
    const program = this.evidence.programRollup || {};

    const expectedActualPartIds = [
      "pump-bracket-A.step",
      "valve-yoke-B.step",
      "sensor-cover-C.step",
      "impeller-trial-D.step",
    ].sort();
    const actualPartIds = (groundTruth.records || []).map((record) => record.part_id).sort();
    const integrationHashes = [
      integration.dry_run?.file_sha256,
      integration.imported?.file_sha256,
      integration.retried?.file_sha256,
    ];
    const historyRow = history.list_row || {};
    const historyDetail = history.detail || {};
    const reconstructionTerminal = reconstruction.terminal_job || {};
    const reconstructionSucceeded =
      reconstruction.outcome === "real-mesh" &&
      reconstruction.submit_status === 202 &&
      reconstructionTerminal.status === "done" &&
      reconstruction.mesh_bytes > 0;
    const reconstructionRecovered =
      reconstruction.outcome === "actionable-job-failure" &&
      reconstruction.submit_status === 202 &&
      reconstructionTerminal.status === "failed" &&
      /Upload images/i.test(reconstruction.visible_text || "") &&
      !/Reconstruction result/i.test(reconstruction.visible_text || "");
    const reconstructionUnavailable =
      reconstruction.outcome === "actionable-unavailable" &&
      [501, 503].includes(reconstruction.submit_status) &&
      /Reconstruction failed/i.test(reconstruction.visible_text || "") &&
      /Upload images/i.test(reconstruction.visible_text || "") &&
      !/Reconstruction result/i.test(reconstruction.visible_text || "");

    return {
      "VER-06": this.structuredPath({
        id: "VER-06",
        persona: "CAD engineer changing material, service world, and computed quantity",
        preconditions: [
          "The deterministic cube.step fixture is available and the organization has a governed rate card and declared machines.",
          "The first verification has no declared annual volume; the second has annual_volume=12000 persisted before re-verification.",
        ],
        actions: [
          "Open Verify, select Stainless, 120 °C, sour service, and 35 MPa, then upload cube.step.",
          "Move the quantity scrubber to its 10,000-unit endpoint and read the displayed recommendation card.",
          "Persist annual_volume=12000, re-verify the same CAD, and inspect the returned six-point ladder and exact 12,000-unit recommendation.",
        ],
        observed: {
          url: exact.url || initial.url || "not observed",
          visible: [
            initial.quantity_readout || "missing initial quantity readout",
            initialCard,
            exact.quantity_readout || "missing exact re-verification quantity readout",
            exactCard,
          ],
          persisted: {
            meshHash: this.evidence.meshHash || "missing",
            initialDecisionId: initial.cost?.saved?.id || "missing",
            exactDecisionId: exact.cost?.saved?.id || "missing",
            partContext: initial.context || "missing",
          },
          numeric: {
            initialQuantities: initial.cost?.quantities || [],
            annualQuantities: exact.cost?.quantities || [],
            selectedQuantity: 10000,
            selectedRecommendation: initialRecommendation || "missing",
            exactSelectedRecommendation: exactRecommendation || "missing",
            annualRecommendation: annualRecommendation || "missing",
          },
          authorization,
          recovery: "The declared annual quantity replaced the nearest interior ladder point without losing either endpoint, and the re-opened Verify result remained tied to its persisted decision.",
        },
        screenshot: exact.screenshot || initial.screenshot,
        assertions: [
          authAssertion(),
          assertion("initial cost response", 200, initial.cost_status ?? "missing", initial.cost_status === 200),
          assertion("initial validation response", 200, initial.validation_status ?? "missing", initial.validation_status === 200),
          assertion("base quantity ladder", baseQuantityLadder, initial.cost?.quantities || [], sameArray(initial.cost?.quantities, baseQuantityLadder)),
          assertion("annual quantity ladder", annualQuantityLadder, exact.cost?.quantities || [], sameArray(exact.cost?.quantities, annualQuantityLadder)),
          assertion("selected quantity readout", "QUANTITY 10,000", initial.quantity_readout || "missing", /QUANTITY\s+10,000/i.test(initial.quantity_readout || "")),
          assertion(
            "initial selected recommendation card",
            `${processDisplay(initialRecommendation?.process)} and ${usdDisplay(initialRecommendation?.unit_cost_usd)}`,
            initialCard,
            Boolean(initialRecommendation) && !initialCard.startsWith("missing resource card"),
          ),
          assertion(
            "reverified selected recommendation card",
            `${processDisplay(exactRecommendation?.process)} and ${usdDisplay(exactRecommendation?.unit_cost_usd)}`,
            exactCard,
            Boolean(exactRecommendation) && !exactCard.startsWith("missing resource card"),
          ),
          assertion("annual recommendation exists", "engine recommendation at 12000", annualRecommendation || "missing", Boolean(annualRecommendation)),
          assertion(
            "annual recommendation reconciles to portfolio basis",
            portfolio.annualized_unit_cost_usd ?? "missing portfolio basis",
            annualRecommendation?.unit_cost_usd ?? "missing annual recommendation",
            isFiniteNumber(annualRecommendation?.unit_cost_usd) &&
              approxEqual(annualRecommendation.unit_cost_usd, portfolio.annualized_unit_cost_usd, 0.001),
          ),
        ],
      }),

      "VER-08": this.structuredPath({
        id: "VER-08",
        persona: "CAD engineer navigating away while deterministic verification is still in flight",
        preconditions: [
          "Exactly one cube.step analysis and one matching cost decision already exist for the selected inputs.",
          "The repeated upload uses the same bytes, material, service world, and quantity parameters.",
        ],
        actions: [
          "Start the repeated cube.step verification and wait until the cost POST has begun.",
          "Navigate in-app to Records before the response completes.",
          "Reopen Records and History, then open the exact persisted analysis detail.",
        ],
        observed: {
          url: interrupted.url || "not observed",
          visible: [
            visibleSignal(interrupted.visible_text, /cube\.step/i, "missing cube.step detail"),
            visibleSignal(interrupted.visible_text, /Linked cost decisions/i, "missing linked decision state"),
          ],
          persisted: {
            beforeAnalysisIds: interrupted.before_analysis_ids || [],
            afterAnalysisIds: interrupted.after_analysis_ids || [],
            beforeDecisionIds: interrupted.before_decision_ids || [],
            afterDecisionIds: interrupted.after_decision_ids || [],
            selectedDecisionId: interrupted.selected_decision_id || "missing",
          },
          numeric: {
            repeatCostStatus: interrupted.repeat_cost_status ?? "missing",
            analysisCountBefore: interrupted.before_analysis_ids?.length ?? 0,
            analysisCountAfter: interrupted.after_analysis_ids?.length ?? 0,
            decisionCountBefore: interrupted.before_decision_ids?.length ?? 0,
            decisionCountAfter: interrupted.after_decision_ids?.length ?? 0,
            navigationStartedAtMs: interrupted.navigation_started_at_ms ?? "missing",
            responseObservedAtMs: interrupted.response_observed_at_ms ?? "missing",
          },
          authorization,
          recovery: "History reopened the original analysis URL and its linked cost decision; the interrupted repeat did not create a second durable record.",
        },
        screenshot: interrupted.screenshot,
        assertions: [
          authAssertion(),
          assertion("repeat cost response", 200, interrupted.repeat_cost_status ?? "missing", interrupted.repeat_cost_status === 200),
          assertion("navigation began while cost response was pending", true, interrupted.navigation_started_before_response ?? "missing", interrupted.navigation_started_before_response === true),
          assertion("analysis count before repeat", 1, interrupted.before_analysis_ids?.length ?? 0, interrupted.before_analysis_ids?.length === 1),
          assertion("analysis count after repeat", 1, interrupted.after_analysis_ids?.length ?? 0, interrupted.after_analysis_ids?.length === 1),
          assertion("analysis identity survives navigation", interrupted.before_analysis_ids?.[0] || "existing analysis id", interrupted.after_analysis_ids?.[0] || "missing", interrupted.before_analysis_ids?.[0] === interrupted.after_analysis_ids?.[0]),
          assertion("decision count before repeat", 1, interrupted.before_decision_ids?.length ?? 0, interrupted.before_decision_ids?.length === 1),
          assertion("decision count after repeat", 1, interrupted.after_decision_ids?.length ?? 0, interrupted.after_decision_ids?.length === 1),
          assertion("decision identity survives navigation", interrupted.before_decision_ids?.[0] || "existing decision id", interrupted.after_decision_ids?.[0] || "missing", interrupted.before_decision_ids?.[0] === interrupted.after_decision_ids?.[0]),
          assertion("deduped response selects durable decision", interrupted.before_decision_ids?.[0] || "existing decision id", interrupted.selected_decision_id || "missing", interrupted.before_decision_ids?.[0] === interrupted.selected_decision_id),
          assertion("recovery analysis URL", `${baseUrl}/analyses/${interrupted.before_analysis_ids?.[0] || "missing"}`, interrupted.url || "missing", interrupted.url === `${baseUrl}/analyses/${interrupted.before_analysis_ids?.[0]}`),
          assertion("linked decision state visible", "Linked cost decisions", visibleSignal(interrupted.visible_text, /Linked cost decisions/i, "missing"), /Linked cost decisions/i.test(interrupted.visible_text || "")),
        ],
      }),

      "WORK-09": this.structuredPath({
        id: "WORK-09",
        persona: "Manufacturing data administrator dry-running and importing a declared SAP manifest",
        preconditions: [
          "An authenticated organization admin is on the offline CSV Integrations surface.",
          "The two-row CSV contains exact declared part, material, program, parent, demand, region, source, and note fields.",
        ],
        actions: [
          "Select SAP manifest CSV and run the exact file in dry_run mode.",
          "Verify no manifest mutation, then run the same bytes in import mode.",
          "Retry the same import and compare counts, row identities, full declared payloads, and SHA-256 ledger entries.",
        ],
        observed: {
          url: integration.url || "not observed",
          visible: [
            visibleSignal(integration.visible_text, /2\/2 valid/i, "missing 2/2 valid count"),
            visibleSignal(integration.visible_text, /dry_run/i, "missing dry_run ledger row"),
            visibleSignal(integration.visible_text, /import/i, "missing import ledger row"),
            visibleSignal(integration.visible_text, new RegExp((integration.file_sha256 || "missing").slice(0, 10), "i"), "missing SHA-256 prefix"),
          ],
          persisted: {
            expectedRows: integration.expected_rows || [],
            importedRows: integration.imported_rows || [],
            retryRows: integration.retry_rows || [],
            importedIds: integration.imported_ids || [],
            retryIds: integration.retry_ids || [],
            runIds: [integration.dry_run?.id, integration.imported?.id, integration.retried?.id].filter(Boolean),
          },
          numeric: {
            fileSha256: integration.file_sha256 || "missing",
            beforeCount: integration.before_count ?? "missing",
            afterDryRunCount: integration.after_dry_run_count ?? "missing",
            afterImportCount: integration.after_import_count ?? "missing",
            afterRetryCount: integration.after_retry_count ?? "missing",
            dryRun: integration.dry_run || "missing",
            import: integration.imported || "missing",
            retry: integration.retried || "missing",
          },
          authorization: {
            ...authorization,
            connector: "sap_manifest_csv",
            boundary: integration.dry_run?.metadata?.proof_boundary || "missing proof boundary",
            rawPayloadStored: integration.dry_run?.raw_stored ?? "missing",
          },
          recovery: "Retrying the identical bytes updated the same two declared rows, kept the manifest cardinality stable, and retained three auditable run-ledger entries without storing raw CSV.",
        },
        screenshot: integration.screenshot,
        assertions: [
          authAssertion(),
          assertion("dry-run rows", { total: 2, valid: 2, invalid: 0 }, { total: integration.dry_run?.rows_total, valid: integration.dry_run?.rows_valid, invalid: integration.dry_run?.rows_invalid }, integration.dry_run?.rows_total === 2 && integration.dry_run?.rows_valid === 2 && integration.dry_run?.rows_invalid === 0),
          assertion("dry-run mutation counts", { imported: 0, updated: 0 }, { imported: integration.dry_run?.imported_count, updated: integration.dry_run?.updated_count }, integration.dry_run?.imported_count === 0 && integration.dry_run?.updated_count === 0),
          assertion("dry-run leaves manifest unchanged", integration.before_count ?? "initial count", integration.after_dry_run_count ?? "missing", integration.before_count === integration.after_dry_run_count),
          assertion("initial import counts", { imported: 2, updated: 0 }, { imported: integration.imported?.imported_count, updated: integration.imported?.updated_count }, integration.imported?.imported_count === 2 && integration.imported?.updated_count === 0),
          assertion("retry counts", { imported: 0, updated: 2 }, { imported: integration.retried?.imported_count, updated: integration.retried?.updated_count }, integration.retried?.imported_count === 0 && integration.retried?.updated_count === 2),
          assertion("retry cardinality is stable", integration.after_import_count ?? "post-import count", integration.after_retry_count ?? "missing", integration.after_import_count === integration.after_retry_count),
          assertion("imported declared payloads", integration.expected_rows || [], integration.imported_rows || [], exactJson(integration.imported_rows, integration.expected_rows)),
          assertion("retried declared payloads", integration.expected_rows || [], integration.retry_rows || [], exactJson(integration.retry_rows, integration.expected_rows)),
          assertion("run ledger SHA-256", integration.file_sha256 || "computed SHA-256", integrationHashes, integrationHashes.length === 3 && integrationHashes.every((hash) => hash === integration.file_sha256)),
          assertion("raw CSV is never stored", [false, false, false], [integration.dry_run?.raw_stored, integration.imported?.raw_stored, integration.retried?.raw_stored], [integration.dry_run, integration.imported, integration.retried].every((run) => run?.raw_stored === false)),
          assertion("visible run counts", "2/2 valid", visibleSignal(integration.visible_text, /2\/2 valid/i, "missing"), /2\/2 valid/i.test(integration.visible_text || "")),
          assertion("visible file hash prefix", (integration.file_sha256 || "missing").slice(0, 10), integration.visible_text?.includes((integration.file_sha256 || "missing").slice(0, 10)) ?? false, Boolean(integration.file_sha256) && integration.visible_text?.includes(integration.file_sha256.slice(0, 10))),
        ],
      }),

      "WORK-10": this.structuredPath({
        id: "WORK-10",
        persona: "Engineer reopening an analysis from durable History",
        preconditions: [
          "cube.step has a persisted analysis and one or more cost decisions in the same organization.",
          "History is populated from the organization-scoped analyses API.",
        ],
        actions: [
          "Open History and click the visible cube.step row.",
          "Wait for the exact /analyses/{id} route and fetch that same detail record.",
          "Compare identity, metadata, timing, verdict, geometry, findings, and linked decisions against persisted API data.",
        ],
        observed: {
          url: history.url || "not observed",
          visible: [
            visibleSignal(history.visible_text, /cube\.step/i, "missing cube.step title"),
            visibleSignal(history.visible_text, /Linked cost decisions/i, "missing linked decisions card"),
            visibleSignal(history.visible_text, new RegExp(historyRow.overall_verdict || "missing-verdict", "i"), "missing verdict"),
          ],
          persisted: {
            listRow: historyRow,
            detail: historyDetail,
            expectedDecisionIds: history.expected_decision_ids || [],
            linkedDecisionIds: history.linked_decision_ids || [],
          },
          numeric: {
            faceCount: historyDetail.face_count ?? "missing",
            analysisTimeMs: historyDetail.analysis_time_ms ?? "missing",
            processFindingCount: historyDetail.process_scores?.length ?? "missing",
            universalFindingCount: historyDetail.universal_issues?.length ?? "missing",
            visibleDecisionLinkCount: history.visible_decision_link_count ?? "missing",
          },
          authorization,
          recovery: "The History row reopened the exact durable analysis URL, and every linked decision button corresponded one-for-one with the organization-scoped API links.",
        },
        screenshot: history.screenshot,
        assertions: [
          authAssertion(),
          assertion("history URL identity", `${baseUrl}/analyses/${historyRow.id || "missing"}`, history.url || "missing", history.url === `${baseUrl}/analyses/${historyRow.id}`),
          assertion("analysis id", historyRow.id || "list id", historyDetail.id || "missing", Boolean(historyRow.id) && historyDetail.id === historyRow.id),
          assertion("analysis ulid", historyRow.ulid || "list ulid", historyDetail.ulid || "missing", Boolean(historyRow.ulid) && historyDetail.ulid === historyRow.ulid),
          assertion("filename and type", { filename: historyRow.filename, fileType: historyRow.file_type }, { filename: historyDetail.filename, fileType: historyDetail.file_type }, historyDetail.filename === historyRow.filename && historyDetail.file_type === historyRow.file_type),
          assertion("verdict", historyRow.overall_verdict || "list verdict", historyDetail.overall_verdict || "missing", Boolean(historyRow.overall_verdict) && historyDetail.overall_verdict === historyRow.overall_verdict),
          assertion("face count", historyRow.face_count ?? "list face count", historyDetail.face_count ?? "missing", isFiniteNumber(historyRow.face_count) && historyDetail.face_count === historyRow.face_count),
          assertion("analysis time", historyRow.analysis_time_ms ?? "list duration", historyDetail.analysis_time_ms ?? "missing", isFiniteNumber(historyRow.analysis_time_ms) && historyDetail.analysis_time_ms === historyRow.analysis_time_ms),
          assertion("created timestamp", historyRow.created_at || "list timestamp", historyDetail.created_at || "missing", Boolean(historyRow.created_at) && historyDetail.created_at === historyRow.created_at),
          assertion("measured geometry persisted", "non-empty geometry object", historyDetail.geometry || "missing", Boolean(historyDetail.geometry && Object.keys(historyDetail.geometry).length > 0)),
          assertion("process findings persisted", "process_scores array", historyDetail.process_scores || "missing", Array.isArray(historyDetail.process_scores)),
          assertion("universal findings persisted", "universal_issues array", historyDetail.universal_issues || "missing", Array.isArray(historyDetail.universal_issues)),
          assertion("linked decision ids", history.expected_decision_ids || [], history.linked_decision_ids || [], sameArray(history.linked_decision_ids, history.expected_decision_ids)),
          assertion("visible decision links", history.linked_decision_ids?.length ?? "linked count", history.visible_decision_link_count ?? "missing", history.visible_decision_link_count === history.linked_decision_ids?.length),
        ],
      }),

      "WORK-11": this.structuredPath({
        id: "WORK-11",
        persona: "Engineer attempting image-to-mesh reconstruction and recovering from invalid or unavailable inputs",
        preconditions: [
          "The authenticated Reconstruction surface accepts JPEG, PNG, or WebP and exposes bounded job polling.",
          "A text file and a deterministic one-pixel PNG are available as adversarial browser inputs.",
        ],
        actions: [
          "Select the unsupported text file and read the inline validation alert.",
          "Replace it with the valid PNG and submit one reconstruction.",
          "Wait for a real terminal mesh or an actionable failure, then verify mesh bytes or the restored upload state and persisted job status.",
        ],
        observed: {
          url: reconstruction.url || "not observed",
          visible: [
            reconstruction.invalid_text || "missing unsupported-image alert",
            visibleSignal(reconstruction.visible_text, /Reconstruction result|Reconstruction failed/i, "missing terminal reconstruction state"),
            visibleSignal(reconstruction.visible_text, /Upload images|Reconstruction result/i, "missing recovery or result state"),
          ],
          persisted: reconstruction.submit_status === 202
            ? {
                jobId: reconstruction.submit_body?.job_id || "missing",
                submitted: reconstruction.job || "missing",
                terminal: reconstruction.terminal_job || "missing",
              }
            : {
                jobId: "not-created",
                serviceStatus: reconstruction.submit_status ?? "missing",
                response: reconstruction.submit_body || "missing",
              },
          numeric: {
            submitStatus: reconstruction.submit_status ?? "missing",
            outcome: reconstruction.outcome || "missing",
            meshBytes: reconstruction.mesh_bytes ?? "missing",
            terminalStatus: reconstructionTerminal.status || "not-created",
          },
          authorization,
          recovery: reconstructionSucceeded
            ? `A real STL response returned ${reconstruction.mesh_bytes} bytes.`
            : "The failure returned to Upload images with a visible error and no Reconstruction result preview.",
        },
        screenshot: reconstruction.screenshot,
        assertions: [
          authAssertion(),
          assertion("unsupported image validation", "not a supported image type; use JPEG, PNG, or WebP", reconstruction.invalid_text || "missing", /not a supported image type.*JPEG, PNG, or WebP/i.test(reconstruction.invalid_text || "")),
          assertion("bounded submit status", "202, 501, or 503", reconstruction.submit_status ?? "missing", [202, 501, 503].includes(reconstruction.submit_status)),
          assertion(
            "honest terminal outcome",
            "real mesh or actionable upload recovery",
            { outcome: reconstruction.outcome || "missing", terminalStatus: reconstructionTerminal.status || "not-created", meshBytes: reconstruction.mesh_bytes ?? "missing" },
            reconstructionSucceeded || reconstructionRecovered || reconstructionUnavailable,
          ),
          assertion("no fake preview on failure", false, reconstruction.outcome === "real-mesh" ? false : /Reconstruction result/i.test(reconstruction.visible_text || ""), reconstruction.outcome === "real-mesh" || !/Reconstruction result/i.test(reconstruction.visible_text || "")),
          assertion("failure recovery returns upload control", true, reconstruction.outcome === "real-mesh" ? "not-applicable-real-mesh" : /Upload images/i.test(reconstruction.visible_text || ""), reconstruction.outcome === "real-mesh" || /Upload images/i.test(reconstruction.visible_text || "")),
          assertion("real mesh is non-empty when successful", "> 0 bytes or not-applicable failure", reconstruction.mesh_bytes ?? "missing", reconstruction.outcome !== "real-mesh" || reconstruction.mesh_bytes > 0),
        ],
      }),

      "ENT-02": this.structuredPath({
        id: "ENT-02",
        persona: "Manufacturing calibration owner proving the minimum real-data boundary",
        preconditions: [
          "The organization has a published governed rate card that remains DEFAULT and unvalidated.",
          "Exactly four non-stand-in historical actuals are available, below the required floor of eight.",
        ],
        actions: [
          "Create the four actual-cost records and reopen Calibration & truth.",
          "Confirm the visible real-record count and validation floor.",
          "Choose Recalibrate and inspect the exact refusal plus persisted API counts.",
        ],
        observed: {
          url: groundTruth.url || "not observed",
          visible: [
            visibleSignal(groundTruth.visible_text, /real records \(held-out pool\)\s*4/i, "missing real-record count"),
            visibleSignal(groundTruth.visible_text, /floor to validate\s*8 real/i, "missing validation floor"),
            visibleSignal(groundTruth.visible_text, /recalibration refused:\s*4 real of 8 needed/i, "missing refusal"),
          ],
          persisted: {
            records: groundTruth.records || [],
            partIds: actualPartIds,
            governedRateCard: this.evidence.rateCard || "missing",
          },
          numeric: {
            total: groundTruth.total ?? "missing",
            real: groundTruth.n_real ?? "missing",
            minimum: groundTruth.min_real ?? "missing",
            recalibrationStatus: groundTruth.recalibration_status ?? "missing",
          },
          authorization,
          recovery: "Recalibration remained refused and unvalidated; the four real rows were retained so four more measured records can be added without data loss.",
        },
        screenshot: groundTruth.screenshot,
        assertions: [
          authAssertion(),
          assertion("persisted actual count", 4, groundTruth.total ?? "missing", groundTruth.total === 4),
          assertion("real-data count", 4, groundTruth.n_real ?? "missing", groundTruth.n_real === 4),
          assertion("minimum real-data floor", 8, groundTruth.min_real ?? "missing", groundTruth.min_real === 8),
          assertion("recalibration refusal status", 422, groundTruth.recalibration_status ?? "missing", groundTruth.recalibration_status === 422),
          assertion("exact persisted part ids", expectedActualPartIds, actualPartIds, sameArray(actualPartIds, expectedActualPartIds)),
          assertion("all actuals are real", false, (groundTruth.records || []).map((record) => record.stand_in), groundTruth.records?.length === 4 && groundTruth.records.every((record) => record.stand_in === false)),
          assertion("governed card remains unvalidated", false, this.evidence.rateCard?.validated ?? "missing", this.evidence.rateCard?.validated === false),
          assertion("visible refusal", "recalibration refused: 4 real of 8 needed", visibleSignal(groundTruth.visible_text, /recalibration refused:\s*4 real of 8 needed/i, "missing"), /recalibration refused:\s*4 real of 8 needed/i.test(groundTruth.visible_text || "")),
        ],
      }),

      "ENT-03": this.structuredPath({
        id: "ENT-03",
        persona: "Energy-sector CAD engineer declaring a severe stainless service world",
        preconditions: [
          "The organization has USER-declared machine envelopes and rates.",
          "The cube.step verification begins with no inferred service context.",
        ],
        actions: [
          "Select Stainless, 120 °C service, sour service, and 35 MPa pressure.",
          "Upload cube.step and wait for both DFM and cost responses.",
          "Read the persisted part context, verification lattice, excluded estimates, and visible standards-cited reasons.",
        ],
        observed: {
          url: initial.url || "not observed",
          visible: [
            visibleSignal(initialText, /120\s*°C service/i, "missing 120 °C service"),
            visibleSignal(initialText, /sour service(?: \(H₂S\))?/i, "missing sour service"),
            visibleSignal(initialText, /35 MPa pressure/i, "missing 35 MPa pressure"),
            exclusionReasons[0] || excludedEstimateReasons[0] || "missing standards-cited exclusion",
          ],
          persisted: {
            meshHash: this.evidence.meshHash || "missing",
            context: initial.context || "missing",
            verification,
          },
          numeric: {
            maxTemperatureC: initial.context?.service_environment?.max_temp_c ?? "missing",
            pressureBar: initial.context?.service_environment?.pressure_bar ?? "missing",
            sourService: initial.context?.service_environment?.sour_service ?? "missing",
            environmentExclusionCount: exclusions.length,
            excludedEstimateCount: excludedEstimates.length,
          },
          authorization,
          recovery: "The severe service world remained on the durable part context and reappeared on re-verification; excluded options stayed explicit instead of silently entering the recommendation.",
        },
        screenshot: initial.screenshot,
        assertions: [
          authAssertion(),
          assertion("service context temperature", 120, initial.context?.service_environment?.max_temp_c ?? "missing", initial.context?.service_environment?.max_temp_c === 120),
          assertion("service context sour flag", true, initial.context?.service_environment?.sour_service ?? "missing", initial.context?.service_environment?.sour_service === true),
          assertion("service context pressure", 350, initial.context?.service_environment?.pressure_bar ?? "missing", initial.context?.service_environment?.pressure_bar === 350),
          assertion("service context provenance", "user", initial.context?.provenance || "missing", initial.context?.provenance === "user"),
          assertion("selected cost material class", "stainless", initial.cost?.material_class || "missing", initial.cost?.material_class === "stainless"),
          assertion("environment declared to verification", true, verification.environment_declared ?? "missing", verification.environment_declared === true),
          assertion("machine inventory declared to verification", true, verification.inventory_declared ?? "missing", verification.inventory_declared === true),
          assertion("standards-cited environment exclusions", "one or more exclusions, every reason cites NACE/HDT/ASME/ASTM/ISO", exclusionReasons, exclusions.length > 0 && exclusions.every((item) => /NACE|HDT|ASME|ASTM|ISO/i.test(item?.human || ""))),
          assertion("excluded routes or materials in cost estimates", "one or more environment_excluded estimates", excludedEstimates.length, excludedEstimates.length > 0),
          assertion("excluded estimate reasons are cited", "every excluded estimate has a standards citation", excludedEstimateReasons, excludedEstimates.length > 0 && excludedEstimates.every((item) => /NACE|HDT|ASME|ASTM|ISO/i.test(item?.environment_exclusion_reason || ""))),
          assertion("exclusion reasons visible", exclusionReasons, exclusionReasons.filter((reason) => initialText.includes(reason)), exclusionReasons.length > 0 && exclusionReasons.every((reason) => initialText.includes(reason))),
          assertion("temperature visible", "120 °C service", visibleSignal(initialText, /120\s*°C service/i, "missing"), /120\s*°C service/i.test(initialText)),
          assertion("sour service visible", "sour service", visibleSignal(initialText, /sour service/i, "missing"), /sour service/i.test(initialText)),
          assertion("pressure visible", "35 MPa pressure", visibleSignal(initialText, /35 MPa pressure/i, "missing"), /35 MPa pressure/i.test(initialText)),
        ],
      }),

      "ENT-04": this.structuredPath({
        id: "ENT-04",
        persona: "Program cost owner assigning annual volume and demanding exact-quantity economics",
        preconditions: [
          "cube.step has the pinned single-part $133.58 headline under the governed organization fixture.",
          "The part has severe-service USER context but initially has no annual volume.",
        ],
        actions: [
          "Read the portfolio before annual volume and confirm annual exposure is withheld.",
          "Declare program, parent assembly, units per parent, and annual_volume=12000; confirm exposure remains withheld pending exact re-verification.",
          "Re-verify cube.step and reconcile the exact 12,000-unit recommendation to the annual portfolio exposure.",
        ],
        observed: {
          url: portfolio.exact_url || "not observed",
          visible: [
            visibleSignal(exactText, new RegExp(escapeRegExp(programName)), "missing program context"),
            visibleSignal(exactText, new RegExp(escapeRegExp(parentAssembly)), "missing parent assembly"),
            visibleSignal(exactText, /USER/i, "missing USER provenance"),
          ],
          persisted: {
            meshHash: portfolio.mesh_hash || "missing",
            program: portfolio.program || "missing",
            parentAssembly: portfolio.parent_assembly || "missing",
            unitsPerParent: portfolio.units_per_parent ?? "missing",
            annualVolume: portfolio.annual_volume ?? "missing",
            contextProvenance: portfolio.context_provenance || "missing",
            rollup: portfolio.rollup || "missing",
          },
          numeric: {
            singlePartHeadlineUsd: portfolio.headline_unit_cost_usd ?? "missing",
            exactQuantity: portfolio.annualized_unit_cost_qty ?? "missing",
            exactUnitCostUsd: portfolio.annualized_unit_cost_usd ?? "missing",
            annualExposureUsd: portfolio.annualized_cost_usd ?? "missing",
            expectedAnnualExposureUsd: portfolio.expected_annualized_cost_usd ?? "missing",
            basis: portfolio.annualized_unit_cost_basis || "missing",
          },
          authorization,
          recovery: "Before exact re-verification the API explained why exposure was withheld; after re-verification the exact 12,000-unit engine point supplied the only annualization basis.",
        },
        screenshot: portfolio.exact_screenshot || exact.screenshot,
        assertions: [
          authAssertion(),
          assertion("single-part headline", 133.58, portfolio.headline_unit_cost_usd ?? "missing", approxEqual(portfolio.headline_unit_cost_usd, 133.58, 0.01)),
          assertion("exposure withheld before volume", true, portfolio.withheld_before_volume ?? "missing", portfolio.withheld_before_volume === true),
          assertion("exposure withheld before exact re-verification", true, portfolio.withheld_until_exact_reverification ?? "missing", portfolio.withheld_until_exact_reverification === true),
          assertion("withheld reason gives re-verification action", "Re-verify this CAD", portfolio.exact_reverification_reason || "missing", /Re-verify this CAD/i.test(portfolio.exact_reverification_reason || "")),
          assertion("exact annual quantity", 12000, portfolio.annualized_unit_cost_qty ?? "missing", portfolio.annualized_unit_cost_qty === 12000),
          assertion("exact annual unit cost", 10.08, portfolio.annualized_unit_cost_usd ?? "missing", approxEqual(portfolio.annualized_unit_cost_usd, 10.08, 0.001)),
          assertion("annual exposure", 120960, portfolio.annualized_cost_usd ?? "missing", approxEqual(portfolio.annualized_cost_usd, 120960, 0.01)),
          assertion("annual exposure multiplication", (portfolio.annualized_unit_cost_usd ?? 0) * annualVolume, portfolio.annualized_cost_usd ?? "missing", approxEqual(portfolio.annualized_cost_usd, (portfolio.annualized_unit_cost_usd ?? 0) * annualVolume, 0.01)),
          assertion("annualization basis", "decision.recommendation", portfolio.annualized_unit_cost_basis || "missing", portfolio.annualized_unit_cost_basis === "decision.recommendation"),
          assertion("single-part headline is not annualized", false, approxEqual(portfolio.annualized_cost_usd, 133.58 * annualVolume, 0.01), !approxEqual(portfolio.annualized_cost_usd, 133.58 * annualVolume, 0.01)),
          assertion("program context", programName, portfolio.program || "missing", portfolio.program === programName),
          assertion("parent assembly context", parentAssembly, portfolio.parent_assembly || "missing", portfolio.parent_assembly === parentAssembly),
          assertion("context provenance", "user", portfolio.context_provenance || "missing", portfolio.context_provenance === "user"),
          assertion("12,000 recommendation reconciles", 10.08, annualRecommendation?.unit_cost_usd ?? "missing", approxEqual(annualRecommendation?.unit_cost_usd, 10.08, 0.001)),
        ],
      }),

      "ENT-05": this.structuredPath({
        id: "ENT-05",
        persona: "Enterprise program owner reconciling Programs with the source decision in Records",
        preconditions: [
          "The exact 12,000-unit re-verification is persisted and assigned to Energy Valve Actuation / Train A.",
          "Programs and Records read the same organization-scoped portfolio and cost-decision stores.",
        ],
        actions: [
          "Open Programs, then open the program detail and inspect cube.step, its volume, exact unit basis, and annual exposure.",
          "Open Records and inspect the cube.step decision list.",
          "Open the newest cube.step decision and compare its ID with the program portfolio source decision.",
        ],
        observed: {
          url: program.url || "not observed",
          visible: [
            visibleSignal(program.programs_summary_text, new RegExp(escapeRegExp(programName)), "missing program name"),
            visibleSignal(program.programs_text, /cube\.step/i, "missing assigned part"),
            visibleSignal(program.programs_text, /\$10\.08\s*@ qty\s*12,000/i, "missing exact quantity basis"),
            visibleSignal(program.programs_text, /\$120,960\/yr/i, "missing annual exposure"),
            visibleSignal(program.records_detail_text, /cube\.step/i, "missing source decision detail"),
          ],
          persisted: {
            portfolioRow: program.row || "missing",
            programRollup: program.rollup || "missing",
            decisionIds: program.decision_ids || [],
            recordsSelectedDecisionId: program.records_selected_decision_id || "missing",
            recordsDetailScreenshot: program.records_detail_screenshot || "missing",
            programsScreenshot: program.programs_screenshot || "missing",
          },
          numeric: {
            assignedParts: program.rollup?.parts ?? "missing",
            declaredVolumeParts: program.rollup?.declared_volume_parts ?? "missing",
            exposedParts: program.rollup?.exposed_parts ?? "missing",
            annualVolume: program.row?.context?.annual_volume ?? "missing",
            rowExposureUsd: program.row?.annualized_cost_usd ?? "missing",
            rollupExposureUsd: program.rollup?.annualized_cost_usd ?? "missing",
          },
          authorization,
          recovery: "Opening the Records row selected the exact decision ID referenced by the Programs portfolio row; no filename-only proxy was used for source identity.",
        },
        screenshot: program.records_detail_screenshot || program.programs_screenshot,
        assertions: [
          authAssertion(),
          assertion("program rollup name", programName, program.rollup?.program || "missing", program.rollup?.program === programName),
          assertion("assigned verified parts", 1, program.rollup?.parts ?? "missing", program.rollup?.parts === 1),
          assertion("declared-volume parts", 1, program.rollup?.declared_volume_parts ?? "missing", program.rollup?.declared_volume_parts === 1),
          assertion("exposed parts", 1, program.rollup?.exposed_parts ?? "missing", program.rollup?.exposed_parts === 1),
          assertion("program annual volume input", "12000", program.programs_annual_volume_input || "missing", program.programs_annual_volume_input === "12000"),
          assertion("portfolio annual volume", 12000, program.row?.context?.annual_volume ?? "missing", program.row?.context?.annual_volume === 12000),
          assertion("portfolio exact unit basis", { qty: 12000, usd: 10.08, basis: "decision.recommendation" }, { qty: program.row?.annualized_unit_cost?.qty, usd: program.row?.annualized_unit_cost?.usd, basis: program.row?.annualized_unit_cost?.basis }, program.row?.annualized_unit_cost?.qty === 12000 && approxEqual(program.row?.annualized_unit_cost?.usd, 10.08, 0.001) && program.row?.annualized_unit_cost?.basis === "decision.recommendation"),
          assertion("row annual exposure", 120960, program.row?.annualized_cost_usd ?? "missing", approxEqual(program.row?.annualized_cost_usd, 120960, 0.01)),
          assertion("rollup annual exposure", program.row?.annualized_cost_usd ?? "row exposure", program.rollup?.annualized_cost_usd ?? "missing", approxEqual(program.rollup?.annualized_cost_usd, program.row?.annualized_cost_usd, 0.01)),
          assertion("source decision identity", program.row?.cost_decision?.id || "portfolio source id", program.records_selected_decision_id || "missing", Boolean(program.row?.cost_decision?.id) && program.row.cost_decision.id === program.records_selected_decision_id),
          assertion("source decision appears in Records API", program.row?.cost_decision?.id || "portfolio source id", program.decision_ids || [], program.decision_ids?.includes(program.row?.cost_decision?.id)),
          assertion("source Records URL", `${baseUrl}/cost-decisions/${program.records_selected_decision_id || "missing"}`, program.url || "missing", program.url === `${baseUrl}/cost-decisions/${program.records_selected_decision_id}`),
          assertion("program detail visible", "cube.step, $10.08 @ qty 12,000, $120,960/yr", program.programs_text || "missing", /cube\.step/i.test(program.programs_text || "") && /\$10\.08\s*@ qty\s*12,000/i.test(program.programs_text || "") && /\$120,960\/yr/i.test(program.programs_text || "")),
        ],
      }),
    };
  }

  async finish() {
    if (this.consoleErrors.length > 0) {
      const sample = this.consoleErrors
        .slice(0, 8)
        .map((e) => `${e.url}: ${e.text}`)
        .join("\n");
      this.issue("medium", "Browser console errors occurred during enterprise QA", sample);
    }
    if (this.requestFailures.length > 0) {
      const sample = this.requestFailures
        .slice(0, 8)
        .map((e) => `${e.method} ${e.url}: ${e.error}`)
        .join("\n");
      this.issue("medium", "Network request failures occurred during enterprise QA", sample);
    }
    const unexpectedHttpErrors = this.unexpectedHttpErrorResponses();
    if (unexpectedHttpErrors.length > 0) {
      const sample = unexpectedHttpErrors
        .slice(0, 12)
        .map((entry) => `${entry.method} ${entry.path}: HTTP ${entry.status}`)
        .join("\n");
      this.issue("medium", "Unexpected HTTP error responses occurred during enterprise QA", sample);
    }

    const criticalPaths = {
      "ENT-01": {
        rateCardSource: this.evidence.rateCard?.source,
        validated: this.evidence.rateCard?.validated,
        machineRates: this.evidence.machineFloor || [],
      },
      "ENT-02": {
        total: this.evidence.groundTruth?.total,
        nReal: this.evidence.groundTruth?.n_real,
        minimumReal: this.evidence.groundTruth?.min_real,
        recalibrationRefused:
          this.evidence.groundTruth?.n_real === 4 && this.evidence.groundTruth?.min_real === 8,
      },
      "ENT-04": {
        quantity: this.evidence.portfolio?.annualized_unit_cost_qty,
        unitCostUsd: this.evidence.portfolio?.annualized_unit_cost_usd,
        annualExposureUsd: this.evidence.portfolio?.annualized_cost_usd,
        basis: this.evidence.portfolio?.annualized_unit_cost_basis,
        withheldBeforeExactQuantity:
          this.evidence.portfolio?.withheld_before_volume === true &&
          this.evidence.portfolio?.withheld_until_exact_reverification === true,
      },
    };
    const goldenPaths = this.buildGoldenPaths();
    const validation = validateGoldenPathMap(structuredGoldenIds, goldenPaths);
    if (validation.valid !== validation.total) {
      const sample = validation.problems
        .slice(0, 12)
        .map((problem) => `${problem.id} ${problem.field}: expected ${JSON.stringify(problem.expected)}, got ${JSON.stringify(problem.actual)}`)
        .join("\n");
      this.issue("medium", "Structured enterprise golden evidence is incomplete", sample);
    }

    const severityRank = { critical: 4, high: 3, medium: 2, low: 1 };
    const blocking = this.issues.filter((i) => severityRank[i.severity] >= severityRank.medium);
    const failedSteps = this.steps.filter((s) => s.status === "fail").length;
    const health = Math.max(
      0,
      100 -
        this.issues.filter((i) => i.severity === "critical").length * 30 -
        this.issues.filter((i) => i.severity === "high").length * 18 -
        this.issues.filter((i) => i.severity === "medium").length * 8 -
        this.issues.filter((i) => i.severity === "low").length * 3
    );
    const status =
      blocking.length === 0 &&
      failedSteps === 0 &&
      validation.valid === validation.total
        ? "PASS"
        : "NEEDS_FIXES";
    const releaseEvidence = {
      ...makeReleaseEvidence(criticalPaths),
      goldenPaths,
      validation,
    };
    const data = {
      status,
      health,
      baseUrl,
      generatedAt: new Date().toISOString(),
      account: this.account ? { email: this.account.email } : null,
      steps: this.steps,
      issues: this.issues,
      consoleErrors: this.consoleErrors,
      requestFailures: this.requestFailures,
      diagnostics: {
        consoleErrors: this.consoleErrors,
        requestFailures: this.requestFailures,
        httpErrorResponses: this.httpErrorResponses,
        networkStatusConsoleMessages: this.networkStatusConsoleMessages,
      },
      evidence: this.evidence,
      buildIdentity: captureBuildIdentity(repoRoot),
      releaseEvidence,
      screenshotDir,
    };
    await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
    await writeFile(artifacts.md, this.markdown(data));
    console.log(
      JSON.stringify(
        {
          status,
          health,
          issues: this.issues.length,
          failedSteps,
          goldenPaths: `${validation.valid}/${validation.total}`,
          goldenPathStatus: Object.fromEntries(
            structuredGoldenIds.map((id) => [id, goldenPaths[id]?.status || "MISSING"]),
          ),
          report: artifacts.md,
          screenshots: screenshotDir,
          evidence: this.evidence,
        },
        null,
        2
      )
    );
    if (status !== "PASS") process.exitCode = 1;
  }

  markdown(data) {
    const rows = data.steps
      .map((s) => `| ${s.status === "pass" ? "PASS" : "FAIL"} | ${s.name} | ${s.url} | ${s.screenshot || ""} |`)
      .join("\n");
    const issues = data.issues.length
      ? data.issues
          .map((i, idx) => `${idx + 1}. **${i.severity.toUpperCase()}** ${i.title}\n   ${i.detail}\n   ${i.screenshot ? `Screenshot: ${i.screenshot}` : ""}`)
          .join("\n")
      : "No medium-or-higher issues found.";
    const goldenRows = structuredGoldenIds
      .map((id) => {
        const result = data.releaseEvidence.validation.byId[id];
        const evidence = data.releaseEvidence.goldenPaths[id];
        return `| ${result?.valid ? "PASS" : "FAIL"} | ${id} | ${evidence?.assertions?.length || 0} | ${result?.failures?.map((failure) => failure.field).join(", ") || "none"} | ${evidence?.screenshot || ""} |`;
      })
      .join("\n");
    return `# Enterprise Domain QA - Localhost

- Date: ${runId}
- Target: ${data.baseUrl}
- Status: ${data.status}
- Health score: ${data.health}/100
- Screenshots: ${data.screenshotDir}
- Test account: ${data.account?.email || "not created/logged in"}
- Structured golden evidence: ${data.releaseEvidence.validation.valid}/${data.releaseEvidence.validation.total}

## Enterprise Scenario

Persona: CAD/cost engineer in an ExxonMobil-like manufacturing organization.

The test signs up or logs in as a real org admin, proves unauthenticated org data is rejected, publishes a governed rate card, declares owned machines, ingests historical actuals, proves calibration refuses under the real-data floor, creates a developer API key through the UI, uploads a real STEP file, declares a sour/high-pressure/high-temperature service world, and verifies portfolio exposure remains withheld until the declared annual volume has an exact re-verified engine point.

## Correctness Assertions

- Governed rate cards are in effect only after publish and remain DEFAULT / not validated.
- Machine envelopes, rates, and materials round-trip with provenance=user.
- Ground-truth recalibration refuses with 4 real records because the floor is 8.
- API key creation reveals the one-time secret on /settings/developer.
- The Verify UI persists the declared service world to part-context before costing.
- Portfolio annualized exposure is null before annual_volume and after declaration until re-verification; it then equals the engine recommendation at that exact quantity × declared volume.
- Program roll-up equals the member row exposure and keeps context provenance=user.

## Evidence

\`\`\`json
${JSON.stringify(data.evidence, null, 2)}
\`\`\`

## Structured golden paths

| Result | ID | Assertions | Failed fields | Screenshot |
| --- | --- | ---: | --- | --- |
${goldenRows}

## Issues

${issues}

## Steps

| Result | Step | URL | Screenshot |
| --- | --- | --- | --- |
${rows}
`;
  }
}

const runner = new EnterpriseDomainQA();
try {
  await runner.init();
  await runner.signup();
  await runner.verifyUnauthenticatedIsolation();
  await runner.publishGovernedRateCard();
  await runner.declareMachineFloor();
  await runner.ingestGroundTruthBelowFloor();
  await runner.verifyGovernedUiSurfaces();
  await runner.verifyIntegrationDryRunImport();
  await runner.createDeveloperKey();
  await runner.runCadVerification();
  await runner.verifyInterruptedVerification();
  await runner.declarePortfolioContext();
  await runner.verifyDeclaredContextInProductStage();
  await runner.assertExactQuantityPortfolioCorrectness();
  await runner.verifyHistoryAnalysisDetail();
  await runner.verifyProgramUiAndHistory();
  await runner.verifyReconstructionRecovery();
} finally {
  await runner.finish().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
  await runner.close().catch(() => {});
}
