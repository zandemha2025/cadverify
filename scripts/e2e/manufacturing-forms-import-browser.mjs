import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { access, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  captureVisualStep,
  makeGoldenPathEvidence,
  validateGoldenPathEvidence,
} from "./golden-path-evidence.mjs";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");

export const MANUFACTURING_FORM_IMPORT_CASE_IDS = Object.freeze([
  "MFI-01",
  "MFI-02",
  "MFI-03",
  "MFI-04",
  "MFI-05",
  "MFI-06",
  "MFI-07",
]);

export const MACHINE_CSV_HEADER = Object.freeze([
  "process",
  "name",
  "count",
  "max_workpiece_kg",
  "hourly_rate_usd",
  "capital_frac",
  "materials",
  "material_thickness_map",
  "capabilities",
  "notes",
]);

export const MANIFEST_CSV_HEADER = Object.freeze([
  "part_id",
  "description",
  "material_class",
  "program",
  "parent_assembly",
  "units_per_parent",
  "annual_volume",
  "quantity",
  "region",
  "source",
  "notes",
]);

export const GROUND_TRUTH_CSV_HEADER = Object.freeze([
  "part_id",
  "process",
  "quantity",
  "actual_unit_cost_usd",
]);

export const REQUIRED_RESPONSE_STATUSES = Object.freeze({
  authMutation: 200,
  machineCreate: 201,
  machineEdit: 200,
  machineDelete: 200,
  machineImportValid: 200,
  machineImportMixed: 200,
  manifestImport: 200,
  groundTruthImport: 200,
});

const MACHINE_IMPORT_PATH = "/api/proxy/machine-inventory/import";
const MACHINE_LIST_PATH = "/api/proxy/machine-inventory?limit=500";
const MANIFEST_IMPORT_PATH = "/api/proxy/manifest/import";
const MANIFEST_LIST_PATH = "/api/proxy/manifest?limit=500";
const MANIFEST_COVERAGE_PATH = "/api/proxy/manifest/coverage";
const GROUND_TRUTH_IMPORT_PATH = "/api/proxy/ground-truth/import";
const GROUND_TRUTH_LIST_PATH = "/api/proxy/ground-truth";

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function normalizedText(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function csvDocument(header, rows) {
  return `${header.join(",")}\n${rows.map((row) => row.map(csvCell).join(",")).join("\n")}\n`;
}

function uploadPayload(name, text) {
  return { name, mimeType: "text/csv", buffer: Buffer.from(text, "utf8") };
}

function assertion(name, expected, actual, pass) {
  return { name, expected, actual, pass: Boolean(pass) };
}

export function assertExactImportSummary(actual, expected, label = "CSV import") {
  assert.ok(actual && typeof actual === "object", `${label} response body is missing`);
  for (const field of ["imported", "skipped", "total"]) {
    assert.equal(actual[field], expected[field], `${label} ${field}`);
  }
  if (Object.hasOwn(expected, "updated")) {
    assert.equal(actual.updated, expected.updated, `${label} updated`);
  }
  assert.ok(Array.isArray(actual.errors), `${label} errors must be an array`);
  if (Object.hasOwn(expected, "errorCount")) {
    assert.equal(actual.errors.length, expected.errorCount, `${label} error count`);
  }
  return {
    imported: actual.imported,
    ...(Object.hasOwn(expected, "updated") ? { updated: actual.updated } : {}),
    skipped: actual.skipped,
    total: actual.total,
    errors: actual.errors,
  };
}

export function assertDurableCount({ before, imported, after, label }) {
  for (const [field, value] of Object.entries({ before, imported, after })) {
    assert.ok(Number.isInteger(value) && value >= 0, `${label} ${field} must be a non-negative integer`);
  }
  assert.equal(after, before + imported, `${label} durable row count`);
  return { before, imported, after };
}

export function assertNoEmptyStateLie({ surface, persistedCount, uiText, emptyCopy }) {
  assert.ok(Number.isInteger(persistedCount) && persistedCount >= 0, `${surface} persisted count is invalid`);
  const text = normalizedText(uiText);
  assert.ok(text, `${surface} UI text is empty`);
  if (persistedCount > 0) {
    for (const copy of emptyCopy) {
      assert.equal(
        text.toLocaleLowerCase().includes(normalizedText(copy).toLocaleLowerCase()),
        false,
        `${surface} showed empty-state copy with ${persistedCount} persisted row(s): ${copy}`,
      );
    }
  }
  return { surface, persistedCount, emptyCopyAbsent: true };
}

/** Ignore only a same-origin Next RSC GET prefetch cancelled by navigation. */
export function isExpectedNextRscPrefetchAbort(failure, appUrl) {
  try {
    const failedUrl = new URL(failure.url);
    const origin = new URL(appUrl).origin;
    return (
      failedUrl.origin === origin &&
      failure.method === "GET" &&
      failure.resourceType === "fetch" &&
      failure.error === "net::ERR_ABORTED" &&
      failedUrl.searchParams.has("_rsc")
    );
  } catch {
    return false;
  }
}

function sameStringArray(actual, expected) {
  return (
    Array.isArray(actual) &&
    actual.length === expected.length &&
    actual.every((value, index) => value === expected[index])
  );
}

/** Pure report oracle used both at runtime and by the static/oracle tests. */
export function validateManufacturingFormsReport(report) {
  const problems = [];
  const check = (field, pass, expected, actual) => {
    if (!pass) problems.push({ field, expected, actual });
  };

  check("schemaVersion", report?.schemaVersion === 2, 2, report?.schemaVersion);
  check(
    "execution.attemptedCaseIds",
    sameStringArray(report?.execution?.attemptedCaseIds, MANUFACTURING_FORM_IMPORT_CASE_IDS),
    MANUFACTURING_FORM_IMPORT_CASE_IDS,
    report?.execution?.attemptedCaseIds,
  );
  check(
    "execution.omittedCaseIds",
    Array.isArray(report?.execution?.omittedCaseIds) && report.execution.omittedCaseIds.length === 0,
    [],
    report?.execution?.omittedCaseIds,
  );

  for (const [name, status] of Object.entries(REQUIRED_RESPONSE_STATUSES)) {
    check(`responseStatuses.${name}`, report?.responseStatuses?.[name] === status, status, report?.responseStatuses?.[name]);
  }

  for (const field of ["unexpectedConsoleErrors", "unexpectedRequestFailures", "unexpectedHttpErrors"]) {
    check(
      `diagnostics.${field}`,
      Array.isArray(report?.diagnostics?.[field]) && report.diagnostics[field].length === 0,
      [],
      report?.diagnostics?.[field],
    );
  }

  const startIdentity = report?.buildIdentity?.start;
  const endIdentity = report?.buildIdentity?.end;
  check("buildIdentity.start.gitHead", typeof startIdentity?.gitHead === "string" && startIdentity.gitHead.length > 0, "git SHA", startIdentity?.gitHead);
  check("buildIdentity.start.buildId", typeof startIdentity?.buildId === "string" && startIdentity.buildId.length > 0, "build id", startIdentity?.buildId);
  check("buildIdentity.end.gitHead", endIdentity?.gitHead === startIdentity?.gitHead, startIdentity?.gitHead, endIdentity?.gitHead);
  check("buildIdentity.end.buildId", endIdentity?.buildId === startIdentity?.buildId, startIdentity?.buildId, endIdentity?.buildId);

  check("releaseEvidence.schemaVersion", report?.releaseEvidence?.schemaVersion === 2, 2, report?.releaseEvidence?.schemaVersion);
  const cases = report?.releaseEvidence?.cases;
  const caseKeys = cases && typeof cases === "object" ? Object.keys(cases) : [];
  check("releaseEvidence.caseIds", sameStringArray(caseKeys, MANUFACTURING_FORM_IMPORT_CASE_IDS), MANUFACTURING_FORM_IMPORT_CASE_IDS, caseKeys);
  for (const id of MANUFACTURING_FORM_IMPORT_CASE_IDS) {
    const entry = cases?.[id];
    check(`${id}.schemaVersion`, entry?.schemaVersion === 2, 2, entry?.schemaVersion);
    check(`${id}.status`, entry?.status === "PASS", "PASS", entry?.status);
    check(`${id}.visualProof`, entry?.visualProof === "PROVEN", "PROVEN", entry?.visualProof);
    check(`${id}.visualSteps`, Array.isArray(entry?.visualSteps) && entry.visualSteps.length > 0, "one or more screenshots", entry?.visualSteps);
    const evidenceValidation = validateGoldenPathEvidence(id, entry);
    check(`${id}.evidenceContract`, evidenceValidation.valid, true, evidenceValidation.failures);
  }

  return { valid: problems.length === 0, problems };
}

async function responseBody(response) {
  let text;
  try {
    text = await response.text();
  } catch (error) {
    return {
      unavailable: true,
      error: error instanceof Error ? error.message : String(error),
    };
  }
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { invalidJson: true, text: text.slice(0, 1000) };
  }
}

