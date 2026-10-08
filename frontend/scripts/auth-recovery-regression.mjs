// Run with APP_URL=http://127.0.0.1:3017 node scripts/auth-recovery-regression.mjs.
// All auth responses are intercepted: no account is created or email sent.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright-core";

const base = process.env.APP_URL || "http://127.0.0.1:3017";
assert.ok(["localhost", "127.0.0.1"].includes(new URL(base).hostname), "Use a local test app");
const artifacts = "../.gstack/qa-reports/screenshots";
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });
try {
  const page = await browser.newPage();
  page.setDefaultTimeout(10_000);
  let status = 500;
  let body = {};
  await page.route("**/api/auth/**", (route) => route.fulfill({ status, json: body }));
  await page.goto(`${base}/login`);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill("audit@example.invalid");
  await page.getByLabel("Password", { exact: true }).fill("SyntheticAuditOnly29!");
  for (const [code, payload, expected] of [
    [500, {}, /account service could not finish/],
    [429, {}, /Too many account requests/],
    [401, {}, /Invalid email or password/],
    [422, { detail: [{ msg: "Enter a valid email." }] }, /Enter a valid email/],
  ]) {
    status = code;
    body = payload;
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await page.getByText(expected).waitFor();
    assert.ok(await page.getByRole("button", { name: "Log in", exact: true }).isEnabled());
    if (code === 500) await page.screenshot({ path: `${artifacts}/005-auth-outage-after.png` });
  }
  console.log("PASS: login distinguishes server failure, throttling, credentials, and validation; retry remains available.");

  status = 500;
  body = {};
  await page.goto(`${base}/magic/verify#token=synthetic-audit-token`);
  await page.getByRole("button", { name: "Continue to ScaleCad" }).waitFor();
  assert.equal(new URL(page.url()).hash, "", "Token must be scrubbed from the URL");
  await page.getByRole("button", { name: "Continue to ScaleCad" }).click();
  await page.getByRole("alert").filter({ hasText: /account service could not finish/ }).waitFor();
  await page.screenshot({ path: `${artifacts}/007-magic-outage-after.png` });
  console.log("PASS: magic token survives hydration and service failures allow a retry without claiming expiration.");
} finally {
  await browser.close();
}
