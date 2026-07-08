import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const pw = require("playwright-core");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const screenshotDir = path.join(outputRoot, "screenshots", `assembly-visual-fidelity-${runId}`);
const fixtureDir = path.join(repoRoot, "scripts", "e2e", "fixtures");
const fixtureOverride = process.env.ASSEMBLY_FIXTURE ? path.resolve(process.env.ASSEMBLY_FIXTURE) : "";
const threeRoot = path.dirname(path.dirname(require.resolve("three")));

const artifacts = {
  json: path.join(outputRoot, `assembly-visual-fidelity-${runId}.json`),
  md: path.join(outputRoot, `qa-report-assembly-visual-fidelity-${runId}.md`),
};

const launchOptions = {
  channel: "chrome",
  headless: true,
  args: [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--use-angle=swiftshader",
    "--use-gl=angle",
  ],
};

function assert(condition, detail) {
  if (!condition) throw new Error(detail);
}

function slug(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 90);
}

function approxEqual(a, b, tolerance = 0.01) {
  return Math.abs(a - b) <= tolerance;
}

function json(res, status, body) {
  const payload = Buffer.from(`${JSON.stringify(body, null, 2)}\n`);
  res.writeHead(status, {
    "cache-control": "no-store",
    "content-length": String(payload.length),
    "content-type": "application/json; charset=utf-8",
  });
  res.end(payload);
}

function text(res, status, body, contentType = "text/plain; charset=utf-8") {
  const payload = Buffer.from(body);
  res.writeHead(status, {
    "cache-control": "no-store",
    "content-length": String(payload.length),
    "content-type": contentType,
  });
  res.end(payload);
}

function contentTypeFor(filename) {
  if (filename.endsWith(".js") || filename.endsWith(".mjs")) return "text/javascript; charset=utf-8";
  if (filename.endsWith(".json")) return "application/json; charset=utf-8";
  if (filename.endsWith(".wasm")) return "application/wasm";
  return "application/octet-stream";
}

function makeHtml(fixtureHash) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>CadVerify Assembly Visual Fidelity Fixture</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #eef1f4;
      color: #17202a;
    }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: radial-gradient(circle at 50% 18%, #ffffff 0%, #eef1f4 54%, #d9dee5 100%);
    }
    #shell {
      width: 1040px;
      max-width: calc(100vw - 32px);
      border: 1px solid #c6ced8;
      background: #f9fafb;
      box-shadow: 0 24px 80px rgba(22, 34, 48, 0.2);
    }
    header {
      display: flex;
      justify-content: space-between;
      gap: 24px;
      padding: 14px 18px;
      border-bottom: 1px solid #d7dde5;
      font-size: 12px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #516174;
    }
    #stage {
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 9;
      overflow: hidden;
      background: #f2f4f7;
    }
    canvas {
      display: block;
      width: 100%;
      height: 100%;
    }
    #hud {
      position: absolute;
      left: 18px;
      bottom: 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      color: #f9fafb;
      text-shadow: 0 1px 12px rgba(0, 0, 0, 0.65);
      font-size: 13px;
    }
    button {
      appearance: none;
      border: 1px solid rgba(255, 255, 255, 0.78);
      background: rgba(14, 20, 28, 0.86);
      color: #ffffff;
      padding: 9px 14px;
      border-radius: 6px;
      font: inherit;
      cursor: pointer;
    }
    button:focus-visible {
      outline: 2px solid #1b66d2;
      outline-offset: 2px;
    }
  </style>
  <script type="importmap">
    {"imports":{"three":"/node_modules/three/build/three.module.js"}}
  </script>
