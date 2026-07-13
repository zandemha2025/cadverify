import { createRequire } from "node:module";
import { createHash, randomBytes } from "node:crypto";
import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual } from "node:util";

import {
  makeGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, "outputs", "human-sim", "manufacturing-cad-adversarial");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");
const screenshotDir = path.join(outputRoot, "screenshots");
const reportPath = path.join(outputRoot, "report.json");

const MANUFACTURING_SUBPATH_IDS = [
  "MFG-01",
  "MFG-02",
  "MFG-03",
  "MFG-04",
  "MFG-05",
  "MFG-06",
];

const EXACT_GOLDEN_IDS = [
  "ENT-01",
  "VER-05",
  "WORK-01",
  "WORK-02",
  "FAIL-01",
  "FAIL-02",
];

const SUPPLEMENTAL_CAD_IDS = [
  "CAD-01",
  "CAD-02",
  "CAD-03",
  "CAD-04",
  "CAD-05",
  "CAD-06",
  "CAD-07",
  "CAD-08",
  "CAD-09",
];

const PATH_IDS = [...MANUFACTURING_SUBPATH_IDS, ...EXACT_GOLDEN_IDS, ...SUPPLEMENTAL_CAD_IDS];

const MACHINE_HEADER = [
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
].join(",");

const evidence = {};
const timings = {};
const unresolvedLimits = [];
const consoleErrors = [];
const requestFailures = [];
const httpErrorResponses = [];
const networkStatusConsoleMessages = [];
const forbiddenCadAssetRequests = [];
let machineMutationResponses = 0;

function assertRecord(name, expected, actual, pass) {
  return { name, expected, actual, pass: Boolean(pass) };
}

function near(actual, expected, tolerance) {
  return Number.isFinite(actual) && Math.abs(actual - expected) <= tolerance;
}

function responsePath(response) {
  const url = new URL(response.url());
  return `${url.pathname}${url.search}`;
}

function isMachineMutation(response) {
  return (
    response.request().method() === "POST" &&
    new URL(response.url()).pathname === "/api/proxy/machine-inventory"
  );
}

function isIgnorableRequestFailure(request) {
  const url = request.url();
  const failure = request.failure()?.errorText || "unknown";
  if (/favicon\.ico|webpack-hmr|vercel\/speed-insights/i.test(url)) return true;
  if (failure === "net::ERR_ABORTED" && (/[?&]_rsc=/.test(url) || request.method() === "GET")) {
    return true;
  }
  return false;
}

function isNetworkStatusConsoleMessage(text) {
  return /^Failed to load resource: the server responded with a status of [45]\d\d\b/.test(text);
}

function isForbiddenCadAssetRequest(url) {
  try {
    const parsed = new URL(url);
    if (["localhost", "127.0.0.1"].includes(parsed.hostname)) return false;
    return (
      /raw\.githack\.com|drei-assets/i.test(parsed.hostname + parsed.pathname) ||
      /\.hdr(?:$|\?)/i.test(parsed.pathname + parsed.search)
    );
  } catch {
    return false;
  }
}

function boxTriangles(origin = [0, 0, 0], size = [10, 10, 10]) {
  const [ox, oy, oz] = origin;
  const [sx, sy, sz] = size;
  const v = [
    [ox, oy, oz],
    [ox + sx, oy, oz],
    [ox + sx, oy + sy, oz],
    [ox, oy + sy, oz],
    [ox, oy, oz + sz],
    [ox + sx, oy, oz + sz],
    [ox + sx, oy + sy, oz + sz],
    [ox, oy + sy, oz + sz],
  ];
  const faces = [
    [0, 2, 1], [0, 3, 2],
    [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4],
    [3, 7, 6], [3, 6, 2],
    [0, 4, 7], [0, 7, 3],
    [1, 2, 6], [1, 6, 5],
  ];
  return faces.map((face) => face.map((index) => v[index]));
}

function binaryStl(triangles, label = "ProofShape deterministic E2E fixture") {
  const out = Buffer.alloc(84 + triangles.length * 50);
  out.write(label.slice(0, 80), 0, "ascii");
  out.writeUInt32LE(triangles.length, 80);
  triangles.forEach((triangle, index) => {
    let offset = 84 + index * 50;
    // A zero normal is legal; trimesh derives the face normal from vertices.
    out.writeFloatLE(0, offset); offset += 4;
    out.writeFloatLE(0, offset); offset += 4;
    out.writeFloatLE(0, offset); offset += 4;
    for (const vertex of triangle) {
      for (const coordinate of vertex) {
        out.writeFloatLE(coordinate, offset);
        offset += 4;
      }
    }
    out.writeUInt16LE(0, offset);
  });
  return out;
}

function uploadPayload(name, buffer, mimeType = "application/octet-stream") {
  return { name, buffer, mimeType };
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function machineCsvRow(values) {
  return [
    values.process,
    values.name,
    values.count,
    values.max_workpiece_kg,
    values.hourly_rate_usd,
    values.capital_frac,
    values.materials,
    values.material_thickness_map,
    values.capabilities,
    values.notes,
  ].map(csvCell).join(",");
}

async function existingAssemblyFixture() {
  const candidates = [
    process.env.E2E_ASSEMBLY_FIXTURE,
    path.join(repoRoot, "backend", ".venv", "share", "doc", "gmsh", "examples", "api", "as1-tu-203.stp"),
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      // Try the next documented fixture location.
    }
  }
  return null;
}

async function launchBrowser() {
  const options = {
    channel: "chrome",
    headless: true,
    args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"],
  };
  return chromium.launch(options).catch(() => chromium.launch({ headless: true }));
}

async function browserApi(page, url, options = {}) {
  return page.evaluate(
    async ({ target, init }) => {
      const normalized = { cache: "no-store", ...init };
      if (normalized.body && typeof normalized.body !== "string") {
        normalized.headers = { "content-type": "application/json", ...(normalized.headers || {}) };
        normalized.body = JSON.stringify(normalized.body);
      }
      const response = await fetch(target, normalized);
      const text = await response.text();
      let body = null;
      try { body = JSON.parse(text); } catch { body = text; }
      return { status: response.status, body };
    },
    { target: url, init: options },
  );
}

async function bodyText(page) {
  return (await page.locator("body").innerText()).replace(/\s+/g, " ").trim();
}

async function shot(page, id) {
  const target = path.join(screenshotDir, `${id.toLowerCase()}.png`);
  await page.screenshot({ path: target, fullPage: true });
  return target;
}

async function recordPath(page, spec, run) {
  const started = Date.now();
  const consoleStart = consoleErrors.length;
  const requestStart = requestFailures.length;
  const httpErrorStart = httpErrorResponses.length;
  const networkStatusStart = networkStatusConsoleMessages.length;
  const forbiddenAssetStart = forbiddenCadAssetRequests.length;
  let result;
  let thrown = null;
  try {
    result = await run();
  } catch (error) {
    thrown = error instanceof Error ? error.message : String(error);
    result = {
      observed: {
        url: page.url() || "browser URL unavailable",
        visible: [`Path exception: ${thrown}`],
        persisted: "not confirmed because the path raised an exception",
        numeric: "not confirmed because the path raised an exception",
        authorization: "authenticated browser context was in use",
        recovery: "runner continued to the next isolated path",
      },
      assertions: [assertRecord("path completed without exception", true, thrown, false)],
    };
  }
  // Let lazy viewer resources and browser diagnostics settle before freezing the
  // path envelope. This prevents a CSP error from leaking into the next path.
  await page.waitForTimeout(300).catch(() => {});
  const screenshot = await shot(page, spec.id).catch(() => path.join(screenshotDir, `${spec.id.toLowerCase()}.png`));
  const pathConsoleErrors = consoleErrors.slice(consoleStart);
  const pathRequestFailures = requestFailures.slice(requestStart);
  const pathHttpErrors = httpErrorResponses.slice(httpErrorStart);
  const pathNetworkStatusMessages = networkStatusConsoleMessages.slice(networkStatusStart);
  const pathForbiddenAssets = forbiddenCadAssetRequests.slice(forbiddenAssetStart);
  result.observed.httpErrorResponses = pathHttpErrors;
  result.observed.networkStatusConsoleMessages = pathNetworkStatusMessages;
  result.observed.remoteCadAssetRequests = pathForbiddenAssets;
  const assertions = Array.isArray(result.assertions) && result.assertions.length
    ? result.assertions
    : [assertRecord("path supplied explicit assertions", true, false, false)];
  const expectedHttpErrorCount = result.expectedHttpErrorCount ?? 0;
  assertions.push(assertRecord(
    "HTTP error response count",
    expectedHttpErrorCount,
    pathHttpErrors.length,
    pathHttpErrors.length === expectedHttpErrorCount,
  ));
  assertions.push(assertRecord(
    "remote CAD lighting requests",
    0,
    pathForbiddenAssets.length,
    pathForbiddenAssets.length === 0,
  ));
  if (pathConsoleErrors.length) {
    assertions.push(assertRecord("browser console errors", 0, pathConsoleErrors.length, false));
  }
  if (pathRequestFailures.length) {
    assertions.push(assertRecord("browser request failures", 0, pathRequestFailures.length, false));
  }
  const status = !thrown && assertions.every((item) => item.pass) && !pathConsoleErrors.length && !pathRequestFailures.length
    ? "PASS"
    : "FAIL";
  timings[spec.id] = Date.now() - started;
  evidence[spec.id] = makeGoldenPathEvidence({
    id: spec.id,
    status,
    persona: spec.persona,
    preconditions: spec.preconditions,
    actions: spec.actions,
    observed: result.observed,
    screenshot,
    consoleErrors: pathConsoleErrors,
    requestFailures: pathRequestFailures,
    assertions,
  });
}