function responsePath(response) {
  const url = new URL(response.url());
  return `${url.pathname}${url.search}`;
}

function isPageResponse(response, method, pathname) {
  return response.request().method() === method && new URL(response.url()).pathname === pathname;
}

function isMachineMutationResponse(response) {
  const method = response.request().method();
  const pathname = new URL(response.url()).pathname;
  return method !== "GET" && /^\/api\/proxy\/machine-inventory(?:\/|$)/.test(pathname);
}

function diagnosticsSnapshot(diagnostics) {
  return {
    console: diagnostics.unexpectedConsoleErrors.length,
    requests: diagnostics.unexpectedRequestFailures.length,
    http: diagnostics.unexpectedHttpErrors.length,
  };
}

function diagnosticsSince(diagnostics, snapshot) {
  return {
    consoleErrors: diagnostics.unexpectedConsoleErrors.slice(snapshot.console),
    requestFailures: diagnostics.unexpectedRequestFailures.slice(snapshot.requests),
    httpErrors: diagnostics.unexpectedHttpErrors.slice(snapshot.http),
  };
}

function installDiagnostics(page, diagnostics, baseUrl) {
  page.on("console", (message) => {
    if (message.type() === "error") {
      diagnostics.unexpectedConsoleErrors.push({
        url: page.url(),
        text: message.text(),
      });
    }
  });
  page.on("pageerror", (error) => {
    diagnostics.unexpectedConsoleErrors.push({ url: page.url(), text: error.message });
  });
  page.on("requestfailed", (request) => {
    const failure = {
      method: request.method(),
      url: request.url(),
      resourceType: request.resourceType(),
      error: request.failure()?.errorText || "request failed",
    };
    if (isExpectedNextRscPrefetchAbort(failure, baseUrl)) {
      diagnostics.expectedRscPrefetchAborts.push(failure);
    } else {
      diagnostics.unexpectedRequestFailures.push(failure);
    }
  });
  page.on("response", (response) => {
    const receipt = {
      source: "browser",
      method: response.request().method(),
      path: responsePath(response),
      status: response.status(),
    };
    diagnostics.responseReceipts.push(receipt);
    if (receipt.status >= 400) diagnostics.unexpectedHttpErrors.push(receipt);
    if (isMachineMutationResponse(response)) diagnostics.machineMutationResponses += 1;
  });
}

async function apiGet(page, pathname, diagnostics, label) {
  const result = await page.evaluate(async (path) => {
    const response = await fetch(path, {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
      headers: { accept: "application/json" },
    });
    return { status: response.status, text: await response.text() };
  }, pathname);
  const receipt = {
    source: "authenticated-browser-get",
    label,
    method: "GET",
    path: pathname,
    status: result.status,
  };
  diagnostics.responseReceipts.push(receipt);
  if (receipt.status >= 400) diagnostics.unexpectedHttpErrors.push(receipt);
  let body = null;
  if (result.text) {
    try {
      body = JSON.parse(result.text);
    } catch {
      body = { invalidJson: true, text: result.text.slice(0, 1000) };
    }
  }
  assert.equal(result.status, 200, `${label} returned HTTP ${result.status}: ${JSON.stringify(body)}`);
  return { status: result.status, body };
}

async function requireUi(page, description, locator, timeout = 15_000) {
  try {
    await locator.first().waitFor({ state: "visible", timeout });
    return locator.first();
  } catch {
    throw new Error(
      `Required UI flow absent or defective: ${description} is not exposed at ${page.url()}.`,
    );
  }
}

async function openWorkspace(page, { tab, heading }) {
  if (new URL(page.url()).pathname !== "/verify") {
    const response = await page.goto("/verify", { waitUntil: "domcontentloaded", timeout: 30_000 });
    assert.equal(response?.status(), 200, `GET /verify returned HTTP ${response?.status() ?? "none"}`);
  }
  const button = await requireUi(
    page,
    `Verify workspace tab “${tab}”`,
    page.getByRole("button", { name: tab, exact: true }),
  );
  await button.click();
  await requireUi(page, `Verify workspace heading “${heading}”`, page.getByRole("heading", { name: heading, exact: true }));
}

async function reloadWorkspace(page, { tab, heading }) {
  const response = await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
  assert.equal(response?.status(), 200, `Reload /verify returned HTTP ${response?.status() ?? "none"}`);
  const button = await requireUi(
    page,
    `Verify workspace tab “${tab}” after refresh`,
    page.getByRole("button", { name: tab, exact: true }),
  );
  await button.click();
  await requireUi(page, `Verify workspace heading “${heading}” after refresh`, page.getByRole("heading", { name: heading, exact: true }));
}

async function settleTerminal(page, timeout = 30_000) {
  await page.waitForLoadState("networkidle", { timeout });
  await page.waitForFunction(
    () => {
      const visible = (element) => {
        if (!(element instanceof HTMLElement) && !(element instanceof SVGElement)) return false;
        const style = window.getComputedStyle(element);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
        if (element.getAttribute("aria-hidden") === "true" || element.hasAttribute("hidden")) return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };
      const busy = [...document.querySelectorAll('[aria-busy="true"], [data-skeleton], [class~="animate-pulse"], [class~="animate-spin"]')].some(visible);
      const transient = [...document.querySelectorAll("button, [role='status'], [aria-live]")].some((element) => {
        if (!visible(element)) return false;
        const text = (element.textContent || "").replace(/\s+/g, " ").trim();
        return /^(?:computing|loading|working|saving|importing)(?:…|\.\.\.)?$/i.test(text);
      });
      return !busy && !transient;
    },
    undefined,
    { timeout },
  );
}

async function pageText(page) {
  return normalizedText(await page.locator("body").innerText());
}

async function captureStep(page, screenshotDir, {
  id,
  stage,
  requiredVisible,
  forbiddenVisible = [],
  terminal = true,
}) {
  if (terminal) await settleTerminal(page);
  const text = await pageText(page);
  for (const required of requiredVisible) {
    assert.ok(
      text.toLocaleLowerCase().includes(normalizedText(required).toLocaleLowerCase()),
      `${id}/${stage} required visible text is absent: ${required}`,
    );
  }
  for (const forbidden of forbiddenVisible) {
    assert.equal(
      text.toLocaleLowerCase().includes(normalizedText(forbidden).toLocaleLowerCase()),
      false,
      `${id}/${stage} forbidden text is visible: ${forbidden}`,
    );
  }
  const screenshot = path.join(screenshotDir, `${id}-${stage}.png`);
  const step = await captureVisualStep(page, {
    id,
    stage,
    terminal,
    requiredVisible,
    forbiddenVisible,
    screenshot,
    fullPage: true,
  });
  const screenshotStat = await stat(screenshot);
  assert.ok(screenshotStat.size > 0, `${id}/${stage} screenshot is empty`);
  return step;
}

async function captureFailureStep(page, screenshotDir, id) {
  const text = await pageText(page).catch(() => "");
  const required = text ? [text.slice(0, Math.min(120, text.length))] : ["No visible document content"];
  try {
    return await captureStep(page, screenshotDir, {
      id,
      stage: "failure",
      requiredVisible: required,
      terminal: false,
    });
  } catch {
    const screenshot = path.join(screenshotDir, `${id}-failure.png`);
    await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" }).catch(() => {});
    return {
      id,
      stage: "failure",
      terminal: false,
      screenshot,
      capturedAt: new Date().toISOString(),
      url: page.url() || "browser URL unavailable",
      requiredVisible: required,
      forbiddenVisible: [],
      capture: {
        text,
        ariaBusyCount: 0,
        skeletonCount: 0,
        loadingIndicatorCount: 0,
      },
    };
  }
}

async function chooseFile(page, button, payload) {
  const chooserPromise = page.waitForEvent("filechooser", { timeout: 15_000 });
  await button.click();
  const chooser = await chooserPromise;
  await chooser.setFiles(payload);
}

async function readMachineList(page, diagnostics, label) {
  const result = await apiGet(page, MACHINE_LIST_PATH, diagnostics, label);
  assert.ok(Array.isArray(result.body?.machines), `${label} did not return a machines array`);
  return result.body;
}

async function readManifestCoverage(page, diagnostics, label) {
  const result = await apiGet(page, MANIFEST_COVERAGE_PATH, diagnostics, label);
  assert.ok(Number.isInteger(result.body?.total_declared), `${label} did not return total_declared`);
  return result.body;
}

async function readManifestList(page, diagnostics, label) {
  const result = await apiGet(page, MANIFEST_LIST_PATH, diagnostics, label);
  assert.ok(Array.isArray(result.body?.parts), `${label} did not return a parts array`);
  return result.body;
}

async function readGroundTruth(page, diagnostics, label) {
  const result = await apiGet(page, GROUND_TRUTH_LIST_PATH, diagnostics, label);
  assert.ok(Array.isArray(result.body?.records), `${label} did not return a records array`);
  assert.equal(result.body.total, result.body.records.length, `${label} total disagrees with records length`);
  return result.body;
}

