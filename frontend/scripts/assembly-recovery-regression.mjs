// Real local AS1 assembly upload, with one injected per-part analysis outage.
// Requires APP_URL, E2E_SESSION_COOKIE, and CADVERIFY_AS1_FIXTURE.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright-core";

const base = process.env.APP_URL || "http://127.0.0.1:3017";
assert.ok(["localhost", "127.0.0.1"].includes(new URL(base).hostname));
assert.ok(process.env.E2E_SESSION_COOKIE && process.env.CADVERIFY_AS1_FIXTURE);
const output = new URL("../../.gstack/qa-reports/assembly-recovery/", import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, extraHTTPHeaders: { "x-real-ip": "203.0.113.207" } });
  await context.addInitScript(() => localStorage.setItem("proofshape_welcome_v2", "1"));
  await context.addCookies([{ name: "dash_session", value: process.env.E2E_SESSION_COOKIE, url: base, httpOnly: true, sameSite: "Lax" }]);
  const page = await context.newPage();
  const requests = [];
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/validate")) requests.push(new URL(r.url()).pathname + new URL(r.url()).search); });
  const route = "**/api/proxy/validate/assembly?format=analysis";
  await page.route(route, (r) => r.fulfill({ status: 503, json: { detail: "Assembly analysis is temporarily unavailable." } }));
  await page.goto(`${base}/verify`);
  await page.getByTestId("verify-part-cad-input").setInputFiles(process.env.CADVERIFY_AS1_FIXTURE);
  const status = page.getByTestId("assembly-analysis-status");
  await status.filter({ hasText: "PER-PART ANALYSIS — UNAVAILABLE" }).waitFor({ timeout: 120_000 });
  assert.equal(await page.getByTestId("assembly-part-row").count(), 18);
  await page.screenshot({ path: new URL("analysis-unavailable.png", output).pathname });
  await page.getByTestId("assembly-part-row").nth(1).click();
  const selected = await page.locator('[data-testid="assembly-part-row"][data-selected="true"]').innerText();
  await page.unroute(route);
  await status.getByRole("button", { name: "Retry analysis" }).waitFor({ timeout: 5000 });
  const responsePromise = page.waitForResponse((r) => r.url().endsWith("/validate/assembly?format=analysis"), { timeout: 180_000 });
  await status.getByRole("button", { name: "Retry analysis" }).click({ timeout: 5000 });
  const response = await responsePromise;
  assert.equal(response.status(), 200);
  const body = await response.json();
  assert.equal(body.part_count, 18);
  assert.ok(body.analysis.per_part.length > 0);
  await status.filter({ hasText: "PER-PART ANALYSIS — REAL" }).waitFor();
  assert.equal(await page.locator('[data-testid="assembly-part-row"][data-selected="true"]').innerText().then((s) => s.split("\n")[0]), selected.split("\n")[0]);
  assert.equal(requests.filter((p) => p.endsWith("format=json")).length, 1);
  assert.equal(requests.filter((p) => p.endsWith("format=glb")).length, 1);
  assert.equal(requests.filter((p) => p.endsWith("format=analysis")).length, 2);
  assert.equal(requests.filter((p) => p === "/api/proxy/validate/cost").length, 0);
  await page.screenshot({ path: new URL("analysis-recovered.png", output).pathname });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: new URL("analysis-mobile.png", output).pathname });
  assert.deepEqual(errors, []);
  await writeFile(new URL("result.json", output), JSON.stringify({ status: "PASS", partCount: body.part_count, summary: body.analysis.analysis_summary, requests }, null, 2));
  console.log("PASS: 18-part STP assembly, real per-part analysis, retry preserves geometry and selection");
} finally {
  await browser.close();
}
