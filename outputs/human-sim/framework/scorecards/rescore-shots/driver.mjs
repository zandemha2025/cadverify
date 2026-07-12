import { createRequire } from "node:module";
import { randomBytes } from "node:crypto";
import path from "node:path";
import fs from "node:fs";

const require = createRequire("/home/user/cadverify/.claude/worktrees/hsim-rescore/frontend/package.json");
const pw = require("playwright-core");

const SHOTS = "/home/user/cadverify/outputs/human-sim/framework/scorecards/rescore-shots";
const STATE = path.join(SHOTS, "storage-state.json");
const EXEC = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const BASE = "http://localhost:3042";
const ASSETS = "/home/user/cadverify/outputs/human-sim/framework/demo-assets";
const CUBE = "/home/user/cadverify/.claude/worktrees/hsim-rescore/backend/tests/assets/cube.step";
const AS1 = "/home/user/cadverify/data/real-corpus/as1-tu-203.stp";

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
  return { ctx };
}

async function verifyUpload(page, file, extraRe) {
  await page.locator('button[title="Verify"]').click({ timeout: 8000 });
  await page.waitForTimeout(700);
  const input = page.locator('input[type="file"]').first();
  const t0 = Date.now();
  await input.setInputFiles(file);
  await page.waitForFunction(() => {
    const t = document.body.innerText;
    return /unit cost|What it really takes|should-cost|Geometry invalid|Cost request failed|Validation failed|couldn.t|Unsupported|Looks like|closest in your library|repair|BUY|MAKE/i.test(t) && !/measuring geometry/i.test(t);
  }, null, { timeout: 120000 }).catch(() => {});
  const ms = Date.now() - t0;
  return ms;
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
    await page.waitForURL((u) => /\/(onboarding|verify)/.test(u.pathname), { timeout: 25000 }).catch(() => {});
    await page.waitForTimeout(1500);
    log("landed at", page.url());
    await shot(page, "w12-03-post-signup-landing", true);
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);
    log("verify url", page.url());
    await shot(page, "w12-04-verify-home", true);
    await ctx.storageState({ path: STATE });
    fs.writeFileSync(path.join(SHOTS, "account.json"), JSON.stringify({ email, password }));
    log("saved state + account");
  }

  if (phase === "a11y") {
    // F3 — focus ring on email + password inputs
    const { ctx } = await newCtx(browser, false);
    const page = await ctx.newPage();
    await page.goto("/signup", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    // tab sequence
    const seq = [];
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press("Tab");
      await page.waitForTimeout(150);
      const info = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el) return null;
        const cs = getComputedStyle(el);
        return {
          tag: el.tagName,
          type: el.getAttribute("type"),
          name: el.getAttribute("name") || el.getAttribute("aria-label") || el.textContent?.slice(0, 30),
          outline: cs.outline,
          outlineWidth: cs.outlineWidth,
          outlineColor: cs.outlineColor,
          boxShadow: cs.boxShadow,
          borderColor: cs.borderColor,
        };
      });
      seq.push(info);
    }
    fs.writeFileSync(path.join(SHOTS, "a11y-tab-sequence.json"), JSON.stringify(seq, null, 2));
    // Focus the email input explicitly and screenshot
    const email = page.getByLabel("Email");
    await email.focus();
    await page.waitForTimeout(300);
    const emailStyle = await email.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { outline: cs.outline, outlineWidth: cs.outlineWidth, outlineColor: cs.outlineColor, boxShadow: cs.boxShadow, borderColor: cs.borderColor };
    });
    fs.writeFileSync(path.join(SHOTS, "a11y-email-focus-style.json"), JSON.stringify(emailStyle, null, 2));
    await shot(page, "f3-a11y-email-focus");
    const pwd = page.getByLabel("Password");
    await pwd.focus();
    await page.waitForTimeout(300);
    const pwdStyle = await pwd.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { outline: cs.outline, outlineWidth: cs.outlineWidth, outlineColor: cs.outlineColor, boxShadow: cs.boxShadow, borderColor: cs.borderColor };
    });
    fs.writeFileSync(path.join(SHOTS, "a11y-pwd-focus-style.json"), JSON.stringify(pwdStyle, null, 2));
    await shot(page, "f3-a11y-pwd-focus");
    log("a11y done");
  }

  if (phase === "w1" || phase === "w1b" || phase === "w1c") {
    const tag = phase;
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    const tNav = Date.now();
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
    timing.pageLoadMs = Date.now() - tNav;
    await page.waitForTimeout(800);
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(800);
    await shot(page, `${tag}-01-verify-empty`);
    const input = page.locator('input[type="file"]').first();
    const tParse = Date.now();
    await input.setInputFiles(CUBE);
    await page.waitForFunction(() => {
      const t = document.body.innerText;
      return /unit cost|What it really takes|should-cost|Geometry invalid|Cost request failed|Validation failed|repair/i.test(t) && !/measuring geometry/i.test(t);
    }, null, { timeout: 120000 }).catch(() => {});
    timing.parseToResultMs = Date.now() - tParse;
    await page.waitForTimeout(2500);
    await shot(page, `${tag}-02-verdict`, true);
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
    await page.getByText(/^Steel$/).first().click({ timeout: 4000 }).catch(() => {});
    await page.waitForFunction(() => !/measuring geometry|VERIFYING/i.test(document.body.innerText), null, { timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(2500);
    fs.writeFileSync(path.join(SHOTS, "w2b-before-bodytext.txt"), await page.locator("body").innerText());
    await shot(page, "w2b-01-steel-ambient", true);
    await page.getByText(/sour service/i).first().click({ timeout: 4000 }).catch(() => {});
    await page.waitForTimeout(3000);
    await page.waitForFunction(() => !/VERIFYING|measuring geometry|GATES CHECKING IN/i.test(document.body.innerText), null, { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(3000);
    await shot(page, "w2b-02-sour-after", true);
    fs.writeFileSync(path.join(SHOTS, "w2b-after-bodytext.txt"), await page.locator("body").innerText());
    await page.evaluate(() => {
      const el = [...document.querySelectorAll("*")].find(n => /Materials that survive/i.test(n.textContent || "") && n.children.length < 3);
      el?.scrollIntoView({ block: "center" });
    });
    await page.waitForTimeout(1200);
    await shot(page, "w2b-03-materials-section", true);
  }

  if (phase === "w3b") {
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    await page.locator('button[title="Verify"]').click({ timeout: 8000 });
    await page.waitForTimeout(600);
    const input = page.locator('input[type="file"]').first();
    const t0 = Date.now();
    await input.setInputFiles(AS1);
    await page.waitForFunction(() => /PRODUCT TREE|product tree|part of interest/i.test(document.body.innerText), null, { timeout: 150000 }).catch(() => {});
    await page.waitForFunction(() => !/ANALYSING PER-PART|analysing per-part/i.test(document.body.innerText), null, { timeout: 120000 }).catch(() => {});
    timing.assemblyMs = Date.now() - t0;
    await page.waitForTimeout(2500);
    await shot(page, "w3b-01-analysis-done", true);
    const bolt = page.getByText(/^bolt$/i).first();
    await bolt.click({ timeout: 6000 }).catch(() => {});
    await page.waitForTimeout(2500);
    await shot(page, "w3b-02-bolt-card", true);
    fs.writeFileSync(path.join(SHOTS, "w3b-bolt-bodytext.txt"), await page.locator("body").innerText());
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
    fs.writeFileSync(path.join(SHOTS, "timing-w3b.json"), JSON.stringify(timing, null, 2));
  }

  if (phase === "w11") {
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
    await page.goto("/verify", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    await page.locator('button[title="Parts"]').click({ timeout: 8000 });
    await page.waitForTimeout(1500);
    await shot(page, "w11-01-parts-onboard-panel", true);
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
    fs.writeFileSync(path.join(SHOTS, "w11-onboard-bodytext.txt"), await page.locator("body").innerText());

    // Verify bracket_A_rev.stl -> EXPECT IdentityCard
    const revMs = await verifyUpload(page, path.join(ASSETS, "bracket_A_rev.stl"));
    log("rev verify ms", revMs);
    await page.waitForTimeout(3000);
    await shot(page, "w11-04-rev-identity", true);
    fs.writeFileSync(path.join(SHOTS, "w11-rev-bodytext.txt"), await page.locator("body").innerText());
    // scroll to find identity card if lower
    await page.evaluate(() => {
      const el = [...document.querySelectorAll("*")].find(n => /Looks like|closest in your library|part library/i.test(n.textContent || "") && n.children.length < 5);
      el?.scrollIntoView({ block: "center" });
    });
    await page.waitForTimeout(800);
    await shot(page, "w11-04b-rev-identity-scrolled", true);
    // try confirm
    const confirmBtn = page.getByRole("button", { name: /^confirm|that.s it|yes,/i }).first();
    if (await confirmBtn.count()) {
      log("confirm button found");
      await confirmBtn.click({ timeout: 4000 }).catch(() => {});
      await page.waitForTimeout(2500);
      await shot(page, "w11-05-confirmed", true);
      fs.writeFileSync(path.join(SHOTS, "w11-confirmed-bodytext.txt"), await page.locator("body").innerText());
    } else {
      log("NO confirm button found");
    }

    // torus_unrelated.stl -> EXPECT NO card
    await verifyUpload(page, path.join(ASSETS, "torus_unrelated.stl"));
    await page.waitForTimeout(3000);
    await shot(page, "w11-06-torus-nomatch", true);
    fs.writeFileSync(path.join(SHOTS, "w11-torus-bodytext.txt"), await page.locator("body").innerText());
  }

  if (phase === "spot") {
    const { ctx } = await newCtx(browser, true);
    const page = await ctx.newPage();
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
    fs.writeFileSync(path.join(SHOTS, "spot-wrongtype-bodytext.txt"), await page.locator("body").innerText());
    // signed-out
    const { ctx: ctx2 } = await newCtx(browser, false);
    const page2 = await ctx2.newPage();
    await page2.goto("/verify", { waitUntil: "domcontentloaded" });
    await page2.waitForTimeout(2500);
    await shot(page2, "spot-02-signedout-verify", true);
    fs.writeFileSync(path.join(SHOTS, "spot-signedout-url.txt"), page2.url());
    // refresh mid-flow
    const { ctx: ctx3 } = await newCtx(browser, true);
    const page3 = await ctx3.newPage();
    await page3.goto("/verify", { waitUntil: "domcontentloaded" });
    await page3.waitForTimeout(1500);
    await page3.reload({ waitUntil: "domcontentloaded" });
    await page3.waitForTimeout(2500);
    await shot(page3, "spot-03-refresh", true);
    fs.writeFileSync(path.join(SHOTS, "spot-refresh-url.txt"), page3.url());
  }

  await browser.close();
  if (Object.keys(timing).length) fs.writeFileSync(path.join(SHOTS, `timing-${phase}.json`), JSON.stringify(timing, null, 2));
}

main().catch((e) => { console.error("FATAL", e); process.exit(1); });