async function authenticate(page, diagnostics, responseStatuses) {
  const email = String(process.env.E2E_EMAIL || "").trim();
  const password = String(process.env.E2E_PASSWORD || "");
  assert.equal(Boolean(email), Boolean(password), "Set both E2E_EMAIL and E2E_PASSWORD, or neither for isolated UI signup");

  let documentResponse;
  let authResponse;
  let account;
  if (email) {
    documentResponse = await page.goto("/login", { waitUntil: "domcontentloaded", timeout: 30_000 });
    assert.equal(documentResponse?.status(), 200, `GET /login returned HTTP ${documentResponse?.status() ?? "none"}`);
    await requireUi(page, "password login email field", page.getByLabel("Email", { exact: true }));
    await requireUi(page, "password login password field", page.getByLabel("Password"));
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Password").fill(password);
    const responsePromise = page.waitForResponse((response) => isPageResponse(response, "POST", "/api/auth/login"));
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    authResponse = await responsePromise;
    account = { mode: "existing-credentials", email };
  } else {
    const generatedEmail = `qa-manufacturing-forms-${Date.now()}-${randomBytes(5).toString("hex")}@example.test`;
    const generatedPassword = `ProofShape-${randomBytes(10).toString("hex")}-7a`;
    documentResponse = await page.goto("/signup", { waitUntil: "domcontentloaded", timeout: 30_000 });
    assert.equal(documentResponse?.status(), 200, `GET /signup returned HTTP ${documentResponse?.status() ?? "none"}`);
    await requireUi(
      page,
      "password signup form (set E2E_EMAIL/E2E_PASSWORD when signup is intentionally disabled)",
      page.getByRole("button", { name: "Create account", exact: true }),
    );
    await page.getByLabel("Email", { exact: true }).fill(generatedEmail);
    await page.getByLabel("Password").fill(generatedPassword);
    const responsePromise = page.waitForResponse((response) => isPageResponse(response, "POST", "/api/auth/signup"));
    await page.getByRole("button", { name: "Create account", exact: true }).click();
    authResponse = await responsePromise;
    account = { mode: "isolated-ui-signup", email: generatedEmail };
  }

  const authBody = await responseBody(authResponse);
  assert.equal(authResponse.status(), 200, `Authentication returned HTTP ${authResponse.status()}: ${JSON.stringify(authBody)}`);
  responseStatuses.authMutation = authResponse.status();
  await page.waitForURL((url) => url.pathname === "/verify", { timeout: 30_000 });

  const orgs = await apiGet(page, "/api/proxy/orgs", diagnostics, "authenticated organization context");
  const active = orgs.body?.organizations?.find((organization) => organization.is_active) ?? null;
  invariant(active, "Authenticated account has no active organization; manufacturing writes cannot be tested");
  invariant(
    ["admin", "member"].includes(active.org_role),
    `Authenticated organization role ${active.org_role ?? "none"} cannot exercise manufacturing writes`,
  );

  return {
    ...account,
    authStatus: authResponse.status(),
    activeOrgId: orgs.body?.active_org_id ?? null,
    orgRole: active.org_role,
    userId: authBody?.user?.id ?? null,
    targetDocument: {
      status: documentResponse.status(),
      headers: Object.fromEntries(
        ["x-build-id", "x-vercel-id", "x-powered-by", "server"]
          .filter((name) => documentResponse.headers()[name])
          .map((name) => [name, documentResponse.headers()[name]]),
      ),
    },
  };
}

async function fillMachineForm(page, values) {
  const mappings = [
    [/^NAME$/, values.name],
    [/^COUNT$/, values.count],
    [/^HOURLY RATE \(USD\)$/, values.rate],
    [/^MAX WORKPIECE \(kg\)$/, values.maxKg],
    [/^MATERIALS \(comma-separated\)/, values.materials],
    [/^NOTES \(OPTIONAL\)$/, values.notes],
  ];
  for (const [label, value] of mappings) {
    if (value !== undefined) await page.getByLabel(label).fill(String(value));
  }
  if (values.process !== undefined) await page.getByLabel(/^PROCESS$/).selectOption(values.process);
  const process = values.process ?? await page.getByLabel(/^PROCESS$/).inputValue();
  if (process === "cnc_turning") {
    if (values.swing !== undefined) await page.getByLabel(/^SWING Ø \(mm\)$/).fill(String(values.swing));
    if (values.between !== undefined) await page.getByLabel(/^BETWEEN CENTERS \(mm\)$/).fill(String(values.between));
  } else {
    if (values.x !== undefined) await page.getByLabel(/^ENVELOPE X \(mm\)$/).fill(String(values.x));
    if (values.y !== undefined) await page.getByLabel(/^Y \(mm\)$/).fill(String(values.y));
    if (values.z !== undefined) await page.getByLabel(/^Z \(mm\)$/).fill(String(values.z));
  }
}

async function openMachineCard(page, name) {
  const card = await requireUi(
    page,
    `persisted machine card “${name}”`,
    page.getByRole("button").filter({ hasText: name }),
  );
  await card.click();
  await requireUi(page, `machine detail “${name}”`, page.getByRole("heading", { name, exact: true }));
}

async function runCase({
  page,
  diagnostics,
  screenshotDir,
  evidence,
  attemptedCaseIds,
  spec,
  execute,
}) {
  attemptedCaseIds.push(spec.id);
  const diagnosticStart = diagnosticsSnapshot(diagnostics);
  let result;
  let failure = null;
  try {
    result = await execute();
  } catch (error) {
    failure = error instanceof Error ? error.stack || error.message : String(error);
    result = {
      observed: {
        url: page.url() || "browser URL unavailable",
        visible: [`Case failed: ${failure}`],
        persisted: "not proven because the browser case failed",
        numeric: "not proven because the browser case failed",
        authorization: "authenticated context was attempted",
        recovery: "runner continued to the next required case and did not mark this branch successful",
      },
      assertions: [assertion("case completed", true, false, false)],
      visualSteps: [await captureFailureStep(page, screenshotDir, spec.id)],
    };
  }

  const caseDiagnostics = diagnosticsSince(diagnostics, diagnosticStart);
  const assertions = [...(result.assertions || [])];
  assertions.push(assertion("unexpected browser console errors", 0, caseDiagnostics.consoleErrors.length, caseDiagnostics.consoleErrors.length === 0));
  assertions.push(assertion("unexpected browser request failures", 0, caseDiagnostics.requestFailures.length, caseDiagnostics.requestFailures.length === 0));
  assertions.push(assertion("unexpected HTTP error responses", 0, caseDiagnostics.httpErrors.length, caseDiagnostics.httpErrors.length === 0));
  const status = !failure && assertions.every((item) => item.pass) ? "PASS" : "FAIL";
  const entry = makeGoldenPathEvidence({
    id: spec.id,
    status,
    persona: spec.persona,
    preconditions: spec.preconditions,
    actions: spec.actions,
    observed: result.observed,
    screenshot: result.visualSteps?.at(-1)?.screenshot,
    visualSteps: result.visualSteps || [],
    consoleErrors: caseDiagnostics.consoleErrors,
    requestFailures: caseDiagnostics.requestFailures,
    assertions,
  });
  entry.httpErrors = caseDiagnostics.httpErrors;
  if (failure) entry.error = failure;

  const validation = validateGoldenPathEvidence(spec.id, entry);
  if (entry.status === "PASS" && !validation.valid) {
    entry.status = "FAIL";
    entry.assertions.push(assertion("schema-v2 evidence contract", true, validation.failures, false));
  }
  evidence[spec.id] = entry;
  return entry;
}

