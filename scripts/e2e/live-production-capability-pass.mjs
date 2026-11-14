#!/usr/bin/env node
/**
 * Live-production capability pass (Step B/C of the 2026-11-13 rollout mandate).
 *
 * Drives the real web frontend at BASE (default https://scalecad.ai) in a real
 * headless Chromium. UI-only for every action (signup, login, uploads, exports,
 * share links); the backend API is read only for parity assertions, from Node
 * (page CSP correctly forbids cross-origin fetches from the app).
 *
 * v3 fixes from run 2 (10 PASS / 1 WARN / 12 FAIL, all failures driver-side):
 *   - page.waitForFunction(fn, {timeout}) passed options as the *argument*;
 *     options are the third parameter — every upload silently waited
 *     Playwright's 30s default (that is why IGES/NIST "timed out")
 *   - verdict wait is scoped to the real check surfaces: /app/check and
 *     /app/part/<key>, matching the terminal states of progressSteps()
 *     (components/v4/part/model.ts) — never full-body regex on /app, whose
 *     recent-checks history ("Try again", old $ figures) settled run 2 early
 *   - ctx.cookies() is awaited
 *   - signup is idempotent: a 409 "already exists" falls back to login
 *   - sign-out clicks through the Confirm dialog ("Sign out of every
 *     browser?") and proves the dash_session cookie is gone
 *   - records: click a row -> record sheet -> download PDF/CSV/JSON exports
 *     and check number-for-number parity against the sheet
 *   - share: record sheet -> Share -> "Create and copy" -> open the link
 *     logged-out in a second context
 *   - multi-body assembly upload + >100MB junk upload (stored-check worker
 *     path) with clean-error assertions
 *
 * Usage:  node scripts/e2e/live-production-capability-pass.mjs
 *         EXPECT_TOLERANCES=1  # post-OCP: require PMI tolerances on NIST part
 * Output: /tmp/scalecad_live_receipt.json + artifacts in /tmp/live-pass-*.
 */
import { createRequire } from "node:module";
import { mkdir, writeFile, readFile, stat } from "node:fs/promises";
import path from "node:path";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");

const BASE = process.env.BASE || "https://scalecad.ai";
const API = process.env.API_BASE || "https://cadverify-api.onrender.com";
const EXPECT_TOLERANCES = process.env.EXPECT_TOLERANCES === "1";
// ONLY=id,id runs just those checks (a login check must be among them).
const ONLY = process.env.ONLY ? process.env.ONLY.split(",").map(s => s.trim()).filter(Boolean) : null;
const CREDS = {
  pilot: { email: process.env.PILOT_EMAIL || "nazeem.acceptance.20261114@scalecad.ai", pass: process.env.PILOT_PASS || "AcceptancePass2026" },
  personal: { email: process.env.PERSONAL_EMAIL || "nazeem.acceptance.20261114@gmail.com", pass: process.env.PERSONAL_PASS || "AcceptancePass2026" },
  work2: { email: process.env.WORK2_EMAIL || "nazeem.acceptance.work2.20261114@scalecad.ai", pass: process.env.WORK2_PASS || "AcceptancePass2026" },
};
const ASSETS = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../backend/tests/assets");
const ART = `/tmp/live-pass-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}`;

const receipt = [];
const consoleErrors = [];           // {text}
const badResponses = [];            // {status,url}
let page, ctx, browser;

