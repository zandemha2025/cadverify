import { randomBytes } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = cleanBaseUrl(process.env.APP_URL || "http://localhost:3000");
const cubePath = path.join(repoRoot, "backend/tests/assets/cube.step");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const screenshotDir = path.join(outputRoot, "screenshots", `p7-role-failure-${runId}`);
const artifacts = {
  json: path.join(outputRoot, `p7-role-failure-${runId}.json`),
  md: path.join(outputRoot, `qa-report-p7-role-failure-${runId}.md`),
};

const failOnUnavailable =
  process.argv.includes("--require-app") || process.env.E2E_FAIL_ON_UNAVAILABLE === "1";

const launchOptions = {
  channel: "chrome",
  headless: true,
  args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
};

const protectedRoutes = [
  { path: "/cost", expectedNext: true },
  { path: "/cost-decisions", expectedNext: true },
  { path: "/batch", expectedNext: true },
  { path: "/history", expectedNext: true },
  { path: "/integrations", expectedNext: true },
  { path: "/notifications", expectedNext: true },
  { path: "/rfq-packages", expectedNext: true },
  { path: "/settings/developer", expectedNext: true },
  { path: "/verify", expectedNext: false, allowFlagOff404: true },
];

const unauthApiChecks = [
  { method: "GET", path: "/api/proxy/admin/users" },
  { method: "GET", path: "/api/proxy/machine-inventory" },
  { method: "GET", path: "/api/proxy/cost-decisions?limit=1" },
];

const visibleCopyRoutes = [
  "/login",
  "/signup",
  "/cost",
  "/batch",
  "/cost-decisions",
  "/integrations",
  "/notifications",
  "/rfq-packages",
];
const governanceApprovalNote = `P7 governance approval ${runId}`;

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

class SkipStep extends Error {
  constructor(message) {
    super(message);
    this.name = "SkipStep";
  }
}

function usage() {
  return `P7 role/failure journey runner

Usage:
  APP_URL=http://localhost:3000 node scripts/e2e/p7-role-failure-journey-runner.mjs

Optional auth hooks:
  E2E_SESSION_COOKIE=<dash_session>                 Use an existing primary session.
  E2E_STORAGE_STATE=/path/to/state.json             Use Playwright storage state.
  E2E_LOGIN_EMAIL=<email> E2E_LOGIN_PASSWORD=<pw>   Log in as primary user.
  E2E_VIEWER_EMAIL=<email> E2E_VIEWER_PASSWORD=<pw> Run seeded low-role checks.
  E2E_VIEWER_SESSION_COOKIE=<dash_session>          Seeded low-role session cookie.
  E2E_VIEWER_STORAGE_STATE=/path/to/state.json      Seeded low-role storage state.

Behavior:
  If APP_URL is unavailable, writes an explicit SKIPPED_UNAVAILABLE report and exits 0.
  Pass --require-app or E2E_FAIL_ON_UNAVAILABLE=1 to make an unavailable app fail.`;
}

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(usage());
  process.exit(0);
}

function cleanBaseUrl(raw) {
  return raw.replace(/\/+$/, "");
}

function targetUrl(pathname = "/") {
  return new URL(pathname, `${baseUrl}/`).toString();
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
  const end = Math.min(text.length, match.index + match[0].length + 120);
  return text.slice(start, end).replace(/\s+/g, " ").trim();
}

function uniqueEmail(prefix = "p7") {
  return `${prefix}-${Date.now()}-${process.pid}-${randomBytes(4).toString("hex")}@example.com`;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function isLoginUrl(url) {
  try {
    const u = new URL(url);
    return u.pathname === "/login";
  } catch {
    return /\/login(?:\?|$)/.test(url);
  }
}

function searchParam(url, key) {
  try {
    return new URL(url).searchParams.get(key);
  } catch {
    return null;
  }
}

function responseDetail(body) {
  if (!body) return "";
  if (typeof body === "string") return body;
  const detail = body.detail ?? body.message ?? body.error;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string") return detail.message;
    if (typeof detail.code === "string") return detail.code;
  }
  try {
    return JSON.stringify(body);
  } catch {
    return String(body);
  }
}

function envKey(prefix, suffix) {
  return prefix ? `E2E_${prefix}_${suffix}` : `E2E_${suffix}`;
}

async function preflightApp() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3500);
  try {
    const res = await fetch(targetUrl("/"), {
      signal: controller.signal,
      redirect: "manual",
      cache: "no-store",
    });
    return { available: true, status: res.status };
  } catch (error) {
    return {
      available: false,
      reason: error instanceof Error ? error.message : String(error),
    };
  } finally {
    clearTimeout(timer);
  }
}

class P7RoleFailureQA {
  constructor() {
    this.steps = [];
    this.issues = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.visited = [];
    this.skips = [];
    this.evidence = {};
    this.contexts = [];
    this.expectedRequestFailure = [];
    this.expectedConsoleErrors = [];
    this.tempDirs = [];
  }

