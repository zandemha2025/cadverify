import { execFile } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import {
  makeGoldenPathEvidence,
  validateGoldenPathMap,
} from "./golden-path-evidence.mjs";
import { captureBuildIdentity } from "./human-sim-release-evidence.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const { zipSync } = require("fflate");
const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const backendRoot = path.join(repoRoot, "backend");
const appUrl = (process.env.APP_URL || "http://localhost:3000").replace(/\/+$/, "");
const apiUrl = (process.env.API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const clientIp = process.env.E2E_CLIENT_IP || "198.51.100.83";
const databaseUrl =
  process.env.DATABASE_URL ||
  "postgresql://cadverify:localdev@127.0.0.1:5432/cadverify";
const runId =
  process.env.E2E_RUN_ID ||
  `role-tenant-${new Date().toISOString().replace(/[-:]/g, "").slice(0, 15)}`;
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(outputRoot, "screenshots", `role-tenant-boundary-${runId}`);
const artifacts = {
  json: path.join(outputRoot, `role-tenant-boundary-${runId}.json`),
  md: path.join(outputRoot, `qa-report-role-tenant-boundary-${runId}.md`),
};
const cubePath = path.join(backendRoot, "tests", "assets", "cube.step");
const password = `ProofShape-Roles-${randomBytes(8).toString("hex")}-9`;
const tag = `${Date.now().toString(36)}-${process.pid}-${randomBytes(3).toString("hex")}`;

const PATH_META = {
  "ROLE-02": {
    persona: "owner, org admin, analyst/member, viewer, and platform-admin",
    preconditions: [
      "Two real organizations exist with explicit platform and organization roles.",
      "Each regular persona starts in organization A; platform-admin has no tenant membership.",
    ],
    actions: [
      "Open role-sensitive browser surfaces.",
      "Exercise read, create, administration, integration, and API-key operations through direct and proxied APIs.",
    ],
  },
  "ROLE-03": {
    persona: "founding owner removing an analyst who also belongs to a second organization",
    preconditions: [
      "Owner is an org admin in A.",
      "Analyst is a member of A and B and owns one API key in each organization.",
    ],
    actions: [
      "Switch organizations in the browser and API.",
      "Remove the analyst from A, then reuse the already-open analyst browser and both bearer keys.",
    ],
  },
  "ROLE-04": {
    persona: "same-org viewer and cross-org attacker using known and guessed identifiers",
    preconditions: [
      "A and B each contain a design project, analysis, cost decision, batch, RFQ package, integration run, notification, and queued job.",
      "Foreign sentinels are unique and known to the test oracle.",
    ],
    actions: [
      "Read A resources as an A viewer.",
      "Switch to B and substitute A identifiers into list, detail, download, export, job, and browser URLs.",
      "Compare every known foreign denial with a same-shape unknown identifier.",
    ],
  },
  "VER-04": {
    persona: "viewer using the durable notification inbox in two organizations",
    preconditions: [
      "A and B contain distinct durable notification titles and IDs.",
      "Read state is per user and notification rows are organization-scoped.",
    ],
    actions: [
      "Open notifications in the browser, mark the A row read, refresh, switch to B, and probe the foreign A ID.",
    ],
  },
  "FAIL-09": {
    persona: "viewer whose active dashboard session is revoked by platform-admin",
    preconditions: [
      "Viewer has an authenticated browser session and authorized organization B data.",
      "Platform-admin can revoke account sessions but is not a tenant member.",
    ],
    actions: [
      "Revoke all viewer sessions through the admin API.",
      "Reuse the stale cookie through direct API and a protected browser URL, then log in again.",
    ],
  },
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function cleanText(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function jsonValue(value) {
  if (value instanceof Uint8Array || Buffer.isBuffer(value)) {
    return { bytes: value.length, sha256: sha256(value) };
  }
  return value;
}

function ghostUlid(seed = "GHOST") {
  return `${seed.replace(/[^A-Z0-9]/gi, "").toUpperCase()}${"0".repeat(26)}`.slice(0, 26);
}

function contentType(headers) {
  return String(headers["content-type"] || "").split(";", 1)[0].toLowerCase();
}

function responseBodyForEvidence(response) {
  if (response.json !== null) return response.json;
  if (/^(text\/|application\/(json|problem\+json))/.test(contentType(response.headers))) {
    return response.text.slice(0, 1000);
  }
  return { bytes: response.bytes.length, sha256: sha256(response.bytes) };
}

function errorCode(response) {
  return response.json?.code ?? response.json?.detail?.code;
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

async function pythonExecutable() {
  const configured = process.env.PYTHON?.trim();
  if (configured) return configured;
  return path.join(backendRoot, ".venv", "bin", "python");
}

class RoleTenantBoundaryMatrix {
  constructor() {
    this.rows = [];
    this.assertions = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.contexts = [];
    this.identities = {};
    this.resources = { A: {}, B: {} };
    this.screenshots = {};
    this.fatalError = null;
    this.startedAt = Date.now();
  }

  assertion(pathId, name, expected, actual, pass, detail = "") {
    const item = {
      pathId,
      name,
      expected: jsonValue(expected),
      actual: jsonValue(actual),
      pass: Boolean(pass),
      detail,
    };
    this.assertions.push(item);
    if (!item.pass) {
      throw new Error(`${name}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}${detail ? ` (${detail})` : ""}`);
    }
    return item;
  }

  equal(pathId, name, actual, expected, detail = "") {
    return this.assertion(pathId, name, expected, actual, deepEqual(actual, expected), detail);
  }

  ok(pathId, name, actual, detail = "") {
    return this.assertion(pathId, name, true, Boolean(actual), Boolean(actual), detail);
  }

  excludes(pathId, name, value, forbidden) {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    const hits = forbidden.filter((needle) => needle && text.includes(String(needle)));
    return this.assertion(pathId, name, "no foreign metadata", hits, hits.length === 0);
  }

  async row({ pathId, persona, channel, surface, operation, target, fn }) {
    const started = Date.now();
    const before = this.assertions.length;
    try {
      const evidence = (await fn()) || {};
      const rowAssertions = this.assertions.slice(before);
      const pass = rowAssertions.length > 0 && rowAssertions.every((item) => item.pass);
      if (!pass) throw new Error("row emitted no passing assertions");
      const row = {
        pathId,
        persona,
        channel,
        surface,
        operation,
        target,
        status: "PASS",
        durationMs: Date.now() - started,
        assertions: rowAssertions,
        evidence,
      };
      this.rows.push(row);
      return evidence;
    } catch (error) {
      const row = {
        pathId,
        persona,
        channel,
        surface,
        operation,
        target,
        status: "FAIL",
        durationMs: Date.now() - started,
        assertions: this.assertions.slice(before),
        error: error instanceof Error ? error.message : String(error),
      };
      this.rows.push(row);
      throw error;
    }
  }

  attach(page, persona) {
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const text = message.text();
      if (/Failed to load resource: the server responded with a status of (401|403|404)/i.test(text)) return;
      this.consoleErrors.push({ persona, url: page.url(), text });
    });
    page.on("pageerror", (error) => {
      this.consoleErrors.push({ persona, url: page.url(), text: error.message });
    });
    page.on("requestfailed", (request) => {
      const failure = request.failure()?.errorText || "request failed";
      const url = request.url();
      if (failure === "net::ERR_ABORTED" && (/[?&]_rsc=/.test(url) || /download|export|results\/csv/.test(url))) return;
      if (failure === "net::ERR_ABORTED" && (/\/_next\/static\//.test(url) || /\/icon\.svg(?:\?|$)/.test(url))) return;
      if (
        failure === "net::ERR_ABORTED" &&
        request.method() === "POST" &&
        new URL(url).pathname === "/settings/organization"
      ) return;
      if (/favicon\.ico|vercel\/speed-insights|\/_next\/webpack-hmr/i.test(url)) return;
      this.requestFailures.push({ persona, url, method: request.method(), failure });
    });
  }

  async start() {
    this.buildIdentityAtStart = captureBuildIdentity(repoRoot);
    await mkdir(screenshotDir, { recursive: true });
    this.browser = await chromium.launch({
      channel: "chrome",
      headless: true,
      args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
    }).catch(() => chromium.launch({ headless: true }));
    this.cubeBytes = await readFile(cubePath);
    this.batchZip = Buffer.from(zipSync({ "cube.step": new Uint8Array(this.cubeBytes) }));
  }

  async seed() {
    const script = String.raw`
import asyncio, json, sys
from sqlalchemy import text
from ulid import ULID
from src.auth.hashing import hash_password
import src.db.engine as eng

tag, password = sys.argv[1], sys.argv[2]

async def main():
    org_a, org_b = str(ULID()), str(ULID())
    people = {
        "owner": {"role": "analyst", "orgs": [(org_a, "admin"), (org_b, "admin")], "active": org_a},
        "admin": {"role": "admin", "orgs": [(org_a, "admin"), (org_b, "admin")], "active": org_a},
        "analyst": {"role": "analyst", "orgs": [(org_a, "member"), (org_b, "member")], "active": org_a},
        "viewer": {"role": "viewer", "orgs": [(org_a, "viewer"), (org_b, "viewer")], "active": org_a},
        "platform_admin": {"role": "superadmin", "orgs": [], "active": None},
        "b_owner": {"role": "analyst", "orgs": [(org_b, "admin")], "active": org_b},
    }
    out = {"tag": tag, "orgs": {"A": org_a, "B": org_b}, "people": {}, "fixtures": {}}
    async with eng.get_session_factory()() as s:
        for key, oid in (("A", org_a), ("B", org_b)):
            await s.execute(text("INSERT INTO organizations (id,name,slug,created_at) VALUES (:i,:n,:s,now())"), {
                "i": oid, "n": f"QA Boundary Org {key} {tag}", "s": f"qa-boundary-{key.lower()}-{tag}"})
        for name, spec in people.items():
            email = f"qa-boundary-{tag}-{name.replace('_','-')}@example.com"
            row = (await s.execute(text("INSERT INTO users (email,email_lower,role,auth_provider,password_hash,current_org_id,is_active,session_version) VALUES (:e,:e,:r,'password',:p,:o,true,0) RETURNING id"), {
                "e": email, "r": spec["role"], "p": hash_password(password), "o": spec["active"]})).first()
            uid = int(row[0])
            for oid, org_role in spec["orgs"]:
                await s.execute(text("INSERT INTO memberships (id,org_id,user_id,org_role,created_at) VALUES (:id,:o,:u,:r,now())"), {
                    "id": str(ULID()), "o": oid, "u": uid, "r": org_role})
            out["people"][name] = {"id": uid, "email": email, "platform_role": spec["role"], "memberships": [{"org_id": o, "org_role": r} for o,r in spec["orgs"]]}
        for key, oid, actor in (("A", org_a, out["people"]["owner"]["id"]), ("B", org_b, out["people"]["b_owner"]["id"])):
            notification = str(ULID())
            title = f"TENANT-{key}-NOTIFICATION-{tag}"
            await s.execute(text("INSERT INTO notifications (ulid,org_id,actor_user_id,kind,severity,status,title,body,dest,source_type,source_id,metadata_json,created_at) VALUES (:id,:o,:u,'qa_boundary','info','open',:t,:b,'records','qa_boundary',:src,:m,now())"), {
                "id": notification, "o": oid, "u": actor, "t": title, "b": f"Private tenant {key} body {tag}", "src": f"{tag}-{key}", "m": json.dumps({"tenant": key, "secret_marker": f"PRIVATE-{key}-{tag}"})})
            job = str(ULID())
            await s.execute(text("INSERT INTO jobs (ulid,user_id,org_id,job_type,status,params_json,created_at) VALUES (:id,:u,:o,'qa_boundary_hold','queued',:p,now())"), {
                "id": job, "u": actor, "o": oid, "p": json.dumps({"tenant": key, "secret_marker": f"PRIVATE-{key}-{tag}"})})
            out["fixtures"][key] = {"notification_id": notification, "notification_title": title, "queued_job_id": job}
        await s.commit()
    print(json.dumps(out))
    await eng.dispose_engine()

asyncio.run(main())
`;
    const python = await pythonExecutable();
    const { stdout, stderr } = await execFileAsync(python, ["-c", script, tag, password], {
      cwd: backendRoot,
      env: { ...process.env, DATABASE_URL: databaseUrl, PYTHONPATH: backendRoot },
      timeout: 45_000,
      maxBuffer: 1024 * 1024,
    });
    if (stderr.trim()) this.seedStderr = stderr.trim().slice(0, 1000);
    this.seedData = JSON.parse(stdout);
    this.resources.A = { ...this.seedData.fixtures.A };
    this.resources.B = { ...this.seedData.fixtures.B };
  }

  async login(name) {
    const identity = this.seedData.people[name];
    const context = await this.browser.newContext({
      baseURL: appUrl,
      extraHTTPHeaders: { "x-real-ip": clientIp },
      viewport: { width: 1440, height: 960 },
      acceptDownloads: true,
      reducedMotion: "reduce",
    });
    this.contexts.push(context);
    const page = await context.newPage();
    this.attach(page, name);
    if (name === "owner") {
      await page.goto("/login", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await page.getByLabel("Email").fill(identity.email);
      await page.getByLabel("Password").fill(password);
      const loginResponsePromise = page.waitForResponse(
        (response) => response.request().method() === "POST" && response.url().includes("/api/auth/login"),
        { timeout: 45_000 },
      );
      await page.getByRole("button", { name: /^Log in$/i }).click();
      const loginResponse = await loginResponsePromise;
      if (loginResponse.status() !== 200) {
        throw new Error(`${name} login returned ${loginResponse.status()}: ${(await loginResponse.text()).slice(0, 1000)}`);
      }
      await page.waitForURL((url) => url.pathname !== "/login", { timeout: 20_000 });
    } else {
      const loginResponse = await context.request.post("/api/auth/login", {
        data: { email: identity.email, password },
        failOnStatusCode: false,
        timeout: 45_000,
      });
      if (loginResponse.status() !== 200) {
        throw new Error(`${name} API login returned ${loginResponse.status()}: ${(await loginResponse.text()).slice(0, 1000)}`);
      }
      await page.goto("/verify", { waitUntil: "domcontentloaded", timeout: 30_000 });
    }
    await page.waitForLoadState("domcontentloaded");
    const cookie = (await context.cookies()).find((item) => item.name === "dash_session");
    assert(cookie?.value, `${name} login did not set dash_session`);
    this.identities[name] = { ...identity, name, context, page, cookie: cookie.value };
    return this.identities[name];
  }

  async relogin(name) {
    const previous = this.identities[name];
    if (previous) await previous.context.close().catch(() => {});
    return this.login(name);
  }

  async response(response) {
    const bytes = Buffer.from(await response.body());
    const text = bytes.toString("utf8");
    let json = null;
    if (text && /json/i.test(response.headers()["content-type"] || "")) {
      try { json = JSON.parse(text); } catch { json = null; }
    }
    return {
      status: response.status(),
      headers: response.headers(),
      bytes,
      text,
      json,
    };
  }

  async request(actor, pathname, options = {}) {
    const direct = options.channel !== "proxy";
    const proxyPath = pathname.replace(/^\/api\/v1(?=\/|$)/, "");
    const url = direct ? `${apiUrl}${pathname}` : `/api/proxy${proxyPath}`;
    const headers = { ...(options.headers || {}) };
    if (options.bearer) headers.authorization = `Bearer ${options.bearer}`;
    else if (direct) headers.cookie = `dash_session=${actor.cookie}`;
    const requestOptions = {
      method: options.method || "GET",
      headers,
      timeout: options.timeout || 90_000,
      failOnStatusCode: false,
    };
    if (Object.prototype.hasOwnProperty.call(options, "data")) requestOptions.data = options.data;
    if (options.multipart) requestOptions.multipart = options.multipart;
    return this.response(await actor.context.request.fetch(url, requestOptions));
  }

  async switchOrg(actor, orgId, pathId = "ROLE-03", channel = "direct") {
    const result = await this.request(actor, "/api/v1/orgs/switch", {
      channel,
      method: "POST",
      data: { org_id: orgId },
    });
    this.equal(pathId, `${actor.name} switch status`, result.status, 200);
    this.equal(pathId, `${actor.name} active org after switch`, result.json?.org_id, orgId);
    return result;
  }

  async createKey(actor, label, channel = "direct") {
    const result = await this.request(actor, "/api/v1/keys", {
      channel,
      method: "POST",
      data: { name: label },
    });
    assert(result.status === 200, `key creation failed ${result.status}: ${result.text}`);
    const setCookie = result.headers["set-cookie"] || "";
    const match = setCookie.match(/cv_mint_once=([^;,]+)/);
    assert(match, "key creation did not return one-time token cookie");
    return { id: result.json.id, prefix: result.json.prefix, token: decodeURIComponent(match[1]), label };
  }

  async createTenantResources(key, actor) {
    const suffix = `TENANT-${key}-${tag}`;
    const design = await this.request(actor, "/api/v1/designs", {
      channel: "proxy",
      method: "POST",
      data: {
        name: `${suffix}-DESIGN`,
        design_note: `${suffix}-DESIGN-NOTE`,
        plan: { kind: "plate", width_mm: key === "A" ? 42 : 47, depth_mm: 30, thickness_mm: 4, holes: [] },
      },
    });
    assert(design.status === 202, `${key} design create ${design.status}: ${design.text}`);

    const analysis = await this.request(actor, "/api/v1/validate", {
      channel: "proxy",
      method: "POST",
      multipart: {
        file: { name: `${suffix}.step`, mimeType: "application/step", buffer: this.cubeBytes },
      },
    });
    assert(analysis.status === 200, `${key} analysis create ${analysis.status}: ${analysis.text.slice(0, 500)}`);
    let analyses = null;
    let analysisRow = null;
    for (let attempt = 0; attempt < 20 && !analysisRow; attempt += 1) {
      analyses = await this.request(actor, "/api/v1/analyses?limit=50", { channel: "proxy" });
      assert(analyses.status === 200, `${key} analysis list ${analyses.status}: ${analyses.text}`);
      analysisRow = analyses.json?.analyses?.find((item) => item.filename === `${suffix}.step`) || null;
      if (!analysisRow) await new Promise((resolve) => setTimeout(resolve, 250));
    }
    assert(analysisRow?.id, `${key} analysis did not persist`);

    const cost = await this.request(actor, "/api/v1/validate/cost", {
      channel: "proxy",
      method: "POST",
      multipart: {
        file: { name: `${suffix}.step`, mimeType: "application/step", buffer: this.cubeBytes },
        qty: "1,100,1000",
        material_class: "polymer",
      },
      timeout: 120_000,
    });
    assert(cost.status === 200 && cost.json?.saved?.id, `${key} cost create ${cost.status}: ${cost.text.slice(0, 500)}`);

    const batch = await this.request(actor, "/api/v1/batch", {
      channel: "proxy",
      method: "POST",
      multipart: {
        file: { name: `${suffix}.zip`, mimeType: "application/zip", buffer: this.batchZip },
        job_type: "dfm",
      },
      timeout: 120_000,
    });
    assert(batch.status === 202 && batch.json?.batch_id, `${key} batch create ${batch.status}: ${batch.text}`);

    const manifestCsv = [
      "part_number,revision,program,annual_volume,material",
      `${suffix}-PART,A,${suffix}-PROGRAM,1000,316L`,
    ].join("\n");
    const integration = await this.request(actor, "/api/v1/integrations/runs", {
      channel: "proxy",
      method: "POST",
      multipart: {
        connector_id: "sap_manifest_csv",
        mode: "dry_run",
        file: { name: `${suffix}-manifest.csv`, mimeType: "text/csv", buffer: Buffer.from(manifestCsv) },
      },
    });
    assert(integration.status === 200 && integration.json?.run?.id, `${key} integration create ${integration.status}: ${integration.text}`);

    const rfq = await this.request(actor, "/api/v1/rfq-packages", {
      channel: "proxy",
      method: "POST",
      data: {
        decision_ids: [cost.json.saved.id],
        title: `${suffix}-RFQ`,
        supplier_name: `${suffix}-SUPPLIER`,
        note: `${suffix}-RFQ-NOTE`,
        include_raw_cad: false,
      },
    });
    assert(rfq.status === 201 && rfq.json?.package?.id, `${key} RFQ create ${rfq.status}: ${rfq.text}`);

    const keyRecord = await this.createKey(actor, `${suffix}-KEY`);
    this.resources[key] = {
      ...this.resources[key],
      sentinel: suffix,
      design_id: design.json.design.id,
      design_job_id: design.json.job_id,
      design_name: `${suffix}-DESIGN`,
      analysis_id: analysisRow.id,
      analysis_filename: `${suffix}.step`,
      cost_id: cost.json.saved.id,
      cost_filename: `${suffix}.step`,
      batch_id: batch.json.batch_id,
      integration_run_id: integration.json.run.id,
      integration_filename: `${suffix}-manifest.csv`,
      integration_sha256: sha256(Buffer.from(manifestCsv)),
      rfq_id: rfq.json.package.id,
      rfq_title: `${suffix}-RFQ`,
      key: keyRecord,
    };
  }

  foreignMarkers(key) {
    const r = this.resources[key];
    return [
      r.sentinel,
      r.design_id,
      r.design_name,
      r.analysis_id,
      r.analysis_filename,
      r.cost_id,
      r.cost_filename,
      r.batch_id,
      r.integration_run_id,
      r.integration_filename,
      r.integration_sha256,
      r.rfq_id,
      r.rfq_title,
      r.notification_id,
      r.notification_title,
      r.queued_job_id,
      r.key?.prefix,
      `PRIVATE-${key}-${tag}`,
    ].filter(Boolean);
  }

  async waitForDesignReady(actor, key) {
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const result = await this.request(actor, `/api/v1/designs/${this.resources[key].design_id}`);
      if (result.status === 200 && ["ready", "failed"].includes(result.json?.design?.status)) {
        assert(result.json.design.status === "ready", `${key} design failed: ${result.text}`);
        return result;
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw new Error(`${key} design did not become ready`);
  }

  async waitForBatchTerminal(actor, key) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const result = await this.request(actor, `/api/v1/batch/${this.resources[key].batch_id}`);
      if (result.status === 200 && ["completed", "failed", "cancelled"].includes(result.json?.status)) return result;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw new Error(`${key} batch did not become terminal`);
  }

  async shot(actor, name, fullPage = true) {
    const filename = path.join(screenshotDir, `${String(Object.keys(this.screenshots).length + 1).padStart(2, "0")}-${name}.png`);
    await actor.page.screenshot({ path: filename, fullPage, animations: "disabled" });
    this.screenshots[name] = filename;
    return filename;
  }

  async browserPage(actor, pathname, { include = [], exclude = [], screenshot = null } = {}) {
    const response = await actor.page.goto(pathname, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await actor.page.waitForLoadState("networkidle", { timeout: 7000 }).catch(() => {});
    await actor.page.waitForTimeout(500);
    const text = cleanText(await actor.page.locator("body").innerText());
    for (const value of include) assert(text.includes(value), `${actor.name} ${pathname} omitted ${value}`);
    for (const value of exclude) assert(!text.includes(value), `${actor.name} ${pathname} leaked ${value}`);
    const screenshotPath = screenshot ? await this.shot(actor, screenshot) : null;
    return { status: response?.status() ?? 0, url: actor.page.url(), text, screenshotPath };
  }

  async opaqueForeign(pathId, actor, realPath, ghostPath, markers, options = {}) {
    const [known, ghost] = await Promise.all([
      this.request(actor, realPath, options),
      this.request(actor, ghostPath, options),
    ]);
    this.equal(pathId, `${actor.name} known foreign status equals ghost`, known.status, ghost.status);
    this.equal(pathId, `${actor.name} foreign status`, known.status, options.expectedStatus ?? 404);
    this.equal(pathId, `${actor.name} foreign content type equals ghost`, contentType(known.headers), contentType(ghost.headers));
    this.equal(
      pathId,
      `${actor.name} foreign response equals ghost`,
      responseBodyForEvidence(known),
      responseBodyForEvidence(ghost),
    );
    this.excludes(pathId, `${actor.name} foreign response has no metadata`, responseBodyForEvidence(known), markers);
    return { known: { status: known.status, body: responseBodyForEvidence(known) }, ghost: { status: ghost.status, body: responseBodyForEvidence(ghost) } };
  }

  async prepare() {
    await this.seed();
    for (const name of ["owner", "admin", "analyst", "viewer", "platform_admin", "b_owner"]) {
      await this.login(name);
    }
    await this.createTenantResources("A", this.identities.owner);
    await this.createTenantResources("B", this.identities.b_owner);
    await Promise.all([
      this.waitForDesignReady(this.identities.owner, "A"),
      this.waitForDesignReady(this.identities.b_owner, "B"),
      this.waitForBatchTerminal(this.identities.owner, "A"),
      this.waitForBatchTerminal(this.identities.b_owner, "B"),
    ]);

    const analyst = this.identities.analyst;
    this.resources.A.analyst_key = await this.createKey(analyst, `TENANT-A-ANALYST-${tag}`);
    await this.switchOrg(analyst, this.seedData.orgs.B);
    this.resources.B.analyst_key = await this.createKey(analyst, `TENANT-B-ANALYST-${tag}`);
    await this.switchOrg(analyst, this.seedData.orgs.A);
  }

  async runRoleCapabilityMatrix() {
    const A = this.seedData.orgs.A;
    const bOnly = this.seedData.people.b_owner;
    const roleExpectations = {
      owner: { orgAdmin: true, platformCreate: true, globalAdmin: false },
      admin: { orgAdmin: true, platformCreate: true, globalAdmin: false },
      analyst: { orgAdmin: false, platformCreate: true, globalAdmin: false },
      viewer: { orgAdmin: false, platformCreate: false, globalAdmin: false },
      platform_admin: { orgAdmin: false, platformCreate: true, globalAdmin: true },
    };

    for (const [name, expected] of Object.entries(roleExpectations)) {
      const actor = this.identities[name];
      await this.row({
        pathId: "ROLE-02",
        persona: name,
        channel: "api-direct",
        surface: "auth/session",
        operation: "read current identity",
        target: "/auth/me",
        fn: async () => {
          const result = await this.request(actor, "/auth/me");
          this.equal("ROLE-02", `${name} auth status`, result.status, 200);
          this.equal("ROLE-02", `${name} platform role`, result.json?.role, actor.platform_role);
          this.excludes("ROLE-02", `${name} auth body excludes other tenant sentinel`, result.json, this.foreignMarkers("B"));
          return { status: result.status, role: result.json?.role };
        },
      });

      await this.row({
        pathId: "ROLE-02",
        persona: name,
        channel: "api-direct",
        surface: "design",
        operation: "interpret a safe design prompt",
        target: "/api/v1/designs/interpret",
        fn: async () => {
          const result = await this.request(actor, "/api/v1/designs/interpret", {
            method: "POST",
            data: { prompt: "plate 60 mm by 40 mm by 4 mm" },
          });
          this.equal("ROLE-02", `${name} analyst-capability status`, result.status, expected.platformCreate ? 200 : 403);
          if (!expected.platformCreate) {
            this.equal("ROLE-02", `${name} analyst denial code`, errorCode(result), "insufficient_role");
          }
          return { status: result.status, body: responseBodyForEvidence(result) };
        },
      });

      await this.row({
        pathId: "ROLE-02",
        persona: name,
        channel: "api-proxy",
        surface: "organization",
        operation: "list active-org invitations",
        target: "/api/proxy/orgs/invites",
        fn: async () => {
          const result = await this.request(actor, "/api/v1/orgs/invites", { channel: "proxy" });
          const expectedStatus = expected.orgAdmin ? 200 : 403;
          this.equal("ROLE-02", `${name} org-admin status`, result.status, expectedStatus);
          if (!expected.orgAdmin) {
            const code = errorCode(result);
            this.equal(
              "ROLE-02",
              `${name} org-admin denial code`,
              code,
              name === "platform_admin" ? "FORBIDDEN" : "insufficient_org_role",
            );
            if (name === "platform_admin") {
              this.equal("ROLE-02", "platform-admin no-tenant denial message", result.json?.message, "No organization for caller.");
            }
          }
          this.excludes("ROLE-02", `${name} org-admin response excludes B-only account`, result.json, [bOnly.email]);
          return { status: result.status, body: responseBodyForEvidence(result) };
        },
      });

      await this.row({
        pathId: "ROLE-02",
        persona: name,
        channel: "api-direct",
        surface: "integrations/credentials",
        operation: "list credential profiles",
        target: "/api/v1/integrations/credential-profiles",
        fn: async () => {
          const result = await this.request(actor, "/api/v1/integrations/credential-profiles");
          this.equal("ROLE-02", `${name} credential-admin status`, result.status, expected.orgAdmin ? 200 : 403);
          this.excludes("ROLE-02", `${name} credential response excludes foreign tenant`, result.json, this.foreignMarkers("B"));
          return { status: result.status, body: responseBodyForEvidence(result) };
        },
      });

      await this.row({
        pathId: "ROLE-02",
        persona: name,
        channel: "api-direct",
        surface: "platform administration",
        operation: "list users",
        target: expected.globalAdmin
          ? `/api/v1/admin/users?cursor=${this.identities.owner.id - 1}&limit=100`
          : "/api/v1/admin/users?limit=100",
        fn: async () => {
          const pathname = expected.globalAdmin
            ? `/api/v1/admin/users?cursor=${this.identities.owner.id - 1}&limit=100`
            : "/api/v1/admin/users?limit=100";
          const result = await this.request(actor, pathname);
          const expectedStatus = expected.orgAdmin || expected.globalAdmin ? 200 : 403;
          this.equal("ROLE-02", `${name} admin-users status`, result.status, expectedStatus);
          if (result.status === 200) {
            const ids = (result.json?.users || []).map((item) => item.id);
            if (expected.globalAdmin) {
              this.ok("ROLE-02", `${name} global user list includes A owner`, ids.includes(this.identities.owner.id));
              this.ok("ROLE-02", `${name} global user list includes B-only owner`, ids.includes(bOnly.id));
            } else {
              this.ok("ROLE-02", `${name} scoped user list includes A owner`, ids.includes(this.identities.owner.id));
              this.ok("ROLE-02", `${name} scoped user list hides B-only owner`, !ids.includes(bOnly.id));
              this.excludes("ROLE-02", `${name} scoped user list has no B-only email`, result.json, [bOnly.email]);
            }
          }
          return { status: result.status, count: result.json?.users?.length ?? 0 };
        },
      });

      await this.row({
        pathId: "ROLE-02",
        persona: name,
        channel: "api-direct",
        surface: "API keys",
        operation: "list own active-org keys",
        target: "/api/v1/keys",
        fn: async () => {
          const result = await this.request(actor, "/api/v1/keys");
          this.equal("ROLE-02", `${name} own key list status`, result.status, 200);
          this.excludes("ROLE-02", `${name} key list excludes owner B key`, result.json, [this.resources.B.key.prefix, this.resources.B.key.label]);
          return { status: result.status, keyCount: Array.isArray(result.json) ? result.json.length : null };
        },
      });
    }

    for (const name of ["owner", "admin"]) {
      const actor = this.identities[name];
      await this.row({
        pathId: "ROLE-02",
        persona: name,
        channel: "api-direct",
        surface: "platform administration",
        operation: "attempt global role mutation",
        target: `/api/v1/admin/users/${bOnly.id}/role`,
        fn: async () => {
          const result = await this.request(actor, `/api/v1/admin/users/${bOnly.id}/role`, {
            method: "PATCH",
            data: { role: "analyst" },
          });
          this.equal("ROLE-02", `${name} global role mutation denied`, result.status, 403);
          this.equal("ROLE-02", `${name} global role denial code`, errorCode(result), "platform_superadmin_required");
          return { status: result.status, body: result.json };
        },
      });
    }

    await this.row({
      pathId: "ROLE-02",
      persona: "platform_admin",
      channel: "api-direct",
      surface: "platform administration",
      operation: "idempotently retain a user's global role",
      target: `/api/v1/admin/users/${bOnly.id}/role`,
      fn: async () => {
        const result = await this.request(this.identities.platform_admin, `/api/v1/admin/users/${bOnly.id}/role`, {
          method: "PATCH",
          data: { role: "analyst" },
        });
        this.equal("ROLE-02", "platform-admin global role mutation status", result.status, 200);
        this.equal("ROLE-02", "platform-admin retained exact role", result.json?.role, "analyst");
        return { status: result.status, role: result.json?.role };
      },
    });

    const browserExpectations = [
      ["owner", ["Manage members, invites, and SSO", this.identities.owner.email], [bOnly.email]],
      ["admin", ["Manage members, invites, and SSO", this.identities.admin.email], [bOnly.email]],
      ["analyst", ["Admins only"], [bOnly.email]],
      ["viewer", ["Admins only"], [bOnly.email]],
      ["platform_admin", ["Admins only"], [this.resources.A.sentinel, this.resources.B.sentinel]],
    ];
    for (const [name, include, exclude] of browserExpectations) {
      const actor = this.identities[name];
      await this.row({
        pathId: "ROLE-02",
        persona: name,
        channel: "browser",
        surface: "organization settings",
        operation: "open direct protected URL",
        target: "/settings/organization",
        fn: async () => {
          const page = await this.browserPage(actor, "/settings/organization", {
            include,
            exclude,
            screenshot: `role-${name}-organization`,
          });
          this.equal("ROLE-02", `${name} organization browser HTTP`, page.status, 200);
          this.ok("ROLE-02", `${name} organization browser visible state`, include.every((value) => page.text.includes(value)));
          this.excludes("ROLE-02", `${name} organization browser no foreign metadata`, page.text, exclude);
          return { url: page.url, visible: include, screenshot: page.screenshotPath };
        },
      });
    }

    await this.row({
      pathId: "ROLE-02",
      persona: "owner",
      channel: "browser",
      surface: "API keys",
      operation: "create a key and reveal plaintext once",
      target: "/settings/developer",
      fn: async () => {
        const owner = this.identities.owner;
        await owner.page.goto("/settings/developer", { waitUntil: "domcontentloaded" });
        await owner.page.getByRole("button", { name: "Create key" }).first().click();
        await owner.page.getByRole("heading", { name: "Save your API key" }).waitFor({ timeout: 15_000 });
        const token = cleanText(await owner.page.locator("pre").innerText());
        this.ok("ROLE-02", "browser reveals a cv_live key", /^cv_live_/.test(token));
        this.equal("ROLE-02", "browser one-time key is not foreign B key", token === this.resources.B.key.token, false);
        const screenshot = await this.shot(owner, "owner-api-key-one-time-reveal");
        await owner.page.getByLabel("I've saved it somewhere safe").check();
        await owner.page.getByRole("button", { name: "Done" }).click();
        await owner.page.reload({ waitUntil: "domcontentloaded" });
        this.equal("ROLE-02", "one-time key is not revealed after reload", await owner.page.getByRole("heading", { name: "Save your API key" }).count(), 0);
        return { url: owner.page.url(), tokenPrefix: token.slice(0, 18), screenshot };
      },
    });

    this.roleCapabilityPersisted = {
      orgA: A,
      ownerPlatformRole: this.identities.owner.platform_role,
      adminPlatformRole: this.identities.admin.platform_role,
      analystPlatformRole: this.identities.analyst.platform_role,
      viewerPlatformRole: this.identities.viewer.platform_role,
      platformAdminRole: this.identities.platform_admin.platform_role,
    };
  }

  async scopedListRow(actor, key, surface, pathname, ownNeedle, foreignNeedle) {
    return this.row({
      pathId: "ROLE-04",
      persona: actor.name,
      channel: "api-direct",
      surface,
      operation: `list organization ${key} records`,
      target: pathname,
      fn: async () => {
        const result = await this.request(actor, pathname);
        this.equal("ROLE-04", `${surface} list status in ${key}`, result.status, 200);
        this.ok("ROLE-04", `${surface} list contains ${key} record`, JSON.stringify(result.json).includes(String(ownNeedle)));
        this.excludes("ROLE-04", `${surface} list excludes foreign record`, result.json, [foreignNeedle]);
        return { status: result.status, ownNeedle, foreignNeedle };
      },
    });
  }

  async sameOrgSurfaceRow(actor, surface, pathname, expectedNeedle = null, expectedContentType = null) {
    return this.row({
      pathId: "ROLE-04",
      persona: actor.name,
      channel: "api-direct",
      surface,
      operation: "read same-organization detail or artifact",
      target: pathname,
      fn: async () => {
        const result = await this.request(actor, pathname);
        this.equal("ROLE-04", `${surface} same-org status`, result.status, 200);
        const bodyNeedle = expectedNeedle && typeof expectedNeedle === "object"
          ? expectedNeedle.body ?? null
          : expectedNeedle;
        if (bodyNeedle !== null) {
          this.ok("ROLE-04", `${surface} same-org body linkage`, JSON.stringify(responseBodyForEvidence(result)).includes(String(bodyNeedle)));
        } else {
          this.ok("ROLE-04", `${surface} same-org artifact nonempty`, result.bytes.length > 0);
        }
        if (expectedNeedle && typeof expectedNeedle === "object" && expectedNeedle.filename) {
          this.ok(
            "ROLE-04",
            `${surface} download filename linkage`,
            String(result.headers["content-disposition"] || "").includes(expectedNeedle.filename),
          );
        }
        if (expectedContentType) {
          this.ok("ROLE-04", `${surface} content type`, contentType(result.headers).includes(expectedContentType));
        }
        return { status: result.status, contentType: contentType(result.headers), bytes: result.bytes.length };
      },
    });
  }

  async browserSwitchOrganization(actor, key) {
    const org = this.seedData.orgs[key];
    const name = `QA Boundary Org ${key} ${tag}`;
    await actor.page.goto("/settings/organization", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await actor.page.getByRole("heading", { name: "Organization" }).waitFor({ timeout: 12_000 });
    const switcher = actor.page.getByRole("combobox", { name: "Active organization" });
    this.equal("ROLE-03", `${actor.name} browser org switcher count`, await switcher.count(), 1);
    const responsePromise = actor.page.waitForResponse(
      (response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/settings/organization",
      { timeout: 20_000 },
    );
    await switcher.click();
    await actor.page.getByRole("option", { name, exact: true }).click();
    const response = await responsePromise;
    this.equal("ROLE-03", `${actor.name} browser switch response`, response.status(), 200);
    await actor.page.waitForFunction(
      (expected) => document.body.innerText.includes(expected),
      name,
      { timeout: 20_000 },
    );
    await actor.page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
    await actor.page.waitForTimeout(500);
    const me = await this.request(actor, "/api/v1/orgs");
    this.equal("ROLE-03", `${actor.name} browser switch persisted active org`, me.json?.active_org_id, org);
    const screenshot = await this.shot(actor, `${actor.name}-switched-to-${key.toLowerCase()}`);
    return { org, name, url: actor.page.url(), screenshot };
  }

  async runSameOrgAndCrossTenantMatrix() {
    const viewer = this.identities.viewer;
    const A = this.resources.A;
    const B = this.resources.B;

    const lists = [
      ["designs", "/api/v1/designs?limit=100", A.design_id, B.design_id],
      ["analyses", "/api/v1/analyses?limit=50", A.analysis_id, B.analysis_id],
      ["cost decisions", "/api/v1/cost-decisions?limit=100", A.cost_id, B.cost_id],
      ["batches", "/api/v1/batches?limit=100", A.batch_id, B.batch_id],
      ["integration runs", "/api/v1/integrations/runs?limit=100", A.integration_run_id, B.integration_run_id],
      ["RFQ packages", "/api/v1/rfq-packages?limit=100", A.rfq_id, B.rfq_id],
      ["notifications", "/api/v1/notifications?limit=100", A.notification_id, B.notification_id],
    ];
    for (const [surface, pathname, ownNeedle, foreignNeedle] of lists) {
      await this.scopedListRow(viewer, "A", surface, pathname, ownNeedle, foreignNeedle);
    }

    const sameOrgSurfaces = [
      ["design detail", `/api/v1/designs/${A.design_id}`, A.design_id, "json"],
      ["design revisions", `/api/v1/designs/${A.design_id}/revisions`, A.design_id, "json"],
      ["design STEP download", `/api/v1/designs/${A.design_id}/download.step`, null, "step"],
      ["analysis detail", `/api/v1/analyses/${A.analysis_id}`, A.analysis_id, "json"],
      ["analysis PDF", `/api/v1/analyses/${A.analysis_id}/pdf`, null, "pdf"],
      ["cost detail", `/api/v1/cost-decisions/${A.cost_id}`, A.cost_id, "json"],
      ["cost JSON export", `/api/v1/cost-decisions/${A.cost_id}/export.json`, { body: "geometry", filename: A.cost_filename.replace(/\.step$/i, "") }, "json"],
      ["cost CSV export", `/api/v1/cost-decisions/${A.cost_id}/export.csv`, null, "csv"],
      ["cost PDF", `/api/v1/cost-decisions/${A.cost_id}/pdf`, null, "pdf"],
      ["batch detail", `/api/v1/batch/${A.batch_id}`, A.batch_id, "json"],
      ["batch items", `/api/v1/batch/${A.batch_id}/items`, "cube.step", "json"],
      ["batch CSV", `/api/v1/batch/${A.batch_id}/results/csv`, null, "csv"],
      ["integration detail", `/api/v1/integrations/runs/${A.integration_run_id}`, A.integration_run_id, "json"],
      ["RFQ detail", `/api/v1/rfq-packages/${A.rfq_id}`, A.rfq_id, "json"],
      ["RFQ ZIP", `/api/v1/rfq-packages/${A.rfq_id}/download.zip`, null, "zip"],
      ["queued job", `/api/v1/jobs/${A.queued_job_id}`, "queued", "json"],
    ];
    for (const [surface, pathname, expectedNeedle, expectedType] of sameOrgSurfaces) {
      await this.sameOrgSurfaceRow(viewer, surface, pathname, expectedNeedle, expectedType);
    }

    const browserLists = [
      ["/designs", A.design_name, B.design_name],
      ["/history", A.analysis_filename, B.analysis_filename],
      ["/cost-decisions", A.cost_filename, B.cost_filename],
      ["/batch", A.batch_id.slice(0, 12), B.batch_id.slice(0, 12)],
      ["/integrations", `${A.integration_sha256.slice(0, 10)}...`, `${B.integration_sha256.slice(0, 10)}...`],
    ];
    for (const [pathname, ownNeedle, foreignNeedle] of browserLists) {
      await this.row({
        pathId: "ROLE-04",
        persona: "viewer",
        channel: "browser",
        surface: pathname,
        operation: "open same-org list",
        target: pathname,
        fn: async () => {
          const page = await this.browserPage(viewer, pathname, { include: [ownNeedle], exclude: [foreignNeedle] });
          this.equal("ROLE-04", `${pathname} browser HTTP`, page.status, 200);
          this.ok("ROLE-04", `${pathname} browser contains own row`, page.text.includes(ownNeedle));
          this.equal("ROLE-04", `${pathname} browser foreign row count`, page.text.includes(foreignNeedle), false);
          return { url: page.url, visible: ownNeedle };
        },
      });
    }

    await this.row({
      pathId: "VER-04",
      persona: "viewer",
      channel: "browser+api",
      surface: "notifications",
      operation: "open, mark read, refresh, and reopen durable state",
      target: "/notifications",
      fn: async () => {
        const page = await this.browserPage(viewer, "/notifications", {
          include: [A.notification_title],
          exclude: [B.notification_title],
        });
        const markPromise = viewer.page.waitForResponse(
          (response) => response.request().method() === "POST" && response.url().includes(`/notifications/${A.notification_id}/read`),
          { timeout: 20_000 },
        );
        await viewer.page.getByText(A.notification_title, { exact: true }).click();
        const markResponse = await markPromise;
        this.equal("VER-04", "notification mark-read response", markResponse.status(), 200);
        const markBody = await markResponse.json();
        this.equal("VER-04", "notification mark-read response ID", markBody?.notification?.id, A.notification_id);
        this.ok("VER-04", "notification mark-read response timestamp", markBody?.notification?.read_at);
        await viewer.page.waitForURL((url) => url.pathname === "/verify", { timeout: 15_000 });
        const all = await this.request(viewer, "/api/v1/notifications?status=open&unread=false&limit=100");
        const unread = await this.request(viewer, "/api/v1/notifications?status=open&unread=true&limit=100");
        const persisted = (all.json?.notifications || []).find((item) => item.id === A.notification_id);
        this.equal("VER-04", "durable notification detail remains scoped and present", persisted?.id, A.notification_id);
        this.ok("VER-04", "durable notification has read timestamp", persisted?.read_at);
        this.equal("VER-04", "read notification absent from unread list", (unread.json?.notifications || []).some((item) => item.id === A.notification_id), false);
        await viewer.page.goto("/notifications", { waitUntil: "domcontentloaded" });
        await viewer.page.waitForFunction(
          (title) => !document.body.innerText.includes("Reading current states...") && !document.body.innerText.includes(title),
          A.notification_title,
          { timeout: 15_000 },
        );
        this.equal("VER-04", "notification absent after browser reopen", await viewer.page.getByText(A.notification_title, { exact: true }).count(), 0);
        await viewer.page.reload({ waitUntil: "domcontentloaded" });
        await viewer.page.waitForFunction(
          (title) => !document.body.innerText.includes("Reading current states...") && !document.body.innerText.includes(title),
          A.notification_title,
          { timeout: 15_000 },
        );
        this.equal("VER-04", "notification stays absent after browser refresh", await viewer.page.getByText(A.notification_title, { exact: true }).count(), 0);
        const screenshot = await this.shot(viewer, "notification-read-state-durable");
        this.notificationPersisted = { id: persisted.id, readAt: persisted.read_at, unreadAfter: 0 };
        return { url: viewer.page.url(), initialUrl: page.url, screenshot, readAt: persisted.read_at };
      },
    });

    await this.row({
      pathId: "ROLE-03",
      persona: "viewer",
      channel: "browser",
      surface: "organization switcher",
      operation: "switch from organization A to B",
      target: "/settings/organization",
      fn: async () => this.browserSwitchOrganization(viewer, "B"),
    });

    for (const [surface, pathname, , foreignNeedle] of lists) {
      await this.scopedListRow(viewer, "B", surface, pathname, foreignNeedle, lists.find((entry) => entry[0] === surface)?.[2]);
    }

    await this.row({
      pathId: "VER-04",
      persona: "viewer",
      channel: "browser+api",
      surface: "notifications",
      operation: "reopen inbox after organization switch",
      target: "/notifications",
      fn: async () => {
        const page = await this.browserPage(viewer, "/notifications", {
          include: [B.notification_title],
          exclude: [A.notification_title],
          screenshot: "notification-org-b-scoped",
        });
        this.equal("VER-04", "organization B notification browser HTTP", page.status, 200);
        const foreign = await this.opaqueForeign(
          "VER-04",
          viewer,
          `/api/v1/notifications/${A.notification_id}/read`,
          `/api/v1/notifications/${ghostUlid("NOTIFICATION")}/read`,
          this.foreignMarkers("A"),
          { method: "POST" },
        );
        this.notificationRecovery = { orgBVisible: true, foreignStatus: foreign.known.status };
        return { url: page.url, screenshot: page.screenshotPath, foreign };
      },
    });

    const ghost = ghostUlid("BOUNDARY");
    const probes = [
      ["design detail", `/api/v1/designs/${A.design_id}`, `/api/v1/designs/${ghost}`],
      ["design revisions", `/api/v1/designs/${A.design_id}/revisions`, `/api/v1/designs/${ghost}/revisions`],
      ["design STEP", `/api/v1/designs/${A.design_id}/download.step`, `/api/v1/designs/${ghost}/download.step`],
      ["analysis detail", `/api/v1/analyses/${A.analysis_id}`, `/api/v1/analyses/${ghost}`],
      ["analysis PDF", `/api/v1/analyses/${A.analysis_id}/pdf`, `/api/v1/analyses/${ghost}/pdf`],
      ["cost detail", `/api/v1/cost-decisions/${A.cost_id}`, `/api/v1/cost-decisions/${ghost}`],
      ["cost JSON export", `/api/v1/cost-decisions/${A.cost_id}/export.json`, `/api/v1/cost-decisions/${ghost}/export.json`],
      ["cost CSV export", `/api/v1/cost-decisions/${A.cost_id}/export.csv`, `/api/v1/cost-decisions/${ghost}/export.csv`],
      ["cost PDF", `/api/v1/cost-decisions/${A.cost_id}/pdf`, `/api/v1/cost-decisions/${ghost}/pdf`],
      ["batch detail", `/api/v1/batch/${A.batch_id}`, `/api/v1/batch/${ghost}`],
      ["batch items", `/api/v1/batch/${A.batch_id}/items`, `/api/v1/batch/${ghost}/items`],
      ["batch CSV", `/api/v1/batch/${A.batch_id}/results/csv`, `/api/v1/batch/${ghost}/results/csv`],
      ["integration detail", `/api/v1/integrations/runs/${A.integration_run_id}`, `/api/v1/integrations/runs/${ghost}`],
      ["RFQ detail", `/api/v1/rfq-packages/${A.rfq_id}`, `/api/v1/rfq-packages/${ghost}`],
      ["RFQ ZIP", `/api/v1/rfq-packages/${A.rfq_id}/download.zip`, `/api/v1/rfq-packages/${ghost}/download.zip`],
      ["queued job detail", `/api/v1/jobs/${A.queued_job_id}`, `/api/v1/jobs/${ghost}`],
      ["queued job result", `/api/v1/jobs/${A.queued_job_id}/result`, `/api/v1/jobs/${ghost}/result`],
    ];
    for (const [surface, knownPath, ghostPath] of probes) {
      await this.row({
        pathId: "ROLE-04",
        persona: "viewer",
        channel: "api-direct",
        surface,
        operation: "compare known foreign ID with unknown ID",
        target: knownPath,
        fn: async () => this.opaqueForeign("ROLE-04", viewer, knownPath, ghostPath, this.foreignMarkers("A")),
      });
    }

    await this.row({
      pathId: "ROLE-04",
      persona: "viewer",
      channel: "api-direct",
      surface: "API keys",
      operation: "guess another user's numeric key identifier",
      target: `/api/v1/keys/${A.key.id}`,
      fn: async () => this.opaqueForeign(
        "ROLE-04",
        viewer,
        `/api/v1/keys/${A.key.id}`,
        "/api/v1/keys/2147483647",
        this.foreignMarkers("A"),
        { method: "PATCH", data: { name: `GUESS-${tag}` } },
      ),
    });

    await this.row({
      pathId: "ROLE-04",
      persona: "viewer",
      channel: "browser",
      surface: "direct URL access",
      operation: "open known foreign cost detail",
      target: `/cost-decisions/${A.cost_id}`,
      fn: async () => {
        const responsePromise = viewer.page.waitForResponse(
          (response) =>
            response.request().method() === "GET" &&
            new URL(response.url()).pathname === `/api/proxy/cost-decisions/${A.cost_id}`,
          { timeout: 20_000 },
        );
        await viewer.page.goto(`/cost-decisions/${A.cost_id}`, { waitUntil: "domcontentloaded" });
        const response = await responsePromise;
        await viewer.page.getByText("Cost decision not found", { exact: true }).first().waitFor({ timeout: 12_000 });
        const text = cleanText(await viewer.page.locator("body").innerText());
        this.equal("ROLE-04", "foreign browser proxy status", response.status(), 404);
        this.excludes("ROLE-04", "foreign browser page has no A metadata", text, this.foreignMarkers("A"));
        await viewer.page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
        await viewer.page.waitForTimeout(500);
        const screenshot = await this.shot(viewer, "foreign-cost-direct-url-opaque");
        this.crossTenantPersisted = { activeOrg: this.seedData.orgs.B, foreignStatus: response.status(), markerLeaks: 0 };
        return { url: viewer.page.url(), screenshot, status: response.status() };
      },
    });
  }

  async runBearerAndMembershipLifecycle() {
    const owner = this.identities.owner;
    const analyst = this.identities.analyst;
    const A = this.resources.A;
    const B = this.resources.B;

    await this.row({
      pathId: "ROLE-03",
      persona: "owner",
      channel: "api-direct",
      surface: "API-key tenant binding",
      operation: "switch dashboard org without moving bearer credential",
      target: "/api/v1/orgs/switch",
      fn: async () => {
        const before = await this.request(owner, `/api/v1/cost-decisions/${A.cost_id}`, { bearer: A.key.token });
        this.equal("ROLE-03", "A bearer works before dashboard switch", before.status, 200);
        const attemptsSwitch = await this.request(owner, "/api/v1/orgs/switch", {
          bearer: A.key.token,
          method: "POST",
          data: { org_id: this.seedData.orgs.B },
        });
        this.equal("ROLE-03", "bearer organization switch denied", attemptsSwitch.status, 403);
        this.equal("ROLE-03", "bearer switch denial code", errorCode(attemptsSwitch), "api_key_org_bound");
        await this.switchOrg(owner, this.seedData.orgs.B);
        const after = await this.request(owner, `/api/v1/cost-decisions/${A.cost_id}`, { bearer: A.key.token });
        this.equal("ROLE-03", "A bearer is rejected after dashboard switches to B", after.status, 403);
        this.equal("ROLE-03", "A bearer mismatch code after dashboard switch", errorCode(after), "api_key_org_mismatch");
        const foreign = await this.request(owner, `/api/v1/cost-decisions/${B.cost_id}`, { bearer: A.key.token });
        this.equal("ROLE-03", "A bearer cannot read B decision", foreign.status, 403);
        this.equal("ROLE-03", "A bearer B denial code", errorCode(foreign), "api_key_org_mismatch");
        this.excludes("ROLE-03", "A bearer denial excludes B metadata", foreign.json, this.foreignMarkers("B"));
        await this.switchOrg(owner, this.seedData.orgs.A);
        const recovered = await this.request(owner, `/api/v1/cost-decisions/${A.cost_id}`, { bearer: A.key.token });
        this.equal("ROLE-03", "A bearer works after dashboard switches back", recovered.status, 200);
        this.bearerPersisted = {
          before: before.status,
          afterDashboardSwitch: after.status,
          crossTenant: foreign.status,
          switchDenied: attemptsSwitch.status,
          recovered: recovered.status,
        };
        return this.bearerPersisted;
      },
    });

    await this.row({
      pathId: "ROLE-03",
      persona: "owner removing analyst",
      channel: "browser",
      surface: "organization members",
      operation: "remove member from organization A",
      target: "/settings/organization",
      fn: async () => {
        await owner.page.goto("/settings/organization", { waitUntil: "domcontentloaded" });
        const row = owner.page.getByRole("row").filter({ hasText: analyst.email });
        await row.waitFor({ timeout: 15_000 });
        await row.getByRole("button", { name: "Remove" }).click();
        await owner.page.getByRole("button", { name: "Remove member" }).click();
        await row.waitFor({ state: "detached", timeout: 20_000 });
        let list = null;
        for (let attempt = 0; attempt < 20; attempt += 1) {
          list = await this.request(owner, "/api/v1/orgs/members");
          if (list.status === 200 && !(list.json?.members || []).some((item) => item.user_id === analyst.id)) break;
          await new Promise((resolve) => setTimeout(resolve, 250));
        }
        this.equal("ROLE-03", "owner member list after removal status", list?.status, 200);
        this.equal("ROLE-03", "removed analyst absent from durable member list", (list?.json?.members || []).some((item) => item.user_id === analyst.id), false);
        const screenshot = await this.shot(owner, "analyst-removed-from-org-a");
        return { url: owner.page.url(), screenshot, remainingMembers: list.json?.members?.length ?? null };
      },
    });

    await this.row({
      pathId: "ROLE-03",
      persona: "removed analyst",
      channel: "api-direct+bearer",
      surface: "membership and API-key lifecycle",
      operation: "reuse stale session and org-bound keys after removal",
      target: "/api/v1/orgs",
      fn: async () => {
        const me = await this.request(analyst, "/auth/me");
        this.equal("ROLE-03", "membership removal does not revoke whole dashboard session", me.status, 200);
        const orgs = await this.request(analyst, "/api/v1/orgs");
        this.equal("ROLE-03", "removed analyst organizations status", orgs.status, 200);
        this.equal("ROLE-03", "removed analyst active org falls back to B", orgs.json?.active_org_id, this.seedData.orgs.B);
        this.equal("ROLE-03", "removed analyst no longer lists A", (orgs.json?.organizations || []).some((item) => item.org_id === this.seedData.orgs.A), false);
        this.equal("ROLE-03", "removed analyst still lists B", (orgs.json?.organizations || []).some((item) => item.org_id === this.seedData.orgs.B), true);

        const dashboardA = await this.request(analyst, `/api/v1/designs/${A.design_id}`);
        const dashboardB = await this.request(analyst, `/api/v1/designs/${B.design_id}`);
        this.equal("ROLE-03", "removed analyst dashboard loses A", dashboardA.status, 404);
        this.equal("ROLE-03", "removed analyst dashboard retains B", dashboardB.status, 200);
        this.excludes("ROLE-03", "removed analyst A denial has no metadata", dashboardA.json, this.foreignMarkers("A"));

        const aKey = await this.request(analyst, `/api/v1/designs/${A.design_id}`, { bearer: A.analyst_key.token });
        const bKey = await this.request(analyst, `/api/v1/designs/${B.design_id}`, { bearer: B.analyst_key.token });
        this.equal("ROLE-03", "removed organization A key is revoked", aKey.status, 401);
        this.equal("ROLE-03", "organization B key remains valid", bKey.status, 200);
        this.equal("ROLE-03", "revoked A key denial code", errorCode(aKey), "auth_invalid");

        const switchBack = await this.request(analyst, "/api/v1/orgs/switch", {
          method: "POST",
          data: { org_id: this.seedData.orgs.A },
        });
        this.equal("ROLE-03", "removed analyst cannot switch back to A", switchBack.status, 403);
        this.excludes("ROLE-03", "switch denial has no A resource metadata", switchBack.json, this.foreignMarkers("A"));
        this.membershipPersisted = {
          activeOrg: orgs.json?.active_org_id,
          organizations: orgs.json?.organizations?.map((item) => item.org_id),
          aDashboard: dashboardA.status,
          bDashboard: dashboardB.status,
          aKey: aKey.status,
          bKey: bKey.status,
        };
        return this.membershipPersisted;
      },
    });

    await this.row({
      pathId: "ROLE-03",
      persona: "removed analyst",
      channel: "browser",
      surface: "stale open browser",
      operation: "navigate after membership removal",
      target: "/designs",
      fn: async () => {
        const page = await this.browserPage(analyst, "/designs", {
          include: [B.design_name],
          exclude: [A.design_name],
          screenshot: "removed-analyst-browser-falls-back-to-b",
        });
        this.equal("ROLE-03", "removed analyst protected browser HTTP", page.status, 200);
        this.ok("ROLE-03", "removed analyst browser shows B", page.text.includes(B.design_name));
        this.equal("ROLE-03", "removed analyst browser hides A", page.text.includes(A.design_name), false);
        this.membershipRecovery = { url: page.url, activeOrganization: "B", AVisible: false, BVisible: true };
        return { ...this.membershipRecovery, screenshot: page.screenshotPath };
      },
    });
  }

  async runStaleSessionLifecycle() {
    const viewer = this.identities.viewer;
    const platformAdmin = this.identities.platform_admin;
    const B = this.resources.B;
    await this.row({
      pathId: "FAIL-09",
      persona: "platform-admin revoking viewer",
      channel: "api-direct",
      surface: "session administration",
      operation: "revoke all dashboard sessions",
      target: `/api/v1/admin/users/${viewer.id}/revoke-sessions`,
      fn: async () => {
        const before = await this.request(viewer, `/api/v1/designs/${B.design_id}`);
        this.equal("FAIL-09", "viewer session works before revocation", before.status, 200);
        const revoked = await this.request(platformAdmin, `/api/v1/admin/users/${viewer.id}/revoke-sessions`, { method: "POST" });
        this.equal("FAIL-09", "platform-admin revoke-session status", revoked.status, 200);
        this.equal("FAIL-09", "revoked user id", revoked.json?.user_id, viewer.id);
        this.ok("FAIL-09", "session version incremented", Number(revoked.json?.session_version) >= 1);
        this.sessionRevocationPersisted = revoked.json;
        return { before: before.status, revoke: revoked.status, body: revoked.json };
      },
    });

    await this.row({
      pathId: "FAIL-09",
      persona: "viewer with revoked session",
      channel: "api-direct+browser",
      surface: "stale session",
      operation: "reuse revoked cookie",
      target: "/designs",
      fn: async () => {
        const stale = await this.request(viewer, "/auth/me");
        this.equal("FAIL-09", "stale cookie direct status", stale.status, 401);
        this.equal("FAIL-09", "stale cookie denial code", errorCode(stale), "session_revoked");
        this.excludes("FAIL-09", "stale cookie denial has no tenant metadata", stale.json, [...this.foreignMarkers("A"), ...this.foreignMarkers("B")]);
        await viewer.page.goto("/designs", { waitUntil: "domcontentloaded" });
        await viewer.page.waitForURL((url) => url.pathname === "/login", { timeout: 20_000 });
        const text = cleanText(await viewer.page.locator("body").innerText());
        this.excludes("FAIL-09", "stale browser login page has no tenant metadata", text, [...this.foreignMarkers("A"), ...this.foreignMarkers("B")]);
        const screenshot = await this.shot(viewer, "revoked-viewer-session-login");
        this.staleSessionObserved = { status: stale.status, code: errorCode(stale), url: viewer.page.url(), screenshot };
        return this.staleSessionObserved;
      },
    });

    await this.row({
      pathId: "FAIL-09",
      persona: "viewer relogging in",
      channel: "browser+api",
      surface: "session recovery",
      operation: "authenticate again and reopen active organization",
      target: "/login",
      fn: async () => {
        const fresh = await this.relogin("viewer");
        const orgs = await this.request(fresh, "/api/v1/orgs");
        this.equal("FAIL-09", "fresh session organizations status", orgs.status, 200);
        this.equal("FAIL-09", "fresh session retains organization B", orgs.json?.active_org_id, this.seedData.orgs.B);
        const page = await this.browserPage(fresh, "/designs", {
          include: [B.design_name],
          exclude: [this.resources.A.design_name],
          screenshot: "viewer-relogin-recovers-org-b",
        });
        this.ok("FAIL-09", "fresh browser displays authorized B record", page.text.includes(B.design_name));
        this.equal("FAIL-09", "fresh browser hides A record", page.text.includes(this.resources.A.design_name), false);
        this.sessionRecovery = { activeOrg: orgs.json?.active_org_id, url: page.url, BVisible: true, AVisible: false };
        return { ...this.sessionRecovery, screenshot: page.screenshotPath };
      },
    });
  }

  buildGoldenPaths() {
    const observations = {
      "ROLE-02": {
        url: this.identities.owner?.page.url() || `${appUrl}/settings/developer`,
        visible: ["Five role personas exercised in the live browser and API."],
        persisted: this.roleCapabilityPersisted || "not-observed",
        numeric: {
          personas: 5,
          passingAssertions: this.assertions.filter((item) => item.pathId === "ROLE-02" && item.pass).length,
        },
        authorization: { roleLadder: "viewer < analyst < admin < superadmin", crossTenantAdminVisibility: "scoped" },
        recovery: "One-time API-key plaintext was absent after browser reload.",
        screenshot: this.screenshots["owner-api-key-one-time-reveal"],
      },
      "ROLE-03": {
        url: this.identities.analyst?.page.url() || `${appUrl}/designs`,
        visible: ["Removed analyst reopened organization B designs without organization A metadata."],
        persisted: { bearer: this.bearerPersisted, membership: this.membershipPersisted },
        numeric: { aKeyStatus: this.membershipPersisted?.aKey, bKeyStatus: this.membershipPersisted?.bKey },
        authorization: { removedOrgA: 404, revokedAKey: 401, retainedOrgB: 200 },
        recovery: this.membershipRecovery || "not-observed",
        screenshot: this.screenshots["removed-analyst-browser-falls-back-to-b"],
      },
      "ROLE-04": {
        url: this.identities.viewer?.page.url() || `${appUrl}/cost-decisions/${this.resources.A.cost_id}`,
        visible: ["Known foreign direct URL rendered the same not-found boundary as an unknown ID."],
        persisted: this.crossTenantPersisted || "not-observed",
        numeric: {
          foreignProbeRows: this.rows.filter((row) => row.pathId === "ROLE-04" && /foreign|guess/i.test(row.operation)).length,
          markerLeaks: this.crossTenantPersisted?.markerLeaks,
        },
        authorization: { sameOrg: 200, foreignOrg: 404, unknownId: 404 },
        recovery: "Switching to organization B exposed B rows while retaining opaque denials for A identifiers.",
        screenshot: this.screenshots["foreign-cost-direct-url-opaque"],
      },
      "VER-04": {
        url: `${appUrl}/notifications`,
        visible: ["Organization B notification visible; organization A read row absent after refresh."],
        persisted: this.notificationPersisted || "not-observed",
        numeric: { unreadAfterRefresh: this.notificationPersisted?.unreadAfter },
        authorization: { orgBVisible: true, foreignAStatus: this.notificationRecovery?.foreignStatus },
        recovery: this.notificationRecovery || "not-observed",
        screenshot: this.screenshots["notification-org-b-scoped"],
      },
      "FAIL-09": {
        url: this.identities.viewer?.page.url() || `${appUrl}/designs`,
        visible: ["Revoked session redirected to login; fresh login reopened organization B."],
        persisted: this.sessionRevocationPersisted || "not-observed",
        numeric: { staleStatus: this.staleSessionObserved?.status, freshBVisible: this.sessionRecovery?.BVisible },
        authorization: { staleCookie: 401, denialCode: this.staleSessionObserved?.code, freshCookie: 200 },
        recovery: this.sessionRecovery || "not-observed",
        screenshot: this.screenshots["viewer-relogin-recovers-org-b"],
      },
    };
    const goldenPaths = {};
    for (const [id, meta] of Object.entries(PATH_META)) {
      const assertions = this.assertions.filter((item) => item.pathId === id);
      goldenPaths[id] = makeGoldenPathEvidence({
        id,
        status: assertions.length > 0 && assertions.every((item) => item.pass) ? "PASS" : "FAIL",
        persona: meta.persona,
        preconditions: meta.preconditions,
        actions: meta.actions,
        observed: {
          url: observations[id].url,
          visible: observations[id].visible,
          persisted: observations[id].persisted,
          numeric: observations[id].numeric,
          authorization: observations[id].authorization,
          recovery: observations[id].recovery,
        },
        screenshot: observations[id].screenshot,
        consoleErrors: this.consoleErrors,
        requestFailures: this.requestFailures,
        assertions,
      });
    }
    return goldenPaths;
  }

  async finish() {
    const finishedAt = Date.now();
    const requiredIds = Object.keys(PATH_META);
    let goldenPaths = {};
    let validation = { total: requiredIds.length, valid: 0, problems: [{ field: "runner", actual: this.fatalError }] };
    try {
      goldenPaths = this.buildGoldenPaths();
      const actualIds = Object.keys(goldenPaths);
      if (!deepEqual([...actualIds].sort(), [...requiredIds].sort())) {
        throw new Error(`releaseEvidence.goldenPaths IDs differ: expected ${requiredIds.join(",")}, got ${actualIds.join(",")}`);
      }
      validation = validateGoldenPathMap(requiredIds, goldenPaths);
    } catch (error) {
      this.fatalError ||= error instanceof Error ? error.message : String(error);
    }
    const buildIdentity = captureBuildIdentity(repoRoot);
    const buildBinding = {
      startGitHead: this.buildIdentityAtStart?.gitHead ?? null,
      finalGitHead: buildIdentity.gitHead,
      sameHead: this.buildIdentityAtStart?.gitHead === buildIdentity.gitHead,
      cleanAtStart: this.buildIdentityAtStart?.gitDirty === false,
      cleanAtFinish: buildIdentity.gitDirty === false,
      exactGoldenIds: deepEqual(Object.keys(goldenPaths).sort(), [...requiredIds].sort()),
    };
    buildBinding.pass = buildBinding.sameHead && buildBinding.cleanAtStart && buildBinding.cleanAtFinish && buildBinding.exactGoldenIds;
    const passedRows = this.rows.filter((row) => row.status === "PASS").length;
    const failedRows = this.rows.filter((row) => row.status === "FAIL").length;
    const report = {
      schemaVersion: 1,
      runId,
      startedAt: new Date(this.startedAt).toISOString(),
      finishedAt: new Date(finishedAt).toISOString(),
      durationMs: finishedAt - this.startedAt,
      appUrl,
      apiUrl,
      status: !this.fatalError && failedRows === 0 && validation.valid === validation.total && this.consoleErrors.length === 0 && this.requestFailures.length === 0 && buildBinding.pass ? "PASS" : "FAIL",
      buildIdentity,
      buildBinding,
      summary: {
        rows: this.rows.length,
        passedRows,
        failedRows,
        assertions: this.assertions.length,
        passedAssertions: this.assertions.filter((item) => item.pass).length,
        organizations: this.seedData ? 2 : 0,
        personas: Object.keys(this.identities).length,
        consoleErrors: this.consoleErrors.length,
        requestFailures: this.requestFailures.length,
      },
      fatalError: this.fatalError,
      rows: this.rows,
      consoleErrors: this.consoleErrors,
      requestFailures: this.requestFailures,
      screenshots: this.screenshots,
      releaseEvidence: { schemaVersion: 1, goldenPaths, validation, buildBinding },
    };
    await mkdir(outputRoot, { recursive: true });
    await writeFile(artifacts.json, `${JSON.stringify(report, null, 2)}\n`);
    const lines = [
      `# Role and tenant boundary matrix — ${runId}`,
      "",
      `- Status: **${report.status}**`,
      `- Matrix rows: ${passedRows}/${this.rows.length} passed`,
      `- Assertions: ${report.summary.passedAssertions}/${report.summary.assertions} passed`,
      `- Golden paths: ${validation.valid}/${validation.total} valid`,
      `- Build binding: ${buildBinding.pass ? "clean current HEAD" : "NOT release-bound"}`,
      `- Browser console errors: ${this.consoleErrors.length}`,
      `- Browser request failures: ${this.requestFailures.length}`,
      `- JSON evidence: ${artifacts.json}`,
      "",
      "## Matrix",
      "",
      "| ID | Persona | Channel | Surface | Operation | Outcome |",
      "|---|---|---|---|---|---|",
      ...this.rows.map((row) => `| ${row.pathId} | ${row.persona} | ${row.channel} | ${row.surface} | ${row.operation} | ${row.status} |`),
    ];
    if (this.fatalError) lines.push("", "## Fatal error", "", this.fatalError);
    if (validation.problems?.length) {
      lines.push("", "## Evidence validation problems", "", ...validation.problems.map((problem) => `- ${problem.id || "runner"} ${problem.field}: expected ${JSON.stringify(problem.expected)}, got ${JSON.stringify(problem.actual)}`));
    }
    await writeFile(artifacts.md, `${lines.join("\n")}\n`);
    process.stdout.write(`${JSON.stringify({ status: report.status, summary: report.summary, validation, artifacts, fatalError: this.fatalError }, null, 2)}\n`);
    return report;
  }

  async close() {
    for (const context of this.contexts) await context.close().catch(() => {});
    await this.browser?.close().catch(() => {});
  }
}

const runner = new RoleTenantBoundaryMatrix();
let report;
try {
  await runner.start();
  await runner.prepare();
  await runner.runRoleCapabilityMatrix();
  await runner.runSameOrgAndCrossTenantMatrix();
  await runner.runBearerAndMembershipLifecycle();
  await runner.runStaleSessionLifecycle();
} catch (error) {
  runner.fatalError = error instanceof Error ? error.stack || error.message : String(error);
} finally {
  report = await runner.finish();
  await runner.close();
}

if (report.status !== "PASS") process.exitCode = 1;