async function caseMachineBoundaries({ page, diagnostics, screenshotDir, state }) {
  await openWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  const before = await readMachineList(page, diagnostics, "machine boundary baseline");
  state.machineBaseline = before.machines.length;

  const add = await requireUi(
    page,
    "machine create form",
    page.getByRole("button", { name: /Add machine|Add your first machine/ }),
  );
  await add.click();
  await requireUi(
    page,
    "machine declaration form title",
    page.getByText("DECLARE A MACHINE — THE DENOMINATOR OF EVERY VERDICT", { exact: true }),
  );
  await fillMachineForm(page, {
    name: `Boundary Reject ${state.token}`,
    process: "cnc_3axis",
    count: "1.5",
    rate: "95/hr",
    maxKg: "0",
    x: "0",
    y: "-1",
    z: "Infinity",
    materials: "6061",
  });
  const mutationsBefore = diagnostics.machineMutationResponses;
  await page.getByRole("button", { name: "Declare machine", exact: true }).click();
  await page.getByTestId("machine-save-error").waitFor({ state: "visible" });
  await page.waitForTimeout(350);
  const mutationsAfter = diagnostics.machineMutationResponses;
  const after = await readMachineList(page, diagnostics, "machine boundary post-submit persistence");
  const errorText = normalizedText((await page.getByRole("alert").allInnerTexts()).join(" "));

  const requiredVisible = [
    "Correct the highlighted declarations. Nothing was saved.",
    "Count must be a whole number.",
    "Hourly rate must be a complete number.",
    "Max workpiece must be greater than 0.",
    "Envelope X must be greater than 0.",
  ];
  const step = await captureStep(page, screenshotDir, {
    id: "MFI-01",
    stage: "client-boundary-refusal",
    requiredVisible,
  });
  await page.getByRole("button", { name: "Cancel", exact: true }).click();

  return {
    observed: {
      url: page.url(),
      visible: requiredVisible,
      persisted: { before: before.machines.length, after: after.machines.length },
      numeric: { mutationResponses: mutationsAfter - mutationsBefore },
      authorization: "Invalid browser form values were refused before an authenticated mutation crossed the proxy.",
      recovery: "The modal retained every invalid entry and exposed field-level corrections; Cancel returned to the unchanged inventory.",
    },
    assertions: [
      assertion("invalid submit persistence requests", 0, mutationsAfter - mutationsBefore, mutationsAfter === mutationsBefore),
      assertion("invalid submit inventory count", before.machines.length, after.machines.length, before.machines.length === after.machines.length),
      assertion("strict complete-number errors rendered", true, errorText, requiredVisible.every((text) => errorText.includes(text))),
    ],
    visualSteps: [step],
  };
}

async function caseMachineCrud({ page, diagnostics, screenshotDir, state, responseStatuses }) {
  await openWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  const before = await readMachineList(page, diagnostics, "machine CRUD baseline");
  assert.equal(before.machines.length, state.machineBaseline, "boundary case changed the machine baseline");

  const machineName = `E2E Boundary Mill ${state.token}`;
  await page.getByRole("button", { name: /Add machine|Add your first machine/ }).first().click();
  await fillMachineForm(page, {
    name: machineName,
    process: "cnc_3axis",
    count: "1",
    rate: "0",
    maxKg: "0.001",
    x: "0.001",
    y: "0.001",
    z: "0.001",
    materials: "6061",
    notes: "accepted numeric boundary; edit follows",
  });
  const createPromise = page.waitForResponse((response) => isPageResponse(response, "POST", "/api/proxy/machine-inventory"));
  await page.getByRole("button", { name: "Declare machine", exact: true }).click();
  const createResponse = await createPromise;
  const createBody = await responseBody(createResponse);
  responseStatuses.machineCreate = createResponse.status();
  assert.equal(createResponse.status(), 201, `machine create HTTP ${createResponse.status()}: ${JSON.stringify(createBody)}`);
  await requireUi(page, `created machine “${machineName}”`, page.getByText(machineName, { exact: true }));

  const createdList = await readMachineList(page, diagnostics, "machine create persistence");
  const created = createdList.machines.find((machine) => machine.id === createBody?.id);
  invariant(created, "Created machine was absent from the persisted inventory");
  assert.equal(created.hourly_rate_usd, 0, "hourly rate lower boundary did not persist");
  assert.equal(created.max_workpiece_kg, 0.001, "positive mass boundary did not persist");
  assert.deepEqual(
    { x: created.capabilities?.x, y: created.capabilities?.y, z: created.capabilities?.z },
    { x: 0.001, y: 0.001, z: 0.001 },
    "positive envelope boundaries did not persist",
  );
  const createdStep = await captureStep(page, screenshotDir, {
    id: "MFI-02",
    stage: "created-boundary-value",
    requiredVisible: [machineName, "$0.00/hr", "0.001 × 0.001 × 0.001 mm"],
  });

  await reloadWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  await openMachineCard(page, machineName);
  await page.getByRole("button", { name: "Edit specs", exact: true }).click();
  await fillMachineForm(page, {
    count: "2",
    rate: "95.5",
    maxKg: "50",
    x: "600",
    y: "400",
    z: "500",
    materials: "6061, 316L",
    notes: "edited production declaration",
  });
  const editPromise = page.waitForResponse((response) =>
    response.request().method() === "PATCH" &&
    new URL(response.url()).pathname === `/api/proxy/machine-inventory/${createBody.id}`
  );
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  const editResponse = await editPromise;
  const editBody = await responseBody(editResponse);
  responseStatuses.machineEdit = editResponse.status();
  assert.equal(editResponse.status(), 200, `machine edit HTTP ${editResponse.status()}: ${JSON.stringify(editBody)}`);

  await reloadWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  await openMachineCard(page, machineName);
  const editedList = await readMachineList(page, diagnostics, "machine edit persistence");
  const edited = editedList.machines.find((machine) => machine.id === createBody.id);
  invariant(edited, "Edited machine disappeared after refresh");
  assert.equal(edited.count, 2);
  assert.equal(edited.hourly_rate_usd, 95.5);
  assert.deepEqual(
    { x: edited.capabilities?.x, y: edited.capabilities?.y, z: edited.capabilities?.z },
    { x: 600, y: 400, z: 500 },
  );
  const editedStep = await captureStep(page, screenshotDir, {
    id: "MFI-02",
    stage: "edited-after-refresh",
    requiredVisible: [machineName, "$95.50/hr", "600 × 400 × 500 mm", "edited production declaration"],
  });

  const deletePromise = page.waitForResponse((response) =>
    response.request().method() === "DELETE" &&
    new URL(response.url()).pathname === `/api/proxy/machine-inventory/${createBody.id}`
  );
  await page.getByRole("button", { name: "Delete machine", exact: true }).click();
  const deleteResponse = await deletePromise;
  const deleteBody = await responseBody(deleteResponse);
  responseStatuses.machineDelete = deleteResponse.status();
  assert.equal(deleteResponse.status(), 200, `machine delete HTTP ${deleteResponse.status()}: ${JSON.stringify(deleteBody)}`);
  assert.deepEqual(deleteBody, { deleted: true, id: createBody.id });

  await reloadWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  const deletedList = await readMachineList(page, diagnostics, "machine delete persistence");
  assert.equal(deletedList.machines.some((machine) => machine.id === createBody.id), false);
  assert.equal(deletedList.machines.length, before.machines.length);
  const deletedStep = await captureStep(page, screenshotDir, {
    id: "MFI-02",
    stage: "deleted-after-refresh",
    requiredVisible: ["Your machines"],
    forbiddenVisible: [machineName],
  });

  return {
    observed: {
      url: page.url(),
      visible: [machineName, "$0.00/hr", "$95.50/hr", "edited production declaration", `deleted id ${createBody.id}`],
      persisted: {
        id: createBody.id,
        createdAfterRefresh: true,
        editedAfterRefresh: edited,
        deletedAfterRefresh: !deletedList.machines.some((machine) => machine.id === createBody.id),
      },
      numeric: {
        createStatus: createResponse.status(),
        editStatus: editResponse.status(),
        deleteStatus: deleteResponse.status(),
        finalCount: deletedList.machines.length,
      },
      authorization: "Create, edit, and delete each crossed the authenticated same-origin UI proxy with exact 201/200/200 responses.",
      recovery: "A full refresh after each mutation re-read the backend row; deletion restored the original inventory count.",
    },
    assertions: [
      assertion("machine create status", 201, createResponse.status(), createResponse.status() === 201),
      assertion("machine edit status", 200, editResponse.status(), editResponse.status() === 200),
      assertion("machine delete status", 200, deleteResponse.status(), deleteResponse.status() === 200),
      assertion("created lower boundaries", { rate: 0, mass: 0.001, envelope: [0.001, 0.001, 0.001] }, { rate: created.hourly_rate_usd, mass: created.max_workpiece_kg, envelope: [created.capabilities.x, created.capabilities.y, created.capabilities.z] }, true),
      assertion("edited values durable", { count: 2, rate: 95.5, envelope: [600, 400, 500] }, { count: edited.count, rate: edited.hourly_rate_usd, envelope: [edited.capabilities.x, edited.capabilities.y, edited.capabilities.z] }, true),
      assertion("delete restored baseline", before.machines.length, deletedList.machines.length, before.machines.length === deletedList.machines.length),
    ],
    visualSteps: [createdStep, editedStep, deletedStep],
  };
}

