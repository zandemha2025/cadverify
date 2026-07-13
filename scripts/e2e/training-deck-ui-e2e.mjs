import { createRequire } from "node:module";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
let baseUrl = process.env.DECK_URL || "";
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const reportRoot = path.join(repoRoot, ".gstack", "qa-reports");
const screenshotDir = process.env.DECK_SCREENSHOT_DIR
  ? path.resolve(process.env.DECK_SCREENSHOT_DIR)
  : path.join(reportRoot, "screenshots", `training-deck-ui-${runId}`);
const reportJson = path.join(reportRoot, `training-deck-ui-${runId}.json`);
const reportMd = path.join(reportRoot, `qa-report-training-deck-ui-${runId}.md`);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function startDeckServer() {
  const root = path.join(repoRoot, "docs", "training");
  const contentTypes = { ".html": "text/html; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg" };
  const server = createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(new URL(request.url || "/", "http://127.0.0.1").pathname);
      if (pathname === "/favicon.ico") {
        response.writeHead(204).end();
        return;
      }
      const relative = pathname === "/" ? "proofshape-platform-guide.html" : pathname.replace(/^\/+/, "");
      const file = path.resolve(root, relative);
      if (!file.startsWith(`${root}${path.sep}`)) {
        response.writeHead(403).end("Forbidden");
        return;
      }
      const body = await readFile(file);
      response.writeHead(200, { "Content-Type": contentTypes[path.extname(file).toLowerCase()] || "application/octet-stream", "Cache-Control": "no-store" });
      response.end(body);
    } catch {
      response.writeHead(404).end("Not found");
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert(address && typeof address === "object", "Deck server did not expose an address");
  return { server, url: `http://127.0.0.1:${address.port}/proofshape-platform-guide.html` };
}

async function waitForActiveImages(page) {
  await page.locator(".slide.active img").evaluateAll(async (images) => {
    await Promise.all(images.map((image) => image.complete
      ? Promise.resolve()
      : new Promise((resolve, reject) => {
        image.addEventListener("load", resolve, { once: true });
        image.addEventListener("error", reject, { once: true });
      })));
    for (const image of images) {
      if (!image.naturalWidth || !image.naturalHeight) throw new Error(`Image failed: ${image.src}`);
    }
  });
}

async function activeState(page) {
  return page.locator(".slide.active").evaluate((slide) => ({
    id: slide.dataset.id,
    className: slide.className,
    horizontalOverflow: slide.scrollWidth > slide.clientWidth + 1,
    verticalOverflow: slide.scrollHeight > slide.clientHeight + 1,
    scrollWidth: slide.scrollWidth,
    clientWidth: slide.clientWidth,
    scrollHeight: slide.scrollHeight,
    clientHeight: slide.clientHeight,
    padding: getComputedStyle(slide).padding,
    copyHeight: slide.querySelector(".copy")?.getBoundingClientRect().height || 0,
    text: slide.innerText,
    images: [...slide.querySelectorAll("img")].map((image) => ({
      src: image.getAttribute("src"),
      loaded: image.complete && image.naturalWidth > 0,
    })),
    validationBadge: slide.querySelector(".validation-badge")?.textContent?.trim() || null,
  }));
}

