import { createRequire } from "node:module";
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
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

const forbiddenPatterns = [
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
  if (method === "POST" && /\/settings\/developer(?:$|\?)/.test(url)) return true;
  return method === "GET" && /\/_next\/static\/chunks\/[^/?]+\.js(?:\?|$)/.test(url);
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
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
    });
    this.page = await this.context.newPage();
    this.page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const text = msg.text();
      if (
        !/favicon\.ico|ResizeObserver loop limit exceeded/i.test(text) &&
        !/Failed to load resource: the server responded with a status of 422/i.test(text)
      ) {
        this.consoleErrors.push({ url: this.page.url(), text });
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

  async shot(name, fullPage = false) {
    const file = path.join(
      screenshotDir,
      `${String(this.steps.length + 1).padStart(2, "0")}-${slug(name)}.png`
    );
    await this.page.screenshot({ path: file, fullPage, animations: "disabled" });
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
    const email = uniqueEmail("petrovector-cad");
    const password = "Passw0rd123";
    this.account = { email, password };
    await this.step("enterprise engineer signs up and receives an org", async () => {
      await this.goto("/signup", "signup", 500);
      await this.page.getByLabel("Email").fill(email);
      await this.page.getByLabel("Password").fill(password);
      await this.page.getByRole("button", { name: /^Create account$/ }).click();
      await this.page.waitForURL(/\/onboarding(?:\?|$)/, { timeout: 20_000 });
      await this.expectText(/Declare your world before the engine prices it/i, "onboarding");
      const members = await this.expectApiOk("/admin/users");
      assert(Array.isArray(members.users), "members response missing users");
      const self = members.users.find((u) => u.email === email);
      assert(self, "new user was not visible in org members");
      assert(self.org_role === "admin", `expected org admin membership, got ${self.org_role}`);
      this.evidence.member = { email: self.email, role: self.role, org_role: self.org_role };
      return { screenshot: await this.shot("onboarding-enterprise-org") };
    });
  }

  async verifyUnauthenticatedIsolation() {
    await this.step("machine inventory rejects an unauthenticated organization", async () => {
      const context = await this.browser.newContext({ baseURL: baseUrl });
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
      await this.scanVisibleText("calibration-truth-ui");
      return { screenshot: await this.shot("calibration-truth-refusal-ui", true), extra: machineShot };
    });
  }

  async createDeveloperKey() {
    await this.step("Developer settings creates and reveals an API key exactly once", async () => {
      await this.goto("/settings/developer", "developer-settings", 1000);
      await this.expectText(/Developer|API keys|Create key/i, "developer settings");
      await this.page.getByRole("button", { name: /^Create key$/ }).first().click();
      await this.page.getByText("Save your API key").waitFor({ timeout: 20_000 });
      const revealText = await this.visibleText();
      assert(/cv_live_[A-Za-z0-9_-]+/.test(revealText), "one-time API key secret was not revealed");
      await this.page.getByLabel(/saved it somewhere safe/i).check();
      await this.page.getByRole("button", { name: /^Done$/ }).click();
      await this.page.getByText("Save your API key").waitFor({ state: "hidden", timeout: 10_000 });
      await this.page.waitForTimeout(1000);
      const text = await this.scanVisibleText("developer-key-created");
      assert(/Default/i.test(text), "created API key row did not appear");
      assert(/Active/i.test(text), "created API key is not active in UI");
      assert(/cv_live_[A-Za-z0-9]{8}_/.test(text), "API key prefix row missing");
      return { screenshot: await this.shot("developer-key-created", true) };
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
        }, null, { timeout: 90_000 })
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
      return { screenshot: await this.shot("cad-step-upload-result", true) };
    });
  }

  async assertPortfolioCorrectness() {
    await this.step("portfolio withholds exposure until declared volume, then computes server-side math", async () => {
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
      const expectedAnnualized = rowAfter.unit_cost.usd * annualVolume;
      assert(
        approxEqual(rowAfter.annualized_cost_usd, expectedAnnualized),
        `annualized cost mismatch: got ${rowAfter.annualized_cost_usd}, expected ${expectedAnnualized}`
      );
      assert(rowAfter.context.program === programName, "portfolio context program mismatch");
      assert(rowAfter.context.parent_assembly === parentAssembly, "portfolio parent assembly mismatch");
      assert(rowAfter.context.provenance === "user", "portfolio context provenance mismatch");
      const rollup = after.summary.programs?.find((p) => p.program === programName);
      assert(rollup, "program rollup missing");
      assert(rollup.parts === 1, `program rollup parts expected 1, got ${rollup.parts}`);
      assert(
        approxEqual(rollup.annualized_cost_usd, rowAfter.annualized_cost_usd),
        "program rollup annualized cost does not match member row"
      );

      this.evidence.portfolio = {
        filename: rowAfter.filename,
        mesh_hash: this.evidence.meshHash,
        unit_cost_usd: rowAfter.unit_cost.usd,
        annual_volume: annualVolume,
        annualized_cost_usd: rowAfter.annualized_cost_usd,
        expected_annualized_cost_usd: expectedAnnualized,
        withheld_before_volume: rowBefore.annualized_cost_usd == null,
        withheld_reason: rowBefore.annualized_reason,
        program: programName,
        parent_assembly: rowAfter.context.parent_assembly,
        units_per_parent: rowAfter.context.units_per_parent,
        service_environment: rowAfter.context.service_environment,
        context_provenance: contextBefore.provenance,
      };
      return { screenshot: await this.shot("portfolio-math-api-verified") };
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
      const programsShot = await this.shot("program-exposure-ui", true);

      await this.goto("/cost-decisions", "cost-history", 1000);
      text = await this.scanVisibleText("cost-history");
      assert(/Cost history/i.test(text), "cost history title missing");
      assert(/cube\.step/i.test(text), "verified cube.step missing from cost history");
      const decisions = await this.expectApiOk("/cost-decisions?limit=20");
      assert(
        decisions.cost_decisions?.some((d) => d.filename === "cube.step"),
        "cost decision API missing cube.step"
      );
      return { screenshot: await this.shot("cost-history-cube-step", true), extra: programsShot };
    });
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
    const status = blocking.length === 0 && failedSteps === 0 ? "PASS" : "NEEDS_FIXES";
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
      evidence: this.evidence,
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
    return `# Enterprise Domain QA - Localhost

- Date: ${runId}
- Target: ${data.baseUrl}
- Status: ${data.status}
- Health score: ${data.health}/100
- Screenshots: ${data.screenshotDir}
- Test account: ${data.account?.email || "not created"}

## Enterprise Scenario

Persona: CAD/cost engineer in an ExxonMobil-like manufacturing organization.

The test signs up a real org admin, proves unauthenticated org data is rejected, publishes a governed rate card, declares owned machines, ingests historical actuals, proves calibration refuses under the real-data floor, creates a developer API key through the UI, uploads a real STEP file, declares a sour/high-pressure/high-temperature service world, and verifies portfolio exposure is withheld until annual volume is user-declared.

## Correctness Assertions

- Governed rate cards are in effect only after publish and remain DEFAULT / not validated.
- Machine envelopes, rates, and materials round-trip with provenance=user.
- Ground-truth recalibration refuses with 4 real records because the floor is 8.
- API key creation reveals the one-time secret on /settings/developer.
- The Verify UI persists the declared service world to part-context before costing.
- Portfolio annualized exposure is null before annual_volume and equals unit cost × declared volume after declaration.
- Program roll-up equals the member row exposure and keeps context provenance=user.

## Evidence

\`\`\`json
${JSON.stringify(data.evidence, null, 2)}
\`\`\`

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
  await runner.createDeveloperKey();
  await runner.runCadVerification();
  await runner.assertPortfolioCorrectness();
  await runner.verifyProgramUiAndHistory();
} finally {
  await runner.finish().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
  await runner.close().catch(() => {});
}
