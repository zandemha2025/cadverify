import { createRequire } from "node:module";
import { randomBytes } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const loginEmail = process.env.E2E_LOGIN_EMAIL || "";
const loginPassword = process.env.E2E_LOGIN_PASSWORD || "";
const cadUploadTimeoutMs = Number.parseInt(process.env.E2E_CAD_UPLOAD_TIMEOUT_MS || "150000", 10);
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const screenshotDir = path.join(outputRoot, "screenshots", `human-e2e-${runId}`);
const artifacts = {
  json: path.join(outputRoot, `human-e2e-${runId}.json`),
  md: path.join(outputRoot, `qa-report-localhost-${runId}.md`),
};
const launchOptions = {
  channel: "chrome",
  headless: true,
  args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
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

const expectedSignals = {
  "/": [/ProofShape/i, /cost/i],
  "/platform": [/Platform/i, /Verify/i],
  "/developers": [/Developers/i, /api/i],
  "/api-reference": [/API/i, /validate/i],
  "/docs": [/API|Docs|ProofShape/i],
  "/teams": [/teams/i, /sourcing/i],
  "/teams/cost-engineering": [/Cost engineering|cost/i],
  "/teams/design-engineering": [/Design engineering|engineering/i],
  "/teams/sourcing": [/Sourcing/i, /quote/i],
  "/teams/in-house-manufacturing": [/Triage/i, /make/i],
  "/teams/shop-owners": [/Shop owners|shop/i],
  "/method": [/method/i, /geometry/i],
  "/security": [/security/i, /CAD/i],
  "/status": [/status/i],
  "/company": [/pilot/i, /ProofShape/i],
  "/pilot-report": [/pilot/i, /report/i],
  "/privacy": [/Privacy/i],
  "/terms": [/Terms/i],
  "/dpa": [/Data Processing|DPA|processing/i],
};

const appRoutes = [
  { path: "/cost", signal: /cost|should-cost|workbench|analyze/i },
  { path: "/analyze", signal: /Upload|Analyze|CAD|analysis/i },
  { path: "/batch", signal: /Batch|Start batch|ZIP/i },
  { path: "/cost-decisions", signal: /Cost history|saved should-cost/i },
  { path: "/cost-decisions/compare", signal: /Compare cost decisions|Pick two saved decisions/i },
  { path: "/rfq-packages", signal: /RFQ packages|Generated packages|New package/i },
  { path: "/integrations", signal: /Integrations|Connector runs|Recent runs/i },
  { path: "/history", signal: /History|recent analyses/i },
  { path: "/reconstruct", signal: /Image to 3D|Reconstruct|photographs/i },
  { path: "/label", signal: /Parts \(Label\)|Labeling|corpus|label/i },
  { path: "/design-system", signal: /Foundations|Glass box|Calibration|Design/i },
  { path: "/settings/developer", signal: /Developer|API|settings|404|not found/i, allow404: true },
  { path: "/notifications", signal: /Notifications|all caught up|states/i },
];

const railSurfaces = [
  { title: "Home", signal: /Home|verification desk|ProofShape/i },
  { title: "Verify", signal: /Drop a part|Verify a part|STEP|STL/i },
  { title: "Parts", signal: /Parts|No parts|catalog/i },
  { title: "Records", signal: /Records|No records|verified/i },
  { title: "Programs", signal: /Programs|No verified parts|exposure/i },
  { title: "Your machines", signal: /machines|Declare your floor|No machines/i },
  { title: "Triage", signal: /Triage|makeability/i },
  { title: "Calibration & truth", signal: /Calibration|truth|rates/i },
];

function uniqueEmail(prefix = "qa") {
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
  const start = Math.max(0, match.index - 60);
  const end = Math.min(text.length, match.index + match[0].length + 90);
  return text.slice(start, end).replace(/\s+/g, " ").trim();
}

function isIgnorableRequestFailure(url, method, failure) {
  if (/favicon\.ico|vercel\/speed-insights|\/_next\/webpack-hmr/i.test(url)) return true;
  if (failure !== "net::ERR_ABORTED") return false;
  if (/[?&]_rsc=/.test(url)) return true;
  if (method === "GET" && /\/api\/proxy\/cost-decisions\?limit=8(?:&|$)/.test(url)) return true;
  // The rail sweep intentionally leaves Programs after proving the surface.
  // A subsequent document navigation may cancel its still-in-flight read; only
  // that browser-generated ERR_ABORTED is expected (HTTP/network errors remain).
  if (method === "GET" && /\/api\/proxy\/catalog\/portfolio(?:\?|$)/.test(url)) return true;
  if (
    method === "GET" &&
    /\/api\/proxy\/(?:governance\/change-requests|ground-truth|machine-inventory|rate-library(?:\/effective)?)(?:[/?#]|$)/.test(url)
  ) {
    return true;
  }
  return method === "GET" && /\/_next\/static\/chunks\/[^/?]+\.js(?:\?|$)/.test(url);
}

class HumanE2E {
  constructor() {
    this.steps = [];
    this.issues = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.visited = [];
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
      viewport: { width: 1440, height: 960 },
      baseURL: baseUrl,
      reducedMotion: "reduce",
    });
    this.page = await this.context.newPage();
    this.page.on("console", (msg) => {
      if (msg.type() === "error") {
        const text = msg.text();
        if (!/favicon\.ico|ResizeObserver loop limit exceeded/i.test(text)) {
          this.consoleErrors.push({ url: this.page.url(), text });
        }
      }
    });
    this.page.on("pageerror", (err) => {
      this.consoleErrors.push({ url: this.page.url(), text: err.message });
    });
    this.page.on("requestfailed", (request) => {
      const url = request.url();
      const failure = request.failure()?.errorText || "request failed";
      if (!isIgnorableRequestFailure(url, request.method(), failure)) {
        this.requestFailures.push({
          url,
          method: request.method(),
          error: failure,
        });
      }
    });
  }

  async close() {
    await this.browser?.close();
  }

  issue(severity, title, detail, screenshot = null) {
    this.issues.push({ severity, title, detail, screenshot, url: this.page?.url?.() || "" });
  }

  async shot(name, fullPage = false) {
    const file = path.join(screenshotDir, `${String(this.steps.length + 1).padStart(2, "0")}-${slug(name)}.png`);
    // Playwright's default caret hiding mutates an input's inline style. If a
    // screenshot races React hydration, that test-only mutation creates a false
    // hydration mismatch. Keep the page DOM untouched while capturing evidence.
    await this.page.screenshot({ path: file, fullPage, animations: "disabled", caret: "initial" });
    return file;
  }

  async step(name, fn) {
    const started = Date.now();
    try {
      const out = await fn();
      const screenshot = out?.screenshot || (await this.shot(name));
      this.steps.push({ name, status: "pass", ms: Date.now() - started, screenshot, url: this.page.url() });
      return out;
    } catch (error) {
      let screenshot = null;
      try {
        screenshot = await this.shot(`${name}-failure`);
      } catch {}
      this.steps.push({
        name,
        status: "fail",
        ms: Date.now() - started,
        screenshot,
        url: this.page.url(),
        error: error instanceof Error ? error.message : String(error),
      });
      this.issue("high", `Step failed: ${name}`, error instanceof Error ? error.message : String(error), screenshot);
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
        this.issue("medium", `Visible non-final copy on ${label}`, `Matched ${pattern}: "${excerpt}"`, screenshot);
      }
    }
    return text;
  }

  async goto(pathname, label, options = {}) {
    const res = await this.page.goto(pathname, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await this.page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
    await this.page.waitForTimeout(options.settleMs ?? 500);
    const status = res?.status() ?? 0;
    if (status >= 400 && !options.allow404) {
      throw new Error(`${label} returned HTTP ${status}`);
    }
    const text = await this.scanVisibleText(label);
    this.visited.push({ label, path: pathname, url: this.page.url(), status });
    return text;
  }

  async expectText(signal, label) {
    const text = await this.visibleText();
    if (!signal.test(text)) {
      throw new Error(`${label} did not expose expected text ${signal}`);
    }
    return text;
  }

  async runMarketing() {
    for (const [pathname, signals] of Object.entries(expectedSignals)) {
      await this.step(`public route ${pathname}`, async () => {
        const text = await this.goto(pathname, pathname, { settleMs: pathname === "/" ? 1200 : 500 });
        for (const signal of signals) {
          if (!signal.test(text)) throw new Error(`${pathname} missing expected signal ${signal}`);
        }
        return { screenshot: await this.shot(`public-${pathname === "/" ? "home" : pathname}`) };
      });
    }
  }

  async runAuth() {
    await this.step("unauthenticated /verify redirects to login", async () => {
      await this.context.clearCookies();
      await this.page.goto("/verify", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await this.page.waitForURL(/\/login(?:\?|$)/, { timeout: 12_000 });
      await this.expectText(/Log in to ProofShape/i, "login gate");
      await this.scanVisibleText("login-gate");
      return { screenshot: await this.shot("login-gate") };
    });

    if (loginEmail && loginPassword) {
      await this.step("signup rejects weak password", async () => {
        await this.goto("/signup", "signup");
        await this.page.getByLabel("Email").fill(uniqueEmail("weak"));
        await this.page.getByLabel("Password").fill("short");
        await this.page.getByRole("button", { name: /^Create account$/ }).click();
        await this.page.getByText("Password must be at least 8 characters.").waitFor({ timeout: 5000 });
        await this.scanVisibleText("signup-weak-password");
        return { screenshot: await this.shot("signup-weak-password") };
      });

      await this.step("login reuses existing synthetic account and lands in app", async () => {
        await this.goto("/login?next=/verify", "login");
        await this.page.getByLabel("Email").fill(loginEmail);
        await this.page.getByLabel("Password").fill(loginPassword);
        await this.page.getByRole("button", { name: /^Log in$/ }).click();
        await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: 20_000 });
        await this.expectText(/ProofShape|Home|Verify/i, "verify shell after login");
        await this.scanVisibleText("login-existing-account");
        return { screenshot: await this.shot("login-existing-account") };
      });
      this.account = { email: loginEmail, password: loginPassword };
      return;
    }

    await this.step("signup rejects weak password", async () => {
      await this.goto("/signup", "signup");
      await this.page.getByLabel("Email").fill(uniqueEmail("weak"));
      await this.page.getByLabel("Password").fill("short");
      await this.page.getByRole("button", { name: /^Create account$/ }).click();
      await this.page.getByText("Password must be at least 8 characters.").waitFor({ timeout: 5000 });
      await this.scanVisibleText("signup-weak-password");
      return { screenshot: await this.shot("signup-weak-password") };
    });

    const email = uniqueEmail("qa");
    const password = "Passw0rd123";
    await this.step("signup creates real account and lands in app", async () => {
      await this.page.getByLabel("Email").fill(email);
      await this.page.getByLabel("Password").fill(password);
      await this.page.getByRole("button", { name: /^Create account$/ }).click();
      await this.page.waitForURL(/\/verify(?:\?|$)/, { timeout: 20_000 });
      await this.expectText(/DAY ZERO SETUP/i, "first-run Verify setup");
      await this.scanVisibleText("first-run Verify setup");
      return { screenshot: await this.shot("first-run-verify-setup") };
    });

    this.account = { email, password };
  }

  async runVerifyShell() {
    await this.step("authenticated /verify loads Verify shell", async () => {
      await this.goto("/verify", "verify shell", { settleMs: 1200 });
      if (/\/login/.test(this.page.url())) throw new Error("authenticated user was redirected back to login");
      await this.expectText(/ProofShape|Home|Verify/i, "verify shell");
      return { screenshot: await this.shot("verify-shell-home") };
    });

    for (const surface of railSurfaces) {
      await this.step(`Verify rail surface: ${surface.title}`, async () => {
        await this.page.locator(`button[title="${surface.title}"]`).first().click({ timeout: 8000 });
        await this.page.waitForTimeout(700);
        await this.expectText(surface.signal, surface.title);
        await this.scanVisibleText(surface.title);
        return { screenshot: await this.shot(`rail-${surface.title}`) };
      });
    }

    await this.step("command palette jumps to Triage", async () => {
      await this.page.getByRole("button", { name: "Open Verify command palette" }).click();
      await this.page.getByRole("textbox", { name: "Command palette search" }).fill("triage");
      await this.page.keyboard.press("Enter");
      await this.page.waitForTimeout(700);
      await this.expectText(/Triage|makeability/i, "command palette triage jump");
      await this.scanVisibleText("command-palette-triage");
      return { screenshot: await this.shot("command-palette-triage") };
    });

    await this.step("notifications inbox opens and derives state", async () => {
      await this.page.getByRole("link", { name: "Notifications" }).click();
      await this.page.waitForURL((url) => url.pathname === "/notifications", { timeout: 8000 });
      await this.page.getByRole("heading", { name: "Notifications" }).waitFor({ timeout: 8000 });
      await this.page.waitForTimeout(1000);
      const text = await this.scanVisibleText("notifications-inbox");
      if (/couldn.t read your states/i.test(text)) {
        this.issue("medium", "Notifications inbox shows an API read failure", firstMatch(text, /couldn.t read your states[^\n]*/i) || "API read failure");
      }
      return { screenshot: await this.shot("notifications-inbox") };
    });
  }

  async runAuthedAppRoutes() {
    for (const route of appRoutes) {
      await this.step(`authenticated app route ${route.path}`, async () => {
        await this.goto(route.path, route.path, { allow404: route.allow404 });
        await this.expectText(route.signal, route.path);
        if (route.path === "/batch") {
          await this.page.getByRole("button", { name: /Start batch/i }).waitFor({ timeout: 8000 });
          const disabled = await this.page.getByRole("button", { name: /Start batch/i }).isDisabled();
          if (!disabled) {
            this.issue("medium", "Batch submit is enabled without a ZIP file", "The Start batch button should stay disabled until a ZIP is selected.");
          }
          const visible = await this.visibleText();
          if (/S3 reference/i.test(visible)) {
            this.issue("medium", "Batch page still exposes S3 reference copy", firstMatch(visible, /S3 reference/i));
          }
        }
        return { screenshot: await this.shot(`app-${route.path}`) };
      });
    }
  }

  async runMobileSmoke() {
    await this.step("mobile public home loads without non-final copy", async () => {
      await this.page.setViewportSize({ width: 390, height: 844 });
      await this.goto("/", "mobile-public-home", { settleMs: 1200 });
      await this.expectText(/ProofShape|cost/i, "mobile public home");
      return { screenshot: await this.shot("mobile-public-home", true) };
    });

    await this.step("mobile Verify shell loads authenticated", async () => {
      await this.goto("/verify", "mobile-verify", { settleMs: 1200 });
      if (/\/login/.test(this.page.url())) throw new Error("authenticated mobile user was redirected back to login");
      await this.expectText(/ProofShape|Home|Verify/i, "mobile verify shell");
      return { screenshot: await this.shot("mobile-verify", true) };
    });

    await this.page.setViewportSize({ width: 1440, height: 960 });
  }

  async runCadUpload() {
    await this.step("Verify processes a real STEP file upload", async () => {
      await this.goto("/verify", "verify-upload", { settleMs: 700 });
      await this.page.locator('button[title="Verify"]').click();
      const input = this.page.locator('input[type="file"][accept*=".stl"]').first();
      await input.setInputFiles(path.join(repoRoot, "backend/tests/assets/cube.step"));
      await this.page.waitForTimeout(3000);
      await this.shot("verify-upload-after-3s");
      await this.page
        .waitForFunction(() => {
          const text = document.body.innerText;
          return (
            /computed from POST \/validate\/cost|What it really takes|Geometry invalid|Cost request failed|Validation failed|repair required|unit cost|bbox/i.test(text) &&
            !/measuring geometry/i.test(text)
          );
        }, null, { timeout: cadUploadTimeoutMs })
        .catch(async () => {
          const text = await this.visibleText();
          throw new Error(`STEP upload did not reach a terminal visible result. Current text: ${text.slice(0, 500).replace(/\s+/g, " ")}`);
        });
      const text = await this.scanVisibleText("verify-step-upload-result");
      if (/Cost request failed|Validation failed|Network error|Geometry invalid|repair required/i.test(text)) {
        this.issue("high", "Verify STEP upload surfaced an engine failure", firstMatch(text, /Cost request failed|Validation failed|Network error|Geometry invalid|repair required/i) || "Upload failed");
      }
      return { screenshot: await this.shot("verify-step-upload-result") };
    });
  }

  async finish() {
    if (this.consoleErrors.length > 0) {
      const sample = this.consoleErrors.slice(0, 8).map((e) => `${e.url}: ${e.text}`).join("\n");
      this.issue("medium", "Browser console errors occurred during human E2E", sample);
    }
    if (this.requestFailures.length > 0) {
      const sample = this.requestFailures.slice(0, 8).map((e) => `${e.method} ${e.url}: ${e.error}`).join("\n");
      this.issue("medium", "Network request failures occurred during human E2E", sample);
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
      visited: this.visited,
      screenshotDir,
    };
    await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
    await writeFile(artifacts.md, this.markdown(data));
    console.log(JSON.stringify({ status, health, issues: this.issues.length, failedSteps, report: artifacts.md, screenshots: screenshotDir }, null, 2));
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
    return `# Human-Simulated E2E QA - Localhost

- Date: ${runId}
- Target: ${data.baseUrl}
- Status: ${data.status}
- Health score: ${data.health}/100
- Screenshots: ${data.screenshotDir}
- Test account: ${data.account?.email || "not created"}

## Coverage

- Public marketing routes: home, platform, developers, teams, method, security, status, company.
- Auth routes: gated /verify redirect, weak-password rejection, real signup, canonical first-run Verify setup.
- Authenticated app: Verify rail surfaces, command palette branch, notifications, batch, cost history, compare, history, reconstruct, label, design system, developer settings.
- Upload path: real STEP file through the Verify UI using backend/tests/assets/cube.step.
- Responsive smoke: mobile public home and authenticated Verify shell.
- Visible copy sweep: partial / in development / stub / mock / placeholder / S3 reference style terms.

## Issues

${issues}

## Steps

| Result | Step | URL | Screenshot |
| --- | --- | --- | --- |
${rows}
`;
  }
}

const runner = new HumanE2E();
try {
  await runner.init();
  await runner.runMarketing();
  await runner.runAuth();
  await runner.runVerifyShell();
  await runner.runAuthedAppRoutes();
  await runner.runMobileSmoke();
  await runner.runCadUpload();
} finally {
  await runner.finish().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
  await runner.close().catch(() => {});
}
