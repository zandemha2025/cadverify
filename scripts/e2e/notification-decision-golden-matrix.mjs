import { execFileSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

import { makeGoldenPathEvidence, validateGoldenPathMap } from "./golden-path-evidence.mjs";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const appUrl = (process.env.APP_URL || "http://localhost:3000").replace(/\/$/, "");
const apiUrl = (process.env.API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const runId = process.env.E2E_RUN_ID || `${new Date().toISOString().replace(/[:.]/g, "-")}-${process.pid}`;
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const artifactDir = path.join(outputRoot, `notification-decision-${runId}`);
const screenshotDir = path.join(artifactDir, "screenshots");
const reportPath = path.join(outputRoot, `notification-decision-golden-${runId}.json`);
const markdownPath = path.join(outputRoot, `notification-decision-golden-${runId}.md`);
const fixturePath = path.join(repoRoot, "backend", "tests", "assets", "cube.step");
const secondFixturePath = path.join(repoRoot, "outputs", "human-sim", "framework", "demo-assets", "bracket_A.stl");
const requiredIds = ["VER-04", "VER-07", "WORK-05", "WORK-07", "ROLE-04", "FAIL-09"];
const password = "QaNotificationMatrix2026";
const normalNote = "QA approval note v1: approve make-vs-buy at qty 50.";
const dispositionCreateNote = "Initial disposition rationale: owned MJF capacity is available.";
const specialNote = "QA edit α/β — “quoted” <tag> & gears ⚙️\nLine 2: $3.80/unit; path C:\\fixtures\\cube.step";
const longPrefix = "LONG-NOTE-BEGIN|";
const longSuffix = "|LONG-NOTE-END";
const longNote = `${longPrefix}${"0123456789abcdef".repeat(64)}`.slice(
  0,
  1000 - longSuffix.length,
) + longSuffix;

function fail(message) {
  throw new Error(message);
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function runScopedClientIp(identityIndex) {
  const digest = createHash("sha256")
    .update(`${runId}:${identityIndex}`)
    .digest("hex");
  return `2001:db8:${digest.slice(0, 4)}:${digest.slice(4, 8)}:${digest.slice(8, 12)}::${identityIndex.toString(16)}`;
}

function forbiddenKeyPaths(value, forbidden, prefix = "") {
  if (!value || typeof value !== "object") return [];
  const paths = [];
  for (const [key, child] of Object.entries(value)) {
    const current = prefix ? `${prefix}.${key}` : key;
    if (forbidden.has(key)) paths.push(current);
    paths.push(...forbiddenKeyPaths(child, forbidden, current));
  }
  return paths;
}

function same(expected, actual) {
  return stableJson(expected) === stableJson(actual);
}

function sha256(value) {
  return createHash("sha256").update(typeof value === "string" ? value : stableJson(value)).digest("hex");
}

function uniqueEmail(prefix) {
  return `${prefix}-${Date.now()}-${process.pid}-${randomBytes(4).toString("hex")}@example.com`;
}

function isoMs(value) {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) fail(`invalid ISO timestamp: ${value}`);
  return parsed;
}

function csvRows(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (quoted) fail("CSV export ended inside a quoted field");
  if (field.length > 0 || row.length > 0) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  const [headers = [], ...data] = rows;
  return data.filter((values) => values.some((value) => value !== "")).map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])),
  );
}

function markdown(report) {
  const rows = requiredIds.map((id) => {
    const validation = report.releaseEvidence.validation.byId[id];
    return `| ${validation.valid ? "PASS" : "FAIL"} | ${id} | ${report.releaseEvidence.goldenPaths[id].assertions.length} | ${report.releaseEvidence.goldenPaths[id].screenshot} |`;
  }).join("\n");
  return `# Notification and decision-record golden matrix\n\n- Status: ${report.status}\n- Build: ${report.buildIdentity.gitHead}\n- App: ${appUrl}\n- Structured evidence: ${report.releaseEvidence.validation.valid}/${report.releaseEvidence.validation.total}\n- Unexpected console errors: ${report.diagnostics.consoleErrors.length}\n- Unexpected request failures: ${report.diagnostics.requestFailures.length}\n\n| Result | Golden path | Exact assertions | Screenshot |\n| --- | --- | ---: | --- |\n${rows}\n\n## Explicit limitations\n\n${report.coverageGaps.map((gap) => `- ${gap}`).join("\n")}\n`;
}

class Matrix {
  constructor() {
    this.assertions = Object.fromEntries(requiredIds.map((id) => [id, []]));
    this.consoleErrors = [];
    this.requestFailures = [];
    this.expected401Pages = new Set();
    this.expected404Pages = new Set();
    this.expected422Pages = new Set();
    this.expectedFailurePages = new Set();
    this.shotIndex = 0;
    this.observations = {};
  }

  check(id, name, expected, actual, pass = same(expected, actual)) {
    const evidenceValue = (value) => {
      if (value === null) return "<null>";
      if (value === "") return "<empty-string>";
      return value;
    };
    const assertion = {
      name,
      expected: evidenceValue(expected),
      actual: evidenceValue(actual),
      pass,
    };
    this.assertions[id].push(assertion);
    if (!pass) fail(`[${id}] ${name}: expected ${stableJson(expected)}, got ${stableJson(actual)}`);
    return actual;
  }

  truth(id, name, actual, expected = true) {
    return this.check(id, name, expected, actual, actual === expected);
  }

