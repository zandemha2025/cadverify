import { createRequire } from "node:module";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const baseUrl = process.env.APP_URL || "http://localhost:3000";
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const screenshotDir = path.join(outputRoot, "screenshots", `site-design-fidelity-${runId}`);
const artifacts = {
  json: path.join(outputRoot, `site-design-fidelity-${runId}.json`),
  md: path.join(outputRoot, `qa-report-site-design-fidelity-${runId}.md`),
};

const launchOptions = {
  channel: "chrome",
  headless: true,
  args: process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : [],
};

const routeSpecs = [
  {
    route: "/",
    design: "Direction - Cinematic.dc.html",
    title: "Home / Direction - Cinematic",
    signals: [
      /Every part arrives\s+with a question\./i,
      /The decision, live\./i,
      /The governed decision layer\s+for everything you make\./i,
      /verification, made of glass/i,
    ],
  },
  {
    route: "/method",
    design: "Method.dc.html",
    title: "Method",
    signals: [/One file in\.\s+The whole model out\./i, /Measure the geometry\./i, /±40%/i],
  },
  {
    route: "/platform",
    design: "Platform.dc.html",
    title: "Platform",
    signals: [
      /The governed decision layer for everything you make\./i,
      /A copilot that cannot hallucinate a number\./i,
      /Every part knows where it lives\./i,
    ],
  },
  {
    route: "/teams",
    design: "Teams.dc.html",
    title: "Teams",
    signals: [
      /One record\.\s+Five people who have to defend it\./i,
      /Can WE make this/i,
      /Same number\. Every lens\. No versions of the truth\./i,
    ],
  },
  {
    route: "/teams/in-house-manufacturing",
    design: "For In-House Manufacturing.dc.html",
    title: "For In-House Manufacturing",
    signals: [/Can WE make this/i, /Declare the floor once/i, /Bring the part your supplier abandoned/i],
  },
  {
    route: "/teams/cost-engineering",
    design: "For Cost Engineering.dc.html",
    title: "For Cost Engineering",
    signals: [
      /You sign the number\.\s+You should be able to open it\./i,
      /A part lands\.\s+Twelve seconds later/i,
      /Bring the part your last review argued about\./i,
    ],
  },
  {
    route: "/teams/design-engineering",
    design: "For Design Engineering.dc.html",
    title: "For Design Engineering",
    signals: [/The verdict,\s+while you design\./i, /The DFM check names things\./i, /Watch the route unlock\./i],
  },
  {
    route: "/teams/sourcing",
    design: "For Sourcing.dc.html",
    title: "For Sourcing",
    signals: [/Make it, buy it, or\s+build the capability\?/i, /Three options\.\s+One computed answer\./i],
  },
  {
    route: "/teams/shop-owners",
    design: "For Shop Owners.dc.html",
    title: "For Shop Owners",
    signals: [/Your floor,\s+fully indexed\./i, /It(?:'|’)s an afternoon, not an implementation\./i],
  },
  {
    route: "/security",
    design: "Security.dc.html",
    title: "Security",
    signals: [/Your CAD is the crown jewels\./i, /SOC 2 Type II/i, /Pen test — scheduled pre-GA/i],
  },
  {
    route: "/developers",
    design: "Developers.dc.html",
    title: "Developers",
    signals: [/The engine is an API\./i, /One request, the whole report\./i, /\/validate\/cost/i],
  },
  {
    route: "/company",
    design: "Company.dc.html",
    title: "Company",
    signals: [
      /Manufacturing runs on numbers nobody can check\./i,
      /Don't take our word for it\./i,
      /Request a pilot/i,
    ],
  },
];

const desktopNavSignals = [
  /ProofShape/i,
  /Method/i,
  /Platform/i,
  /Teams/i,
  /Security/i,
  /Developers/i,
  /Company/i,
  /Request a pilot/i,
];

const forbiddenVisiblePatterns = [
  /\bCadVerify\b/i,
  /\bunder construction\b/i,
  /\bcoming soon\b/i,
  /\bnot implemented\b/i,
  /\bnot yet implemented\b/i,
  /\bTODO\b/i,
  /\bTBD\b/i,
  /\bstub\b/i,
  /\bmock(?:ed|up)?\b/i,
  /\bplaceholder\b/i,
  /\bpartial(?:ly)?\b/i,
  /should-cost,\s*made of glass/i,
  /Every part knows what it should cost/i,
  /Pen test\s+—\s+annual/i,
];

function htmlToText(source) {
  return source
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&mdash;/g, "—")
    .replace(/&ldquo;|&rdquo;/g, "\"")
    .replace(/&#39;|&apos;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function slug(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 90);
}

function firstMatch(text, regex) {
  const match = text.match(regex);
  if (!match || match.index == null) return null;
  const start = Math.max(0, match.index - 70);
  const end = Math.min(text.length, match.index + match[0].length + 110);
  return text.slice(start, end).replace(/\s+/g, " ").trim();
}

function isIgnorableRequestFailure(url, method, failure) {
  if (/favicon\.ico|vercel\/speed-insights|\/_next\/webpack-hmr/i.test(url)) return true;
  if (failure !== "net::ERR_ABORTED") return false;
  if (/[?&]_rsc=/.test(url)) return true;
  return method === "GET" && /\/_next\/static\/chunks\/[^/?]+\.js(?:\?|$)/.test(url);
}

class SiteDesignFidelity {
  constructor() {
    this.steps = [];
    this.issues = [];
    this.consoleErrors = [];
    this.requestFailures = [];
    this.evidence = {};
  }

  async init() {
    await mkdir(screenshotDir, { recursive: true });
    try {
      this.browser = await pw.chromium.launch(launchOptions);
    } catch {
      this.browser = await pw.chromium.launch({
        headless: true,
        args: launchOptions.args,
      });
    }
    this.context = await this.browser.newContext({
      baseURL: baseUrl,
      viewport: { width: 1440, height: 960 },
      reducedMotion: "reduce",
    });
    this.page = await this.context.newPage();
    this.page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const text = msg.text();
      if (!/favicon\.ico|ResizeObserver loop limit exceeded/i.test(text)) {
        this.consoleErrors.push({ url: this.page.url(), text });
      }
    });
    this.page.on("pageerror", (err) => {
      this.consoleErrors.push({ url: this.page.url(), text: err.message });
    });
    this.page.on("requestfailed", (request) => {
      const url = request.url();
      const failure = request.failure()?.errorText || "request failed";
      if (!isIgnorableRequestFailure(url, request.method(), failure)) {
        this.requestFailures.push({ url, method: request.method(), error: failure });
      }
    });
  }

  async close() {
    await this.browser?.close();
  }

  issue(severity, title, detail, screenshot = null) {
    this.issues.push({ severity, title, detail, screenshot, url: this.page?.url?.() || "" });
  }

  async shot(name, fullPage = false) {
    const file = path.join(screenshotDir, `${String(this.steps.length + 1).padStart(2, "0")}-${slug(name)}.png`);
    await this.page.screenshot({ path: file, fullPage, animations: "disabled", caret: "initial" });
    return file;
  }

  async step(name, fn) {
    const started = Date.now();
    try {
      const out = await fn();
      const screenshot = out?.screenshot || (await this.shot(name));
      this.steps.push({ name, status: "pass", ms: Date.now() - started, screenshot, url: this.page.url() });
      return out;
    } catch (error) {
      let screenshot = null;
      try {
        screenshot = await this.shot(`${name}-failure`, true);
      } catch {}
      this.steps.push({
        name,
        status: "fail",
        ms: Date.now() - started,
        screenshot,
        url: this.page.url(),
        error: error instanceof Error ? error.message : String(error),
      });
      this.issue("high", `Step failed: ${name}`, error instanceof Error ? error.message : String(error), screenshot);
      return null;
    }
  }

  async visibleText() {
    return this.page.locator("body").innerText({ timeout: 10_000 });
  }

  async assertNoForbiddenCopy(label) {
    const text = await this.visibleText();
    for (const pattern of forbiddenVisiblePatterns) {
      const excerpt = firstMatch(text, pattern);
      if (excerpt) {
        const screenshot = await this.shot(`${label}-forbidden-copy`, true);
        this.issue("medium", `Visible non-final or superseded copy on ${label}`, `Matched ${pattern}: "${excerpt}"`, screenshot);
      }
    }
    return text;
  }

  async assertDarkTheater() {
    const theater = await this.page.evaluate(() => {
      const el = document.querySelector(".site-theater");
      const style = el ? getComputedStyle(el) : null;
      const overlay = /Next\.js|Runtime Error|Unhandled Runtime Error|Build Error/i.test(document.body.innerText);
      return {
        hasSiteTheater: Boolean(el),
        background: style?.backgroundColor || "",
        color: style?.color || "",
        hasFrameworkOverlay: overlay,
      };
    });
    assert(theater.hasSiteTheater, "missing .site-theater dark-register wrapper");
    assert(/rgb\(5,\s*5,\s*6\)|#050506/i.test(theater.background), `wrong site background: ${theater.background}`);
    assert(!theater.hasFrameworkOverlay, "framework error overlay visible");
    return theater;
  }

  async verifyRoute(spec) {
    await this.step(`Claude site design route ${spec.route}`, async () => {
      const designFile = path.join(repoRoot, "handoff_cadverify_2026-07-04", "site", spec.design);
      const sourceText = htmlToText(await readFile(designFile, "utf8"));
      for (const signal of spec.signals) {
        assert(signal.test(sourceText), `${spec.design} does not contain expected design signal ${signal}`);
      }

      const res = await this.page.goto(spec.route, { waitUntil: "domcontentloaded", timeout: 30_000 });
      await this.page.waitForLoadState("networkidle", { timeout: 6_000 }).catch(() => {});
      assert((res?.status() || 0) < 400, `${spec.route} returned HTTP ${res?.status()}`);
      const theater = await this.assertDarkTheater();
      const text = await this.assertNoForbiddenCopy(spec.route);
      for (const signal of [...desktopNavSignals, ...spec.signals]) {
        assert(signal.test(text), `${spec.route} missing rendered signal ${signal}`);
      }
      const screenshot = await this.shot(`desktop-${spec.title}`, true);
      const fileStat = await stat(screenshot);
      assert(fileStat.size > 20_000, `${spec.route} screenshot too small to prove render (${fileStat.size} bytes)`);
      this.evidence[spec.route] = {
        design: path.relative(repoRoot, designFile),
        title: spec.title,
        background: theater.background,
        screenshot,
        bytes: fileStat.size,
      };
      return { screenshot };
    });
  }

  async verifyMobileSample(spec) {
    await this.step(`Claude site mobile route ${spec.route}`, async () => {
      await this.page.setViewportSize({ width: 390, height: 844 });
      const res = await this.page.goto(spec.route, { waitUntil: "domcontentloaded", timeout: 30_000 });
      await this.page.waitForLoadState("networkidle", { timeout: 6_000 }).catch(() => {});
      assert((res?.status() || 0) < 400, `${spec.route} mobile returned HTTP ${res?.status()}`);
      const theater = await this.assertDarkTheater();
      const text = await this.assertNoForbiddenCopy(`${spec.route} mobile`);
      for (const signal of spec.signals.slice(0, 2)) {
        assert(signal.test(text), `${spec.route} mobile missing rendered signal ${signal}`);
      }
      const overflow = await this.page.evaluate(() => {
        const root = document.documentElement;
        return Math.max(0, root.scrollWidth - root.clientWidth);
      });
      assert(overflow <= 2, `${spec.route} mobile has horizontal overflow ${overflow}px`);
      const screenshot = await this.shot(`mobile-${spec.title}`, true);
      const fileStat = await stat(screenshot);
      assert(fileStat.size > 15_000, `${spec.route} mobile screenshot too small (${fileStat.size} bytes)`);
      this.evidence[`${spec.route} mobile`] = {
        design: spec.design,
        background: theater.background,
        screenshot,
        bytes: fileStat.size,
        horizontalOverflowPx: overflow,
      };
      await this.page.setViewportSize({ width: 1440, height: 960 });
      return { screenshot };
    });
  }

  async finish() {
    if (this.consoleErrors.length > 0) {
      this.issue(
        "medium",
        "Browser console errors occurred during Claude site fidelity QA",
        this.consoleErrors.slice(0, 8).map((e) => `${e.url}: ${e.text}`).join("\n")
      );
    }
    if (this.requestFailures.length > 0) {
      this.issue(
        "medium",
        "Network request failures occurred during Claude site fidelity QA",
        this.requestFailures.slice(0, 8).map((e) => `${e.method} ${e.url}: ${e.error}`).join("\n")
      );
    }
    const failedSteps = this.steps.filter((step) => step.status === "fail").length;
    const blocking = this.issues.filter((issue) => ["critical", "high", "medium"].includes(issue.severity));
    const data = {
      status: failedSteps === 0 && blocking.length === 0 ? "PASS" : "NEEDS_FIXES",
      generatedAt: new Date().toISOString(),
      runId,
      baseUrl,
      designRoot: path.join(repoRoot, "handoff_cadverify_2026-07-04", "site"),
      screenshotDir,
      steps: this.steps,
      issues: this.issues,
      consoleErrors: this.consoleErrors,
      requestFailures: this.requestFailures,
      evidence: this.evidence,
      boundary:
        "This gate proves the production Next website routes render the accepted Claude dark-theater site design signals. It is not a pixel-perfect computer-vision diff of every CSS value.",
    };
    await mkdir(outputRoot, { recursive: true });
    await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
    await writeFile(artifacts.md, markdown(data));
    console.log(
      JSON.stringify(
        {
          status: data.status,
          routes: routeSpecs.length,
          steps: this.steps.length,
          failedSteps,
          issues: this.issues.length,
          report: artifacts.md,
          screenshots: screenshotDir,
        },
        null,
        2
      )
    );
    if (data.status !== "PASS") process.exitCode = 1;
  }
}

function markdown(data) {
  const rows = data.steps
    .map((step) => `| ${step.status === "pass" ? "PASS" : "FAIL"} | ${step.name} | ${step.url} | ${step.screenshot || ""} | ${step.error || "pass"} |`)
    .join("\n");
  const issues = data.issues.length
    ? data.issues.map((issue) => `- **${issue.severity.toUpperCase()}** ${issue.title}: ${issue.detail}`).join("\n")
    : "No medium-or-higher issues found.";

  return `# Claude Site Design Fidelity

- Date: ${data.runId}
- Status: ${data.status}
- Target: ${data.baseUrl}
- Accepted design root: ${data.designRoot}
- Screenshots: ${data.screenshotDir}
- Boundary: ${data.boundary}

## Issues

${issues}

## Steps

| Result | Step | URL | Screenshot | Evidence |
| --- | --- | --- | --- | --- |
${rows}
`;
}

const runner = new SiteDesignFidelity();
try {
  await runner.init();
  for (const spec of routeSpecs) {
    await runner.verifyRoute(spec);
  }
  for (const spec of routeSpecs.filter((item) => ["/", "/platform", "/teams", "/security"].includes(item.route))) {
    await runner.verifyMobileSample(spec);
  }
} finally {
  await runner.finish().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
  await runner.close().catch(() => {});
}
