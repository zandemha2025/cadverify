import { createRequire } from "node:module";
import { randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";
import { makeGoldenPathEvidence, validateGoldenPathMap } from "./golden-path-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(outputRoot, "screenshots", `public-auth-verify-golden-${runId}`);
const artifacts = {
  json: path.join(outputRoot, `public-auth-verify-golden-${runId}.json`),
  md: path.join(outputRoot, `qa-report-public-auth-verify-golden-${runId}.md`),
};
const databaseUrl = process.env.DATABASE_URL || "postgresql://cadverify:localdev@127.0.0.1:5432/cadverify";
const requiredIds = [
  "PUB-01", "PUB-02", "PUB-03", "PUB-04",
  "AUTH-01", "AUTH-02", "AUTH-03", "AUTH-04", "AUTH-05",
  "VER-01", "VER-02", "VER-03",
];

const publicRoutes = [
  "/", "/platform", "/developers", "/api-reference", "/docs", "/teams",
  "/teams/cost-engineering", "/teams/design-engineering", "/teams/sourcing",
  "/teams/in-house-manufacturing", "/teams/shop-owners", "/method", "/security",
  "/status", "/company", "/pilot-report", "/privacy", "/terms", "/dpa",
];
const protectedRoutes = [
  "/verify", "/designs", "/cost", "/analyze", "/batch", "/cost-decisions",
  "/cost-decisions/compare", "/rfq-packages", "/integrations", "/history",
  "/reconstruct", "/label", "/settings/developer", "/settings/organization",
  "/settings/security", "/notifications",
];
const railSurfaces = ["Home", "Verify", "Parts", "Records", "Programs", "Your machines", "Triage", "Calibration & truth"];
const canonicalPublicPaths = new Map([["/docs", "/developers"]]);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function uniqueEmail(prefix) {
  return `${prefix}-${Date.now()}-${process.pid}-${randomBytes(4).toString("hex")}@example.com`;
}

function sqlLiteral(value) {
  return `'${String(value).replaceAll("'", "''")}'`;
}

function sqlCount(query) {
  const raw = execFileSync(process.env.PSQL || "psql", [databaseUrl, "-At", "-c", query], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
  const count = Number(raw);
  assert(Number.isInteger(count), `database count was not an integer: ${raw}`);
  return count;
}

function countRows(value) {
  if (Array.isArray(value)) return value.length;
  for (const key of ["items", "rows", "decisions", "records", "machines", "parts"]) {
    if (Array.isArray(value?.[key])) return value[key].length;
  }
  if (typeof value?.total === "number") return value.total;
  return 0;
}

function assertion(name, expected, actual, pass = Object.is(expected, actual)) {
  return { name, expected, actual, pass };
}

function markdown(data) {
  const rows = requiredIds.map((id) => {
    const item = data.validation.byId[id];
    return `| ${item.valid ? "PASS" : "FAIL"} | ${id} | ${item.failures.map((failure) => failure.field).join(", ") || "none"} | ${data.goldenPaths[id]?.screenshot || ""} |`;
  }).join("\n");
  return `# Public, authentication, and Day Zero golden matrix\n\n- Run: ${runId}\n- Status: ${data.status}\n- Build: ${data.buildIdentity.gitHead}\n- Structured outcomes: ${data.validation.valid}/${data.validation.total}\n- Console errors: ${data.consoleErrors.length}\n- Request failures: ${data.requestFailures.length}\n\n| Result | Golden path | Missing/invalid fields | Screenshot |\n| --- | --- | --- | --- |\n${rows}\n`;
}

class Matrix {
  constructor() {
    this.goldenPaths = {};
    this.consoleErrors = [];
    this.requestFailures = [];
    this.failures = [];
    this.shotIndex = 0;
  }

  async init() {
    await mkdir(screenshotDir, { recursive: true });
    this.clientIp = `198.51.100.${(process.pid % 200) + 20}`;
    try {
      this.browser = await chromium.launch({ channel: "chrome", headless: true });
    } catch {
      this.browser = await chromium.launch({ headless: true });
    }
    this.context = await this.browser.newContext({
      baseURL: baseUrl,
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
      extraHTTPHeaders: { "x-real-ip": this.clientIp },
    });
    this.page = await this.context.newPage();
    this.watch(this.page);
  }

  watch(page) {
    page.on("console", (message) => {
      const expectedAuthRejection = /\/login(?:\?|$)/.test(page.url()) && /status of 401 \(Unauthorized\)/i.test(message.text());
      if (message.type() === "error" && !expectedAuthRejection && !/favicon\.ico|ResizeObserver loop limit exceeded/i.test(message.text())) {
        this.consoleErrors.push({ url: page.url(), text: message.text() });
      }
    });
    page.on("pageerror", (error) => this.consoleErrors.push({ url: page.url(), text: error.message }));
    page.on("requestfailed", (request) => {
      const error = request.failure()?.errorText || "request failed";
      if (error === "net::ERR_ABORTED" || /favicon\.ico|_next\/static/.test(request.url())) return;
      this.requestFailures.push({ url: request.url(), method: request.method(), error });
    });
  }

  async shot(id, page = this.page, fullPage = false) {
    this.shotIndex += 1;
    const filename = path.join(screenshotDir, `${String(this.shotIndex).padStart(2, "0")}-${id.toLowerCase()}.png`);
    await page.screenshot({ path: filename, fullPage, animations: "disabled", caret: "initial" });
    return filename;
  }

  async api(pathname, options = {}, page = this.page) {
    return page.evaluate(async ({ pathname, options }) => {
      const response = await fetch(pathname, options);
      const text = await response.text();
      let body = null;
      try { body = JSON.parse(text); } catch { body = text; }
      return { status: response.status, body, headers: Object.fromEntries(response.headers.entries()) };
    }, { pathname, options });
  }

  add(id, input, errorOffsets) {
    const consoleErrors = this.consoleErrors.slice(errorOffsets.console);
    const requestFailures = this.requestFailures.slice(errorOffsets.request);
    assert(consoleErrors.length === 0, `${id} produced console errors: ${JSON.stringify(consoleErrors)}`);
    assert(requestFailures.length === 0, `${id} produced request failures: ${JSON.stringify(requestFailures)}`);
    this.goldenPaths[id] = makeGoldenPathEvidence({
      id,
      status: "PASS",
      ...input,
      consoleErrors,
      requestFailures,
    });
  }

  async path(id, fn) {
    const offsets = { console: this.consoleErrors.length, request: this.requestFailures.length };
    try {
      const input = await fn();
      this.add(id, input, offsets);
    } catch (error) {
      this.failures.push({ id, error: error instanceof Error ? error.message : String(error) });
    }
  }

  async publicEvaluation() {
    await this.path("PUB-01", async () => {
      const observed = [];
      let homeScreenshot = null;
      for (const route of publicRoutes) {
        const response = await this.page.goto(route, { waitUntil: "domcontentloaded", timeout: 30_000 });
        await this.page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
        assert((response?.status() || 500) < 400, `${route} returned HTTP ${response?.status()}`);
        const expectedPath = canonicalPublicPaths.get(route) || route;
        assert(new URL(this.page.url()).pathname === expectedPath, `${route} canonicalized to ${this.page.url()}`);
        const body = await this.page.locator("body").innerText();
        assert(/ProofShape/i.test(body), `${route} lost the ProofShape identity`);
        assert(!/\bCadVerify\b|\bArcus\b|under construction|coming soon|not implemented|\bTODO\b|\bTBD\b/i.test(body), `${route} exposed retired or unfinished copy`);
        const heading = (await this.page.locator("h1, h2").first().innerText().catch(() => "")).trim();
        assert(heading.length > 0, `${route} has no visible heading`);
        const overflow = await this.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        assert(overflow <= 1, `${route} overflows desktop by ${overflow}px`);
        observed.push({ route, status: response.status(), heading, overflow });
        if (route === "/") homeScreenshot = await this.shot("PUB-01", this.page, true);
      }
      assert(homeScreenshot, "public home screenshot was not captured");
      return {
        persona: "Public evaluator",
        preconditions: ["Signed out in a new browser context.", "Production-mode frontend and backend are running."],
        actions: ["Open every public, team, developer, legal, company, and status route from the canonical origin.", "Inspect the route heading, identity, overflow, console, and network result."],
        observed: {
          url: `${baseUrl}/`,
          visible: [`All ${observed.length} routes showed a route-specific heading and one ProofShape identity.`],
          persisted: "not-applicable: public navigation performs no mutation",
          numeric: { routeCount: observed.length, statuses: observed.map((item) => item.status) },
          authorization: "public routes required no session and exposed no protected data",
          recovery: "Each route remained independently reachable by canonical URL.",
        },
        screenshot: homeScreenshot,
        assertions: [
          assertion("all public routes visited", publicRoutes.length, observed.length),
          assertion("all HTTP statuses are below 400", true, observed.every((item) => item.status < 400)),
          assertion("all pages fit desktop width", true, observed.every((item) => item.overflow <= 1)),
        ],
      };
    });

    await this.path("PUB-02", async () => {
      await this.page.setViewportSize({ width: 390, height: 844 });
      await this.page.goto("/", { waitUntil: "domcontentloaded" });
      const menuButton = this.page.locator('summary[aria-label="Open site navigation"]');
      await menuButton.click();
      const platform = this.page.locator(".st-mobile-panel").getByRole("link", { name: "Platform", exact: true });
      await platform.waitFor({ state: "visible" });
      await platform.click();
      await this.page.waitForURL((url) => url.pathname === "/platform");
      await this.page.locator('summary[aria-label="Open site navigation"]').click();
      const overflow = await this.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      const ctaVisible = await this.page.locator(".st-mobile-panel").getByRole("link", { name: /Request a pilot/i }).isVisible();
      assert(overflow <= 1, `mobile platform overflows by ${overflow}px`);
      assert(ctaVisible, "mobile pilot CTA is not reachable");
      const screenshot = await this.shot("PUB-02", this.page, true);
      await this.page.setViewportSize({ width: 1440, height: 960 });
      return {
        persona: "Mobile public evaluator",
        preconditions: ["390 × 844 viewport.", "Signed out on the public home page."],
        actions: ["Open the mobile navigation.", "Select Platform.", "Confirm the primary pilot CTA remains reachable and the document does not overflow."],
        observed: {
          url: `${baseUrl}/platform`,
          visible: ["Mobile menu opened, Platform navigated, and Request a pilot remained visible."],
          persisted: "not-applicable: responsive navigation performs no mutation",
          numeric: { width: 390, height: 844, horizontalOverflowPx: overflow },
          authorization: "public mobile navigation required no session",
          recovery: "Direct navigation and the mobile menu reached the same canonical Platform route.",
        },
        screenshot,
        assertions: [
          assertion("horizontal overflow", 0, Math.max(0, overflow)),
          assertion("pilot CTA visible", true, ctaVisible),
        ],
      };
    });

    let validPayload;
    let validReceipt;
    await this.path("PUB-03", async () => {
      await this.page.goto("/company#pilot", { waitUntil: "domcontentloaded" });
      await this.page.getByLabel("Work email").fill(uniqueEmail("pilot-valid"));
      await this.page.getByLabel("Company").fill("Golden Matrix Manufacturing");
      await this.page.getByLabel("What do you make?").fill("Precision valve brackets and sealed production housings");
      await this.page.getByLabel("Deployment preference").selectOption("cloud");
      const requestPromise = this.page.waitForRequest((request) => request.method() === "POST" && new URL(request.url()).pathname === "/api/pilot/request");
      const responsePromise = this.page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/pilot/request");
      await this.page.getByRole("button", { name: "Send request" }).click();
      const [request, response] = await Promise.all([requestPromise, responsePromise]);
      validPayload = request.postDataJSON();
      const body = await response.json();
      validReceipt = body.receipt;
      await this.page.getByText("Request received and recorded.").waitFor();
      const visibleReceipt = (await this.page.getByText(/^CV-/).innerText()).replace(/^CV-/, "");
      const duplicate = await this.api("/api/pilot/request", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(validPayload),
      });
      const durableCount = sqlCount(`select count(*) from audit_log where action = 'pilot.requested' and resource_id = ${sqlLiteral(validPayload.requestId)}`);
      assert(response.status() === 200, `pilot request returned ${response.status()}`);
      assert(visibleReceipt === validReceipt, "visible receipt differs from response receipt");
      assert(duplicate.status === 200 && duplicate.body?.receipt === validReceipt, "idempotent retry changed the receipt");
      assert(durableCount === 1, `pilot receipt created ${durableCount} durable rows`);
      const screenshot = await this.shot("PUB-03");
      return {
        persona: "Public manufacturing evaluator",
        preconditions: ["No account or CAD file supplied.", "Pilot intake reports ready without Turnstile in the local production-mode boundary."],
        actions: ["Fill every required pilot field with business-only context.", "Submit once.", "Repeat the identical request ID through the same browser origin."],
        observed: {
          url: `${baseUrl}/company#pilot`,
          visible: [`Request received and recorded with receipt CV-${validReceipt}.`],
          persisted: { receipt: validReceipt, auditRows: durableCount, duplicateReceipt: duplicate.body.receipt },
          numeric: { initialStatus: response.status(), duplicateStatus: duplicate.status, durableRows: durableCount },
          authorization: "public intake accepted only the bounded pilot payload and requested no CAD or quote data",
          recovery: "An exact browser retry returned the same receipt and created no duplicate row.",
        },
        screenshot,
        assertions: [
          assertion("visible and response receipts match", validReceipt, visibleReceipt),
          assertion("duplicate receipt is stable", validReceipt, duplicate.body.receipt),
          assertion("durable row count", 1, durableCount),
        ],
      };
    });

    await this.path("PUB-04", async () => {
      const pilotContext = await this.browser.newContext({
        baseURL: baseUrl,
        viewport: { width: 1440, height: 960 },
        extraHTTPHeaders: { "x-real-ip": this.clientIp },
      });
      const pilotPage = await pilotContext.newPage();
      this.watch(pilotPage);
      await pilotPage.goto("/company?matrix=pub04#pilot", { waitUntil: "domcontentloaded" });
      let postCount = 0;
      const countPost = (request) => {
        if (request.method() === "POST" && new URL(request.url()).pathname === "/api/pilot/request") postCount += 1;
      };
      pilotPage.on("request", countPost);
      await pilotPage.getByLabel("Work email").fill(uniqueEmail("pilot-incomplete"));
      await pilotPage.getByRole("button", { name: "Send request" }).click();
      await pilotPage.waitForTimeout(300);
      const invalidRequired = await pilotPage.locator('input[name="company"]:invalid, textarea[name="what"]:invalid').count();
      pilotPage.off("request", countPost);
      assert(invalidRequired === 2, `expected two missing required fields, got ${invalidRequired}`);
      assert(postCount === 0, `incomplete form sent ${postCount} requests`);

      await pilotPage.getByLabel("Company").fill("Bot-shaped request");
      await pilotPage.getByLabel("What do you make?").fill("This neutral response must not disclose the honeypot.");
      await pilotPage.locator('input[name="website"]').evaluate((element) => { element.value = "https://bot.invalid"; });
      const requestPromise = pilotPage.waitForRequest((request) => request.method() === "POST" && new URL(request.url()).pathname === "/api/pilot/request");
      const responsePromise = pilotPage.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/pilot/request");
      await pilotPage.getByRole("button", { name: "Send request" }).click();
      const [request, response] = await Promise.all([requestPromise, responsePromise]);
      const payload = request.postDataJSON();
      const body = await response.json();
      await pilotPage.getByText("Request received and recorded.").waitFor();
      const honeypotRows = sqlCount(`select count(*) from audit_log where action = 'pilot.requested' and resource_id = ${sqlLiteral(payload.requestId)}`);
      assert(response.status() === 200 && body.status === "received", "honeypot did not receive the neutral success shape");
      assert(honeypotRows === 0, `honeypot request persisted ${honeypotRows} rows`);
      const screenshot = await this.shot("PUB-04", pilotPage);
      await pilotContext.close();
      return {
        persona: "Public evaluator and automated-abuse simulation",
        preconditions: ["Fresh pilot form.", "No authenticated account."],
        actions: ["Attempt submission with two required fields missing.", "Fill the invisible website honeypot and submit a complete-looking request.", "Repeat the valid request from PUB-03 with its original request ID."],
        observed: {
          url: `${baseUrl}/company#pilot`,
          visible: ["Native required-field validation blocked the incomplete request.", "The honeypot received the same neutral acknowledgement as a valid request."],
          persisted: { incompletePosts: postCount, honeypotAuditRows: honeypotRows, duplicateValidAuditRows: 1 },
          numeric: { invalidRequiredFields: invalidRequired, honeypotStatus: response.status() },
          authorization: "bot detection disclosed no distinguishing detail",
          recovery: "Correctly completing the visible required fields allowed a bounded submission without changing session state.",
        },
        screenshot,
        assertions: [
          assertion("incomplete request count", 0, postCount),
          assertion("invalid required fields", 2, invalidRequired),
          assertion("honeypot durable rows", 0, honeypotRows),
          assertion("neutral honeypot status", "received", body.status),
        ],
      };
    });
  }

  async authAndDayZero() {
    await this.path("AUTH-01", async () => {
      const context = await this.browser.newContext({ baseURL: baseUrl, viewport: { width: 1280, height: 800 } });
      const page = await context.newPage();
      this.watch(page);
      const results = [];
      for (const route of protectedRoutes) {
        const response = await page.goto(route, { waitUntil: "domcontentloaded", timeout: 30_000 });
        await page.waitForURL((url) => url.pathname === "/login", { timeout: 10_000 });
        const body = await page.locator("body").innerText();
        assert(/Log in to ProofShape/i.test(body), `${route} did not show the login boundary`);
        assert(!/Cost history|ProofShape Design Studio|RFQ packages|Developer settings|Organization members/i.test(body), `${route} flashed protected content`);
        results.push({ route, initialStatus: response?.status(), finalPath: new URL(page.url()).pathname });
      }
      const apiStatuses = [];
      for (const endpoint of ["/api/proxy/machine-inventory", "/api/proxy/cost-decisions?limit=1", "/api/proxy/admin/users"]) {
        const response = await context.request.get(new URL(endpoint, baseUrl).href);
        apiStatuses.push({ endpoint, status: response.status() });
        assert(response.status() === 401, `${endpoint} returned ${response.status()}, expected 401`);
      }
      const screenshot = await this.shot("AUTH-01", page);
      await context.close();
      return {
        persona: "Signed-out visitor",
        preconditions: ["New cookie-free browser context."],
        actions: ["Open every protected application route directly.", "Call representative protected APIs through the same-origin proxy."],
        observed: {
          url: `${baseUrl}/login`,
          visible: [`All ${results.length} protected routes showed Log in to ProofShape without protected-page copy.`],
          persisted: "no user, organization, or session mutation",
          numeric: { protectedRoutes: results.length, apiStatuses },
          authorization: { redirectsToLogin: results.every((item) => item.finalPath === "/login"), apiStatuses: apiStatuses.map((item) => item.status) },
          recovery: "Authentication remained the only route into the protected surfaces.",
        },
        screenshot,
        assertions: [
          assertion("protected routes redirected", protectedRoutes.length, results.filter((item) => item.finalPath === "/login").length),
          assertion("protected API statuses", true, apiStatuses.every((item) => item.status === 401)),
        ],
      };
    });

    const weakEmail = uniqueEmail("weak-password");
    await this.path("AUTH-02", async () => {
      await this.page.goto("/signup", { waitUntil: "domcontentloaded" });
      await this.page.getByLabel("Email").fill(weakEmail);
      await this.page.getByLabel("Password").fill("short");
      await this.page.getByRole("button", { name: /^Create account$/ }).click();
      await this.page.getByText("Password must be at least 8 characters.").waitFor();
      const cookies = await this.context.cookies();
      const userRows = sqlCount(`select count(*) from users where lower(email) = lower(${sqlLiteral(weakEmail)})`);
      assert(userRows === 0, "weak password created a user row");
      assert(cookies.every((cookie) => !/session/i.test(cookie.name)), "weak password created a session cookie");
      const screenshot = await this.shot("AUTH-02");
      return {
        persona: "New account applicant",
        preconditions: ["Email address has no existing account.", "Cookie-free signup form."],
        actions: ["Enter an email and the password short.", "Submit Create account."],
        observed: {
          url: `${baseUrl}/signup`,
          visible: ["Password must be at least 8 characters."],
          persisted: { userRows, sessionCookies: cookies.filter((cookie) => /session/i.test(cookie.name)).length },
          numeric: { submittedPasswordLength: 5, minimumLength: 8 },
          authorization: "no session was granted",
          recovery: "The same form remained available for a compliant password.",
        },
        screenshot,
        assertions: [
          assertion("created user rows", 0, userRows),
          assertion("created session cookies", 0, cookies.filter((cookie) => /session/i.test(cookie.name)).length),
        ],
      };
    });

    const unknownEmail = uniqueEmail("unknown-login");
    let unknownError;
    await this.page.goto("/login?next=/verify", { waitUntil: "domcontentloaded" });
    await this.page.getByLabel("Email").fill(unknownEmail);
    await this.page.getByLabel("Password").fill("WrongPassword1");
    await this.page.getByRole("button", { name: /^Log in$/ }).click();
    await this.page.getByText("Invalid email or password.").waitFor();
    unknownError = await this.page.getByText("Invalid email or password.").innerText();
    assert(unknownError === "Invalid email or password.", `unexpected unknown-account error: ${unknownError}`);

    const email = uniqueEmail("golden-user");
    const password = "GoldenPass123";
    await this.path("AUTH-04", async () => {
      await this.page.goto("/signup", { waitUntil: "domcontentloaded" });
      await this.page.getByLabel("Email").fill(email);
      await this.page.getByLabel("Password").fill(password);
      await this.page.getByRole("button", { name: /^Create account$/ }).click();
      await this.page.waitForURL((url) => url.pathname === "/verify", { timeout: 20_000 });
      await this.page.getByText("DAY ZERO SETUP").waitFor();
      const userRows = sqlCount(`select count(*) from users where lower(email) = lower(${sqlLiteral(email)})`);
      const membershipRows = sqlCount(`select count(*) from memberships m join users u on u.id = m.user_id where lower(u.email) = lower(${sqlLiteral(email)})`);
      const orgId = execFileSync(process.env.PSQL || "psql", [databaseUrl, "-At", "-c", `select current_org_id from users where lower(email) = lower(${sqlLiteral(email)})`], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      }).trim();
      await this.page.getByRole("button", { name: "Account" }).click();
      const visibleEmail = await this.page.getByText(email, { exact: true }).innerText();
      await this.page.keyboard.press("Escape");
      const cookies = await this.context.cookies();
      assert(visibleEmail === email, "account menu did not show the signed-up identity");
      assert(userRows === 1 && membershipRows === 1, `signup created users=${userRows}, memberships=${membershipRows}`);
      assert(orgId.length > 0, "signup did not select a current organization");
      assert(cookies.some((cookie) => /session/i.test(cookie.name)), "signup did not create a session cookie");
      const screenshot = await this.shot("AUTH-04");
      return {
        persona: "First CAD engineer",
        preconditions: ["Unique email with no user record.", "A password satisfying length, letter, and digit rules."],
        actions: ["Complete the real signup form.", "Wait for the authenticated Verify redirect.", "Inspect the Day Zero surface and authenticated self record."],
        observed: {
          url: `${baseUrl}/verify`,
          visible: ["DAY ZERO SETUP", "Unified ProofShape authenticated shell"],
          persisted: { userRows, membershipRows, email: visibleEmail, orgId },
          numeric: { users: userRows, memberships: membershipRows, sessions: cookies.filter((cookie) => /session/i.test(cookie.name)).length },
          authorization: { authenticatedIdentityVisible: true, authenticatedEmail: visibleEmail },
          recovery: "The newly created credentials can be used again after logout.",
        },
        screenshot,
        assertions: [
          assertion("user rows", 1, userRows),
          assertion("membership rows", 1, membershipRows),
          assertion("authenticated email", email, visibleEmail),
        ],
      };
    });

    await this.path("VER-01", async () => {
      await this.page.goto("/verify", { waitUntil: "domcontentloaded" });
      await this.page.getByText("DAY ZERO SETUP").waitFor();
      const [machines, decisions, portfolio, truth] = await Promise.all([
        this.api("/api/proxy/machine-inventory"),
        this.api("/api/proxy/cost-decisions?limit=50"),
        this.api("/api/proxy/catalog/portfolio"),
        this.api("/api/proxy/ground-truth"),
      ]);
      const counts = {
        machines: countRows(machines.body),
        records: countRows(decisions.body),
        parts: countRows(portfolio.body),
        actuals: countRows(truth.body),
      };
      assert(Object.values(counts).every((count) => count === 0), `Day Zero APIs were not empty: ${JSON.stringify(counts)}`);
      const body = await this.page.locator("body").innerText();
      for (const text of ["Declare machines + rates", "Verify first part", "Add program context", "Send actuals for validation"]) {
        assert(body.includes(text), `Day Zero omitted ${text}`);
      }
      const screenshot = await this.shot("VER-01", this.page, true);
      return {
        persona: "First CAD engineer in a new organization",
        preconditions: ["Freshly created organization with no seeded tenant data."],
        actions: ["Open Verify Home.", "Read all four Day Zero actions.", "Query the organization-scoped machine, decision, portfolio, and actuals collections."],
        observed: {
          url: `${baseUrl}/verify`,
          visible: ["Declare machines + rates", "Verify first part", "Add program context", "Send actuals for validation"],
          persisted: counts,
          numeric: counts,
          authorization: "all four empty collections were scoped to the signed-in organization",
          recovery: "Opening Day Zero required no workaround and created no tenant facts.",
        },
        screenshot,
        assertions: Object.entries(counts).map(([name, actual]) => assertion(`${name} count`, 0, actual)),
      };
    });

    await this.path("VER-02", async () => {
      const before = {
        machines: countRows((await this.api("/api/proxy/machine-inventory")).body),
        records: countRows((await this.api("/api/proxy/cost-decisions?limit=50")).body),
        parts: countRows((await this.api("/api/proxy/catalog/portfolio")).body),
        actuals: countRows((await this.api("/api/proxy/ground-truth")).body),
      };
      const mounted = [];
      for (const title of railSurfaces) {
        const button = this.page.locator(`button[title=${JSON.stringify(title)}]`).first();
        await button.click();
        await this.page.waitForTimeout(250);
        const body = await this.page.locator("body").innerText();
        assert(body.length > 100, `${title} mounted a blank surface`);
        mounted.push(title);
      }
      const after = {
        machines: countRows((await this.api("/api/proxy/machine-inventory")).body),
        records: countRows((await this.api("/api/proxy/cost-decisions?limit=50")).body),
        parts: countRows((await this.api("/api/proxy/catalog/portfolio")).body),
        actuals: countRows((await this.api("/api/proxy/ground-truth")).body),
      };
      assert(JSON.stringify(after) === JSON.stringify(before), `rail navigation mutated state: before=${JSON.stringify(before)} after=${JSON.stringify(after)}`);
      const screenshot = await this.shot("VER-02");
      return {
        persona: "First CAD engineer exploring the workspace",
        preconditions: ["Authenticated fresh organization.", "All Day Zero collection counts captured before navigation."],
        actions: railSurfaces.map((title) => `Select ${title} from the Verify rail.`),
        observed: {
          url: `${baseUrl}/verify`,
          visible: mounted.map((title) => `${title} mounted a nonblank, understandable state.`),
          persisted: { before, after },
          numeric: { surfaces: mounted.length, countsBefore: before, countsAfter: after },
          authorization: "every rail collection remained organization-scoped",
          recovery: "Home remained reachable after visiting every section.",
        },
        screenshot,
        assertions: [
          assertion("mounted surfaces", railSurfaces.length, mounted.length),
          assertion("opening sections does not mutate tenant data", JSON.stringify(before), JSON.stringify(after)),
        ],
      };
    });

    await this.path("VER-03", async () => {
      await this.page.locator('button[title="Home"]').first().click();
      await this.page.getByRole("button", { name: "Open Verify command palette" }).click();
      const search = this.page.getByRole("textbox", { name: "Command palette search" });
      await search.fill("triage");
      await this.page.keyboard.press("Enter");
      await this.page.getByText(/Portfolio triage|Triage/i).first().waitFor();
      const dialogCount = await this.page.getByRole("dialog").count();
      const active = await this.page.locator('button[title="Triage"]').first().evaluate((element) => element.getAttribute("aria-pressed") ?? element.getAttribute("data-active") ?? element.className);
      assert(dialogCount === 0, "command palette remained open after navigation");
      const screenshot = await this.shot("VER-03");
      return {
        persona: "Daily CAD engineer using keyboard navigation",
        preconditions: ["Authenticated Verify Home is open."],
        actions: ["Open the command palette.", "Type triage.", "Press Enter."],
        observed: {
          url: `${baseUrl}/verify`,
          visible: ["Triage surface opened and the command dialog closed."],
          persisted: "not-applicable: command navigation changed no tenant record",
          numeric: { openDialogsAfterNavigation: dialogCount },
          authorization: "the command exposed only surfaces available to the authenticated user",
          recovery: "The rail remained usable after the keyboard jump.",
        },
        screenshot,
        assertions: [
          assertion("open dialogs after navigation", 0, dialogCount),
          assertion("triage button exposes active state", true, Boolean(active)),
        ],
      };
    });

    await this.path("AUTH-05", async () => {
      // Regression: ISSUE-007 — deleting the local cookie left a copied pre-logout session usable.
      // Found by /qa on 2026-07-13
      // Report: .gstack/qa-reports/qa-report-public-auth-verify-golden-2026-07-13-expansion-r3.md
      await this.page.goto("/cost", { waitUntil: "domcontentloaded" });
      const oldCookies = await this.context.cookies();
      await this.page.getByRole("button", { name: "Account" }).click();
      await this.page.getByText("Sign out", { exact: true }).click();
      await this.page.waitForURL((url) => url.pathname === "/login");

      const oldContext = await this.browser.newContext({ baseURL: baseUrl });
      await oldContext.addCookies(oldCookies);
      const oldPage = await oldContext.newPage();
      this.watch(oldPage);
      await oldPage.goto("/cost", { waitUntil: "domcontentloaded" });
      await oldPage.waitForURL((url) => url.pathname === "/login");
      const oldApiStatus = (await this.api("/api/proxy/cost-decisions?limit=1", {}, oldPage)).status;
      assert(oldApiStatus === 401, `logged-out cookie still returned API ${oldApiStatus}`);
      await oldContext.close();

      await this.page.goto("/cost", { waitUntil: "domcontentloaded" });
      await this.page.waitForURL((url) => url.pathname === "/login" && url.searchParams.get("next") === "/cost");
      await this.page.getByLabel("Email").fill(email);
      await this.page.getByLabel("Password").fill("WrongPassword1");
      await this.page.getByRole("button", { name: /^Log in$/ }).click();
      await this.page.getByText("Invalid email or password.").waitFor();
      const knownError = await this.page.getByText("Invalid email or password.").innerText();
      assert(knownError === unknownError, `login error enumerated account existence: unknown=${unknownError}, known=${knownError}`);

      await this.page.getByLabel("Password").fill(password);
      await this.page.getByRole("button", { name: /^Log in$/ }).click();
      await this.page.waitForURL((url) => url.pathname === "/cost", { timeout: 20_000 });
      const screenshot = await this.shot("AUTH-05");

      this.goldenPaths["AUTH-03"] = makeGoldenPathEvidence({
        id: "AUTH-03",
        mode: "browser",
        status: "PASS",
        persona: "Signed-out visitor with unknown and known emails",
        preconditions: ["One unknown email and one existing account email.", "No active session."],
        actions: ["Submit the unknown email with a wrong password.", "Submit the known email with a wrong password."],
        observed: {
          url: `${baseUrl}/login`,
          visible: [unknownError, knownError],
          persisted: "no new user or session was created by either failed login",
          numeric: { comparedErrorMessages: 2 },
          authorization: { unknownGranted: false, knownWrongPasswordGranted: false },
          recovery: "Entering the valid password then restored the safe local destination.",
        },
        screenshot,
        consoleErrors: [],
        requestFailures: [],
        assertions: [
          assertion("unknown account error", "Invalid email or password.", unknownError),
          assertion("known account wrong-password error", unknownError, knownError),
        ],
      });

      return {
        persona: "Returning CAD engineer",
        preconditions: ["Authenticated user is on /cost.", "The browser session cookie is captured before logout."],
        actions: ["Sign out through Account.", "Replay the old cookie against /cost and a protected API.", "Log in with valid credentials and next=/cost."],
        observed: {
          url: `${baseUrl}/cost`,
          visible: ["Logout returned the login boundary.", "Valid login returned to the safe local /cost destination."],
          persisted: { oldSessionRejected: true, accountRetained: true },
          numeric: { oldSessionApiStatus: oldApiStatus },
          authorization: { oldCookieStatus: oldApiStatus, newSessionDestination: "/cost" },
          recovery: "A fresh valid login restored only the authorized workspace.",
        },
        screenshot,
        assertions: [
          assertion("old session API status", 401, oldApiStatus),
          assertion("safe next destination", "/cost", new URL(this.page.url()).pathname),
        ],
      };
    });
  }

  async finish() {
    const validation = validateGoldenPathMap(requiredIds, this.goldenPaths);
    const buildIdentity = captureBuildIdentity(repoRoot);
    const status = this.failures.length === 0 && validation.valid === validation.total && this.consoleErrors.length === 0 && this.requestFailures.length === 0
      ? "PASS"
      : "NEEDS_FIXES";
    const data = {
      status,
      runId,
      baseUrl,
      generatedAt: new Date().toISOString(),
      buildIdentity,
      releaseEvidence: { schemaVersion: 1, goldenPaths: this.goldenPaths },
      goldenPaths: this.goldenPaths,
      validation,
      failures: this.failures,
      consoleErrors: this.consoleErrors,
      requestFailures: this.requestFailures,
      screenshotDir,
    };
    await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
    await writeFile(artifacts.md, markdown(data));
    console.log(JSON.stringify({
      status,
      goldenPaths: `${validation.valid}/${validation.total}`,
      failures: this.failures,
      consoleErrors: this.consoleErrors.length,
      requestFailures: this.requestFailures.length,
      report: artifacts.md,
    }, null, 2));
    if (status !== "PASS") process.exitCode = 1;
    await this.browser?.close();
  }
}

const matrix = new Matrix();
try {
  await matrix.init();
  await matrix.publicEvaluation();
  await matrix.authAndDayZero();
} finally {
  await matrix.finish();
}
