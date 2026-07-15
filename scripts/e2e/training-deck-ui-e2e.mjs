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
const EXPECTED_LOCAL_PATHS = 64;
const EXPECTED_EXTERNAL_PATHS = 7;
const EXPECTED_FAILURE_PATHS = 10;
const GOLDEN_PATHS_FILE = path.join(repoRoot, "docs", "HUMAN_SIMULATION_GOLDEN_PATHS.md");
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
const VALID_LEVELS = new Set(["onboarding", "basic", "advanced", "boundary"]);
const VALID_SCOPES = new Set(["local", "mixed", "external", "unsupported"]);
const PLACEHOLDER_LANGUAGE = /\b(?:lorem|ipsum|todo|tbd|fixme|coming soon|placeholder)\b|example\.com|cadverify|arcus/i;
const HISTORICAL_UNBACKED_CLAIMS = /48\s+estimate|923[- ]unit|660[- ]second|actionable\s+501|\b19,030\b/i;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sorted(values) {
  return [...values].sort((a, b) => a.localeCompare(b));
}

function sameSet(left, right) {
  return JSON.stringify(sorted(new Set(left))) === JSON.stringify(sorted(new Set(right)));
}

function parseGoldenPathContract(markdown) {
  const rows = new Map();
  for (const line of markdown.split(/\r?\n/)) {
    const cells = line.split("|").slice(1, -1).map((cell) => cell.trim());
    const id = cells[0];
    if (!/^[A-Z]+-\d{2}$/.test(id || "")) continue;
    const declaredMode = cells.at(-1);
    const mode = id.startsWith("FAIL-") ? "local" : declaredMode === "browser" ? "local" : declaredMode === "external" ? "external" : null;
    assert(mode, `Canonical golden-path row ${id} has no browser/external mode`);
    assert(!rows.has(id), `Canonical golden-path ID is duplicated: ${id}`);
    rows.set(id, { id, mode, text: cells.join(" | ") });
  }
  const localIds = [...rows.values()].filter((row) => row.mode === "local").map((row) => row.id);
  const externalIds = [...rows.values()].filter((row) => row.mode === "external").map((row) => row.id);
  const failureIds = localIds.filter((id) => id.startsWith("FAIL-"));
  assert(localIds.length === EXPECTED_LOCAL_PATHS, `Canonical local-path inventory drifted: ${localIds.length}`);
  assert(externalIds.length === EXPECTED_EXTERNAL_PATHS, `Canonical external-path inventory drifted: ${externalIds.length}`);
  assert(failureIds.length === EXPECTED_FAILURE_PATHS, `Canonical failure inventory drifted: ${failureIds.length}`);
  return { rows, localIds, externalIds, failureIds };
}

function numericTokens(text) {
  const withoutIdsOrHashes = String(text || "")
    .replace(/\b[A-Z]+-\d{2}\b/g, " ")
    .replace(/\b[a-f0-9]{64}\b/gi, " ");
  return [...withoutIdsOrHashes.matchAll(/(?<![A-Za-z0-9])\$?\d[\d,]*(?:\.\d+)?(?:\s*%|\s*°C)?(?![A-Za-z0-9])/g)]
    .map((match) => match[0].replace(/[\s,$]/g, "").replace(/°C$/, ""));
}