async function caseValidMachineImport({ page, diagnostics, screenshotDir, state, responseStatuses }) {
  await openWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  const before = await readMachineList(page, diagnostics, "valid machine import baseline");
  const lathe = `E2E Lathe ${state.token}`;
  const printer = `E2E FDM ${state.token}`;
  const csv = csvDocument(MACHINE_CSV_HEADER, [
    ["cnc_turning", lathe, 2, 100, 110, 0.3, "steel|stainless", "", JSON.stringify({ swing_dia: 400, between_centers: 800 }), "valid turning row"],
    ["fdm", printer, 3, 5, 12.5, 0.1, "polymer", "", JSON.stringify({ x: 300, y: 300, z: 400, min_wall_mm: 0.8 }), "valid additive row"],
  ]);
  const responsePromise = page.waitForResponse((response) => isPageResponse(response, "POST", MACHINE_IMPORT_PATH));
  const importButton = await requireUi(page, "machine CSV import button", page.getByRole("button", { name: "Import CSV", exact: true }));
  await chooseFile(page, importButton, uploadPayload(`valid-machines-${state.token}.csv`, csv));
  const response = await responsePromise;
  const body = await responseBody(response);
  responseStatuses.machineImportValid = response.status();
  assert.equal(response.status(), 200, `valid machine import HTTP ${response.status()}: ${JSON.stringify(body)}`);
  const summary = assertExactImportSummary(body, { imported: 2, skipped: 0, total: 2, errorCount: 0 }, "valid machine import");
  await page.getByTestId("machine-import-result").waitFor({ state: "visible" });
  await requireUi(page, `imported machine “${lathe}”`, page.getByText(lathe, { exact: true }));
  await requireUi(page, `imported machine “${printer}”`, page.getByText(printer, { exact: true }));
  const after = await readMachineList(page, diagnostics, "valid machine import persistence");
  const countEvidence = assertDurableCount({ before: before.machines.length, imported: 2, after: after.machines.length, label: "valid machine import" });
  const summaryStep = await captureStep(page, screenshotDir, {
    id: "MFI-03",
    stage: "exact-valid-import-summary",
    requiredVisible: ["Import complete: 2 imported · 0 skipped · 2 total", lathe, printer],
  });

  await reloadWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  await requireUi(page, `refreshed imported machine “${lathe}”`, page.getByText(lathe, { exact: true }));
  await requireUi(page, `refreshed imported machine “${printer}”`, page.getByText(printer, { exact: true }));
  const refreshStep = await captureStep(page, screenshotDir, {
    id: "MFI-03",
    stage: "valid-rows-after-refresh",
    requiredVisible: [lathe, printer],
  });
  state.machineNames.push(lathe, printer);

  return {
    observed: {
      url: page.url(),
      visible: ["Import complete: 2 imported · 0 skipped · 2 total", lathe, printer],
      persisted: { names: [lathe, printer], countEvidence },
      numeric: { status: response.status(), summary },
      authorization: "The real machine CSV file chooser posted through the authenticated UI and returned HTTP 200.",
      recovery: "Both imported rows remained visible and present in GET /machine-inventory after a full refresh.",
    },
    assertions: [
      assertion("valid import HTTP status", 200, response.status(), response.status() === 200),
      assertion("valid import exact counts", { imported: 2, skipped: 0, total: 2 }, summary, summary.imported === 2 && summary.skipped === 0 && summary.total === 2),
      assertion("valid rows durable", before.machines.length + 2, after.machines.length, after.machines.length === before.machines.length + 2),
      assertion("valid names persisted", [lathe, printer], after.machines.filter((machine) => [lathe, printer].includes(machine.name)).map((machine) => machine.name).sort(), [lathe, printer].every((name) => after.machines.some((machine) => machine.name === name))),
    ],
    visualSteps: [summaryStep, refreshStep],
  };
}

async function caseMixedMachineImport({ page, diagnostics, screenshotDir, state, responseStatuses }) {
  await openWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  const before = await readMachineList(page, diagnostics, "mixed machine import baseline");
  const validName = `E2E SLS ${state.token}`;
  const invalidName = `E2E Invalid Count ${state.token}`;
  const csv = csvDocument(MACHINE_CSV_HEADER, [
    ["sls", validName, 1, 20, 65, 0.45, "polymer", "", JSON.stringify({ x: 380, y: 284, z: 380, min_wall_mm: 0.8 }), "valid mixed-file row"],
    ["cnc_3axis", invalidName, "2x", 40, 90, 0.25, "aluminum", "", JSON.stringify({ x: 500, y: 400, z: 300 }), "must never persist"],
  ]);
  const responsePromise = page.waitForResponse((response) => isPageResponse(response, "POST", MACHINE_IMPORT_PATH));
  const importButton = await requireUi(page, "machine CSV mixed import button", page.getByRole("button", { name: "Import CSV", exact: true }));
  await chooseFile(page, importButton, uploadPayload(`mixed-machines-${state.token}.csv`, csv));
  const response = await responsePromise;
  const body = await responseBody(response);
  responseStatuses.machineImportMixed = response.status();
  assert.equal(response.status(), 200, `mixed machine import HTTP ${response.status()}: ${JSON.stringify(body)}`);
  const summary = assertExactImportSummary(body, { imported: 1, skipped: 1, total: 2, errorCount: 1 }, "mixed machine import");
  assert.equal(summary.errors[0]?.line, 3, "mixed machine error line");
  assert.match(summary.errors[0]?.reason || "", /count not an integer \('2x'\)/);
  await page.getByTestId("machine-import-result").waitFor({ state: "visible" });
  await requireUi(page, `mixed import valid machine “${validName}”`, page.getByText(validName, { exact: true }));
  const resultText = normalizedText(await page.getByTestId("machine-import-result").innerText());
  const after = await readMachineList(page, diagnostics, "mixed machine import persistence");
  const countEvidence = assertDurableCount({ before: before.machines.length, imported: 1, after: after.machines.length, label: "mixed machine import" });
  assert.equal(after.machines.some((machine) => machine.name === invalidName), false, "invalid mixed row persisted");
  const summaryStep = await captureStep(page, screenshotDir, {
    id: "MFI-04",
    stage: "mixed-import-partial-success",
    requiredVisible: ["Import complete: 1 imported · 1 skipped · 2 total", "line 3: count not an integer ('2x')", validName],
    forbiddenVisible: [invalidName],
  });

  await reloadWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  await requireUi(page, `mixed valid row after refresh “${validName}”`, page.getByText(validName, { exact: true }));
  const refreshText = await pageText(page);
  assert.equal(refreshText.includes(invalidName), false, "invalid mixed row appeared after refresh");
  const refreshStep = await captureStep(page, screenshotDir, {
    id: "MFI-04",
    stage: "mixed-import-after-refresh",
    requiredVisible: [validName],
    forbiddenVisible: [invalidName],
  });
  state.machineNames.push(validName);

  return {
    observed: {
      url: page.url(),
      visible: ["Import complete: 1 imported · 1 skipped · 2 total", "line 3: count not an integer ('2x')", validName],
      persisted: { validName, invalidAbsent: true, countEvidence },
      numeric: { status: response.status(), summary },
      authorization: "The mixed CSV used the real UI file chooser and received an honest HTTP 200 partial-success body.",
      recovery: "The valid row survived refresh; the malformed line stayed absent while its line-3 reason remained in the import receipt.",
    },
    assertions: [
      assertion("mixed import HTTP status", 200, response.status(), response.status() === 200),
      assertion("mixed import exact counts", { imported: 1, skipped: 1, total: 2 }, summary, summary.imported === 1 && summary.skipped === 1 && summary.total === 2),
      assertion("mixed import exact line error", { line: 3, reason: "count not an integer ('2x')" }, summary.errors[0], summary.errors[0]?.line === 3 && /count not an integer \('2x'\)/.test(summary.errors[0]?.reason || "")),
      assertion("mixed import rendered line receipt", true, resultText, resultText.includes("line 3") && resultText.includes("count not an integer ('2x')")),
      assertion("mixed valid row durable", before.machines.length + 1, after.machines.length, after.machines.length === before.machines.length + 1),
      assertion("mixed invalid row absent", false, after.machines.some((machine) => machine.name === invalidName), !after.machines.some((machine) => machine.name === invalidName)),
    ],
    visualSteps: [summaryStep, refreshStep],
  };
}

