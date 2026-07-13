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
    this.expected404Pages = new Set();
    this.expectedFailurePages = new Set();
    this.shotIndex = 0;
    this.observations = {};
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
      const expected404 = this.expected404Pages.has(page) && /status of 404 \(Not Found\)/i.test(text);
      const expectedFailure = this.expectedFailurePages.has(page) && /status of 503 \(Service Unavailable\)/i.test(text);
      if (expected404 || expectedFailure || /favicon\.ico|ResizeObserver loop limit exceeded/i.test(text)) return;
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
    const context = await this.browser.newContext({
      baseURL: appUrl,
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
      acceptDownloads: true,
      extraHTTPHeaders: { "x-real-ip": `198.51.100.${ipSuffix}` },
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
    return { context, page, email };
  }

  async shot(id, page, label) {
    this.shotIndex += 1;
    const filename = `${String(this.shotIndex).padStart(2, "0")}-${id}-${label}.png`;
    const destination = path.join(screenshotDir, filename);
    await page.screenshot({ path: destination, fullPage: true });
    return destination;
  }

  async request(context, endpoint, options = {}) {
    const response = await context.request.fetch(new URL(endpoint, appUrl).href, {
      method: options.method || "GET",
      data: options.data,
      headers: options.headers,
      timeout: options.timeout || 60_000,
      failOnStatusCode: false,
    });
    const bytes = await response.body();
    const contentType = response.headers()["content-type"] || "";
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
    return { status: response.status(), headers: response.headers(), body, bytes };
  }

  async decision(context, id) {
    const response = await this.request(context, `/api/proxy/cost-decisions/${id}`);
    if (response.status !== 200) fail(`GET decision ${id} returned ${response.status}`);
    return response.body;
  }

  async notifications(context, { unread = false } = {}) {
    const response = await this.request(
      context,
      `/api/proxy/notifications?status=all&unread=${unread ? "true" : "false"}&limit=100`,
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
    const detail = await this.decision(identity.context, cost.saved.id);
    let notification = null;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      notification = (await this.notifications(identity.context)).find(
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
    this.check("VER-04", "notification and decision creation timestamp", first.detail.created_at, firstRow.created_at);

    const { page, context } = identity;
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
    await page.getByText(firstRow.title, { exact: true }).click();
    const readResponse = await readResponsePromise;
    const readAfter = Date.now();
    this.check("VER-04", "mark-one HTTP status", 200, readResponse.status());
    const readPayload = await readResponse.json();
    const readNotification = readPayload.notification;
    this.check("VER-04", "mark-one response id", firstRow.id, readNotification.id);
    this.check("VER-04", "mark-one response is_read", true, readNotification.is_read);
    this.truth(
      "VER-04",
      "mark-one timestamp bounded by browser action",
      isoMs(readNotification.read_at) >= readBefore - 1_000 && isoMs(readNotification.read_at) <= readAfter + 1_000,
    );
    await page.waitForURL((url) => url.pathname === "/verify" && url.searchParams.get("screen") === "records", { timeout: 20_000 });
    await page.getByRole("heading", { name: "Records", exact: true }).waitFor({ timeout: 20_000 });
    this.check("VER-04", "notification opens declared browser destination", `${appUrl}/verify?screen=records`, page.url());
    this.check("VER-04", "destination visible heading", "Records", await page.getByRole("heading", { name: "Records", exact: true }).innerText());

    let persisted = (await this.notifications(context)).find((item) => item.id === firstRow.id);
    this.check("VER-04", "persisted mark-one is_read", true, persisted.is_read);
    this.check("VER-04", "persisted mark-one read_at", readNotification.read_at, persisted.read_at);
    this.check("VER-04", "mark-one preserves status", "open", persisted.status);

    await page.goto("/notifications", { waitUntil: "domcontentloaded" });
    await page.getByText("You're all caught up.", { exact: true }).waitFor({ timeout: 15_000 });
    const readReloadScreenshot = await this.shot("VER-04", page, "read-state-after-return");

    const second = await this.uploadDecision(
      identity,
      `notification-secondary-${runId}.stl`,
      secondFixturePath,
    );
    const secondRow = second.notification;
    await page.goto("/notifications", { waitUntil: "domcontentloaded" });
    await page.getByText(secondRow.title, { exact: true }).waitFor({ timeout: 15_000 });
    const unreadBeforeMarkAll = await this.notifications(context, { unread: true });
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
    await page.getByText("You're all caught up.", { exact: true }).waitFor({ timeout: 15_000 });
    const markAllScreenshot = await this.shot("VER-04", page, "after-mark-all");
    const allAfter = await this.notifications(context);
    const secondPersisted = allAfter.find((item) => item.id === secondRow.id);
    this.check("VER-04", "mark-all persisted second row", true, secondPersisted.is_read);
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
    this.check("VER-04", "dismiss/restore endpoint count", 0, dismissRestorePaths.length);
    this.observations.notifications = {
      first: persisted,
      second: secondPersisted,
      notificationPaths,
      dismissRestoreSupported: false,
      screenshots: { unreadScreenshot, readReloadScreenshot, markAllScreenshot },
      firstDecision: first,
      secondDecision: second,
    };
  }

  async sessionRecovery(identity) {
    const { page, context, email } = identity;
    const expectedRows = this.observations.notifications;
    await page.goto("/notifications", { waitUntil: "domcontentloaded" });
    await page.getByText("You're all caught up.", { exact: true }).waitFor({ timeout: 15_000 });
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
    const replayApi = await this.request(replayContext, "/api/proxy/notifications?status=all&unread=false&limit=100");
    this.check("FAIL-09", "copied pre-logout cookie API status", 401, replayApi.status);
    await replayContext.close();

    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: /^Log in$/ }).click();
    await page.waitForURL((url) => url.pathname !== "/login", { timeout: 30_000 });
    await page.goto("/notifications", { waitUntil: "domcontentloaded" });
    this.check("FAIL-09", "post-login empty inbox copy", "You're all caught up.", await page.getByText("You're all caught up.", { exact: true }).innerText());
    const afterLogin = await this.notifications(context);
    const firstAfter = afterLogin.find((item) => item.id === expectedRows.first.id);
    const secondAfter = afterLogin.find((item) => item.id === expectedRows.second.id);
    this.check("FAIL-09", "first read_at survives logout/login", expectedRows.first.read_at, firstAfter.read_at);
    this.check("FAIL-09", "second read_at survives logout/login", expectedRows.second.read_at, secondAfter.read_at);
    this.check("FAIL-09", "first read status survives logout/login", true, firstAfter.is_read);
    this.check("FAIL-09", "second read status survives logout/login", true, secondAfter.is_read);
    const screenshot = await this.shot("FAIL-09", page, "reauthenticated-read-state");
    this.observations.session = {
      logoutStatus: logoutEvidence.status,
      sessionsRevoked: logoutEvidence.body.sessionsRevoked,
      replayApiStatus: replayApi.status,
      finalUrl: page.url(),
      firstReadAt: firstAfter.read_at,
      secondReadAt: secondAfter.read_at,
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
    const detail = await this.decision(identity.context, id);
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
    const detail = await this.decision(identity.context, id);
    this.check("WORK-05", `${branch} reopened status`, "unreviewed", detail.approval_status);
    this.check("WORK-05", `${branch} cleared note`, null, detail.approval_note);
    this.check("WORK-05", `${branch} cleared timestamp`, null, detail.approved_at);
    this.check("WORK-05", `${branch} cleared signer`, null, detail.approved_by_user_id);
    return detail;
  }

  async decisionNotes(identity) {
    const { page, context } = identity;
    const id = this.observations.notifications.firstDecision.detail.id;
    await page.goto(`/cost-decisions/${id}`, { waitUntil: "domcontentloaded" });
    await page.getByText("Decision governance", { exact: true }).waitFor({ timeout: 20_000 });
    const initial = await this.decision(context, id);
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
    const overlong = await this.request(context, `/api/proxy/cost-decisions/${id}/approve`, {
      method: "POST",
      data: { note: `${longNote}X` },
    });
    this.check("WORK-05", "1001-character API status", 422, overlong.status);
    this.truth(
      "WORK-05",
      "1001-character response names 1000-character limit",
      /1000/.test(stableJson(overlong.body)),
    );
    const afterOverlong = await this.decision(context, id);
    this.check("WORK-05", "rejected 1001-character note leaves exact prior note", longNote, afterOverlong.approval_note);
    this.check("WORK-05", "rejected 1001-character note leaves timestamp", long.approved_at, afterOverlong.approved_at);
    await this.reopenViaBrowser(identity, id, "1000-character-note-final-edit");

    const final = await this.approveViaBrowser(identity, id, specialNote, "final-special-note");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("approval-note").waitFor({ timeout: 15_000 });
    this.check("WORK-05", "special note survives page reopen", specialNote, await page.getByTestId("approval-note").innerText());
    const reopenedDetail = await this.decision(context, id);
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

  async chooseDispositionViaBrowser(identity, id, clickedKey, expectedDisposition, expectedLabel, branch) {
    const { page, context } = identity;
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
    const detail = await this.decision(context, id);
    this.check("VER-07", `${branch} response disposition`, expectedDisposition, payload.user_disposition);
    this.check("VER-07", `${branch} persisted disposition`, expectedDisposition, detail.user_disposition);
    this.check("VER-07", `${branch} response label`, expectedLabel, payload.user_disposition_label);
    this.check("VER-07", `${branch} persisted label`, expectedLabel, detail.user_disposition_label);
    this.check("VER-07", `${branch} response/persisted timestamp`, payload.disposition_updated_at, detail.disposition_updated_at);
    this.check("VER-07", `${branch} response/persisted actor`, payload.disposition_updated_by_user_id, detail.disposition_updated_by_user_id);
    this.truth(
      "VER-07",
      `${branch} timestamp bounded by browser action`,
      isoMs(detail.disposition_updated_at) >= before - 1_000 && isoMs(detail.disposition_updated_at) <= after + 1_000,
    );
    this.check("VER-07", `${branch} selected browser state`, expectedDisposition === clickedKey ? "true" : "false", await page.getByTestId(`record-disposition-${clickedKey}`).getAttribute("aria-pressed"));
    const panelText = await page.getByTestId("cost-decision-disposition").innerText();
    this.truth(
      "VER-07",
      `${branch} visible governance state`,
      expectedLabel ? panelText.includes(expectedLabel) : panelText.includes("Choose what the organization will do with this part."),
    );
    return detail;
  }

  async approveDispositionSignoff(identity, id, note, branch) {
    const { page, context } = identity;
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
    const detail = await this.decision(context, id);
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
    const { page, context } = identity;
    const id = this.observations.decision.final.id;
    const filename = this.observations.decision.final.filename;
    const artifactHash = this.observations.decision.artifactHash;
    await page.goto(`/cost-decisions/${id}`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("cost-decision-disposition").waitFor({ timeout: 20_000 });
    const initial = await this.decision(context, id);
    this.check("VER-07", "initial choice is undecided", null, initial.user_disposition);
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
    const failedResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "PUT" && response.url().includes(`/cost-decisions/${id}/disposition`),
      { timeout: 20_000 },
    );
    await page.getByTestId("record-disposition-inhouse").click();
    const failedResponse = await failedResponsePromise;
    this.check("VER-07", "injected choice failure HTTP status", 503, failedResponse.status());
    await page.getByText("Injected disposition outage", { exact: false }).first().waitFor({ timeout: 15_000 });
    const afterFailure = await this.decision(context, id);
    this.check("VER-07", "failed choice leaves persisted outcome", null, afterFailure.user_disposition);
    this.check("VER-07", "failed choice leaves approved status", "approved", afterFailure.approval_status);
    this.check("VER-07", "failed choice leaves immutable artifact", artifactHash, sha256(afterFailure.result));
    this.check("VER-07", "failed choice remains retryable", false, await page.getByTestId("record-disposition-inhouse").isDisabled());
    const errorScreenshot = await this.shot("VER-07", page, "injected-error-retryable");
    await page.waitForTimeout(500);
    this.expectedFailurePages.delete(page);
    await page.unroute(routePattern, injectedFailure);

    const choices = [];
    const inhouse = await this.chooseDispositionViaBrowser(identity, id, "inhouse", "inhouse", "Make in-house", "make-in-house");
    this.check("VER-07", "make-in-house reopens prior approval", "unreviewed", inhouse.approval_status);
    this.check("VER-07", "make-in-house clears prior approval note", null, inhouse.approval_note);
    this.check("VER-07", "make-in-house preserves immutable artifact", artifactHash, sha256(inhouse.result));
    choices.push({ key: "inhouse", label: "Make in-house", updatedAt: inhouse.disposition_updated_at });

    const signedInhouse = await this.approveDispositionSignoff(identity, id, "Approved in-house outcome.", "in-house signoff");
    this.check("VER-07", "approval keeps in-house choice", "inhouse", signedInhouse.user_disposition);
    const outside = await this.chooseDispositionViaBrowser(identity, id, "outside", "outside", "Make outside", "make-outside");
    this.check("VER-07", "changed approved choice reopens signoff", "unreviewed", outside.approval_status);
    this.check("VER-07", "changed approved choice clears signer", null, outside.approved_by_user_id);
    this.check("VER-07", "changed approved choice clears timestamp", null, outside.approved_at);
    this.check("VER-07", "changed approved choice clears note", null, outside.approval_note);
    this.check("VER-07", "make-outside preserves immutable artifact", artifactHash, sha256(outside.result));
    choices.push({ key: "outside", label: "Make outside", updatedAt: outside.disposition_updated_at });

    const acquire = await this.chooseDispositionViaBrowser(identity, id, "acquire", "acquire", "Acquire capability", "acquire-capability");
    this.check("VER-07", "acquire preserves immutable artifact", artifactHash, sha256(acquire.result));
    choices.push({ key: "acquire", label: "Acquire capability", updatedAt: acquire.disposition_updated_at });
    const redesign = await this.chooseDispositionViaBrowser(identity, id, "redesign", "redesign", "Redesign", "redesign");
    this.check("VER-07", "redesign preserves immutable artifact", artifactHash, sha256(redesign.result));
    choices.push({ key: "redesign", label: "Redesign", updatedAt: redesign.disposition_updated_at });
    this.truth("VER-07", "all four choice timestamps are distinct", new Set(choices.map((choice) => choice.updatedAt)).size === 4);

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("cost-decision-disposition").waitFor({ timeout: 20_000 });
    this.check("VER-07", "redesign survives detail reload", "true", await page.getByTestId("record-disposition-redesign").getAttribute("aria-pressed"));
    this.truth("VER-07", "full governance shows Redesign", (await page.getByTestId("cost-decision-disposition").innerText()).includes("Redesign"));
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
    const recordsScreenshot = await this.shot("VER-07", page, "records-redesign-visible");

    await page.goto(`/cost-decisions/${id}`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("cost-decision-disposition").waitFor({ timeout: 20_000 });
    const withdrawn = await this.chooseDispositionViaBrowser(identity, id, "redesign", null, null, "withdraw-redesign");
    this.check("VER-07", "withdraw clears disposition note", null, withdrawn.disposition_note);
    this.check("VER-07", "withdraw preserves immutable artifact", artifactHash, sha256(withdrawn.result));
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("cost-decision-disposition").waitFor({ timeout: 20_000 });
    this.truth("VER-07", "withdraw survives detail reload", (await page.getByTestId("cost-decision-disposition").innerText()).includes("Choose what the organization will do with this part."));
    const persistedWithdrawn = await this.decision(context, id);
    this.check("VER-07", "withdraw survives API reopen", null, persistedWithdrawn.user_disposition);
    this.check("VER-07", "withdraw timestamp survives reload", withdrawn.disposition_updated_at, persistedWithdrawn.disposition_updated_at);

    const restored = await this.approveDispositionSignoff(identity, id, specialNote, "post-disposition export signoff");
    this.check("VER-07", "post-disposition signoff remains withdrawn", null, restored.user_disposition);
    this.check("VER-07", "post-disposition signoff preserves immutable artifact", artifactHash, sha256(restored.result));
    this.observations.decision.final = restored;
    this.observations.disposition = {
      id,
      choices,
      errorRecovered: true,
      selectedBeforeWithdraw: "redesign",
      finalDisposition: restored.user_disposition,
      finalDispositionUpdatedAt: restored.disposition_updated_at,
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
    const { page, context } = identity;
    const decision = this.observations.decision.final;
    const id = decision.id;
    await page.goto(`/cost-decisions/${id}`, { waitUntil: "domcontentloaded" });
    await page.getByTestId("approval-note").waitFor({ timeout: 20_000 });
    const beforeHash = sha256((await this.decision(context, id)).result);

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
    this.check("WORK-07", "JSON carries withdrawn disposition", null, governance.user_disposition);
    const jsonResult = { ...json };
    delete jsonResult.governance;
    this.check("WORK-07", "JSON retains exact immutable cost artifact", beforeHash, sha256(jsonResult));
    this.check("WORK-07", "CSV row count matches result estimates", decision.result.estimates.length, rows.length);
    this.truth("WORK-07", "CSV every row is approved", rows.every((row) => row.approval_status === "approved"));
    this.truth("WORK-07", "CSV every row has exact signer", rows.every((row) => row.approved_by_user_id === String(decision.approved_by_user_id)));
    this.truth("WORK-07", "CSV every row has exact timestamp", rows.every((row) => row.approved_at === decision.approved_at));
    this.truth("WORK-07", "CSV every row has exact multiline/special note", rows.every((row) => row.approval_note === specialNote));
    this.truth("WORK-07", "CSV every row carries withdrawn disposition", rows.every((row) => row.user_disposition === ""));
    this.truth("WORK-07", "PDF contains Decision Governance heading", pdfText.includes("Decision Governance"));
    this.truth("WORK-07", "PDF contains approved status", /Status:\s+approved/.test(pdfText));
    this.truth("WORK-07", "PDF carries Not decided disposition", /Recorded outcome:\s+Not decided/.test(pdfText));
    this.truth("WORK-07", "PDF contains exact signer", pdfText.includes(`Signed by user: ${decision.approved_by_user_id}`));
    this.truth("WORK-07", "PDF contains exact approval timestamp", pdfText.includes(decision.approved_at));
    const pdfNote = specialNote.replaceAll("\ufe0f", "");
    this.truth("WORK-07", "PDF contains first special-note line", pdfText.includes(pdfNote.split("\n")[0]));
    this.truth("WORK-07", "PDF contains second special-note line", pdfText.includes(specialNote.split("\n")[1]));
    const afterHash = sha256((await this.decision(context, id)).result);
    this.check("WORK-07", "exports do not mutate decision artifact", beforeHash, afterHash);
    this.truth("WORK-07", "JSON download filename is explicit", /-cost\.json$/.test(jsonFilename));
    this.truth("WORK-07", "CSV download filename is explicit", /-cost\.csv$/.test(csvFilename));
    this.truth("WORK-07", "PDF download filename is explicit", /-cost-report\.pdf$/.test(pdfFilename));
    const screenshot = await this.shot("WORK-07", page, "exports-complete");
    this.observations.exports = {
      paths: { json: jsonPath, csv: csvPath, pdf: pdfPath },
      filenames: { json: jsonFilename, csv: csvFilename, pdf: pdfFilename },
      governance,
      csvRows: rows.length,
      pdfBytes: (await readFile(pdfPath)).length,
      pdfContainsFullNote: pdfNote.split("\n").every((line) => pdfText.includes(line)),
      beforeHash,
      afterHash,
      screenshot,
    };
  }

  async crossOrg(primary, secondary) {
    const aDecision = this.observations.decision.final;
    const aNotification = this.observations.notifications.first;
    const { context, page } = secondary;
    const ownDecisions = await this.request(context, "/api/proxy/cost-decisions?limit=100");
    const ownNotifications = await this.notifications(context);
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
    ];
    const statuses = {};
    for (const [name, method, endpoint, data] of probes) {
      const response = await this.request(context, endpoint, { method, data });
      statuses[name] = response.status;
      this.check("ROLE-04", `${name} foreign status`, 404, response.status);
      const bodyText = Buffer.isBuffer(response.body) ? response.body.toString("utf8") : stableJson(response.body);
      this.check("ROLE-04", `${name} does not leak note`, false, bodyText.includes(specialNote));
      this.check("ROLE-04", `${name} does not leak filename`, false, bodyText.includes(aDecision.filename));
    }
    this.check("VER-07", "cross-org disposition mutation is denied", 404, statuses["decision disposition"]);

    this.expected404Pages.add(page);
    await page.goto(`/cost-decisions/${aDecision.id}`, { waitUntil: "domcontentloaded" });
    const notFound = page.getByText("Cost decision not found", { exact: true }).first();
    await notFound.waitFor({ timeout: 20_000 });
    await page.waitForTimeout(500);
    this.expected404Pages.delete(page);
    this.check("ROLE-04", "foreign browser visible state", "Cost decision not found", await notFound.innerText());
    this.check("ROLE-04", "foreign browser does not show note", 0, await page.getByText(specialNote, { exact: true }).count());
    this.check("ROLE-04", "foreign browser does not show filename", 0, await page.getByText(aDecision.filename, { exact: true }).count());
    const ownerStillSeesDecision = await this.decision(primary.context, aDecision.id);
    this.check("ROLE-04", "negative probes do not mutate owner note", specialNote, ownerStillSeesDecision.approval_note);
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
        actions: ["Upload two real STEP files through Verify.", "Reload one unread row, open it, and verify the declared Records destination.", "Mark the remaining row read with Mark all read and inspect persisted API state.", "Inspect OpenAPI for dismiss/restore support."],
        observed: {
          url: `${appUrl}/notifications`,
          visible: [notification.first.title, notification.first.body, "Records", "You're all caught up."],
          persisted: { first: notification.first, second: notification.second },
          numeric: { emitted: 2, retained: 2, unreadAfter: 0, markAllAffected: 1, consoleErrorCount: 0, requestFailureCount: 0 },
          authorization: "Both rows were available only through Org A's authenticated session; ROLE-04 proves foreign IDs return 404.",
          recovery: "Unread survived reload; exact read_at values survived navigation and login. Dismiss/restore is explicitly unsupported by the current UI and OpenAPI.",
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
        preconditions: ["A real saved cost decision exists with an immutable result hash.", "The record starts approved and has no recorded four-way outcome."],
        actions: ["Inject one failed outcome save and retry through the browser.", "Select Make in-house, approve it, then change the approved choice to Make outside.", "Select Acquire capability and Redesign, reload, and inspect Records plus full governance.", "Withdraw Redesign and verify reload/API persistence.", "Attempt the same disposition mutation from Org B."],
        observed: {
          url: `${appUrl}/cost-decisions/${disposition.id}`,
          visible: ["Make in-house", "Make outside", "Acquire capability", "Redesign", "RECORDED OUTCOME", "Not decided"],
          persisted: { choices: disposition.choices, selectedBeforeWithdraw: disposition.selectedBeforeWithdraw, finalDisposition: disposition.finalDisposition, finalDispositionUpdatedAt: disposition.finalDispositionUpdatedAt, artifactHash: disposition.artifactHash },
          numeric: { browserChoices: disposition.choices.length, injectedFailureStatus: 503, foreignMutationStatus: crossOrg.statuses["decision disposition"], consoleErrorCount: 0, requestFailureCount: 0 },
          authorization: { ownerMutationsAllowed: true, foreignMutationStatus: crossOrg.statuses["decision disposition"], existenceHidden: true },
          recovery: "The failed save changed nothing and the same enabled control succeeded on retry; changing an approved choice reopened signoff; withdrawal survived reload.",
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
        persona: "Sourcing reviewer exporting a signed decision package",
        preconditions: ["The saved cost decision is approved with an exact multiline special-character note.", "Browser downloads and local PDF text inspection are available."],
        actions: ["Download JSON, CSV, and PDF from the decision page.", "Parse each downloaded artifact.", "Compare exported governance and cost values with the persisted API record."],
        observed: {
          url: `${appUrl}/cost-decisions/${decision.id}`,
          visible: ["JSON", "CSV", "Download PDF", specialNote],
          persisted: { governance: exports.governance, artifactHashBefore: exports.beforeHash, artifactHashAfter: exports.afterHash, artifactPaths: exports.paths },
          numeric: { csvRows: exports.csvRows, pdfBytes: exports.pdfBytes, exportedFormats: 3, consoleErrorCount: 0, requestFailureCount: 0 },
          authorization: "All three owner-scoped downloads succeeded for Org A and returned 404 for Org B.",
          recovery: "Generating exports left the immutable decision artifact hash unchanged.",
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
        actions: ["List Org B's own collections.", "Probe Org A detail, disposition, approve, reopen, JSON, CSV, PDF, and notification-read endpoints.", "Open Org A's decision URL in Org B's browser."],
        observed: {
          url: crossOrg.finalUrl,
          visible: [crossOrg.visible],
          persisted: { orgBDecisionCount: crossOrg.orgBDecisionCount, orgBNotificationCount: crossOrg.orgBNotificationCount, ownerNoteAfterProbes: specialNote },
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
        preconditions: ["Org A has two read notifications with captured read_at timestamps.", "A copy of the pre-logout session cookie is retained only for the negative replay check."],
        actions: ["Sign out through Account.", "Replay the copied old cookie against a protected page and notifications API.", "Log in again and reopen Notifications."],
        observed: {
          url: session.finalUrl,
          visible: ["Log in to ProofShape", "You're all caught up."],
          persisted: { firstReadAt: session.firstReadAt, secondReadAt: session.secondReadAt, sessionsRevoked: session.sessionsRevoked },
          numeric: { logoutStatus: session.logoutStatus, replayApiStatus: session.replayApiStatus, consoleErrorCount: 0, requestFailureCount: 0 },
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
        runtime: { appUrl, apiUrl, externalSaaSRequired: false },
        releaseEvidence: { schemaVersion: 1, goldenPaths, validation },
        branchMatrix: {
          notifications: ["unread", "reload-unread", "open/read", "destination", "reload-read", "logout-login", "mark-all", "dismiss-unsupported", "restore-unsupported", "cross-org"],
          dispositions: ["error-no-mutation", "retry", "make-in-house", "make-outside", "acquire-capability", "redesign", "reload", "Records", "full-governance", "approved-choice-reopens", "withdraw", "cross-org"],
          decisionNotes: ["empty", "ordinary-create", "edit-via-reopen", "multiline", "special-characters", "1000-character", "1001-rejected", "page-reopen", "JSON-export", "CSV-export", "PDF-export", "cross-org"],
        },
        diagnostics: { consoleErrors: this.consoleErrors, requestFailures: this.requestFailures },
        coverageGaps: [
          "Notifications expose read-one and read-all only; dismiss and restore have no browser control or API endpoint, so those branches are reported unsupported rather than passed.",
          "The four-way disposition API persists and exports an optional disposition note, but current browser controls expose no create/edit field and submit null; VER-07 proves the four choices, not disposition-note authoring.",
        ],
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