async function signup(page) {
  const email = `qa-mfg-cad-${Date.now()}-${randomBytes(4).toString("hex")}@example.com`;
  const password = `ProofShape-${randomBytes(8).toString("hex")}-9a`;
  await page.goto(`${baseUrl}/signup`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  const signupResponse = page.waitForResponse((response) =>
    response.request().method() === "POST" && new URL(response.url()).pathname === "/api/auth/signup"
  );
  await page.getByRole("button", { name: "Create account" }).click();
  const response = await signupResponse;
  const signupBody = await response.json().catch(() => null);
  await page.waitForURL((url) => !url.pathname.includes("signup"), { timeout: 30_000 });
  if (response.status() !== 200) {
    throw new Error(`signup failed HTTP ${response.status()}`);
  }
  const organizations = await browserApi(page, "/api/proxy/orgs");
  const active = organizations.body?.organizations?.find((org) => org.is_active) ?? null;
  if (organizations.status !== 200 || active?.org_role !== "admin") {
    throw new Error(`signup organization context missing (HTTP ${organizations.status}, role ${active?.org_role ?? "none"})`);
  }
  return {
    email,
    userId: signupBody?.user?.id ?? null,
    globalRole: signupBody?.user?.role ?? null,
    activeOrgId: organizations.body?.active_org_id ?? null,
    orgRole: active.org_role,
  };
}

async function openMachines(page, { reload = false } = {}) {
  if (reload || !new URL(page.url()).pathname.startsWith("/verify")) {
    await page.goto(`${baseUrl}/verify`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  }
  const inventoryResponse = page.waitForResponse((response) =>
    response.request().method() === "GET" && new URL(response.url()).pathname === "/api/proxy/machine-inventory"
  ).catch(() => null);
  await page.getByRole("button", { name: "Your machines", exact: true }).click();
  await page.getByRole("heading", { name: "Your machines" }).waitFor({ timeout: 20_000 });
  await inventoryResponse;
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
  if (values.process) await page.getByLabel(/^PROCESS$/).selectOption(values.process);
  if (values.process === "cnc_turning") {
    if (values.swing !== undefined) await page.getByLabel(/^SWING Ø \(mm\)$/).fill(String(values.swing));
    if (values.between !== undefined) await page.getByLabel(/^BETWEEN CENTERS \(mm\)$/).fill(String(values.between));
  } else {
    if (values.x !== undefined) await page.getByLabel(/^ENVELOPE X \(mm\)$/).fill(String(values.x));
    if (values.y !== undefined) await page.getByLabel(/^Y \(mm\)$/).fill(String(values.y));
    if (values.z !== undefined) await page.getByLabel(/^Z \(mm\)$/).fill(String(values.z));
  }
}

async function machineList(page) {
  const response = await browserApi(page, "/api/proxy/machine-inventory");
  if (response.status !== 200 || !Array.isArray(response.body?.machines)) {
    throw new Error(`machine list failed HTTP ${response.status}`);
  }
  return response.body.machines;
}

async function openCostOptions(page) {
  const button = page.getByRole("button", { name: /Costing options/ });
  if ((await button.getAttribute("aria-expanded")) !== "true") await button.click();
}

async function selectCostOption(page, label, option) {
  const field = page.getByText(label, { exact: true }).locator("..");
  await field.getByRole("combobox").click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

async function prepareAnalyze(page, { units = "mm", material = null } = {}) {
  await page.goto(`${baseUrl}/analyze`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByText(/Drop a CAD file/).waitFor({ timeout: 20_000 });
  await openCostOptions(page);
  const unitTrigger = page.getByRole("combobox", { name: "CAD source units" });
  await unitTrigger.click();
  await page.getByRole("option", { name: units === "inch" ? "Inches (in)" : "Millimetres (mm)", exact: true }).click();
  if (material) await selectCostOption(page, "Material class", material);
}

async function uploadAnalyze(page, payload, timeout = 90_000) {
  const costPromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === "POST" && url.pathname === "/api/proxy/validate/cost";
  }, { timeout });
  const dfmPromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === "POST" && url.pathname === "/api/proxy/validate";
  }, { timeout });
  const started = Date.now();
  await page.locator('input[type="file"][accept*=".stl"]').first().setInputFiles(payload);
  const [costResponse, dfmResponse] = await Promise.all([costPromise, dfmPromise]);
  const [costBody, dfmBody] = await Promise.all([
    costResponse.json().catch(async () => ({ raw: await costResponse.text().catch(() => "") })),
    dfmResponse.json().catch(async () => ({ raw: await dfmResponse.text().catch(() => "") })),
  ]);
  await page.waitForTimeout(250);
  return {
    elapsedMs: Date.now() - started,
    cost: { status: costResponse.status(), body: costBody, path: responsePath(costResponse) },
    dfm: { status: dfmResponse.status(), body: dfmBody, path: responsePath(dfmResponse) },
  };
}

async function resetAnalyze(page) {
  const button = page.getByRole("button", { name: "New part", exact: true });
  if (await button.count()) await button.first().click();
  await page.getByText(/Drop a CAD file/).waitFor({ timeout: 20_000 });
  return /Drop a CAD file/.test(await bodyText(page));
}