async function main() {
  await mkdir(screenshotDir, { recursive: true });
  await mkdir(reportRoot, { recursive: true });
  let localServer = null;
  if (!baseUrl) {
    localServer = await startDeckServer();
    baseUrl = localServer.url;
  }
  const browser = await chromium.launch({ channel: "chrome", headless: true }).catch(() => chromium.launch({ headless: true }));
  const consoleErrors = [];
  const requestFailures = [];
  const checks = [];
  const screenshots = [];
  let page;

  const record = async (name, fn) => {
    const started = Date.now();
    try {
      const evidence = await fn();
      checks.push({ name, status: "PASS", durationMs: Date.now() - started, evidence });
      return evidence;
    } catch (error) {
      checks.push({ name, status: "FAIL", durationMs: Date.now() - started, error: error.message });
      throw error;
    }
  };

  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, reducedMotion: "reduce" });
    page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error" && !/favicon\.ico|status of 404 \(File not found\)/i.test(message.text())) {
        consoleErrors.push({ url: page.url(), text: message.text() });
      }
    });
    page.on("pageerror", (error) => consoleErrors.push({ url: page.url(), text: error.message }));
    page.on("requestfailed", (request) => requestFailures.push({ url: request.url(), error: request.failure()?.errorText || "request failed" }));

    await record("load 31-slide guide", async () => {
      await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30_000 });
      await page.evaluate(() => localStorage.removeItem("proofshapeGuideProgress"));
      await page.reload({ waitUntil: "networkidle" });
      assert(await page.locator(".slide").count() === 31, "Expected exactly 31 slides");
      assert((await page.locator("#counter").innerText()).trim() === "1 / 31", "Counter did not start at 1 / 31");
      return { counter: await page.locator("#counter").innerText() };
    });

    await record("buttons and keyboard navigate", async () => {
      await page.locator("#nextBtn").click();
      assert((await page.locator("#counter").innerText()).trim() === "2 / 31", "Next button failed");
      await page.locator("#prevBtn").click();
      assert((await page.locator("#counter").innerText()).trim() === "1 / 31", "Previous button failed");
      await page.keyboard.press("ArrowRight");
      assert((await page.locator("#counter").innerText()).trim() === "2 / 31", "ArrowRight failed");
      await page.keyboard.press("Home");
      assert((await page.locator("#counter").innerText()).trim() === "1 / 31", "Home failed");
      return { counter: await page.locator("#counter").innerText() };
    });

    await record("section and role jumps resolve", async () => {
      await page.locator('.section-btn[data-section="Access"]').click();
      assert((await activeState(page)).id === "access", "Access section jump failed");
      await page.keyboard.press("Home");
      await page.keyboard.press("ArrowRight");
      await page.keyboard.press("ArrowRight");
      assert((await activeState(page)).id === "roles", "Role slide was not reached");
      await page.getByRole("button", { name: /CAD engineer/i }).click();
      assert((await activeState(page)).id === "verify-upload", "CAD role jump failed");
      return { id: (await activeState(page)).id };
    });

    await record("step completion persists after reload", async () => {
      await page.keyboard.press("Home");
      for (let i = 0; i < 5; i += 1) await page.keyboard.press("ArrowRight");
      assert((await activeState(page)).id === "before", "Checklist slide was not reached");
      const first = page.locator('.slide.active [data-check="0"]');
      await first.click();
      assert(await page.locator(".slide.active .step.done").count() === 1, "Step did not become complete");
      await page.reload({ waitUntil: "networkidle" });
      assert((await activeState(page)).id === "before", "Hash did not preserve the current slide");
      assert(await page.locator(".slide.active .step.done").count() === 1, "Completed step did not persist");
      await page.evaluate(() => localStorage.removeItem("proofshapeGuideProgress"));
      return { persisted: true };
    });

    await record("evidence zoom opens and closes", async () => {
      await page.goto(`${baseUrl}?modal-check=1#slide=access`, { waitUntil: "networkidle" });
      await waitForActiveImages(page);
      await page.locator(".slide.active img").click();
      assert(await page.locator("#modal").evaluate((modal) => modal.classList.contains("open")), "Evidence modal did not open");
      await page.keyboard.press("Escape");
      assert(!await page.locator("#modal").evaluate((modal) => modal.classList.contains("open")), "Evidence modal did not close");
      return { modal: "open/close" };
    });

    await record("all desktop slides render without overflow", async () => {
      await page.goto(baseUrl, { waitUntil: "networkidle" });
      const states = [];
      for (let i = 0; i < 31; i += 1) {
        await waitForActiveImages(page);
        const state = await activeState(page);
        assert(!state.horizontalOverflow, `${state.id} has horizontal overflow (${state.scrollWidth} > ${state.clientWidth})`);
        assert(!state.verticalOverflow, `${state.id} has vertical overflow (${state.scrollHeight} > ${state.clientHeight}; class ${state.className}; padding ${state.padding}; copy ${state.copyHeight})`);
        assert(
          /expected outcome|validated scope \/ remaining gate/i.test(state.text),
          `${state.id} is missing its expected outcome or scoped validation gate`,
        );
        assert(state.images.every((image) => image.loaded), `${state.id} has an unloaded image`);
        if (state.images.length > 0) {
          assert(
            /VALIDATED|PARTIAL|EVIDENCE SCREEN/.test(state.validationBadge || ""),
            `${state.id} image is missing an explicit validation-scope badge`,
          );
        }
        const file = path.join(screenshotDir, `slide-${String(i + 1).padStart(2, "0")}-${state.id}.png`);
        await page.screenshot({ path: file });
        screenshots.push(file);
        states.push({ id: state.id, images: state.images.length, validationBadge: state.validationBadge });
        if (i < 30) await page.keyboard.press("ArrowRight");
      }
      assert((await page.locator("#counter").innerText()).trim() === "31 / 31", "Did not reach slide 31");
      assert(states.some((state) => /PARTIAL/.test(state.validationBadge || "")), "Deck did not disclose any partial validation scopes");
      assert(states.some((state) => /VALIDATED/.test(state.validationBadge || "")), "Deck did not identify validated workflows");
      return { slides: states.length, ids: states.map((state) => state.id) };
    });

    await record("mobile surface remains navigable", async () => {
      const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
      const mobilePage = await mobile.newPage();
      await mobilePage.goto(`${baseUrl}#slide=mobile`, { waitUntil: "networkidle" });
      const overflow = await mobilePage.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      assert(!overflow, "Mobile document has horizontal overflow");
      await mobilePage.locator("#menuBtn").click();
      assert(await mobilePage.locator("#drawer").evaluate((drawer) => drawer.classList.contains("open")), "Mobile section drawer did not open");
      await mobilePage.keyboard.press("Escape");
      const mobileShot = path.join(screenshotDir, "mobile-guide.png");
      await mobilePage.screenshot({ path: mobileShot, fullPage: true });
      screenshots.push(mobileShot);
      await mobile.close();
      return { width: 390, screenshot: mobileShot };
    });

    assert(consoleErrors.length === 0, `Console errors: ${JSON.stringify(consoleErrors)}`);
    assert(requestFailures.length === 0, `Request failures: ${JSON.stringify(requestFailures)}`);
    await context.close();
  } finally {
    await browser.close();
    if (localServer) await new Promise((resolve) => localServer.server.close(resolve));
  }

  const report = {
    runId,
    url: baseUrl,
    status: checks.every((check) => check.status === "PASS") && consoleErrors.length === 0 && requestFailures.length === 0 ? "PASS" : "FAIL",
    checks,
    consoleErrors,
    requestFailures,
    screenshots,
  };
  await writeFile(reportJson, `${JSON.stringify(report, null, 2)}\n`);
  const lines = [
    `# ProofShape interactive training deck QA — ${runId}`,
    "",
    `**Status:** ${report.status}`,
    `**Surface:** ${baseUrl}`,
    `**Slides:** 31 desktop + mobile`,
    `**Console errors:** ${consoleErrors.length}`,
    `**Request failures:** ${requestFailures.length}`,
    "",
    "## Checks",
    "",
    ...checks.map((check) => `- ${check.status === "PASS" ? "PASS" : "FAIL"} — ${check.name}`),
    "",
    `Screenshots: ${screenshotDir}`,
    "",
  ];
  await writeFile(reportMd, `${lines.join("\n")}\n`);
  console.log(JSON.stringify({ status: report.status, checks: checks.length, consoleErrors: consoleErrors.length, requestFailures: requestFailures.length, screenshots: screenshots.length, screenshotDir, reportMd }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
