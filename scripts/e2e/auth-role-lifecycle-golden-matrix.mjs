import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
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
import { configuredClientIp } from "./run-scoped-client-ip.mjs";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const execFileAsync = promisify(execFile);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const backendRoot = path.join(repoRoot, "backend");
const appUrl = (process.env.APP_URL || "http://localhost:3000").replace(/\/+$/, "");
const apiUrl = (process.env.API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const databaseUrl =
  process.env.DATABASE_URL ||
  "postgresql://cadverify:localdev@127.0.0.1:5432/cadverify";
const runId =
  process.env.E2E_RUN_ID ||
  `auth-role-lifecycle-${new Date().toISOString().replace(/[-:]/g, "").slice(0, 15)}`;
const clientIp = configuredClientIp(runId, "auth-role-lifecycle");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = path.join(
  outputRoot,
  "screenshots",
  `auth-role-lifecycle-${runId}`,
);
const artifacts = {
  json: path.join(outputRoot, `auth-role-lifecycle-${runId}.json`),
  md: path.join(outputRoot, `qa-report-auth-role-lifecycle-${runId}.md`),
};
const cubePath = path.join(backendRoot, "tests", "assets", "cube.step");
const requiredIds = ["AUTH-07", "AUTH-08", "ROLE-01"];
const password = `ProofShape-AuthRole-${randomBytes(8).toString("hex")}-9`;
const initializedPassword = `ProofShape-Initialized-${randomBytes(8).toString("hex")}-7`;
const tag = `${Date.now().toString(36)}-${process.pid}-${randomBytes(3).toString("hex")}`;

const pathMeta = {
  "AUTH-07": {
    persona: "organization admin and three invited teammates",
    preconditions: [
      "A named organization has one authenticated admin.",
      "Three exact invited accounts exist without organization membership.",
    ],
    actions: [
      "Create three one-time invitation links in the Organization browser UI.",
      "Accept one link, force one fixture past expiry, and revoke one through the confirmation dialog.",
      "Reopen every durable invitation state and retry every unusable link in an invited browser.",
    ],
  },
  "AUTH-08": {
    persona: "verified email-link user with two pre-existing dashboard sessions",
    preconditions: [
      "The account has no password hash and has two valid version-zero dashboard cookies.",
      "Password authentication is enabled in the production-mode local stack.",
    ],
    actions: [
      "Open Settings Security and submit the initial password twice for confirmation.",
      "Reuse both old cookies on protected API and browser routes.",
      "Log in again through the visible password form with the new credential.",
    ],
  },
  "ROLE-01": {
    persona: "organization viewer",
    preconditions: [
      "The viewer belongs only to organization A.",
      "Organizations A and B each contain a uniquely named durable cost decision.",
    ],
    actions: [
      "Open organization A evidence in the browser.",
      "Open Organization settings and inspect absent or gated admin controls.",
      "Attempt an invitation mutation and substitute organization B's known decision ID into a direct browser URL.",
      "Return to the authorized evidence after the denial.",
    ],
  },
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function cleanText(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function errorCode(body) {
  return body?.code ?? body?.detail?.code ?? null;
}

function appPath(rawLink) {
  const parsed = new URL(rawLink, `${appUrl}/`);
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

async function pythonExecutable() {
  return process.env.PYTHON?.trim() || path.join(backendRoot, ".venv", "bin", "python");
}

async function dashboardSessionSecret() {
  if (process.env.DASHBOARD_SESSION_SECRET?.trim()) {
    return process.env.DASHBOARD_SESSION_SECRET.trim();
  }
  const localAuthPath = path.join(repoRoot, ".env.local-auth");
  const text = await readFile(localAuthPath, "utf8").catch(() => "");
  const match = text.match(/^DASHBOARD_SESSION_SECRET=(?:'([^']+)'|"([^"]+)"|([^\s]+))$/m);
  const value = match?.[1] || match?.[2] || match?.[3] || "";
  if (!value) {
    throw new Error(
      "DASHBOARD_SESSION_SECRET is required to mint the two verified-session fixtures; export it or provide .env.local-auth",
    );
  }
  return value;
}

class AuthRoleLifecycleMatrix {
  constructor() {
    this.assertions = [];
    this.steps = [];
    this.goldenPaths = {};
    this.failures = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.expectedBrowserDenials = [];
    this.expectedNavigationAborts = [];
    this.contexts = [];
    this.screenshots = {};
    this.identities = {};
    this.resources = {};
    this.startedAt = Date.now();
  }

  record(pathId, name, expected, actual, pass) {
    const item = { pathId, name, expected, actual, pass: Boolean(pass) };
    this.assertions.push(item);
    if (!item.pass) {
      throw new Error(
        `${name}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
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

  excludes(pathId, name, value, forbidden) {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    const hits = forbidden.filter((needle) => needle && text.includes(String(needle)));
    return this.record(pathId, name, "no foreign metadata", hits, hits.length === 0);
  }

  watch(page, persona) {
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const text = message.text();
      if (/Failed to load resource: the server responded with a status of (401|403|404|409)/i.test(text)) {
        this.expectedBrowserDenials.push({ persona, url: page.url(), text });
        return;
      }
      if (/favicon\.ico|ResizeObserver loop limit exceeded/i.test(text)) return;
      this.consoleErrors.push({ persona, url: page.url(), text });
    });
    page.on("pageerror", (error) => {
      this.consoleErrors.push({ persona, url: page.url(), text: error.message });
    });
    page.on("requestfailed", (request) => {
      const error = request.failure()?.errorText || "request failed";
      const url = request.url();
      // Chromium cancels still-running idempotent fetches when a human leaves a
      // data-heavy page. That is an expected navigation outcome, not an API or
      // network failure. Keep it in the report instead of hiding it, while all
      // mutation aborts and non-ERR_ABORTED failures remain release blockers.
      if (
        error === "net::ERR_ABORTED" &&
        ["GET", "HEAD"].includes(request.method())
      ) {
        this.expectedNavigationAborts.push({
          persona,
          url,
          method: request.method(),
          error,
        });
        return;
      }
      if (
        error === "net::ERR_ABORTED" &&
        (/[?&]_rsc=/.test(url) || /\/_next\/static\//.test(url) || /\/icon\.svg(?:\?|$)/.test(url))
      ) return;
      if (
        error === "net::ERR_ABORTED" &&
        request.method() === "POST" &&
        new URL(url).pathname === "/settings/organization"
      ) return;
      if (/favicon\.ico|vercel\/speed-insights|\/_next\/webpack-hmr/i.test(url)) return;
      this.requestFailures.push({ persona, url, method: request.method(), error });
    });
  }

  async newContext(persona, sessionToken = null) {
    const context = await this.browser.newContext({
      baseURL: appUrl,
      extraHTTPHeaders: { "x-real-ip": clientIp },
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
      acceptDownloads: true,
    });
    this.contexts.push(context);
    if (sessionToken) {
      const sessionOrigin = new URL(appUrl);
      await context.addCookies([{
        name: "dash_session",
        value: sessionToken,
        domain: sessionOrigin.hostname,
        path: "/",
        httpOnly: true,
        secure: true,
        sameSite: "Lax",
      }]);
    }
    const page = await context.newPage();
    this.watch(page, persona);
    return { persona, context, page };
  }

  async ensureBrowserOrigin(actor) {
    let origin = null;
    try {
      origin = new URL(actor.page.url()).origin;
    } catch {
      // about:blank has no usable same-origin cookie boundary.
    }
    if (origin === new URL(appUrl).origin) return;
    const response = await actor.page.goto("/status", {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    assert(response?.status() === 200, `${actor.persona} browser origin returned ${response?.status()}`);
  }

  async browserJson(actor, pathname, options = {}) {
    await this.ensureBrowserOrigin(actor);
    const targetUrl = new URL(pathname, appUrl);
    assert(
      targetUrl.origin === new URL(appUrl).origin,
      `${actor.persona} browser request escaped the app origin`,
    );
    assert(
      targetUrl.pathname.startsWith("/api/auth/") ||
        targetUrl.pathname.startsWith("/api/proxy/"),
      `${actor.persona} browser request bypassed an authenticated app boundary`,
    );
    const target = `${targetUrl.pathname}${targetUrl.search}`;
    return actor.page.evaluate(async ({ target, options }) => {
      const response = await fetch(target, {
        ...options,
        cache: "no-store",
        credentials: "same-origin",
      });
      const text = await response.text();
      let body = null;
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
      return {
        status: response.status,
        body,
        text,
        headers: Object.fromEntries(response.headers.entries()),
      };
    }, { target, options });
  }

  async browserNavigationJson(actor, pathname) {
    const response = await actor.page.goto(pathname, {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    assert(response, `${actor.persona} browser navigation returned no response`);
    const text = await response.text();
    let body = null;
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
    return { status: response.status(), body, text, headers: response.headers() };
  }

  async shot(key, actor, fullPage = false) {
    const index = Object.keys(this.screenshots).length + 1;
    const filename = path.join(
      screenshotDir,
      `${String(index).padStart(2, "0")}-${key}.png`,
    );
    await actor.page.screenshot({
      path: filename,
      fullPage,
      animations: "disabled",
      caret: "initial",
    });
    this.screenshots[key] = filename;
    return filename;
  }

  async start() {
    this.buildIdentityAtStart = captureBuildIdentity(repoRoot);
    await mkdir(screenshotDir, { recursive: true });
    this.browser = await chromium
      .launch({ channel: "chrome", headless: true })
      .catch(() => chromium.launch({ headless: true }));
    this.cubeBytes = await readFile(cubePath);
  }

  async seed() {
    const script = String.raw`
import asyncio, json, sys
from sqlalchemy import text
from ulid import ULID
from src.auth.dashboard_session import sign
from src.auth.hashing import hash_password
import src.db.engine as eng

tag, password = sys.argv[1], sys.argv[2]

async def main():
    orgs = {key: str(ULID()) for key in ("A", "B", "C")}
    people = {
        "owner": {"platform": "analyst", "provider": "password", "password": True, "org": "A", "org_role": "admin"},
        "viewer": {"platform": "viewer", "provider": "password", "password": True, "org": "A", "org_role": "viewer"},
        "b_owner": {"platform": "analyst", "provider": "password", "password": True, "org": "B", "org_role": "admin"},
        "accepted": {"platform": "viewer", "provider": "password", "password": True, "org": None, "org_role": None},
        "expired": {"platform": "viewer", "provider": "password", "password": True, "org": None, "org_role": None},
        "revoked": {"platform": "viewer", "provider": "password", "password": True, "org": None, "org_role": None},
        "magic": {"platform": "analyst", "provider": "magic_link", "password": False, "org": "C", "org_role": "admin"},
    }
    out = {"tag": tag, "orgs": {}, "people": {}}
    async with eng.get_session_factory()() as s:
        for key, oid in orgs.items():
            name = f"QA Auth Role Org {key} {tag}"
            await s.execute(text("INSERT INTO organizations (id,name,slug,created_at) VALUES (:i,:n,:slug,now())"), {
                "i": oid, "n": name, "slug": f"qa-auth-role-{key.lower()}-{tag}"})
            out["orgs"][key] = {"id": oid, "name": name}
        for key, spec in people.items():
            email = f"qa-auth-role-{tag}-{key}@example.com"
            current_org = orgs[spec["org"]] if spec["org"] else None
            password_hash = hash_password(password) if spec["password"] else None
            row = (await s.execute(text("INSERT INTO users (email,email_lower,role,auth_provider,password_hash,current_org_id,is_active,session_version) VALUES (:e,:e,:r,:provider,:p,:o,true,0) RETURNING id"), {
                "e": email, "r": spec["platform"], "provider": spec["provider"], "p": password_hash, "o": current_org})).first()
            uid = int(row[0])
            if current_org:
                await s.execute(text("INSERT INTO memberships (id,org_id,user_id,org_role,created_at) VALUES (:id,:o,:u,:r,now())"), {
                    "id": str(ULID()), "o": current_org, "u": uid, "r": spec["org_role"]})
            out["people"][key] = {"id": uid, "email": email, "org_id": current_org, "org_role": spec["org_role"]}
        await s.commit()
    magic = out["people"]["magic"]
    magic["session"] = sign(magic["id"], session_version=0)
    print(json.dumps(out))
    await eng.dispose_engine()

asyncio.run(main())
`;
    const python = await pythonExecutable();
    const secret = await dashboardSessionSecret();
    const { stdout, stderr } = await execFileAsync(
      python,
      ["-c", script, tag, password],
      {
        cwd: backendRoot,
        env: {
          ...process.env,
          DATABASE_URL: databaseUrl,
          DASHBOARD_SESSION_SECRET: secret,
          PYTHONPATH: backendRoot,
          PYTHONDONTWRITEBYTECODE: "1",
        },
        timeout: 60_000,
        maxBuffer: 1024 * 1024,
      },
    );
    if (stderr.trim()) this.seedStderr = stderr.trim().slice(0, 1000);
    this.seedData = JSON.parse(stdout);
  }

  async db(action, value = "") {
    const script = String.raw`
import asyncio, json, sys
from sqlalchemy import text
import src.db.engine as eng

action, value, tag = sys.argv[1], sys.argv[2], sys.argv[3]

async def main():
    async with eng.get_session_factory()() as s:
        if action == "expire":
            row = (await s.execute(text("UPDATE org_invites SET expires_at = now() - interval '1 minute' WHERE email = :e AND accepted_at IS NULL AND revoked_at IS NULL RETURNING id"), {"e": value})).first()
            await s.commit()
            print(json.dumps({"updated": 0 if row is None else 1, "invite_id": None if row is None else int(row[0])}))
            return
        emails = {kind: f"qa-auth-role-{tag}-{kind}@example.com" for kind in ("accepted", "expired", "revoked", "magic")}
        invite_rows = (await s.execute(text("SELECT email, role, accepted_at, revoked_at, expires_at FROM org_invites WHERE email IN (:accepted,:expired,:revoked) ORDER BY id"), emails)).all()
        invites = {}
        for email, role, accepted_at, revoked_at, expires_at in invite_rows:
            kind = next(key for key in ("accepted", "expired", "revoked") if emails[key] == email)
            status = "accepted" if accepted_at else "revoked" if revoked_at else "expired" if expires_at and expires_at.timestamp() < __import__('time').time() else "pending"
            invites[kind] = {"role": role, "status": status}
        memberships = {}
        for kind in ("accepted", "expired", "revoked"):
            row = (await s.execute(text("SELECT count(*), coalesce(max(m.org_role),'') FROM memberships m JOIN users u ON u.id=m.user_id WHERE u.email_lower=:e"), {"e": emails[kind]})).first()
            memberships[kind] = {"count": int(row[0]), "role": row[1]}
        magic = (await s.execute(text("SELECT id, password_hash IS NOT NULL, password_hash LIKE '$argon2id$%%', session_version, current_org_id FROM users WHERE email_lower=:e"), {"e": emails["magic"]})).first()
        audit_count = int((await s.execute(text("SELECT count(*) FROM audit_log WHERE user_id=:u AND action='auth.password_initialized'"), {"u": int(magic[0])})).scalar_one())
        print(json.dumps({
            "invites": invites,
            "memberships": memberships,
            "magic": {"password_configured": bool(magic[1]), "argon2id": bool(magic[2]), "session_version": int(magic[3]), "current_org_id": magic[4], "audit_rows": audit_count},
        }))

asyncio.run(main())
`;
    const python = await pythonExecutable();
    const { stdout } = await execFileAsync(python, ["-c", script, action, value, tag], {
      cwd: backendRoot,
      env: {
        ...process.env,
        DATABASE_URL: databaseUrl,
        PYTHONPATH: backendRoot,
        PYTHONDONTWRITEBYTECODE: "1",
      },
      timeout: 30_000,
      maxBuffer: 1024 * 1024,
    });
    return JSON.parse(stdout);
  }

  async login(key, { ui = true } = {}) {
    const person = this.seedData.people[key];
    const actor = await this.newContext(key);
    if (ui) {
      await actor.page.goto("/login", { waitUntil: "domcontentloaded", timeout: 30_000 });
      await actor.page.getByLabel("Email").fill(person.email);
      await actor.page.getByLabel("Password").fill(password);
      const responsePromise = actor.page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === "/api/auth/login",
        { timeout: 45_000 },
      );
      await actor.page.getByRole("button", { name: /^Log in$/i }).click();
      const response = await responsePromise;
      assert(response.status() === 200, `${key} login returned ${response.status()}`);
      await actor.page.waitForURL((url) => url.pathname !== "/login", { timeout: 20_000 });
    } else {
      const response = await this.browserJson(actor, "/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: person.email, password }),
      });
      assert(response.status === 200, `${key} setup login returned ${response.status}`);
    }
    const cookie = (await actor.context.cookies()).find((item) => item.name === "dash_session");
    assert(cookie?.value, `${key} login did not set dash_session`);
    Object.assign(actor, person, { key, cookie: cookie.value });
    this.identities[key] = actor;
    return actor;
  }

  async loginFromInvite(key, inviteLink) {
    const person = this.seedData.people[key];
    const actor = await this.newContext(`${key}-invitee`);
    await actor.page.goto(appPath(inviteLink), { waitUntil: "domcontentloaded", timeout: 30_000 });
    await actor.page.getByText("Log in as the invited account.", { exact: true }).waitFor();
    await actor.page.getByRole("link", { name: "Log in to accept" }).click();
    await actor.page.waitForURL((url) => url.pathname === "/login", { timeout: 10_000 });
    await actor.page.getByLabel("Email").fill(person.email);
    await actor.page.getByLabel("Password").fill(password);
    const loginResponse = actor.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/auth/login",
      { timeout: 45_000 },
    );
    await actor.page.getByRole("button", { name: /^Log in$/i }).click();
    assert((await loginResponse).status() === 200, `${key} invite login failed`);
    await actor.page.waitForURL((url) => url.pathname === "/orgs/accept", { timeout: 20_000 });
    Object.assign(actor, person, { key });
    this.identities[key] = actor;
    return actor;
  }

  async createInvite(owner, email) {
    await owner.page.locator("#invite-email").fill(email);
    await owner.page.getByRole("button", { name: "Send invite" }).click();
    const shown = owner.page.getByText(/One-time accept link \(shown once\):/i);
    await shown.waitFor({ timeout: 20_000 });
    const link = cleanText(await shown.locator("xpath=..").locator("code").innerText());
    assert(link.includes("token="), `invite link for ${email} did not include a token`);
    const row = owner.page.getByRole("row").filter({ hasText: email });
    await row.waitFor({ timeout: 15_000 });
    return link;
  }

  async runAuth07() {
    const id = "AUTH-07";
    const owner = await this.login("owner");
    await owner.page.goto("/settings/organization", {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    await owner.page.getByText(/Manage members, invites, and SSO for/i).waitFor();

    const acceptedLink = await this.createInvite(owner, this.seedData.people.accepted.email);
    const accepted = await this.loginFromInvite("accepted", acceptedLink);
    await accepted.page.getByText("Invitation accepted.", { exact: true }).waitFor({ timeout: 20_000 });
    await accepted.page.getByText("You joined the organization as member.", { exact: true }).waitFor();
    this.equal(id, "accepted invite visible role", cleanText(await accepted.page.locator("body").innerText()).includes("as member"), true);
    const acceptedOrgs = await this.browserJson(accepted, "/api/proxy/orgs");
    this.equal(id, "accepted account organization status", acceptedOrgs.status, 200);
    this.equal(id, "accepted account active organization", acceptedOrgs.body?.active_org_id, this.seedData.orgs.A.id);

    const expiredLink = await this.createInvite(owner, this.seedData.people.expired.email);
    const expiredMutation = await this.db("expire", this.seedData.people.expired.email);
    this.equal(id, "expired fixture row updated", expiredMutation.updated, 1);
    await owner.page.reload({ waitUntil: "domcontentloaded" });
    const expiredRow = owner.page.getByRole("row").filter({ hasText: this.seedData.people.expired.email });
    await expiredRow.getByText("expired", { exact: true }).waitFor({ timeout: 15_000 });
    const expired = await this.loginFromInvite("expired", expiredLink);
    await expired.page.getByText("Invite not accepted.", { exact: true }).waitFor({ timeout: 20_000 });
    await expired.page.getByText("This invite has expired.", { exact: true }).waitFor();

    const revokedLink = await this.createInvite(owner, this.seedData.people.revoked.email);
    let revokedRow = owner.page.getByRole("row").filter({ hasText: this.seedData.people.revoked.email });
    await revokedRow.getByRole("button", { name: "Revoke", exact: true }).click();
    const dialog = owner.page.getByRole("alertdialog");
    await dialog.getByRole("button", { name: "Revoke invite" }).click();
    await owner.page.waitForTimeout(500);
    revokedRow = owner.page.getByRole("row").filter({ hasText: this.seedData.people.revoked.email });
    await revokedRow.getByText("revoked", { exact: true }).waitFor({ timeout: 15_000 });
    const revoked = await this.loginFromInvite("revoked", revokedLink);
    await revoked.page.getByText("Invite not accepted.", { exact: true }).waitFor({ timeout: 20_000 });
    await revoked.page.getByText("This invite has been revoked.", { exact: true }).waitFor();

    await accepted.page.goto(appPath(acceptedLink), { waitUntil: "domcontentloaded" });
    await accepted.page.getByText("Invite not accepted.", { exact: true }).waitFor({ timeout: 20_000 });
    await accepted.page.getByText("This invite has already been used.", { exact: true }).waitFor();

    const state = await this.db("snapshot");
    this.equal(id, "accepted invite durable status", state.invites.accepted?.status, "accepted");
    this.equal(id, "expired invite durable status", state.invites.expired?.status, "expired");
    this.equal(id, "revoked invite durable status", state.invites.revoked?.status, "revoked");
    this.equal(id, "accepted membership count", state.memberships.accepted.count, 1);
    this.equal(id, "accepted membership role", state.memberships.accepted.role, "member");
    this.equal(id, "expired membership count", state.memberships.expired.count, 0);
    this.equal(id, "revoked membership count", state.memberships.revoked.count, 0);

    await owner.page.reload({ waitUntil: "domcontentloaded" });
    for (const [kind, expected] of [["accepted", "accepted"], ["expired", "expired"], ["revoked", "revoked"]]) {
      const row = owner.page.getByRole("row").filter({ hasText: this.seedData.people[kind].email });
      await row.getByText(expected, { exact: true }).waitFor({ timeout: 15_000 });
    }
    const screenshot = await this.shot("auth-07-invitation-states", owner, true);
    return {
      persona: pathMeta[id].persona,
      preconditions: pathMeta[id].preconditions,
      actions: pathMeta[id].actions,
      observed: {
        url: owner.page.url(),
        visible: [
          "Invitation accepted. You joined the organization as member.",
          "The admin invitation table visibly retained accepted, expired, and revoked states after reload.",
          "Expired, revoked, and reused links each rendered Invite not accepted with the exact bounded reason.",
        ],
        persisted: state,
        numeric: {
          invitations: Object.keys(state.invites).length,
          acceptedMemberships: state.memberships.accepted.count,
          invalidMemberships: state.memberships.expired.count + state.memberships.revoked.count,
        },
        authorization: {
          acceptedOrgId: acceptedOrgs.body?.active_org_id,
          acceptedRole: state.memberships.accepted.role,
          expiredMutation: "denied without membership",
          revokedMutation: "denied without membership",
        },
        recovery: "Reopening the accepted link returned already used while preserving exactly one membership; the admin reload retained all three terminal states.",
      },
      screenshot,
    };
  }

  async runAuth08() {
    const id = "AUTH-08";
    const person = this.seedData.people.magic;
    const primary = await this.newContext("magic-primary", person.session);
    const stale = await this.newContext("magic-stale", person.session);
    this.identities.magicPrimary = primary;
    this.identities.magicStale = stale;

    const beforePrimary = await this.browserJson(primary, "/api/proxy/orgs");
    const beforeStale = await this.browserJson(stale, "/api/proxy/orgs");
    this.equal(id, "primary old session starts authorized", beforePrimary.status, 200);
    this.equal(id, "second old session starts authorized", beforeStale.status, 200);

    await primary.page.goto("/settings/security", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await primary.page.getByRole("heading", { name: "Initial password" }).waitFor();
    await primary.page.getByLabel("New password").fill(initializedPassword);
    await primary.page.getByLabel("Confirm password").fill(initializedPassword);
    const responsePromise = primary.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/auth/password/initialize",
      { timeout: 45_000 },
    );
    await primary.page.getByRole("button", { name: "Set password" }).click();
    const initialized = await responsePromise;
    this.equal(id, "initial password response status", initialized.status(), 200);
    await primary.page.getByText("Password configured. Older dashboard sessions were revoked.", { exact: true }).waitFor({ timeout: 15_000 });
    const screenshot = await this.shot("auth-08-password-sessions-revoked", primary);

    const primaryAfter = await this.browserJson(primary, "/api/proxy/orgs");
    this.equal(id, "rotated caller session remains authorized", primaryAfter.status, 200);
    const staleApi = await this.browserJson(stale, "/api/proxy/orgs");
    this.equal(id, "old second session status", staleApi.status, 401);
    this.equal(id, "old second session denial code", errorCode(staleApi.body), "session_revoked");
    const rawOld = await this.browserNavigationJson(stale, `${apiUrl}/auth/me`);
    this.equal(id, "raw old cookie status", rawOld.status, 401);
    this.equal(id, "raw old cookie denial code", errorCode(rawOld.body), "session_revoked");

    await stale.page.goto("/verify", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await stale.page.waitForURL((url) => url.pathname === "/login", { timeout: 15_000 });
    await stale.page.getByText("Log in to ProofShape", { exact: true }).waitFor();

    const durable = await this.db("snapshot");
    this.equal(id, "password configured durably", durable.magic.password_configured, true);
    this.equal(id, "password hash scheme", durable.magic.argon2id, true);
    this.equal(id, "session version increment", durable.magic.session_version, 1);
    this.equal(id, "password initialization audit rows", durable.magic.audit_rows, 1);

    const recovered = await this.newContext("magic-password-recovery");
    await recovered.page.goto("/login?next=/settings/security", { waitUntil: "domcontentloaded" });
    await recovered.page.getByLabel("Email").fill(person.email);
    await recovered.page.getByLabel("Password").fill(initializedPassword);
    const loginPromise = recovered.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/auth/login",
      { timeout: 45_000 },
    );
    await recovered.page.getByRole("button", { name: /^Log in$/i }).click();
    this.equal(id, "new password login status", (await loginPromise).status(), 200);
    await recovered.page.waitForURL((url) => url.pathname === "/settings/security", { timeout: 20_000 });
    const recoveredApi = await this.browserJson(recovered, "/api/proxy/orgs");
    this.equal(id, "fresh password session authorized", recoveredApi.status, 200);

    return {
      persona: pathMeta[id].persona,
      preconditions: pathMeta[id].preconditions,
      actions: pathMeta[id].actions,
      observed: {
        url: primary.page.url(),
        visible: [
          "Password configured. Older dashboard sessions were revoked.",
          "The stale browser returned to Log in to ProofShape on its next protected navigation.",
        ],
        persisted: durable.magic,
        numeric: {
          sessionVersionBefore: 0,
          sessionVersionAfter: durable.magic.session_version,
          passwordInitializationAuditRows: durable.magic.audit_rows,
        },
        authorization: {
          rotatedCaller: primaryAfter.status,
          staleCookie: staleApi.status,
          staleCode: errorCode(staleApi.body),
          freshPasswordLogin: recoveredApi.status,
        },
        recovery: "A fresh visible password login reached Settings Security and organization APIs after both version-zero cookies were rejected.",
      },
      screenshot,
    };
  }

  async browserCost(actor, filename) {
    await this.ensureBrowserOrigin(actor);
    const pathname = "/api/proxy/validate/cost";
    const base64 = this.cubeBytes.toString("base64");
    return actor.page.evaluate(async ({ pathname, filename, base64 }) => {
      const bytes = Uint8Array.from(atob(base64), (character) => character.charCodeAt(0));
      const form = new FormData();
      form.append("file", new Blob([bytes], { type: "application/step" }), filename);
      form.append("qty", "1,100");
      form.append("material_class", "polymer");
      const response = await fetch(pathname, {
        method: "POST",
        body: form,
        cache: "no-store",
        credentials: "same-origin",
        signal: AbortSignal.timeout(120_000),
      });
      const text = await response.text();
      let body = null;
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
      return {
        status: response.status,
        body,
        text,
        headers: Object.fromEntries(response.headers.entries()),
      };
    }, { pathname, filename, base64 });
  }

  async createCost(actor, orgKey) {
    const filename = `ROLE-01-${orgKey}-${tag}.step`;
    const result = await this.browserCost(actor, filename);
    assert(result.status === 200, `${orgKey} cost fixture returned ${result.status}: ${result.text.slice(0, 500)}`);
    assert(result.body?.saved?.id, `${orgKey} cost fixture did not persist an ID`);
    return { id: result.body.saved.id, filename };
  }

  async runRole01() {
    const id = "ROLE-01";
    const owner = this.identities.owner || (await this.login("owner"));
    const bOwner = await this.login("b_owner", { ui: false });
    const allowed = await this.createCost(owner, "A-ALLOWED");
    const foreign = await this.createCost(bOwner, "B-FOREIGN");
    this.resources.role01 = { allowed, foreign };

    const viewer = await this.login("viewer");
    const allowedResponse = viewer.page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname === `/api/proxy/cost-decisions/${allowed.id}`,
      { timeout: 30_000 },
    );
    await viewer.page.goto(`/cost-decisions/${allowed.id}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
    this.equal(id, "same-organization evidence status", (await allowedResponse).status(), 200);
    await viewer.page.getByText(allowed.filename, { exact: true }).first().waitFor({ timeout: 20_000 });
    const permittedScreenshot = await this.shot("role-01-viewer-permitted-evidence", viewer, true);

    await viewer.page.goto("/settings/organization", { waitUntil: "domcontentloaded", timeout: 30_000 });
    await viewer.page.getByText("Admins only", { exact: true }).waitFor();
    const gateText = cleanText(await viewer.page.locator("body").innerText());
    const sendInviteButtons = await viewer.page.getByRole("button", { name: "Send invite" }).count();
    const inviteInputs = await viewer.page.locator("#invite-email").count();
    this.equal(id, "viewer organization gate names role", gateText.includes("You're a viewer"), true);
    this.equal(id, "send invite controls absent", sendInviteButtons, 0);
    this.equal(id, "invite email controls absent", inviteInputs, 0);
    const gatedScreenshot = await this.shot("role-01-viewer-admin-gate", viewer, true);

    const mutation = await this.browserJson(viewer, "/api/proxy/orgs/invites", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: `role-01-denied-${tag}@example.com`, role: "viewer" }),
    });
    this.equal(id, "viewer admin mutation status", mutation.status, 403);
    this.equal(id, "viewer admin mutation code", errorCode(mutation.body), "insufficient_org_role");

    const foreignResponse = viewer.page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname === `/api/proxy/cost-decisions/${foreign.id}`,
      { timeout: 30_000 },
    );
    await viewer.page.goto(`/cost-decisions/${foreign.id}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
    this.equal(id, "known cross-tenant evidence status", (await foreignResponse).status(), 404);
    await viewer.page.getByText("Cost decision not found", { exact: true }).waitFor({ timeout: 20_000 });
    const foreignText = cleanText(await viewer.page.locator("body").innerText());
    this.excludes(id, "foreign cost metadata absent", foreignText, [foreign.filename, tag + "-B-FOREIGN"]);
    const foreignScreenshot = await this.shot("role-01-cross-tenant-not-found", viewer, true);

    const recoveryResponse = viewer.page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname === `/api/proxy/cost-decisions/${allowed.id}`,
      { timeout: 30_000 },
    );
    await viewer.page.goto(`/cost-decisions/${allowed.id}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
    this.equal(id, "viewer recovers same-org evidence", (await recoveryResponse).status(), 200);
    await viewer.page.getByText(allowed.filename, { exact: true }).first().waitFor({ timeout: 20_000 });

    return {
      persona: pathMeta[id].persona,
      preconditions: pathMeta[id].preconditions,
      actions: pathMeta[id].actions,
      observed: {
        url: viewer.page.url(),
        visible: [
          `Viewer opened permitted evidence ${allowed.filename}.`,
          "Organization settings visibly rendered Admins only and named the viewer role without invite controls.",
          "The known foreign decision rendered Cost decision not found without foreign metadata.",
        ],
        persisted: {
          allowedDecisionId: allowed.id,
          foreignDecisionId: foreign.id,
          screenshots: { permittedScreenshot, gatedScreenshot, foreignScreenshot },
        },
        numeric: {
          sameOrgStatus: 200,
          adminMutationStatus: mutation.status,
          crossTenantStatus: 404,
          visibleAdminControls: sendInviteButtons + inviteInputs,
        },
        authorization: {
          orgRole: "viewer",
          permittedRead: 200,
          adminMutation: 403,
          adminMutationCode: errorCode(mutation.body),
          crossTenantRead: 404,
          metadataLeaks: 0,
        },
        recovery: "After the 403 mutation and opaque 404, the same viewer session reopened the authorized organization A decision with HTTP 200.",
      },
      screenshot: gatedScreenshot,
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
      assert(assertions.length > 0, `${id} emitted no field-level assertions`);
      const consoleErrors = this.consoleErrors.slice(consoleOffset);
      const requestFailures = this.requestFailures.slice(requestOffset);
      assert(consoleErrors.length === 0, `${id} produced console errors: ${JSON.stringify(consoleErrors)}`);
      assert(requestFailures.length === 0, `${id} produced request failures: ${JSON.stringify(requestFailures)}`);
      this.goldenPaths[id] = makeGoldenPathEvidence({
        id,
        status: "PASS",
        ...input,
        consoleErrors,
        requestFailures,
        assertions,
      });
      this.steps.push({ id, status: "PASS", durationMs: Date.now() - started });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.failures.push({ id, error: message });
      this.steps.push({ id, status: "FAIL", durationMs: Date.now() - started, error: message });
      this.goldenPaths[id] = makeGoldenPathEvidence({
        id,
        status: "FAIL",
        persona: pathMeta[id].persona,
        preconditions: pathMeta[id].preconditions,
        actions: pathMeta[id].actions,
        observed: {
          url: appUrl,
          visible: [`Path failed before complete evidence: ${message}`],
          persisted: "not-observed",
          numeric: "not-observed",
          authorization: "not-observed",
          recovery: "not-observed",
        },
        screenshot: this.screenshots[Object.keys(this.screenshots).at(-1)] || "",
        consoleErrors: this.consoleErrors.slice(consoleOffset),
        requestFailures: this.requestFailures.slice(requestOffset),
        assertions: this.assertions.slice(assertionOffset),
      });
    }
  }

  markdown(data) {
    const rows = requiredIds.map((id) => {
      const result = data.releaseEvidence.validation.byId[id];
      return `| ${result.valid ? "PASS" : "FAIL"} | ${id} | ${result.failures.map((item) => item.field).join(", ") || "none"} | ${data.releaseEvidence.goldenPaths[id]?.screenshot || ""} |`;
    }).join("\n");
    return `# Authentication and viewer-role lifecycle golden matrix

- Run: ${runId}
- Status: ${data.status}
- Build: ${data.buildIdentity.gitHead}
- Structured paths: ${data.releaseEvidence.validation.valid}/${data.releaseEvidence.validation.total}
- Assertions: ${data.summary.passedAssertions}/${data.summary.assertions}
- Unexpected console errors: ${data.summary.consoleErrors}
- Unexpected request failures: ${data.summary.requestFailures}

| Result | Golden ID | Invalid fields | Screenshot |
| --- | --- | --- | --- |
${rows}

## Scope

- AUTH-07: real Organization UI invitation creation, browser acceptance, forced expiry fixture, UI revocation, durable reopen, and single-use retry.
- AUTH-08: browser initial-password form, atomic session-version rotation, stale-cookie API/browser rejection, and fresh password recovery.
- ROLE-01: same-org evidence read, visible viewer admin gate, exact 403 mutation, opaque known-foreign 404, and same-session recovery.
`;
  }

  async finish(fatalError = null) {
    for (const id of requiredIds) {
      if (!this.goldenPaths[id]) {
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
    }
    const validation = validateGoldenPathMap(requiredIds, this.goldenPaths);
    const buildIdentity = captureBuildIdentity(repoRoot);
    const exactGoldenIds = deepEqual(Object.keys(this.goldenPaths).sort(), [...requiredIds].sort());
    const buildBinding = {
      startGitHead: this.buildIdentityAtStart?.gitHead || null,
      finalGitHead: buildIdentity.gitHead,
      sameHead: this.buildIdentityAtStart?.gitHead === buildIdentity.gitHead,
      cleanAtStart: this.buildIdentityAtStart?.gitDirty === false,
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
      suite: "auth-role-lifecycle-golden-matrix",
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
        expectedBrowserDenials: this.expectedBrowserDenials.length,
        expectedNavigationAborts: this.expectedNavigationAborts.length,
      },
      steps: this.steps,
      failures: this.failures,
      fatalError,
      screenshots: this.screenshots,
      consoleErrors: this.consoleErrors,
      requestFailures: this.requestFailures,
      expectedBrowserDenials: this.expectedBrowserDenials,
      expectedNavigationAborts: this.expectedNavigationAborts,
      releaseEvidence: {
        schemaVersion: 1,
        goldenPaths: this.goldenPaths,
        validation,
      },
      artifacts,
    };
    await mkdir(outputRoot, { recursive: true });
    await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
    await writeFile(artifacts.md, this.markdown(data));
    console.log(JSON.stringify({
      status,
      summary: data.summary,
      validation,
      buildBinding,
      artifacts,
      fatalError,
    }, null, 2));
    return data;
  }

  async close() {
    await Promise.all(this.contexts.map((context) => context.close().catch(() => {})));
    await this.browser?.close().catch(() => {});
  }
}

const matrix = new AuthRoleLifecycleMatrix();
let fatalError = null;
try {
  await matrix.start();
  await matrix.seed();
  await matrix.path("AUTH-07", () => matrix.runAuth07());
  await matrix.path("AUTH-08", () => matrix.runAuth08());
  await matrix.path("ROLE-01", () => matrix.runRole01());
} catch (error) {
  fatalError = error instanceof Error ? error.stack || error.message : String(error);
}
const report = await matrix.finish(fatalError);
await matrix.close();
if (report.status !== "PASS") process.exitCode = 1;