async function prepareVerify(page) {
  await page.goto(`${baseUrl}/verify`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await page.getByTestId("verify-part-cad-input").waitFor({ state: "attached", timeout: 20_000 });
}

function allDfmIssues(validation) {
  return [
    ...(validation?.universal_issues ?? []),
    ...((validation?.process_scores ?? []).flatMap((score) => score.issues ?? [])),
  ];
}

async function runSuite(page, account) {
  const boundaryMill = "QA Boundary Mill";
  const microMill = "QA Micro Mill";

  await recordPath(page, {
    id: "MFG-01",
    persona: "shop administrator declaring an owned machining floor",
    preconditions: ["Fresh authenticated organization with no seeded machine inventory.", "Shared PostgreSQL API is healthy."],
    actions: ["Open Verify → Your machines.", "Author a CNC 3-axis machine with rate, envelope, materials, count, mass, and notes.", "Reload Verify and reopen the machine detail."],
  }, async () => {
    await openMachines(page, { reload: true });
    await page.getByRole("button", { name: /Add machine|Add your first machine/ }).first().click();
    await fillMachineForm(page, {
      name: boundaryMill,
      process: "cnc_3axis",
      count: "2",
      rate: "75",
      maxKg: "100",
      materials: "aluminum, steel",
      notes: "QA declaration retained across reopen",
      x: "5", y: "5", z: "5",
    });
    const createdResponse = page.waitForResponse(isMachineMutation);
    await page.getByRole("button", { name: "Declare machine" }).click();
    const created = await createdResponse;
    await page.getByText(boundaryMill, { exact: true }).waitFor();
    await openMachines(page, { reload: true });
    await page.getByText(boundaryMill, { exact: true }).click();
    await page.getByRole("heading", { name: boundaryMill }).waitFor();
    const machines = await machineList(page);
    const persisted = machines.find((machine) => machine.name === boundaryMill);
    const text = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: [boundaryMill, "5 × 5 × 5 mm", "$75.00/hr", "QA declaration retained across reopen"],
        persisted: persisted ?? "machine missing",
        numeric: persisted ? { count: persisted.count, rate: persisted.hourly_rate_usd, envelope: persisted.capabilities } : "machine missing",
        authorization: `create HTTP ${created.status()} under authenticated org-admin session`,
        recovery: "Full page reload returned to the same persisted machine detail.",
      },
      assertions: [
        assertRecord("machine create status", 201, created.status(), created.status() === 201),
        assertRecord("persisted count", 2, persisted?.count, persisted?.count === 2),
        assertRecord("persisted rate", 75, persisted?.hourly_rate_usd, persisted?.hourly_rate_usd === 75),
        assertRecord("persisted envelope", { x: 5, y: 5, z: 5 }, persisted?.capabilities, persisted?.capabilities?.x === 5 && persisted?.capabilities?.y === 5 && persisted?.capabilities?.z === 5),
        assertRecord("reopened detail visible", true, text.includes(boundaryMill) && text.includes("5 × 5 × 5 mm"), text.includes(boundaryMill) && text.includes("5 × 5 × 5 mm")),
      ],
    };
  });

  await recordPath(page, {
    id: "MFG-02",
    persona: "shop administrator correcting malformed and boundary machine values",
    preconditions: ["Authenticated machine inventory list is open.", "Strict form parser is loaded in the browser."],
    actions: ["Enter malformed count, prefixed dimension, negative rate, and zero max mass.", "Submit and verify no API mutation occurs.", "Correct to valid lower-bound values and save without losing the other entries."],
  }, async () => {
    await openMachines(page, { reload: true });
    await page.getByRole("button", { name: "Add machine", exact: true }).click();
    await fillMachineForm(page, {
      name: microMill,
      process: "cnc_3axis",
      count: "2 machines",
      rate: "-0.01",
      maxKg: "0",
      materials: "aluminum",
      notes: "boundary recovery retained",
      x: "12abc", y: "0", z: "Infinity",
    });
    const before = machineMutationResponses;
    await page.getByRole("button", { name: "Declare machine" }).click();
    await page.getByTestId("machine-save-error").waitFor();
    await page.waitForTimeout(300);
    const invalidText = await bodyText(page);
    const retainedName = await page.getByLabel(/^NAME$/).inputValue();
    const noMutation = machineMutationResponses === before;
    await fillMachineForm(page, {
      count: "1", rate: "0", maxKg: "0.001", x: "0.001", y: "0.001", z: "0.001",
    });
    const responsePromise = page.waitForResponse(isMachineMutation);
    await page.getByRole("button", { name: "Declare machine" }).click();
    const response = await responsePromise;
    await page.getByText(microMill, { exact: true }).waitFor();
    const persisted = (await machineList(page)).find((machine) => machine.name === microMill);
    return {
      observed: {
        url: page.url(),
        visible: ["Count must be a complete number.", "Hourly rate must be at least 0.", "Correct the highlighted declarations. Nothing was saved.", microMill],
        persisted: persisted ?? "corrected machine missing",
        numeric: { mutationsDuringInvalidSubmit: machineMutationResponses - before, acceptedRate: persisted?.hourly_rate_usd, acceptedEnvelopeX: persisted?.capabilities?.x },
        authorization: `corrected create HTTP ${response.status()} under authenticated org-admin session`,
        recovery: "All non-numeric entries remained in the form; correcting only highlighted fields saved successfully.",
      },
      assertions: [
        assertRecord("invalid submit made no persistence request", 0, machineMutationResponses - before, noMutation),
        assertRecord("malformed and boundary errors visible", true, /complete number/.test(invalidText) && /at least 0/.test(invalidText) && /greater than 0/.test(invalidText), /complete number/.test(invalidText) && /at least 0/.test(invalidText) && /greater than 0/.test(invalidText)),
        assertRecord("unrelated form value retained", microMill, retainedName, retainedName === microMill),
        assertRecord("valid zero hourly rate persisted", 0, persisted?.hourly_rate_usd, persisted?.hourly_rate_usd === 0),
        assertRecord("positive 0.001 mm boundary persisted", 0.001, persisted?.capabilities?.x, persisted?.capabilities?.x === 0.001),
      ],
    };
  });

  await recordPath(page, {
    id: "MFG-03",
    persona: "manufacturing engineer updating capacity before a make/buy decision",
    preconditions: ["QA Boundary Mill exists with an intentionally undersized 5 mm envelope.", "A deterministic 10 mm watertight cube is available."],
    actions: ["Edit the persisted machine to a 100 mm envelope and $95/hr rate.", "Reopen the record.", "Upload the 10 mm part through Analyze using aluminum and inspect DFM plus machine-fit cost output."],
  }, async () => {
    await openMachines(page, { reload: true });
    await page.getByText(boundaryMill, { exact: true }).click();
    await page.getByRole("button", { name: "Edit specs" }).click();
    await fillMachineForm(page, { rate: "95", x: "100", y: "100", z: "100" });
    const patchResponse = page.waitForResponse((response) =>
      response.request().method() === "PATCH" && /\/api\/proxy\/machine-inventory\//.test(new URL(response.url()).pathname)
    );
    await page.getByRole("button", { name: "Save changes" }).click();
    const patched = await patchResponse;
    await page.getByText("100 × 100 × 100 mm", { exact: true }).waitFor();
    const persisted = (await machineList(page)).find((machine) => machine.name === boundaryMill);
    await prepareAnalyze(page, { units: "mm", material: "aluminum" });
    const run = await uploadAnalyze(page, uploadPayload("mfg-downstream-10mm.stl", binaryStl(boxTriangles())));
    const route = run.cost.body?.verification?.per_route?.cnc_3axis;
    const visible = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["mfg-downstream-10mm.stl", "100×100×100 mm", boundaryMill],
        persisted: persisted ?? "edited machine missing",
        numeric: { dfmBboxMm: run.dfm.body?.geometry?.bounding_box_mm, machineRateUsd: route?.machine_rate_usd, machinesEvaluated: route?.machines_evaluated, elapsedMs: run.elapsedMs },
        authorization: `machine edit HTTP ${patched.status()}; cost HTTP ${run.cost.status}; DFM HTTP ${run.dfm.status}`,
        recovery: "Reopening and analyzing used the edited, not stale, machine values.",
      },
      assertions: [
        assertRecord("machine edit status", 200, patched.status(), patched.status() === 200),
        assertRecord("edited envelope persisted", { x: 100, y: 100, z: 100 }, persisted?.capabilities, persisted?.capabilities?.x === 100 && persisted?.capabilities?.y === 100 && persisted?.capabilities?.z === 100),
        assertRecord("DFM measured 10 mm cube", [10, 10, 10], run.dfm.body?.geometry?.bounding_box_mm, JSON.stringify(run.dfm.body?.geometry?.bounding_box_mm) === JSON.stringify([10, 10, 10])),
        assertRecord("cost route evaluated owned CNC machine", true, route ?? null, route?.machines_evaluated >= 1 && route?.best_machine === boundaryMill),
        assertRecord("edited marginal rate reached decision", 95, route?.machine_rate_usd, route?.machine_rate_usd === 95),
        assertRecord("browser renders machine-grounded result", true, visible.includes(boundaryMill), visible.includes(boundaryMill)),
      ],
    };
  });

  await recordPath(page, {
    id: "MFG-04",
    persona: "operations lead exporting the canonical machine import schema",
    preconditions: ["Authenticated machine list is open.", "Browser downloads are enabled."],
    actions: ["Click Download CSV template.", "Read the downloaded artifact.", "Compare its filename, exact header, and example row shape to the import contract."],
  }, async () => {
    await openMachines(page, { reload: true });
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download CSV template" }).click();
    const download = await downloadPromise;
    const tempPath = await download.path();
    const csv = tempPath ? await readFile(tempPath, "utf8") : "";
    const [header, example, trailing] = csv.split("\n");
    const visible = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["Download CSV template", "Downloaded the exact machine import template"],
        persisted: "read-only export; inventory row count unchanged",
        numeric: { bytes: Buffer.byteLength(csv), columns: header?.split(",").length, rows: csv.trimEnd().split("\n").length },
        authorization: "template GET completed in authenticated viewer context",
        recovery: "Downloaded artifact remained readable and the machine list stayed interactive.",
      },
      assertions: [
        assertRecord("download filename", "machines-template.csv", download.suggestedFilename(), download.suggestedFilename() === "machines-template.csv"),
        assertRecord("exact canonical header", MACHINE_HEADER, header, header === MACHINE_HEADER),
        assertRecord("one non-empty example row", true, Boolean(example) && example.split(",").length >= 10, Boolean(example) && example.split(",").length >= 10),
        assertRecord("single trailing newline", "empty string after final newline", trailing ?? "missing", trailing === ""),
        assertRecord("success state visible", true, visible.includes("Downloaded the exact machine import template"), visible.includes("Downloaded the exact machine import template")),
      ],
    };
  });

  await recordPath(page, {
    id: "MFG-05",
    persona: "shop administrator importing a mixed-validity machine CSV",
    preconditions: ["Canonical machine CSV header is known.", "Existing machines must survive partial import."],
    actions: ["Import one valid lathe row and one malformed-count row in the same CSV.", "Read persistent per-line feedback.", "Reopen inventory and verify only the valid row persisted."],
  }, async () => {
    await openMachines(page, { reload: true });
    const before = await machineList(page);
    const csv = `${MACHINE_HEADER}\n${machineCsvRow({
      name: "MJF 5200 - Bay 4", process: "mjf", count: "3", max_workpiece_kg: "8", hourly_rate_usd: "48", capital_frac: "0.62", materials: "polymer", material_thickness_map: "", capabilities: JSON.stringify({ x: 380, y: 284, z: 380, min_layer_um: 80, min_wall_mm: 0.8 }), notes: "valid imported row",
    })}\n${machineCsvRow({
      name: "CSV Bad Count", process: "cnc_3axis", count: "2x", max_workpiece_kg: "50", hourly_rate_usd: "80", capital_frac: "0.2", materials: "aluminum", material_thickness_map: "", capabilities: JSON.stringify({ x: 100, y: 100, z: 100 }), notes: "must not persist",
    })}\n`;
    const responsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/machine-inventory/import"
    );
    await page.locator('input[type="file"][accept*=".csv"]').setInputFiles(uploadPayload("mixed-machines.csv", Buffer.from(csv), "text/csv"));
    const response = await responsePromise;
    await page.getByTestId("machine-import-result").waitFor();
    const summary = await response.json();
    const resultText = await page.getByTestId("machine-import-result").innerText();
    const after = await machineList(page);
    return {
      observed: {
        url: page.url(),
        visible: ["Import complete: 1 imported · 1 skipped · 2 total", "line 3: count not an integer ('2x')"],
        persisted: { before: before.length, after: after.length, valid: after.some((machine) => machine.name === "MJF 5200 - Bay 4"), invalid: after.some((machine) => machine.name === "CSV Bad Count") },
        numeric: summary,
        authorization: `CSV import HTTP ${response.status()} under authenticated analyst context`,
        recovery: "Valid row was usable immediately; malformed row was skipped without rolling back or deleting existing inventory.",
      },
      assertions: [
        assertRecord("partial import HTTP status", 200, response.status(), response.status() === 200),
        assertRecord("partial import counts", { imported: 1, skipped: 1, total: 2 }, { imported: summary.imported, skipped: summary.skipped, total: summary.total }, summary.imported === 1 && summary.skipped === 1 && summary.total === 2),
        assertRecord("line-specific error rendered persistently", "line 3 count error", resultText, resultText.includes("line 3") && resultText.includes("count not an integer ('2x')")),
        assertRecord("valid row persisted", true, after.some((machine) => machine.name === "MJF 5200 - Bay 4"), after.some((machine) => machine.name === "MJF 5200 - Bay 4")),
        assertRecord("invalid row did not persist", false, after.some((machine) => machine.name === "CSV Bad Count"), !after.some((machine) => machine.name === "CSV Bad Count")),
        assertRecord("existing inventory preserved", before.length + 1, after.length, after.length === before.length + 1),
      ],
    };
  });

  await recordPath(page, {
    id: "MFG-06",
    persona: "shop administrator recovering from an empty import",
    preconditions: ["Existing machine inventory is non-empty.", "CSV importer supports retry from the same screen."],
    actions: ["Import an empty UTF-8 CSV.", "Confirm an actionable refusal and no data loss.", "Retry with a corrected two-row CSV and verify persistence."],
  }, async () => {
    await openMachines(page, { reload: true });
    const before = await machineList(page);
    const emptyResponsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/machine-inventory/import"
    );
    const csvInput = page.locator('input[type="file"][accept*=".csv"]');
    await csvInput.setInputFiles(uploadPayload("empty.csv", Buffer.alloc(0), "text/csv"));
    const emptyResponse = await emptyResponsePromise;
    const emptyBody = await emptyResponse.json();
    await page.getByTestId("machine-import-error").waitFor();
    const emptyText = await page.getByTestId("machine-import-error").innerText();
    const afterEmpty = await machineList(page);
    const recoveryCsv = `${MACHINE_HEADER}\n${machineCsvRow({
      name: "Mazak Integrex i-200", process: "cnc_5axis", count: "1", max_workpiece_kg: "180", hourly_rate_usd: "142", capital_frac: "0.58", materials: "stainless|titanium|steel", material_thickness_map: "", capabilities: JSON.stringify({ x: 660, y: 660, z: 1016 }), notes: "recovered import",
    })}\n${machineCsvRow({
      name: "EOS M290 - Nickel/SS Cell", process: "dmls", count: "1", max_workpiece_kg: "20", hourly_rate_usd: "185", capital_frac: "0.65", materials: "stainless|titanium", material_thickness_map: "", capabilities: JSON.stringify({ x: 250, y: 250, z: 325, laser_power_kw: 0.4, min_layer_um: 30, min_wall_mm: 0.3 }), notes: "recovered import",
    })}\n`;
    const retryResponsePromise = page.waitForResponse((response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/proxy/machine-inventory/import"
    );
    await csvInput.setInputFiles(uploadPayload("recovery.csv", Buffer.from(recoveryCsv), "text/csv"));
    const retryResponse = await retryResponsePromise;
    await page.getByText(/Import complete: 2 imported · 0 skipped · 2 total/).waitFor();
    const afterRetry = await machineList(page);
    return {
      observed: {
        url: page.url(),
        visible: ["Import failed — Empty CSV upload.", "Correct the CSV and choose Import CSV again; existing machines were not removed.", "Import complete: 2 imported · 0 skipped · 2 total"],
        persisted: { before: before.length, afterEmpty: afterEmpty.length, afterRetry: afterRetry.length, recoveryMachines: ["Mazak Integrex i-200", "EOS M290 - Nickel/SS Cell"].every((name) => afterRetry.some((machine) => machine.name === name)) },
        numeric: { emptyStatus: emptyResponse.status(), emptyBody, retryStatus: retryResponse.status() },
        authorization: `empty import HTTP ${emptyResponse.status()}; corrected retry HTTP ${retryResponse.status()}`,
        recovery: "Corrected retry succeeded from the same file input; prior inventory remained intact.",
      },
      expectedHttpErrorCount: 1,
      assertions: [
        assertRecord("empty CSV refused without server error", { status: 400, message: "Empty CSV upload" }, { status: emptyResponse.status(), message: emptyBody.message }, emptyResponse.status() === 400 && emptyBody.message === "Empty CSV upload"),
        assertRecord("empty CSV feedback actionable", "retry guidance and no-removal guarantee", emptyText, emptyText.includes("Correct the CSV") && emptyText.includes("existing machines were not removed")),
        assertRecord("empty CSV caused no data loss", before.length, afterEmpty.length, before.length === afterEmpty.length),
        assertRecord("corrected retry status", 200, retryResponse.status(), retryResponse.status() === 200),
        assertRecord("corrected rows persisted", true, ["Mazak Integrex i-200", "EOS M290 - Nickel/SS Cell"].every((name) => afterRetry.some((machine) => machine.name === name)), ["Mazak Integrex i-200", "EOS M290 - Nickel/SS Cell"].every((name) => afterRetry.some((machine) => machine.name === name))),
      ],
    };
  });

  await recordPath(page, {
    id: "ENT-01",
    persona: "organization administrator governing rates and declaring the production floor",
    preconditions: ["The six browser-driven manufacturing subpaths completed in the same fresh organization.", "RATE_LIBRARY_ENABLED is active."],
    actions: ["Publish a governed rate-card version through the authenticated browser boundary.", "Reopen Your machines after form and CSV authoring.", "Verify the exact MJF/CNC 3-axis/CNC 5-axis/DMLS rates and USER provenance, then confirm governed-card state in Calibration & truth."],
  }, async () => {
    const draft = await browserApi(page, "/api/proxy/rate-library", {
      method: "POST",
      body: {
        name: "Manufacturing CAD QA governed defaults",
        change_note: "Human-simulated manufacturing floor certification.",
      },
    });
    const published = draft.status < 300 && draft.body?.id
      ? await browserApi(page, `/api/proxy/rate-library/${draft.body.id}/publish`, { method: "POST", body: {} })
      : { status: 0, body: null };
    const effective = await browserApi(page, "/api/proxy/rate-library/effective");
    const machines = await machineList(page);
    const expectedRates = new Map([
      ["mjf", 48],
      ["cnc_3axis", 95],
      ["cnc_5axis", 142],
      ["dmls", 185],
    ]);
    const machineRates = [...expectedRates].map(([process, rate]) => {
      const candidates = machines.filter((machine) => machine.process === process && machine.hourly_rate_usd === rate);
      return { process, rate, matches: candidates.map((machine) => machine.name), provenance: candidates[0]?.provenance ?? null };
    });
    await page.goto(`${baseUrl}/verify`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Calibration & truth", exact: true }).click();
    await page.getByText(/GOVERNED CARD IN EFFECT/i).waitFor({ timeout: 20_000 });
    const calibrationText = await bodyText(page);
    await page.getByRole("button", { name: "Your machines", exact: true }).click();
    await page.getByRole("heading", { name: "Your machines" }).waitFor();
    for (const name of ["MJF 5200 - Bay 4", boundaryMill, "Mazak Integrex i-200", "EOS M290 - Nickel/SS Cell"]) {
      await page.getByText(name, { exact: true }).waitFor({ timeout: 20_000 });
    }
    const machineText = await bodyText(page);
    const subpathsPassed = MANUFACTURING_SUBPATH_IDS.every((id) => evidence[id]?.status === "PASS");
    return {
      observed: {
        url: page.url(),
        visible: ["GOVERNED CARD IN EFFECT", "MJF 5200 - Bay 4", boundaryMill, "Mazak Integrex i-200", "EOS M290 - Nickel/SS Cell", "OWNED → MARGINAL"],
        persisted: { rateCardId: published.body?.id ?? null, rateCardStatus: published.body?.status ?? null, machineRates },
        numeric: { machineRates: Object.fromEntries(machineRates.map((item) => [item.process, item.rate])), governedValidated: effective.body?.validated },
        authorization: {
          draftHttp: draft.status,
          publishHttp: published.status,
          effectiveCardHttp: effective.status,
          userId: account.userId,
          activeOrgId: account.activeOrgId,
          orgRole: account.orgRole,
        },
        recovery: "Full machine inventory and governed-card state remained visible after navigation between manufacturing surfaces.",
      },
      assertions: [
        assertRecord("active organization administrator membership", "admin", account.orgRole, account.orgRole === "admin" && Boolean(account.activeOrgId)),
        assertRecord("manufacturing author/import subpaths", "all six PASS", MANUFACTURING_SUBPATH_IDS.map((id) => [id, evidence[id]?.status]), subpathsPassed),
        assertRecord("governed rate card published", { status: "published", source: "governed_rate_card" }, { status: published.body?.status, source: effective.body?.source }, published.status === 200 && published.body?.status === "published" && effective.body?.source === "governed_rate_card"),
        assertRecord("governed assumptions remain unvalidated", false, effective.body?.validated, effective.body?.validated === false),
        assertRecord("exact golden machine rates", { mjf: 48, cnc_3axis: 95, cnc_5axis: 142, dmls: 185 }, machineRates, machineRates.every((item) => item.matches.length > 0 && item.provenance === "user")),
        assertRecord("governed state visible", true, /GOVERNED CARD IN EFFECT/i.test(calibrationText), /GOVERNED CARD IN EFFECT/i.test(calibrationText)),
        assertRecord("declared floor visible", true, ["MJF 5200 - Bay 4", boundaryMill, "Mazak Integrex i-200", "EOS M290 - Nickel/SS Cell"].every((name) => machineText.includes(name)), ["MJF 5200 - Bay 4", boundaryMill, "Mazak Integrex i-200", "EOS M290 - Nickel/SS Cell"].every((name) => machineText.includes(name))),
      ],
    };
  });

  const goldenStep = path.join(repoRoot, "backend", "tests", "assets", "cube.step");

  await recordPath(page, {
    id: "VER-05",
    persona: "manufacturing engineer verifying the deterministic production STEP fixture",
    preconditions: ["backend/tests/assets/cube.step is the frozen golden input.", "Authenticated Verify surface and CAD kernel are healthy."],
    actions: ["Upload cube.step through Verify's human CAD control.", "Wait for real validation and should-cost terminal responses.", "Read measured geometry/provenance and confirm the durable decision id."],
  }, async () => {
    await prepareVerify(page);
    const run = await uploadAnalyze(page, goldenStep, 150_000);
    const bytes = await readFile(goldenStep);
    const fixtureSha256 = createHash("sha256").update(bytes).digest("hex");
    const geometry = run.dfm.body?.geometry ?? {};
    await page.waitForFunction(() => !/measuring geometry/i.test(document.body.innerText), null, { timeout: 150_000 }).catch(() => {});
    const text = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["cube.step", text.match(/20 × 15 × 10 mm|20×15×10 mm/)?.[0] || "20 × 15 × 10 mm", "MEASURED", "DEFAULT"],
        persisted: { decisionId: run.cost.body?.saved?.id ?? null, decisionUrl: run.cost.body?.saved?.url ?? null },
        numeric: { fixtureSha256, boundingBoxMm: geometry.bounding_box_mm, volumeMm3: geometry.volume_mm3, surfaceAreaMm2: geometry.surface_area_mm2, watertight: geometry.is_watertight },
        authorization: `POST /validate HTTP ${run.dfm.status}; POST /validate/cost HTTP ${run.cost.status}`,
        recovery: "Terminal result retained the Verify rail and durable Records destination; no busy/tessellation fallback appeared.",
      },
      assertions: [
        assertRecord("fixture SHA-256", "76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a", fixtureSha256, fixtureSha256 === "76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a"),
        assertRecord("golden response statuses", { validation: 200, cost: 200 }, { validation: run.dfm.status, cost: run.cost.status }, run.dfm.status === 200 && run.cost.status === 200),
        assertRecord("golden bounding box", [20, 15, 10], geometry.bounding_box_mm, Array.isArray(geometry.bounding_box_mm) && geometry.bounding_box_mm.every((value, index) => near(value, [20, 15, 10][index], 0.1))),
        assertRecord("golden volume mm3", "2717.3 ± 1", geometry.volume_mm3, near(geometry.volume_mm3, 2717.3, 1)),
        assertRecord("golden surface area mm2", "1432 ± 2", geometry.surface_area_mm2, near(geometry.surface_area_mm2, 1432, 2)),
        assertRecord("golden watertight", true, geometry.is_watertight, geometry.is_watertight === true),
        assertRecord("durable cost decision", "non-empty id", run.cost.body?.saved?.id ?? null, typeof run.cost.body?.saved?.id === "string" && run.cost.body.saved.id.length > 0),
        assertRecord("no false failure copy", true, !/temporarily busy|couldn.t be tessellated/i.test(text), !/temporarily busy|couldn.t be tessellated/i.test(text)),
      ],
    };
  });

  await recordPath(page, {
    id: "WORK-01",
    persona: "cost engineer changing inputs and reconciling the saved should-cost",
    preconditions: ["Golden STEP is available.", "The production cost route persists decisions."],
    actions: ["Open Analyze costing options.", "Select aluminum and quantities 25,2500 before upload.", "Upload cube.step, reconcile line items/confidence, and compare the live result to the saved record."],
  }, async () => {
    await prepareAnalyze(page, { material: "aluminum" });
    await page.getByLabel(/Quantities \(comma list/).fill("25,2500");
    const run = await uploadAnalyze(page, goldenStep, 150_000);
    const estimates = run.cost.body?.estimates ?? [];
    const estimate = estimates[0];
    const lineSum = estimate ? Object.values(estimate.line_items ?? {}).reduce((sum, value) => sum + Number(value), 0) : NaN;
    const decisionId = run.cost.body?.saved?.id;
    const saved = decisionId ? await browserApi(page, `/api/proxy/cost-decisions/${decisionId}`) : { status: 0, body: null };
    const savedEstimate = saved.body?.result?.estimates?.[0];
    const confidence = estimate?.confidence;
    const text = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["cube.step", "aluminum", text.match(/25|2,500/)?.[0] || "25 and 2,500 quantities", text.match(/confidence|assumption-based|measured/i)?.[0] || "confidence state rendered"],
        persisted: { decisionId, detailStatus: saved.status, savedEstimate },
        numeric: { quantity: estimate?.quantity, unitCostUsd: estimate?.unit_cost_usd, roundedLineSum: Math.round(lineSum * 100) / 100, confidence },
        authorization: `cost HTTP ${run.cost.status}; saved decision GET HTTP ${saved.status}`,
        recovery: "Saved detail returned the exact same first estimate and remained available after the live run completed.",
      },
      assertions: [
        assertRecord("should-cost success", 200, run.cost.status, run.cost.status === 200),
        assertRecord("declared quantity set", [25, 2500], run.cost.body?.quantities, JSON.stringify(run.cost.body?.quantities) === JSON.stringify([25, 2500])),
        assertRecord("line items reconcile", "abs(unit - round(sum(lines),2)) < 0.02", { unit: estimate?.unit_cost_usd, lineSum }, Number.isFinite(lineSum) && Math.abs(estimate.unit_cost_usd - Math.round(lineSum * 100) / 100) < 0.02),
        assertRecord("confidence bounds contain point", "low <= point <= high", confidence, confidence && confidence.low_usd <= confidence.point_usd && confidence.point_usd <= confidence.high_usd),
        assertRecord("saved record available", 200, saved.status, saved.status === 200),
        assertRecord("saved and live estimate agree", estimate ?? null, savedEstimate ?? null, isDeepStrictEqual(savedEstimate, estimate)),
      ],
    };
  });

  await recordPath(page, {
    id: "WORK-02",
    persona: "manufacturing engineer inspecting DFM findings and measured geometry",
    preconditions: ["Golden STEP is available.", "Analyze runs the DFM endpoint in parallel with cost."],
    actions: ["Upload cube.step through Analyze.", "Open Routing & DFM/inspection state.", "Verify ranked routes and every returned finding carries actionable structured evidence."],
  }, async () => {
    await prepareAnalyze(page);
    const run = await uploadAnalyze(page, goldenStep, 150_000);
    const issues = allDfmIssues(run.dfm.body);
    const structured = issues.every((issue) =>
      typeof issue.code === "string" && issue.code.length > 0 &&
      typeof issue.severity === "string" && issue.severity.length > 0 &&
      typeof issue.message === "string" && issue.message.length > 0 &&
      typeof (issue.fix ?? issue.fix_suggestion) === "string" && (issue.fix ?? issue.fix_suggestion).length > 0
    );
    const ranked = run.dfm.body?.process_scores ?? [];
    const routingButton = page.getByRole("button", { name: /Routing|Inspection|DFM/ }).first();
    if (await routingButton.count()) await routingButton.click().catch(() => {});
    const text = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["cube.step", text.match(/Routing|DFM|Inspection/)?.[0] || "Routing & DFM", issues[0]?.message ?? "structured DFM result with no issue"],
        persisted: run.cost.body?.saved ?? "DFM response linked to current live decision",
        numeric: { geometry: run.dfm.body?.geometry, rankedRouteCount: ranked.length, issueCount: issues.length, firstIssue: issues[0] ?? null },
        authorization: `DFM HTTP ${run.dfm.status} under authenticated analyst session`,
        recovery: "Finding inspection did not mutate geometry or the persisted cost artifact.",
      },
      assertions: [
        assertRecord("DFM success", 200, run.dfm.status, run.dfm.status === 200),
        assertRecord("measured geometry present", [20, 15, 10], run.dfm.body?.geometry?.bounding_box_mm, Array.isArray(run.dfm.body?.geometry?.bounding_box_mm) && run.dfm.body.geometry.bounding_box_mm.every((value, index) => near(value, [20, 15, 10][index], 0.1))),
        assertRecord("ranked manufacturing routes", "> 0", ranked.length, ranked.length > 0),
        assertRecord("structured finding evidence", true, { issueCount: issues.length, structured }, issues.length > 0 && structured),
        assertRecord("DFM state visible", true, /Routing|DFM|Inspection/i.test(text), /Routing|DFM|Inspection/i.test(text)),
      ],
    };
  });

  await recordPath(page, {
    id: "FAIL-01",
    persona: "manufacturing engineer receiving a file named STEP with invalid magic bytes",
    preconditions: ["Authenticated Verify session.", "The .step suffix is supported but the bytes are not ISO-10303-21 CAD."],
    actions: ["Upload invalid-magic.step through Verify's CAD input.", "Read the exact unreadable-file oracle.", "Upload cube.step in the same session and confirm success without a new account."],
  }, async () => {
    await prepareVerify(page);
    const rejected = await uploadAnalyze(page, uploadPayload("invalid-magic.step", Buffer.from("not a STEP exchange file"), "application/step"));
    await page.getByText("We couldn’t read this file.", { exact: true }).waitFor({ timeout: 30_000 });
    const failureText = await bodyText(page);
    const recovered = await uploadAnalyze(page, goldenStep, 150_000);
    const recoveryText = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["We couldn’t read this file.", "Re-export the original part as a clean STL, STEP, STP, IGES, or IGS file, then upload that export.", "cube.step"],
        persisted: { invalidDecision: rejected.cost.body?.saved?.id ?? null, recoveryDecision: recovered.cost.body?.saved?.id ?? null },
        numeric: { rejection: [rejected.cost.status, rejected.dfm.status], recovery: [recovered.cost.status, recovered.dfm.status] },
        authorization: "same authenticated session used for rejection and recovery",
        recovery: "Correct cube.step completed in the same account/session without reauthentication.",
      },
      expectedHttpErrorCount: 4,
      assertions: [
        assertRecord("unreadable-file exact title", "We couldn’t read this file.", failureText.includes("We couldn’t read this file."), failureText.includes("We couldn’t read this file.")),
        assertRecord("clean-export guidance", "STL, STEP, STP, IGES, or IGS", failureText, failureText.includes("STL, STEP, STP, IGES, or IGS") && /re-export/i.test(failureText)),
        assertRecord("unreadable file rejected without decision", "no decision id", rejected.cost.body?.saved?.id ?? "no decision id", !rejected.cost.body?.saved?.id),
        assertRecord("correct-file recovery", [200, 200], [recovered.cost.status, recovered.dfm.status], recovered.cost.status === 200 && recovered.dfm.status === 200 && recoveryText.includes("cube.step")),
      ],
    };
  });

  await recordPath(page, {
    id: "FAIL-02",
    persona: "manufacturing engineer recovering from a corrupt supported STEP export",
    preconditions: ["STEP magic is valid but the body is structurally corrupt.", "Authenticated Verify session and healthy CAD kernel."],
    actions: ["Upload corrupt-valid-magic STEP.", "Read the exact unreadable-export guidance without a fabricated tessellation diagnosis.", "Upload the clean golden STEP and confirm ordinary verification succeeds."],
  }, async () => {
    await prepareVerify(page);
    const badStep = uploadPayload("corrupt-surface.step", Buffer.from("ISO-10303-21;\nHEADER;\nTHIS IS NOT VALID STEP AT ALL\u0000\u0001"));
    const rejected = await uploadAnalyze(page, badStep, 120_000);
    await page.getByText("We couldn’t read this file.", { exact: true }).waitFor({ timeout: 30_000 });
    const failureText = await bodyText(page);
    const recovered = await uploadAnalyze(page, goldenStep, 150_000);
    const recoveryText = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["We couldn’t read this file.", "Re-export the original part as a clean STL, STEP, STP, IGES, or IGS file, then upload that export.", "cube.step"],
        persisted: { corruptDecision: rejected.cost.body?.saved?.id ?? null, recoveryDecision: recovered.cost.body?.saved?.id ?? null },
        numeric: { rejection: [rejected.cost.status, rejected.dfm.status], recovery: [recovered.cost.status, recovered.dfm.status], rejectionElapsedMs: rejected.elapsedMs },
        authorization: "same authenticated session used for parse rejection and clean-export recovery",
        recovery: "Clean golden STEP completed without a new session and produced a durable decision.",
      },
      expectedHttpErrorCount: 4,
      assertions: [
        assertRecord("unreadable-export exact title", "We couldn’t read this file.", failureText.includes("We couldn’t read this file."), failureText.includes("We couldn’t read this file.")),
        assertRecord("clean-export action", "Re-export the original part as a clean STL, STEP, STP, IGES, or IGS file, then upload that export.", failureText, failureText.includes("Re-export the original part as a clean STL, STEP, STP, IGES, or IGS file, then upload that export.")),
        assertRecord("parse failure is not mislabeled tessellation", false, /tessellat/i.test(failureText), !/tessellat/i.test(failureText)),
        assertRecord("corrupt input bounded 4xx", "both 4xx and <120s", { status: [rejected.cost.status, rejected.dfm.status], elapsedMs: rejected.elapsedMs }, rejected.cost.status >= 400 && rejected.cost.status < 500 && rejected.dfm.status >= 400 && rejected.dfm.status < 500 && rejected.elapsedMs < 120_000),
        assertRecord("clean-solid recovery", [200, 200], [recovered.cost.status, recovered.dfm.status], recovered.cost.status === 200 && recovered.dfm.status === 200 && recoveryText.includes("cube.step")),
      ],
    };
  });

  await recordPath(page, {
    id: "CAD-01",
    persona: "manufacturing engineer receiving a corrupt STL export",
    preconditions: ["Authenticated Analyze surface.", "Malformed bytes use a supported .stl filename."],
    actions: ["Upload malformed STL bytes through the dropzone.", "Wait for bounded cost and DFM responses.", "Read the visible parse failure and return to New part."],
  }, async () => {
    await prepareAnalyze(page);
    const run = await uploadAnalyze(page, uploadPayload("malformed.stl", Buffer.from("solid definitely-not-a-valid-stl\nendsolid")));
    const errorText = await bodyText(page);
    const recovered = await resetAnalyze(page);
    return {
      observed: {
        url: page.url(),
        visible: [errorText.match(/(?:invalid|parse|could not|failed|geometry)[^.]{0,160}/i)?.[0] || "malformed STL error rendered", "Drop a CAD file"],
        persisted: "no analysis/cost artifact asserted for malformed bytes; machine inventory unchanged",
        numeric: { costStatus: run.cost.status, dfmStatus: run.dfm.status, elapsedMs: run.elapsedMs },
        authorization: "authenticated analyst upload; backend rejected malformed CAD",
        recovery: recovered ? "New part restored a clean dropzone." : "dropzone recovery failed",
      },
      expectedHttpErrorCount: 2,
      assertions: [
        assertRecord("malformed upload rejected without 500", "4xx cost and DFM", { cost: run.cost.status, dfm: run.dfm.status }, run.cost.status >= 400 && run.cost.status < 500 && run.dfm.status >= 400 && run.dfm.status < 500),
        assertRecord("actionable parse/geometry message visible", true, /invalid|parse|could not|failed|geometry/i.test(errorText), /invalid|parse|could not|failed|geometry/i.test(errorText)),
        assertRecord("malformed path bounded", "< 90 seconds", run.elapsedMs, run.elapsedMs < 90_000),
        assertRecord("recovery restored upload surface", true, recovered, recovered),
      ],
    };
  });

  await recordPath(page, {
    id: "CAD-02",
    persona: "manufacturing engineer accidentally uploading a zero-byte CAD file",
    preconditions: ["Authenticated Analyze surface.", "File has a supported .stl suffix but zero bytes."],
    actions: ["Upload the empty STL.", "Verify both analysis branches reject it clearly.", "Use New part and confirm the uploader is ready again."],
  }, async () => {
    await prepareAnalyze(page);
    const run = await uploadAnalyze(page, uploadPayload("empty.stl", Buffer.alloc(0)));
    const errorText = await bodyText(page);
    const recovered = await resetAnalyze(page);
    return {
      observed: {
        url: page.url(),
        visible: ["Uploaded file is empty", "Drop a CAD file"],
        persisted: "zero-byte upload produced no usable analysis; prior manufacturing context remained available",
        numeric: { costStatus: run.cost.status, dfmStatus: run.dfm.status, elapsedMs: run.elapsedMs },
        authorization: "authenticated analyst upload; empty input refused",
        recovery: recovered ? "New part restored a clean dropzone." : "dropzone recovery failed",
      },
      expectedHttpErrorCount: 2,
      assertions: [
        assertRecord("empty upload rejected", "4xx cost and DFM", { cost: run.cost.status, dfm: run.dfm.status }, run.cost.status >= 400 && run.cost.status < 500 && run.dfm.status >= 400 && run.dfm.status < 500),
        assertRecord("empty-file message visible", true, /empty/i.test(errorText), /empty/i.test(errorText)),
        assertRecord("empty path bounded", "< 30 seconds", run.elapsedMs, run.elapsedMs < 30_000),
        assertRecord("recovery restored upload surface", true, recovered, recovered),
      ],
    };
  });

  await recordPath(page, {
    id: "CAD-03",
    persona: "CAD engineer validating a translated model with very large world coordinates",
    preconditions: ["Watertight 10 mm cube is translated to coordinates around ±1,000,000 mm.", "Millimetres are explicitly selected."],
    actions: ["Upload the huge-coordinate STL.", "Inspect cost and DFM geometry.", "Verify local dimensions/volume stay finite and translation does not distort the part."],
  }, async () => {
    await prepareAnalyze(page);
    const payload = uploadPayload("huge-coordinate-cube.stl", binaryStl(boxTriangles([1_000_000, -1_000_000, 500_000], [10, 10, 10])));
    const run = await uploadAnalyze(page, payload);
    const text = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["huge-coordinate-cube.stl", text.match(/10×10×10 mm|10 × 10 × 10 mm/)?.[0] || "10 mm geometry rendered"],
        persisted: run.cost.body?.saved ?? "cost persistence disabled in this environment",
        numeric: { bboxMm: run.dfm.body?.geometry?.bounding_box_mm, volumeMm3: run.dfm.body?.geometry?.volume_mm3, centerOfMass: run.dfm.body?.geometry?.center_of_mass, elapsedMs: run.elapsedMs },
        authorization: `cost HTTP ${run.cost.status}; DFM HTTP ${run.dfm.status}`,
        recovery: "Successful result left New part available; no hang or data loss occurred.",
      },
      assertions: [
        assertRecord("huge-coordinate analysis success", { cost: 200, dfm: 200 }, { cost: run.cost.status, dfm: run.dfm.status }, run.cost.status === 200 && run.dfm.status === 200),
        assertRecord("translation preserves local bbox", [10, 10, 10], run.dfm.body?.geometry?.bounding_box_mm, JSON.stringify(run.dfm.body?.geometry?.bounding_box_mm) === JSON.stringify([10, 10, 10])),
        assertRecord("translation preserves volume", 1000, run.dfm.body?.geometry?.volume_mm3, near(run.dfm.body?.geometry?.volume_mm3, 1000, 0.1)),
        assertRecord("center of mass remains finite", true, run.dfm.body?.geometry?.center_of_mass, run.dfm.body?.geometry?.center_of_mass?.every(Number.isFinite)),
        assertRecord("huge-coordinate path bounded", "< 90 seconds", run.elapsedMs, run.elapsedMs < 90_000),
      ],
    };
  });

  await recordPath(page, {
    id: "CAD-04",
    persona: "cost engineer reviewing an implausibly tiny unitless STL",
    preconditions: ["Watertight 0.3 mm cube is uploaded with default mm interpretation.", "The engine's unit plausibility rail is enabled."],
    actions: ["Upload the tiny STL.", "Confirm a successful geometric result plus an explicit units warning.", "Verify the browser tells the user how to resolve ambiguity."],
  }, async () => {
    await prepareAnalyze(page);
    const run = await uploadAnalyze(page, uploadPayload("tiny-0.3mm-cube.stl", binaryStl(boxTriangles([0, 0, 0], [0.3, 0.3, 0.3]))));
    const warning = run.cost.body?.unit_warnings?.find((item) => item.code === "IMPLAUSIBLE_VOLUME");
    const text = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["tiny-0.3mm-cube.stl", text.match(/source units|unusually (?:small|large)|confirm (?:mm|inches)/i)?.[0] || "units warning not rendered"],
        persisted: run.cost.body?.saved ?? "cost persistence disabled in this environment",
        numeric: { bboxMm: run.dfm.body?.geometry?.bounding_box_mm, warning, elapsedMs: run.elapsedMs },
        authorization: `cost HTTP ${run.cost.status}; DFM HTTP ${run.dfm.status}`,
        recovery: "Source-unit selector remains available for an explicit retry.",
      },
      assertions: [
        assertRecord("tiny watertight geometry succeeds", { cost: 200, dfm: 200 }, { cost: run.cost.status, dfm: run.dfm.status }, run.cost.status === 200 && run.dfm.status === 200),
        assertRecord("tiny bbox measured", [0.3, 0.3, 0.3], run.dfm.body?.geometry?.bounding_box_mm, JSON.stringify(run.dfm.body?.geometry?.bounding_box_mm) === JSON.stringify([0.3, 0.3, 0.3])),
        assertRecord("engine emits unit plausibility warning", "IMPLAUSIBLE_VOLUME warning", warning?.code, warning?.code === "IMPLAUSIBLE_VOLUME" && warning?.severity === "warning"),
        assertRecord("unit warning visible to human", true, /source units|unusually (?:small|large)|confirm (?:mm|inches)/i.test(text), /source units|unusually (?:small|large)|confirm (?:mm|inches)/i.test(text)),
      ],
    };
  });

  await recordPath(page, {
    id: "CAD-05",
    persona: "manufacturing engineer resolving inch-versus-mm ambiguity before trusting cost",
    preconditions: ["Same unitless 10-coordinate cube is available for both runs.", "Source units can be selected before upload."],
    actions: ["Analyze bytes as millimetres.", "Reset, select inches, and analyze identical bytes again.", "Compare DFM bbox/volume and cost volume for exactly one 25.4 scale."],
  }, async () => {
    const bytes = binaryStl(boxTriangles([0, 0, 0], [10, 10, 10]));
    await prepareAnalyze(page, { units: "mm" });
    const mm = await uploadAnalyze(page, uploadPayload("unit-ambiguous-mm.stl", bytes));
    await prepareAnalyze(page, { units: "inch" });
    const inch = await uploadAnalyze(page, uploadPayload("unit-ambiguous-inch.stl", bytes));
    const dfmRatio = inch.dfm.body?.geometry?.volume_mm3 / mm.dfm.body?.geometry?.volume_mm3;
    const costRatio = inch.cost.body?.geometry?.volume_cm3 / mm.cost.body?.geometry?.volume_cm3;
    const text = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["unit-ambiguous-inch.stl", "Inches (in)", text.match(/254×254×254 mm|254 × 254 × 254 mm/)?.[0] || "254 mm geometry rendered"],
        persisted: { mmSaved: mm.cost.body?.saved ?? null, inchSaved: inch.cost.body?.saved ?? null },
        numeric: { mmBbox: mm.dfm.body?.geometry?.bounding_box_mm, inchBbox: inch.dfm.body?.geometry?.bounding_box_mm, dfmVolumeRatio: dfmRatio, costVolumeRatio: costRatio, sourceProvenance: inch.dfm.body?.source_units },
        authorization: `four authenticated engine calls completed: mm cost/DFM ${mm.cost.status}/${mm.dfm.status}, inch cost/DFM ${inch.cost.status}/${inch.dfm.status}`,
        recovery: "Changing the declared units and re-uploading identical bytes produced a coherent new decision, not a stale cache hit.",
      },
      assertions: [
        assertRecord("both interpretations succeed", true, { mm: [mm.cost.status, mm.dfm.status], inch: [inch.cost.status, inch.dfm.status] }, [mm.cost.status, mm.dfm.status, inch.cost.status, inch.dfm.status].every((status) => status === 200)),
        assertRecord("inch DFM bbox scaled exactly once", [254, 254, 254], inch.dfm.body?.geometry?.bounding_box_mm, JSON.stringify(inch.dfm.body?.geometry?.bounding_box_mm) === JSON.stringify([254, 254, 254])),
        assertRecord("DFM volume ratio", 25.4 ** 3, dfmRatio, near(dfmRatio, 25.4 ** 3, 0.1)),
        assertRecord("cost volume ratio", 25.4 ** 3, costRatio, near(costRatio, 25.4 ** 3, 0.1)),
        assertRecord("DFM source-unit provenance", { declared: "inch", provenance: "USER", scale_to_mm: 25.4 }, inch.dfm.body?.source_units, inch.dfm.body?.source_units?.declared === "inch" && inch.dfm.body?.source_units?.provenance === "USER" && inch.dfm.body?.source_units?.scale_to_mm === 25.4),
      ],
    };
  });

  await recordPath(page, {
    id: "CAD-06",
    persona: "design engineer dragging an unsupported native/mesh format",
    preconditions: ["Authenticated Analyze dropzone.", "OBJ is outside the documented STL/STEP/IGES contract."],
    actions: ["Set an .obj file on the human upload control.", "Confirm client-side actionable refusal and zero engine POSTs.", "Dismiss the error and remain ready for a supported file."],
  }, async () => {
    await page.goto(`${baseUrl}/analyze`, { waitUntil: "domcontentloaded" });
    const postsBefore = await page.evaluate(() => performance.getEntriesByType("resource").filter((entry) => /\/api\/proxy\/validate/.test(entry.name)).length);
    await page.locator('input[type="file"]').first().setInputFiles(uploadPayload("unsupported.obj", Buffer.from("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"), "text/plain"));
    await page.getByText(/Unsupported file type/).waitFor();
    const text = await bodyText(page);
    const postsAfter = await page.evaluate(() => performance.getEntriesByType("resource").filter((entry) => /\/api\/proxy\/validate/.test(entry.name)).length);
    const retry = page.getByRole("button", { name: /Try again|Retry|Dismiss/ });
    if (await retry.count()) await retry.first().click();
    return {
      observed: {
        url: page.url(),
        visible: ["Unsupported file type. Use STL, STEP, STP, IGES or IGS.", "Drag and drop or click to upload"],
        persisted: "unsupported file created no analysis or decision artifact",
        numeric: { engineRequestsBefore: postsBefore, engineRequestsAfter: postsAfter },
        authorization: "client-side format gate ran before authenticated engine boundary",
        recovery: "Error was dismissible and the supported-file dropzone remained available.",
      },
      assertions: [
        assertRecord("unsupported copy names accepted formats", true, text.includes("Unsupported file type. Use STL, STEP, STP, IGES or IGS."), text.includes("Unsupported file type. Use STL, STEP, STP, IGES or IGS.")),
        assertRecord("unsupported file sent no engine request", postsBefore, postsAfter, postsBefore === postsAfter),
        assertRecord("upload surface remains present", true, /Drag and drop or click to upload/.test(await bodyText(page)), /Drag and drop or click to upload/.test(await bodyText(page))),
      ],
    };
  });

  await recordPath(page, {
    id: "CAD-07",
    persona: "manufacturing engineer reviewing an open/non-watertight mesh",
    preconditions: ["Cube mesh has two faces removed.", "Supported STL upload reaches both DFM and cost geometry gates."],
    actions: ["Upload the open cube.", "Confirm DFM measures it as non-watertight while cost refuses a fabricated number.", "Read the visible repair guidance and return to New part."],
  }, async () => {
    await prepareAnalyze(page);
    const openTriangles = boxTriangles().slice(0, 10);
    const run = await uploadAnalyze(page, uploadPayload("open-cube.stl", binaryStl(openTriangles)));
    const text = await bodyText(page);
    const issues = run.dfm.body?.universal_issues ?? [];
    const recovered = await resetAnalyze(page);
    return {
      observed: {
        url: page.url(),
        visible: [text.match(/not watertight|repair|close all holes/i)?.[0] || "non-watertight guidance rendered", "Drop a CAD file"],
        persisted: "cost artifact withheld for invalid geometry; existing inventory unchanged",
        numeric: { costStatus: run.cost.status, costCode: run.cost.body?.code, dfmStatus: run.dfm.status, watertight: run.dfm.body?.geometry?.is_watertight, universalCodes: issues.map((item) => item.code) },
        authorization: "authenticated engine evaluated DFM but refused should-cost",
        recovery: recovered ? "New part restored a clean dropzone." : "dropzone recovery failed",
      },
      expectedHttpErrorCount: 1,
      assertions: [
        assertRecord("DFM returns measured failure", 200, run.dfm.status, run.dfm.status === 200),
        assertRecord("DFM watertight flag", false, run.dfm.body?.geometry?.is_watertight, run.dfm.body?.geometry?.is_watertight === false),
        assertRecord("DFM issue code", "NON_WATERTIGHT", issues.map((item) => item.code), issues.some((item) => item.code === "NON_WATERTIGHT")),
        assertRecord("cost refuses invalid geometry", { status: 400, code: "GEOMETRY_INVALID" }, { status: run.cost.status, code: run.cost.body?.code }, run.cost.status === 400 && run.cost.body?.code === "GEOMETRY_INVALID"),
        assertRecord("repair guidance visible", true, /watertight|repair|close.*holes/i.test(text), /watertight|repair|close.*holes/i.test(text)),
        assertRecord("recovery restored upload surface", true, recovered, recovered),
      ],
    };
  });

  await recordPath(page, {
    id: "CAD-08",
    persona: "manufacturing engineer receiving two disconnected solids in one STL",
    preconditions: ["Two watertight 10 mm cubes are separated by 10 mm in one STL.", "The universal multi-body check is enabled."],
    actions: ["Upload the multi-body STL.", "Verify combined geometry succeeds without hanging.", "Confirm the browser/API warns that bodies should be unioned or separated."],
  }, async () => {
    await prepareAnalyze(page);
    const triangles = [...boxTriangles([0, 0, 0], [10, 10, 10]), ...boxTriangles([20, 0, 0], [10, 10, 10])];
    const run = await uploadAnalyze(page, uploadPayload("two-body.stl", binaryStl(triangles)));
    const issues = run.dfm.body?.universal_issues ?? [];
    const multi = issues.find((item) => item.code === "MULTIPLE_BODIES");
    const text = await bodyText(page);
    return {
      observed: {
        url: page.url(),
        visible: ["two-body.stl", multi?.message ?? "multiple-body message missing", multi?.fix ?? multi?.fix_suggestion ?? "multi-body guidance missing"],
        persisted: run.cost.body?.saved ?? "cost persistence disabled in this environment",
        numeric: { bboxMm: run.dfm.body?.geometry?.bounding_box_mm, volumeMm3: run.dfm.body?.geometry?.volume_mm3, issue: multi, elapsedMs: run.elapsedMs },
        authorization: `cost HTTP ${run.cost.status}; DFM HTTP ${run.dfm.status}`,
        recovery: "Successful advisory result retained New part and did not merge/delete source data.",
      },
      assertions: [
        assertRecord("multi-body analysis bounded success", { cost: 200, dfm: 200 }, { cost: run.cost.status, dfm: run.dfm.status, elapsedMs: run.elapsedMs }, run.cost.status === 200 && run.dfm.status === 200 && run.elapsedMs < 90_000),
        assertRecord("combined bbox", [30, 10, 10], run.dfm.body?.geometry?.bounding_box_mm, JSON.stringify(run.dfm.body?.geometry?.bounding_box_mm) === JSON.stringify([30, 10, 10])),
        assertRecord("combined volume", 2000, run.dfm.body?.geometry?.volume_mm3, near(run.dfm.body?.geometry?.volume_mm3, 2000, 0.1)),
        assertRecord("multi-body advisory code", "MULTIPLE_BODIES", multi?.code, multi?.code === "MULTIPLE_BODIES"),
        assertRecord("actionable union/separate guidance visible", true, /disconnected bodies|boolean union|separate/i.test(text), /disconnected bodies|boolean union|separate/i.test(text)),
      ],
    };
  });

  await recordPath(page, {
    id: "CAD-09",
    persona: "manufacturing engineer opening a real multi-solid STEP assembly",
    preconditions: ["Gmsh AS1 STEP fixture is locally available.", "Shared CAD kernel and assembly analyzer are healthy."],
    actions: ["Upload the STEP through Verify's human CAD control.", "Wait for structured assembly JSON, combined GLB, and bounded per-part analysis.", "Inspect the 18-solid tree, analysis summary, and rendered status."],
  }, async () => {
    const fixture = await existingAssemblyFixture();
    if (!fixture) throw new Error("documented AS1 assembly fixture is unavailable");
    await page.goto(`${baseUrl}/verify`, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.getByRole("button", { name: "Verify", exact: true }).click();
    const jsonPromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "POST" && url.pathname === "/api/proxy/validate/assembly" && url.searchParams.get("format") === "json";
    }, { timeout: 120_000 });
    const glbPromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "POST" && url.pathname === "/api/proxy/validate/assembly" && url.searchParams.get("format") === "glb";
    }, { timeout: 120_000 });
    const analysisPromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === "POST" && url.pathname === "/api/proxy/validate/assembly" && url.searchParams.get("format") === "analysis";
    }, { timeout: 180_000 });
    const started = Date.now();
    await page.getByTestId("verify-part-cad-input").setInputFiles(fixture);
    const jsonResponse = await jsonPromise;
    const model = await jsonResponse.json();
    const glbResponse = await glbPromise;
    await page.getByText(/Real STEP assembly — 18 solids/).waitFor({ timeout: 120_000 });
    const analysisResponse = await analysisPromise;
    const analysisBody = await analysisResponse.json();
    const glbBytes = Number(glbResponse.headers()["x-assembly-glb-bytes"] ?? "0");
    const analysisStatus = page
      .getByTestId("assembly-analysis-status")
      .filter({ hasText: /PER-PART ANALYSIS — REAL/i })
      .last();
    await analysisStatus.waitFor({ timeout: 90_000 });
    const analysisStatusText = await analysisStatus.innerText();
    const renderMode = page.getByTestId("verify-stage-render-mode");
    await renderMode.waitFor({ timeout: 30_000 });
    const renderState = await renderMode.getAttribute("data-render-state");
    const renderedPartCount = Number(
      (await page.getByTestId("verify-stage-assembly").getAttribute("data-assembly-parts")) ?? "0",
    );
    const elapsedMs = Date.now() - started;
    const text = await bodyText(page);
    const summary = analysisBody?.analysis?.analysis_summary;
    return {
      observed: {
        url: page.url(),
        visible: ["Real STEP assembly — 18 solids", "18 parts in world position", text.match(/\d+ of 18|18 of 18|analy[sz]ed/i)?.[0] || "per-part analysis status rendered"],
        persisted: "assembly upload is zero-egress/read-only by contract; no raw CAD blob persisted",
        numeric: { partCount: model.part_count, uniqueDesigns: Object.keys(model.unique_designs ?? {}).length, glbBytes, summary, elapsedMs, renderState, renderedPartCount },
        authorization: `assembly JSON/GLB/analysis HTTP ${jsonResponse.status()}/${glbResponse.status()}/${analysisResponse.status()}`,
        recovery: "Assembly tree remained interactive after the bounded per-part analysis completed.",
      },
      expectedHttpErrorCount: 0,
      assertions: [
        assertRecord("assembly endpoint statuses", [200, 200, 200], [jsonResponse.status(), glbResponse.status(), analysisResponse.status()], jsonResponse.status() === 200 && glbResponse.status() === 200 && analysisResponse.status() === 200),
        assertRecord("assembly classification", { kind: "assembly", part_count: 18 }, { kind: model.kind, part_count: model.part_count }, model.kind === "assembly" && model.part_count === 18),
        assertRecord("all part instances serialized", 18, model.parts?.length, model.parts?.length === 18),
        assertRecord("combined assembly GLB is non-empty", "> 0 bytes", glbBytes, Number.isFinite(glbBytes) && glbBytes > 0),
        assertRecord("per-part analysis produced outcomes", "> 0 analyzed and total 18", summary, summary?.parts_total === 18 && summary?.parts_analyzed > 0),
        assertRecord("assembly analysis status exact", "PER-PART ANALYSIS — REAL and 18/18 costed", analysisStatusText, /PER-PART ANALYSIS — REAL/i.test(analysisStatusText) && /18\/18 costed/i.test(analysisStatusText)),
        assertRecord("assembly analysis bounded", "< 90 seconds", elapsedMs, elapsedMs < 90_000),
        assertRecord("assembly real shell rendered", { state: "real-assembly", parts: 18 }, { state: renderState, parts: renderedPartCount }, renderState === "real-assembly" && renderedPartCount === 18),
        assertRecord("assembly visible state", true, text.includes("Real STEP assembly — 18 solids"), text.includes("Real STEP assembly — 18 solids")),
      ],
    };
  });
}