</head>
<body>
  <div id="shell">
    <header>
      <span>CadVerify QA assembly fixture</span>
      <span id="status">exploded preview</span>
    </header>
    <div id="stage" data-testid="assembly-visual-stage">
      <div id="hud">
        <button id="seat" type="button">Seat handle in door</button>
      <span id="readout">loading assembly context</span>
      </div>
    </div>
  </div>
  <script type="module">
    import * as THREE from "three";

    const SCALE = 0.01;
    const fixtureHash = ${JSON.stringify(fixtureHash)};
    const fixture = await fetch("/fixture.json").then((res) => res.json());
    const stage = document.getElementById("stage");
    const status = document.getElementById("status");
    const readout = document.getElementById("readout");
    const seatButton = document.getElementById("seat");
    readout.textContent = fixture.parentAssembly.id + " / " + fixture.part.id;
    seatButton.textContent = "Seat " + fixture.part.kind + " in " + fixture.parentAssembly.kind;

    const mm = (value) => value * SCALE;
    const v3 = (arr) => new THREE.Vector3(mm(arr[0]), mm(arr[1]), mm(arr[2]));
    const deg = (value) => (value * Math.PI) / 180;

    const width = 960;
    const height = 540;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#f2f4f7");

    const camera = new THREE.PerspectiveCamera(29, width / height, 0.05, 80);
    camera.position.set(4.2, -3.2, 10.4);
    camera.lookAt(2.15, -1.15, 0.3);

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      preserveDrawingBuffer: true,
      powerPreference: "high-performance"
    });
    renderer.setPixelRatio(1);
    renderer.setSize(width, height, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    stage.prepend(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x708090, 1.25));
    const key = new THREE.DirectionalLight(0xffffff, 2.7);
    key.position.set(1.8, 4.8, 7.5);
    key.castShadow = true;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xbfd7ef, 1.25);
    rim.position.set(-4.5, -2.4, 5.5);
    scene.add(rim);

    const doorDims = fixture.parentAssembly.dimensionsMm;
    const door = new THREE.Mesh(
      new THREE.BoxGeometry(mm(doorDims.width), mm(doorDims.height), mm(doorDims.thickness)),
      new THREE.MeshStandardMaterial({
        color: "#45647c",
        metalness: 0.35,
        roughness: 0.55
      })
    );
    door.name = fixture.parentAssembly.id;
    door.receiveShadow = true;
    scene.add(door);

    const doorEdges = new THREE.LineSegments(
      new THREE.EdgesGeometry(door.geometry),
      new THREE.LineBasicMaterial({ color: "#233647", transparent: true, opacity: 0.45 })
    );
    scene.add(doorEdges);

    const recess = fixture.parentAssembly.recess;
    const recessMesh = new THREE.Mesh(
      new THREE.BoxGeometry(mm(recess.dimensionsMm[0]), mm(recess.dimensionsMm[1]), mm(recess.dimensionsMm[2])),
      new THREE.MeshStandardMaterial({
        color: "#263f54",
        metalness: 0.18,
        roughness: 0.68
      })
    );
    recessMesh.name = recess.id;
    recessMesh.position.copy(v3(recess.centerMm));
    recessMesh.castShadow = false;
    recessMesh.receiveShadow = true;
    scene.add(recessMesh);

    const mountMaterial = new THREE.MeshStandardMaterial({
      color: "#e9c566",
      metalness: 0.55,
      roughness: 0.38
    });
    for (const anchor of fixture.parentAssembly.mountAnchors) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(0.045, 20, 16), mountMaterial);
      marker.name = "parent-anchor-" + anchor.id;
      marker.position.copy(v3(anchor.positionMm));
      marker.castShadow = true;
      scene.add(marker);
    }

    const handle = new THREE.Group();
    handle.name = fixture.part.id;
    const partDims = fixture.part.dimensionsMm;
    const handleMaterial = new THREE.MeshStandardMaterial({
      color: "#15181d",
      metalness: 0.28,
      roughness: 0.28
    });
    const bossMaterial = new THREE.MeshStandardMaterial({
      color: "#30343b",
      metalness: 0.42,
      roughness: 0.36
    });

    const grip = new THREE.Mesh(
      new THREE.BoxGeometry(mm(partDims.length - 24), mm(22), mm(28)),
      handleMaterial
    );
    grip.castShadow = true;
    handle.add(grip);

    for (const side of [-1, 1]) {
      const cap = new THREE.Mesh(new THREE.CapsuleGeometry(mm(18), mm(10), 8, 18), handleMaterial);
      cap.rotation.z = Math.PI / 2;
      cap.position.x = side * mm((partDims.length - 24) / 2);
      cap.castShadow = true;
      handle.add(cap);
    }

    for (const anchor of fixture.part.localAnchors) {
      const boss = new THREE.Mesh(new THREE.CylinderGeometry(mm(8), mm(8), mm(16), 24), bossMaterial);
      boss.rotation.x = Math.PI / 2;
      boss.position.copy(v3(anchor.positionMm));
      boss.castShadow = true;
      handle.add(boss);
    }

    const highlight = new THREE.Mesh(
      new THREE.BoxGeometry(mm(partDims.length), mm(partDims.height), mm(3)),
      new THREE.MeshStandardMaterial({
        color: "#ffffff",
        transparent: true,
        opacity: 0.12,
        metalness: 0,
        roughness: 0.22
      })
    );
    highlight.position.z = mm(partDims.depth / 2 + 1.5);
    handle.add(highlight);
    scene.add(handle);

    function poseVector(seated) {
      const base = fixture.partToParentTransform.translationMm;
      const offset = seated ? [0, 0, 0] : fixture.cinematicExpectations.explodedOffsetMm;
      return v3([base[0] + offset[0], base[1] + offset[1], base[2] + offset[2]]);
    }

    function applyPose(seated) {
      handle.position.copy(poseVector(seated));
      handle.rotation.set(
        deg(fixture.partToParentTransform.rotationDeg[0]),
        deg(fixture.partToParentTransform.rotationDeg[1]),
        deg(fixture.partToParentTransform.rotationDeg[2])
      );
      handle.updateMatrixWorld(true);
      status.textContent = seated ? "seated and verified" : "exploded preview";
    }

    function transformPointMm(pointMm) {
      const v = new THREE.Vector3(pointMm[0], pointMm[1], pointMm[2]);
      v.applyEuler(
        new THREE.Euler(
          deg(fixture.partToParentTransform.rotationDeg[0]),
          deg(fixture.partToParentTransform.rotationDeg[1]),
          deg(fixture.partToParentTransform.rotationDeg[2]),
          "XYZ"
        )
      );
      v.add(new THREE.Vector3(...fixture.partToParentTransform.translationMm));
      return [v.x, v.y, v.z];
    }

    function distMm(a, b) {
      return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    }

    function placementMetrics() {
      const parentById = new Map(fixture.parentAssembly.mountAnchors.map((anchor) => [anchor.id, anchor]));
      const anchorErrors = fixture.part.localAnchors.map((anchor) => {
        const parent = parentById.get(anchor.id);
        const transformed = transformPointMm(anchor.positionMm);
        return {
          id: anchor.id,
          transformedMm: transformed.map((n) => Number(n.toFixed(4))),
          targetMm: parent.positionMm,
          errorMm: Number(distMm(transformed, parent.positionMm).toFixed(4))
        };
      });
      const maxAnchorErrorMm = Math.max(...anchorErrors.map((item) => item.errorMm));
      const handleBackZMm = fixture.partToParentTransform.translationMm[2] - fixture.part.dimensionsMm.depth / 2;
      const standoffMm = Number((handleBackZMm - fixture.parentAssembly.frontSkinZMm).toFixed(4));
      const recessCenter = fixture.parentAssembly.recess.centerMm;
      const handleCenter = fixture.partToParentTransform.translationMm;
      const lateralOffsetMm = [
        Number((handleCenter[0] - recessCenter[0]).toFixed(4)),
        Number((handleCenter[1] - recessCenter[1]).toFixed(4))
      ];
      const pocketSlackMm = [
        Number(((fixture.parentAssembly.recess.dimensionsMm[0] - fixture.part.dimensionsMm.length) / 2).toFixed(4)),
        Number(((fixture.parentAssembly.recess.dimensionsMm[1] - fixture.part.dimensionsMm.height) / 2).toFixed(4))
      ];
      return {
        anchorErrors,
        maxAnchorErrorMm: Number(maxAnchorErrorMm.toFixed(4)),
        toleranceMm: fixture.partToParentTransform.placementToleranceMm,
        standoffMm,
        requiredStandOffMm: fixture.partToParentTransform.requiredStandOffMm,
        lateralOffsetMm,
        pocketSlackMm,
        environment: fixture.parentAssembly.environment,
        parentAssemblyId: fixture.parentAssembly.id,
        partId: fixture.part.id
      };
    }

    function projectToPixel(pointMm) {
      const projected = v3(pointMm).project(camera);
      return {
        x: Math.round((projected.x + 1) * 0.5 * width),
        y: Math.round((projected.y + 1) * 0.5 * height),
        ndc: [Number(projected.x.toFixed(4)), Number(projected.y.toFixed(4)), Number(projected.z.toFixed(4))]
      };
    }

    function summarizePixels(buffer, zone) {
      const bg = [242, 244, 247];
      const x0 = Math.max(0, Math.floor(zone.x0));
      const y0 = Math.max(0, Math.floor(zone.y0));
      const x1 = Math.min(width - 1, Math.ceil(zone.x1));
      const y1 = Math.min(height - 1, Math.ceil(zone.y1));
      let count = 0;
      let nonBackground = 0;
      let darkPixels = 0;
      let doorPixels = 0;
      let goldPixels = 0;
      let minLuma = 255;
      let maxLuma = 0;
      const colors = new Set();
      const step = Math.max(1, Math.floor(Math.min(x1 - x0 + 1, y1 - y0 + 1) / 80));
      for (let y = y0; y <= y1; y += step) {
        for (let x = x0; x <= x1; x += step) {
          const idx = (y * width + x) * 4;
          const r = buffer[idx];
          const g = buffer[idx + 1];
          const b = buffer[idx + 2];
          const a = buffer[idx + 3];
          if (a < 8) continue;
          count += 1;
          colors.add(r + "," + g + "," + b);
          const deltaBg = Math.abs(r - bg[0]) + Math.abs(g - bg[1]) + Math.abs(b - bg[2]);
          if (deltaBg > 34) nonBackground += 1;
          if (r < 85 && g < 90 && b < 100) darkPixels += 1;
          if (b > r + 10 && b > 88 && g > 70) doorPixels += 1;
          if (r > 145 && g > 105 && b < 120) goldPixels += 1;
          const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
          minLuma = Math.min(minLuma, luma);
          maxLuma = Math.max(maxLuma, luma);
        }
      }
      return {
        count,
        sampledColors: colors.size,
        nonBackground,
        nonBackgroundRatio: count ? Number((nonBackground / count).toFixed(4)) : 0,
        darkPixels,
        doorPixels,
        goldPixels,
        luminanceRange: Number((maxLuma - minLuma).toFixed(2))
      };
    }

    function hashBuffer(buffer) {
      let h = 2166136261;
      for (let i = 0; i < buffer.length; i += 16) {
        h ^= buffer[i];
        h = Math.imul(h, 16777619);
      }
      return (h >>> 0).toString(16).padStart(8, "0");
    }

    function captureFrame(label) {
      renderer.render(scene, camera);
      const gl = renderer.getContext();
      const buffer = new Uint8Array(width * height * 4);
      gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, buffer);
      const handleCenter = projectToPixel(fixture.partToParentTransform.translationMm);
      const doorCenter = projectToPixel(fixture.parentAssembly.recess.centerMm);
      const full = summarizePixels(buffer, { x0: 0, y0: 0, x1: width - 1, y1: height - 1 });
      const handleZone = summarizePixels(buffer, {
        x0: handleCenter.x - 88,
        y0: handleCenter.y - 54,
        x1: handleCenter.x + 88,
        y1: handleCenter.y + 54
      });
      const doorZone = summarizePixels(buffer, {
        x0: doorCenter.x - 150,
        y0: doorCenter.y - 90,
        x1: doorCenter.x + 150,
        y1: doorCenter.y + 90
      });
      return {
        buffer,
        stats: {
          label,
          width,
          height,
          pixelHash: hashBuffer(buffer),
          handleCenter,
          doorCenter,
          full,
          handleZone,
          doorZone
        }
      };
    }

    function visualDelta(beforeBuffer, afterBuffer) {
      let changedSampledPixels = 0;
      let meanDelta = 0;
      let samples = 0;
      for (let i = 0; i < beforeBuffer.length; i += 32) {
        const d =
          Math.abs(beforeBuffer[i] - afterBuffer[i]) +
          Math.abs(beforeBuffer[i + 1] - afterBuffer[i + 1]) +
          Math.abs(beforeBuffer[i + 2] - afterBuffer[i + 2]);
        meanDelta += d;
        samples += 1;
        if (d > 35) changedSampledPixels += 1;
      }
      return {
        changedSampledPixels,
        samples,
        meanDelta: Number((meanDelta / Math.max(1, samples)).toFixed(2))
      };
    }

    function publish(seated, beforeFrame, afterFrame = null) {
      window.__cadverifyAssemblyResult = {
        fixtureId: fixture.id,
        fixtureHash,
        seated,
        boundary: fixture.boundary,
        placement: placementMetrics(),
        render: {
          before: beforeFrame.stats,
          after: afterFrame ? afterFrame.stats : null,
          visualDelta: afterFrame ? visualDelta(beforeFrame.buffer, afterFrame.buffer) : null
        }
      };
    }

    try {
      applyPose(false);
      const beforeFrame = captureFrame("exploded-preview");
      publish(false, beforeFrame);

      seatButton.addEventListener("click", () => {
        applyPose(true);
        const afterFrame = captureFrame("seated-in-door");
        publish(true, beforeFrame, afterFrame);
      });

      window.__assemblyReady = true;
    } catch (error) {
      window.__assemblyError = error instanceof Error ? error.stack || error.message : String(error);
    }
  </script>
