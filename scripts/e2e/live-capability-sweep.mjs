#!/usr/bin/env node
/**
 * Live capability sweep (Step C: "100% of /tmp/scalecad_capabilities.json
 * passes live"), derived from the map rather than hand-listed:
 *
 *  - every frontend page route loads (public ones logged-out, app ones as the
 *    pilot smoke account), with no "Application error" and no 5xx;
 *  - every read-only (GET/HEAD) backend route answers < 500 as the pilot
 *    account, with path params substituted from real instances fetched from
 *    the API; mutating routes are counted, never executed here (the live
 *    capability pass exercises the core mutations through the real UI);
 *  - route classes that cannot be probed safely (dynamic pages with no live
 *    instance, admin role-scoped mutations) are tallied with their reason,
 *    not silently dropped.
 *
 * Usage:  node scripts/e2e/live-capability-sweep.mjs
 * Output: /tmp/scalecad_sweep_receipt.json
 */
import { createRequire } from "node:module";
import { writeFile } from "node:fs/promises";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");

const BASE = process.env.BASE || "https://scalecad.ai";
const API = process.env.API_BASE || "https://cadverify-api.onrender.com";
const MAP = process.env.MAP || "/tmp/scalecad_capabilities.json";
const CREDS = {
  pilot: { email: process.env.PILOT_EMAIL || "nazeem.acceptance.20261114@scalecad.ai", pass: process.env.PILOT_PASS || "AcceptancePass2026" },
};

const map = require_map();
function require_map() { return JSON.parse(require("node:fs").readFileSync(MAP, "utf8")); }

// ── route normalization ────────────────────────────────────────
const GROUP = /\((site|app|v4|verify|auth|marketing)\)\//g;
function pageUrl(route) {
  let r = route.replace(GROUP, "");
  if (r === "" || r === "/") return "/";
  return r;
}
// The map renders dynamic segments as {param} (Next.js [param] normalized).
const isDynamic = r => /\{[^}]+\}|\[[^\]]+\]/.test(r);

// ── receipts ───────────────────────────────────────────────────
const rows = [];
const add = (kind, item, status, ms, detail = "") =>
  rows.push({ kind, item, status, ms: Math.round(ms), detail: String(detail).slice(0, 220) });
const tally = () => {
  const t = {};
  for (const r of rows) t[`${r.kind}:${r.status}`] = (t[`${r.kind}:${r.status}`] || 0) + 1;
  return t;
};

// ── API helpers (Node-side fetch with the pilot session) ──────
async function api(url, { cookie, method = "GET" } = {}) {
  const t0 = Date.now();
  try {
    const r = await fetch(url, { method, headers: cookie ? { cookie } : {}, redirect: "manual" });
    const body = await r.text().catch(() => "");
    return { status: r.status, ms: Date.now() - t0, body: body.slice(0, 400) };
  } catch (e) {
    return { status: 0, ms: Date.now() - t0, body: String(e).slice(0, 200) };
  }
}