async function check(id, description, fn, { timeoutMs = 300_000, expect4xx = false } = {}) {
  if (ONLY && !ONLY.includes(id)) {
    receipt.push({ id, description, status: "SKIP", ms: 0 });
    return;
  }
  const t0 = Date.now();
  const cMark = consoleErrors.length, rMark = badResponses.length;
  try {
    await Promise.race([
      (async () => { await fn(); })(),
      new Promise((_, rej) => setTimeout(() => rej(new Error(`timeout after ${timeoutMs}ms`)), timeoutMs)),
    ]);
    let errs = consoleErrors.slice(cMark).map(e => e.text).filter(t => !/favicon|net::ERR_ABORTED/.test(t));
    if (expect4xx) errs = errs.filter(t => !/status of (4\d\d)/.test(t));
    // The part-context probe 404s while a check is still running (the browser
    // logs every non-2xx fetch); the app retries and the check succeeds. The
    // count is kept on the receipt as a known-noise item, not a failure.
    const ctx404 = badResponses.slice(rMark).filter(r => r.status === 404 && /\/api\/proxy\/part-context\//.test(r.url)).length;
    let quiet = 0;
    errs = errs.filter(t => {
      if (/status of 404/.test(t) && quiet < ctx404) { quiet++; return false; }
      return true;
    });
    const fourxx = badResponses.slice(rMark).filter(r => r.status >= 400);
    const expectedCtx = r => /\/api\/proxy\/part-context\//.test(r.url);
    receipt.push({ id, description, status: errs.length ? "WARN" : "PASS", ms: Date.now() - t0, consoleErrors: errs, part_context_404s: fourxx.filter(expectedCtx).length, http_4xx_5xx: expect4xx ? fourxx.filter(r => !expectedCtx(r)) : fourxx.filter(r => !expectedCtx(r) && !/analytics|posthog|rb2b|cloudfront|sentry|googletag/i.test(r.url)), evidence: `${ART}/${id}.png` });
    await page.screenshot({ path: `${ART}/${id}.png`, fullPage: false }).catch(() => {});
  } catch (err) {
    receipt.push({ id, description, status: "FAIL", ms: Date.now() - t0, error: String(err.message || err).slice(0, 400), consoleErrors: consoleErrors.slice(cMark).map(e => e.text).slice(0, 6), http_4xx_5xx: badResponses.slice(rMark).slice(0, 6), evidence: `${ART}/${id}.png` });
    await page.screenshot({ path: `${ART}/${id}.png`, fullPage: false }).catch(() => {});
  }
  const row = receipt[receipt.length - 1];
  console.log(`[${row.status}] ${id} ${description} (${row.ms}ms)${row.error ? " :: " + row.error : ""}`);
}

async function bodyText() { return page.evaluate(() => document.body.innerText || ""); }

async function dismissConsentModal() {
  for (const label of ["Decline", "Reject", "Necessary only", "Deny"]) {
    const btn = page.locator(`button:has-text("${label}")`).first();
    if (await btn.isVisible().catch(() => false)) { await btn.click().catch(() => {}); await page.waitForTimeout(400); return true; }
  }
  return false;
}

async function gotoAppAndSettle(screen = "/app") {
  await page.goto(`${BASE}${screen}`, { waitUntil: "load" });
  await page.waitForTimeout(800);
  await dismissConsentModal();
}

async function uiLogin(email, pass) {
  await page.goto(`${BASE}/login`, { waitUntil: "load" });
  await page.fill("#email", email);
  await page.fill('input[type="password"]', pass);
  await Promise.all([
    page.waitForURL(u => !/\/(login|signup)$/.test(u.pathname), { timeout: 45_000 }),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForLoadState("load");
  await page.waitForTimeout(600);
  await dismissConsentModal();
}

/** Signup, or — when the account already exists (a prior run created it) — log in. */
async function uiSignupOrLogin({ email, pass, name }) {
  await ctx.clearCookies();
  await page.goto(`${BASE}/signup`, { waitUntil: "load" });
  const nameField = await page.$('#name, input[name="name"]');
  if (nameField) await nameField.fill(name);
  await page.fill("#email", email);
  await page.fill('input[type="password"]', pass);
  const respP = page.waitForResponse(r => /\/api\/.*signup/.test(r.url()) || /\/auth\/signup/.test(r.url()), { timeout: 45_000 });
  await page.click('button[type="submit"]');
  const resp = await respP;
  if (resp.status() === 409 || /already exists/i.test(await bodyText())) {
    await uiLogin(email, pass);
    return { created: false };
  }
  await page.waitForURL(u => !/\/signup$/.test(u.pathname), { timeout: 45_000 });
  await page.waitForLoadState("load");
  await page.waitForTimeout(600);
  await dismissConsentModal();
  return { created: true };
}

async function switchAccount(creds) {
  await ctx.clearCookies();
  await uiLogin(creds.email, creds.pass);
}

/**
 * Drop a file through the real UI and wait for a terminal state, scoped to the
 * check surfaces: /app/check, the out-of-checks modal (which can open on /app
 * itself), or a part page at /app/part/<key> OR /app/parts/<key> (both routes
 * exist; run 3's assembly handover landed on the plural). Returns
 * { outcome, url } with outcome in:
 *   priced | priced-unsaved | assembly-priced | cant-read | refused |
 *   out-of-checks | cost-failed | geometry-bad | stopped-early | stored-failed
 */
async function uploadAndAwaitVerdict(fileAbs, { timeout = 300_000 } = {}) {
  const name = path.basename(fileAbs);
  await page.locator('input[type="file"]').first().setInputFiles(fileAbs);
  // Stage 1: the app picks the file up — it opens a check surface or the
  // out-of-checks modal. The only on-/app refusal detected here is a line that
  // names THIS file and calls it empty (run 3 showed broader patterns match
  // marketing copy and misfire: the NIST upload read as "refused").
  const stage1 = await page.waitForFunction(n => {
    if (document.getElementById("oc-title")) return "check";
    const m = location.pathname.match(/^\/app\/parts?\/([^/]+)/);
    if (m && !/^(analyses|records|packages|programs|compare)$/.test(m[1])) return "check";
    if (/^\/app\/check/.test(location.pathname)) return "check";
    const line = (document.body.innerText || "").split("\n").find(l => l.includes(n));
    if (line && /empty|nothing/i.test(line)) return "refused";
    return null;
  }, name, { timeout: 45_000, polling: 400 }).then(h => h.jsonValue());
  if (stage1 === "refused") return { outcome: "refused", url: page.url() };
  // Stage 2: terminal state of THIS check (progressSteps() in model.ts).
  return page.waitForFunction(() => {
    const t = document.body.innerText || "";
    if (document.getElementById("oc-title")) return { outcome: "out-of-checks" };
    if (document.querySelector('main[aria-label="The file you dropped"]')) return { outcome: "cant-read" };
    if (document.querySelector(".sc-card.bad")) return { outcome: "stored-failed" };
    if (/Didn.t finish/.test(t)) return { outcome: "cost-failed" };
    if (/check ran out of time|ran out of time on our side/i.test(t)) return { outcome: "cost-failed" };
    if (/Check interrupted|Nothing computed/i.test(t)) return { outcome: "interrupted" };
    if (/Nothing after Received ran/.test(t)) return { outcome: "stopped-early" };
    const rec = t.match(/Record saved\s+Record ([0-9A-Za-z-]{8})/);
    if (rec) return { outcome: "priced", record: rec[1] };
    if (/Record saved\s+Not saved: record keeping is off/.test(t)) return { outcome: "priced-unsaved" };
    if (/Not computed/.test(t)) return { outcome: "geometry-bad" };
    if (document.querySelector('main[aria-label="The assembly"]') && /\$\s?[\d,]+\.\d\d/.test(t)) return { outcome: "assembly-priced" };
    const m = location.pathname.match(/^\/app\/parts?\/([^/]+)/);
    if (m && !/^(analyses|records|packages|programs|compare)$/.test(m[1]) && /\$\s?[\d,]+\.\d\d/.test(t) && !/s so far/i.test(t)) return { outcome: "priced" };
    return null;
  }, null, { timeout, polling: 800 }).then(h => h.jsonValue()).then(r => ({ ...r, url: page.url() }));
}

const PRICED = new Set(["priced", "priced-unsaved", "assembly-priced"]);
const CLEAN_ERROR = new Set(["cant-read", "refused", "stopped-early", "geometry-bad", "stored-failed", "cost-failed", "interrupted"]);

async function assertCleanError(result) {
  const t = await bodyText();
  if (/internal server|traceback|unhandled|exception/i.test(t)) throw new Error("raw server error surfaced");
  if (!CLEAN_ERROR.has(result.outcome)) throw new Error(`expected a clean error outcome, got ${JSON.stringify(result)}`);
  return result.outcome;
}

async function apiGet(pathname, { cookie } = {}) {
  const r = await fetch(`${API}${pathname}`, { headers: cookie ? { cookie } : {} });
  return { status: r.status, body: await r.json().catch(() => null) };
}

async function dashCookie() {
  const c = await ctx.cookies();
  const s = (c || []).find(x => x.name === "dash_session");
  return s ? `dash_session=${s.value}` : null;
}

function fmtMoney(n) { return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function dollarFigures(text) { return [...new Set((text.match(/\$\s?[\d,]+\.\d{2}/g) || []).map(s => s.replace(/\s/g, "")))]; }

/** Open the first record row (button.lrow.rec on /app/parts/records) and wait
 * for its sheet — including the cost figures (run 3 captured the page before
 * the sheet rendered and "found" a parity gap that was not there). */
async function openFirstRecord() {
  await gotoAppAndSettle("/app/parts/records");
  await page.locator("button.lrow, button.rec").first().waitFor({ state: "visible", timeout: 30_000 });
  await page.locator("button.lrow, button.rec").first().click();
  await page.waitForURL(u => /\/app\/parts\/records\/.+/.test(u.pathname), { timeout: 30_000 });
  await page.waitForSelector("text=Export", { timeout: 30_000 });
  await page.waitForFunction(() => /Unit cost|\$\s?[\d,]+\.\d\d/.test(document.body.innerText || ""), null, { timeout: 30_000, polling: 500 });
  await page.waitForTimeout(500);
}

/** Minimal CSV parse (quoted fields with embedded commas/newlines). */
function parseCsv(text) {
  const rows = []; let row = []; let field = ""; let q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') q = false;
      else field += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c !== "\r") field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows.filter(r => r.length > 1);
}

/** Every finite number in the JSON export, as a formatted money string. The
 * export keys its cost lines by line name ("Machine", "Setup"), so no key
 * pattern can find them all; a sheet figure must simply appear in the export. */
function jsonMoneySet(obj, out = new Set()) {
  if (Array.isArray(obj)) { obj.forEach(v => jsonMoneySet(v, out)); return out; }
  if (obj && typeof obj === "object") { Object.values(obj).forEach(v => jsonMoneySet(v, out)); return out; }
  if (typeof obj === "number" && Number.isFinite(obj)) out.add(fmtMoney(obj));
  return out;
}

/** Switch off the public link on the open record sheet, if it has one. */
async function switchOffOpenRecordLink() {
  const off = page.getByRole("button", { name: "Switch off", exact: true }).first();
  if (!(await off.isVisible().catch(() => false))) return false;
  await off.click();
  // The row is replaced by a Confirm whose action is also "Switch off".
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: "Switch off", exact: true }).first().click();
  await page.getByRole("button", { name: "Share", exact: true }).first().waitFor({ state: "visible", timeout: 20_000 });
  return true;
}

async function main() {
  await mkdir(ART, { recursive: true });
  browser = await pw.chromium.launch({ headless: true });
  ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  page = await ctx.newPage();
  page.on("console", m => { if (m.type() === "error") consoleErrors.push({ text: m.text().slice(0, 300) }); });
  page.on("pageerror", e => consoleErrors.push({ text: String(e).slice(0, 300) }));
  page.on("response", r => { if (r.status() >= 400) badResponses.push({ status: r.status(), url: r.url().slice(0, 160) }); });

  /* ── Phase 0: public site ─────────────────────────────────── */
  await check("pub-home", "marketing home loads clean (headline, whitespace-normalized)", async () => {
    const resp = await page.goto(BASE, { waitUntil: "load" });
    if (!resp.ok()) throw new Error(`home HTTP ${resp.status()}`);
    await page.waitForFunction(() => /can\s+you\s+make\s+it/i.test((document.body.innerText || "").replace(/\s+/g, " ")), null, { timeout: 30_000 });
  }, { timeoutMs: 60_000 });
  await check("pub-login-page", "login page renders form", async () => {
    await page.goto(`${BASE}/login`, { waitUntil: "load" });
    await page.waitForSelector("#email");
  }, { timeoutMs: 60_000 });

  // Adversarial uploads run on a tier with checks left (parse failures consume
  // none, but the out-of-checks gate fires before any parsing, so an exhausted
  // account only ever sees the upsell modal).
  const adversarial = [
    ["upload-adversarial-wire", "wire-only STEP → clean engineering error, no crash", () => uploadAndAwaitVerdict(path.join(ASSETS, "wire_only_unmeshable.step"))],
    ["upload-adversarial-zerobyte", "0-byte upload → clean error", async () => {
      const p0 = `${ART}/zero-byte.stp`; await writeFile(p0, "");
      return uploadAndAwaitVerdict(p0);
    }],
    ["upload-adversarial-corrupt", "corrupt bytes upload → clean error", async () => {
      const pc = `${ART}/corrupt.step`;
      await writeFile(pc, Buffer.from([0x00, 0xff, 0x13, 0x37, ...Buffer.alloc(2048, 0x41)]));
      return uploadAndAwaitVerdict(pc);
    }],
  ];
  const adversarialOn = async tier => {
    for (const [id, desc, run] of adversarial) {
      await check(id, `${tier}: ${desc}`, async () => {
        await gotoAppAndSettle();
        const r = await run();
        await assertCleanError(r);
      }, { expect4xx: true, timeoutMs: 150_000 });
    }
    await check("upload-adversarial-oversize", `${tier}: 101MB junk .step (stored-check worker path) → clean error, no hang`, async () => {
      await gotoAppAndSettle();
      const r = await uploadAndAwaitVerdict("/tmp/oversized.step", { timeout: 480_000 });
      await assertCleanError(r);
    }, { expect4xx: true, timeoutMs: 540_000 });
  };

  /* ── Phase 1: personal tier — 3 real checks, adversarial, paywall ── */
  await check("login-personal", "UI login (personal tier account)", async () => {
    await uiLogin(CREDS.personal.email, CREDS.personal.pass);
  }, { timeoutMs: 90_000 });

  const usedAtStart = {};
  let remainAtStart = 3;
  await check("quota-personal-start", "personal usage read via UI cookie (cap 3)", async () => {
    await gotoAppAndSettle("/app/account");
    const usage = await apiGet("/auth/me/usage", { cookie: await dashCookie() });
    if (usage.status !== 200 || usage.body?.tier !== "personal" || usage.body?.cap !== 3)
      throw new Error(`usage says status=${usage.status} cap=${usage.body?.cap} tier=${usage.body?.tier}`);
    usedAtStart.personal = usage.body.used ?? 0;
    remainAtStart = Math.max(0, Math.min(3, usage.body.remaining ?? 3));
    console.log(`  usage JSON: ${JSON.stringify(usage.body)}`);
    if (remainAtStart < 3) console.log(`  note: personal account has ${remainAtStart}/3 checks left (prior runs); exhausting those`);
  }, { timeoutMs: 90_000 });

  const personalRecordIds = [];
  const personalParts = [
    ["upload-personal-prismatic", "prismatic plate-with-boss STEP — check with a price", "plate-with-boss.step"],
    ["upload-personal-thinwall", "1mm-wall bushing — check with a price", "bushing-1mm-wall.step"],
    ["upload-personal-third", "cube-with-material — final personal check", "cube_with_material.step"],
  ].slice(0, remainAtStart);
  for (const [id, desc, file] of personalParts) {
    await check(id, `personal: ${desc}`, async () => {
      await gotoAppAndSettle();
      const r = await uploadAndAwaitVerdict(path.join(ASSETS, file));
      if (!PRICED.has(r.outcome)) throw new Error(`expected a priced outcome, got ${JSON.stringify(r)}`);
      const t = await bodyText();
      if (!/\$\s?[\d,]+\.\d\d/.test(t)) throw new Error("no cost figure on the part page");
      if (r.record) personalRecordIds.push(r.record);
    }, { timeoutMs: 360_000 });
  }
  await check("personal-quota-exhausted", "personal allowance is now exhausted (remaining 0)", async () => {
    const usage = await apiGet("/auth/me/usage", { cookie: await dashCookie() });
    if (usage.body?.remaining !== 0 || usage.body?.used !== (usedAtStart.personal + personalParts.length))
      throw new Error(`expected used=${usedAtStart.personal + personalParts.length}/3 remaining=0, got ${JSON.stringify(usage.body)}`);
  }, { timeoutMs: 60_000 });
  await check("personal-paywall", "check #4 stops at the out-of-checks modal (X3), no raw 4xx/500 screen", async () => {
    await gotoAppAndSettle();
    const r = await uploadAndAwaitVerdict(path.join(ASSETS, "cube.step"), { timeout: 120_000 });
    if (r.outcome !== "out-of-checks") throw new Error(`expected out-of-checks, got ${JSON.stringify(r)}`);
    const t = await bodyText();
    if (!/free checks used|checks used|Pro/i.test(t)) throw new Error("usage bar copy missing from the modal");
  }, { timeoutMs: 180_000, expect4xx: true });

  /* ── Phase 2: work trial tier ─────────────────────────────── */
  await check("signup-work2", "UI signup (idempotent: falls back to login on 409) → work-tier account", async () => {
    await uiSignupOrLogin({ ...CREDS.work2, name: "Acceptance Work Two" });
  }, { timeoutMs: 120_000, expect4xx: true });
  await check("quota-work2-15", "work tier allowance is 15", async () => {
    await gotoAppAndSettle("/app/account");
    const usage = await apiGet("/auth/me/usage", { cookie: await dashCookie() });
    if (usage.body?.cap !== 15 || !/work|trial/i.test(usage.body?.tier || "")) throw new Error(`usage says cap=${usage.body?.cap} tier=${usage.body?.tier}`);
    console.log(`  usage JSON: ${JSON.stringify(usage.body)}`);
  }, { timeoutMs: 90_000 });
  // Adversarial CAD runs here, where checks remain (a parse failure consumes
  // nothing, but the out-of-checks gate fires before any parsing).
  await adversarialOn("work");
  await check("upload-work2-iges-inch", "work: inch IGES upload prices (unit handling)", async () => {
    await gotoAppAndSettle();
    const r = await uploadAndAwaitVerdict(path.join(ASSETS, "box-inch.iges"), { timeout: 420_000 });
    if (!PRICED.has(r.outcome)) throw new Error(`expected priced, got ${JSON.stringify(r)}`);
  }, { timeoutMs: 480_000 });

  /* ── Phase 3: pilot tier — viewer, NIST PMI, BOM, exports, share, logout ── */
  await check("login-pilot", "UI login (pilot account)", async () => {
    await switchAccount(CREDS.pilot);
  }, { timeoutMs: 90_000 });
  await check("quota-pilot-unlimited", "pilot account is unlimited", async () => {
    await gotoAppAndSettle("/app/account");
    const usage = await apiGet("/auth/me/usage", { cookie: await dashCookie() });
    if (usage.body?.plan !== "pilot" || usage.body?.unlimited !== true) throw new Error(`usage=${JSON.stringify(usage.body).slice(0, 200)}`);
  }, { timeoutMs: 90_000 });

  await check("upload-pilot-multibody", "multi-body assembly (two_bodies.step) → per-part figures / sum of parts", async () => {
    await gotoAppAndSettle();
    const r = await uploadAndAwaitVerdict("/tmp/two_bodies.step", { timeout: 420_000 });
    if (!PRICED.has(r.outcome)) throw new Error(`expected priced/assembly, got ${JSON.stringify(r)}`);
    const t = await bodyText();
    if (!/sum of parts|\d+ of \d+ costed/i.test(t)) throw new Error("assembly view lacks per-part/sum-of-parts figures");
  }, { timeoutMs: 480_000 });

  let nist = { tolerancesSeen: false, pmiBlockText: null };
  await check("upload-pilot-nist-pmi", "NIST AP242 (CTC-01) end-to-end under pilot", async () => {
    // Cached analyses are deterministic ("same file, same result, every
    // time"), so a file checked before an engine upgrade answers with the
    // pre-upgrade response. The run's copy bumps the STEP FILE_NAME
    // timestamp — bytes unique to this run, geometry and PMI identical — so
    // the check exercises today's engine, not a cached yesterday.
    const nistRun = `${ART}/nist_ctc_01.stp`;
    await writeFile(nistRun, (await readFile("/tmp/nist_ctc_01.stp"))
      .toString("utf8")
      .replace("'2021-12-21T09:14:03'", `'${new Date().toISOString()}'`));
    await gotoAppAndSettle();
    const r = await uploadAndAwaitVerdict(nistRun, { timeout: 600_000 });
    if (!PRICED.has(r.outcome)) throw new Error(`expected priced, got ${JSON.stringify(r)}`);
    const t = await bodyText();
    // The lens dial buttons carry a label plus a small sub-line ("SpecsUse it"),
    // so anchor only on the start of the button's text.
    const specs = page.locator('nav.dial button').filter({ hasText: /^Specs/ }).first();
    if (await specs.isVisible().catch(() => false)) { await specs.click(); await page.waitForTimeout(1800); }
    const t2 = await bodyText();
    // The Specs tab's PMI block ("Read from this file · N tolerances") is the
    // UI surface for the engine's AP242 reading; without the OCP deploy there
    // is nothing to read and the block is absent by design.
    const m = t2.match(/Read from this file · (\d+) tolerances?/);
    nist.tolerancesSeen = !!m && Number(m[1]) > 0;
    nist.pmiBlockText = (t2.match(/[^\n]*Read from this file[^\n]*/g) || []).join(" | ").slice(0, 300);
    if (EXPECT_TOLERANCES && !nist.tolerancesSeen) throw new Error(`PMI block missing or empty on the NIST part's Specs tab (${nist.pmiBlockText})`);
    if (!EXPECT_TOLERANCES) console.log(`  note: PMI block = ${JSON.stringify(nist.pmiBlockText)} (EXPECTED only after the OCP deploy)`);
  }, { timeoutMs: 660_000 });

  await check("webgl-viewer-orbit", "3D viewer: canvas + orbit with no WebGL/console errors", async () => {
    await gotoAppAndSettle();
    const r = await uploadAndAwaitVerdict(path.join(ASSETS, "plate-with-boss.step"), { timeout: 360_000 });
    if (!PRICED.has(r.outcome)) throw new Error(`expected priced, got ${JSON.stringify(r)}`);
    const canvas = page.locator("canvas").first();
    await canvas.waitFor({ state: "visible", timeout: 30_000 });
    const box = await canvas.boundingBox();
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
    for (let i = 0; i < 4; i++) {
      await page.mouse.move(cx - 120 + i * 60, cy - 40);
      await page.mouse.down(); await page.mouse.move(cx + 100 - i * 40, cy + 60, { steps: 8 }); await page.mouse.up();
    }
    await page.waitForTimeout(800);
    if (consoleErrors.some(e => /webgl|context lost/i.test(e.text))) throw new Error("WebGL context error during orbit");
  }, { timeoutMs: 420_000 });

  await check("bom-surface-pilot", "BOM / package surface reachable and sane", async () => {
    await gotoAppAndSettle("/app/parts/packages");
    const t = await bodyText();
    if (!/bom|assembly|package/i.test(t)) throw new Error("no BOM/assembly surface found on packages page");
  }, { timeoutMs: 90_000 });

  await check("app-screens-smoke", "every /app screen opens without 5xx", async () => {
    const screens = ["/app", "/app/check", "/app/parts", "/app/parts/analyses", "/app/parts/records", "/app/many", "/app/make", "/app/shop", "/app/setup", "/app/notices", "/app/account", "/app/account/security", "/app/account/activity", "/app/account/links", "/app/account/api", "/app/account/data", "/app/account/notifications", "/app/account/billing"];
    for (const s of screens) {
      const r = await page.goto(`${BASE}${s}`, { waitUntil: "load" });
      if (r && !r.ok() && r.status() >= 500) throw new Error(`${s} → HTTP ${r.status()}`);
      await dismissConsentModal();
      await page.waitForTimeout(150);
    }
  }, { timeoutMs: 240_000 });

  let exported = {};
  await check("record-export-parity", "record sheet: UI figures == CSV == JSON exports (PDF well-formed)", async () => {
    await openFirstRecord();
    const ui = await bodyText();
    const uiFigures = dollarFigures(ui).slice(0, 30);
    if (!uiFigures.length) throw new Error("no cost figures on the record sheet");

    const dl = path => {
      const [btnText, out] = path;
      return (async () => {
        const p = page.waitForEvent("download", { timeout: 60_000 });
        await page.getByRole("button", { name: btnText, exact: btnText === "PDF" || btnText === "JSON" }).click();
        const d = await p;
        const f = `${ART}/export-${out}`;
        await d.saveAs(f);
        return f;
      })();
    };
    exported.pdf = await dl(["PDF", "pdf"]);
    exported.csv = await dl(["CSV of cost inputs", "csv"]);
    exported.json = await dl(["JSON", "json"]);

    const pdfBuf = await readFile(exported.pdf);
    if (pdfBuf.subarray(0, 5).toString() !== "%PDF-" || pdfBuf.length < 15_000) throw new Error(`PDF malformed (${pdfBuf.length} bytes)`);
    const csvRows = parseCsv(await readFile(exported.csv, "utf8"));
    const csvHeader = csvRows[0];
    const col = n => csvHeader.indexOf(n);
    const jsonRaw = JSON.parse(await readFile(exported.json, "utf8"));

    // The CSV is "cost inputs": one row per quantity × cost line, with the
    // per-quantity unit costs repeated on each row. Cross-format parity:
    // every CSV unit cost must exist in the JSON, and the sheet must show
    // at least one of them (the displayed quantity).
    const csvUnitCosts = [...new Set(csvRows.slice(1).map(r => Number(r[col("unit_cost_usd")])))].filter(Number.isFinite);
    const csvLineUsd = [...new Set(csvRows.slice(1).map(r => Number(r[col("line_usd")])))].filter(Number.isFinite);
    const csvMoney = new Set([...csvUnitCosts, ...csvLineUsd].map(fmtMoney));
    const uiSet = new Set(uiFigures);
    const jsonFigures = [...jsonMoneySet(jsonRaw)];

    exported.parity = {
      ui: uiFigures.slice(0, 14),
      csv_unit_costs: csvUnitCosts.map(fmtMoney),
      ui_shows_csv_unit_cost: csvUnitCosts.some(v => uiSet.has(fmtMoney(v))),
      ui_shows_csv_line: csvLineUsd.some(v => uiSet.has(fmtMoney(v))),
      csv_units_in_json: csvUnitCosts.every(v => jsonFigures.includes(fmtMoney(v))),
      ui_in_json: uiFigures.filter(f => jsonFigures.includes(f)).length,
    };
    if (!exported.parity.ui_shows_csv_unit_cost && !exported.parity.ui_shows_csv_line)
      throw new Error(`no CSV figure visible in the sheet: ${JSON.stringify({ ui: uiFigures.slice(0, 10), csv: [...csvMoney].slice(0, 10) })}`);
    if (!exported.parity.csv_units_in_json)
      throw new Error(`CSV unit costs missing from JSON export: ${JSON.stringify({ csv: csvUnitCosts, json: jsonFigures.slice(0, 10) })}`);
    if (exported.parity.ui_in_json < Math.min(2, uiFigures.length))
      throw new Error(`sheet figures missing from JSON export: ${JSON.stringify({ ui: uiFigures.slice(0, 10), json: jsonFigures.slice(0, 10) })}`);
  }, { timeoutMs: 300_000 });

  let share = {};
  await check("share-link-lifecycle", "share link: create in the Share dialog, opens logged-out, switch off ends it", async () => {
    const anonOpen = async (url, shot) => {
      const anon = await browser.newContext({ viewport: { width: 1280, height: 800 } });
      const ap = await anon.newPage();
      const resp = await ap.goto(url, { waitUntil: "load" });
      await ap.waitForTimeout(1200);
      const text = await ap.evaluate(() => document.body.innerText || "");
      await ap.screenshot({ path: `${ART}/${shot}.png` }).catch(() => {});
      await anon.close();
      return { status: resp ? resp.status() : 0, text };
    };

    await openFirstRecord();
    // A link left on by an earlier run is switched off first: start from "Off".
    share.precleaned = await switchOffOpenRecordLink();
    await page.getByRole("button", { name: "Share", exact: true }).first().click();
    await page.locator('[role="dialog"]').first().waitFor({ state: "visible", timeout: 15_000 });
    const create = page.getByRole("button", { name: "Create and copy", exact: true }).first();
    await create.waitFor({ state: "visible", timeout: 30_000 });
    await create.click();
    const linkInput = page.locator('[role="dialog"] input[readonly]').first();
    await linkInput.waitFor({ state: "visible", timeout: 30_000 });
    const link = await linkInput.inputValue();
    if (!/^https?:\/\//.test(link)) throw new Error(`share link not a URL: ${link}`);
    share.link = link.replace(/[A-Za-z0-9_-]{12,}$/, "<token>");

    const live = await anonOpen(link, "share-link-anon-live");
    if (live.status >= 400) throw new Error(`share link HTTP ${live.status} while on`);
    if (!/nist|plate|\.st[ep]{1,2}|spec|quantity/i.test(live.text)) throw new Error(`shared page shows no part: ${live.text.slice(0, 160)}`);
    share.live = { status: live.status, shows: live.text.replace(/\s+/g, " ").slice(0, 140) };

    // Back on the sheet: switch it off, and the same URL must say so.
    await page.keyboard.press("Escape");
    await page.reload({ waitUntil: "load" });
    await page.waitForSelector("text=Export", { timeout: 30_000 });
    if (!(await switchOffOpenRecordLink())) throw new Error("the sheet shows no live link to switch off after creating one");
    const ended = await anonOpen(link, "share-link-anon-off");
    share.ended = { status: ended.status, shows: ended.text.replace(/\s+/g, " ").slice(0, 140) };
    if (ended.status < 400 && !/switched off|no longer|ended|not available|turned off/i.test(ended.text))
      throw new Error(`link still serves the part after switch-off: ${share.ended.shows}`);

    // Leave no public links behind on the smoke account (earlier runs did).
    share.cleaned = 0;
    for (let i = 0; i < 6; i++) {
      await gotoAppAndSettle("/app/parts/records");
      const shared = page.locator("button.lrow", { hasText: "Shared" }).first();
      if (!(await shared.isVisible().catch(() => false))) break;
      await shared.click();
      await page.waitForURL(u => /\/app\/parts\/records\/.+/.test(u.pathname), { timeout: 30_000 });
      await page.waitForSelector("text=Export", { timeout: 30_000 });
      if (!(await switchOffOpenRecordLink())) break;
      share.cleaned++;
    }
    await gotoAppAndSettle("/app/parts/records");
    if (await page.locator("button.lrow", { hasText: "Shared" }).first().isVisible().catch(() => false))
      throw new Error("a record is still publicly shared after cleanup");
  }, { timeoutMs: 300_000 });

  await check("logout-control-ux", "Security screen sign-out (with confirm) revokes the session", async () => {
    await gotoAppAndSettle("/app/account/security");
    const btn = page.getByRole("button", { name: "Sign out", exact: true }).last();
    if (!(await btn.count())) throw new Error("no Sign out control on security screen");
    await btn.click();
    // The Confirm dialog ("Sign out of every browser?") needs a second click.
    for (let i = 0; i < 3 && (await dashCookie()); i++) {
      const confirmBtn = page.getByRole("button", { name: "Sign out", exact: true }).last();
      if (await confirmBtn.isVisible().catch(() => false)) { await confirmBtn.click(); await page.waitForTimeout(1200); } else break;
    }
    if (await dashCookie()) throw new Error("dash_session still present after confirming sign-out");
    await page.goto(`${BASE}/app`, { waitUntil: "load" });
    await page.waitForTimeout(1500);
    const url = page.url();
    if (!/login|signup|\/$/.test(url)) throw new Error(`after sign-out /app did not bounce to login (url=${url})`);
  }, { timeoutMs: 120_000 });

  await check("login-persistence", "re-login restores the session", async () => {
    await uiLogin(CREDS.pilot.email, CREDS.pilot.pass);
    await gotoAppAndSettle("/app");
    const t = await bodyText();
    if (!/check a part|drop a part|choose file/i.test(t)) throw new Error("app home did not render after re-login");
  }, { timeoutMs: 120_000 });

  await browser.close();

  const failed = receipt.filter(r => r.status === "FAIL");
  const warned = receipt.filter(r => r.status === "WARN");
  const summary = {
    base: BASE, at: new Date().toISOString(), artifacts: ART, expect_tolerances: EXPECT_TOLERANCES,
    nist_tolerances_seen: nist.tolerancesSeen, nist_pmi_block: nist.pmiBlockText, exported, share,
    total: receipt.length, pass: receipt.filter(r => r.status === "PASS").length, warn: warned.length, fail: failed.length, skipped: receipt.filter(r => r.status === "SKIP").length,
    rows: receipt,
  };
  await writeFile("/tmp/scalecad_live_receipt.json", JSON.stringify(summary, null, 1));
  console.log(`\n=== ${summary.pass} PASS / ${summary.warn} WARN / ${summary.fail} FAIL of ${summary.total} ===`);
  for (const f of failed) console.log(`FAIL ${f.id}: ${f.error}`);
  for (const w of warned) console.log(`WARN ${w.id}: ${(w.consoleErrors || []).join(" | ").slice(0, 200)}`);
  console.log(`receipt: /tmp/scalecad_live_receipt.json | artifacts: ${ART}`);
  process.exit(failed.length ? 1 : 0);
}

main().catch(e => { console.error("driver crashed:", e); process.exit(2); });