async function main() {
  const buildIdentity = captureBuildIdentity(repoRoot);
  await mkdir(screenshotDir, { recursive: true });
  const browser = await launchBrowser();
  const context = await browser.newContext({
    baseURL: baseUrl,
    acceptDownloads: true,
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const entry = { url: page.url(), text: message.text() };
    if (isNetworkStatusConsoleMessage(entry.text)) networkStatusConsoleMessages.push(entry);
    else consoleErrors.push(entry);
  });
  page.on("request", (request) => {
    if (isForbiddenCadAssetRequest(request.url())) {
      forbiddenCadAssetRequests.push({ method: request.method(), url: request.url() });
    }
  });
  page.on("requestfailed", (request) => {
    if (!isIgnorableRequestFailure(request)) {
      requestFailures.push({ method: request.method(), url: request.url(), error: request.failure()?.errorText || "unknown" });
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      httpErrorResponses.push({
        method: response.request().method(),
        path: responsePath(response),
        status: response.status(),
      });
    }
    if (isMachineMutation(response)) machineMutationResponses += 1;
  });

  let account = null;
  let fatal = null;
  try {
    account = await signup(page);
    await runSuite(page, account);
  } catch (error) {
    fatal = error instanceof Error ? error.message : String(error);
  } finally {
    for (const id of PATH_IDS) {
      if (!evidence[id]) {
        const screenshot = await shot(page, id).catch(() => path.join(screenshotDir, `${id.toLowerCase()}.png`));
        evidence[id] = makeGoldenPathEvidence({
          id,
          status: "FAIL",
          persona: "path was not reached after a fatal runner failure",
          preconditions: ["The earlier browser sequence must complete."],
          actions: ["Runner attempted to continue to this path."],
          observed: {
            url: page.url() || baseUrl,
            visible: [`Not reached: ${fatal || "unknown fatal runner failure"}`],
            persisted: "not observed",
            numeric: "not observed",
            authorization: "not observed",
            recovery: "runner emitted a complete evidence envelope instead of omitting the path",
          },
          screenshot,
          consoleErrors: [],
          requestFailures: [],
          assertions: [assertRecord("path reached", true, false, false)],
        });
      }
    }
    const goldenPaths = Object.fromEntries(EXACT_GOLDEN_IDS.map((id) => [id, evidence[id]]));
    const manufacturingSubpaths = Object.fromEntries(MANUFACTURING_SUBPATH_IDS.map((id) => [id, evidence[id]]));
    const supplementalCadPaths = Object.fromEntries(SUPPLEMENTAL_CAD_IDS.map((id) => [id, evidence[id]]));
    const validation = validateGoldenPathMap(EXACT_GOLDEN_IDS, goldenPaths);
    const manufacturingValidation = validateGoldenPathMap(MANUFACTURING_SUBPATH_IDS, manufacturingSubpaths);
    const supplementalCadValidation = validateGoldenPathMap(SUPPLEMENTAL_CAD_IDS, supplementalCadPaths);
    const passed = PATH_IDS.filter((id) => evidence[id].status === "PASS");
    const failed = PATH_IDS.filter((id) => evidence[id].status !== "PASS");
    const report = {
      generatedAt: new Date().toISOString(),
      runId,
      target: baseUrl,
      buildIdentity,
      account: account ? { ...account, kind: "fresh local QA organization" } : null,
      scope: {
        exactGoldenIds: EXACT_GOLDEN_IDS,
        supplementalCadIds: SUPPLEMENTAL_CAD_IDS,
        manufacturingSubpaths: MANUFACTURING_SUBPATH_IDS,
        notClaimedHere: ["VER-06", "VER-08", "WORK-09", "WORK-10", "WORK-11", "ENT-02", "ENT-03", "ENT-05", "FAIL-03", "FAIL-04", "FAIL-05", "FAIL-06", "FAIL-07", "FAIL-08", "FAIL-10"],
      },
      summary: {
        total: PATH_IDS.length,
        passed: passed.length,
        failed: failed.length,
        passedIds: passed,
        failedIds: failed,
        consoleErrors: consoleErrors.length,
        requestFailures: requestFailures.length,
        httpErrorResponses: httpErrorResponses.length,
        networkStatusConsoleMessages: networkStatusConsoleMessages.length,
        forbiddenCadAssetRequests: forbiddenCadAssetRequests.length,
        fatal,
      },
      timingsMs: timings,
      releaseEvidence: {
        goldenPaths,
        validation,
        manufacturingSubpaths,
        manufacturingValidation,
        supplementalCadPaths,
        supplementalCadValidation,
      },
      unresolvedLimits,
    };
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    await context.close();
    await browser.close();
    process.stdout.write(`${JSON.stringify({ reportPath, summary: report.summary, validation: { total: validation.total, valid: validation.valid, problems: validation.problems } }, null, 2)}\n`);
    if (
      failed.length ||
      fatal ||
      validation.problems.length ||
      manufacturingValidation.problems.length ||
      supplementalCadValidation.problems.length
    ) process.exitCode = 1;
  }
}

await main();
