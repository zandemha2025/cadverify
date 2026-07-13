import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const { unzipSync } = require("fflate");

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
const EXPECTED_SLIDES = 53;
const CUBE_SHA256 = "76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a";
const STATIC_FIXTURES = {
  "README.md": { bytes: 1_655, sha256: "8f0f70354d3672ebe2effe743ee486c45c7912b06c0c2f0a463ec09fdceca9f3" },
  "ground-truth-mixed.csv": { bytes: 1_671, sha256: "16cd702c4e063170bffcc496515b10e5fcf988e7f3bd77e0c28d3625d9f7762a" },
  "parts-manifest-mixed.csv": { bytes: 444, sha256: "567fc0c2853324d0401e2001208bf8d2c5a6ec65d099a882c05a9aab87281268" },
  "parts-master-map.csv": { bytes: 230, sha256: "118e15d195c0666533187aef6f598106c64d9aae6ab94d50bfbafa81b2d05ac5" },
  "sap-s4hana-sandbox.json": { bytes: 382, sha256: "31aa45fef08c44fc7cb8cd7cc30340a294d2fa620092200f6f7f83b588f2664f" },
  "windchill-sandbox.json": { bytes: 358, sha256: "5ff55031f13a1dc53f3c185f87c98f84101a81c23b72019774892ffe22117307" },
  "wire-only-unmeshable.step": { bytes: 2_036, sha256: "a5d464dce37e9160691f7cb721ca9d9b94d3dcabd75eb776f837430985fa23a7" },
};
const gitHead = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" }).trim();
const gitDirty = Boolean(execFileSync("git", ["status", "--porcelain", "--untracked-files=normal"], { cwd: repoRoot, encoding: "utf8" }).trim());

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
    overflowY: getComputedStyle(slide).overflowY,
  }));
}

async function downloadBytes(page, selector) {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(`.slide.active ${selector}`).click(),
  ]);
  const stream = await download.createReadStream();
  assert(stream, `Download stream was unavailable for ${selector}`);
  const chunks = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return { name: download.suggestedFilename(), bytes: Buffer.concat(chunks) };
}