</body>
</html>`;
}

function createFixtureServer(fixtureRaw, fixture, fixtureHash) {
  return createServer(async (req, res) => {
    const host = req.headers.host || "127.0.0.1";
    const url = new URL(req.url || "/", `http://${host}`);
    try {
      if (url.pathname === "/" || url.pathname === "/fixture") {
        return text(res, 200, makeHtml(fixtureHash), "text/html; charset=utf-8");
      }
      if (url.pathname === "/fixture.json") {
        return text(res, 200, fixtureRaw, "application/json; charset=utf-8");
      }
      if (url.pathname === "/health") {
        return json(res, 200, {
          status: "ok",
          fixtureId: fixture.id,
          fixtureHash,
          boundary: fixture.boundary,
        });
      }
      if (url.pathname === "/favicon.ico") {
        res.writeHead(204, { "cache-control": "no-store" });
        res.end();
        return;
      }
      if (url.pathname.startsWith("/node_modules/three/")) {
        const rel = decodeURIComponent(url.pathname.replace("/node_modules/three/", ""));
        const filePath = path.resolve(threeRoot, rel);
        if (!filePath.startsWith(threeRoot) || !existsSync(filePath)) {
          return json(res, 404, { error: "not_found" });
        }
        const body = await readFile(filePath);
        res.writeHead(200, {
          "cache-control": "no-store",
          "content-length": String(body.length),
          "content-type": contentTypeFor(filePath),
        });
        res.end(body);
        return;
      }
      return json(res, 404, { error: "not_found" });
    } catch (error) {
      return json(res, 500, { error: error instanceof Error ? error.message : String(error) });
    }
  });
}

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert(address && typeof address === "object", "fixture server did not expose an address");
  return `http://127.0.0.1:${address.port}`;
}