async function caseManifestOnboarding({ page, diagnostics, screenshotDir, state, responseStatuses }) {
  await openWorkspace(page, { tab: "Triage", heading: "Triage at scale" });
  const importButton = await requireUi(
    page,
    "manifest/BOM onboarding button on Triage",
    page.getByRole("button", { name: /Import manifest CSV|Import \/ re-import BOM/ }),
  );
  const beforeCoverage = await readManifestCoverage(page, diagnostics, "manifest onboarding baseline coverage");
  const beforeList = await readManifestList(page, diagnostics, "manifest onboarding baseline list");
  const partA = `E2E-${state.token}-PUMP-001`;
  const partB = `E2E-${state.token}-BRACKET-002`;
  const csv = csvDocument(MANIFEST_CSV_HEADER, [
    [partA, "centrifugal pump impeller", "steel", `Pilot-${state.token}`, "PUMP-ASSY-01", 1, 120, 120, "US", "browser-e2e", "declared BOM row"],
    [partB, "mounting bracket", "aluminum", `Pilot-${state.token}`, "PUMP-ASSY-01", 4, 480, 480, "US", "browser-e2e", "declared BOM row"],
  ]);
  const responsePromise = page.waitForResponse((response) => isPageResponse(response, "POST", MANIFEST_IMPORT_PATH));
  await chooseFile(page, importButton, uploadPayload(`manifest-${state.token}.csv`, csv));
  const response = await responsePromise;
  const body = await responseBody(response);
  responseStatuses.manifestImport = response.status();
  assert.equal(response.status(), 200, `manifest import HTTP ${response.status()}: ${JSON.stringify(body)}`);
  const summary = assertExactImportSummary(body, { imported: 2, updated: 0, skipped: 0, total: 2, errorCount: 0 }, "manifest import");
  await requireUi(page, `declared manifest row “${partA}”`, page.getByText(partA, { exact: true }));
  await requireUi(page, `declared manifest row “${partB}”`, page.getByText(partB, { exact: true }));

  const afterCoverage = await readManifestCoverage(page, diagnostics, "manifest onboarding persisted coverage");
  const afterList = await readManifestList(page, diagnostics, "manifest onboarding persisted list");
  const countEvidence = assertDurableCount({
    before: beforeCoverage.total_declared,
    imported: 2,
    after: afterCoverage.total_declared,
    label: "manifest declared-part",
  });
  assert.equal(beforeList.parts.some((part) => [partA, partB].includes(part.part_id)), false, "manifest fixture IDs collided with existing data");
  assert.ok([partA, partB].every((partId) => afterList.parts.some((part) => part.part_id === partId)), "imported manifest rows missing from backend list");
  const importStep = await captureStep(page, screenshotDir, {
    id: "MFI-05",
    stage: "bom-onboarded",
    requiredVisible: ["DECLARED INVENTORY · IMPORTED BOM", partA, partB, `${afterCoverage.total_declared} declared parts`],
    forbiddenVisible: ["No declared parts yet — import a BOM"],
  });

  await reloadWorkspace(page, { tab: "Triage", heading: "Triage at scale" });
  await requireUi(page, `declared manifest row after refresh “${partA}”`, page.getByText(partA, { exact: true }));
  await requireUi(page, `declared manifest row after refresh “${partB}”`, page.getByText(partB, { exact: true }));
  const refreshText = await pageText(page);
  assertNoEmptyStateLie({
    surface: "manifest/BOM Triage cohort",
    persistedCount: afterCoverage.total_declared,
    uiText: refreshText,
    emptyCopy: ["No declared parts yet — import a BOM"],
  });
  const refreshStep = await captureStep(page, screenshotDir, {
    id: "MFI-05",
    stage: "bom-after-refresh",
    requiredVisible: ["DECLARED INVENTORY · IMPORTED BOM", partA, partB],
    forbiddenVisible: ["No declared parts yet — import a BOM"],
  });
  state.manifestPartIds.push(partA, partB);
  state.manifestTotal = afterCoverage.total_declared;

  return {
    observed: {
      url: page.url(),
      visible: ["DECLARED INVENTORY · IMPORTED BOM", partA, partB, "awaiting geometry"],
      persisted: { partIds: [partA, partB], countEvidence, afterRefresh: true },
      numeric: { status: response.status(), summary, geometry: afterCoverage.geometry },
      authorization: "Manifest/BOM onboarding was exposed on Triage and the real UI upload returned HTTP 200.",
      recovery: "A full refresh retained both declared rows and the exact declared/geometry coverage; no empty-BOM copy replaced them.",
    },
    assertions: [
      assertion("manifest import HTTP status", 200, response.status(), response.status() === 200),
      assertion("manifest exact counts", { imported: 2, updated: 0, skipped: 0, total: 2 }, summary, summary.imported === 2 && summary.updated === 0 && summary.skipped === 0 && summary.total === 2),
      assertion("manifest durable total", beforeCoverage.total_declared + 2, afterCoverage.total_declared, afterCoverage.total_declared === beforeCoverage.total_declared + 2),
      assertion("manifest rows durable", [partA, partB], afterList.parts.filter((part) => [partA, partB].includes(part.part_id)).map((part) => part.part_id).sort(), [partA, partB].every((partId) => afterList.parts.some((part) => part.part_id === partId))),
      assertion("manifest remains honestly uncosted without geometry", 2, afterCoverage.geometry?.without_geometry - beforeCoverage.geometry?.without_geometry, afterCoverage.geometry?.without_geometry === beforeCoverage.geometry?.without_geometry + 2),
    ],
    visualSteps: [importStep, refreshStep],
  };
}

async function waitForGroundTruthCount(page, expected) {
  const label = await requireUi(
    page,
    "ground-truth real-record count",
    page.getByText("real records (held-out pool)", { exact: true }),
  );
  await page.waitForFunction(
    ({ text, count }) => {
      const labels = [...document.querySelectorAll("span")].filter((node) => node.textContent?.trim() === text);
      return labels.some((node) => node.parentElement?.innerText.replace(/\s+/g, " ").trim().endsWith(String(count)));
    },
    { text: "real records (held-out pool)", count: expected },
    { timeout: 30_000 },
  );
  return normalizedText(await label.locator("..").innerText());
}

async function caseGroundTruthImport({ page, diagnostics, screenshotDir, state, responseStatuses }) {
  await openWorkspace(page, { tab: "Calibration & truth", heading: "Calibration & truth" });
  const actualsButton = await requireUi(
    page,
    "ground-truth/actuals CSV import button",
    page.getByRole("button", { name: "Choose ground-truth actuals CSV", exact: true }),
  );
  const before = await readGroundTruth(page, diagnostics, "ground-truth import baseline");
  const beforeReal = before.records.filter((record) => record.stand_in === false).length;
  const rows = [
    [`${state.token}-actual-001.stl`, "cnc_3axis", 10, 42.5],
    [`${state.token}-actual-002.stl`, "cnc_turning", 20, 27.25],
    [`${state.token}-actual-003.stl`, "sls", 50, 11.75],
  ];
  const csv = csvDocument(GROUND_TRUTH_CSV_HEADER, rows);
  const responsePromise = page.waitForResponse((response) => isPageResponse(response, "POST", GROUND_TRUTH_IMPORT_PATH));
  await chooseFile(page, actualsButton, uploadPayload(`actuals-${state.token}.csv`, csv));
  const response = await responsePromise;
  const body = await responseBody(response);
  responseStatuses.groundTruthImport = response.status();
  assert.equal(response.status(), 200, `ground-truth import HTTP ${response.status()}: ${JSON.stringify(body)}`);
  const summary = assertExactImportSummary(body, { imported: 3, skipped: 0, total: 3, errorCount: 0 }, "ground-truth import");
  const expectedReal = beforeReal + 3;
  const uiCount = await waitForGroundTruthCount(page, expectedReal);
  const after = await readGroundTruth(page, diagnostics, "ground-truth import persistence");
  const afterReal = after.records.filter((record) => record.stand_in === false).length;
  const totalEvidence = assertDurableCount({ before: before.total, imported: 3, after: after.total, label: "ground-truth total" });
  const realEvidence = assertDurableCount({ before: beforeReal, imported: 3, after: afterReal, label: "ground-truth real" });
  const importedPartIds = rows.map((row) => row[0]);
  assert.ok(importedPartIds.every((partId) => after.records.some((record) => record.part_id === partId && record.stand_in === false)), "ground-truth rows were not durable real records");
  const importStep = await captureStep(page, screenshotDir, {
    id: "MFI-06",
    stage: "actuals-imported",
    requiredVisible: ["THE HALLMARK — GROUND-TRUTH FLYWHEEL", "real records (held-out pool)", String(expectedReal)],
  });

  await reloadWorkspace(page, { tab: "Calibration & truth", heading: "Calibration & truth" });
  const refreshCount = await waitForGroundTruthCount(page, expectedReal);
  const refreshText = await pageText(page);
  assertNoEmptyStateLie({
    surface: "ground-truth actuals",
    persistedCount: afterReal,
    uiText: refreshText,
    emptyCopy: ["validation status: n=0 real", "n=0 · every band still hatched"],
  });
  const refreshStep = await captureStep(page, screenshotDir, {
    id: "MFI-06",
    stage: "actuals-after-refresh",
    requiredVisible: ["THE HALLMARK — GROUND-TRUTH FLYWHEEL", "real records (held-out pool)", String(expectedReal)],
    forbiddenVisible: ["validation status: n=0 real"],
  });
  state.groundTruthPartIds.push(...importedPartIds);
  state.groundTruthTotal = after.total;
  state.realActualCount = afterReal;

  return {
    observed: {
      url: page.url(),
      visible: ["THE HALLMARK — GROUND-TRUTH FLYWHEEL", uiCount, refreshCount],
      persisted: { partIds: importedPartIds, totalEvidence, realEvidence },
      numeric: { status: response.status(), summary, realCountAfterRefresh: afterReal },
      authorization: "The actuals file chooser posted through the authenticated Calibration & truth UI and returned HTTP 200.",
      recovery: "The exact real-record count survived a full page refresh and a fresh backend list read.",
    },
    assertions: [
      assertion("ground-truth import HTTP status", 200, response.status(), response.status() === 200),
      assertion("ground-truth exact counts", { imported: 3, skipped: 0, total: 3 }, summary, summary.imported === 3 && summary.skipped === 0 && summary.total === 3),
      assertion("ground-truth total durable", before.total + 3, after.total, after.total === before.total + 3),
      assertion("ground-truth real count durable", beforeReal + 3, afterReal, afterReal === beforeReal + 3),
      assertion("ground-truth rows are real", importedPartIds, after.records.filter((record) => importedPartIds.includes(record.part_id) && !record.stand_in).map((record) => record.part_id).sort(), importedPartIds.every((partId) => after.records.some((record) => record.part_id === partId && !record.stand_in))),
    ],
    visualSteps: [importStep, refreshStep],
  };
}