function validateClaimNumbers(slides, contract) {
  const derivedBySlide = {
    guarantee: new Set(["64", "7", "10"]),
    roles: new Set(["4", "5", "7", "8", "9"]),
    recovery: new Set(["10"]),
    "whole-journey": new Set(["76923244"]),
    finish: new Set(["64", "7", "10"]),
  };
  const violations = [];
  for (const slide of slides) {
    const claims = [
      { kind: "title", text: slide.title, refs: slide.proof.refs },
      { kind: "summary", text: slide.summary, refs: slide.proof.refs },
      { kind: "expected", text: slide.expected, refs: slide.proof.expectedRefs },
      ...(slide.steps || []).map((text, index) => ({ kind: `step ${index + 1}`, text, refs: slide.proof.stepRefs[index] })),
      ...(slide.actions || []).map((action, index) => ({ kind: `action ${index + 1}`, text: action[0], refs: slide.proof.actionRefs[index] })),
      ...(slide.roles || slide.metrics || slide.legend || slide.flow || []).map((card, index) => ({ kind: `card ${index + 1}`, text: card.filter((value) => typeof value === "string" && !/^#[0-9a-f]{6}$/i.test(value)).join(" "), refs: slide.proof.cardRefs[index] })),
    ];
    for (const claim of claims) {
      const canonicalText = claim.refs.map((id) => contract.rows.get(id)?.text || "").join(" ");
      const allowed = new Set([...numericTokens(canonicalText), ...(derivedBySlide[slide.id] || [])]);
      for (const token of numericTokens(claim.text)) {
        if (!allowed.has(token)) violations.push(`${slide.id} ${claim.kind}: ${token} is absent from ${claim.refs.join(", ")}`);
      }
      for (const sha of String(claim.text || "").match(/\b[a-f0-9]{64}\b/gi) || []) {
        if (!canonicalText.toLowerCase().includes(sha.toLowerCase())) violations.push(`${slide.id} ${claim.kind}: SHA-256 is absent from ${claim.refs.join(", ")}`);
      }
      for (const id of String(claim.text || "").match(/\b[A-Z]+-\d{2}\b/g) || []) {
        if (!claim.refs.includes(id)) violations.push(`${slide.id} ${claim.kind}: names ${id} without mapping it`);
      }
    }
  }
  assert(violations.length === 0, `Unbacked numeric or named-ID claims:\n${violations.join("\n")}`);
  return { auditedClaims: slides.reduce((sum, slide) => sum + 3 + (slide.steps || []).length + (slide.actions || []).length + (slide.roles || slide.metrics || slide.legend || slide.flow || []).length, 0) };
}

async function startDeckServer() {
  const root = path.join(repoRoot, "docs", "training");
  const contentTypes = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".step": "model/step",
    ".zip": "application/zip",
  };
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

async function startActionSink() {
  const requests = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    if (url.pathname === "/favicon.ico") {
      response.writeHead(204).end();
      return;
    }
    requests.push(`${url.pathname}${url.search}`);
    const label = `${url.pathname}${url.search}`.replace(/[<>&]/g, "");
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
    response.end(`<!doctype html><html><head><title>ProofShape action</title></head><body><main><h1>${label}</h1></main></body></html>`);
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert(address && typeof address === "object", "Action sink did not expose an address");
  return { server, origin: `http://127.0.0.1:${address.port}`, requests };
}

function urlWithApp(url, appOrigin) {
  const configured = new URL(url);
  configured.searchParams.set("app", appOrigin);
  configured.hash = "";
  return configured.href;
}

function monitorPage(target, consoleErrors, requestFailures, responseErrors) {
  target.on("console", (message) => {
    if (message.type() === "error" && !/favicon\.ico/i.test(message.text())) {
      consoleErrors.push({ url: target.url(), text: message.text() });
    }
  });
  target.on("pageerror", (error) => consoleErrors.push({ url: target.url(), text: error.message }));
  target.on("requestfailed", (request) => requestFailures.push({ url: request.url(), error: request.failure()?.errorText || "request failed" }));
  target.on("response", (response) => {
    if (response.status() >= 400) responseErrors.push({ url: response.url(), status: response.status() });
  });
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
    proofScope: slide.dataset.proofScope,
    level: slide.dataset.level,
    images: [...slide.querySelectorAll("img")].map((image) => ({
      src: image.getAttribute("src"),
      loaded: image.complete && image.naturalWidth > 0,
    })),
    validationBadge: slide.querySelector(".validation-badge")?.textContent?.trim() || null,
    expectedHeading: slide.querySelector(".expected strong")?.textContent?.trim() || null,
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
  const goldenContract = parseGoldenPathContract(await readFile(GOLDEN_PATHS_FILE, "utf8"));
  let localServer = null;
  if (!baseUrl) {
    localServer = await startDeckServer();
    baseUrl = localServer.url;
  }
  const actionSink = await startActionSink();
  const browser = await chromium.launch({ channel: "chrome", headless: true }).catch(() => chromium.launch({ headless: true }));
  const consoleErrors = [];
  const requestFailures = [];
  const responseErrors = [];
  const checks = [];
  const screenshots = [];
  const servedBuilds = await readServedBuilds();
  let fatalError = null;
  let slideIds = [];
  let slideContracts = {};
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
    monitorPage(page, consoleErrors, requestFailures, responseErrors);

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

    await record("every claim maps to the canonical 64 local and 7 external golden paths", async () => {
      const guide = await page.evaluate(() => {
        const api = window.__proofshapeGuide;
        return {
          localPathIds: api.localPathIds,
          externalPathIds: api.externalPathIds,
          goldenPathModes: api.goldenPathModes,
          slides: api.slides.map((slide) => ({
            id: slide.id,
            section: slide.section,
            title: slide.title,
            summary: slide.summary || "",
            expected: slide.expected || "",
            steps: slide.steps || [],
            actions: slide.actions || [],
            roles: slide.roles || null,
            metrics: slide.metrics || null,
            legend: slide.legend || null,
            flow: slide.flow || null,
            proof: slide.proof,
          })),
        };
      });
      assert(sameSet(guide.localPathIds, goldenContract.localIds), "Deck local IDs differ from the canonical markdown contract");
      assert(sameSet(guide.externalPathIds, goldenContract.externalIds), "Deck external IDs differ from the canonical markdown contract");
      assert(Object.keys(guide.goldenPathModes).length === goldenContract.rows.size, "Deck mode inventory has missing or extra IDs");
      for (const [id, row] of goldenContract.rows) {
        assert(guide.goldenPathModes[id] === row.mode, `${id} mode drifted: expected ${row.mode}, got ${guide.goldenPathModes[id]}`);
      }

      const substantiveCoverage = new Map([...goldenContract.rows.keys()].map((id) => [id, []]));
      for (const slide of guide.slides) {
        const { proof } = slide;
        assert(VALID_LEVELS.has(proof.level), `${slide.id} has invalid learning level ${proof.level}`);
        assert(VALID_SCOPES.has(proof.scope), `${slide.id} has invalid proof scope ${proof.scope}`);
        assert(proof.refs.length > 0, `${slide.id} has no golden-path refs`);
        assert(proof.source && !PLACEHOLDER_LANGUAGE.test(proof.source), `${slide.id} has missing or provisional evidence source`);
        for (const id of proof.refs) assert(goldenContract.rows.has(id), `${slide.id} maps unknown ID ${id}`);
        const modes = new Set(proof.refs.map((id) => goldenContract.rows.get(id).mode));
        if (proof.scope === "local" || proof.scope === "unsupported") assert(sameSet(modes, ["local"]), `${slide.id} ${proof.scope} scope includes an external ID`);
        if (proof.scope === "external") assert(sameSet(modes, ["external"]), `${slide.id} external scope includes a local ID`);
        if (proof.scope === "mixed") assert(sameSet(modes, ["local", "external"]), `${slide.id} mixed scope does not include both modes`);
        const cardCount = (slide.roles || slide.metrics || slide.legend || slide.flow || []).length;
        for (const [label, mappings, count] of [
          ["step", proof.stepRefs, slide.steps.length],
          ["action", proof.actionRefs, slide.actions.length],
          ["card", proof.cardRefs, cardCount],
        ]) {
          assert(mappings.length === count, `${slide.id} ${label} mapping count ${mappings.length} != ${count}`);
          mappings.forEach((refs, index) => {
            assert(refs.length > 0, `${slide.id} ${label} ${index + 1} has no evidence mapping`);
            refs.forEach((id) => {
              assert(goldenContract.rows.has(id), `${slide.id} ${label} ${index + 1} maps unknown ${id}`);
              assert(proof.refs.includes(id), `${slide.id} ${label} ${index + 1} maps ${id} outside its slide contract`);
            });
          });
        }
        assert(proof.expectedRefs.length > 0, `${slide.id} expected result has no evidence mapping`);
        proof.expectedRefs.forEach((id) => assert(proof.refs.includes(id), `${slide.id} expected result maps ${id} outside its slide contract`));
        if (!["guarantee", "roles", "finish"].includes(slide.id)) {
          proof.refs.forEach((id) => substantiveCoverage.get(id).push(slide.id));
        }
      }
      const uncovered = [...substantiveCoverage].filter(([, ids]) => ids.length === 0).map(([id]) => id);
      assert(uncovered.length === 0, `Golden paths appear only in inventory/finish slides: ${uncovered.join(", ")}`);

      const domAudit = await page.evaluate(() => {
        const issues = [];
        const ids = [...document.querySelectorAll("[id]")].map((node) => node.id);
        const duplicates = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
        if (duplicates.length) issues.push(`duplicate DOM IDs: ${duplicates.join(", ")}`);
        const claimNodes = [...document.querySelectorAll(".claim, [data-claim], .slide h2, .slide .lede, .step-text, .card, .action-wrap, .expected, .evidence, .image-trigger")];
        const mappings = claimNodes.map((node) => ({
          slide: node.closest(".slide")?.dataset.id || "shell",
          kind: node.className || node.tagName,
          refs: (node.getAttribute("data-golden-paths") || "").split(/\s+/).filter(Boolean),
        }));
        for (const mapping of mappings) if (!mapping.refs.length) issues.push(`${mapping.slide} ${mapping.kind} lacks data-golden-paths`);
        for (const node of document.querySelectorAll("a[target='_blank']")) {
          const rel = new Set((node.getAttribute("rel") || "").split(/\s+/));
          if (!rel.has("noopener") || !rel.has("noreferrer")) issues.push(`unsafe target=_blank link: ${node.textContent?.trim()}`);
        }
        if (document.querySelector("a a, a button, button a, button button")) issues.push("nested interactive controls exist");
        for (const node of document.querySelectorAll("button, a[href], input, select, summary")) {
          const label = node.getAttribute("aria-label") || node.textContent?.trim() || (node.id ? document.querySelector(`label[for='${CSS.escape(node.id)}']`)?.textContent?.trim() : "") || node.getAttribute("title");
          if (!label) issues.push(`unnamed interactive ${node.tagName.toLowerCase()}${node.id ? `#${node.id}` : ""}`);
        }
        for (const image of document.querySelectorAll("img")) if (!image.getAttribute("alt")) issues.push(`image lacks alt: ${image.getAttribute("src")}`);
        if (document.querySelectorAll("main").length !== 1) issues.push("guide must expose one main landmark");
        if (!document.querySelector("#progressTrack[role='progressbar'][aria-valuenow][aria-valuemax]")) issues.push("progressbar semantics are incomplete");
        if (!document.querySelector("#slideStatus[aria-live='polite']")) issues.push("slide changes lack a polite live region");
        return { issues, mappings, bodyText: document.body.innerText, links: [...document.querySelectorAll("a[href]")].map((node) => node.getAttribute("href")) };
      });
      assert(domAudit.issues.length === 0, `Accessibility/evidence semantics failed:\n${domAudit.issues.join("\n")}`);
      for (const mapping of domAudit.mappings) for (const id of mapping.refs) assert(goldenContract.rows.has(id), `${mapping.slide} DOM maps unknown ${id}`);
      assert(!PLACEHOLDER_LANGUAGE.test(domAudit.bodyText), `Visible placeholder or legacy language remains: ${domAudit.bodyText.match(PLACEHOLDER_LANGUAGE)?.[0]}`);
      assert(!HISTORICAL_UNBACKED_CLAIMS.test(domAudit.bodyText), `Historical unbacked claim remains: ${domAudit.bodyText.match(HISTORICAL_UNBACKED_CLAIMS)?.[0]}`);
      assert(domAudit.links.every((href) => href && !href.startsWith("javascript:")), "A link is empty or uses javascript:");
      const numericEvidence = validateClaimNumbers(guide.slides, goldenContract);
      slideContracts = Object.fromEntries(guide.slides.map((slide) => [slide.id, slide.proof.refs]));
      return {
        local: guide.localPathIds.length,
        external: guide.externalPathIds.length,
        failures: goldenContract.failureIds.length,
        slides: guide.slides.length,
        mappedDomClaims: domAudit.mappings.length,
        auditedClaims: numericEvidence.auditedClaims,
      };
    });

    await record("navigation buttons keyboard progress skip link and fullscreen resolve", async () => {
      assert(await page.locator("#prevBtn").isDisabled(), "Previous must be disabled on the first slide");
      assert((await page.locator("#progressTrack").getAttribute("aria-valuenow")) === "1", "Progressbar did not start at one");
      await page.locator("#nextBtn").click();
      assert((await page.locator("#counter").innerText()).trim() === `2 / ${EXPECTED_SLIDES}`, "Next button failed");
      await page.locator("#prevBtn").click();
      assert((await page.locator("#counter").innerText()).trim() === `1 / ${EXPECTED_SLIDES}`, "Previous button failed");
      await page.keyboard.press("ArrowRight");
      assert((await page.locator("#counter").innerText()).trim() === `2 / ${EXPECTED_SLIDES}`, "ArrowRight failed");
      await page.keyboard.press("PageDown");
      assert((await page.locator("#counter").innerText()).trim() === `3 / ${EXPECTED_SLIDES}`, "PageDown failed");
      await page.keyboard.press("PageUp");
      assert((await page.locator("#counter").innerText()).trim() === `2 / ${EXPECTED_SLIDES}`, "PageUp failed");
      await page.keyboard.press("Home");
      assert((await page.locator("#counter").innerText()).trim() === `1 / ${EXPECTED_SLIDES}`, "Home failed");
      await page.keyboard.press("End");
      assert((await page.locator("#counter").innerText()).trim() === `${EXPECTED_SLIDES} / ${EXPECTED_SLIDES}`, "End failed");
      assert(await page.locator("#nextBtn").isDisabled(), "Next must be disabled on the final slide");
      assert((await page.locator("#progressTrack").getAttribute("aria-valuenow")) === String(EXPECTED_SLIDES), "Progressbar did not reach the final slide");
      await page.keyboard.press("Home");
      await page.locator(".skip-link").focus();
      await page.keyboard.press("Enter");
      assert(await page.evaluate(() => document.activeElement?.id) === "guideMain", "Skip link did not focus the main guide landmark");
      const fullscreen = page.locator("#fullBtn");
      if (await fullscreen.isVisible()) {
        await fullscreen.click();
        await page.waitForFunction(() => Boolean(document.fullscreenElement));
        await page.waitForFunction(() => document.getElementById("fullBtn")?.getAttribute("aria-pressed") === "true");
        await fullscreen.click();
        await page.waitForFunction(() => !document.fullscreenElement);
      }
      return { counter: await page.locator("#counter").innerText(), fullscreen: await fullscreen.isVisible() ? "entered/exited" : "browser unsupported" };
    });

    await record("every section jump resolves to its first slide", async () => {
      const sections = await page.locator(".section-btn").evaluateAll((buttons) => buttons.map((button) => button.dataset.section));
      const resolved = {};
      for (const section of sections) {
        await page.locator(`.section-btn[data-section="${section}"]`).click();
        const expected = await page.evaluate((name) => window.__proofshapeGuide.slides.find((slide) => slide.section === name)?.id, section);
        const actual = (await activeState(page)).id;
        assert(actual === expected, `${section} jump opened ${actual}, expected ${expected}`);
        resolved[section] = actual;
      }
      return resolved;
    });

    await record("use-case search separates levels and every slide result opens", async () => {
      await page.keyboard.press("Home");
      await page.keyboard.press("/");
      assert(await page.locator("#drawer").evaluate((drawer) => drawer.classList.contains("open")), "/ did not open use-case search");
      assert(await page.evaluate(() => document.activeElement?.id) === "guideSearch", "Search did not receive focus");
      await page.locator("#guideSearch").fill("VER-05");
      const idMatches = await page.locator("#drawerLinks [data-slide-jump]").count();
      assert(idMatches > 0 && idMatches < EXPECTED_SLIDES, `VER-05 search was not selective: ${idMatches}`);
      assert(await page.locator("#drawerLinks").innerText().then((text) => text.includes("VER-05")), "VER-05 search results omit the matched ID");
      await page.locator("#guideSearch").fill("");
      for (const level of VALID_LEVELS) {
        await page.locator("#levelFilter").selectOption(level);
        const resultLevels = await page.locator("#drawerLinks [data-slide-jump]").evaluateAll((buttons) => buttons.map((button) => button.querySelector("span")?.textContent || ""));
        assert(resultLevels.length > 0, `${level} filter returned no use cases`);
        assert(resultLevels.every((text) => text.includes(` · ${level} · `)), `${level} filter mixed learning levels`);
      }
      await page.locator("#levelFilter").selectOption("all");
      await page.locator("#guideSearch").fill("no-such-proofshape-use-case");
      assert(/No use case matches/i.test(await page.locator("#drawerLinks").innerText()), "Empty search lacks recovery copy");
      await page.locator("#guideSearch").fill("");
      const resultIds = await page.locator("#drawerLinks [data-slide-jump]").evaluateAll((buttons) => buttons.map((button) => button.dataset.slideJump));
      assert(resultIds.length === EXPECTED_SLIDES && sameSet(resultIds, slideIds), "Unfiltered search does not expose every slide exactly once");
      await page.keyboard.press("Escape");
      for (const id of slideIds) {
        await page.locator("#menuBtn").click();
        await page.locator(`#drawerLinks [data-slide-jump="${id}"]`).click();
        assert((await activeState(page)).id === id, `Search result failed to open ${id}`);
      }
      await page.locator("#menuBtn").click();
      await page.locator("#drawerClose").click();
      assert(!await page.locator("#drawer").evaluate((drawer) => drawer.classList.contains("open")), "Drawer close button failed");
      await page.locator("#menuBtn").click();
      await page.mouse.click(1270, 100);
      assert(!await page.locator("#drawer").evaluate((drawer) => drawer.classList.contains("open")), "Drawer scrim failed to close");
      return { queryMatches: idMatches, levels: VALID_LEVELS.size, slideResultsOpened: resultIds.length };
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
      await page.evaluate(() => localStorage.setItem("proofshapeGuideProgress", "{malformed"));
      await page.reload({ waitUntil: "networkidle" });
      assert(await page.locator(".slide.active .step.done").count() === 0, "Malformed progress did not recover to an empty checklist");
      assert(await page.evaluate(() => localStorage.getItem("proofshapeGuideProgress")) === null, "Malformed progress was not removed");
      return { persisted: true, malformedStateRecovered: true };
    });

    await record("every checklist control toggles and restores exact completion progress", async () => {
      await page.evaluate(() => localStorage.removeItem("proofshapeGuideProgress"));
      await page.reload({ waitUntil: "networkidle" });
      let toggled = 0;
      for (const id of slideIds) {
        await page.goto(`${baseUrl}#slide=${encodeURIComponent(id)}`, { waitUntil: "networkidle" });
        const count = await page.locator(".slide.active [data-check]").count();
        for (let index = 0; index < count; index += 1) {
          const control = page.locator(`.slide.active [data-check="${index}"]`);
          await control.click();
          assert((await control.getAttribute("aria-pressed")) === "true", `${id} step ${index + 1} did not become complete`);
          assert(/\d+ of \d+ practice steps checked/.test(await page.locator("#completionSummary").innerText()), `${id} did not update completion summary`);
          await control.click();
          assert((await control.getAttribute("aria-pressed")) === "false", `${id} step ${index + 1} did not restore incomplete state`);
          toggled += 1;
        }
      }
      assert(await page.evaluate(() => JSON.parse(localStorage.getItem("proofshapeGuideProgress") || "{}")).then((state) => Object.values(state).every((steps) => steps.length === 0)), "Checklist controls did not restore empty progress");
      return { controlsToggledTwice: toggled };
    });

    await record("every evidence disclosure and image modal opens and closes", async () => {
      let disclosures = 0;
      let images = 0;
      for (const id of slideIds) {
        await page.goto(`${baseUrl}#slide=${encodeURIComponent(id)}`, { waitUntil: "networkidle" });
        const details = page.locator(".slide.active details.evidence");
        assert(await details.count() === 1, `${id} has no evidence disclosure`);
        await details.locator("summary").click();
        assert(await details.getAttribute("open") !== null, `${id} evidence did not expand`);
        assert(await details.locator(".evidence-body").isVisible(), `${id} evidence body is not visible when expanded`);
        await details.locator("summary").click();
        assert(await details.getAttribute("open") === null, `${id} evidence did not collapse`);
        disclosures += 1;
        await waitForActiveImages(page);
        const triggerCount = await page.locator(".slide.active .image-trigger").count();
        for (let index = 0; index < triggerCount; index += 1) {
          const trigger = page.locator(".slide.active .image-trigger").nth(index);
          const source = await trigger.locator("img").getAttribute("src");
          await trigger.click();
          assert(await page.locator("#modal").evaluate((modal) => modal.classList.contains("open")), `${id} image ${index + 1} did not open`);
          assert((await page.locator("#modalImage").getAttribute("src"))?.endsWith(source || ""), `${id} modal image source drifted`);
          await page.locator("#closeModal").click();
          assert(!await page.locator("#modal").evaluate((modal) => modal.classList.contains("open")), `${id} image ${index + 1} did not close`);
          assert(await trigger.evaluate((node) => node === document.activeElement), `${id} image ${index + 1} did not regain focus`);
          images += 1;
        }
      }
      return { disclosures, imageModals: images };
    });

    await record("every fixture link downloads and exact bytes hashes and archive contents validate", async () => {
      await page.goto(baseUrl, { waitUntil: "networkidle" });
      const fixtureLinks = await page.locator("[data-fixture]").evaluateAll((links) => links.map((link) => ({
        fixture: link.dataset.fixture,
        slide: link.closest(".slide")?.dataset.id,
      })));
      assert(fixtureLinks.length > 3, `Expected repeated hands-on fixture controls, got ${fixtureLinks.length}`);
      const embeddedEvidence = [];
      let canonicalCube = null;
      for (const link of fixtureLinks) {
        await page.goto(`${baseUrl}#slide=${encodeURIComponent(link.slide)}`, { waitUntil: "networkidle" });
        const downloaded = await downloadBytes(page, `[data-fixture="${link.fixture}"]`);
        if (link.fixture === "cube-step") {
          assert(downloaded.name === "cube.step", `Unexpected STEP filename ${downloaded.name}`);
          assert(downloaded.bytes.length === 19_030, `Expected 19,030 STEP bytes, got ${downloaded.bytes.length}`);
          const digest = createHash("sha256").update(downloaded.bytes).digest("hex");
          assert(digest === CUBE_SHA256, `Downloaded STEP hash drifted on ${link.slide}: ${digest}`);
          canonicalCube ||= downloaded.bytes;
        } else if (link.fixture === "machine-csv") {
          assert(downloaded.name === "proofshape-machine-import.csv", `Unexpected machine CSV filename ${downloaded.name}`);
          const machineText = downloaded.bytes.toString("utf8");
          assert(downloaded.bytes.length === 348, `Machine CSV byte count drifted: ${downloaded.bytes.length}`);
          assert(createHash("sha256").update(downloaded.bytes).digest("hex") === "dc96692c9729dd8c6856821ef26e86f6d3ec6f2ab3dc09a2f7c397b9de155306", "Machine CSV hash drifted");
          assert(machineText.startsWith("process,name,count,max_workpiece_kg,hourly_rate_usd,"), "Machine CSV header drifted");
          assert(machineText.includes("cnc_3axis,QA CNC Mill,1,200,95"), "Machine CSV valid row drifted");
          assert(machineText.includes("cnc_3axis,Broken row,not-a-number"), "Machine CSV rejected row drifted");
        } else if (link.fixture === "batch-zip") {
          assert(downloaded.name === "proofshape-one-part-batch.zip", `Unexpected batch ZIP filename ${downloaded.name}`);
          const entries = unzipSync(new Uint8Array(downloaded.bytes));
          assert(Object.keys(entries).join(",") === "cube.step", `Batch ZIP entries drifted: ${Object.keys(entries)}`);
          assert(createHash("sha256").update(Buffer.from(entries["cube.step"])).digest("hex") === CUBE_SHA256, "Batch ZIP cube hash drifted");
        } else {
          throw new Error(`Unknown embedded fixture control ${link.fixture}`);
        }
        embeddedEvidence.push({ ...link, name: downloaded.name, bytes: downloaded.bytes.length });
      }
      assert(canonicalCube, "No standalone canonical cube was downloaded");

      await page.goto(baseUrl, { waitUntil: "networkidle" });
      const staticLinks = await page.locator("[data-guide-fixture]").evaluateAll((links) => links.map((link) => ({
        name: link.dataset.guideFixture,
        slide: link.closest(".slide")?.dataset.id,
      })));
      const requiredStaticLinks = ["README.md", "wire-only-unmeshable.step", "sap-s4hana-sandbox.json", "windchill-sandbox.json", "parts-manifest-mixed.csv"];
      assert(sameSet(staticLinks.map((link) => link.name), requiredStaticLinks), `Static fixture controls drifted: ${JSON.stringify(staticLinks)}`);
      const staticEvidence = [];
      for (const link of staticLinks) {
        const contract = STATIC_FIXTURES[link.name];
        assert(contract, `No independent byte contract for linked fixture ${link.name}`);
        await page.goto(`${baseUrl}#slide=${encodeURIComponent(link.slide)}`, { waitUntil: "networkidle" });
        const downloaded = await downloadBytes(page, `[data-guide-fixture="${link.name}"]`);
        assert(downloaded.name === link.name, `Unexpected static fixture filename ${downloaded.name} for ${link.name}`);
        assert(downloaded.bytes.length === contract.bytes, `${link.name} byte count drifted: ${downloaded.bytes.length}`);
        const digest = createHash("sha256").update(downloaded.bytes).digest("hex");
        assert(digest === contract.sha256, `${link.name} SHA-256 drifted: ${digest}`);
        staticEvidence.push({ ...link, bytes: downloaded.bytes.length, sha256: digest });
      }
      return { fixtureControls: fixtureLinks.length + staticLinks.length, cubeSha256: CUBE_SHA256, embedded: embeddedEvidence, static: staticEvidence };
    });

    await record("every platform action opens its safe exact live target", async () => {
      const actionDeckUrl = urlWithApp(baseUrl, actionSink.origin);
      await page.goto(actionDeckUrl, { waitUntil: "networkidle" });
      const result = await page.evaluate(() => {
        const guide = window.__proofshapeGuide;
        const counts = new Map();
        const links = [...document.querySelectorAll("[data-app-path]")].map((link) => {
          const slide = link.closest(".slide")?.dataset.id;
          const index = counts.get(slide) || 0;
          counts.set(slide, index + 1);
          return { path: link.dataset.appPath, href: link.href, slide, index, tag: link.tagName, target: link.target, rel: link.rel };
        });
        return { appBase: guide.appBase, links };
      });
      assert(result.appBase === actionSink.origin, `Configured action sink drifted: ${result.appBase}`);
      assert(result.links.length > 10, `Expected broad action coverage, got ${result.links.length}`);
      for (const link of result.links) {
        assert(link.path.startsWith("/"), `Action is not root-relative: ${link.path}`);
        assert(link.href === `${result.appBase}${link.path}`, `Action href mismatch for ${link.path}: ${link.href}`);
        assert(link.tag === "A" && link.target === "_blank", `${link.slide} action ${link.path} is not an executable new-tab link`);
        assert(/\bnoopener\b/.test(link.rel) && /\bnoreferrer\b/.test(link.rel), `${link.slide} action ${link.path} lacks safe rel tokens`);
      }
      for (const expected of ["/verify?screen=catalog", "/verify?screen=triage", "/verify?screen=machines"]) {
        assert(result.links.some((link) => link.path === expected), `Missing workspace deep link ${expected}`);
      }
      const opened = [];
      for (const link of result.links) {
        await page.goto(`${actionDeckUrl}#slide=${encodeURIComponent(link.slide)}`, { waitUntil: "networkidle" });
        const control = page.locator(".slide.active [data-app-path]").nth(link.index);
        const [popup] = await Promise.all([
          page.waitForEvent("popup"),
          control.click(),
        ]);
        monitorPage(popup, consoleErrors, requestFailures, responseErrors);
        await popup.waitForLoadState("load");
        const actual = new URL(popup.url());
        const expected = new URL(link.path, actionSink.origin);
        assert(actual.origin === actionSink.origin, `${link.slide} opened an unexpected origin: ${actual.origin}`);
        assert(`${actual.pathname}${actual.search}${actual.hash}` === `${expected.pathname}${expected.search}${expected.hash}`, `${link.slide} opened ${actual.href}, expected ${expected.href}`);
        assert((await popup.locator("h1").innerText()) === `${expected.pathname}${expected.search}`, `${link.slide} target did not render the requested action`);
        opened.push({ slide: link.slide, path: link.path });
        await popup.close();
      }
      assert(actionSink.requests.length === result.links.length, `Action sink received ${actionSink.requests.length} requests for ${result.links.length} links`);
      return { appBase: result.appBase, linksInspected: result.links.length, linksOpened: opened.length };
    });

    await record("platform URL resolution handles separate host invalid input and direct file", async () => {
      await page.goto(baseUrl, { waitUntil: "networkidle" });
      assert(await page.evaluate(() => window.__proofshapeGuide.appBase) === "http://localhost:3000", "Locally served guide did not default platform actions to localhost:3000");
      await page.goto(`${baseUrl}?app=${encodeURIComponent("https://staging.proofshape.test/path")}`, { waitUntil: "networkidle" });
      assert(await page.evaluate(() => window.__proofshapeGuide.appBase) === "https://staging.proofshape.test", "Explicit separate-host app URL did not normalize to its origin");
      assert((await page.locator('[data-app-path="/login"]').getAttribute("href")) === "https://staging.proofshape.test/login", "Separate-host action link drifted");

      await page.goto(`${baseUrl}?app=${encodeURIComponent("javascript:alert(1)")}`, { waitUntil: "networkidle" });
      assert(await page.evaluate(() => window.__proofshapeGuide.appBase) === null, "Unsafe app protocol was accepted");
      assert(await page.locator("[data-needs-base]").count() > 0, "Invalid app URL did not disable platform actions");

      const fileContext = await browser.newContext({ viewport: { width: 1280, height: 720 }, reducedMotion: "reduce" });
      const filePage = await fileContext.newPage();
      monitorPage(filePage, consoleErrors, requestFailures, responseErrors);
      const guideFile = pathToFileURL(path.join(repoRoot, "docs", "training", "proofshape-platform-guide.html")).href;
      await filePage.goto(`${guideFile}#slide=access`, { waitUntil: "load" });
      await filePage.evaluate(() => localStorage.removeItem("proofshapePlatformBase"));
      await filePage.reload({ waitUntil: "load" });
      assert(await filePage.evaluate(() => window.__proofshapeGuide.appBase) === null, "Direct-file guide invented a platform origin");
      await filePage.locator(".slide.active [data-needs-base]").first().click();
      assert(await filePage.evaluate(() => document.activeElement?.id) === "platformBase", "Disabled direct-file action did not focus platform setup");
      await filePage.locator("#platformBase").fill("ftp://unsafe.example");
      await filePage.locator("#platformConfig").getByRole("button", { name: /Use this platform URL/i }).click();
      assert(/http:\/\/ or https:\/\//.test(await filePage.locator("#platformError").innerText()), "Invalid direct-file URL lacked recovery guidance");
      await filePage.locator("#platformBase").fill("https://staging.proofshape.test/workspace");
      await Promise.all([
        filePage.waitForEvent("load"),
        filePage.locator("#platformConfig").getByRole("button", { name: /Use this platform URL/i }).click(),
      ]);
      assert(await filePage.evaluate(() => window.__proofshapeGuide.appBase) === "https://staging.proofshape.test", "Direct-file platform configuration did not persist");
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
      const drawerFocusables = page.locator('#drawer button, #drawer input, #drawer select, #drawer a[href]');
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
      const imageTrigger = page.locator(".slide.active .image-trigger").first();
      await imageTrigger.focus();
      await page.keyboard.press("Enter");
      assert(await page.locator("#modal").evaluate((modal) => modal.classList.contains("open")), "Enter did not open evidence modal");
      await page.keyboard.press("Tab");
      assert(await page.evaluate(() => Boolean(document.activeElement?.closest?.("#modal"))), "Tab escaped evidence modal");
      await page.keyboard.press("Escape");
      assert(await page.locator("#modal").getAttribute("inert") !== null, "Closed modal is not inert");
      assert(await page.evaluate(() => document.activeElement?.matches?.(".slide.active .image-trigger")), "Modal Escape did not restore image focus");
      await page.keyboard.press("Space");
      assert(await page.locator("#modal").evaluate((modal) => modal.classList.contains("open")), "Space did not reopen evidence modal");
      await page.keyboard.press("Escape");
      await imageTrigger.click();
      await page.locator("#modal").click({ position: { x: 5, y: 5 } });
      assert(!await page.locator("#modal").evaluate((modal) => modal.classList.contains("open")), "Modal backdrop did not close the dialog");
      return { checklist: "Space + focus retained", drawer: "Tab/Shift+Tab/Escape", modal: "Enter/Space/Tab/Escape/backdrop" };
    });

    await record("all desktop slides render with reachable evidence and no horizontal clipping", async () => {
      await page.goto(baseUrl, { waitUntil: "networkidle" });
      const states = [];
      const badgeByScope = {
        local: /LOCAL GOLDEN PATH · RUN EVIDENCE/,
        mixed: /LOCAL \+ STAGING GATE/,
        external: /EXTERNAL STAGING REQUIRED/,
        unsupported: /UNSUPPORTED · SAFE FALLBACK/,
      };
      const headingByScope = {
        local: "Golden-path result",
        mixed: "Local proof / staging gate",
        external: "Staging acceptance",
        unsupported: "Supported boundary",
      };
      for (let i = 0; i < EXPECTED_SLIDES; i += 1) {
        await waitForActiveImages(page);
        const state = await activeState(page);
        assert(!state.horizontalOverflow, `${state.id} has horizontal overflow (${state.scrollWidth} > ${state.clientWidth})`);
        assert(!state.verticalOverflow || ["auto", "scroll"].includes(state.overflowY), `${state.id} clips vertical content instead of scrolling`);
        assert(state.expectedHeading === headingByScope[state.proofScope], `${state.id} expected heading does not distinguish ${state.proofScope}`);
        assert(state.images.every((image) => image.loaded), `${state.id} has an unloaded image`);
        assert(badgeByScope[state.proofScope]?.test(state.validationBadge || ""), `${state.id} badge does not honestly label ${state.proofScope}: ${state.validationBadge}`);
        assert(!/CURRENT BUILD|LOCAL BUILD|BOUNDARY VERIFIED/.test(state.validationBadge || ""), `${state.id} self-certified without a clean current-build release report`);
        const evidence = page.locator(".slide.active details.evidence");
        await evidence.scrollIntoViewIfNeeded();
        assert(await evidence.isVisible(), `${state.id} evidence is not reachable`);
        await page.locator(".slide.active").evaluate((slide) => { slide.scrollTop = 0; });
        const file = path.join(screenshotDir, `slide-${String(i + 1).padStart(2, "0")}-${state.id}.png`);
        await page.screenshot({ path: file });
        screenshots.push(file);
        states.push({ id: state.id, images: state.images.length, validationBadge: state.validationBadge, proofScope: state.proofScope, level: state.level });
        if (i < EXPECTED_SLIDES - 1) await page.keyboard.press("ArrowRight");
      }
      assert((await page.locator("#counter").innerText()).trim() === `${EXPECTED_SLIDES} / ${EXPECTED_SLIDES}`, `Did not reach slide ${EXPECTED_SLIDES}`);
      for (const scope of Object.keys(badgeByScope)) assert(states.some((state) => state.proofScope === scope), `Deck has no ${scope} proof scope`);
      const source = await page.content();
      assert(!/64\s*\/\s*64/.test(source), "Deck self-certifies with an unearned 64/64 claim");
      assert(/exact clean-build LOCAL_GATE_PASS report/i.test(source), "Finish gate does not require an exact clean-build report");
      return { slides: states.length, ids: states.map((state) => state.id), scopes: Object.fromEntries(Object.keys(badgeByScope).map((scope) => [scope, states.filter((state) => state.proofScope === scope).length])) };
    });

    await record(`all ${EXPECTED_SLIDES} mobile slides remain usable at 375 by 812 with touch navigation`, async () => {
      const mobile = await browser.newContext({ viewport: { width: 375, height: 812 }, reducedMotion: "reduce", hasTouch: true });
      const mobilePage = await mobile.newPage();
      monitorPage(mobilePage, consoleErrors, requestFailures, responseErrors);
      await mobilePage.goto(baseUrl, { waitUntil: "networkidle" });
      await mobilePage.dispatchEvent("#deck", "pointerdown", { pointerType: "touch", pointerId: 1, isPrimary: true, clientX: 330, clientY: 400 });
      await mobilePage.dispatchEvent("#deck", "pointerup", { pointerType: "touch", pointerId: 1, isPrimary: true, clientX: 70, clientY: 400 });
      assert((await activeState(mobilePage)).id === slideIds[1], "Left touch swipe did not advance");
      await mobilePage.dispatchEvent("#deck", "pointerdown", { pointerType: "touch", pointerId: 2, isPrimary: true, clientX: 70, clientY: 400 });
      await mobilePage.dispatchEvent("#deck", "pointerup", { pointerType: "touch", pointerId: 2, isPrimary: true, clientX: 330, clientY: 400 });
      assert((await activeState(mobilePage)).id === slideIds[0], "Right touch swipe did not return");
      const mobileStates = [];
      for (let i = 0; i < EXPECTED_SLIDES; i += 1) {
        await waitForActiveImages(mobilePage);
        const state = await activeState(mobilePage);
        const documentOverflow = await mobilePage.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
        assert(!documentOverflow, `${state.id} creates mobile document overflow`);
        assert(!state.horizontalOverflow, `${state.id} has mobile horizontal clipping`);
        assert(/LOCAL GOLDEN PATH|LOCAL \+ STAGING GATE|EXTERNAL STAGING REQUIRED|UNSUPPORTED · SAFE FALLBACK/.test(state.validationBadge || ""), `${state.id} lacks an honest mobile validation badge`);
        const controls = await mobilePage.locator(".slide.active button, .slide.active a").evaluateAll((elements) => elements.map((element) => {
          const rect = element.getBoundingClientRect();
          return { label: element.textContent?.trim() || element.getAttribute("aria-label"), width: rect.width, height: rect.height };
        }));
        for (const control of controls) {
          assert(control.width >= 43 && control.height >= 43, `${state.id} control is not touch-sized: ${JSON.stringify(control)}`);
        }
        const evidence = mobilePage.locator(".slide.active details.evidence");
        await evidence.scrollIntoViewIfNeeded();
        assert(await evidence.isVisible(), `${state.id} evidence is unreachable on mobile`);
        await mobilePage.locator(".slide.active").evaluate((slide) => { slide.scrollTop = 0; });
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
      return { width: 375, height: 812, slides: mobileStates.length, controls: mobileStates.reduce((sum, state) => sum + state.controls, 0), swipe: "left/right" };
    });

    await record("public evaluator remains complete at the canonical 390 px width", async () => {
      const publicMobile = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce", hasTouch: true });
      const publicPage = await publicMobile.newPage();
      monitorPage(publicPage, consoleErrors, requestFailures, responseErrors);
      await publicPage.goto(`${baseUrl}#slide=public-evaluator`, { waitUntil: "networkidle" });
      const state = await activeState(publicPage);
      const documentOverflow = await publicPage.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      assert(!documentOverflow && !state.horizontalOverflow, "Public evaluator path overflows at 390 px");
      assert(await publicPage.locator('.slide.active [data-app-path="/company#pilot"]').count() === 1, "390 px public path lost the pilot action");
      await publicPage.locator("#menuBtn").click();
      assert(await publicPage.locator("#guideSearch").isVisible(), "390 px use-case search is unreachable");
      await publicPage.keyboard.press("Escape");
      await publicMobile.close();
      return { width: 390, slide: state.id, pilotAction: true };
    });

    await record(`all ${EXPECTED_SLIDES} tablet slides remain usable at 768 by 1024`, async () => {
      const tablet = await browser.newContext({ viewport: { width: 768, height: 1024 }, reducedMotion: "reduce", hasTouch: true });
      const tabletPage = await tablet.newPage();
      monitorPage(tabletPage, consoleErrors, requestFailures, responseErrors);
      await tabletPage.goto(baseUrl, { waitUntil: "networkidle" });
      const ids = [];
      for (let i = 0; i < EXPECTED_SLIDES; i += 1) {
        await waitForActiveImages(tabletPage);
        const state = await activeState(tabletPage);
        const documentOverflow = await tabletPage.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
        assert(!documentOverflow, `${state.id} creates tablet document overflow`);
        assert(!state.horizontalOverflow, `${state.id} has tablet horizontal clipping`);
        assert(!state.verticalOverflow || ["auto", "scroll"].includes(state.overflowY), `${state.id} clips tablet vertical content`);
        const evidence = tabletPage.locator(".slide.active details.evidence");
        await evidence.scrollIntoViewIfNeeded();
        assert(await evidence.isVisible(), `${state.id} evidence is unreachable at 768 px`);
        ids.push(state.id);
        if (i < EXPECTED_SLIDES - 1) await tabletPage.locator("#nextBtn").click();
      }
      assert(sameSet(ids, slideIds), "Tablet traversal missed or duplicated a slide");
      await tablet.close();
      return { width: 768, height: 1024, slides: ids.length };
    });

    assert(consoleErrors.length === 0, `Console errors: ${JSON.stringify(consoleErrors)}`);
    assert(requestFailures.length === 0, `Request failures: ${JSON.stringify(requestFailures)}`);
    assert(responseErrors.length === 0, `HTTP response errors: ${JSON.stringify(responseErrors)}`);
    await context.close();
  } catch (error) {
    fatalError = error;
  } finally {
    await browser.close();
    if (localServer) await new Promise((resolve) => localServer.server.close(resolve));
    await new Promise((resolve) => actionSink.server.close(resolve));
  }

  const mappingCheck = checks.find((check) => check.name.startsWith("every claim maps"));
  const fixtureCheck = checks.find((check) => check.name.startsWith("every fixture link"));
  const report = {
    runId,
    url: baseUrl,
    status: !fatalError && checks.every((check) => check.status === "PASS") && consoleErrors.length === 0 && requestFailures.length === 0 && responseErrors.length === 0 ? "PASS" : "FAIL",
    fatalError: fatalError instanceof Error ? fatalError.message : fatalError ? String(fatalError) : null,
    gitHead,
    clean: !gitDirty,
    servedBuilds,
    goldenPathContract: {
      source: path.relative(repoRoot, GOLDEN_PATHS_FILE),
      local: goldenContract.localIds.length,
      external: goldenContract.externalIds.length,
      failures: goldenContract.failureIds.length,
      mappingStatus: mappingCheck?.status || "NOT_RUN",
    },
    fixtures: fixtureCheck?.status === "PASS" ? { "cube-step": CUBE_SHA256 } : {},
    slideEvidence: Object.fromEntries(slideIds.map((id) => [id, {
      status: checks.some((check) => check.status === "PASS" && check.name.startsWith("all desktop")) ? "PASS" : "NOT_RUN",
      contracts: slideContracts[id] || [],
      checks: checks.filter((check) => check.status === "PASS" && (/all desktop|all 53 mobile|all 53 tablet/.test(check.name))).map((check) => check.name),
    }])),
    checks,
    consoleErrors,
    requestFailures,
    responseErrors,
    screenshots,
  };
  await writeFile(reportJson, `${JSON.stringify(report, null, 2)}\n`);
  const lines = [
    `# ProofShape interactive training deck QA — ${runId}`,
    "",
    `**Status:** ${report.status}`,
    `**Surface:** ${baseUrl}`,
    `**Slides:** ${EXPECTED_SLIDES} desktop + 375/390 px mobile + 768 px tablet`,
    `**Console errors:** ${consoleErrors.length}`,
    `**Request failures:** ${requestFailures.length}`,
    `**HTTP response errors:** ${responseErrors.length}`,
    `**Canonical contract:** ${goldenContract.localIds.length} local / ${goldenContract.externalIds.length} external / ${goldenContract.failureIds.length} recoveries`,
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
  console.log(JSON.stringify({ status: report.status, checks: checks.length, consoleErrors: consoleErrors.length, requestFailures: requestFailures.length, responseErrors: responseErrors.length, screenshots: screenshots.length, screenshotDir, reportMd }, null, 2));
  if (fatalError) throw fatalError;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
