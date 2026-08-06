import { createRequire } from "node:module";
import { randomBytes } from "node:crypto";
import path from "node:path";
import fs from "node:fs";

const require = createRequire("/home/user/cadverify/.claude/worktrees/hsim-base/frontend/package.json");
const pw = require("playwright-core");

const SHOTS = "/home/user/cadverify/outputs/human-sim/framework/scorecards/baseline-shots";
const STATE = path.join(SHOTS, "storage-state.json");
const EXEC = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const BASE = "http://localhost:3041";
const ASSETS = "/home/user/cadverify/outputs/human-sim/framework/demo-assets";
const CUBE = "/home/user/cadverify/.claude/worktrees/hsim-base/backend/tests/assets/cube.step";
const AS1 = "/home/user/cadverify/.claude/worktrees/hsim-base/data/real-corpus/as1-tu-203.stp";

const phase = process.argv[2] || "auth";
const log = (...a) => console.log("[driver]", ...a);
const timing = {};

async function shot(page, name, fullPage = false) {
  const file = path.join(SHOTS, `${name}.png`);
  await page.screenshot({ path: file, fullPage, animations: "disabled" });
  log("shot", file);
  return file;
}

async function newCtx(browser, useState = true) {
  const opts = { viewport: { width: 1440, height: 960 }, baseURL: BASE, reducedMotion: "reduce" };
  if (useState && fs.existsSync(STATE)) opts.storageState = STATE;
  const ctx = await browser.newContext(opts);
  const consoleErrors = [];
  ctx.on("console", () => {});
  return { ctx, consoleErrors };
}