  watch(page) {
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const text = message.text();
      const expected401 = this.expected401Pages.has(page) && /status of 401\b/i.test(text);
      const expected404 = this.expected404Pages.has(page) && /status of 404 \(Not Found\)/i.test(text);
      const expected422 = this.expected422Pages.has(page) && /status of 422\b/i.test(text);
      const expectedFailure = this.expectedFailurePages.has(page) && /status of 503 \(Service Unavailable\)/i.test(text);
      if (expected401 || expected404 || expected422 || expectedFailure || /favicon\.ico|ResizeObserver loop limit exceeded/i.test(text)) return;
      this.consoleErrors.push({ url: page.url(), text });
    });
    page.on("pageerror", (error) => this.consoleErrors.push({ url: page.url(), text: error.message }));
    page.on("requestfailed", (request) => {
      const error = request.failure()?.errorText || "request failed";
      if (error === "net::ERR_ABORTED" || /favicon\.ico/.test(request.url())) return;
      this.requestFailures.push({ url: request.url(), method: request.method(), error });
    });
  }

  async init() {
    await mkdir(screenshotDir, { recursive: true });
    try {
      this.browser = await chromium.launch({ channel: "chrome", headless: true });
    } catch {
      this.browser = await chromium.launch({ headless: true });
    }
  }

  async newIdentity(prefix, ipSuffix) {
    const clientIp = runScopedClientIp(ipSuffix);
    const context = await this.browser.newContext({
      baseURL: appUrl,
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
      acceptDownloads: true,
      extraHTTPHeaders: { "x-real-ip": clientIp },
    });
    const page = await context.newPage();
    this.watch(page);
    const email = uniqueEmail(prefix);
    await page.goto("/signup", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: /^Create account$/ }).click();
    await page.waitForURL((url) => url.pathname === "/verify", { timeout: 30_000 });
    await page.getByRole("button", { name: "Account" }).waitFor({ timeout: 20_000 });
    const sessionCookie = (await context.cookies()).find((cookie) => cookie.name === "dash_session");
    if (!sessionCookie?.value) fail(`${prefix} signup did not set the real dash_session browser cookie`);
    return { context, page, email, clientIp };
  }

  async shot(id, page, label) {
    this.shotIndex += 1;
    const filename = `${String(this.shotIndex).padStart(2, "0")}-${id}-${label}.png`;
    const destination = path.join(screenshotDir, filename);
    await page.screenshot({ path: destination, fullPage: true });
    return destination;
  }

  async request(page, endpoint, options = {}) {
    // Playwright's out-of-page HTTP client does not reproduce Chromium's local
    // Secure-cookie behavior. Fetch inside the signed-in page so the real
    // first-party session cookie reaches the same-origin proxy.
    if (!endpoint.startsWith("/api/proxy/")) {
      fail(`authenticated browser request must use /api/proxy: ${endpoint}`);
    }
    if (options.headers) {
      fail("authenticated browser requests use only the real session cookie; custom proxy headers are forbidden");
    }
    const result = await page.evaluate(async ({ target, method, data, timeout }) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      try {
        const response = await fetch(target, {
          method,
          headers: data === undefined ? undefined : { "content-type": "application/json" },
          body: data === undefined ? undefined : JSON.stringify(data),
          cache: "no-store",
          credentials: "same-origin",
          signal: controller.signal,
        });
        const bytes = new Uint8Array(await response.arrayBuffer());
        let binary = "";
        for (let offset = 0; offset < bytes.length; offset += 0x8000) {
          binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
        }
        return {
          status: response.status,
          headers: Object.fromEntries(response.headers.entries()),
          base64: btoa(binary),
        };
      } finally {
        clearTimeout(timer);
      }
    }, {
      target: endpoint,
      method: String(options.method || "GET").toUpperCase(),
      data: options.data,
      timeout: options.timeout || 60_000,
    });
    const bytes = Buffer.from(result.base64, "base64");
    const contentType = result.headers["content-type"] || "";
    let body = bytes;
    if (/json/i.test(contentType)) {
      try {
        body = JSON.parse(bytes.toString("utf8"));
      } catch {
        body = bytes.toString("utf8");
      }
    } else if (/text|csv|html/i.test(contentType)) {
      body = bytes.toString("utf8");
    }
    return { status: result.status, headers: result.headers, body, bytes };
  }

  async publicRequest(endpoint) {
    const response = await fetch(endpoint, { cache: "no-store" });
    const bytes = Buffer.from(await response.arrayBuffer());
    const headers = Object.fromEntries(response.headers.entries());
    const contentType = headers["content-type"] || "";
    let body = bytes;
    if (/json/i.test(contentType)) {
      try {
        body = JSON.parse(bytes.toString("utf8"));
      } catch {
        body = bytes.toString("utf8");
      }
    } else if (/text|csv|html/i.test(contentType)) {
      body = bytes.toString("utf8");
    }
    return { status: response.status, headers, body, bytes };
  }

  async decision(page, id) {
    const response = await this.request(page, `/api/proxy/cost-decisions/${id}`);
    if (response.status !== 200) fail(`GET decision ${id} returned ${response.status}`);
    return response.body;
  }

  async notifications(page, { unread = false, dismissed = false } = {}) {
    const response = await this.request(
      page,
      `/api/proxy/notifications?status=all&unread=${unread ? "true" : "false"}&dismissed=${dismissed ? "true" : "false"}&limit=100`,
    );
    if (response.status !== 200) fail(`GET notifications returned ${response.status}`);
    return response.body.notifications || [];
  }

  async uploadDecision(identity, filename, sourcePath = fixturePath) {
    const { page } = identity;
    await page.goto("/verify", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.locator('button[title="Verify"]').first().click();
    const input = page.locator('input[type="file"][accept*=".stl"]').first();
    await input.waitFor({ state: "attached", timeout: 15_000 });
    const validationPromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && /\/api\/proxy\/validate$/.test(new URL(response.url()).pathname),
      { timeout: 120_000 },
    );
    const costPromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && /\/api\/proxy\/validate\/cost$/.test(new URL(response.url()).pathname),
      { timeout: 120_000 },
    );
    await input.setInputFiles({
      name: filename,
      mimeType: filename.toLowerCase().endsWith(".stl") ? "model/stl" : "application/step",
      buffer: await readFile(sourcePath),
    });
    const [validationResponse, costResponse] = await Promise.all([validationPromise, costPromise]);
    if (!validationResponse.ok()) fail(`POST /validate returned ${validationResponse.status()}`);
    if (!costResponse.ok()) fail(`POST /validate/cost returned ${costResponse.status()}`);
    const validation = await validationResponse.json();
    const cost = await costResponse.json();
    if (!cost?.saved?.id) fail("cost response omitted saved decision id");
    const detail = await this.decision(identity.page, cost.saved.id);
    let notification = null;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      notification = (await this.notifications(identity.page)).find(
        (item) => item.source_id === cost.saved.id,
      );
      if (notification) break;
      await page.waitForTimeout(250);
    }
    if (!notification) fail(`decision ${cost.saved.id} emitted no durable notification`);
    return {
      validationStatus: validationResponse.status(),
      costStatus: costResponse.status(),
      validation,
      cost,
      detail,
      notification,
    };
  }

  async notificationLifecycle(identity) {
    const first = await this.uploadDecision(identity, `notification-primary-${runId}.step`);
    const firstRow = first.notification;
    this.check("VER-04", "notification source id", first.detail.id, firstRow.source_id);
    this.check("VER-04", "notification source type", "cost_decision", firstRow.source_type);
    this.check("VER-04", "notification title", `Verification recorded - ${first.detail.filename}`, firstRow.title);
    this.check("VER-04", "notification destination", "records", firstRow.dest);
    this.check("VER-04", "notification initial status", "open", firstRow.status);
    this.check("VER-04", "notification initial read_at", null, firstRow.read_at);
    this.check("VER-04", "notification initial is_read", false, firstRow.is_read);
    this.check("VER-04", "notification initial dismissed_at", null, firstRow.dismissed_at);
    this.check("VER-04", "notification initial is_dismissed", false, firstRow.is_dismissed);
    this.check("VER-04", "notification and decision creation timestamp", first.detail.created_at, firstRow.created_at);

    const { page } = identity;
    await page.goto("/notifications", { waitUntil: "domcontentloaded" });
    await page.getByText(firstRow.title, { exact: true }).waitFor({ timeout: 15_000 });
    this.check("VER-04", "visible notification body", firstRow.body, await page.getByText(firstRow.body, { exact: true }).innerText());
    await page.reload({ waitUntil: "domcontentloaded" });
    this.check("VER-04", "unread survives browser reload", firstRow.title, await page.getByText(firstRow.title, { exact: true }).innerText());
    const unreadScreenshot = await this.shot("VER-04", page, "unread-after-reload");

    const readBefore = Date.now();
    const readResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes(`/notifications/${firstRow.id}/read`),
      { timeout: 20_000 },
    );
    await page.getByRole("link", { name: `Open notification: ${firstRow.title}` }).click();
    const readResponse = await readResponsePromise;
    const readAfter = Date.now();
    this.check("VER-04", "mark-one HTTP status", 200, readResponse.status());
    const readPayload = await readResponse.json();
    const readNotification = readPayload.notification;
    this.check("VER-04", "mark-one response id", firstRow.id, readNotification.id);
    this.check("VER-04", "mark-one response is_read", true, readNotification.is_read);
    this.check("VER-04", "mark-one response remains active", false, readNotification.is_dismissed);
    this.truth(
      "VER-04",
      "mark-one timestamp bounded by browser action",
      isoMs(readNotification.read_at) >= readBefore - 1_000 && isoMs(readNotification.read_at) <= readAfter + 1_000,
    );
    await page.waitForURL((url) => url.pathname === "/verify" && url.searchParams.get("screen") === "records", { timeout: 20_000 });
    await page.getByRole("heading", { name: "Records", exact: true }).waitFor({ timeout: 20_000 });
    this.check("VER-04", "notification opens declared browser destination", `${appUrl}/verify?screen=records`, page.url());
    this.check("VER-04", "destination visible heading", "Records", await page.getByRole("heading", { name: "Records", exact: true }).innerText());

    let persisted = (await this.notifications(page)).find((item) => item.id === firstRow.id);
    this.check("VER-04", "persisted mark-one is_read", true, persisted.is_read);
    this.check("VER-04", "persisted mark-one read_at", readNotification.read_at, persisted.read_at);
    this.check("VER-04", "mark-one preserves status", "open", persisted.status);

    await page.goto("/notifications", { waitUntil: "domcontentloaded" });
    const firstActiveCard = page.locator(`[data-notification-id="${firstRow.id}"]`);
    await firstActiveCard.waitFor({ timeout: 15_000 });
    this.check("VER-04", "read row remains visible in full inbox", firstRow.title, await firstActiveCard.getByText(firstRow.title, { exact: true }).innerText());
    this.check("VER-04", "read row exposes exact timestamp", readNotification.read_at, await firstActiveCard.getAttribute("data-read-at"));
    const readReloadScreenshot = await this.shot("VER-04", page, "read-state-after-return");

    const dismissBefore = Date.now();
    const dismissResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes(`/notifications/${firstRow.id}/dismiss`),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: `Dismiss notification: ${firstRow.title}` }).click();
    const dismissResponse = await dismissResponsePromise;
    const dismissAfter = Date.now();
    this.check("VER-04", "dismiss HTTP status", 200, dismissResponse.status());
    const dismissedPayload = (await dismissResponse.json()).notification;
    this.check("VER-04", "dismiss response id", firstRow.id, dismissedPayload.id);
    this.check("VER-04", "dismiss preserves read status", true, dismissedPayload.is_read);
    this.check("VER-04", "dismiss preserves exact read_at", readNotification.read_at, dismissedPayload.read_at);
    this.check("VER-04", "dismiss response state", true, dismissedPayload.is_dismissed);
    this.truth(
      "VER-04",
      "dismiss timestamp bounded by browser action",
      isoMs(dismissedPayload.dismissed_at) >= dismissBefore - 1_000 && isoMs(dismissedPayload.dismissed_at) <= dismissAfter + 1_000,
    );
    const activeAfterDismiss = await this.notifications(page);
    const dismissedAfterDismiss = await this.notifications(page, { dismissed: true });
    this.check("VER-04", "dismiss removes row from active API collection", 0, activeAfterDismiss.filter((item) => item.id === firstRow.id).length);
    this.check("VER-04", "dismissed API collection has exact row", 1, dismissedAfterDismiss.filter((item) => item.id === firstRow.id).length);
    this.check("VER-04", "dismissed API timestamp equals mutation response", dismissedPayload.dismissed_at, dismissedAfterDismiss.find((item) => item.id === firstRow.id).dismissed_at);
    await page.reload({ waitUntil: "domcontentloaded" });
    const dismissedCard = page.locator(`[data-notification-id="${firstRow.id}"][data-dismissed-at]`);
    await dismissedCard.waitFor({ timeout: 15_000 });
    this.check("VER-04", "dismiss survives reload visually", dismissedPayload.dismissed_at, await dismissedCard.getAttribute("data-dismissed-at"));
    const dismissedScreenshot = await this.shot("VER-04", page, "dismissed-after-reload");

    const restorePattern = `**/api/proxy/notifications/${firstRow.id}/restore`;
    const failRestore = async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Injected notification restore outage" }),
      });
    };
    await page.route(restorePattern, failRestore);
    this.expectedFailurePages.add(page);
    const failedRestorePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes(`/notifications/${firstRow.id}/restore`),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: `Restore notification: ${firstRow.title}` }).click();
    const failedRestore = await failedRestorePromise;
    this.check("VER-04", "injected restore failure HTTP status", 503, failedRestore.status());
    await page.getByRole("alert").getByText("Injected notification restore outage", { exact: false }).waitFor({ timeout: 15_000 });
    const afterFailedRestore = (await this.notifications(page, { dismissed: true })).find((item) => item.id === firstRow.id);
    this.check("VER-04", "failed restore preserves exact dismissed_at", dismissedPayload.dismissed_at, afterFailedRestore.dismissed_at);
    this.check("VER-04", "failed restore leaves visible dismissed row", 1, await page.locator(`[data-notification-id="${firstRow.id}"][data-dismissed-at]`).count());
    await page.waitForTimeout(500);
    this.expectedFailurePages.delete(page);
    await page.unroute(restorePattern, failRestore);

    const restoreBefore = Date.now();
    const restoreResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes(`/notifications/${firstRow.id}/restore`),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: `Restore notification: ${firstRow.title}` }).click();
    const restoreResponse = await restoreResponsePromise;
    const restoreAfter = Date.now();
    this.check("VER-04", "restore HTTP status", 200, restoreResponse.status());
    const restoredPayload = (await restoreResponse.json()).notification;
    this.check("VER-04", "restore response id", firstRow.id, restoredPayload.id);
    this.check("VER-04", "restore clears dismissed state", false, restoredPayload.is_dismissed);
    this.check("VER-04", "restore clears dismissed timestamp", null, restoredPayload.dismissed_at);
    this.check("VER-04", "restore preserves prior read state", true, restoredPayload.is_read);
    this.check("VER-04", "restore preserves prior read timestamp", readNotification.read_at, restoredPayload.read_at);
    this.truth("VER-04", "restore browser action completed in bounded time", restoreAfter >= restoreBefore && restoreAfter - restoreBefore < 20_000);
    const activeAfterRestore = (await this.notifications(page)).find((item) => item.id === firstRow.id);
    this.check("VER-04", "restore persists active state", false, activeAfterRestore.is_dismissed);
    this.check("VER-04", "restore persists exact prior read_at", readNotification.read_at, activeAfterRestore.read_at);
    this.check("VER-04", "restore removes row from dismissed API collection", 0, (await this.notifications(page, { dismissed: true })).filter((item) => item.id === firstRow.id).length);
    await page.reload({ waitUntil: "domcontentloaded" });
    const restoredCard = page.locator(`[data-notification-id="${firstRow.id}"][data-read-at]`);
    await restoredCard.waitFor({ timeout: 15_000 });
    this.check("VER-04", "restored row survives reload visually", readNotification.read_at, await restoredCard.getAttribute("data-read-at"));
    const restoredScreenshot = await this.shot("VER-04", page, "restored-after-reload");

    const second = await this.uploadDecision(
      identity,
      `notification-secondary-${runId}.stl`,
      secondFixturePath,
    );
    const secondRow = second.notification;
    await page.goto("/notifications", { waitUntil: "domcontentloaded" });
    await page.getByText(secondRow.title, { exact: true }).waitFor({ timeout: 15_000 });
    const unreadBeforeMarkAll = await this.notifications(page, { unread: true });
    this.check("VER-04", "exact unread count before mark-all", 1, unreadBeforeMarkAll.length);
    this.check("VER-04", "second unread id", secondRow.id, unreadBeforeMarkAll[0].id);
    const markAllBefore = Date.now();
    const markAllResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/notifications/read-all"),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: "Mark all read" }).click();
    const markAllResponse = await markAllResponsePromise;
    const markAllAfter = Date.now();
    this.check("VER-04", "mark-all HTTP status", 200, markAllResponse.status());
    const markAllPayload = await markAllResponse.json();
    this.check("VER-04", "mark-all affected exact unread rows", 1, markAllPayload.count);
    this.truth(
      "VER-04",
      "mark-all response timestamp bounded by browser action",
      isoMs(markAllPayload.read_at) >= markAllBefore - 1_000 && isoMs(markAllPayload.read_at) <= markAllAfter + 1_000,
    );
    await page.waitForFunction(
      ({ id, readAt }) => document.querySelector(`[data-notification-id="${id}"]`)?.getAttribute("data-read-at") === readAt,
      { id: secondRow.id, readAt: markAllPayload.read_at },
    );
    this.check("VER-04", "mark-all control disappears at zero unread", 0, await page.getByRole("button", { name: "Mark all read" }).count());
    const markAllScreenshot = await this.shot("VER-04", page, "after-mark-all");
    const allAfter = await this.notifications(page);
    const secondPersisted = allAfter.find((item) => item.id === secondRow.id);
    this.check("VER-04", "mark-all persisted second row", true, secondPersisted.is_read);
    this.check("VER-04", "mark-all response/persisted exact timestamp", markAllPayload.read_at, secondPersisted.read_at);
    this.truth(
      "VER-04",
      "mark-all timestamp bounded by browser action",
      isoMs(secondPersisted.read_at) >= markAllBefore - 1_000 && isoMs(secondPersisted.read_at) <= markAllAfter + 1_000,
    );
    this.check("VER-04", "read notifications retained", 2, allAfter.filter((item) => [firstRow.id, secondRow.id].includes(item.id)).length);
    this.check("VER-04", "read notifications retain open status", true, allAfter.filter((item) => [firstRow.id, secondRow.id].includes(item.id)).every((item) => item.status === "open"));

    const openapiResponse = await fetch(`${apiUrl}/openapi.json`);
    this.check("VER-04", "OpenAPI HTTP status", 200, openapiResponse.status);
    const openapi = await openapiResponse.json();
    const notificationPaths = Object.keys(openapi.paths || {}).filter((item) => item.includes("/notifications"));
    const dismissRestorePaths = notificationPaths.filter((item) => /dismiss|restore/i.test(item));
    this.check("VER-04", "dismiss/restore endpoint count", 2, dismissRestorePaths.length);
    this.truth("VER-04", "OpenAPI exposes dismiss endpoint", dismissRestorePaths.some((item) => item.endsWith("/dismiss")));
    this.truth("VER-04", "OpenAPI exposes restore endpoint", dismissRestorePaths.some((item) => item.endsWith("/restore")));
    this.observations.notifications = {
      first: activeAfterRestore,
      second: secondPersisted,
      notificationPaths,
      dismissRestoreSupported: true,
      transitions: {
        read: readNotification,
        dismissed: dismissedPayload,
        failedRestoreDismissedAt: afterFailedRestore.dismissed_at,
        restored: restoredPayload,
      },
      screenshots: { unreadScreenshot, readReloadScreenshot, dismissedScreenshot, restoredScreenshot, markAllScreenshot },
      firstDecision: first,
      secondDecision: second,
    };
  }

  async sessionRecovery(identity) {
    const { page, context, email } = identity;
    const expectedRows = this.observations.notifications;
    await page.goto("/notifications", { waitUntil: "domcontentloaded" });
    await page.getByText(expectedRows.first.title, { exact: true }).waitFor({ timeout: 15_000 });
    await page.getByText(expectedRows.second.title, { exact: true }).waitFor({ timeout: 15_000 });
    const oldCookies = await context.cookies();
    await page.evaluate(() => {
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const target = typeof args[0] === "string" ? args[0] : args[0] instanceof Request ? args[0].url : "";
        if (new URL(target, window.location.href).pathname === "/api/auth/logout") {
          const body = await response.clone().json();
          window.sessionStorage.setItem(
            "qa.logout.evidence",
            JSON.stringify({ status: response.status, body }),
          );
        }
        return response;
      };
    });
    const logoutResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/auth/logout",
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: "Account" }).click();
    await page.getByText("Sign out", { exact: true }).click();
    const logoutResponse = await logoutResponsePromise;
    this.check("FAIL-09", "logout HTTP status", 200, logoutResponse.status());
    await page.waitForURL((url) => url.pathname === "/login", { timeout: 20_000 });
    const logoutEvidence = await page.evaluate(() => JSON.parse(window.sessionStorage.getItem("qa.logout.evidence") || "null"));
    this.check("FAIL-09", "browser-captured logout status", 200, logoutEvidence.status);
    this.check("FAIL-09", "logout revoked sessions", true, logoutEvidence.body.sessionsRevoked);

    const replayContext = await this.browser.newContext({ baseURL: appUrl });
    await replayContext.addCookies(oldCookies);
    const replayPage = await replayContext.newPage();
    this.watch(replayPage);
    await replayPage.goto("/notifications", { waitUntil: "domcontentloaded" });
    await replayPage.waitForURL((url) => url.pathname === "/login", { timeout: 20_000 });
    this.expected401Pages.add(replayPage);
    const replayApi = await this.request(replayPage, "/api/proxy/notifications?status=all&unread=false&limit=100");
    this.expected401Pages.delete(replayPage);
    this.check("FAIL-09", "copied pre-logout cookie API status", 401, replayApi.status);
    await replayContext.close();

    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: /^Log in$/ }).click();
    await page.waitForURL((url) => url.pathname !== "/login", { timeout: 30_000 });
    await page.goto("/notifications", { waitUntil: "domcontentloaded" });
    this.check("FAIL-09", "post-login first durable row visible", expectedRows.first.title, await page.getByText(expectedRows.first.title, { exact: true }).innerText());
    this.check("FAIL-09", "post-login second durable row visible", expectedRows.second.title, await page.getByText(expectedRows.second.title, { exact: true }).innerText());
    const afterLogin = await this.notifications(page);
    const firstAfter = afterLogin.find((item) => item.id === expectedRows.first.id);
    const secondAfter = afterLogin.find((item) => item.id === expectedRows.second.id);
    this.check("FAIL-09", "first read_at survives logout/login", expectedRows.first.read_at, firstAfter.read_at);
    this.check("FAIL-09", "second read_at survives logout/login", expectedRows.second.read_at, secondAfter.read_at);
    this.check("FAIL-09", "first read status survives logout/login", true, firstAfter.is_read);
    this.check("FAIL-09", "second read status survives logout/login", true, secondAfter.is_read);
    this.check("FAIL-09", "restored first row stays active after logout/login", false, firstAfter.is_dismissed);
    this.check("FAIL-09", "second row stays active after logout/login", false, secondAfter.is_dismissed);
    const dismissedAfterLogin = await this.notifications(page, { dismissed: true });
    this.check("FAIL-09", "dismissed collection remains empty after logout/login", 0, dismissedAfterLogin.length);
    const screenshot = await this.shot("FAIL-09", page, "reauthenticated-read-state");
    this.observations.session = {
      logoutStatus: logoutEvidence.status,
      sessionsRevoked: logoutEvidence.body.sessionsRevoked,
      replayApiStatus: replayApi.status,
      finalUrl: page.url(),
      firstReadAt: firstAfter.read_at,
      secondReadAt: secondAfter.read_at,
      dismissedCount: dismissedAfterLogin.length,
      screenshot,
    };
  }

  async approveViaBrowser(identity, id, note, branch) {
    const { page } = identity;
    const textarea = page.getByPlaceholder("Optional approval note");
    await textarea.waitFor({ timeout: 15_000 });
    if (note !== "") await textarea.fill(note);
    const before = Date.now();
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes(`/cost-decisions/${id}/approve`),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: /^Approve$/ }).click();
    const response = await responsePromise;
    const after = Date.now();
    this.check("WORK-05", `${branch} approval HTTP status`, 200, response.status());
    const payload = await response.json();
    await page.getByText("Approved", { exact: true }).waitFor({ timeout: 15_000 });
    const detail = await this.decision(identity.page, id);
    const expectedNote = note.trim() || null;
    this.check("WORK-05", `${branch} approval status`, "approved", detail.approval_status);
    this.check("WORK-05", `${branch} persisted note`, expectedNote, detail.approval_note);
    this.check("WORK-05", `${branch} response/persisted timestamp`, payload.approved_at, detail.approved_at);
    this.check("WORK-05", `${branch} response/persisted signer`, payload.approved_by_user_id, detail.approved_by_user_id);
    this.truth(
      "WORK-05",
      `${branch} timestamp bounded by browser action`,
      isoMs(detail.approved_at) >= before - 1_000 && isoMs(detail.approved_at) <= after + 1_000,
    );
    return detail;
  }

  async reopenViaBrowser(identity, id, branch) {
    const { page } = identity;
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "DELETE" && response.url().includes(`/cost-decisions/${id}/approve`),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: /^Reopen$/ }).click();
    const response = await responsePromise;
    this.check("WORK-05", `${branch} reopen HTTP status`, 200, response.status());
    await page.getByText("Unreviewed", { exact: true }).waitFor({ timeout: 15_000 });
    const detail = await this.decision(identity.page, id);
    this.check("WORK-05", `${branch} reopened status`, "unreviewed", detail.approval_status);
    this.check("WORK-05", `${branch} cleared note`, null, detail.approval_note);
    this.check("WORK-05", `${branch} cleared timestamp`, null, detail.approved_at);
    this.check("WORK-05", `${branch} cleared signer`, null, detail.approved_by_user_id);
    return detail;
  }

  async decisionNotes(identity) {
    const { page } = identity;
    const id = this.observations.notifications.firstDecision.detail.id;
    await page.goto(`/cost-decisions/${id}`, { waitUntil: "domcontentloaded" });
    await page.getByText("Decision governance", { exact: true }).waitFor({ timeout: 20_000 });
    const initial = await this.decision(page, id);
    const artifactHash = sha256(initial.result);
    this.check("WORK-05", "initial governance status", "unreviewed", initial.approval_status);
    this.check("WORK-05", "initial approval note", null, initial.approval_note);

    const empty = await this.approveViaBrowser(identity, id, "", "empty-note");
    this.check("WORK-05", "empty note has no visible Approval note block", 0, await page.getByText("Approval note", { exact: true }).count());
    this.check("WORK-05", "empty approval preserves result artifact", artifactHash, sha256(empty.result));
    const emptyScreenshot = await this.shot("WORK-05", page, "empty-note-approved");
    await this.reopenViaBrowser(identity, id, "empty-note");

    const ordinary = await this.approveViaBrowser(identity, id, normalNote, "ordinary-note");
    this.check("WORK-05", "ordinary note exact visible value", normalNote, await page.getByTestId("approval-note").innerText());
    this.check("WORK-05", "ordinary approval preserves result artifact", artifactHash, sha256(ordinary.result));
    await this.reopenViaBrowser(identity, id, "ordinary-note-edit");

    const special = await this.approveViaBrowser(identity, id, specialNote, "special-character-edit");
    this.check("WORK-05", "special note exact visible value", specialNote, await page.getByTestId("approval-note").innerText());
    this.check(
      "WORK-05",
      "special note visible whitespace mode",
      "pre-wrap",
      await page.getByTestId("approval-note").evaluate((element) => getComputedStyle(element).whiteSpace),
    );
    this.check("WORK-05", "special approval preserves result artifact", artifactHash, sha256(special.result));
    const specialScreenshot = await this.shot("WORK-05", page, "special-note-visible");
    await this.reopenViaBrowser(identity, id, "special-note-long-boundary");

    const long = await this.approveViaBrowser(identity, id, longNote, "1000-character-note");
    this.check("WORK-05", "1000-character persisted length", 1000, long.approval_note.length);
    this.check("WORK-05", "1000-character visible value", longNote, await page.getByTestId("approval-note").innerText());
    this.check("WORK-05", "1000-character prefix", longPrefix, long.approval_note.slice(0, longPrefix.length));
    this.check("WORK-05", "1000-character suffix", longSuffix, long.approval_note.slice(-longSuffix.length));
    this.expected422Pages.add(page);
    const overlong = await this.request(page, `/api/proxy/cost-decisions/${id}/approve`, {
      method: "POST",
      data: { note: `${longNote}X` },
    });
    this.expected422Pages.delete(page);
    this.check("WORK-05", "1001-character API status", 422, overlong.status);
    this.truth(
      "WORK-05",
      "1001-character response names 1000-character limit",
      /1000/.test(stableJson(overlong.body)),
    );
    const afterOverlong = await this.decision(page, id);
    this.check("WORK-05", "rejected 1001-character note leaves exact prior note", longNote, afterOverlong.approval_note);
    this.check("WORK-05", "rejected 1001-character note leaves timestamp", long.approved_at, afterOverlong.approved_at);
    await this.reopenViaBrowser(identity, id, "1000-character-note-final-edit");

    const final = await this.approveViaBrowser(identity, id, specialNote, "final-special-note");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("approval-note").waitFor({ timeout: 15_000 });
    this.check("WORK-05", "special note survives page reopen", specialNote, await page.getByTestId("approval-note").innerText());
    const reopenedDetail = await this.decision(page, id);
    this.check("WORK-05", "special note survives API reopen", specialNote, reopenedDetail.approval_note);
    this.check("WORK-05", "final approved_at survives page reopen", final.approved_at, reopenedDetail.approved_at);
    this.check("WORK-05", "all governance mutations preserve immutable result", artifactHash, sha256(reopenedDetail.result));
    const finalScreenshot = await this.shot("WORK-05", page, "final-note-after-page-reopen");
    this.observations.decision = {
      id,
      filename: final.filename,
      initialStatus: initial.approval_status,
      empty,
      ordinary,
      special,
      long,
      final: reopenedDetail,
      artifactHash,
      screenshots: { emptyScreenshot, specialScreenshot, finalScreenshot },
      branches: {
        empty: null,
        ordinary: normalNote,
        special: specialNote,
        long: longNote,
        overlongStatus: overlong.status,
      },
    };
  }

  async chooseDispositionViaBrowser(identity, id, clickedKey, expectedLabel, expectedNote, branch) {
    const { page } = identity;
    const before = Date.now();
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "PUT" && response.url().includes(`/cost-decisions/${id}/disposition`),
      { timeout: 20_000 },
    );
    await page.getByTestId(`record-disposition-${clickedKey}`).click();
    const response = await responsePromise;
    const after = Date.now();
    this.check("VER-07", `${branch} HTTP status`, 200, response.status());
    const payload = await response.json();
    const detail = await this.decision(page, id);
    this.check("VER-07", `${branch} response disposition`, clickedKey, payload.user_disposition);
    this.check("VER-07", `${branch} persisted disposition`, clickedKey, detail.user_disposition);
    this.check("VER-07", `${branch} response label`, expectedLabel, payload.user_disposition_label);
    this.check("VER-07", `${branch} persisted label`, expectedLabel, detail.user_disposition_label);
    this.check("VER-07", `${branch} response disposition note`, expectedNote, payload.disposition_note);
    this.check("VER-07", `${branch} persisted disposition note`, expectedNote, detail.disposition_note);
    this.check("VER-07", `${branch} response/persisted timestamp`, payload.disposition_updated_at, detail.disposition_updated_at);
    this.check("VER-07", `${branch} response/persisted actor`, payload.disposition_updated_by_user_id, detail.disposition_updated_by_user_id);
    this.truth(
      "VER-07",
      `${branch} timestamp bounded by browser action`,
      isoMs(detail.disposition_updated_at) >= before - 1_000 && isoMs(detail.disposition_updated_at) <= after + 1_000,
    );
    this.check("VER-07", `${branch} selected browser state`, "true", await page.getByTestId(`record-disposition-${clickedKey}`).getAttribute("aria-pressed"));
    this.check("VER-07", `${branch} exact note remains in editor`, expectedNote ?? "", await page.getByTestId("record-disposition-note").inputValue());
    const panelText = await page.getByTestId("cost-decision-disposition").innerText();
    this.truth(
      "VER-07",
      `${branch} visible governance state`,
      expectedLabel ? panelText.includes(expectedLabel) : panelText.includes("Choose what the organization will do with this part."),
    );
    return detail;
  }

  async saveDispositionNoteViaBrowser(identity, id, note, expectedDisposition, branch) {
    const { page } = identity;
    const textarea = page.getByTestId("record-disposition-note");
    await textarea.fill(note);
    const expectedNote = note.trim() || null;
    const before = Date.now();
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "PUT" && response.url().includes(`/cost-decisions/${id}/disposition`),
      { timeout: 20_000 },
    );
    await page.getByTestId("record-disposition-note-save").click();
    const response = await responsePromise;
    const after = Date.now();
    this.check("VER-07", `${branch} HTTP status`, 200, response.status());
    const payload = await response.json();
    const detail = await this.decision(page, id);
    this.check("VER-07", `${branch} response keeps choice`, expectedDisposition, payload.user_disposition);
    this.check("VER-07", `${branch} persisted choice`, expectedDisposition, detail.user_disposition);
    this.check("VER-07", `${branch} response note`, expectedNote, payload.disposition_note);
    this.check("VER-07", `${branch} persisted note`, expectedNote, detail.disposition_note);
    this.check("VER-07", `${branch} response/persisted timestamp`, payload.disposition_updated_at, detail.disposition_updated_at);
    this.truth(
      "VER-07",
      `${branch} timestamp bounded by browser action`,
      isoMs(detail.disposition_updated_at) >= before - 1_000 && isoMs(detail.disposition_updated_at) <= after + 1_000,
    );
    await page.waitForFunction(
      (expected) => document.querySelector('[data-testid="record-disposition-note"]')?.value === expected,
      expectedNote ?? "",
    );
    this.check("VER-07", `${branch} exact browser value`, expectedNote ?? "", await textarea.inputValue());
    return detail;
  }

  async withdrawDispositionViaBrowser(identity, id, branch) {
    const { page } = identity;
    const before = Date.now();
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "PUT" && response.url().includes(`/cost-decisions/${id}/disposition`),
      { timeout: 20_000 },
    );
    await page.getByTestId("record-disposition-withdraw").click();
    const response = await responsePromise;
    const after = Date.now();
    this.check("VER-07", `${branch} HTTP status`, 200, response.status());
    const payload = await response.json();
    const detail = await this.decision(page, id);
    this.check("VER-07", `${branch} response clears disposition`, null, payload.user_disposition);
    this.check("VER-07", `${branch} persisted disposition`, null, detail.user_disposition);
    this.check("VER-07", `${branch} response clears label`, null, payload.user_disposition_label);
    this.check("VER-07", `${branch} persisted label`, null, detail.user_disposition_label);
    this.check("VER-07", `${branch} response clears note`, null, payload.disposition_note);
    this.check("VER-07", `${branch} persisted note`, null, detail.disposition_note);
    this.check("VER-07", `${branch} response/persisted timestamp`, payload.disposition_updated_at, detail.disposition_updated_at);
    this.truth(
      "VER-07",
      `${branch} timestamp bounded by browser action`,
      isoMs(detail.disposition_updated_at) >= before - 1_000 && isoMs(detail.disposition_updated_at) <= after + 1_000,
    );
    await page.waitForFunction(
      () => document.querySelector('[data-testid="record-disposition-note"]')?.value === "",
    );
    this.truth("VER-07", `${branch} visible undecided state`, (await page.getByTestId("cost-decision-disposition").innerText()).includes("Choose what the organization will do with this part."));
    return detail;
  }

  async approveDispositionSignoff(identity, id, note, branch) {
    const { page } = identity;
    await page.getByPlaceholder("Optional approval note").fill(note);
    const before = Date.now();
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes(`/cost-decisions/${id}/approve`),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: /^Approve$/ }).click();
    const response = await responsePromise;
    const after = Date.now();
    this.check("VER-07", `${branch} approval HTTP status`, 200, response.status());
    const payload = await response.json();
    const detail = await this.decision(page, id);
    this.check("VER-07", `${branch} approved status`, "approved", detail.approval_status);
    this.check("VER-07", `${branch} approval note`, note, detail.approval_note);
    this.check("VER-07", `${branch} approval timestamp`, payload.approved_at, detail.approved_at);
    this.truth(
      "VER-07",
      `${branch} approval timestamp bounded by browser action`,
      isoMs(detail.approved_at) >= before - 1_000 && isoMs(detail.approved_at) <= after + 1_000,
    );
    return detail;
  }

  async fourWayDisposition(identity) {
    const { page } = identity;
    const id = this.observations.decision.final.id;
    const filename = this.observations.decision.final.filename;
    const artifactHash = this.observations.decision.artifactHash;
    await page.goto(`/cost-decisions/${id}`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("cost-decision-disposition").waitFor({ timeout: 20_000 });
    const initial = await this.decision(page, id);
    this.check("VER-07", "initial choice is undecided", null, initial.user_disposition);
    this.check("VER-07", "initial disposition note is empty", null, initial.disposition_note);
    this.check("VER-07", "initial disposition note editor is empty", "", await page.getByTestId("record-disposition-note").inputValue());
    this.check("VER-07", "initial choice flow starts approved", "approved", initial.approval_status);
    this.check("VER-07", "initial choice flow preserves WORK-05 note", specialNote, initial.approval_note);
    this.check("VER-07", "initial disposition artifact hash", artifactHash, sha256(initial.result));

    const routePattern = `**/api/proxy/cost-decisions/${id}/disposition`;
    const injectedFailure = async (route) => {
      if (route.request().method() === "PUT") {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Injected disposition outage" }),
        });
      } else {
        await route.continue();
      }
    };
    await page.route(routePattern, injectedFailure);
    this.expectedFailurePages.add(page);
    await page.getByTestId("record-disposition-note").fill(dispositionCreateNote);
    const failedResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "PUT" && response.url().includes(`/cost-decisions/${id}/disposition`),
      { timeout: 20_000 },
    );
    await page.getByTestId("record-disposition-inhouse").click();
    const failedResponse = await failedResponsePromise;
    this.check("VER-07", "injected choice failure HTTP status", 503, failedResponse.status());
    await page.getByTestId("record-disposition-error").getByText("Injected disposition outage", { exact: false }).waitFor({ timeout: 15_000 });
    const afterFailure = await this.decision(page, id);
    this.check("VER-07", "failed choice leaves persisted outcome", null, afterFailure.user_disposition);
    this.check("VER-07", "failed choice leaves persisted disposition note", null, afterFailure.disposition_note);
    this.check("VER-07", "failed choice preserves note draft for retry", dispositionCreateNote, await page.getByTestId("record-disposition-note").inputValue());
    this.check("VER-07", "failed choice leaves approved status", "approved", afterFailure.approval_status);
    this.check("VER-07", "failed choice leaves immutable artifact", artifactHash, sha256(afterFailure.result));
    this.check("VER-07", "failed choice remains retryable", false, await page.getByTestId("record-disposition-inhouse").isDisabled());
    const errorScreenshot = await this.shot("VER-07", page, "injected-error-retryable");
    await page.waitForTimeout(500);
    this.expectedFailurePages.delete(page);
    await page.unroute(routePattern, injectedFailure);

    const choices = [];
    const inhouse = await this.chooseDispositionViaBrowser(identity, id, "inhouse", "Make in-house", dispositionCreateNote, "make-in-house-with-created-note");
    this.check("VER-07", "make-in-house reopens prior approval", "unreviewed", inhouse.approval_status);
    this.check("VER-07", "make-in-house clears prior approval note", null, inhouse.approval_note);
    this.check("VER-07", "make-in-house preserves immutable artifact", artifactHash, sha256(inhouse.result));
    choices.push({ key: "inhouse", label: "Make in-house", note: inhouse.disposition_note, updatedAt: inhouse.disposition_updated_at });

    const signedInhouse = await this.approveDispositionSignoff(identity, id, "Approved in-house outcome.", "in-house signoff");
    this.check("VER-07", "approval keeps in-house choice", "inhouse", signedInhouse.user_disposition);
    this.check("VER-07", "approval keeps created disposition note", dispositionCreateNote, signedInhouse.disposition_note);

    const specialEdit = await this.saveDispositionNoteViaBrowser(identity, id, specialNote, "inhouse", "special-character note edit");
    this.check("VER-07", "approved disposition-note edit reopens signoff", "unreviewed", specialEdit.approval_status);
    this.check("VER-07", "approved disposition-note edit clears signer", null, specialEdit.approved_by_user_id);
    this.check("VER-07", "approved disposition-note edit clears timestamp", null, specialEdit.approved_at);
    this.check("VER-07", "approved disposition-note edit clears approval note", null, specialEdit.approval_note);
    this.check("VER-07", "special-character note preserves immutable artifact", artifactHash, sha256(specialEdit.result));

    const longEdit = await this.saveDispositionNoteViaBrowser(identity, id, longNote, "inhouse", "1000-character disposition note");
    this.check("VER-07", "1000-character disposition note length", 1000, longEdit.disposition_note.length);
    this.check("VER-07", "1000-character note counter", "1000/1000", await page.getByText("1000/1000", { exact: true }).innerText());
    this.expected422Pages.add(page);
    const overlongDisposition = await this.request(page, `/api/proxy/cost-decisions/${id}/disposition`, {
      method: "PUT",
      data: { disposition: "inhouse", note: `${longNote}X` },
    });
    this.expected422Pages.delete(page);
    this.check("VER-07", "1001-character disposition note API status", 422, overlongDisposition.status);
    this.truth("VER-07", "1001-character disposition note response names limit", /1000/.test(stableJson(overlongDisposition.body)));
    const afterOverlongDisposition = await this.decision(page, id);
    this.check("VER-07", "rejected disposition note preserves exact 1000 characters", longNote, afterOverlongDisposition.disposition_note);
    this.check("VER-07", "rejected disposition note preserves timestamp", longEdit.disposition_updated_at, afterOverlongDisposition.disposition_updated_at);

    const emptyEdit = await this.saveDispositionNoteViaBrowser(identity, id, "  \n  ", "inhouse", "empty disposition note edit");
    this.check("VER-07", "empty disposition note normalizes to null", null, emptyEdit.disposition_note);
    const restoredSpecial = await this.saveDispositionNoteViaBrowser(identity, id, specialNote, "inhouse", "restore special disposition note");
    this.check("VER-07", "restored special note preserves choice", "inhouse", restoredSpecial.user_disposition);
    const signedSpecial = await this.approveDispositionSignoff(identity, id, "Approved special disposition rationale.", "special disposition signoff");
    this.check("VER-07", "special disposition signoff keeps exact note", specialNote, signedSpecial.disposition_note);

    const outside = await this.chooseDispositionViaBrowser(identity, id, "outside", "Make outside", specialNote, "make-outside");
    this.check("VER-07", "changed approved choice reopens signoff", "unreviewed", outside.approval_status);
    this.check("VER-07", "changed approved choice clears signer", null, outside.approved_by_user_id);
    this.check("VER-07", "changed approved choice clears timestamp", null, outside.approved_at);
    this.check("VER-07", "changed approved choice clears note", null, outside.approval_note);
    this.check("VER-07", "make-outside preserves immutable artifact", artifactHash, sha256(outside.result));
    choices.push({ key: "outside", label: "Make outside", note: outside.disposition_note, updatedAt: outside.disposition_updated_at });

    const acquire = await this.chooseDispositionViaBrowser(identity, id, "acquire", "Acquire capability", specialNote, "acquire-capability");
    this.check("VER-07", "acquire preserves immutable artifact", artifactHash, sha256(acquire.result));
    choices.push({ key: "acquire", label: "Acquire capability", note: acquire.disposition_note, updatedAt: acquire.disposition_updated_at });
    const redesign = await this.chooseDispositionViaBrowser(identity, id, "redesign", "Redesign", specialNote, "redesign");
    this.check("VER-07", "redesign preserves immutable artifact", artifactHash, sha256(redesign.result));
    choices.push({ key: "redesign", label: "Redesign", note: redesign.disposition_note, updatedAt: redesign.disposition_updated_at });
    this.truth("VER-07", "all four choice timestamps are distinct", new Set(choices.map((choice) => choice.updatedAt)).size === 4);

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("cost-decision-disposition").waitFor({ timeout: 20_000 });
    this.check("VER-07", "redesign survives detail reload", "true", await page.getByTestId("record-disposition-redesign").getAttribute("aria-pressed"));
    this.truth("VER-07", "full governance shows Redesign", (await page.getByTestId("cost-decision-disposition").innerText()).includes("Redesign"));
    this.check("VER-07", "full governance reload shows exact disposition note", specialNote, await page.getByTestId("record-disposition-note").inputValue());
    const governanceScreenshot = await this.shot("VER-07", page, "full-governance-reload");

    await page.goto("/verify?screen=records", { waitUntil: "domcontentloaded" });
    await page.getByRole("heading", { name: "Records", exact: true }).waitFor({ timeout: 20_000 });
    const recordRow = page.locator("button").filter({ hasText: filename }).first();
    await recordRow.waitFor({ timeout: 20_000 });
    await recordRow.click();
    const recordsSummary = page.getByTestId("record-disposition-summary");
    await recordsSummary.waitFor({ timeout: 20_000 });
    this.truth("VER-07", "Records modal shows Redesign", (await recordsSummary.innerText()).includes("Redesign"));
    this.truth("VER-07", "Records modal exposes full governance link", (await recordsSummary.innerText()).includes("Open governance"));
    this.check("VER-07", "Records modal shows exact disposition note", specialNote, await page.getByTestId("record-disposition-note-summary").innerText());
    const recordsScreenshot = await this.shot("VER-07", page, "records-redesign-visible");

    await page.goto(`/cost-decisions/${id}`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("cost-decision-disposition").waitFor({ timeout: 20_000 });
    const withdrawn = await this.withdrawDispositionViaBrowser(identity, id, "withdraw-redesign");
    this.check("VER-07", "withdraw clears disposition note", null, withdrawn.disposition_note);
    this.check("VER-07", "withdraw preserves immutable artifact", artifactHash, sha256(withdrawn.result));
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("cost-decision-disposition").waitFor({ timeout: 20_000 });
    this.truth("VER-07", "withdraw survives detail reload", (await page.getByTestId("cost-decision-disposition").innerText()).includes("Choose what the organization will do with this part."));
    const persistedWithdrawn = await this.decision(page, id);
    this.check("VER-07", "withdraw survives API reopen", null, persistedWithdrawn.user_disposition);
    this.check("VER-07", "withdraw timestamp survives reload", withdrawn.disposition_updated_at, persistedWithdrawn.disposition_updated_at);

    await page.getByTestId("record-disposition-note").fill(specialNote);
    const reopened = await this.chooseDispositionViaBrowser(identity, id, "redesign", "Redesign", specialNote, "reopen-redesign-after-withdraw");
    this.check("VER-07", "reopened choice timestamp differs from withdrawal", false, reopened.disposition_updated_at === withdrawn.disposition_updated_at);
    this.check("VER-07", "reopened choice preserves immutable artifact", artifactHash, sha256(reopened.result));
    const final = await this.approveDispositionSignoff(identity, id, specialNote, "post-disposition export signoff");
    this.check("VER-07", "post-disposition signoff keeps reopened choice", "redesign", final.user_disposition);
    this.check("VER-07", "post-disposition signoff keeps exact disposition note", specialNote, final.disposition_note);
    this.check("VER-07", "post-disposition signoff preserves immutable artifact", artifactHash, sha256(final.result));
    this.observations.decision.final = final;
    this.observations.disposition = {
      id,
      choices,
      errorRecovered: true,
      selectedBeforeWithdraw: "redesign",
      noteTransitions: {
        initial: null,
        created: dispositionCreateNote,
        special: specialNote,
        longLength: longEdit.disposition_note.length,
        empty: emptyEdit.disposition_note,
        final: final.disposition_note,
        overlongStatus: overlongDisposition.status,
      },
      withdrawnAt: withdrawn.disposition_updated_at,
      reopenedAt: reopened.disposition_updated_at,
      finalDisposition: final.user_disposition,
      finalDispositionNote: final.disposition_note,
      finalDispositionUpdatedAt: final.disposition_updated_at,
      artifactHash,
      screenshots: { errorScreenshot, governanceScreenshot, recordsScreenshot },
    };
  }

  async download(page, buttonName, destination) {
    const downloadPromise = page.waitForEvent("download", { timeout: 90_000 });
    await page.getByRole("button", { name: buttonName }).click();
    const download = await downloadPromise;
    await download.saveAs(destination);
    const failure = await download.failure();
    if (failure) fail(`download ${buttonName} failed: ${failure}`);
    return download.suggestedFilename();
  }

  async exports(identity) {
    const { page } = identity;
    const decision = this.observations.decision.final;
    const id = decision.id;
    await page.goto(`/cost-decisions/${id}`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("approval-note").waitFor({ timeout: 20_000 });
    const beforeHash = sha256((await this.decision(page, id)).result);

    const jsonPath = path.join(artifactDir, `${id}-cost.json`);
    const csvPath = path.join(artifactDir, `${id}-cost.csv`);
    const pdfPath = path.join(artifactDir, `${id}-cost-report.pdf`);
    const jsonFilename = await this.download(page, /^JSON$/, jsonPath);
    const csvFilename = await this.download(page, /^CSV$/, csvPath);
    const pdfFilename = await this.download(page, /^Download PDF$/, pdfPath);
    const json = JSON.parse(await readFile(jsonPath, "utf8"));
    const csvText = await readFile(csvPath, "utf8");
    const rows = csvRows(csvText);
    const pdfText = execFileSync("pdftotext", [pdfPath, "-"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    const governance = json.governance;
    this.check("WORK-07", "JSON approval status", "approved", governance.approval_status);
    this.check("WORK-07", "JSON approved signer", decision.approved_by_user_id, governance.approved_by_user_id);
    this.check("WORK-07", "JSON approval timestamp", decision.approved_at, governance.approved_at);
    this.check("WORK-07", "JSON exact multiline/special note", specialNote, governance.approval_note);
    this.check("WORK-07", "JSON carries final disposition", "redesign", governance.user_disposition);
    this.check("WORK-07", "JSON carries final disposition label", "Redesign", governance.user_disposition_label);
    this.check("WORK-07", "JSON exact multiline/special disposition note", specialNote, governance.disposition_note);
    this.check("WORK-07", "JSON disposition timestamp", decision.disposition_updated_at, governance.disposition_updated_at);
    const jsonResult = { ...json };
    delete jsonResult.governance;
    this.check("WORK-07", "JSON retains exact immutable cost artifact", beforeHash, sha256(jsonResult));
    this.check("WORK-07", "CSV row count matches result estimates", decision.result.estimates.length, rows.length);
    this.truth("WORK-07", "CSV every row is approved", rows.every((row) => row.approval_status === "approved"));
    this.truth("WORK-07", "CSV every row has exact signer", rows.every((row) => row.approved_by_user_id === String(decision.approved_by_user_id)));
    this.truth("WORK-07", "CSV every row has exact timestamp", rows.every((row) => row.approved_at === decision.approved_at));
    this.truth("WORK-07", "CSV every row has exact multiline/special note", rows.every((row) => row.approval_note === specialNote));
    this.truth("WORK-07", "CSV every row carries final disposition", rows.every((row) => row.user_disposition === "redesign"));
    this.truth("WORK-07", "CSV every row carries final disposition label", rows.every((row) => row.user_disposition_label === "Redesign"));
    this.truth("WORK-07", "CSV every row has exact multiline/special disposition note", rows.every((row) => row.disposition_note === specialNote));
    this.truth("WORK-07", "CSV every row has exact disposition timestamp", rows.every((row) => row.disposition_updated_at === decision.disposition_updated_at));
    this.truth("WORK-07", "PDF contains Decision Governance heading", pdfText.includes("Decision Governance"));
    this.truth("WORK-07", "PDF contains approved status", /Status:\s+approved/.test(pdfText));
    this.truth("WORK-07", "PDF carries final Redesign disposition", /Recorded outcome:\s+Redesign/.test(pdfText));
    this.truth("WORK-07", "PDF contains exact signer", pdfText.includes(`Signed by user: ${decision.approved_by_user_id}`));
    this.truth("WORK-07", "PDF contains exact approval timestamp", pdfText.includes(decision.approved_at));
    const pdfNote = specialNote.replaceAll("\ufe0f", "");
    this.truth("WORK-07", "PDF contains first special-note line", pdfText.includes(pdfNote.split("\n")[0]));
    this.truth("WORK-07", "PDF contains second special-note line", pdfText.includes(specialNote.split("\n")[1]));
    this.truth("WORK-07", "PDF contains disposition note heading", pdfText.includes("Outcome note:"));
    this.truth("WORK-07", "PDF disposition note keeps inline text glyph", !pdfText.includes("⚙️"));
    const afterHash = sha256((await this.decision(page, id)).result);
    this.check("WORK-07", "exports do not mutate decision artifact", beforeHash, afterHash);
    this.truth("WORK-07", "JSON download filename is explicit", /-cost\.json$/.test(jsonFilename));
    this.truth("WORK-07", "CSV download filename is explicit", /-cost\.csv$/.test(csvFilename));
    this.truth("WORK-07", "PDF download filename is explicit", /-cost-report\.pdf$/.test(pdfFilename));

    await page.getByRole("button", { name: "Share", exact: true }).click();
    const shareDialog = page.getByRole("dialog", { name: "Share this should-cost decision" });
    await shareDialog.waitFor();
    const shareUrl = await shareDialog.locator("input[readonly]").inputValue();
    const sharePath = new URL(shareUrl).pathname;
    const shortId = sharePath.split("/").filter(Boolean).at(-1);
    this.truth("WORK-07", "share URL has public cost route", /^\/s\/cost\/[A-Za-z0-9_-]+$/.test(sharePath));

    const publicContext = await this.browser.newContext({
      baseURL: appUrl,
      viewport: { width: 1200, height: 900 },
      reducedMotion: "reduce",
      extraHTTPHeaders: { "x-real-ip": "198.51.100.73" },
    });
    const publicPage = await publicContext.newPage();
    this.watch(publicPage);
    await publicPage.goto(sharePath, { waitUntil: "domcontentloaded" });
    await publicPage.getByText("Shared should-cost · read-only", { exact: true }).waitFor();
    const publicText = await publicPage.locator("body").innerText();
    const publicPayload = await this.publicRequest(`${apiUrl}/s/cost/${shortId}`);
    this.check("WORK-07", "public share API status", 200, publicPayload.status);
    const forbiddenPaths = forbiddenKeyPaths(
      publicPayload.body,
      new Set(["id", "ulid", "user_id", "api_key_id", "mesh_hash", "params_hash", "share_short_id", "is_public"]),
    );
    this.check("WORK-07", "public share forbidden identity fields", [], forbiddenPaths);
    this.truth("WORK-07", "public page states read-only", /read-only/i.test(publicText));
    this.truth("WORK-07", "public page has no mutation controls", !/Approve|Reopen|Revoke|Create share link/i.test(publicText));
    this.truth("WORK-07", "public page hides private decision id", !publicText.includes(id));
    this.truth("WORK-07", "public page hides source mesh hash", !publicText.includes(decision.mesh_hash || "__no_mesh_hash__"));
    const publicScreenshot = await this.shot("WORK-07", publicPage, "public-share-read-only");

    await shareDialog.getByRole("button", { name: "Done" }).click();
    const revokeResponse = page.waitForResponse((response) =>
      response.request().method() === "DELETE" && new URL(response.url()).pathname === `/api/proxy/cost-decisions/${id}/share`,
    );
    await page.getByRole("button", { name: "Revoke", exact: true }).click();
    this.check("WORK-07", "share revoke HTTP", 200, (await revokeResponse).status());
    const revokedPayload = await this.publicRequest(`${apiUrl}/s/cost/${shortId}`);
    this.check("WORK-07", "revoked public API status", 404, revokedPayload.status);
    this.expected404Pages.add(publicPage);
    await publicPage.reload({ waitUntil: "domcontentloaded" });
    await publicPage.getByText("Cost decision not available", { exact: true }).waitFor();
    const ownerAfterRevoke = await this.decision(page, id);
    this.check("WORK-07", "owner share state revoked", { is_public: false, share_url: null }, { is_public: ownerAfterRevoke.is_public, share_url: ownerAfterRevoke.share_url });
    await publicContext.close();

    const screenshot = await this.shot("WORK-07", page, "exports-share-revoked");
    this.observations.exports = {
      paths: { json: jsonPath, csv: csvPath, pdf: pdfPath },
      filenames: { json: jsonFilename, csv: csvFilename, pdf: pdfFilename },
      governance,
      csvRows: rows.length,
      pdfBytes: (await readFile(pdfPath)).length,
      pdfContainsFullNote: pdfNote.split("\n").every((line) => pdfText.includes(line)),
      pdfContainsDispositionNote: pdfText.includes("Outcome note:") && pdfNote.split("\n").every((line) => pdfText.includes(line)),
      beforeHash,
      afterHash,
      share: { sharePath, shortId, publicScreenshot, forbiddenPaths, revokedStatus: revokedPayload.status },
      screenshot,
    };
  }

  async crossOrg(primary, secondary) {
    const aDecision = this.observations.decision.final;
    const aNotification = this.observations.notifications.first;
    const { page } = secondary;
    const ownDecisions = await this.request(page, "/api/proxy/cost-decisions?limit=100");
    const ownNotifications = await this.notifications(page);
    this.check("ROLE-04", "Org B decision list HTTP status", 200, ownDecisions.status);
    this.check("ROLE-04", "Org B decision count", 0, ownDecisions.body.cost_decisions.length);
    this.check("ROLE-04", "Org B notification count", 0, ownNotifications.length);

    const probes = [
      ["decision detail", "GET", `/api/proxy/cost-decisions/${aDecision.id}`, undefined],
      ["decision disposition", "PUT", `/api/proxy/cost-decisions/${aDecision.id}/disposition`, { disposition: "outside", note: null }],
      ["decision approve", "POST", `/api/proxy/cost-decisions/${aDecision.id}/approve`, { note: "foreign mutation" }],
      ["decision reopen", "DELETE", `/api/proxy/cost-decisions/${aDecision.id}/approve`, undefined],
      ["decision JSON", "GET", `/api/proxy/cost-decisions/${aDecision.id}/export.json`, undefined],
      ["decision CSV", "GET", `/api/proxy/cost-decisions/${aDecision.id}/export.csv`, undefined],
      ["decision PDF", "GET", `/api/proxy/cost-decisions/${aDecision.id}/pdf`, undefined],
      ["notification read", "POST", `/api/proxy/notifications/${aNotification.id}/read`, undefined],
      ["notification dismiss", "POST", `/api/proxy/notifications/${aNotification.id}/dismiss`, undefined],
      ["notification restore", "POST", `/api/proxy/notifications/${aNotification.id}/restore`, undefined],
    ];
    const statuses = {};
    this.expected404Pages.add(page);
    for (const [name, method, endpoint, data] of probes) {
      const response = await this.request(page, endpoint, { method, data });
      statuses[name] = response.status;
      this.check("ROLE-04", `${name} foreign status`, 404, response.status);
      const bodyText = Buffer.isBuffer(response.body) ? response.body.toString("utf8") : stableJson(response.body);
      this.check("ROLE-04", `${name} does not leak note`, false, bodyText.includes(specialNote));
      this.check("ROLE-04", `${name} does not leak filename`, false, bodyText.includes(aDecision.filename));
    }
    this.check("VER-07", "cross-org disposition mutation is denied", 404, statuses["decision disposition"]);
    this.check("VER-04", "cross-org notification dismiss is denied", 404, statuses["notification dismiss"]);
    this.check("VER-04", "cross-org notification restore is denied", 404, statuses["notification restore"]);

    await page.goto(`/cost-decisions/${aDecision.id}`, { waitUntil: "domcontentloaded" });
    const notFound = page.getByText("Cost decision not found", { exact: true }).first();
    await notFound.waitFor({ timeout: 20_000 });
    await page.waitForTimeout(500);
    this.expected404Pages.delete(page);
    this.check("ROLE-04", "foreign browser visible state", "Cost decision not found", await notFound.innerText());
    this.check("ROLE-04", "foreign browser does not show note", 0, await page.getByText(specialNote, { exact: true }).count());
    this.check("ROLE-04", "foreign browser does not show filename", 0, await page.getByText(aDecision.filename, { exact: true }).count());
    const ownerStillSeesDecision = await this.decision(primary.page, aDecision.id);
    this.check("ROLE-04", "negative probes do not mutate owner note", specialNote, ownerStillSeesDecision.approval_note);
    this.check("ROLE-04", "negative probes do not mutate owner disposition", "redesign", ownerStillSeesDecision.user_disposition);
    this.check("ROLE-04", "negative probes do not mutate owner disposition note", specialNote, ownerStillSeesDecision.disposition_note);
    const screenshot = await this.shot("ROLE-04", page, "foreign-id-not-found");
    this.observations.crossOrg = {
      orgBDecisionCount: ownDecisions.body.cost_decisions.length,
      orgBNotificationCount: ownNotifications.length,
      statuses,
      finalUrl: page.url(),
      visible: "Cost decision not found",
      screenshot,
    };
  }

  buildGoldenPaths() {
    const notification = this.observations.notifications;
    const decision = this.observations.decision;
    const exports = this.observations.exports;
    const crossOrg = this.observations.crossOrg;
    const session = this.observations.session;
    const disposition = this.observations.disposition;
    return {
      "VER-04": makeGoldenPathEvidence({
        id: "VER-04",
        status: "PASS",
        persona: "Signed-in cost analyst managing a durable workflow inbox",
        preconditions: ["Fresh organization with no notification rows.", "Real STEP verification and cost persistence are enabled locally."],
        actions: ["Upload two real STEP files through Verify.", "Reload one unread row, open it, and verify the declared Records destination.", "Dismiss the read row and prove its exact read/dismiss timestamps survive reload.", "Inject a restore failure, prove no mutation, retry, and prove restored active state survives reload.", "Mark the remaining row read with Mark all read and inspect its exact server timestamp.", "Inspect OpenAPI and cross-org denial for dismiss/restore."],
        observed: {
          url: `${appUrl}/notifications`,
          visible: [notification.first.title, notification.first.body, "Inbox (2)", "Dismissed (0)", "Records"],
          persisted: { first: notification.first, second: notification.second, transitions: notification.transitions },
          numeric: { emitted: 2, retained: 2, unreadAfter: 0, markAllAffected: 1, dismissRestoreEndpoints: 2, dismissedAfterFinal: 0, consoleErrorCount: 0, requestFailureCount: 0 },
          authorization: { ownerDismissRestoreAllowed: true, foreignDismissStatus: crossOrg.statuses["notification dismiss"], foreignRestoreStatus: crossOrg.statuses["notification restore"], existenceHidden: true },
          recovery: "Unread, read_at, and dismissed_at survived reloads. The injected restore failure changed nothing; retry restored the row with its original read timestamp, and both rows survived logout/login.",
        },
        screenshot: notification.screenshots.markAllScreenshot,
        consoleErrors: [],
        requestFailures: [],
        assertions: this.assertions["VER-04"],
      }),
      "VER-07": makeGoldenPathEvidence({
        id: "VER-07",
        status: "PASS",
        persona: "Accountable sourcing analyst recording the organization's human outcome beside computed evidence",
        preconditions: ["A real saved cost decision exists with an immutable result hash.", "The record starts approved with no four-way outcome or disposition note."],
        actions: ["Draft a disposition note, inject one failed create, prove no mutation, and retry.", "Edit the note with multiline Unicode/special characters and prove signoff reopens.", "Persist exactly 1000 characters, reject 1001, clear to empty, and recreate the special note.", "Exercise all four choices, including changing an approved choice.", "Reload and inspect the exact note in Records and full governance.", "Withdraw, reload, reopen Redesign with the note, approve, export, and attempt the same mutation from Org B."],
        observed: {
          url: `${appUrl}/cost-decisions/${disposition.id}`,
          visible: ["Make in-house", "Make outside", "Acquire capability", "Redesign", "Outcome note (optional)", specialNote, "RECORDED OUTCOME"],
          persisted: { choices: disposition.choices, noteTransitions: disposition.noteTransitions, selectedBeforeWithdraw: disposition.selectedBeforeWithdraw, withdrawnAt: disposition.withdrawnAt, reopenedAt: disposition.reopenedAt, finalDisposition: disposition.finalDisposition, finalDispositionNote: disposition.finalDispositionNote, finalDispositionUpdatedAt: disposition.finalDispositionUpdatedAt, artifactHash: disposition.artifactHash },
          numeric: { browserChoices: disposition.choices.length, dispositionNoteMaxLength: disposition.noteTransitions.longLength, overlongStatus: disposition.noteTransitions.overlongStatus, injectedFailureStatus: 503, foreignMutationStatus: crossOrg.statuses["decision disposition"], consoleErrorCount: 0, requestFailureCount: 0 },
          authorization: { ownerMutationsAllowed: true, foreignMutationStatus: crossOrg.statuses["decision disposition"], existenceHidden: true },
          recovery: "The failed note-bearing create changed nothing and retained its draft for retry; note edits and approved-choice changes reopened signoff; withdrawal survived reload and the final choice/note was recreated and signed.",
        },
        screenshot: disposition.screenshots.recordsScreenshot,
        consoleErrors: [],
        requestFailures: [],
        assertions: this.assertions["VER-07"],
      }),
      "WORK-05": makeGoldenPathEvidence({
        id: "WORK-05",
        status: "PASS",
        persona: "Cost analyst signing, revising, and reopening a saved sourcing record",
        preconditions: ["A real immutable cost-decision artifact exists in Org A.", "The analyst can approve and reopen organization records."],
        actions: ["Approve with an empty note and reopen.", "Create an ordinary note, then edit through the supported reopen/re-approve workflow.", "Persist multiline Unicode and HTML-like characters.", "Accept exactly 1000 characters, reject 1001, and reopen the page."],
        observed: {
          url: `${appUrl}/cost-decisions/${decision.id}`,
          visible: ["Decision governance", "Approved", specialNote],
          persisted: { finalStatus: decision.final.approval_status, finalNote: decision.final.approval_note, approvedAt: decision.final.approved_at, approvedBy: decision.final.approved_by_user_id, branches: decision.branches },
          numeric: { acceptedLength: 1000, rejectedLength: 1001, rejectedStatus: decision.branches.overlongStatus, consoleErrorCount: 0, requestFailureCount: 0 },
          authorization: "Approval and reopen used the signed-in analyst session and preserved the organization-scoped artifact.",
          recovery: "Every reopen cleared signer, timestamp, and note while preserving the cost result; the final note survived a full browser reload.",
        },
        screenshot: decision.screenshots.finalScreenshot,
        consoleErrors: [],
        requestFailures: [],
        assertions: this.assertions["WORK-05"],
      }),
      "WORK-07": makeGoldenPathEvidence({
        id: "WORK-07",
        status: "PASS",
        persona: "Sourcing reviewer exporting and sharing a signed decision package",
        preconditions: ["The saved cost decision is approved with exact multiline special-character approval and disposition notes.", "The final recorded outcome is Redesign.", "Browser downloads, an unauthenticated browser, and local PDF text inspection are available."],
        actions: ["Download and parse JSON, CSV, and PDF from the decision page.", "Create a public share and open it in an unauthenticated browser.", "Verify the page is read-only and strips private IDs/hashes.", "Revoke the share and prove both public HTML and API become unavailable."],
        observed: {
          url: `${appUrl}/cost-decisions/${decision.id}`,
          visible: ["JSON", "CSV", "Download PDF", "Redesign", specialNote],
          persisted: { governance: exports.governance, artifactHashBefore: exports.beforeHash, artifactHashAfter: exports.afterHash, artifactPaths: exports.paths, share: exports.share },
          numeric: { csvRows: exports.csvRows, pdfBytes: exports.pdfBytes, exportedFormats: 3, forbiddenPublicFields: exports.share.forbiddenPaths.length, revokedStatus: exports.share.revokedStatus, consoleErrorCount: 0, requestFailureCount: 0 },
          authorization: "All three owner-scoped downloads succeeded for Org A and returned 404 for Org B.",
          recovery: "Exports left the immutable decision hash unchanged; revocation immediately returned the public HTML and API to an unavailable state while the owner record remained intact.",
        },
        screenshot: exports.screenshot,
        consoleErrors: [],
        requestFailures: [],
        assertions: this.assertions["WORK-07"],
      }),
      "ROLE-04": makeGoldenPathEvidence({
        id: "ROLE-04",
        status: "PASS",
        persona: "Analyst in an unrelated organization attempting foreign record access",
        preconditions: ["Org A owns notification and decision IDs.", "Org B is a separately signed-up organization with empty collections."],
        actions: ["List Org B's own collections.", "Probe Org A detail, disposition, approve, reopen, JSON, CSV, PDF, and notification read/dismiss/restore endpoints.", "Open Org A's decision URL in Org B's browser."],
        observed: {
          url: crossOrg.finalUrl,
          visible: [crossOrg.visible],
          persisted: { orgBDecisionCount: crossOrg.orgBDecisionCount, orgBNotificationCount: crossOrg.orgBNotificationCount, ownerApprovalNoteAfterProbes: specialNote, ownerDispositionAfterProbes: "redesign", ownerDispositionNoteAfterProbes: specialNote },
          numeric: { foreignProbes: Object.keys(crossOrg.statuses).length, statuses: crossOrg.statuses, consoleErrorCount: 0, requestFailureCount: 0 },
          authorization: { existenceHiddenAs404: Object.values(crossOrg.statuses).every((status) => status === 404), leakedOwnerValues: 0 },
          recovery: "Org A's exact approval note remained unchanged after every negative Org B probe.",
        },
        screenshot: crossOrg.screenshot,
        consoleErrors: [],
        requestFailures: [],
        assertions: this.assertions["ROLE-04"],
      }),
      "FAIL-09": makeGoldenPathEvidence({
        id: "FAIL-09",
        status: "PASS",
        persona: "Returning analyst recovering after explicit session revocation",
        preconditions: ["Org A has two active read notifications with captured read_at timestamps after one dismiss/restore cycle.", "A copy of the pre-logout session cookie is retained only for the negative replay check."],
        actions: ["Sign out through Account.", "Replay the copied old cookie against a protected page and notifications API.", "Log in again and reopen Notifications."],
        observed: {
          url: session.finalUrl,
          visible: ["Log in to ProofShape", notification.first.title, notification.second.title],
          persisted: { firstReadAt: session.firstReadAt, secondReadAt: session.secondReadAt, dismissedCount: session.dismissedCount, sessionsRevoked: session.sessionsRevoked },
          numeric: { logoutStatus: session.logoutStatus, replayApiStatus: session.replayApiStatus, activeRowsAfterLogin: 2, dismissedRowsAfterLogin: session.dismissedCount, consoleErrorCount: 0, requestFailureCount: 0 },
          authorization: { copiedSessionRejected: session.replayApiStatus === 401, freshLoginGranted: true },
          recovery: "Fresh credentials restored the authorized workspace and both exact notification read timestamps.",
        },
        screenshot: session.screenshot,
        consoleErrors: [],
        requestFailures: [],
        assertions: this.assertions["FAIL-09"],
      }),
    };
  }

  async run() {
    await this.init();
    try {
      const primary = await this.newIdentity("notification-decision-a", 71);
      await this.notificationLifecycle(primary);
      await this.sessionRecovery(primary);
      await this.decisionNotes(primary);
      await this.fourWayDisposition(primary);
      await this.exports(primary);
      const secondary = await this.newIdentity("notification-decision-b", 72);
      await this.crossOrg(primary, secondary);
      this.check("ROLE-04", "unexpected console errors", 0, this.consoleErrors.length);
      this.check("ROLE-04", "unexpected request failures", 0, this.requestFailures.length);
      const goldenPaths = this.buildGoldenPaths();
      const validation = validateGoldenPathMap(requiredIds, goldenPaths);
      if (validation.valid !== validation.total) fail(`structured evidence invalid: ${stableJson(validation.problems)}`);
      const report = {
        schemaVersion: 1,
        suite: "notification-decision-golden-matrix",
        runId,
        generatedAt: new Date().toISOString(),
        status: "PASS",
        buildIdentity: captureBuildIdentity(repoRoot),
        runtime: {
          appUrl,
          apiUrl,
          externalSaaSRequired: false,
          clientIpMode: "run-scoped-rfc3849",
          identityIps: [primary.clientIp, secondary.clientIp],
        },
        releaseEvidence: { schemaVersion: 1, goldenPaths, validation },
        branchMatrix: {
          notifications: ["unread", "reload-unread", "open/read", "destination", "reload-read", "dismiss", "reload-dismissed", "restore-failure-no-mutation", "restore-retry", "reload-restored", "logout-login", "mark-all", "cross-org-dismiss", "cross-org-restore"],
          dispositions: ["note-create-error-no-mutation", "note-create-retry", "note-edit-reopens-signoff", "note-empty", "note-special-characters", "note-1000-character", "note-1001-rejected", "make-in-house", "make-outside", "acquire-capability", "redesign", "reload", "Records-note", "full-governance-note", "approved-choice-reopens", "withdraw", "reload-withdrawn", "reopen-after-withdraw", "cross-org"],
          decisionNotes: ["empty", "ordinary-create", "edit-via-reopen", "multiline", "special-characters", "1000-character", "1001-rejected", "page-reopen", "JSON-export", "CSV-export", "PDF-export", "disposition-note-export", "cross-org"],
        },
        diagnostics: { consoleErrors: this.consoleErrors, requestFailures: this.requestFailures },
        coverageGaps: [],
      };
      await mkdir(outputRoot, { recursive: true });
      await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
      await writeFile(markdownPath, markdown(report));
      await primary.context.close();
      await secondary.context.close();
      return report;
    } finally {
      await this.browser?.close();
    }
  }
}

const matrix = new Matrix();
matrix.run().then((report) => {
  process.stdout.write(`${JSON.stringify({ status: report.status, reportPath, markdownPath, valid: report.releaseEvidence.validation.valid, total: report.releaseEvidence.validation.total, assertions: Object.fromEntries(requiredIds.map((id) => [id, report.releaseEvidence.goldenPaths[id].assertions.length])) }, null, 2)}\n`);
}).catch((error) => {
  process.stderr.write(`${error?.stack || error}\n`);
  process.exitCode = 1;
});