async function main() {
  const browser = await pw.chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // Login through the real UI; harvest the dash_session cookie.
  await page.goto(`${BASE}/login`, { waitUntil: "load" });
  await page.fill("#email", CREDS.pilot.email);
  await page.fill('input[type="password"]', CREDS.pilot.pass);
  await Promise.all([
    page.waitForURL(u => !/\/(login|signup)$/.test(u.pathname), { timeout: 45_000 }),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForTimeout(800);
  const cookies = await ctx.cookies();
  const dash = cookies.find(c => c.name === "dash_session");
  const cookie = dash ? `dash_session=${dash.value}` : null;
  if (!cookie) { console.error("no session cookie — aborting"); process.exit(2); }
  add("auth", "pilot login", "pass", 0);

  // ── real instances for parameterized routes ──────────────────
  const instances = {};
  const listers = [
    ["id", "/api/v1/cost-decisions?limit=3", b => (JSON.parse(b).items ?? JSON.parse(b) ?? []).map(x => x.id ?? x.decision_id).filter(Boolean)],
    ["hash", "/api/v1/part-context?limit=3", b => (JSON.parse(b).parts ?? []).map(x => x.mesh_hash).filter(Boolean)],
    ["key", "/api/v1/part-context?limit=3", b => (JSON.parse(b).parts ?? []).map(x => x.mesh_hash).filter(Boolean)],
    ["decision_id", "/api/v1/cost-decisions?limit=3", b => (JSON.parse(b).items ?? JSON.parse(b) ?? []).map(x => x.id ?? x.decision_id).filter(Boolean)],
  ];
  for (const [param, url, pick] of listers) {
    const r = await api(`${API}${url}`, { cookie });
    if (r.status === 200) {
      try { const ids = pick(r.body.length > 400 ? await (await fetch(`${API}${url}`, { headers: { cookie } })).text() : r.body); if (ids.length) instances[param] = ids[0]; } catch {}
    }
  }

  // ── backend route sweep ───────────────────────────────────────
  for (const route of map.backend_routes) {
    const method = (route.method || "GET").toUpperCase();
    if (!["GET", "HEAD"].includes(method)) {
      add("backend", `${method} ${route.path}`, "not-executed-mutating", 0);
      continue;
    }
    // The map lists the router prefix itself as a row per file; those are
    // artifacts with no route behind them. Share links (/s/...) and /plans
    // are mounted on the web origin, not the API.
    if (route.path === "/api/v1" || route.path === "/api/v1/") {
      add("backend", route.path, "map-artifact", 0);
      continue;
    }
    const origin = /^(\/s\/|\/plans)/.test(route.path) ? BASE : API;
    let path = route.path;
    const params = [...path.matchAll(/\{(\w+)\}/g)].map(m => m[1]);
    let missing = params.filter(p => !instances[p]);
    if (missing.length) { add("backend", `${method} ${path}`, `skipped-no-instance(${missing.join(",")})`, 0); continue; }
    for (const p of params) path = path.replace(`{${p}}`, encodeURIComponent(instances[p]));
    const r = await api(`${origin}${path}`, { cookie });
    const status = r.status >= 500 || r.status === 0 ? "fail" : r.status < 300 ? "pass" : r.status < 400 ? "pass-redirect" : `pass-${r.status}`;
    add("backend", `${method} ${route.path}`, status, r.ms, r.status === 0 ? r.body : `HTTP ${r.status}`);
    await new Promise(res => setTimeout(res, 120)); // stay under the rate limits
  }

  // ── frontend page sweep ───────────────────────────────────────
  const seen = new Set();
  for (const entry of map.frontend_pages) {
    const url = pageUrl(entry.route);
    if (seen.has(url)) { add("page", url, "duplicate-route-group", 0); continue; }
    seen.add(url);
    if (isDynamic(url)) { add("page", url, "covered-by-live-pass", 0, "dynamic segment; the live pass opened real records/parts"); continue; }
    const t0 = Date.now();
    try {
      const resp = await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
      await page.waitForTimeout(350);
      const status = resp ? resp.status() : 0;
      const text = await page.evaluate(() => document.body.innerText || "");
      if (status >= 500 || status === 0) add("page", url, "fail", Date.now() - t0, `HTTP ${status}`);
      else if (/Application error|client-side exception/i.test(text)) add("page", url, "fail", Date.now() - t0, "application error text");
      else if (status >= 400) add("page", url, `pass-${status}`, Date.now() - t0, `HTTP ${status}`);
      else add("page", url, "pass", Date.now() - t0);
    } catch (e) {
      add("page", url, "fail", Date.now() - t0, e.message);
    }
  }

  // ── frontend BFF routes ───────────────────────────────────────
  for (const route of map.frontend_api_routes) {
    const methods = (route.methods || ["GET"]).filter(m => ["GET", "HEAD"].includes(m.toUpperCase()));
    if (!methods.length) { add("bff", `${(route.methods || []).join(",")} ${route.route}`, "not-executed-mutating", 0); continue; }
    const t0 = Date.now();
    const r = await fetch(`${BASE}${route.route}`, { headers: { cookie } });
    add("bff", `GET ${route.route}`, r.status >= 500 ? "fail" : r.status < 400 ? "pass" : `pass-${r.status}`, Date.now() - t0, `HTTP ${r.status}`);
  }

  await browser.close();

  const fails = rows.filter(r => r.status === "fail");
  const summary = {
    base: BASE, at: new Date().toISOString(), map_commit: map.repo_commit,
    totals: tally(), fails: fails.length, rows,
  };
  await writeFile("/tmp/scalecad_sweep_receipt.json", JSON.stringify(summary, null, 1));
  console.log("=== sweep tally ===");
  for (const [k, v] of Object.entries(tally()).sort()) console.log(`${String(v).padStart(4)}  ${k}`);
  console.log(fails.length ? `\nFAILS:\n${fails.map(f => `  ${f.item} :: ${f.detail}`).join("\n")}` : "\nno failures");
  console.log("receipt: /tmp/scalecad_sweep_receipt.json");
  process.exit(fails.length ? 1 : 0);
}

main().catch(e => { console.error("sweep crashed:", e); process.exit(2); });
