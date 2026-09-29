// Local integration check. Requires APP_URL and E2E_SESSION_COOKIE for a test account.
// Real CAD requests reach the local backend; only named failure cases are intercepted.
import assert from "node:assert/strict";
import { readFile, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const base = process.env.APP_URL || "http://127.0.0.1:3017";
assert.ok(["localhost", "127.0.0.1"].includes(new URL(base).hostname), "Use a local test app");
assert.ok(process.env.E2E_SESSION_COOKIE, "Provide a local test account session");
const cube = await readFile(new URL("../../backend/tests/assets/cube.step", import.meta.url));
const output = new URL("../../.gstack/qa-reports/step-upload-regression/", import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--disable-webgl"] });
const temp = await mkdtemp(join(tmpdir(), "cadverify-upload-"));
const evidence = [];
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.addInitScript(() => localStorage.setItem("proofshape_welcome_v2", "1"));
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.setDefaultTimeout(15_000);
  await page.goto(`${base}/`);
  assert.equal(await page.getByRole("heading", { name: "Something went wrong" }).count(), 0);
  await page.getByRole("link", { name: "Check your first part free", exact: true }).first().waitFor();
  await context.addCookies([{ name: "dash_session", value: process.env.E2E_SESSION_COOKIE, url: base, httpOnly: true, sameSite: "Lax" }]);
  await page.goto(`${base}/verify`);
  const input = page.getByTestId("verify-part-cad-input");
  const rejection = page.getByTestId("verify-upload-rejection");
  const assemblyRoute = "**/api/proxy/validate/assembly?format=json";
  const costResponse = () => page.waitForResponse((r) => new URL(r.url()).pathname === "/api/proxy/validate/cost", { timeout: 120_000 });
  async function complete(response, name) {
    const r = await response;
    assert.equal(r.status(), 200);
    const cost = await r.json();
    assert.deepEqual([...cost.geometry.bbox_mm].sort((a, b) => a - b), [10, 15, 20]);
    assert.ok(Math.abs(cost.geometry.volume_cm3 - (3000 - 90 * Math.PI) / 1000) < 0.01);
    assert.ok(cost.saved?.id, "A success must have a persisted record");
    await page.getByRole("button", { name: "Open the record →", exact: true }).first().waitFor();
    await page.getByTestId("verify-stage-webgl-fallback").waitFor();
    evidence.push({ name, status: r.status(), geometry: cost.geometry, saved: cost.saved });
    console.log(`PASS: ${name}`);
  }

  for (const [name, mimeType] of [["part.step", "application/step"], ["part.stp", "application/octet-stream"], ["part.STEP", "model/step"], ["part.STP", ""]]) {
    const response = costResponse();
    await input.setInputFiles({ name, mimeType, buffer: cube });
    await complete(response, `${name} (${mimeType || "empty MIME"})`);
  }

  await page.goto(`${base}/verify`);
  const drop = await page.evaluateHandle(({ bytes }) => {
    const data = new DataTransfer();
    data.items.add(new File([new Uint8Array(bytes)], "dropped.STP", { type: "application/octet-stream" }));
    return data;
  }, { bytes: [...cube] });
  const dropped = costResponse();
  await page.getByRole("button", { name: /Check my part/ }).dispatchEvent("drop", { dataTransfer: drop });
  await complete(dropped, "drag-and-drop .STP");
  await drop.dispose();

  for (const [name, buffer, expected] of [
    ["empty.stp", Buffer.alloc(0), /empty file/i],
    ["malformed.STEP", Buffer.from("not CAD"), /missing ISO-10303-21 header/i],
    ["oversized.step", Buffer.alloc(101 * 1024 * 1024, 32), /100MB limit/i],
    ["native.sldprt", cube, /SolidWorks files need a STEP export/i],
  ]) {
    if (buffer.length > 50 * 1024 * 1024) {
      const path = join(temp, name);
      await writeFile(path, buffer);
      await input.setInputFiles(path);
    } else {
      await input.setInputFiles({ name, mimeType: "application/octet-stream", buffer });
    }
    await rejection.filter({ hasText: expected }).waitFor({ timeout: 60_000 });
    evidence.push({ name, error: await rejection.innerText() });
    assert.equal(await page.getByRole("button", { name: "Retry upload", exact: true }).count(), 0);
  }

  for (const status of [503, 429, 401]) {
    await page.route(assemblyRoute, (route) => route.fulfill({ status, json: {}, headers: { "retry-after": "12" } }));
    await input.setInputFiles({ name: "valid.STP", mimeType: "application/step", buffer: cube });
    await rejection.filter({ hasText: status === 401 ? /session expired/i : status === 429 ? /12 seconds/i : /service could not finish/i }).waitFor();
    assert.doesNotMatch(await rejection.innerText(), /re-export|export the assembly/i);
    if (status === 401) {
      assert.equal(await rejection.getByRole("link", { name: "Sign in again" }).getAttribute("href"), "/login?next=%2Fverify");
    } else {
      await rejection.getByRole("button", { name: "Retry upload", exact: true }).waitFor();
    }
    evidence.push({ status, error: await rejection.innerText() });
    await page.unroute(assemblyRoute);
    if (status === 503) {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: new URL("009-stp-outage-after.png", output).pathname });
      const retry = costResponse();
      await rejection.getByRole("button", { name: "Retry upload", exact: true }).click();
      await complete(retry, "retry same STP after service recovery");
      await page.setViewportSize({ width: 1440, height: 960 });
    }
  }
  assert.deepEqual(pageErrors, [], "No unhandled errors, including without WebGL");
  await writeFile(new URL("results.json", output), JSON.stringify(evidence, null, 2));
  console.log("PASS: CAD errors, bounded recovery, persisted results, and no-WebGL fallback");
} finally {
  await browser.close();
  await rm(temp, { recursive: true, force: true });
}