async function close(server) {
  await new Promise((resolve) => server.close(resolve));
}

async function withStep(steps, name, fn) {
  const started = Date.now();
  try {
    const evidence = await fn();
    steps.push({ name, status: "pass", ms: Date.now() - started, evidence });
    return evidence;
  } catch (error) {
    steps.push({
      name,
      status: "fail",
      ms: Date.now() - started,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}

async function runBrowser(baseUrl) {
  await mkdir(screenshotDir, { recursive: true });
  let browser;
  try {
    browser = await pw.chromium.launch(launchOptions);
  } catch {
    browser = await pw.chromium.launch({
      headless: true,
      args: launchOptions.args,
    });
  }

  const consoleErrors = [];
  const requestFailures = [];
  const context = await browser.newContext({
    viewport: { width: 1040, height: 690 },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(err.message));
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (/favicon\.ico/i.test(url)) return;
    requestFailures.push({
      url,
      method: request.method(),
      error: request.failure()?.errorText || "request failed",
    });
  });

  try {
    await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForFunction(() => window.__assemblyReady || window.__assemblyError, null, { timeout: 30_000 });
    const initError = await page.evaluate(() => window.__assemblyError || null);
    assert(!initError, `assembly browser fixture failed to initialize: ${initError}`);

    const fixtureId = await page.evaluate(() => window.__cadverifyAssemblyResult?.fixtureId || "assembly-fixture");
    const beforeScreenshot = path.join(screenshotDir, `01-${slug(`${fixtureId}-exploded-preview`)}.png`);
    await page.screenshot({ path: beforeScreenshot, fullPage: false, animations: "disabled" });
    await page.getByRole("button", { name: /^Seat /i }).click();
    await page.waitForFunction(() => window.__cadverifyAssemblyResult?.seated === true, null, { timeout: 10_000 });
    const result = await page.evaluate(() => window.__cadverifyAssemblyResult);
    const afterScreenshot = path.join(screenshotDir, `02-${slug(`${fixtureId}-seated-in-parent`)}.png`);
    await page.screenshot({ path: afterScreenshot, fullPage: false, animations: "disabled" });
    const beforeStat = await stat(beforeScreenshot);
    const afterStat = await stat(afterScreenshot);
    assert(beforeStat.size > 20_000, `before screenshot too small: ${beforeStat.size}`);
    assert(afterStat.size > 20_000, `after screenshot too small: ${afterStat.size}`);
    return {
      result,
      screenshots: {
        before: beforeScreenshot,
        after: afterScreenshot,
      },
      screenshotBytes: {
        before: beforeStat.size,
        after: afterStat.size,
      },
      consoleErrors,
      requestFailures,
    };
  } finally {
    await browser.close();
  }
}

function markdown(data) {
  const caseRows = data.cases
    .map(
      (item) =>
        `| ${item.status} | ${item.fixtureId} | ${item.parentAssemblyId} | ${item.partId} | ${item.steps.length} | ${item.error || "pass"} |`
    )
    .join("\n");
  const stepRows = data.cases
    .flatMap((item) =>
      item.steps.map(
        (step) =>
          `| ${item.fixtureId} | ${step.status} | ${step.name} | ${step.ms} | ${step.error || JSON.stringify(step.evidence).slice(0, 220)} |`
      )
    )
    .join("\n");

  return `# Assembly Visual Fidelity

- Run: ${data.runId}
- Status: ${data.status}
- Fixtures: ${data.cases.length}
- Boundary: ${data.boundary}

## Fixture Cases

| Result | Fixture | Parent Assembly | Part | Steps | Evidence |
| --- | --- | --- | --- | ---: | --- |
${caseRows}

## Step Evidence

| Fixture | Result | Step | Duration ms | Evidence |
| --- | --- | --- | ---: | --- |
${stepRows}

## Screenshots

${data.cases
  .map(
    (item) =>
      `- ${item.fixtureId} before: ${item.screenshots?.before || "not captured"}\n- ${item.fixtureId} after: ${item.screenshots?.after || "not captured"}`
  )
  .join("\n")}

## Failed

\`\`\`json
${JSON.stringify(data.failed, null, 2)}
\`\`\`
`;
}

async function fixturePaths() {
  if (fixtureOverride) return [fixtureOverride];
  const entries = await readdir(fixtureDir);
  return entries
    .filter((entry) => entry.endsWith("-assembly.fixture.json"))
    .sort()
    .map((entry) => path.join(fixtureDir, entry));
}

function validateFixtureContract(fixture) {
  assert(fixture.id, "fixture id missing");
  assert(fixture.boundary && /not .*certification|not .*signoff|not .*proprietary/i.test(fixture.boundary), "truth boundary missing");
  assert(fixture.coordinateSystem?.units === "mm", "fixture coordinate system must be mm");
  assert(fixture.parentAssembly?.id, "parent assembly id missing");
  assert(fixture.parentAssembly?.kind, "parent assembly kind missing");
  assert(fixture.part?.id, "part id missing");
  assert(fixture.part?.kind, "part kind missing");
  assert(fixture.partToParentTransform?.translationMm?.length === 3, "part-to-parent translation missing");
  assert(fixture.partToParentTransform?.rotationDeg?.length === 3, "part-to-parent rotation missing");
  assert(Number.isFinite(fixture.partToParentTransform?.placementToleranceMm), "placement tolerance missing");
  assert(Number.isFinite(fixture.partToParentTransform?.requiredStandOffMm), "required standoff missing");
  assert((fixture.parentAssembly.mountAnchors || []).length >= 2, "parent mount anchors missing");
  assert((fixture.part.localAnchors || []).length >= 2, "part local anchors missing");
  const parentIds = new Set(fixture.parentAssembly.mountAnchors.map((anchor) => anchor.id));
  for (const anchor of fixture.part.localAnchors) {
    assert(parentIds.has(anchor.id), `part anchor ${anchor.id} has no matching parent anchor`);
  }
  assert(Object.keys(fixture.parentAssembly.environment || {}).length >= 3, "parent service environment is too thin");
  assert(fixture.parentAssembly.recess?.centerMm?.length === 3, "parent assembly recess/seat center missing");
  assert(fixture.cinematicExpectations?.explodedOffsetMm?.length === 3, "exploded cinematic offset missing");
  assert(
    Number.isFinite(fixture.cinematicExpectations?.minimumVisualDeltaPixels),
    "minimum visual delta missing"
  );
}

async function runFixtureCase(fixtureFile) {
  const fixtureRaw = await readFile(fixtureFile, "utf8");
  const fixture = JSON.parse(fixtureRaw);
  const fixtureHash = createHash("sha256").update(fixtureRaw).digest("hex");
  const server = createFixtureServer(fixtureRaw, fixture, fixtureHash);
  const baseUrl = await listen(server);
  const steps = [];
  let browserEvidence = null;
  let caseError = null;

  try {
    await withStep(steps, "assembly fixture declares parent, part, coordinate system, and environment", async () => {
      validateFixtureContract(fixture);
      return {
        parentAssembly: fixture.parentAssembly.id,
        parentKind: fixture.parentAssembly.kind,
        part: fixture.part.id,
        partKind: fixture.part.kind,
        coordinateSystem: fixture.coordinateSystem,
        serviceEnvironment: fixture.parentAssembly.environment,
        fixtureHash,
      };
    });

    await withStep(steps, "browser renders exploded and seated populated-context states", async () => {
      const evidence = await runBrowser(baseUrl);
      assert(evidence.consoleErrors.length === 0, `browser console errors: ${evidence.consoleErrors.join("; ")}`);
      assert(evidence.requestFailures.length === 0, `browser request failures: ${JSON.stringify(evidence.requestFailures)}`);
      assert(evidence.result?.seated === true, "browser did not enter seated state");
      assert(evidence.result.fixtureHash === fixtureHash, "browser rendered a different fixture hash");
      browserEvidence = evidence;
      return {
        screenshotBytes: evidence.screenshotBytes,
        beforePixelHash: evidence.result.render.before.pixelHash,
        afterPixelHash: evidence.result.render.after.pixelHash,
        visualDelta: evidence.result.render.visualDelta,
      };
    });

    await withStep(steps, "part seats into parent assembly within transform tolerance", async () => {
      const placement = browserEvidence.result.placement;
      assert(placement.parentAssemblyId === fixture.parentAssembly.id, "rendered parent assembly id drifted");
      assert(placement.partId === fixture.part.id, "rendered part id drifted");
      assert(
        placement.maxAnchorErrorMm <= placement.toleranceMm,
        `mount anchor error ${placement.maxAnchorErrorMm}mm exceeds tolerance ${placement.toleranceMm}mm`
      );
      assert(
        approxEqual(placement.standoffMm, placement.requiredStandOffMm, 0.05),
        `standoff ${placement.standoffMm}mm does not match required ${placement.requiredStandOffMm}mm`
      );
      assert(
        Math.abs(placement.lateralOffsetMm[0]) <= placement.pocketSlackMm[0],
        `part lateral X offset ${placement.lateralOffsetMm[0]}mm exceeds pocket slack ${placement.pocketSlackMm[0]}mm`
      );
      assert(
        Math.abs(placement.lateralOffsetMm[1]) <= placement.pocketSlackMm[1],
        `part lateral Y offset ${placement.lateralOffsetMm[1]}mm exceeds pocket slack ${placement.pocketSlackMm[1]}mm`
      );
      return placement;
    });

    await withStep(steps, "seated canvas has nonblank cinematic and part-specific pixel evidence", async () => {
      const render = browserEvidence.result.render;
      assert(render.before.pixelHash !== render.after.pixelHash, "exploded and seated renders produced identical pixel hashes");
      assert(
        render.visualDelta.changedSampledPixels >= fixture.cinematicExpectations.minimumVisualDeltaPixels,
        `visual delta ${render.visualDelta.changedSampledPixels} below minimum ${fixture.cinematicExpectations.minimumVisualDeltaPixels}`
      );
      assert(render.after.full.sampledColors >= 32, "seated canvas does not have enough sampled colors");
      assert(render.after.full.luminanceRange >= 35, "seated canvas lacks contrast");
      assert(render.after.full.nonBackgroundRatio >= 0.18, "seated canvas is mostly background");
      assert(render.after.handleZone.darkPixels > 30, "part zone does not contain enough dark part pixels");
      assert(render.after.doorZone.doorPixels > 40, "parent assembly zone does not contain enough parent pixels");
      return {
        before: render.before,
        after: render.after,
        visualDelta: render.visualDelta,
      };
    });
  } catch (error) {
    caseError = error instanceof Error ? error.message : String(error);
  } finally {
    await close(server);
  }

  const failed = steps.filter((step) => step.status !== "pass");
  return {
    status: failed.length === 0 && !caseError ? "PASS" : "FAIL",
    fixtureFile,
    fixtureId: fixture.id,
    fixtureName: fixture.name,
    fixtureHash,
    parentAssemblyId: fixture.parentAssembly?.id || null,
    partId: fixture.part?.id || null,
    simulatorUrl: baseUrl,
    steps,
    failed,
    error: caseError,
    boundary: fixture.boundary,
    placement: browserEvidence?.result?.placement || null,
    render: browserEvidence?.result?.render || null,
    screenshots: browserEvidence?.screenshots || null,
    screenshotBytes: browserEvidence?.screenshotBytes || null,
    consoleErrors: browserEvidence?.consoleErrors || [],
    requestFailures: browserEvidence?.requestFailures || [],
  };
}

async function main() {
  const paths = await fixturePaths();
  assert(paths.length > 0, "no assembly fixture files found");
  const cases = [];
  for (const file of paths) {
    cases.push(await runFixtureCase(file));
  }

  const failed = cases.filter((item) => item.status !== "PASS");
  const data = {
    status: failed.length === 0 ? "PASS" : "NEEDS_FIXES",
    generatedAt: new Date().toISOString(),
    runId,
    boundary:
      "This proves deterministic assembly/context population for synthetic customer-like fixtures: parent assembly identity, part identity, coordinate system, declared service environment, part-to-parent transform, browser WebGL render health, and visual change from exploded to seated state. It is not customer proprietary CAD, native CAD certification, vendor certification, or live customer signoff.",
    fixtures: paths,
    cases,
    steps: cases.flatMap((item) =>
      item.steps.map((step) => ({
        ...step,
        name: `${item.fixtureId}: ${step.name}`,
        fixtureId: item.fixtureId,
        url: item.simulatorUrl,
      }))
    ),
    failed,
  };

  await mkdir(outputRoot, { recursive: true });
  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));
  console.log(
    JSON.stringify(
      {
        status: data.status,
        fixtures: data.cases.length,
        steps: data.cases.reduce((total, item) => total + item.steps.length, 0),
        failed: failed.map((item) => ({ fixture: item.fixtureId, error: item.error || item.failed[0]?.error })),
        report: artifacts.md,
      },
      null,
      2
    )
  );
  if (data.status !== "PASS") process.exitCode = 1;
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
