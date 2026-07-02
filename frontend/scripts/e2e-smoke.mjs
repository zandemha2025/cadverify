#!/usr/bin/env node
/**
 * e2e-smoke — the honest Playwright baseline (redesign safety net).
 *
 * Boots system Google Chrome via playwright-core (`channel: 'chrome'`, no
 * browser download needed — same pattern the prior session's shoot.mjs used
 * for manual visual QA), points it at the marketing home page ("/"), and
 * reports:
 *   - whether the page loaded at all
 *   - every console error / uncaught page error it saw
 *   - a full-page screenshot for human review
 *
 * BOUNDARY: unauthenticated marketing surface ONLY. There are no test
 * credentials available in this environment, so authed-page automation
 * (login, /cost, /analyses, etc.) is explicitly OUT of scope here — do not
 * extend this script to log in without first wiring real seeded test
 * credentials + a decision on how they're supplied (env, fixture, etc).
 *
 * HONESTY CONTRACT: this script never reports a pass it didn't earn.
 *   - App unreachable at APP_URL           -> clear message, exit 2 (setup
 *                                              problem, not a code defect).
 *   - Page loaded but threw console/page
 *     errors                                -> printed verbatim, exit 1.
 *   - Page loaded clean                     -> exit 0, screenshot saved.
 * It does NOT catch-and-ignore failures to force a green run.
 *
 * Usage:
 *   APP_URL=http://localhost:3000 node scripts/e2e-smoke.mjs
 *   npm run test:e2e                 # same, APP_URL defaults to :3000
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pw from "playwright-core";

const { chromium } = pw;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(__dirname, "e2e-smoke-output");
const APP_URL = (process.env.APP_URL || "http://localhost:3000").replace(/\/+$/, "");
const NAV_TIMEOUT_MS = Number(process.env.E2E_SMOKE_TIMEOUT_MS || 10_000);

const log = (...a) => console.log("[e2e-smoke]", ...a);

/** Exit codes are part of the contract — callers (CI, humans) branch on them. */
const EXIT_OK = 0;
const EXIT_SMOKE_FAILED = 1; // page loaded, but threw errors
const EXIT_APP_UNREACHABLE = 2; // couldn't even reach APP_URL — not a code bug

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  log(`target: ${APP_URL}/`);
  let browser;
  try {
    browser = await chromium.launch({ channel: "chrome", headless: true });
  } catch (e) {
    log("FAIL: could not launch system Google Chrome via playwright-core.");
    log(`  ${e.message}`);
    log("  Is Google Chrome installed at the usual macOS location?");
    process.exit(EXIT_APP_UNREACHABLE);
  }

  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  /** @type {string[]} */
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  /** Uncaught exceptions in page JS — distinct from console.error calls. */
  page.on("pageerror", (err) => {
    consoleErrors.push(`[uncaught] ${err.message}`);
  });

  let response;
  try {
    response = await page.goto(`${APP_URL}/`, {
      waitUntil: "networkidle",
      timeout: NAV_TIMEOUT_MS,
    });
  } catch (e) {
    await browser.close();
    log(`FAIL: app not reachable at ${APP_URL}/ within ${NAV_TIMEOUT_MS}ms.`);
    log(`  ${e.message}`);
    log("  This is a setup problem, not a smoke-test failure: start the app");
    log(`  (e.g. \`npm run dev\` in frontend/) or point APP_URL at a running`);
    log("  instance, then re-run. Not reporting a pass.");
    process.exit(EXIT_APP_UNREACHABLE);
  }

  if (!response || !response.ok()) {
    const status = response ? response.status() : "no response";
    log(`FAIL: ${APP_URL}/ responded with ${status}, not 2xx.`);
    await browser.close();
    process.exit(EXIT_APP_UNREACHABLE);
  }

  // Let the marketing page settle (fonts, hydration) before the shot.
  await page.waitForTimeout(500);

  const screenshotPath = path.join(OUT_DIR, "marketing-home.png");
  await page.screenshot({ path: screenshotPath, fullPage: true });
  log(`screenshot: ${screenshotPath}`);

  await browser.close();

  if (consoleErrors.length > 0) {
    log(`FAIL: ${consoleErrors.length} console error(s) on ${APP_URL}/:`);
    for (const e of consoleErrors) log(`  - ${e.slice(0, 300)}`);
    process.exit(EXIT_SMOKE_FAILED);
  }

  log(`PASS: ${APP_URL}/ loaded clean, 0 console errors.`);
  process.exit(EXIT_OK);
}

main().catch((e) => {
  // A genuinely unexpected failure in the harness itself — still not a fake
  // pass. Treat as a smoke failure, not a silent success.
  log("FAIL: unexpected error in e2e-smoke itself.");
  log(e.stack || e.message);
  process.exit(EXIT_SMOKE_FAILED);
});
