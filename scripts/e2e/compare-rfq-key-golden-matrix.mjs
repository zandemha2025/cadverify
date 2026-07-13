import { execFile } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual, promisify } from "node:util";
import {
  makeGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const { strFromU8, unzipSync } = require("fflate");
const execFileAsync = promisify(execFile);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const backendRoot = path.join(repoRoot, "backend");
const fixturePath = path.join(__dirname, "compare-rfq-key-fixture.py");
const cubePath = path.join(backendRoot, "tests", "assets", "cube.step");
const appUrl = (process.env.APP_URL || "http://localhost:3000").replace(/\/+$/, "");
const apiUrl = (process.env.API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const clientIp = process.env.E2E_CLIENT_IP || "198.51.100.88";
const databaseUrl =
  process.env.DATABASE_URL ||
  "postgresql://cadverify:localdev@127.0.0.1:5432/cadverify";
const runId =
  process.env.E2E_RUN_ID ||
  "compare-rfq-key-" +
    new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(
  outputRoot,
  "screenshots",
  "compare-rfq-key-" + runId,
);
const artifactDir = path.join(outputRoot, "artifacts", "compare-rfq-key-" + runId);
const requiredIds = ["WORK-06", "WORK-08", "WORK-12"];
const tag =
  Date.now().toString(36) +
  "-" +
  process.pid +
  "-" +
  randomBytes(3).toString("hex");
const password = "ProofShape-WorkMatrix-" + randomBytes(8).toString("hex") + "-9";
const rfqTitle = "WORK-08 sourcing package " + tag;
const rfqSupplier = "QA Supplier " + tag;
const rfqNote =
  "Pinned three-decision package: approved, stale, unvalidated, and retained raw CAD.";
const artifacts = {
  json: path.join(outputRoot, "compare-rfq-key-" + runId + ".json"),
  md: path.join(outputRoot, "qa-report-compare-rfq-key-" + runId + ".md"),
  rfqZip: path.join(artifactDir, "WORK-08-rfq-package.zip"),
  supplierPdf: path.join(artifactDir, "WORK-08-supplier-brief.pdf"),
  decisionPdfs: {},
};

const pathMeta = {
  "WORK-06": {
    persona: "cost analyst comparing two durable should-cost decisions",
    preconditions: [
      "Two same-organization cost decisions contain overlapping and non-overlapping quantity recommendations.",
      "The pinned recommendations produce positive, negative, and null B-minus-A outcomes.",
    ],
    actions: [
      "Open Compare cost decisions and select A and B through the visible pickers.",
      "Read every quantity row and reconcile it to the compare API.",
      "Reload, reselect both durable decisions, and repeat the comparison.",
    ],
  },
  "WORK-08": {
    persona: "sourcing lead assembling governed supplier evidence",
    preconditions: [
      "Three selected decisions span approved, stale, unreviewed, validated, and unvalidated states.",
      "Exactly one selected decision has a retained same-organization raw CAD blob.",
    ],
    actions: [
      "Select all three decisions, request retained raw CAD, and generate the package in the browser.",
      "Reload the package list, open the durable detail, and reconcile visible counts and warnings.",
      "Download through the visible control, unzip the archive, parse CSV and JSON, and extract every PDF to text.",
    ],
  },
  "WORK-12": {
    persona: "organization administrator managing programmatic credentials",
    preconditions: [
      "The signed-in administrator has no API keys in the fresh fixture organization.",
      "The local API validates tenant-bound cv_live bearer credentials.",
    ],
    actions: [
      "Create a key and capture its one-time browser reveal.",
      "Reload to prove plaintext is gone, rotate through the visible row action, and capture the replacement once.",
      "Reject the old token, revoke the replacement, reject it, then reopen durable statuses and audit state.",
    ],
  },
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function cleanText(value) {
  return String(value == null ? "" : value).replace(/\s+/g, " ").trim();
}

function deepEqual(a, b) {
  return isDeepStrictEqual(a, b);
}

function evidenceValue(value) {
  if (value === null) return "<null>";
  if (value === undefined) return "<undefined>";
  if (value === "") return "<empty-string>";
  if (typeof value === "number" && !Number.isFinite(value)) return String(value);
  return value;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function errorCode(body) {
  return body && (body.code || (body.detail && body.detail.code))
    ? body.code || body.detail.code
    : null;
}

function escapeRegex(value) {
  return String(value).replace(/[.*+?^$()|[\]\\]/g, "\\$&");
}

function countOccurrences(haystack, needle) {
  if (!needle) return 0;
  return String(haystack).split(String(needle)).length - 1;
}

async function responseJson(response) {
  const text = await response.text();
  let body = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = text;
  }
  return {
    status: response.status(),
    body,
    text,
    headers: response.headers(),
  };
}

function parseCsv(source, label) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (quoted) {
      if (char === '"' && source[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
      continue;
    }
    if (char === '"') {
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
  if (field || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  assert(!quoted, label + " ended inside a quoted field");
  const nonempty = rows.filter((cells) => cells.some((cell) => cell !== ""));
  assert(nonempty.length >= 1, label + " contained no rows");
  const headers = nonempty[0];
  const records = nonempty.slice(1).map((cells, rowIndex) => {
    assert(
      cells.length === headers.length,
      label +
        " row " +
        (rowIndex + 2) +
        " had " +
        cells.length +
        " fields for " +
        headers.length +
        " headers",
    );
    return Object.fromEntries(headers.map((header, index) => [header, cells[index]]));
  });
  return { headers, records };
}

function zipText(entries, name) {
  assert(entries[name], "RFQ ZIP is missing " + name);
  return strFromU8(entries[name]);
}

function zipJson(entries, name) {
  return JSON.parse(zipText(entries, name));
}

class CompareRfqKeyMatrix {
  constructor() {
    this.assertions = [];
    this.steps = [];
    this.goldenPaths = {};
    this.failures = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.contexts = [];
    this.screenshots = {};
    this.startedAt = Date.now();
  }

  record(pathId, name, expected, actual, pass) {
    const item = {
      pathId,
      name,
      expected: evidenceValue(expected),
      actual: evidenceValue(actual),
      pass: Boolean(pass),
    };
    this.assertions.push(item);
    if (!item.pass) {
      throw new Error(
        name +
          ": expected " +
          JSON.stringify(item.expected) +
          ", got " +
          JSON.stringify(item.actual),
      );
    }
    return item;
  }

  equal(pathId, name, actual, expected) {
    return this.record(pathId, name, expected, actual, deepEqual(actual, expected));
  }

  ok(pathId, name, actual) {
    return this.record(pathId, name, true, Boolean(actual), Boolean(actual));
  }

  watch(page, persona) {
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const text = message.text();
      if (/favicon\.ico|ResizeObserver loop limit exceeded/i.test(text)) return;
      this.consoleErrors.push({ persona, url: page.url(), text });
    });
    page.on("pageerror", (error) => {
      this.consoleErrors.push({
        persona,
        url: page.url(),
        text: error.message,
      });
    });
    page.on("requestfailed", (request) => {
      const error = (request.failure() && request.failure().errorText) || "request failed";
      const url = request.url();
      if (
        error === "net::ERR_ABORTED" &&
        (/[?&]_rsc=/.test(url) ||
          /\/_next\/static\//.test(url) ||
          /\/icon\.svg(?:\?|$)/.test(url))
      ) {
        return;
      }
      if (/favicon\.ico|vercel\/speed-insights|\/_next\/webpack-hmr/i.test(url)) {
        return;
      }
      this.requestFailures.push({
        persona,
        url,
        method: request.method(),
        error,
      });
    });
  }

  async newContext(persona) {
    const context = await this.browser.newContext({
      baseURL: appUrl,
      extraHTTPHeaders: { "x-real-ip": clientIp },
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
      acceptDownloads: true,
    });
    this.contexts.push(context);
    const page = await context.newPage();
    this.watch(page, persona);
    return { persona, context, page };
  }

  async shot(key, actor, fullPage) {
    const index = Object.keys(this.screenshots).length + 1;
    const filename = path.join(
      screenshotDir,
      String(index).padStart(2, "0") + "-" + key + ".png",
    );
    await actor.page.screenshot({
      path: filename,
      fullPage: Boolean(fullPage),
      animations: "disabled",
      caret: "initial",
    });
    this.screenshots[key] = filename;
    return filename;
  }

  async pythonExecutable() {
    return (
      (process.env.PYTHON && process.env.PYTHON.trim()) ||
      path.join(backendRoot, ".venv", "bin", "python")
    );
  }

  async fixture(action, args) {
    const python = await this.pythonExecutable();
    const result = await execFileAsync(
      python,
      [fixturePath, action].concat(args.map(String)),
      {
        cwd: backendRoot,
        env: {
          ...process.env,
          DATABASE_URL: databaseUrl,
          PYTHONPATH: backendRoot,
          PYTHONDONTWRITEBYTECODE: "1",
          OBJECT_STORE_BACKEND: process.env.OBJECT_STORE_BACKEND || "local",
          OBJECT_STORE_LOCAL_ROOT:
            process.env.OBJECT_STORE_LOCAL_ROOT ||
            path.join(repoRoot, "data", "local-blobs"),
        },
        timeout: 90_000,
        maxBuffer: 8 * 1024 * 1024,
      },
    );
    if (result.stderr.trim()) {
      this.fixtureStderr = result.stderr.trim().slice(0, 2000);
    }
    return JSON.parse(result.stdout);
  }

  async start() {
    this.buildIdentityAtStart = captureBuildIdentity(repoRoot);
    await Promise.all([
      mkdir(screenshotDir, { recursive: true }),
      mkdir(artifactDir, { recursive: true }),
    ]);
    this.browser = await chromium
      .launch({ channel: "chrome", headless: true })
      .catch(() => chromium.launch({ headless: true }));
    this.cubeBytes = await readFile(cubePath);
    this.seedData = await this.fixture("seed", [tag, password, cubePath]);
  }

  async snapshot() {
    return this.fixture("snapshot", [
      this.seedData.owner.id,
      rfqTitle,
    ]);
  }

  async login() {
    if (this.actor) return this.actor;
    const actor = await this.newContext("cost analyst and sourcing administrator");
    await actor.page.goto("/login", {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    await actor.page.getByLabel("Email").fill(this.seedData.owner.email);
    await actor.page.getByLabel("Password").fill(password);
    const responsePromise = actor.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/auth/login",
      { timeout: 45_000 },
    );
    await actor.page.getByRole("button", { name: /^Log in$/i }).click();
    const response = await responsePromise;
    assert(response.status() === 200, "fixture login returned " + response.status());
    await actor.page.waitForURL((url) => url.pathname !== "/login", {
      timeout: 20_000,
    });
    this.actor = actor;
    return actor;
  }

  async chooseCompareDecision(page, label, filename) {
    const labelNode = page.locator("label.cv-eyebrow").filter({ hasText: label });
    const trigger = labelNode.locator("xpath=..").getByRole("combobox");
    await trigger.click();
    await page
      .getByRole("option", {
        name: new RegExp("^" + escapeRegex(filename) + "(?:\\s|$)"),
      })
      .click();
  }

  async compareOnce(actor) {
    const a = this.seedData.decisions.A;
    const b = this.seedData.decisions.B;
    await this.chooseCompareDecision(actor.page, "Decision A", a.filename);
    await this.chooseCompareDecision(actor.page, "Decision B", b.filename);
    const responsePromise = actor.page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname ===
          "/api/proxy/cost-decisions/compare",
      { timeout: 30_000 },
    );
    await actor.page.getByRole("button", { name: /^Compare/ }).click();
    const response = await responsePromise;
    const parsed = await responseJson(response);
    await actor.page
      .getByText("Recommended unit cost by quantity", { exact: true })
      .waitFor({ timeout: 15_000 });
    const rows = {};
    const rowLocators = actor.page
      .locator("section")
      .filter({ hasText: "Recommended unit cost by quantity" })
      .locator("tbody tr");
    const rowCount = await rowLocators.count();
    for (let index = 0; index < rowCount; index += 1) {
      const cells = (await rowLocators.nth(index).locator("td").allInnerTexts()).map(
        cleanText,
      );
      rows[Number(cells[0].replace(/,/g, ""))] = cells;
    }
    return { response: parsed, rows };
  }

  async runWork06() {
    const id = "WORK-06";
    const actor = await this.login();
    await actor.page.goto("/cost-decisions/compare", {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    await actor.page
      .getByRole("heading", { name: "Compare cost decisions" })
      .waitFor({ timeout: 15_000 });
    const first = await this.compareOnce(actor);
    this.equal(id, "compare response authorization status", first.response.status, 200);
    this.equal(
      id,
      "comparison A durable id",
      first.response.body.a.id,
      this.seedData.decisions.A.id,
    );
    this.equal(
      id,
      "comparison B durable id",
      first.response.body.b.id,
      this.seedData.decisions.B.id,
    );
    this.equal(
      id,
      "aligned quantity rows",
      first.response.body.unit_cost_by_qty.map((row) => row.quantity),
      [1, 10, 100, 1000],
    );
    for (const expected of this.seedData.expected_compare) {
      const actual = first.response.body.unit_cost_by_qty.find(
        (row) => row.quantity === expected.quantity,
      );
      this.ok(id, "quantity " + expected.quantity + " exists", actual);
      this.equal(
        id,
        "quantity " + expected.quantity + " A source",
        actual.a,
        expected.a,
      );
      this.equal(
        id,
        "quantity " + expected.quantity + " B source",
        actual.b,
        expected.b,
      );
      this.equal(
        id,
        "quantity " + expected.quantity + " delta B minus A",
        actual.delta_usd,
        expected.delta_usd,
      );
      this.equal(
        id,
        "quantity " + expected.quantity + " percent delta",
        actual.delta_pct,
        expected.delta_pct,
      );
    }
    const expectedUi = {
      1: ["1", "$10.00", "$12.35", "+$2.35 (+23.5%)"],
      10: ["10", "$20.00", "$15.00", "-$5.00 (-25%)"],
      100: ["100", "$8.00", "—", "—"],
      1000: ["1,000", "—", "$7.00", "—"],
    };
    this.equal(id, "visible compare table exact formatting", first.rows, expectedUi);
    const screenshot = await this.shot("work-06-compare-exact", actor, true);

    await actor.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    await actor.page
      .getByRole("heading", { name: "Compare cost decisions" })
      .waitFor({ timeout: 15_000 });
    const reopened = await this.compareOnce(actor);
    this.equal(id, "reopened compare response status", reopened.response.status, 200);
    this.equal(
      id,
      "reopened comparison is exact",
      reopened.response.body,
      first.response.body,
    );
    this.equal(id, "reopened visible table is exact", reopened.rows, expectedUi);

    const durable = await this.snapshot();
    const durableIds = durable.cost_decisions.map((decision) => decision.id);
    this.equal(
      id,
      "both comparison sources remain durable",
      [
        durableIds.includes(this.seedData.decisions.A.id),
        durableIds.includes(this.seedData.decisions.B.id),
      ],
      [true, true],
    );

    return {
      persona: pathMeta[id].persona,
      preconditions: pathMeta[id].preconditions,
      actions: pathMeta[id].actions,
      observed: {
        url: actor.page.url(),
        visible: [
          "Quantity 1 showed $10.00 versus $12.35 and +$2.35 (+23.5%).",
          "Quantity 10 showed $20.00 versus $15.00 and -$5.00 (-25%).",
          "A-only quantity 100 and B-only quantity 1,000 showed em dashes for unavailable deltas.",
        ],
        persisted: {
          decisionA: this.seedData.decisions.A.id,
          decisionB: this.seedData.decisions.B.id,
          exactAfterReload: true,
        },
        numeric: {
          quantities: [1, 10, 100, 1000],
          positiveDeltaUsd: 2.35,
          positiveDeltaPct: 23.5,
          negativeDeltaUsd: -5,
          negativeDeltaPct: -25,
          nullDeltaRows: 2,
        },
        authorization: {
          compareStatus: first.response.status,
          reopenedStatus: reopened.response.status,
          organizationId: this.seedData.org.id,
        },
        recovery:
          "After a full reload cleared client state, reselecting both persisted decisions reproduced the identical API payload and visible table.",
      },
      screenshot,
    };
  }

  expectedRfqWarnings() {
    const b = this.seedData.decisions.B;
    const c = this.seedData.decisions.C;
    const unavailable =
      "Raw CAD was requested but is not available for this saved decision.";
    return [
      {
        code: "decision_stale",
        decision_id: b.id,
        message: b.filename + " predates governed assumption changes.",
      },
      {
        code: "confidence_unvalidated",
        decision_id: b.id,
        message: b.filename + " includes assumption-based confidence bands.",
      },
      {
        code: "raw_cad_unavailable",
        decision_id: b.id,
        message: unavailable,
      },
      {
        code: "decision_unapproved",
        decision_id: c.id,
        message: c.filename + " is not approved.",
      },
      {
        code: "confidence_unvalidated",
        decision_id: c.id,
        message: c.filename + " includes assumption-based confidence bands.",
      },
      {
        code: "raw_cad_unavailable",
        decision_id: c.id,
        message: unavailable,
      },
    ];
  }

  async extractPdf(pdfPath) {
    const result = await execFileAsync("pdftotext", [pdfPath, "-"], {
      timeout: 30_000,
      maxBuffer: 4 * 1024 * 1024,
    });
    return result.stdout;
  }

  async runWork08() {
    const id = "WORK-08";
    const actor = await this.login();
    const decisions = [
      this.seedData.decisions.A,
      this.seedData.decisions.B,
      this.seedData.decisions.C,
    ];
    await actor.page.goto("/rfq-packages", {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    await actor.page
      .getByRole("heading", { name: "RFQ packages" })
      .waitFor({ timeout: 15_000 });
    for (const decision of decisions) {
      await actor.page
        .getByRole("checkbox", {
          name: "Include " + decision.filename + " in the RFQ package",
        })
        .check();
    }
    await actor.page
      .getByText(
        "Selected decisions include stale or unapproved records; the package will preserve those warnings.",
        { exact: true },
      )
      .waitFor();
    await actor.page.getByPlaceholder("Pump RFQ package").fill(rfqTitle);
    await actor.page.getByPlaceholder("optional").fill(rfqSupplier);
    await actor.page.getByPlaceholder("Buyer note").fill(rfqNote);
    await actor.page
      .getByLabel("Include raw CAD only if already retained")
      .check();

    const createPromise = actor.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/proxy/rfq-packages",
      { timeout: 45_000 },
    );
    await actor.page
      .getByRole("button", { name: "Generate package (3)" })
      .click();
    const created = await responseJson(await createPromise);
    this.equal(id, "RFQ create authorization status", created.status, 201);
    const pkg = created.body.package;
    this.ok(id, "RFQ create returned durable id", pkg && pkg.id);
    this.equal(id, "RFQ title", pkg.title, rfqTitle);
    this.equal(id, "RFQ supplier", pkg.supplier_name, rfqSupplier);
    this.equal(id, "RFQ selected item count", pkg.item_count, 3);
    this.equal(id, "RFQ approved count", pkg.approved_count, 2);
    this.equal(id, "RFQ stale count", pkg.stale_count, 1);
    this.equal(id, "RFQ unvalidated count", pkg.unvalidated_count, 2);
    this.equal(id, "RFQ raw CAD included", pkg.raw_cad_included, true);
    this.equal(id, "RFQ retained raw payload count", pkg.metadata.raw_payload_count, 1);
    this.equal(id, "RFQ live supplier send boundary", pkg.live_supplier_send, false);
    this.equal(id, "RFQ exact warnings", pkg.warnings, this.expectedRfqWarnings());
    this.equal(id, "RFQ item order", pkg.items.map((item) => item.decision.id), decisions.map((d) => d.id));
    await actor.page
      .getByText("RFQ package generated", { exact: true })
      .waitFor({ timeout: 20_000 });

    await actor.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    const packageRow = actor.page.getByRole("row").filter({ hasText: rfqTitle });
    await packageRow.waitFor({ timeout: 15_000 });
    const packageCells = (await packageRow.locator("td").allInnerTexts()).map(
      cleanText,
    );
    this.equal(id, "reopened RFQ list approved text", packageCells[1], "2/3 approved");
    this.equal(id, "reopened RFQ list warning count", packageCells[2], "6");

    const detailPromise = actor.page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname ===
          "/api/proxy/rfq-packages/" + pkg.id,
      { timeout: 30_000 },
    );
    await packageRow.getByRole("button", { name: rfqTitle }).click();
    await actor.page.waitForURL(
      (url) => url.pathname === "/rfq-packages/" + pkg.id,
      { timeout: 15_000 },
    );
    const detail = await responseJson(await detailPromise);
    this.equal(id, "RFQ detail authorization status", detail.status, 200);
    this.equal(id, "RFQ detail exactly reopens create snapshot", detail.body.package, pkg);

    const summaryGrid = actor.page
      .locator("div.grid")
      .filter({ has: actor.page.getByText("Approved", { exact: true }) })
      .first();
    const summaryCards = (await summaryGrid.locator(":scope > div").allInnerTexts()).map(
      cleanText,
    );
    this.equal(
      id,
      "visible RFQ summary counts",
      summaryCards,
      ["Approved 2/3", "Stale 1", "Unvalidated 2", "Raw CAD Yes"],
    );
    const warningFrequency = {};
    for (const warning of this.expectedRfqWarnings()) {
      warningFrequency[warning.code] = (warningFrequency[warning.code] || 0) + 1;
    }
    for (const [code, expectedCount] of Object.entries(warningFrequency)) {
      this.equal(
        id,
        "visible warning frequency " + code,
        await actor.page.getByText(code, { exact: true }).count(),
        expectedCount,
      );
    }
    const itemRows = {};
    const itemLocators = actor.page.locator("tbody tr");
    const itemCount = await itemLocators.count();
    for (let index = 0; index < itemCount; index += 1) {
      const cells = (await itemLocators.nth(index).locator("td").allInnerTexts()).map(
        cleanText,
      );
      itemRows[cells[0]] = cells.slice(1);
    }
    this.equal(
      id,
      "visible RFQ item truth",
      itemRows,
      {
        [decisions[0].filename]: ["cnc_3axis", "approved", "raw CAD", "--"],
        [decisions[1].filename]: ["mjf", "approved", "stale, unvalidated", "--"],
        [decisions[2].filename]: ["dmls", "unreviewed", "unvalidated", "--"],
      },
    );
    const screenshot = await this.shot("work-08-rfq-detail", actor, true);

    const refreshedPromise = actor.page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname ===
          "/api/proxy/rfq-packages/" + pkg.id,
      { timeout: 30_000 },
    );
    await actor.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    const refreshed = await responseJson(await refreshedPromise);
    this.equal(id, "RFQ detail survives reload exactly", refreshed.body.package, pkg);

    const downloadResponsePromise = actor.page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname ===
          "/api/proxy/rfq-packages/" + pkg.id + "/download.zip",
      { timeout: 180_000 },
    );
    const downloadPromise = actor.page.waitForEvent("download", {
      timeout: 180_000,
    });
    await actor.page.getByRole("button", { name: "Download ZIP" }).click();
    const [downloadResponse, download] = await Promise.all([
      downloadResponsePromise,
      downloadPromise,
    ]);
    this.equal(id, "RFQ ZIP download authorization status", downloadResponse.status(), 200);
    await download.saveAs(artifacts.rfqZip);
    const downloadFailure = await download.failure();
    this.equal(id, "RFQ ZIP browser download failure", downloadFailure, null);
    this.ok(id, "RFQ ZIP suggested filename", /-rfq\.zip$/i.test(download.suggestedFilename()));

    const zipBytes = await readFile(artifacts.rfqZip);
    const entries = unzipSync(new Uint8Array(zipBytes));
    const names = Object.keys(entries).sort();
    const requiredRootFiles = [
      "cost-decisions.json",
      "line-items.csv",
      "package_manifest.json",
      "supplier-brief.md",
      "supplier-brief.pdf",
    ];
    for (const filename of requiredRootFiles) {
      this.ok(id, "RFQ ZIP contains " + filename, Boolean(entries[filename]));
    }
    this.equal(
      id,
      "RFQ ZIP has no supplier PDF fallback",
      Boolean(entries["supplier-brief-pdf-unavailable.txt"]),
      false,
    );
    const manifest = zipJson(entries, "package_manifest.json");
    this.equal(id, "manifest id", manifest.id, pkg.id);
    this.equal(id, "manifest title", manifest.title, rfqTitle);
    this.equal(id, "manifest supplier", manifest.supplier_name, rfqSupplier);
    this.equal(id, "manifest item count", manifest.item_count, 3);
    this.equal(id, "manifest approved count", manifest.approved_count, 2);
    this.equal(id, "manifest stale count", manifest.stale_count, 1);
    this.equal(id, "manifest unvalidated count", manifest.unvalidated_count, 2);
    this.equal(id, "manifest raw CAD included", manifest.raw_cad_included, true);
    this.equal(id, "manifest exact warnings", manifest.warnings, pkg.warnings);
    this.equal(id, "manifest buyer note", manifest.metadata.note, rfqNote);
    this.equal(
      id,
      "manifest required root files",
      requiredRootFiles.every((filename) => manifest.included_files.includes(filename)),
      true,
    );

    const expectedHeaders = [
      "decision_id",
      "filename",
      "approval_status",
      "is_stale",
      "unvalidated_confidence",
      "make_now_process",
      "crossover_qty",
      "manifest_part_id",
      "program",
      "raw_cad_included",
    ];
    const lineItems = parseCsv(zipText(entries, "line-items.csv"), "RFQ line-items.csv");
    this.equal(id, "RFQ CSV exact headers", lineItems.headers, expectedHeaders);
    this.equal(id, "RFQ CSV one row per selected decision", lineItems.records.length, 3);
    const csvById = Object.fromEntries(
      lineItems.records.map((record) => [record.decision_id, record]),
    );
    for (const decision of decisions) {
      const row = csvById[decision.id];
      this.ok(id, "RFQ CSV contains " + decision.filename, row);
      this.equal(id, decision.filename + " CSV filename", row.filename, decision.filename);
      this.equal(
        id,
        decision.filename + " CSV approval",
        row.approval_status,
        decision.approval_status,
      );
      this.equal(
        id,
        decision.filename + " CSV stale",
        row.is_stale,
        decision.is_stale ? "True" : "False",
      );
      this.equal(
        id,
        decision.filename + " CSV unvalidated",
        row.unvalidated_confidence,
        decision.unvalidated ? "True" : "False",
      );
      this.equal(
        id,
        decision.filename + " CSV process",
        row.make_now_process,
        decision.process,
      );
    }
    this.equal(
      id,
      "RFQ CSV exact raw CAD flags",
      decisions.map((decision) => csvById[decision.id].raw_cad_included),
      ["True", "False", "False"],
    );

    const packagedItems = zipJson(entries, "cost-decisions.json");
    this.equal(id, "RFQ packaged decision snapshots", packagedItems, pkg.items);
    const supplierBrief = zipText(entries, "supplier-brief.md");
    this.ok(id, "supplier brief exact title", supplierBrief.includes("# " + rfqTitle));
    this.ok(id, "supplier brief exact note", supplierBrief.includes(rfqNote));
    this.ok(id, "supplier brief item count", supplierBrief.includes("Decisions included: 3"));
    this.ok(id, "supplier brief approved count", supplierBrief.includes("Approved decisions: 2"));
    this.ok(id, "supplier brief stale count", supplierBrief.includes("Stale decisions: 1"));
    this.ok(
      id,
      "supplier brief unvalidated count",
      supplierBrief.includes("Decisions with unvalidated confidence bands: 2"),
    );
    this.ok(id, "supplier brief raw CAD count boundary", supplierBrief.includes("Raw CAD included: yes"));
    for (const warning of pkg.warnings) {
      this.ok(
        id,
        "supplier brief warning " + warning.code + " " + warning.decision_id,
        supplierBrief.includes(warning.code + ": " + warning.message),
      );
    }

    await writeFile(artifacts.supplierPdf, entries["supplier-brief.pdf"]);
    const supplierPdfText = await this.extractPdf(artifacts.supplierPdf);
    const supplierPdfNormalized = cleanText(supplierPdfText);
    this.ok(id, "supplier PDF is real", strFromU8(entries["supplier-brief.pdf"].slice(0, 5)) === "%PDF-");
    this.ok(id, "supplier PDF exact title", supplierPdfNormalized.includes(rfqTitle));
    this.ok(id, "supplier PDF exact buyer note", supplierPdfNormalized.includes(rfqNote));
    this.ok(id, "supplier PDF approved count", /Approved decisions\s+2/.test(supplierPdfText));
    this.ok(id, "supplier PDF stale count", /Stale decisions\s+1/.test(supplierPdfText));
    this.ok(
      id,
      "supplier PDF unvalidated count",
      /Unvalidated confidence\s+2/.test(supplierPdfText),
    );
    this.ok(id, "supplier PDF raw CAD truth", /Raw CAD included\s+yes/.test(supplierPdfText));
    this.ok(id, "supplier PDF no-live-send truth", /Live supplier send\s+no/.test(supplierPdfText));
    for (const warning of pkg.warnings) {
      this.ok(
        id,
        "supplier PDF warning code " + warning.code + " " + warning.decision_id,
        supplierPdfText.includes(warning.code),
      );
      this.ok(
        id,
        "supplier PDF warning message " + warning.decision_id,
        supplierPdfNormalized.includes(cleanText(warning.message)),
      );
    }
    this.equal(
      id,
      "supplier PDF repeated raw-CAD warning count",
      countOccurrences(supplierPdfText, "raw_cad_unavailable"),
      2,
    );

    const expectedPdfCost = { A: "$10.00", B: "$12.35", C: "$30.00" };
    const expectedDriverHeaders = [
      "process",
      "material",
      "quantity",
      "unit_cost_usd",
      "fixed_cost_usd",
      "variable_cost_usd",
      "est_error_band_pct",
      "confidence_low_usd",
      "confidence_high_usd",
      "confidence_label",
      "confidence_validated",
      "dfm_ready",
      "approval_status",
      "approved_by_user_id",
      "approved_at",
      "approval_note",
      "user_disposition",
      "user_disposition_label",
      "disposition_note",
      "disposition_updated_at",
      "disposition_updated_by_user_id",
      "line_items",
    ];
    const driverGovernanceColumns = [
      "approval_status",
      "approved_by_user_id",
      "approved_at",
      "approval_note",
      "user_disposition",
      "user_disposition_label",
      "disposition_note",
      "disposition_updated_at",
      "disposition_updated_by_user_id",
    ];
    for (let index = 0; index < decisions.length; index += 1) {
      const decision = decisions[index];
      const packagedDecision = pkg.items[index].decision;
      const stem = path.parse(decision.filename).name;
      const prefix =
        "decisions/" + String(index + 1).padStart(2, "0") + "-" + stem + "/";
      const decisionJsonName = prefix + "cost-decision.json";
      const driverName = prefix + "cost-drivers.csv";
      const pdfName = prefix + "should-cost-report.pdf";
      this.ok(id, decision.filename + " packaged JSON", Boolean(entries[decisionJsonName]));
      this.ok(id, decision.filename + " packaged drivers", Boolean(entries[driverName]));
      this.ok(id, decision.filename + " packaged PDF", Boolean(entries[pdfName]));
      const packagedCost = zipJson(entries, decisionJsonName);
      this.equal(
        id,
        decision.filename + " packaged cost snapshot",
        packagedCost,
        pkg.items[index].cost_decision,
      );
      const driverCsv = parseCsv(zipText(entries, driverName), driverName);
      this.equal(
        id,
        decision.filename + " driver CSV exact headers",
        driverCsv.headers,
        expectedDriverHeaders,
      );
      this.equal(
        id,
        decision.filename + " driver CSV one row per estimate",
        driverCsv.records.length,
        packagedCost.estimates.length,
      );
      for (const row of driverCsv.records) {
        for (const field of driverGovernanceColumns) {
          this.equal(
            id,
            decision.filename + " driver governance " + field,
            row[field],
            String(packagedDecision[field] ?? ""),
          );
        }
      }
      this.equal(
        id,
        decision.filename + " no PDF fallback",
        Boolean(entries[prefix + "pdf-unavailable.txt"]),
        false,
      );
      const pdfPath = path.join(artifactDir, decision.id + "-should-cost-report.pdf");
      artifacts.decisionPdfs[decision.id] = pdfPath;
      await writeFile(pdfPath, entries[pdfName]);
      const pdfText = await this.extractPdf(pdfPath);
      this.ok(id, decision.filename + " PDF header", strFromU8(entries[pdfName].slice(0, 5)) === "%PDF-");
      this.ok(id, decision.filename + " PDF filename", pdfText.includes(decision.filename));
      this.ok(
        id,
        decision.filename + " PDF approval status",
        new RegExp("Status:\\s+" + decision.approval_status).test(pdfText),
      );
      this.ok(
        id,
        decision.filename + " PDF exact unit cost",
        pdfText.includes(expectedPdfCost[decision.key]),
      );
    }

    const aStem = path.parse(decisions[0].filename).name;
    const aRawName =
      "decisions/01-" +
      aStem +
      "/raw-cad/" +
      aStem +
      path.extname(decisions[0].filename);
    this.ok(id, "retained raw CAD file is packaged", Boolean(entries[aRawName]));
    this.equal(
      id,
      "retained raw CAD bytes are exact",
      sha256(entries[aRawName]),
      this.seedData.retained_raw_cad.sha256,
    );
    for (let index = 1; index < decisions.length; index += 1) {
      const stem = path.parse(decisions[index].filename).name;
      const boundaryName =
        "decisions/" +
        String(index + 1).padStart(2, "0") +
        "-" +
        stem +
        "/raw-cad-unavailable.txt";
      this.ok(id, decisions[index].filename + " raw CAD boundary", Boolean(entries[boundaryName]));
      this.ok(
        id,
        decisions[index].filename + " raw CAD reason",
        zipText(entries, boundaryName).includes("no_same_org_completed_batch_blob"),
      );
    }

    const durable = await this.snapshot();
    this.equal(id, "RFQ durable database snapshot", durable.rfq_package, {
      id: pkg.id,
      title: pkg.title,
      item_count: pkg.item_count,
      approved_count: pkg.approved_count,
      stale_count: pkg.stale_count,
      unvalidated_count: pkg.unvalidated_count,
      raw_cad_included: pkg.raw_cad_included,
      live_supplier_send: pkg.live_supplier_send,
      items: pkg.items,
      warnings: pkg.warnings,
      metadata: pkg.metadata,
    });

    return {
      persona: pathMeta[id].persona,
      preconditions: pathMeta[id].preconditions,
      actions: pathMeta[id].actions,
      observed: {
        url: actor.page.url(),
        visible: [
          "The durable detail showed Approved 2/3, Stale 1, Unvalidated 2, and Raw CAD Yes.",
          "Six exact warning rows remained visible after reopening the package.",
          "Three item rows preserved approval, stale, confidence, process, and raw-CAD states.",
        ],
        persisted: {
          packageId: pkg.id,
          databaseExact: true,
          detailReloadExact: true,
          zipPath: artifacts.rfqZip,
          zipSha256: sha256(zipBytes),
          supplierPdfPath: artifacts.supplierPdf,
        },
        numeric: {
          itemCount: 3,
          approvedCount: 2,
          staleCount: 1,
          unvalidatedCount: 2,
          rawCadIncludedCount: 1,
          warningCount: 6,
          zipFiles: names.length,
          pdfFilesValidated: 4,
        },
        authorization: {
          create: created.status,
          detail: detail.status,
          download: downloadResponse.status(),
          organizationId: this.seedData.org.id,
        },
        recovery:
          "A full detail reload reproduced the immutable package, and the downloaded ZIP independently reconstructed every count, warning, decision link, raw-CAD boundary, and PDF truth.",
      },
      screenshot,
    };
  }

  async dismissReveal(actor) {
    await actor.page
      .getByLabel("I've saved it somewhere safe")
      .check();
    await actor.page.getByRole("button", { name: "Done" }).click();
    await actor.page
      .getByRole("heading", { name: "Save your API key" })
      .waitFor({ state: "detached", timeout: 15_000 });
  }

  async beginDeveloperMutation(
    actor,
    button,
    label,
    { method, pathname, expectedStatus = 200 },
  ) {
    const pending = actor.page.waitForResponse(
      (response) =>
        response.request().method() === method &&
        pathname.test(new URL(response.url()).pathname),
      { timeout: 30_000 },
    );
    await button.click();
    const response = await pending;
    this.equal(
      "WORK-12",
      `${label} mutation HTTP`,
      response.status(),
      expectedStatus,
    );
    return response;
  }

  async finishDeveloperMutation(actor, response, label) {
    const streamError = await Promise.race([
      response.finished(),
      actor.page.waitForTimeout(30_000).then(() => {
        throw new Error(`${label} mutation response did not finish within 30 seconds`);
      }),
    ]);
    this.equal(
      "WORK-12",
      `${label} mutation response completed`,
      streamError?.message ?? "<none>",
      "<none>",
    );
  }

  async bearer(actor, token) {
    return responseJson(
      await actor.context.request.get(
        apiUrl + "/api/v1/cost-decisions?limit=10",
        {
          headers: { Authorization: "Bearer " + token },
          failOnStatusCode: false,
          timeout: 30_000,
        },
      ),
    );
  }

  async runWork12() {
    const id = "WORK-12";
    const actor = await this.login();
    await actor.page.goto("/settings/developer", {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    await actor.page
      .getByRole("heading", { name: "Developer", exact: true })
      .waitFor({ timeout: 15_000 });
    const createActionResponse = await this.beginDeveloperMutation(
      actor,
      actor.page.getByRole("button", { name: "Create key" }).first(),
      "create key",
      { method: "POST", pathname: /^\/api\/proxy\/keys$/ },
    );
    const reveal = actor.page.getByRole("dialog");
    await reveal
      .getByRole("heading", { name: "Save your API key" })
      .waitFor({ timeout: 30_000 });
    const oldToken = cleanText(await reveal.locator("pre").innerText());
    this.ok(
      id,
      "created key exact token format",
      /^cv_live_[A-Za-z0-9]{8}_[A-Za-z0-9]{32}$/.test(oldToken),
    );
    const oldPrefix = oldToken.split("_")[2];
    this.equal(id, "created key prefix length", oldPrefix.length, 8);
    const revealScreenshot = await this.shot("work-12-create-one-time-reveal", actor, false);
    const oldAuthorized = await this.bearer(actor, oldToken);
    this.equal(id, "created bearer authorization", oldAuthorized.status, 200);
    this.ok(
      id,
      "created bearer sees same-org decision",
      oldAuthorized.body.cost_decisions.some(
        (decision) => decision.id === this.seedData.decisions.A.id,
      ),
    );
    await this.dismissReveal(actor);
    await this.finishDeveloperMutation(actor, createActionResponse, "create key");
    await actor.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    const afterCreateText = cleanText(await actor.page.locator("body").innerText());
    this.equal(id, "created plaintext absent after reload", afterCreateText.includes(oldToken), false);
    this.ok(
      id,
      "created prefix remains visible",
      afterCreateText.includes("cv_live_" + oldPrefix + "_…"),
    );
    this.equal(
      id,
      "created reveal cookie scrubbed",
      (await actor.context.cookies()).filter((cookie) => cookie.name === "cv_mint_once").length,
      0,
    );

    const oldRow = actor.page
      .getByRole("row")
      .filter({ hasText: "cv_live_" + oldPrefix + "_…" });
    this.ok(id, "created row is active", cleanText(await oldRow.innerText()).includes("Active"));
    const rotateActionResponse = await this.beginDeveloperMutation(
      actor,
      oldRow.getByRole("button", { name: "Rotate" }),
      "rotate key",
      { method: "POST", pathname: /^\/api\/proxy\/keys\/\d+\/rotate$/ },
    );
    await reveal
      .getByRole("heading", { name: "Save your API key" })
      .waitFor({ timeout: 30_000 });
    const newToken = cleanText(await reveal.locator("pre").innerText());
    this.ok(
      id,
      "rotated key exact token format",
      /^cv_live_[A-Za-z0-9]{8}_[A-Za-z0-9]{32}$/.test(newToken),
    );
    const newPrefix = newToken.split("_")[2];
    this.equal(id, "rotation changed prefix", newPrefix === oldPrefix, false);
    const rotateScreenshot = await this.shot("work-12-rotate-one-time-reveal", actor, false);
    await this.dismissReveal(actor);
    await this.finishDeveloperMutation(actor, rotateActionResponse, "rotate key");
    await actor.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    const afterRotateText = cleanText(await actor.page.locator("body").innerText());
    this.equal(id, "rotated plaintext absent after reload", afterRotateText.includes(newToken), false);
    this.equal(id, "old plaintext remains absent", afterRotateText.includes(oldToken), false);
    const oldRotatedRow = actor.page
      .getByRole("row")
      .filter({ hasText: "cv_live_" + oldPrefix + "_…" });
    const newActiveRow = actor.page
      .getByRole("row")
      .filter({ hasText: "cv_live_" + newPrefix + "_…" });
    this.ok(id, "rotated old row is revoked", cleanText(await oldRotatedRow.innerText()).includes("Revoked"));
    this.ok(id, "rotation replacement row is active", cleanText(await newActiveRow.innerText()).includes("Active"));
    this.equal(id, "old revoked row has no Rotate", await oldRotatedRow.getByRole("button", { name: "Rotate" }).count(), 0);
    this.equal(id, "old revoked row has no Revoke", await oldRotatedRow.getByRole("button", { name: "Revoke" }).count(), 0);

    const oldRejected = await this.bearer(actor, oldToken);
    this.equal(id, "rotated old token rejection status", oldRejected.status, 401);
    this.equal(id, "rotated old token rejection code", errorCode(oldRejected.body), "auth_invalid");
    const replacementAuthorized = await this.bearer(actor, newToken);
    this.equal(id, "rotation replacement authorization", replacementAuthorized.status, 200);

    const revokeActionResponse = await this.beginDeveloperMutation(
      actor,
      newActiveRow.getByRole("button", { name: "Revoke" }),
      "revoke key",
      {
        method: "DELETE",
        pathname: /^\/api\/proxy\/keys\/\d+$/,
        expectedStatus: 204,
      },
    );
    const newRevokedRow = actor.page
      .getByRole("row")
      .filter({ hasText: "cv_live_" + newPrefix + "_…" });
    await newRevokedRow.getByText("Revoked", { exact: true }).waitFor({
      timeout: 30_000,
    });
    await this.finishDeveloperMutation(actor, revokeActionResponse, "revoke key");
    const replacementRejected = await this.bearer(actor, newToken);
    this.equal(id, "revoked replacement rejection status", replacementRejected.status, 401);
    this.equal(
      id,
      "revoked replacement rejection code",
      errorCode(replacementRejected.body),
      "auth_invalid",
    );

    await actor.page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    const oldFinalRow = actor.page
      .getByRole("row")
      .filter({ hasText: "cv_live_" + oldPrefix + "_…" });
    const newFinalRow = actor.page
      .getByRole("row")
      .filter({ hasText: "cv_live_" + newPrefix + "_…" });
    this.ok(id, "old revocation survives reload", cleanText(await oldFinalRow.innerText()).includes("Revoked"));
    this.ok(id, "replacement revocation survives reload", cleanText(await newFinalRow.innerText()).includes("Revoked"));
    this.equal(id, "replacement revoked row has no Rotate", await newFinalRow.getByRole("button", { name: "Rotate" }).count(), 0);
    this.equal(id, "replacement revoked row has no Revoke", await newFinalRow.getByRole("button", { name: "Revoke" }).count(), 0);

    const keyList = await responseJson(
      await actor.context.request.get("/api/proxy/keys", {
        failOnStatusCode: false,
      }),
    );
    this.equal(id, "dashboard key list authorization", keyList.status, 200);
    this.equal(id, "dashboard key list count", keyList.body.length, 2);
    this.equal(
      id,
      "dashboard key list prefixes",
      keyList.body.map((key) => key.prefix).sort(),
      [oldPrefix, newPrefix].sort(),
    );
    this.equal(
      id,
      "dashboard key list all revoked",
      keyList.body.every((key) => Boolean(key.revoked_at)),
      true,
    );
    this.equal(id, "dashboard key list omits plaintext", JSON.stringify(keyList.body).includes(oldToken) || JSON.stringify(keyList.body).includes(newToken), false);

    const durable = await this.snapshot();
    this.equal(id, "durable API key row count", durable.api_keys.length, 2);
    this.equal(
      id,
      "durable API key prefixes",
      durable.api_keys.map((key) => key.prefix).sort(),
      [oldPrefix, newPrefix].sort(),
    );
    this.equal(
      id,
      "durable API keys all revoked",
      durable.api_keys.every((key) => Boolean(key.revoked_at)),
      true,
    );
    this.equal(
      id,
      "durable API key HMAC indexes",
      durable.api_keys.every((key) => key.hmac_length === 64 && key.hmac_hex),
      true,
    );
    this.equal(
      id,
      "durable API key Argon2id hashes",
      durable.api_keys.every((key) => key.argon2id),
      true,
    );
    this.equal(id, "API key create audit rows", durable.api_key_audit["api_key.created"], 2);
    this.equal(id, "API key revoke audit rows", durable.api_key_audit["api_key.revoked"], 2);
    this.equal(
      id,
      "API key table has no plaintext column",
      durable.api_key_columns.some((column) =>
        ["token", "plaintext", "full_token", "secret"].includes(column),
      ),
      false,
    );
    const dashboardRecovery = await responseJson(
      await actor.context.request.get("/api/proxy/cost-decisions?limit=1", {
        failOnStatusCode: false,
      }),
    );
    this.equal(id, "dashboard session remains authorized after key rejection", dashboardRecovery.status, 200);
    await actor.page.getByRole("button", { name: "Create key" }).first().waitFor();
    const finalScreenshot = await this.shot("work-12-all-keys-revoked", actor, true);

    return {
      persona: pathMeta[id].persona,
      preconditions: pathMeta[id].preconditions,
      actions: pathMeta[id].actions,
      observed: {
        url: actor.page.url(),
        visible: [
          "Create revealed one full cv_live key with the warning Copy it now — we will not show it again.",
          "Reload showed only the eight-character prefix and Active status; rotation revealed a different full key once.",
          "The final reload showed both prefixes as Revoked with Rotate and Revoke controls absent.",
        ],
        persisted: {
          oldPrefix,
          newPrefix,
          oldTokenSha256: sha256(oldToken),
          newTokenSha256: sha256(newToken),
          databaseRows: durable.api_keys,
          audit: durable.api_key_audit,
          screenshots: { revealScreenshot, rotateScreenshot, finalScreenshot },
        },
        numeric: {
          keyRows: durable.api_keys.length,
          createdAuditRows: durable.api_key_audit["api_key.created"],
          revokedAuditRows: durable.api_key_audit["api_key.revoked"],
          fullTokenRevealCountPerCredential: 1,
          plaintextColumns: 0,
        },
        authorization: {
          createdToken: oldAuthorized.status,
          rotatedOldToken: oldRejected.status,
          rotatedOldCode: errorCode(oldRejected.body),
          replacementBeforeRevoke: replacementAuthorized.status,
          replacementAfterRevoke: replacementRejected.status,
          replacementRevokedCode: errorCode(replacementRejected.body),
          dashboardRecovery: dashboardRecovery.status,
        },
        recovery:
          "After both bearer credentials were rejected, the dashboard session still reopened Developer settings, listed both durable revocations, and kept Create key available.",
      },
      screenshot: revealScreenshot,
    };
  }

  async path(id, fn) {
    const started = Date.now();
    const assertionOffset = this.assertions.length;
    const consoleOffset = this.consoleErrors.length;
    const requestOffset = this.requestFailures.length;
    try {
      const input = await fn();
      const assertions = this.assertions.slice(assertionOffset);
      assert(assertions.length > 0, id + " emitted no field-level assertions");
      const consoleErrors = this.consoleErrors.slice(consoleOffset);
      const requestFailures = this.requestFailures.slice(requestOffset);
      assert(
        consoleErrors.length === 0,
        id + " produced console errors: " + JSON.stringify(consoleErrors),
      );
      assert(
        requestFailures.length === 0,
        id + " produced request failures: " + JSON.stringify(requestFailures),
      );
      this.goldenPaths[id] = makeGoldenPathEvidence({
        id,
        status: "PASS",
        ...input,
        consoleErrors,
        requestFailures,
        assertions,
      });
      this.steps.push({
        id,
        status: "PASS",
        durationMs: Date.now() - started,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.failures.push({ id, error: message });
      this.steps.push({
        id,
        status: "FAIL",
        durationMs: Date.now() - started,
        error: message,
      });
      this.goldenPaths[id] = makeGoldenPathEvidence({
        id,
        status: "FAIL",
        persona: pathMeta[id].persona,
        preconditions: pathMeta[id].preconditions,
        actions: pathMeta[id].actions,
        observed: {
          url: appUrl,
          visible: ["Path failed before complete evidence: " + message],
          persisted: "not-observed",
          numeric: "not-observed",
          authorization: "not-observed",
          recovery: "not-observed",
        },
        screenshot:
          this.screenshots[Object.keys(this.screenshots).at(-1)] || "",
        consoleErrors: this.consoleErrors.slice(consoleOffset),
        requestFailures: this.requestFailures.slice(requestOffset),
        assertions: this.assertions.slice(assertionOffset),
      });
    }
  }

  markdown(data) {
    const rows = requiredIds.map((id) => {
      const validation = data.releaseEvidence.validation.byId[id];
      const invalid = validation.failures.map((item) => item.field).join(", ") || "none";
      return (
        "| " +
        (validation.valid ? "PASS" : "FAIL") +
        " | " +
        id +
        " | " +
        invalid +
        " | " +
        (data.releaseEvidence.goldenPaths[id].screenshot || "") +
        " |"
      );
    });
    return [
      "# Compare, RFQ, and API-key golden matrix",
      "",
      "- Run: " + runId,
      "- Status: " + data.status,
      "- Build: " + data.buildIdentity.gitHead,
      "- Structured paths: " +
        data.releaseEvidence.validation.valid +
        "/" +
        data.releaseEvidence.validation.total,
      "- Assertions: " +
        data.summary.passedAssertions +
        "/" +
        data.summary.assertions,
      "- Unexpected console errors: " + data.summary.consoleErrors,
      "- Unexpected request failures: " + data.summary.requestFailures,
      "",
      "| Result | Golden ID | Invalid fields | Screenshot |",
      "| --- | --- | --- | --- |",
      ...rows,
      "",
      "## Scope",
      "",
      "- WORK-06: exact B-minus-A arithmetic, 0.01 USD and 0.1% API precision, null source handling, visible formatting, and reload recomputation.",
      "- WORK-08: real browser package creation/reopen/download, exact counts and warnings, retained raw CAD, parsed CSV/JSON, package-level warning PDF, and per-decision PDF text.",
      "- WORK-12: create/reveal-once/prefix/rotate/revoke, bearer acceptance and rejection, durable hash-only storage, audit counts, and dashboard recovery.",
      "",
    ].join("\n");
  }

  async finish(fatalError) {
    for (const id of requiredIds) {
      if (this.goldenPaths[id]) continue;
      this.goldenPaths[id] = makeGoldenPathEvidence({
        id,
        status: "FAIL",
        persona: pathMeta[id].persona,
        preconditions: pathMeta[id].preconditions,
        actions: pathMeta[id].actions,
        observed: {
          url: appUrl,
          visible: ["Path did not execute."],
          persisted: "not-observed",
          numeric: "not-observed",
          authorization: "not-observed",
          recovery: "not-observed",
        },
        screenshot: "",
        consoleErrors: this.consoleErrors,
        requestFailures: this.requestFailures,
        assertions: [],
      });
    }
    const validation = validateGoldenPathMap(requiredIds, this.goldenPaths);
    const buildIdentity = captureBuildIdentity(repoRoot);
    const exactGoldenIds = deepEqual(
      Object.keys(this.goldenPaths).sort(),
      requiredIds.slice().sort(),
    );
    const buildBinding = {
      startGitHead:
        (this.buildIdentityAtStart && this.buildIdentityAtStart.gitHead) || null,
      finalGitHead: buildIdentity.gitHead,
      sameHead:
        Boolean(this.buildIdentityAtStart) &&
        this.buildIdentityAtStart.gitHead === buildIdentity.gitHead,
      cleanAtStart:
        Boolean(this.buildIdentityAtStart) &&
        this.buildIdentityAtStart.gitDirty === false,
      cleanAtFinish: buildIdentity.gitDirty === false,
      exactGoldenIds,
    };
    buildBinding.pass =
      buildBinding.sameHead &&
      buildBinding.cleanAtStart &&
      buildBinding.cleanAtFinish &&
      buildBinding.exactGoldenIds;
    const passedAssertions = this.assertions.filter((item) => item.pass).length;
    const status =
      !fatalError &&
      this.failures.length === 0 &&
      validation.valid === requiredIds.length &&
      this.consoleErrors.length === 0 &&
      this.requestFailures.length === 0 &&
      buildBinding.pass
        ? "PASS"
        : "FAIL";
    const data = {
      status,
      suite: "compare-rfq-key-golden-matrix",
      runId,
      generatedAt: new Date().toISOString(),
      durationMs: Date.now() - this.startedAt,
      baseUrl: appUrl,
      apiUrl,
      buildIdentity,
      buildIdentityAtStart: this.buildIdentityAtStart,
      buildBinding,
      summary: {
        goldenPaths: requiredIds.length,
        validGoldenPaths: validation.valid,
        assertions: this.assertions.length,
        passedAssertions,
        consoleErrors: this.consoleErrors.length,
        requestFailures: this.requestFailures.length,
      },
      steps: this.steps,
      failures: this.failures,
      fatalError: fatalError || null,
      screenshots: this.screenshots,
      consoleErrors: this.consoleErrors,
      requestFailures: this.requestFailures,
      releaseEvidence: {
        schemaVersion: 1,
        goldenPaths: this.goldenPaths,
        validation,
      },
      artifacts,
    };
    await mkdir(outputRoot, { recursive: true });
    await writeFile(artifacts.json, JSON.stringify(data, null, 2) + "\n");
    await writeFile(artifacts.md, this.markdown(data));
    console.log(
      JSON.stringify(
        {
          status,
          summary: data.summary,
          validation,
          buildBinding,
          artifacts,
          fatalError: fatalError || null,
        },
        null,
        2,
      ),
    );
    return data;
  }

  async close() {
    await Promise.all(
      this.contexts.map((context) => context.close().catch(() => {})),
    );
    if (this.browser) await this.browser.close().catch(() => {});
  }
}

const matrix = new CompareRfqKeyMatrix();
let fatalError = null;
try {
  await matrix.start();
  await matrix.path("WORK-06", () => matrix.runWork06());
  await matrix.path("WORK-08", () => matrix.runWork08());
  await matrix.path("WORK-12", () => matrix.runWork12());
} catch (error) {
  fatalError = error instanceof Error ? error.stack || error.message : String(error);
}
const report = await matrix.finish(fatalError);
await matrix.close();
if (report.status !== "PASS") process.exitCode = 1;