async function caseRefreshTruth({ page, diagnostics, screenshotDir, state }) {
  const machines = await readMachineList(page, diagnostics, "final refreshed machine inventory");
  const coverage = await readManifestCoverage(page, diagnostics, "final refreshed manifest coverage");
  const manifest = await readManifestList(page, diagnostics, "final refreshed manifest list");
  const groundTruth = await readGroundTruth(page, diagnostics, "final refreshed ground-truth list");
  const realActualCount = groundTruth.records.filter((record) => record.stand_in === false).length;

  assert.ok(state.machineNames.every((name) => machines.machines.some((machine) => machine.name === name)), "one or more imported machines vanished before final recovery check");
  assert.ok(state.manifestPartIds.every((partId) => manifest.parts.some((part) => part.part_id === partId)), "one or more manifest rows vanished before final recovery check");
  assert.ok(state.groundTruthPartIds.every((partId) => groundTruth.records.some((record) => record.part_id === partId && !record.stand_in)), "one or more actuals vanished before final recovery check");

  await openWorkspace(page, { tab: "Your machines", heading: "Your machines" });
  await Promise.all(state.machineNames.map((name) => requireUi(page, `final machine “${name}”`, page.getByText(name, { exact: true }))));
  const machineText = await pageText(page);
  assertNoEmptyStateLie({
    surface: "machine inventory",
    persistedCount: machines.machines.length,
    uiText: machineText,
    emptyCopy: ["Declare your floor.", "No machines declared"],
  });
  const machineStep = await captureStep(page, screenshotDir, {
    id: "MFI-07",
    stage: "machines-refresh-recovery",
    requiredVisible: ["Your machines", ...state.machineNames],
    forbiddenVisible: ["Declare your floor."],
  });

  await reloadWorkspace(page, { tab: "Triage", heading: "Triage at scale" });
  await Promise.all(state.manifestPartIds.map((partId) => requireUi(page, `final manifest row “${partId}”`, page.getByText(partId, { exact: true }))));
  const manifestText = await pageText(page);
  assertNoEmptyStateLie({
    surface: "manifest/BOM cohort",
    persistedCount: coverage.total_declared,
    uiText: manifestText,
    emptyCopy: ["No declared parts yet — import a BOM"],
  });
  const manifestStep = await captureStep(page, screenshotDir, {
    id: "MFI-07",
    stage: "manifest-refresh-recovery",
    requiredVisible: ["DECLARED INVENTORY · IMPORTED BOM", ...state.manifestPartIds],
    forbiddenVisible: ["No declared parts yet — import a BOM"],
  });

  const reloadResponse = await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
  assert.equal(reloadResponse?.status(), 200, `Final home reload returned HTTP ${reloadResponse?.status() ?? "none"}`);
  await page.getByRole("button", { name: "Home", exact: true }).click();
  await requireUi(page, "Verify home recovery heading", page.getByRole("heading", { name: "Good morning.", exact: true }));
  await page.waitForFunction(
    ({ machineCount, actualCount }) => {
      const text = (document.body?.innerText || "").replace(/\s+/g, " ");
      const machines = `${machineCount} machine${machineCount === 1 ? "" : "s"} owned`;
      const actuals = `${actualCount} actual${actualCount === 1 ? "" : "s"} received`;
      return text.includes(machines) && text.includes(actuals);
    },
    { machineCount: machines.machines.length, actualCount: realActualCount },
    { timeout: 30_000 },
  );
  const homeText = await pageText(page);
  assertNoEmptyStateLie({
    surface: "Verify home machine summary",
    persistedCount: machines.machines.length,
    uiText: homeText,
    emptyCopy: ["No machines declared", "declare your floor — everything starts from the denominator"],
  });
  assertNoEmptyStateLie({
    surface: "Verify home actuals summary",
    persistedCount: realActualCount,
    uiText: homeText,
    emptyCopy: ["n=0 · every band still hatched"],
  });
  const homeStep = await captureStep(page, screenshotDir, {
    id: "MFI-07",
    stage: "home-no-empty-state-lies",
    requiredVisible: [
      `${machines.machines.length} machine${machines.machines.length === 1 ? "" : "s"} owned`,
      `${realActualCount} actual${realActualCount === 1 ? "" : "s"} received`,
    ],
    forbiddenVisible: ["No machines declared", "n=0 · every band still hatched"],
  });

  return {
    observed: {
      url: page.url(),
      visible: [
        `${machines.machines.length} machines persisted`,
        `${coverage.total_declared} manifest rows persisted`,
        `${realActualCount} real actuals persisted`,
      ],
      persisted: {
        machines: state.machineNames,
        manifestParts: state.manifestPartIds,
        actualParts: state.groundTruthPartIds,
      },
      numeric: {
        machineCount: machines.machines.length,
        manifestCount: coverage.total_declared,
        groundTruthTotal: groundTruth.total,
        realActualCount,
      },
      authorization: "All final reads used the same authenticated organization context as the browser mutations.",
      recovery: "Independent refreshes of Machines, Triage, and Home recovered persisted rows and replaced no non-empty surface with zero/empty copy.",
    },
    assertions: [
      assertion("all imported machines remain", state.machineNames, machines.machines.filter((machine) => state.machineNames.includes(machine.name)).map((machine) => machine.name).sort(), state.machineNames.every((name) => machines.machines.some((machine) => machine.name === name))),
      assertion("all manifest rows remain", state.manifestPartIds, manifest.parts.filter((part) => state.manifestPartIds.includes(part.part_id)).map((part) => part.part_id).sort(), state.manifestPartIds.every((partId) => manifest.parts.some((part) => part.part_id === partId))),
      assertion("all actual rows remain real", state.groundTruthPartIds, groundTruth.records.filter((record) => state.groundTruthPartIds.includes(record.part_id) && !record.stand_in).map((record) => record.part_id).sort(), state.groundTruthPartIds.every((partId) => groundTruth.records.some((record) => record.part_id === partId && !record.stand_in))),
      assertion("home machine count is non-empty", "> 0", machines.machines.length, machines.machines.length > 0 && !homeText.includes("No machines declared")),
      assertion("home actual count is non-empty", "> 0", realActualCount, realActualCount > 0 && !homeText.includes("n=0 · every band still hatched")),
    ],
    visualSteps: [machineStep, manifestStep, homeStep],
  };
}

async function sourceIdentity() {
  const testPath = path.join(__dirname, "manufacturing-forms-import-browser.test.mjs");
  const runner = await readFile(__filename);
  let test = null;
  try {
    test = await readFile(testPath);
  } catch {
    // Report the missing companion test as null; the report oracle will still
    // bind the executable runner and static CI catches the absent test file.
  }
  return {
    runner: { path: path.relative(repoRoot, __filename), bytes: runner.length, sha256: sha256(runner) },
    test: test ? { path: path.relative(repoRoot, testPath), bytes: test.length, sha256: sha256(test) } : null,
  };
}

async function assertScreenshotFiles(evidence) {
  for (const id of MANUFACTURING_FORM_IMPORT_CASE_IDS) {
    const steps = evidence[id]?.visualSteps || [];
    for (const step of steps) {
      await access(step.screenshot);
      const info = await stat(step.screenshot);
      assert.ok(info.size > 0, `${id}/${step.stage} screenshot is empty`);
    }
  }
}

async function launchBrowser() {
  const args = process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [];
  return chromium.launch({ channel: "chrome", headless: true, args }).catch(() =>
    chromium.launch({ headless: true, args })
  );
}