  async initBrowser() {
    await mkdir(screenshotDir, { recursive: true });
    try {
      this.browser = await pw.chromium.launch(launchOptions);
    } catch {
      this.browser = await pw.chromium.launch({
        headless: true,
        args: launchOptions.args,
      });
    }
    this.context = await this.newContext();
    this.page = await this.context.newPage();
    this.attachPage(this.page);
  }

  async newContext(options = {}) {
    const context = await this.browser.newContext({
      baseURL: baseUrl,
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
      ...options,
    });
    this.contexts.push(context);
    return context;
  }

  attachPage(page) {
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const text = msg.text();
      if (
        /favicon\.ico|ResizeObserver loop limit exceeded/i.test(text) ||
        /Failed to load resource: the server responded with a status of (401|403|404|422|503)/i.test(text) ||
        this.isExpectedConsoleError(text)
      ) {
        return;
      }
      this.consoleErrors.push({ url: page.url(), text });
    });
    page.on("pageerror", (err) => {
      this.consoleErrors.push({ url: page.url(), text: err.message });
    });
    page.on("requestfailed", (request) => {
      const url = request.url();
      const failure = request.failure()?.errorText || "request failed";
      if (
        /favicon\.ico|\/_next\/webpack-hmr|vercel\/speed-insights/i.test(url) ||
        (failure === "net::ERR_ABORTED" && /[?&]_rsc=/.test(url)) ||
        this.expectedRequestFailure.some((pattern) => pattern.test(url))
      ) {
        return;
      }
      this.requestFailures.push({ url, method: request.method(), error: failure });
    });
  }

  async close() {
    for (const context of this.contexts.splice(0)) {
      await context.close().catch(() => {});
    }
    await this.browser?.close().catch(() => {});
    for (const dir of this.tempDirs.splice(0)) {
      await rm(dir, { recursive: true, force: true }).catch(() => {});
    }
  }

  issue(severity, title, detail, screenshot = null, url = this.page?.url?.() || "") {
    this.issues.push({ severity, title, detail, screenshot, url });
  }

  expectConsoleError(pattern, ttlMs = 10_000) {
    this.expectedConsoleErrors.push({ pattern, expiresAt: Date.now() + ttlMs });
  }

  isExpectedConsoleError(text) {
    const now = Date.now();
    this.expectedConsoleErrors = this.expectedConsoleErrors.filter(
      (entry) => entry.expiresAt >= now
    );
    return this.expectedConsoleErrors.some((entry) => entry.pattern.test(text));
  }

  async shot(name, fullPage = false, page = this.page) {
    if (!page) return null;
    const file = path.join(
      screenshotDir,
      `${String(this.steps.length + 1).padStart(2, "0")}-${slug(name)}.png`
    );
    await page.screenshot({ path: file, fullPage, animations: "disabled" });
    return file;
  }

  recordSkip(name, reason, url = "") {
    this.skips.push({ name, reason, url });
    this.steps.push({ name, status: "skip", ms: 0, screenshot: null, url, reason });
  }

  async step(name, fn) {
    const started = Date.now();
    try {
      const out = (await fn()) || {};
      const hasScreenshot = Object.prototype.hasOwnProperty.call(out, "screenshot");
      const screenshot = hasScreenshot ? out.screenshot : await this.shot(name, false, out.page || this.page);
      this.steps.push({
        name,
        status: "pass",
        ms: Date.now() - started,
        screenshot,
        url: out.url || out.page?.url?.() || this.page?.url?.() || "",
      });
      return out;
    } catch (error) {
      if (error instanceof SkipStep) {
        this.recordSkip(name, error.message, this.page?.url?.() || "");
        return null;
      }
      let screenshot = null;
      try {
        screenshot = await this.shot(`${name}-failure`, true);
      } catch {}
      const detail = error instanceof Error ? error.message : String(error);
      const url = this.page?.url?.() || "";
      this.steps.push({
        name,
        status: "fail",
        ms: Date.now() - started,
        screenshot,
        url,
        error: detail,
      });
      this.issue("high", `Step failed: ${name}`, detail, screenshot, url);
      return null;
    }
  }

  async visibleText(page = this.page) {
    return page.locator("body").innerText({ timeout: 10_000 });
  }

  async scanVisibleText(label, page = this.page) {
    const text = await this.visibleText(page);
    for (const pattern of forbiddenPatterns) {
      const excerpt = firstMatch(text, pattern);
      if (excerpt) {
        const screenshot = await this.shot(`${label}-forbidden-copy`, true, page);
        this.issue(
          "medium",
          `Visible non-final copy on ${label}`,
          `Matched ${pattern}: "${excerpt}"`,
          screenshot,
          page.url()
        );
      }
    }
    return text;
  }

  async goto(pathname, label, options = {}) {
    const page = options.page || this.page;
    const res = await page.goto(pathname, {
      waitUntil: "domcontentloaded",
      timeout: options.timeout ?? 30_000,
    });
    await page.waitForLoadState("networkidle", { timeout: options.networkIdleMs ?? 5_000 }).catch(() => {});
    await page.waitForTimeout(options.settleMs ?? 500);
    const status = res?.status() ?? 0;
    if (status >= 500 && !options.allow5xx) {
      throw new Error(`${label} returned HTTP ${status}`);
    }
    if (status >= 400 && !options.allow4xx) {
      throw new Error(`${label} returned HTTP ${status}`);
    }
    const text = await this.scanVisibleText(label, page);
    this.visited.push({ label, path: pathname, url: page.url(), status });
    return { text, status, url: page.url(), page };
  }

  async readResponseJson(response) {
    const text = await response.text().catch(() => "");
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text.slice(0, 500);
    }
  }

  async proxyJson(context, pathname, options = {}) {
    const headers = { ...(options.headers || {}) };
    const requestOptions = {
      method: options.method || "GET",
      headers,
      timeout: options.timeout ?? 30_000,
    };

    if (Object.prototype.hasOwnProperty.call(options, "body")) {
      headers["content-type"] = headers["content-type"] || "application/json";
      requestOptions.data = JSON.stringify(options.body);
    }
    if (options.multipart) {
      requestOptions.multipart = options.multipart;
    }

    const response = await context.request.fetch(pathname, requestOptions);
    return {
      ok: response.ok(),
      status: response.status(),
      body: await this.readResponseJson(response),
    };
  }

  skipUnavailable(status, label, body) {
    if ([401, 403].includes(status)) {
      throw new SkipStep(`${label} rejected the primary session with ${status}: ${responseDetail(body)}`);
    }
    if (status === 404) {
      throw new SkipStep(`${label} is not mounted in this build`);
    }
    if ([502, 503, 504].includes(status)) {
      throw new SkipStep(`${label} is unavailable (${status}): ${responseDetail(body)}`);
    }
  }

  async addSessionCookie(context, value) {
    const u = new URL(baseUrl);
    await context.addCookies([
      {
        name: "dash_session",
        value,
        domain: u.hostname,
        path: "/",
        httpOnly: true,
        sameSite: "Lax",
        secure: u.protocol === "https:",
      },
    ]);
  }

  async loginWithCredentials(page, email, password, label = "login") {
    await this.goto("/login", `${label}-login`, { page });
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: /^Log in$/i }).click();
    await page.waitForLoadState("domcontentloaded", { timeout: 10_000 }).catch(() => {});
    await page.waitForURL((url) => !isLoginUrl(String(url)), { timeout: 20_000 }).catch(() => {});
    await page.waitForTimeout(800);
    if (isLoginUrl(page.url())) {
      const text = await this.visibleText(page).catch(() => "");
      throw new Error(`login stayed on /login: ${text.slice(0, 300).replace(/\s+/g, " ")}`);
    }
  }

  async assertAuthenticated(page, label = "authenticated context") {
    await page.goto("/cost", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
    await page.waitForTimeout(800);
    if (isLoginUrl(page.url())) {
      throw new Error(`${label} was redirected to login`);
    }
    await this.scanVisibleText(label, page);
  }

  async authContextFromHooks(prefix, label) {
    const storageState = process.env[envKey(prefix, "STORAGE_STATE")];
    const sessionCookie = process.env[envKey(prefix, "SESSION_COOKIE")];
    const email = process.env[envKey(prefix, "LOGIN_EMAIL")] || process.env[envKey(prefix, "EMAIL")];
    const password =
      process.env[envKey(prefix, "LOGIN_PASSWORD")] || process.env[envKey(prefix, "PASSWORD")];

    if (!storageState && !sessionCookie && !(email && password)) {
      return null;
    }

    const context = await this.newContext(storageState ? { storageState } : {});
    if (sessionCookie) await this.addSessionCookie(context, sessionCookie);
    const page = await context.newPage();
    this.attachPage(page);
    if (email && password) {
      await this.loginWithCredentials(page, email, password, label);
    }
    await this.assertAuthenticated(page, label);
    return { context, page, label, source: storageState ? "storage" : sessionCookie ? "cookie" : "credentials" };
  }

  async runUnauthenticatedRedirects() {
    await this.context.clearCookies();
    for (const route of protectedRoutes) {
      await this.step(`unauthenticated ${route.path} does not render protected UI`, async () => {
        const context = await this.newContext();
        const page = await context.newPage();
        this.attachPage(page);
        const res = await page.goto(route.path, { waitUntil: "domcontentloaded", timeout: 30_000 });
        await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
        await page.waitForTimeout(500);
        const status = res?.status() ?? 0;
        const text = await this.scanVisibleText(`unauth-${route.path}`, page);
        if (route.allowFlagOff404 && status === 404) {
          throw new SkipStep(`${route.path} returned 404; Verify UI flag appears off in this build`);
        }
        const redirected = isLoginUrl(page.url());
        const loginCopy = /Log in to CadVerify|Welcome back|Create an account/i.test(text);
        assert(
          redirected || loginCopy,
          `${route.path} did not redirect to or render login. URL: ${page.url()}`
        );
        if (route.expectedNext) {
          assert(
            searchParam(page.url(), "next") === route.path,
            `${route.path} login redirect did not preserve next=${route.path}`
          );
        }
        return {
          page,
          url: page.url(),
          screenshot: await this.shot(`unauth-${route.path}`, false, page),
        };
      });
    }
  }

  async runUnauthenticatedApiChecks() {
    for (const check of unauthApiChecks) {
      await this.step(`unauthenticated API ${check.method} ${check.path} rejects`, async () => {
        const context = await this.newContext();
        const response = await context.request.fetch(check.path, { method: check.method });
        const body = await this.readResponseJson(response);
        if (response.status() >= 500) {
          throw new SkipStep(
            `proxy/backend returned ${response.status()} before auth rejection could be verified: ${responseDetail(body)}`
          );
        }
        assert(
          [401, 403].includes(response.status()),
          `expected 401/403, got ${response.status()}: ${responseDetail(body)}`
        );
        this.evidence[`${check.method} ${check.path}`] = {
          status: response.status(),
          detail: responseDetail(body),
        };
        return { url: targetUrl(check.path), screenshot: null };
      });
    }
  }

  async runLoginFailures() {
    await this.step("invalid credentials show a bounded login error", async () => {
      await this.context.clearCookies();
      await this.goto("/login", "invalid-login");
      await this.page.getByLabel("Email").fill(uniqueEmail("bad-login"));
      await this.page.getByLabel("Password").fill("WrongPass123");
      await this.page.getByRole("button", { name: /^Log in$/i }).click();
      await this.page.waitForTimeout(1400);
      const text = await this.scanVisibleText("invalid-login-result");
      if (/Could not reach the server/i.test(text)) {
        throw new SkipStep("backend unavailable; credential rejection could not be distinguished");
      }
      assert(/Invalid email or password|invalid|incorrect|not found|credential/i.test(text), "no visible credential error appeared");
      return { screenshot: await this.shot("invalid-login-result") };
    });

    await this.step("network failure on login renders explicit recovery copy", async () => {
      await this.context.clearCookies();
      this.expectedRequestFailure.push(/\/api\/auth\/login(?:$|\?)/);
      this.expectConsoleError(/Failed to load resource: net::ERR_FAILED/i, 15_000);
      await this.page.route("**/api/auth/login", (route) => route.abort("failed"));
      try {
        await this.goto("/login", "login-network-failure");
        await this.page.getByLabel("Email").fill(uniqueEmail("network"));
        await this.page.getByLabel("Password").fill("Passw0rd123");
        await this.page.getByRole("button", { name: /^Log in$/i }).click();
        await this.page.getByText(/Could not reach the server/i).waitFor({ timeout: 8_000 });
        await this.scanVisibleText("login-network-failure-result");
        return { screenshot: await this.shot("login-network-failure-result") };
      } finally {
        this.expectConsoleError(/Failed to load resource: net::ERR_FAILED/i, 3_000);
        await this.page.unroute("**/api/auth/login").catch(() => {});
        this.expectedRequestFailure = this.expectedRequestFailure.filter(
          (pattern) => String(pattern) !== String(/\/api\/auth\/login(?:$|\?)/)
        );
      }
    });
  }

  async establishPrimaryAuth() {
    const fromGenericHooks = await this.step("primary authenticated session is available", async () => {
      const hookContext = await this.authContextFromHooks("", "primary");
      if (hookContext) {
        this.primary = hookContext;
        this.evidence.primaryAuth = { source: hookContext.source };
        return {
          page: hookContext.page,
          url: hookContext.page.url(),
          screenshot: await this.shot("primary-auth-from-hook", false, hookContext.page),
        };
      }

      const email = uniqueEmail("p7-primary");
      const password = "Passw0rd123";
      await this.context.clearCookies();
      await this.goto("/signup", "primary-signup");
      await this.page.getByLabel("Email").fill(email);
      await this.page.getByLabel("Password").fill(password);
      await this.page.getByRole("button", { name: /^Create account$/i }).click();
      await this.page.waitForURL((url) => !String(url).includes("/signup"), { timeout: 25_000 }).catch(() => {});
      await this.page.waitForTimeout(1000);
      const text = await this.visibleText(this.page).catch(() => "");
      if (/Could not reach the server/i.test(text)) {
        throw new SkipStep("backend unavailable; signup could not create an authenticated session");
      }
      if (/Could not create your account|already registered|error/i.test(text) && /\/signup/.test(this.page.url())) {
        throw new SkipStep(`signup did not complete: ${text.slice(0, 260).replace(/\s+/g, " ")}`);
      }
      await this.assertAuthenticated(this.page, "primary-signup");
      this.primary = { context: this.context, page: this.page, label: "primary-signup", source: "signup" };
      this.account = { email, password };
      this.evidence.primaryAuth = { source: "signup", email };
      return { screenshot: await this.shot("primary-signup-authed") };
    });
    return Boolean(fromGenericHooks && this.primary);
  }

  async runUnsupportedUpload() {
    if (!this.primary) {
      this.recordSkip("unsupported upload journey", "no authenticated primary session was available");
      return;
    }

    await this.step("unsupported batch upload renders a file-format failure", async () => {
      const page = this.primary.page;
      const tmpDir = await mkdtemp(path.join(os.tmpdir(), "cadverify-p7-upload-"));
      this.tempDirs.push(tmpDir);
      const badFile = path.join(tmpDir, "supplier-notes.txt");
      await writeFile(badFile, "not a zip or cad file\n");
      await this.goto("/batch", "unsupported-batch-upload", { page, settleMs: 1000 });
      const input = page.locator('input[type="file"]').first();
      await input.setInputFiles(badFile);
      await page.waitForTimeout(1200);
      const text = await this.scanVisibleText("unsupported-batch-upload-result", page);
      assert(
        /Only \.zip files are accepted|zip files are accepted|Please select a ZIP|unsupported|accepted/i.test(text),
        `unsupported upload did not surface a visible format error. Current text: ${text.slice(0, 400).replace(/\s+/g, " ")}`
      );
      return { page, url: page.url(), screenshot: await this.shot("unsupported-batch-upload-result", false, page) };
    });
  }

  async runAuthedApiFailureRendering() {
    if (!this.primary) {
      this.recordSkip("authenticated API failure rendering", "no authenticated primary session was available");
      return;
    }

    await this.step("cost history renders injected API failure", async () => {
      const page = this.primary.page;
      await page.route("**/api/proxy/cost-decisions**", (route) =>
        route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "P7 injected cost history outage" }),
        })
      );
      try {
        await this.goto("/cost-decisions", "cost-history-injected-api-failure", {
          page,
          settleMs: 1500,
        });
        await page.waitForTimeout(1200);
        const text = await this.scanVisibleText("cost-history-injected-api-failure-result", page);
        assert(
          /P7 injected cost history outage|Failed to load cost decisions|Server error|unavailable|error/i.test(text),
          `cost history did not render an API failure. Current text: ${text.slice(0, 500).replace(/\s+/g, " ")}`
        );
        return {
          page,
          url: page.url(),
          screenshot: await this.shot("cost-history-injected-api-failure-result", false, page),
        };
      } finally {
        await page.unroute("**/api/proxy/cost-decisions**").catch(() => {});
      }
    });
  }

  async createGovernanceDecisionFixture() {
    let fileBuffer;
    try {
      fileBuffer = await readFile(cubePath);
    } catch {
      throw new SkipStep(`local CAD fixture is unavailable at ${cubePath}`);
    }

    const q1 = 50 + (Number.parseInt(randomBytes(2).toString("hex"), 16) % 900);
    const q2 = q1 * 10;
    const filename = `p7-governance-${Date.now()}-${randomBytes(2).toString("hex")}.step`;
    const res = await this.proxyJson(this.primary.context, "/api/proxy/validate/cost", {
      method: "POST",
      timeout: 120_000,
      multipart: {
        file: {
          name: filename,
          mimeType: "application/step",
          buffer: fileBuffer,
        },
        qty: `${q1},${q2}`,
        region: "US",
        cavities: "1",
        complexity: "moderate",
        material_class: "aluminum",
      },
    });

    if (!res.ok) {
      this.skipUnavailable(res.status, "POST /validate/cost", res.body);
      if ([400, 413, 422].includes(res.status)) {
        throw new SkipStep(
          `cost-decision fixture could not be generated (${res.status}): ${responseDetail(res.body)}`
        );
      }
      if (res.status >= 500) {
        throw new SkipStep(`cost engine failed during fixture setup (${res.status}): ${responseDetail(res.body)}`);
      }
      throw new Error(`POST /validate/cost returned ${res.status}: ${responseDetail(res.body)}`);
    }

    const saved = res.body?.saved;
    if (!saved?.id) {
      throw new SkipStep(
        "POST /validate/cost completed without a saved decision id; COST_PERSIST_ENABLED may be off"
      );
    }

    this.evidence.governanceFixture = {
      id: saved.id,
      filename,
      quantities: [q1, q2],
      setup: "POST /api/proxy/validate/cost",
    };
    return saved.id;
  }

  async fetchGovernanceDecision(id) {
    const res = await this.proxyJson(this.primary.context, `/api/proxy/cost-decisions/${id}`);
    if (!res.ok) {
      this.skipUnavailable(res.status, `GET /cost-decisions/${id}`, res.body);
      throw new Error(`GET /cost-decisions/${id} returned ${res.status}: ${responseDetail(res.body)}`);
    }
    return res.body;
  }

  async runCostDecisionGovernance() {
    if (!this.primary) {
      this.recordSkip("cost-decision governance journey", "no authenticated primary session was available");
      return;
    }

    await this.step("cost-decision governance fixture is saved", async () => {
      const id = await this.createGovernanceDecisionFixture();
      const detail = await this.fetchGovernanceDecision(id);
      assert(detail.id === id, `saved decision detail id drifted: ${detail.id}`);
      assert(
        detail.approval_status === "unreviewed",
        `fresh decision should start unreviewed, got ${detail.approval_status}`
      );
      assert(detail.is_stale !== true, "fresh decision was already stale before a governed change");
      this.governanceDecisionId = id;
      this.evidence.governanceInitial = {
        id,
        approval_status: detail.approval_status,
        is_stale: detail.is_stale,
        stale_reason: detail.stale_reason,
      };
      return { url: targetUrl(`/cost-decisions/${id}`), screenshot: null };
    });

    if (!this.governanceDecisionId) return;

    await this.step("cost-decision detail approves and reopens from UI", async () => {
      const page = this.primary.page;
      const id = this.governanceDecisionId;
      await this.goto(`/cost-decisions/${id}`, "cost-decision-governance-detail", {
        page,
        settleMs: 1500,
      });
      await page.getByText("Decision governance").waitFor({ timeout: 10_000 });
      await page.getByPlaceholder("Optional approval note").fill(governanceApprovalNote);
      await page.getByRole("button", { name: /^Approve$/i }).click();
      await page
        .waitForFunction(
          (note) => {
            const text = document.body.innerText;
            return /Approved/i.test(text) && text.includes(note);
          },
          governanceApprovalNote,
          { timeout: 12_000 }
        )
        .catch(async () => {
          const text = await this.visibleText(page).catch(() => "");
          if (/Approval failed|forbidden|not authorized|permission/i.test(text)) {
            throw new SkipStep(`primary session cannot approve cost decisions: ${text.slice(0, 300).replace(/\s+/g, " ")}`);
          }
          throw new Error(`approval did not appear in the UI: ${text.slice(0, 500).replace(/\s+/g, " ")}`);
        });

      const approved = await this.fetchGovernanceDecision(id);
      assert(approved.approval_status === "approved", `API approval status stayed ${approved.approval_status}`);
      assert(approved.approved_at, "API approval timestamp missing");
      assert(approved.approval_note === governanceApprovalNote, "approval note did not round-trip");

      await page.getByRole("button", { name: /^Reopen$/i }).click();
      await page.waitForFunction(
        () => /Unreviewed|Awaiting analyst signoff/i.test(document.body.innerText),
        null,
        { timeout: 12_000 }
      );
      const reopened = await this.fetchGovernanceDecision(id);
      assert(
        reopened.approval_status === "unreviewed",
        `API reopen status stayed ${reopened.approval_status}`
      );
      assert(reopened.approved_at == null, "reopen left approved_at populated");
      assert(reopened.approval_note == null, "reopen left approval_note populated");

      this.evidence.governanceApproval = {
        id,
        approved_at: approved.approved_at,
        reopened_status: reopened.approval_status,
      };
      await this.scanVisibleText("cost-decision-governance-approve-reopen", page);
      return {
        page,
        url: page.url(),
        screenshot: await this.shot("cost-decision-governance-approve-reopen", true, page),
      };
    });

    await this.step("cost-decision detail shows stale warning after governed rate publish", async () => {
      const page = this.primary.page;
      const id = this.governanceDecisionId;
      const before = await this.fetchGovernanceDecision(id);
      assert(before.is_stale !== true, "decision was stale before the P7 governed-rate trigger");

      await page.waitForTimeout(1100);
      const draft = await this.proxyJson(this.primary.context, "/api/proxy/rate-library", {
        method: "POST",
        body: {
          name: `P7 stale trigger ${runId}`,
          change_note: "P7 QA: publish a governed card to stale existing cost decisions.",
        },
      });
      if (!draft.ok) {
        this.skipUnavailable(draft.status, "POST /rate-library", draft.body);
        if ([400, 422].includes(draft.status)) {
          throw new SkipStep(`rate-library draft could not be created: ${responseDetail(draft.body)}`);
        }
        throw new Error(`POST /rate-library returned ${draft.status}: ${responseDetail(draft.body)}`);
      }

      const published = await this.proxyJson(
        this.primary.context,
        `/api/proxy/rate-library/${draft.body.id}/publish`,
        { method: "POST", body: {} }
      );
      if (!published.ok) {
        this.skipUnavailable(published.status, `POST /rate-library/${draft.body.id}/publish`, published.body);
        if ([400, 409, 422].includes(published.status)) {
          throw new SkipStep(`rate-library publish could not run: ${responseDetail(published.body)}`);
        }
        throw new Error(
          `POST /rate-library/${draft.body.id}/publish returned ${published.status}: ${responseDetail(published.body)}`
        );
      }

      let stale = null;
      for (let i = 0; i < 8; i += 1) {
        stale = await this.fetchGovernanceDecision(id);
        if (stale.is_stale === true) break;
        await page.waitForTimeout(500);
      }
      assert(stale?.is_stale === true, `decision did not become stale after rate publish: ${JSON.stringify(stale)}`);
      assert(
        /rate_library_published/i.test(stale.stale_reason || ""),
        `unexpected stale reason: ${stale.stale_reason}`
      );

      await this.goto(`/cost-decisions/${id}`, "cost-decision-stale-detail", {
        page,
        settleMs: 1500,
      });
      const text = await this.scanVisibleText("cost-decision-stale-detail", page);
      assert(/Stale/i.test(text), "stale status badge was not visible");
      assert(/Re-cost before relying on this record/i.test(text), "stale re-cost warning copy was not visible");

      this.evidence.governanceStale = {
        id,
        stale_at: stale.stale_at,
        stale_reason: stale.stale_reason,
        rate_card_id: published.body.id,
        rate_card_version: published.body.version,
      };
      return {
        page,
        url: page.url(),
        screenshot: await this.shot("cost-decision-stale-warning", true, page),
      };
    });
  }

  async runSeededLowRoleChecks() {
    await this.step("seeded low-role credentials are available", async () => {
      const lowRole = await this.authContextFromHooks("VIEWER", "seeded-viewer");
      if (!lowRole) {
        throw new SkipStep(
          "no E2E_VIEWER_* auth hook supplied; low-role journey intentionally skipped"
        );
      }
      this.lowRole = lowRole;
      this.evidence.lowRoleAuth = { source: lowRole.source };
      return {
        page: lowRole.page,
        url: lowRole.page.url(),
        screenshot: await this.shot("seeded-viewer-authenticated", false, lowRole.page),
      };
    });

    if (!this.lowRole) return;

    await this.step("seeded low-role admin API is denied", async () => {
      const response = await this.lowRole.context.request.get("/api/proxy/admin/users");
      const body = await this.readResponseJson(response);
      assert(
        [401, 403].includes(response.status()),
        `expected low-role admin/users to be denied, got ${response.status()}: ${responseDetail(body)}`
      );
      this.evidence.lowRoleAdminUsers = {
        status: response.status(),
        detail: responseDetail(body),
      };
      return { url: targetUrl("/api/proxy/admin/users"), screenshot: null };
    });

    await this.step("seeded low-role Verify members panel shows gated copy when mounted", async () => {
      const page = this.lowRole.page;
      const res = await page.goto("/verify", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
      await page.waitForTimeout(1000);
      if ((res?.status() ?? 0) === 404) {
        throw new SkipStep("Verify UI route returned 404; role-limited panel is behind a disabled flag");
      }
      if (isLoginUrl(page.url())) {
        throw new Error("seeded low-role session was redirected to login on /verify");
      }
      const calibrationButton = page.locator('button[title="Calibration & truth"]').first();
      if (!(await calibrationButton.isVisible({ timeout: 5000 }).catch(() => false))) {
        throw new SkipStep("Verify rail did not expose Calibration & truth in this build");
      }
      await calibrationButton.click();
      await page.waitForTimeout(1500);
      const text = await this.scanVisibleText("seeded-low-role-calibration", page);
      assert(
        /Org-admin required|requires org-admin|couldn.t load members|roles gate actions/i.test(text),
        `low-role calibration did not show gated members copy. Current text: ${text.slice(0, 500).replace(/\s+/g, " ")}`
      );
      return {
        page,
        url: page.url(),
        screenshot: await this.shot("seeded-low-role-calibration-gate", true, page),
      };
    });
  }

  async runVisibleCopySweep() {
    for (const pathname of visibleCopyRoutes) {
      await this.step(`visible-copy sweep ${pathname}`, async () => {
        const authed = Boolean(this.primary) && !["/login", "/signup"].includes(pathname);
        const page = authed ? this.primary.page : this.page;
        if (!authed && !["/login", "/signup"].includes(pathname)) {
          throw new SkipStep("protected route copy sweep needs an authenticated primary session");
        }
        await this.goto(pathname, `copy-sweep-${pathname}`, {
          page,
          allow4xx: pathname === "/verify",
          settleMs: 900,
        });
        return { page, url: page.url(), screenshot: await this.shot(`copy-sweep-${pathname}`, false, page) };
      });
    }
  }

  async finish(statusOverride = null, unavailableReason = null) {
    if (!statusOverride) {
      if (this.consoleErrors.length > 0) {
        const sample = this.consoleErrors
          .slice(0, 8)
          .map((e) => `${e.url}: ${e.text}`)
          .join("\n");
        this.issue("medium", "Browser console errors occurred during P7 QA", sample);
      }
      if (this.requestFailures.length > 0) {
        const sample = this.requestFailures
          .slice(0, 8)
          .map((e) => `${e.method} ${e.url}: ${e.error}`)
          .join("\n");
        this.issue("medium", "Network request failures occurred during P7 QA", sample);
      }
    }

    const severityRank = { critical: 4, high: 3, medium: 2, low: 1 };
    const blocking = this.issues.filter((i) => severityRank[i.severity] >= severityRank.medium);
    const failedSteps = this.steps.filter((s) => s.status === "fail").length;
    const skippedSteps = this.steps.filter((s) => s.status === "skip").length;
    const passedSteps = this.steps.filter((s) => s.status === "pass").length;
    const status =
      statusOverride ||
      (blocking.length === 0 && failedSteps === 0
        ? skippedSteps > 0
          ? "PASS_WITH_SKIPS"
          : "PASS"
        : "NEEDS_FIXES");
    const health =
      status === "SKIPPED_UNAVAILABLE"
        ? null
        : Math.max(
            0,
            100 -
              this.issues.filter((i) => i.severity === "critical").length * 30 -
              this.issues.filter((i) => i.severity === "high").length * 18 -
              this.issues.filter((i) => i.severity === "medium").length * 8 -
              this.issues.filter((i) => i.severity === "low").length * 3
          );

    const data = {
      status,
      health,
      baseUrl,
      generatedAt: new Date().toISOString(),
      unavailableReason,
      account: this.account ? { email: this.account.email } : null,
      seededHooks: {
        primary:
          Boolean(process.env.E2E_STORAGE_STATE) ||
          Boolean(process.env.E2E_SESSION_COOKIE) ||
          Boolean(process.env.E2E_LOGIN_EMAIL),
        viewer:
          Boolean(process.env.E2E_VIEWER_STORAGE_STATE) ||
          Boolean(process.env.E2E_VIEWER_SESSION_COOKIE) ||
          Boolean(process.env.E2E_VIEWER_EMAIL),
      },
      steps: this.steps,
      issues: this.issues,
      skips: this.skips,
      consoleErrors: this.consoleErrors,
      requestFailures: this.requestFailures,
      visited: this.visited,
      evidence: this.evidence,
      screenshotDir,
    };

    await mkdir(outputRoot, { recursive: true });
    await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
    await writeFile(artifacts.md, this.markdown(data));
    console.log(
      JSON.stringify(
        {
          status,
          health,
          passedSteps,
          skippedSteps,
          failedSteps,
          issues: this.issues.length,
          report: artifacts.md,
          screenshots: screenshotDir,
        },
        null,
        2
      )
    );

    if (status === "NEEDS_FIXES" || (status === "SKIPPED_UNAVAILABLE" && failOnUnavailable)) {
      process.exitCode = 1;
    }
  }

  markdown(data) {
    const rows = data.steps.length
      ? data.steps
          .map((s) => {
            const result =
              s.status === "pass" ? "PASS" : s.status === "skip" ? "SKIP" : "FAIL";
            const note = s.error || s.reason || "";
            return `| ${result} | ${s.name} | ${s.url || ""} | ${note.replace(/\n/g, " ")} | ${s.screenshot || ""} |`;
          })
          .join("\n")
      : "| SKIP | App availability preflight |  | App was unavailable. |  |";
    const issues = data.issues.length
      ? data.issues
          .map((i, idx) => `${idx + 1}. **${i.severity.toUpperCase()}** ${i.title}\n   ${i.detail}\n   ${i.screenshot ? `Screenshot: ${i.screenshot}` : ""}`)
          .join("\n")
      : "No medium-or-higher issues found.";
    const skips = data.skips.length
      ? data.skips.map((s, idx) => `${idx + 1}. ${s.name}: ${s.reason}`).join("\n")
      : "No skipped checks.";
    const unavailable = data.unavailableReason
      ? `\n- Unavailable reason: ${data.unavailableReason}`
      : "";

    return `# P7 Role and Failure Journey QA

- Date: ${runId}
- Target: ${data.baseUrl}
- Status: ${data.status}
- Health score: ${data.health == null ? "n/a" : `${data.health}/100`}
- Screenshots: ${data.screenshotDir}
- Primary test account: ${data.account?.email || "hooked or not created"}${unavailable}

## Coverage

- Unauthenticated app-route redirects: cost, cost decisions, batch, history, integrations, notifications, RFQ packages, developer settings, and Verify when the feature flag is mounted.
- Unauthenticated API rejection through the same-origin proxy.
- Login failures: bad credentials plus injected network failure copy.
- Authenticated failure paths when a primary session is available: unsupported batch upload and injected cost-history API failure.
- Cost-decision governance when a saved decision can be created: browser-driven approve, reopen, and stale-warning display after a governed rate-card publish.
- Seeded low-role checks when E2E_VIEWER_* hooks are supplied.
- Visible-copy sweep for unfinished language: in development, under construction, coming soon, not implemented, TODO/TBD, stub, mock, placeholder, partial, S3 reference, ComingDoor, StubScreen.

## Optional Auth Hooks

- Primary hook supplied: ${data.seededHooks.primary ? "yes" : "no"}
- Viewer/low-role hook supplied: ${data.seededHooks.viewer ? "yes" : "no"}

## Issues

${issues}

## Skips

${skips}

## Steps

| Result | Step | URL | Note | Screenshot |
| --- | --- | --- | --- | --- |
${rows}
`;
  }
}

const runner = new P7RoleFailureQA();
const availability = await preflightApp();

try {
  if (!availability.available) {
    const reason = availability.reason || "APP_URL did not respond";
    runner.recordSkip("app availability preflight", reason, baseUrl);
    await runner.finish("SKIPPED_UNAVAILABLE", reason);
  } else {
    runner.evidence.preflight = availability;
    await runner.initBrowser();
    await runner.runUnauthenticatedRedirects();
    await runner.runUnauthenticatedApiChecks();
    await runner.runLoginFailures();
    await runner.establishPrimaryAuth();
    await runner.runUnsupportedUpload();
    await runner.runAuthedApiFailureRendering();
    await runner.runCostDecisionGovernance();
    await runner.runSeededLowRoleChecks();
    await runner.runVisibleCopySweep();
    await runner.finish();
  }
} finally {
  await runner.close();
}