async function main() {
  const browser = await pw.chromium.launch({
    headless: true,
    executablePath: EXEC,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });

  if (phase === "auth") {
    const { ctx } = await newCtx(browser, false);
    const page = await ctx.newPage();
    const email = `nazeem+${Date.now()}-${randomBytes(3).toString("hex")}@acme-eng.com`;
    const password = "Passw0rd123";
    log("signup email", email);
    await page.goto("/signup", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(800);
    await shot(page, "w12-01-signup-form");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await shot(page, "w12-02-signup-filled");
    await page.getByRole("button", { name: /^Create account$/ }).click();
    // land somewhere authed
    await page.waitForURL((u) => /\/(onboarding|verify)/.test(u.pathname), { timeout: 25000 }).catch(() => {});
    await page.waitForTimeout(1500);
    log("landed at", page.url());
    await shot(page, "w12-03-post-signup-landing", true);
    // navigate to /verify to confirm app access
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);
    log("verify url", page.url());
    await shot(page, "w12-04-verify-home", true);
    await ctx.storageState({ path: STATE });
    fs.writeFileSync(path.join(SHOTS, "account.json"), JSON.stringify({ email, password }));
    log("saved state + account");
  }

  if (phase === "w1" || phase === "w1b" || phase === "w1c") {
    const tag = phase; // w1, w1b, w1c for reliability repeats
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    const tNav = Date.now();
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
    timing.pageLoadMs = Date.now() - tNav;
    await page.waitForTimeout(800);
    // click Verify rail
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(800);
    await shot(page, `${tag}-01-verify-empty`);
    const input = page.locator('input[type="file"]').first();
    const tParse = Date.now();
    await input.setInputFiles(CUBE);
    // wait for terminal result
    await page.waitForFunction(() => {
      const t = document.body.innerText;
      return /unit cost|What it really takes|should-cost|Geometry invalid|Cost request failed|Validation failed|repair/i.test(t) && !/measuring geometry/i.test(t);
    }, null, { timeout: 120000 }).catch(() => {});
    timing.parseToResultMs = Date.now() - tParse;
    await page.waitForTimeout(2500);
    await shot(page, `${tag}-02-verdict`, true);
    // scroll to should-cost drivers
    await page.mouse.wheel(0, 1200);
    await page.waitForTimeout(1000);
    await shot(page, `${tag}-03-cost-drivers`, true);
    await page.mouse.wheel(0, 1400);
    await page.waitForTimeout(800);
    await shot(page, `${tag}-04-cost-more`, true);
    const bodyText = await page.locator("body").innerText();
    fs.writeFileSync(path.join(SHOTS, `${tag}-bodytext.txt`), bodyText);
    log("W1 timing", JSON.stringify(timing));
  }

  if (phase === "w2") {
    // Continue from w1 state — re-upload then toggle environment (sour/H2S)
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(600);
    const input = page.locator('input[type="file"]').first();
    await input.setInputFiles(CUBE);
    await page.waitForFunction(() => /unit cost|What it really takes|should-cost|Geometry invalid|repair/i.test(document.body.innerText) && !/measuring geometry/i.test(document.body.innerText), null, { timeout: 120000 }).catch(() => {});
    await page.waitForTimeout(2000);
    await shot(page, "w2-01-before-env", true);
    // find and toggle sour/H2S controls — dump control labels
    const controls = await page.locator('button, [role="switch"], label, select').allInnerTexts();
    fs.writeFileSync(path.join(SHOTS, "w2-controls.txt"), controls.join("\n---\n"));
    // Try to click something referencing sour / H2S / environment
    const sour = page.getByText(/sour|H2S|environment|NACE/i).first();
    if (await sour.count()) {
      await sour.click({ timeout: 4000 }).catch(() => {});
      await page.waitForTimeout(2500);
    }
    await shot(page, "w2-02-after-env-click", true);
    const bt = await page.locator("body").innerText();
    fs.writeFileSync(path.join(SHOTS, "w2-bodytext.txt"), bt);
  }

  if (phase === "w3") {
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(600);
    const input = page.locator('input[type="file"]').first();
    const t0 = Date.now();
    await input.setInputFiles(AS1);
    await page.waitForFunction(() => /part|assembly|interference|verdict|BUY|MAKE|solids/i.test(document.body.innerText) && !/measuring geometry|parsing/i.test(document.body.innerText), null, { timeout: 150000 }).catch(() => {});
    timing.assemblyMs = Date.now() - t0;
    await page.waitForTimeout(3000);
    await shot(page, "w3-01-assembly", true);
    const bt = await page.locator("body").innerText();
    fs.writeFileSync(path.join(SHOTS, "w3-bodytext.txt"), bt);
    // Try to click a bolt/nut part in tree
    const partBtns = page.locator('[class*="part"], button').filter({ hasText: /bolt|nut|M12|screw|fasten/i });
    if (await partBtns.count()) {
      await partBtns.first().click({ timeout: 4000 }).catch(() => {});
      await page.waitForTimeout(2000);
      await shot(page, "w3-02-bolt-selected", true);
    }
    log("W3 timing", JSON.stringify(timing));
  }

  if (phase === "w3b") {
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(600);
    const input = page.locator('input[type="file"]').first();
    await input.setInputFiles(AS1);
    await page.waitForFunction(() => /PRODUCT TREE|product tree|part of interest/i.test(document.body.innerText), null, { timeout: 150000 }).catch(() => {});
    // wait for per-part analysis to finish
    await page.waitForFunction(() => !/ANALYSING PER-PART|analysing per-part/i.test(document.body.innerText), null, { timeout: 120000 }).catch(() => {});
    await page.waitForTimeout(2500);
    await shot(page, "w3b-01-analysis-done", true);
    // click first bolt row
    const bolt = page.getByText(/^bolt$/i).first();
    await bolt.click({ timeout: 6000 }).catch(() => {});
    await page.waitForTimeout(2500);
    await shot(page, "w3b-02-bolt-card", true);
    fs.writeFileSync(path.join(SHOTS, "w3b-bolt-bodytext.txt"), await page.locator("body").innerText());
    // scroll to find nut and click it
    await page.evaluate(() => {
      const el = [...document.querySelectorAll("*")].find(n => /^nut$/i.test((n.textContent||"").trim()));
      el?.scrollIntoView({ block: "center" });
    });
    await page.waitForTimeout(800);
    const nut = page.getByText(/^nut$/i).first();
    if (await nut.count()) {
      await nut.click({ timeout: 6000 }).catch(() => {});
      await page.waitForTimeout(2500);
      await shot(page, "w3b-03-nut-card", true);
      fs.writeFileSync(path.join(SHOTS, "w3b-nut-bodytext.txt"), await page.locator("body").innerText());
    } else {
      log("no nut row found");
    }
  }

  if (phase === "w2b") {
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(600);
    const input = page.locator('input[type="file"]').first();
    await input.setInputFiles(CUBE);
    await page.waitForFunction(() => /unit cost|should-cost|Materials that survive/i.test(document.body.innerText) && !/measuring geometry/i.test(document.body.innerText), null, { timeout: 120000 }).catch(() => {});
    await page.waitForTimeout(2000);
    // select Steel material class so exclusions are meaningful under sour
    await page.getByText(/^Steel$/).first().click({ timeout: 4000 }).catch(() => {});
    await page.waitForFunction(() => !/measuring geometry|VERIFYING/i.test(document.body.innerText), null, { timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(2500);
    const beforeText = await page.locator("body").innerText();
    fs.writeFileSync(path.join(SHOTS, "w2b-before-bodytext.txt"), beforeText);
    await shot(page, "w2b-01-steel-ambient", true);
    // toggle sour service
    await page.getByText(/sour service/i).first().click({ timeout: 4000 }).catch(() => {});
    // wait for reverification to finish
    await page.waitForTimeout(3000);
    await page.waitForFunction(() => !/VERIFYING|measuring geometry|GATES CHECKING IN/i.test(document.body.innerText), null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, "w2b-02-sour-after", true);
    const afterText = await page.locator("body").innerText();
    fs.writeFileSync(path.join(SHOTS, "w2b-after-bodytext.txt"), afterText);
    // scroll the right panel to materials section via keyboard on a focused element
    await page.evaluate(() => {
      const el = [...document.querySelectorAll("*")].find(n => /Materials that survive/i.test(n.textContent || "") && n.children.length < 3);
      el?.scrollIntoView({ block: "center" });
    });
    await page.waitForTimeout(1200);
    await shot(page, "w2b-03-materials-section", true);
  }

  if (phase === "w11") {
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    // Parts screen
    await page.locator('button[title="Parts"]').click({ timeout: 8000 });
    await page.waitForTimeout(1500);
    await shot(page, "w11-01-parts-onboard-panel", true);
    // onboard: two hidden file inputs
    const fileInputs = page.locator('input[type="file"]');
    const n = await fileInputs.count();
    log("parts file inputs", n);
    // cad file input accepts CAD exts, mapping accepts csv/json
    const cadInput = page.locator('input[type="file"][multiple]').first();
    await cadInput.setInputFiles(path.join(ASSETS, "bracket_A.stl"));
    const mapInput = page.locator('input[type="file"][accept*=".csv"]').first();
    await mapInput.setInputFiles(path.join(ASSETS, "identity.csv"));
    await page.waitForTimeout(600);
    await shot(page, "w11-02-onboard-filled", true);
    await page.getByRole("button", { name: /Onboard library/i }).click({ timeout: 6000 }).catch(async () => {
      await page.getByText(/Onboard library/i).first().click({ timeout: 6000 });
    });
    await page.waitForTimeout(4000);
    await shot(page, "w11-03-onboard-readout", true);
    const obText = await page.locator("body").innerText();
    fs.writeFileSync(path.join(SHOTS, "w11-onboard-bodytext.txt"), obText);

    // Now verify bracket_A_rev.stl
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(800);
    const vInput = page.locator('input[type="file"]').first();
    await vInput.setInputFiles(path.join(ASSETS, "bracket_A_rev.stl"));
    await page.waitForFunction(() => /unit cost|should-cost|Looks like|identity|Geometry invalid|repair/i.test(document.body.innerText) && !/measuring geometry/i.test(document.body.innerText), null, { timeout: 120000 }).catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, "w11-04-rev-identity", true);
    const revText = await page.locator("body").innerText();
    fs.writeFileSync(path.join(SHOTS, "w11-rev-bodytext.txt"), revText);
    // try confirm
    const confirmBtn = page.getByRole("button", { name: /confirm|that.s it|yes/i }).first();
    if (await confirmBtn.count()) {
      await confirmBtn.click({ timeout: 4000 }).catch(() => {});
      await page.waitForTimeout(2500);
      await shot(page, "w11-05-confirmed", true);
      fs.writeFileSync(path.join(SHOTS, "w11-confirmed-bodytext.txt"), await page.locator("body").innerText());
    }

    // Now torus_unrelated.stl — expect NO confident match
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(800);
    const tInput = page.locator('input[type="file"]').first();
    await tInput.setInputFiles(path.join(ASSETS, "torus_unrelated.stl"));
    await page.waitForFunction(() => /unit cost|should-cost|Geometry invalid|repair/i.test(document.body.innerText) && !/measuring geometry/i.test(document.body.innerText), null, { timeout: 120000 }).catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, "w11-06-torus-nomatch", true);
    fs.writeFileSync(path.join(SHOTS, "w11-torus-bodytext.txt"), await page.locator("body").innerText());
  }

  if (phase === "spot") {
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    // wrong file type upload
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(600);
    const junk = path.join(SHOTS, "junk.txt");
    fs.writeFileSync(junk, "this is not a cad file at all\n".repeat(20));
    const input = page.locator('input[type="file"]').first();
    await input.setInputFiles(junk);
    await page.waitForTimeout(6000);
    await shot(page, "spot-01-wrongtype", true);
    const bt = await page.locator("body").innerText();
    fs.writeFileSync(path.join(SHOTS, "spot-wrongtype-bodytext.txt"), bt);
    // signed-out access to app
    const { ctx: ctx2 } = await newCtx(browser, false);
    const page2 = await ctx2.newPage();
    await page2.goto("/verify", { waitUntil: "domcontentloaded" });
    await page2.waitForTimeout(2500);
    await shot(page2, "spot-02-signedout-verify", true);
    fs.writeFileSync(path.join(SHOTS, "spot-signedout-url.txt"), page2.url());
  }

  await browser.close();
  fs.writeFileSync(path.join(SHOTS, `timing-${phase}.json`), JSON.stringify(timing, null, 2));
}

main().catch((e) => { console.error("FATAL", e); process.exit(1); });