async function readServedBuilds() {
  const servedBuilds = { frontend: null, backend: null };
  if (process.env.APP_URL) {
    const response = await fetch(`${process.env.APP_URL.replace(/\/+$/, "")}/status`);
    if (response.ok) servedBuilds.frontend = response.headers.get("x-proofshape-build");
  }
  if (process.env.API_URL) {
    const response = await fetch(`${process.env.API_URL.replace(/\/+$/, "")}/health`);
    if (response.ok) servedBuilds.backend = (await response.json()).build_id || null;
  }
  return servedBuilds;
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
  const servedBuilds = await readServedBuilds();
  let fatalError = null;
  let slideIds = [];
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

    await record(`load ${EXPECTED_SLIDES}-slide guide with unique routes`, async () => {
      await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30_000 });
      await page.evaluate(() => localStorage.removeItem("proofshapeGuideProgress"));
      await page.reload({ waitUntil: "networkidle" });
      const ids = await page.locator(".slide").evaluateAll((slides) => slides.map((slide) => slide.dataset.id));
      slideIds = ids;
      assert(ids.length === EXPECTED_SLIDES, `Expected exactly ${EXPECTED_SLIDES} slides, got ${ids.length}`);
      assert(new Set(ids).size === ids.length, `Slide IDs must be unique: ${JSON.stringify(ids)}`);
      assert((await page.locator("#counter").innerText()).trim() === `1 / ${EXPECTED_SLIDES}`, `Counter did not start at 1 / ${EXPECTED_SLIDES}`);
      return { counter: await page.locator("#counter").innerText(), ids };
    });

    await record("buttons and keyboard navigate", async () => {
      await page.locator("#nextBtn").click();
      assert((await page.locator("#counter").innerText()).trim() === `2 / ${EXPECTED_SLIDES}`, "Next button failed");
      await page.locator("#prevBtn").click();
      assert((await page.locator("#counter").innerText()).trim() === `1 / ${EXPECTED_SLIDES}`, "Previous button failed");
      await page.keyboard.press("ArrowRight");
      assert((await page.locator("#counter").innerText()).trim() === `2 / ${EXPECTED_SLIDES}`, "ArrowRight failed");
      await page.keyboard.press("Home");
      assert((await page.locator("#counter").innerText()).trim() === `1 / ${EXPECTED_SLIDES}`, "Home failed");
      return { counter: await page.locator("#counter").innerText() };
    });

    await record("section jump resolves", async () => {
      await page.locator('.section-btn[data-section="Access"]').click();
      assert((await activeState(page)).id === "access", "Access section jump failed");
      return { id: (await activeState(page)).id };
    });

    await record("all eight role itineraries start and advance exactly", async () => {
      const rolePaths = await page.evaluate(() => window.__proofshapeGuide.rolePaths);
      const evidence = {};
      assert(Object.keys(rolePaths).length === 8, `Expected eight role paths, got ${Object.keys(rolePaths).length}`);
      for (const [role, route] of Object.entries(rolePaths)) {
        const expected = route.slides;
        await page.goto(`${baseUrl}#slide=roles`, { waitUntil: "networkidle" });
        await page.locator(`[data-role="${role}"]`).click();
        for (let stop = 0; stop < expected.length; stop += 1) {
          assert((await activeState(page)).id === expected[stop], `${role} stop ${stop + 1} was not ${expected[stop]}`);
          const progress = page.locator(".slide.active .role-progress");
          assert(await progress.count() === 1, `${role} stop ${stop + 1} did not display role progress`);
          assert((await progress.innerText()).includes(`${stop + 1} / ${expected.length}`), `${role} progress count drifted at stop ${stop + 1}`);
          if (stop === 0) {
            await page.reload({ waitUntil: "networkidle" });
            assert((await activeState(page)).id === expected[0], `${role} reload lost its first stop`);
            assert(await page.locator(".slide.active .role-progress").count() === 1, `${role} reload lost selected-role progress`);
          }
          if (stop < expected.length - 1) {
            await page.locator(".slide.active .role-progress").getByRole("button", { name: /Next in my role/i }).click();
          }
        }
        if (expected.length > 1) {
          await page.goBack();
          assert((await activeState(page)).id === expected.at(-2), `${role} browser Back lost role position`);
          await page.goForward();
          assert((await activeState(page)).id === expected.at(-1), `${role} browser Forward lost role position`);
        }
        evidence[role] = { label: route.label, stops: expected };
      }
      return evidence;
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

    await record("embedded practice fixtures download with exact independent bytes", async () => {
      await page.goto(`${baseUrl}#slide=before`, { waitUntil: "networkidle" });
      const cube = await downloadBytes(page, '[data-fixture="cube-step"]');
      assert(cube.name === "cube.step", `Unexpected STEP filename ${cube.name}`);
      assert(cube.bytes.length === 19_030, `Expected 19,030 STEP bytes, got ${cube.bytes.length}`);
      assert(createHash("sha256").update(cube.bytes).digest("hex") === CUBE_SHA256, "Downloaded STEP hash drifted");

      const machine = await downloadBytes(page, '[data-fixture="machine-csv"]');
      assert(machine.name === "proofshape-machine-import.csv", `Unexpected machine CSV filename ${machine.name}`);
      const machineText = machine.bytes.toString("utf8");
      assert(machine.bytes.length === 348, `Machine CSV byte count drifted: ${machine.bytes.length}`);
      assert(createHash("sha256").update(machine.bytes).digest("hex") === "dc96692c9729dd8c6856821ef26e86f6d3ec6f2ab3dc09a2f7c397b9de155306", "Machine CSV hash drifted");
      assert(machineText.startsWith("process,name,count,max_workpiece_kg,hourly_rate_usd,"), "Machine CSV header drifted");
      assert(machineText.includes("cnc_3axis,QA CNC Mill,1,200,95"), "Machine CSV valid row drifted");
      assert(machineText.includes("cnc_3axis,Broken row,not-a-number"), "Machine CSV rejected row drifted");

      const batch = await downloadBytes(page, '[data-fixture="batch-zip"]');
      assert(batch.name === "proofshape-one-part-batch.zip", `Unexpected batch ZIP filename ${batch.name}`);
      const entries = unzipSync(new Uint8Array(batch.bytes));
      assert(Object.keys(entries).join(",") === "cube.step", `Batch ZIP entries drifted: ${Object.keys(entries)}`);
      const zippedCube = Buffer.from(entries["cube.step"]);
      assert(zippedCube.equals(cube.bytes), "Batch ZIP cube is not byte-identical to the standalone fixture");

      const staticLinks = await page.locator("[data-guide-fixture]").evaluateAll((links) => Object.fromEntries(links.map((link) => [
        link.dataset.guideFixture,
        link.closest(".slide")?.dataset.id,
      ])));
      assert(
        JSON.stringify(Object.keys(staticLinks).sort()) === JSON.stringify(Object.keys(STATIC_FIXTURES).sort()),
        `Static fixture actions drifted: ${JSON.stringify(staticLinks)}`,
      );
      const staticEvidence = {};
      for (const [name, contract] of Object.entries(STATIC_FIXTURES)) {
        await page.goto(`${baseUrl}#slide=${encodeURIComponent(staticLinks[name])}`, { waitUntil: "networkidle" });
        const downloaded = await downloadBytes(page, `[data-guide-fixture="${name}"]`);
        assert(downloaded.name === name, `Unexpected static fixture filename ${downloaded.name} for ${name}`);
        assert(downloaded.bytes.length === contract.bytes, `${name} byte count drifted: ${downloaded.bytes.length}`);
        const digest = createHash("sha256").update(downloaded.bytes).digest("hex");
        assert(digest === contract.sha256, `${name} SHA-256 drifted: ${digest}`);
        staticEvidence[name] = { bytes: downloaded.bytes.length, sha256: digest, slide: staticLinks[name] };
      }
      return { cubeBytes: cube.bytes.length, cubeSha256: CUBE_SHA256, machineBytes: machine.bytes.length, batchEntries: Object.keys(entries), staticFixtures: staticEvidence };
    });

    await record("application actions resolve to safe exact deep links", async () => {
      await page.goto(baseUrl, { waitUntil: "networkidle" });
      const result = await page.evaluate(() => {
        const guide = window.__proofshapeGuide;
        const links = [...document.querySelectorAll("[data-app-path]")].map((link) => ({
          path: link.dataset.appPath,
          href: link.href,
        }));
        return { appBase: guide.appBase, links };
      });
      assert(result.appBase === "http://localhost:3000", `Local guide app base drifted: ${result.appBase}`);
      assert(result.links.length > 10, `Expected broad action coverage, got ${result.links.length}`);
      for (const link of result.links) {
        assert(link.path.startsWith("/"), `Action is not root-relative: ${link.path}`);
        assert(link.href === `${result.appBase}${link.path}`, `Action href mismatch for ${link.path}: ${link.href}`);
      }
      for (const expected of ["/verify?screen=catalog", "/verify?screen=triage", "/verify?screen=machines"]) {
        assert(result.links.some((link) => link.path === expected), `Missing workspace deep link ${expected}`);
      }
      return { appBase: result.appBase, links: result.links.length };
    });

    await record("platform URL resolution handles separate host invalid input and direct file", async () => {
      await page.goto(`${baseUrl}?app=${encodeURIComponent("https://staging.proofshape.example/path")}`, { waitUntil: "networkidle" });
      assert(await page.evaluate(() => window.__proofshapeGuide.appBase) === "https://staging.proofshape.example", "Explicit separate-host app URL did not normalize to its origin");
      assert((await page.locator('[data-app-path="/login"]').getAttribute("href")) === "https://staging.proofshape.example/login", "Separate-host action link drifted");

      await page.goto(`${baseUrl}?app=${encodeURIComponent("javascript:alert(1)")}`, { waitUntil: "networkidle" });
      assert(await page.evaluate(() => window.__proofshapeGuide.appBase) === null, "Unsafe app protocol was accepted");
      assert(await page.locator("[data-needs-base]").count() > 0, "Invalid app URL did not disable platform actions");

      const fileContext = await browser.newContext({ viewport: { width: 1280, height: 720 }, reducedMotion: "reduce" });
      const filePage = await fileContext.newPage();
      const guideFile = pathToFileURL(path.join(repoRoot, "docs", "training", "proofshape-platform-guide.html")).href;
      await filePage.goto(`${guideFile}#slide=access`, { waitUntil: "load" });
      assert(await filePage.evaluate(() => window.__proofshapeGuide.appBase) === null, "Direct-file guide invented a platform origin");
      await filePage.locator(".slide.active [data-needs-base]").first().click();
      assert(await filePage.evaluate(() => document.activeElement?.id) === "platformBase", "Disabled direct-file action did not focus platform setup");
      await filePage.locator("#platformBase").fill("ftp://unsafe.example");
      await filePage.locator("#platformConfig").getByRole("button", { name: /Use this platform URL/i }).click();
      assert(/http:\/\/ or https:\/\//.test(await filePage.locator("#platformError").innerText()), "Invalid direct-file URL lacked recovery guidance");
      await filePage.locator("#platformBase").fill("https://staging.proofshape.example/workspace");
      await Promise.all([
        filePage.waitForEvent("load"),
        filePage.locator("#platformConfig").getByRole("button", { name: /Use this platform URL/i }).click(),
      ]);
      assert(await filePage.evaluate(() => window.__proofshapeGuide.appBase) === "https://staging.proofshape.example", "Direct-file platform configuration did not persist");
      await fileContext.close();
      return { separateHost: true, unsafeProtocolRejected: true, directFileConfigured: true };
    });

    await record("hidden slides cannot receive keyboard focus", async () => {
      await page.goto(baseUrl, { waitUntil: "networkidle" });
      const hidden = await page.locator('.slide[aria-hidden="true"]:not([inert])').count();
      assert(hidden === 0, `${hidden} hidden slides lack inert`);
      for (let i = 0; i < 30; i += 1) {
        await page.keyboard.press("Tab");
        const focusedHidden = await page.evaluate(() => Boolean(document.activeElement?.closest?.('.slide[aria-hidden="true"]')));
        assert(!focusedHidden, `Tab ${i + 1} entered a hidden slide`);
      }
      return { tabs: 30, hiddenSlides: EXPECTED_SLIDES - 1 };
    });

    await record("drawer modal images and checklists are keyboard complete", async () => {
      await page.goto(`${baseUrl}#slide=before`, { waitUntil: "networkidle" });
      const check = page.locator('.slide.active [data-check="0"]');
      await check.focus();
      await page.keyboard.press("Space");
      assert(await page.locator('.slide.active [data-check="0"]').getAttribute("aria-pressed") === "true", "Space did not expose checked state");
      assert(await page.evaluate(() => document.activeElement?.getAttribute("data-check")) === "0", "Checklist rerender lost focus");

      await page.locator("#menuBtn").click();
      assert(!await page.locator("#drawer").getAttribute("inert"), "Open drawer remained inert");
      const drawerFocusables = page.locator('#drawer button, #drawer input');
      await drawerFocusables.last().focus();
      await page.keyboard.press("Tab");
      assert(await page.evaluate(() => Boolean(document.activeElement?.closest?.("#drawer"))), "Tab escaped the drawer");
      await drawerFocusables.first().focus();
      await page.keyboard.press("Shift+Tab");
      assert(await page.evaluate(() => Boolean(document.activeElement?.closest?.("#drawer"))), "Shift+Tab escaped the drawer");
      await page.keyboard.press("Escape");
      assert(await page.locator("#drawer").getAttribute("inert") !== null, "Closed drawer is not inert");
      assert(await page.evaluate(() => document.activeElement?.id) === "menuBtn", "Drawer Escape did not restore menu focus");

      await page.goto(`${baseUrl}#slide=access`, { waitUntil: "networkidle" });
      const imageTrigger = page.locator(".slide.active img[role=button]").first();
      await imageTrigger.focus();
      await page.keyboard.press("Enter");
      assert(await page.locator("#modal").evaluate((modal) => modal.classList.contains("open")), "Enter did not open evidence modal");
      await page.keyboard.press("Tab");
      assert(await page.evaluate(() => Boolean(document.activeElement?.closest?.("#modal"))), "Tab escaped evidence modal");
      await page.keyboard.press("Escape");
      assert(await page.locator("#modal").getAttribute("inert") !== null, "Closed modal is not inert");
      assert(await page.evaluate(() => document.activeElement?.matches?.(".slide.active img[role=button]")), "Modal Escape did not restore image focus");
      await page.keyboard.press("Space");
      assert(await page.locator("#modal").evaluate((modal) => modal.classList.contains("open")), "Space did not reopen evidence modal");
      await page.keyboard.press("Escape");
      return { checklist: "Space + focus retained", drawer: "Tab/Shift+Tab/Escape", modal: "Enter/Space/Tab/Escape" };
    });

    await record("all desktop slides render with reachable evidence and no horizontal clipping", async () => {
      await page.goto(baseUrl, { waitUntil: "networkidle" });
      const states = [];
      for (let i = 0; i < EXPECTED_SLIDES; i += 1) {
        await waitForActiveImages(page);
        const state = await activeState(page);
        assert(!state.horizontalOverflow, `${state.id} has horizontal overflow (${state.scrollWidth} > ${state.clientWidth})`);
        assert(!state.verticalOverflow || ["auto", "scroll"].includes(state.overflowY), `${state.id} clips vertical content instead of scrolling`);
        assert(
          /expected outcome|validated scope \/ remaining gate/i.test(state.text),
          `${state.id} is missing its expected outcome or scoped validation gate`,
        );
        assert(state.images.every((image) => image.loaded), `${state.id} has an unloaded image`);
        assert(
          /BUILD VERIFIED|TEST CONTRACT|PARTIAL|EVIDENCE SCREEN/.test(state.validationBadge || ""),
          `${state.id} is missing an explicit validation-scope badge`,
        );
        const evidence = page.locator(".slide.active div.evidence");
        await evidence.scrollIntoViewIfNeeded();
        assert(await evidence.isVisible(), `${state.id} evidence is not reachable`);
        const file = path.join(screenshotDir, `slide-${String(i + 1).padStart(2, "0")}-${state.id}.png`);
        await page.screenshot({ path: file });
        screenshots.push(file);
        states.push({ id: state.id, images: state.images.length, validationBadge: state.validationBadge });
        if (i < EXPECTED_SLIDES - 1) await page.keyboard.press("ArrowRight");
      }
      assert((await page.locator("#counter").innerText()).trim() === `${EXPECTED_SLIDES} / ${EXPECTED_SLIDES}`, `Did not reach slide ${EXPECTED_SLIDES}`);
      assert(states.some((state) => /PARTIAL/.test(state.validationBadge || "")), "Deck did not disclose any partial validation scopes");
      assert(states.some((state) => /TEST CONTRACT|BUILD VERIFIED/.test(state.validationBadge || "")), "Deck did not identify covered test contracts");
      const source = await page.content();
      assert(!/64\s*\/\s*64/.test(source), "Deck self-certifies with an unearned 64/64 claim");
      assert(/exact clean-build LOCAL_100 report/i.test(source), "Finish gate does not require an exact clean-build report");
      return { slides: states.length, ids: states.map((state) => state.id) };
    });

    await record(`all ${EXPECTED_SLIDES} mobile slides remain usable at 390 by 844`, async () => {
      const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
      const mobilePage = await mobile.newPage();
      mobilePage.on("console", (message) => {
        if (message.type() === "error" && !/favicon\.ico|status of 404 \(File not found\)/i.test(message.text())) consoleErrors.push({ url: mobilePage.url(), text: message.text() });
      });
      mobilePage.on("pageerror", (error) => consoleErrors.push({ url: mobilePage.url(), text: error.message }));
      mobilePage.on("requestfailed", (request) => requestFailures.push({ url: request.url(), error: request.failure()?.errorText || "request failed" }));
      await mobilePage.goto(baseUrl, { waitUntil: "networkidle" });
      const mobileStates = [];
      for (let i = 0; i < EXPECTED_SLIDES; i += 1) {
        await waitForActiveImages(mobilePage);
        const state = await activeState(mobilePage);
        const documentOverflow = await mobilePage.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
        assert(!documentOverflow, `${state.id} creates mobile document overflow`);
        assert(!state.horizontalOverflow, `${state.id} has mobile horizontal clipping`);
        assert(/BUILD VERIFIED|TEST CONTRACT|PARTIAL|EVIDENCE SCREEN/.test(state.validationBadge || ""), `${state.id} lacks a mobile validation badge`);
        const controls = await mobilePage.locator(".slide.active button, .slide.active a").evaluateAll((elements) => elements.map((element) => {
          const rect = element.getBoundingClientRect();
          return { label: element.textContent?.trim() || element.getAttribute("aria-label"), width: rect.width, height: rect.height };
        }));
        for (const control of controls) {
          assert(control.width >= 43 && control.height >= 43, `${state.id} control is not touch-sized: ${JSON.stringify(control)}`);
        }
        const evidence = mobilePage.locator(".slide.active div.evidence");
        await evidence.scrollIntoViewIfNeeded();
        assert(await evidence.isVisible(), `${state.id} evidence is unreachable on mobile`);
        mobileStates.push({ id: state.id, controls: controls.length });
        if ([0, 2, 5, 13, 27, 40, 49, 52].includes(i)) {
          const file = path.join(screenshotDir, `mobile-${String(i + 1).padStart(2, "0")}-${state.id}.png`);
          await mobilePage.screenshot({ path: file });
          screenshots.push(file);
        }
        if (i < EXPECTED_SLIDES - 1) await mobilePage.locator("#nextBtn").click();
      }
      await mobilePage.locator("#menuBtn").click();
      assert(await mobilePage.locator("#drawer").evaluate((drawer) => drawer.classList.contains("open")), "Mobile section drawer did not open");
      await mobilePage.keyboard.press("Escape");
      assert(await mobilePage.evaluate(() => document.activeElement?.id) === "menuBtn", "Mobile drawer did not restore focus");
      await mobile.close();
      return { width: 390, height: 844, slides: mobileStates.length, controls: mobileStates.reduce((sum, state) => sum + state.controls, 0) };
    });

    assert(consoleErrors.length === 0, `Console errors: ${JSON.stringify(consoleErrors)}`);
    assert(requestFailures.length === 0, `Request failures: ${JSON.stringify(requestFailures)}`);
    await context.close();
  } catch (error) {
    fatalError = error;
  } finally {
    await browser.close();
    if (localServer) await new Promise((resolve) => localServer.server.close(resolve));
  }

  const report = {
    runId,
    url: baseUrl,
    status: !fatalError && checks.every((check) => check.status === "PASS") && consoleErrors.length === 0 && requestFailures.length === 0 ? "PASS" : "FAIL",
    fatalError: fatalError instanceof Error ? fatalError.message : fatalError ? String(fatalError) : null,
    gitHead,
    clean: !gitDirty,
    servedBuilds,
    slideEvidence: Object.fromEntries(slideIds.map((id) => [id, checks.filter((check) => check.status === "PASS" && (/all desktop|all 53 mobile/.test(check.name))).map((check) => check.name)])),
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
    `**Slides:** ${EXPECTED_SLIDES} desktop + mobile`,
    `**Console errors:** ${consoleErrors.length}`,
    `**Request failures:** ${requestFailures.length}`,
    `**Git SHA:** ${gitHead}`,
    `**Clean checkout:** ${!gitDirty}`,
    `**Served frontend/backend:** ${servedBuilds.frontend || "not supplied"} / ${servedBuilds.backend || "not supplied"}`,
    `**Fatal error:** ${report.fatalError || "none"}`,
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
  if (fatalError) throw fatalError;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