async function main() {
  const baseUrl = process.env.APP_URL || "http://localhost:3000";
  const runId = process.env.E2E_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");
  const outputRoot = process.env.E2E_ARTIFACT_DIR
    ? path.resolve(process.env.E2E_ARTIFACT_DIR)
    : path.join(repoRoot, ".gstack", "qa-reports");
  const artifactDir = path.join(outputRoot, `manufacturing-forms-import-${runId}`);
  const screenshotDir = path.join(artifactDir, "screenshots");
  const reportPath = path.join(artifactDir, "report.json");
  await mkdir(screenshotDir, { recursive: true });

  const buildIdentityStart = captureBuildIdentity(repoRoot);
  const ownedSources = await sourceIdentity();
  const diagnostics = {
    unexpectedConsoleErrors: [],
    unexpectedRequestFailures: [],
    unexpectedHttpErrors: [],
    expectedRscPrefetchAborts: [],
    responseReceipts: [],
    machineMutationResponses: 0,
  };
  const responseStatuses = {};
  const evidence = {};
  const attemptedCaseIds = [];
  const token = `${Date.now().toString(36)}-${randomBytes(3).toString("hex")}`.toUpperCase();
  const state = {
    token,
    machineBaseline: null,
    machineNames: [],
    manifestPartIds: [],
    manifestTotal: null,
    groundTruthPartIds: [],
    groundTruthTotal: null,
    realActualCount: null,
  };

  let browser = null;
  let context = null;
  let page = null;
  let account = null;
  let fatal = null;

  try {
    browser = await launchBrowser();
    context = await browser.newContext({
      baseURL: baseUrl,
      acceptDownloads: true,
      viewport: { width: 1440, height: 1000 },
      reducedMotion: "reduce",
      extraHTTPHeaders: {
        "x-real-ip": process.env.E2E_CLIENT_IP || `198.51.100.${40 + (randomBytes(1)[0] % 180)}`,
      },
    });
    page = await context.newPage();
    page.setDefaultTimeout(20_000);
    installDiagnostics(page, diagnostics, baseUrl);
    account = await authenticate(page, diagnostics, responseStatuses);

    const shared = { page, diagnostics, screenshotDir, state, responseStatuses };
    const cases = [
      {
        spec: {
          id: "MFI-01",
          persona: "shop administrator declaring machine boundaries",
          preconditions: ["Authenticated organization context is active.", "Machine inventory is read through the real backend."],
          actions: ["Open Your machines.", "Enter malformed, fractional, zero, negative, and non-finite declarations.", "Submit and verify no mutation request or row count change."],
        },
        execute: () => caseMachineBoundaries(shared),
      },
      {
        spec: {
          id: "MFI-02",
          persona: "shop administrator maintaining a durable machine record",
          preconditions: ["Invalid form submission left inventory unchanged.", "The authenticated caller can author machine inventory."],
          actions: ["Create a machine at accepted numeric boundaries.", "Refresh and edit it to production values.", "Refresh, delete it through the UI, and refresh again."],
        },
        execute: () => caseMachineCrud(shared),
      },
      {
        spec: {
          id: "MFI-03",
          persona: "operations lead importing a valid machine inventory",
          preconditions: ["The canonical machine CSV schema is used.", "The machine list is open in the browser."],
          actions: ["Choose a two-row valid CSV through Import CSV.", "Assert exact response and UI counts.", "Refresh and verify both backend rows remain visible."],
        },
        execute: () => caseValidMachineImport(shared),
      },
      {
        spec: {
          id: "MFI-04",
          persona: "operations lead handling a mixed-error machine inventory",
          preconditions: ["Existing imported machines must not be removed.", "Partial success reports every malformed line."],
          actions: ["Choose one valid and one malformed row in the same CSV.", "Assert exact 1/1/2 counts and line-3 reason.", "Refresh and prove only the valid row persisted."],
        },
        execute: () => caseMixedMachineImport(shared),
      },
      {
        spec: {
          id: "MFI-05",
          persona: "sourcing lead onboarding a manifest/BOM",
          preconditions: ["Triage exposes the manifest/BOM import affordance.", "Declared inventory is distinct from geometry-derived makeability."],
          actions: ["Upload two BOM rows through Triage.", "Assert exact import/update/skip/total counts.", "Refresh and verify declared rows plus honest geometry coverage."],
        },
        execute: () => caseManifestOnboarding(shared),
      },
      {
        spec: {
          id: "MFI-06",
          persona: "cost engineer sending measured actuals back",
          preconditions: ["Calibration & truth exposes the ground-truth CSV chooser.", "The starting real-record count is read from the backend."],
          actions: ["Upload three real actual rows through the UI.", "Assert exact 3/0/3 response counts.", "Refresh and verify the durable total and real-record count."],
        },
        execute: () => caseGroundTruthImport(shared),
      },
      {
        spec: {
          id: "MFI-07",
          persona: "production operator recovering every manufacturing surface after refresh",
          preconditions: ["Machine, manifest, and actual rows were persisted by prior UI flows.", "All final reads remain in one active organization."],
          actions: ["Refresh Machines and verify imported rows.", "Refresh Triage and verify declared BOM rows.", "Refresh Home and reject zero/empty copy against positive backend counts."],
        },
        execute: () => caseRefreshTruth(shared),
      },
    ];

    for (const item of cases) {
      await runCase({
        page,
        diagnostics,
        screenshotDir,
        evidence,
        attemptedCaseIds,
        spec: item.spec,
        execute: item.execute,
      });
    }
    await page.waitForTimeout(500);
  } catch (error) {
    fatal = error instanceof Error ? error.stack || error.message : String(error);
  }

  for (const id of MANUFACTURING_FORM_IMPORT_CASE_IDS) {
    if (evidence[id]) continue;
    const screenshot = path.join(screenshotDir, `${id}-not-reached.png`);
    if (page) await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" }).catch(() => {});
    evidence[id] = makeGoldenPathEvidence({
      id,
      status: "FAIL",
      persona: "required manufacturing browser branch was not reached",
      preconditions: ["Authentication and every earlier required branch must remain executable."],
      actions: ["Runner attempted the complete ordered case list."],
      observed: {
        url: page?.url() || baseUrl,
        visible: [`Not reached: ${fatal || "runner stopped before this required branch"}`],
        persisted: "not observed",
        numeric: "not observed",
        authorization: "not observed",
        recovery: "A failing evidence entry was emitted instead of treating the omitted branch as success.",
      },
      screenshot,
      visualSteps: [{
        id,
        stage: "not-reached",
        terminal: false,
        screenshot,
        capturedAt: new Date().toISOString(),
        url: page?.url() || baseUrl,
        requiredVisible: ["Required branch not reached"],
        forbiddenVisible: [],
        capture: { text: "", ariaBusyCount: 0, skeletonCount: 0, loadingIndicatorCount: 0 },
      }],
      consoleErrors: [],
      requestFailures: [],
      assertions: [assertion("required branch reached", true, false, false)],
    });
  }

  const buildIdentityEnd = captureBuildIdentity(repoRoot);
  const omittedCaseIds = MANUFACTURING_FORM_IMPORT_CASE_IDS.filter((id) => !attemptedCaseIds.includes(id));
  const report = {
    schemaVersion: 2,
    suite: "manufacturing-forms-import-browser",
    generatedAt: new Date().toISOString(),
    runId,
    target: baseUrl,
    status: "RUNNING",
    fatal,
    account,
    ownedSources,
    buildIdentity: { start: buildIdentityStart, end: buildIdentityEnd },
    execution: {
      requiredCaseIds: MANUFACTURING_FORM_IMPORT_CASE_IDS,
      attemptedCaseIds,
      omittedCaseIds,
      noBranchesTreatedAsSuccessWithoutExecution: true,
    },
    responseStatuses,
    diagnostics: {
      unexpectedConsoleErrors: diagnostics.unexpectedConsoleErrors,
      unexpectedRequestFailures: diagnostics.unexpectedRequestFailures,
      unexpectedHttpErrors: diagnostics.unexpectedHttpErrors,
      expectedRscPrefetchAborts: diagnostics.expectedRscPrefetchAborts,
      responseReceipts: diagnostics.responseReceipts,
    },
    releaseEvidence: {
      schemaVersion: 2,
      cases: Object.fromEntries(MANUFACTURING_FORM_IMPORT_CASE_IDS.map((id) => [id, evidence[id]])),
    },
    artifacts: { root: artifactDir, screenshots: screenshotDir, report: reportPath },
  };

  try {
    await assertScreenshotFiles(evidence);
  } catch (error) {
    report.screenshotError = error instanceof Error ? error.message : String(error);
  }
  const validation = validateManufacturingFormsReport(report);
  if (report.screenshotError) {
    validation.valid = false;
    validation.problems.push({ field: "screenshots", expected: "all non-empty files", actual: report.screenshotError });
  }
  if (fatal) {
    validation.valid = false;
    validation.problems.push({ field: "fatal", expected: null, actual: fatal });
  }
  report.validation = validation;
  report.status = validation.valid ? "PASS" : "FAIL";
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");

  await context?.close().catch(() => {});
  await browser?.close().catch(() => {});

  process.stdout.write(`${JSON.stringify({
    status: report.status,
    report: reportPath,
    attemptedCaseIds,
    omittedCaseIds,
    responseStatuses,
    diagnostics: {
      consoleErrors: diagnostics.unexpectedConsoleErrors.length,
      requestFailures: diagnostics.unexpectedRequestFailures.length,
      httpErrors: diagnostics.unexpectedHttpErrors.length,
    },
    validationProblems: validation.problems,
  }, null, 2)}\n`);
  if (report.status !== "PASS") process.exitCode = 1;
}

const invokedAsScript = process.argv[1] && path.resolve(process.argv[1]) === __filename;
if (invokedAsScript) {
  await main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
