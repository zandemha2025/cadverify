import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");

const apiBase = (process.env.CADVERIFY_API_URL || "https://cadvrfy-api.fly.dev").replace(/\/$/, "");
const timeoutMs = Number.parseInt(process.env.CADVERIFY_HEALTH_TIMEOUT_MS || "180000", 10);
const intervalMs = Number.parseInt(process.env.CADVERIFY_HEALTH_INTERVAL_MS || "5000", 10);
const requireWorker = process.env.CADVERIFY_REQUIRE_WORKER !== "0";
const requireWorkerStrict = process.env.CADVERIFY_REQUIRE_WORKER_STRICT !== "0";
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-");

const artifacts = {
  json: path.join(outputRoot, `fly-live-health-gate-${runId}.json`),
  md: path.join(outputRoot, `qa-report-fly-live-health-gate-${runId}.md`),
};

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function verdict(status, body) {
  const checks = [
    ["http_200", status === 200, `HTTP status ${status}`],
    ["status_ok", body?.status === "ok", `health status ${body?.status}`],
    ["postgres", body?.postgres === true, `postgres ${body?.postgres}`],
    ["redis", body?.redis === true && body?.async?.redis === true, `redis ${body?.redis}/${body?.async?.redis}`],
  ];
  if (requireWorker) {
    checks.push([
      "worker_ok",
      body?.async?.worker === "ok",
      `worker ${body?.async?.worker || "missing"}`,
    ]);
  }
  if (requireWorkerStrict) {
    checks.push([
      "worker_strict",
      body?.async?.worker_strict === true,
      `worker_strict ${body?.async?.worker_strict}`,
    ]);
  }
  const failed = checks.filter(([, ok]) => !ok);
  return {
    ok: failed.length === 0,
    checks: checks.map(([id, ok, detail]) => ({ id, ok, detail })),
    failed: failed.map(([id, , detail]) => ({ id, detail })),
  };
}

async function probe() {
  const started = Date.now();
  try {
    const response = await fetch(`${apiBase}/health`, { cache: "no-store" });
    const text = await response.text();
    let body = null;
    try {
      body = JSON.parse(text);
    } catch {
      body = { raw: text.slice(0, 500) };
    }
    return {
      ok: true,
      durationMs: Date.now() - started,
      httpStatus: response.status,
      body,
      verdict: verdict(response.status, body),
    };
  } catch (error) {
    return {
      ok: false,
      durationMs: Date.now() - started,
      httpStatus: 0,
      body: null,
      error: error instanceof Error ? error.message : String(error),
      verdict: {
        ok: false,
        checks: [{ id: "fetch", ok: false, detail: "fetch failed" }],
        failed: [{ id: "fetch", detail: error instanceof Error ? error.message : String(error) }],
      },
    };
  }
}

function markdown(data) {
  const rows = data.attempts
    .map((attempt) => {
      const failed = attempt.verdict.failed.map((item) => `${item.id}: ${item.detail}`).join("; ") || "none";
      return `| ${attempt.index} | ${attempt.httpStatus} | ${attempt.durationMs} | ${attempt.verdict.ok ? "PASS" : "WAIT"} | ${failed} |`;
    })
    .join("\n");
  return `# Fly Live Health Gate

- Status: ${data.status}
- API: ${data.apiBase}
- Requires worker: ${data.requireWorker}
- Requires strict worker gate: ${data.requireWorkerStrict}
- Attempts: ${data.attempts.length}

| Attempt | HTTP | Duration ms | Verdict | Failed checks |
| ---: | ---: | ---: | --- | --- |
${rows}
`;
}

async function main() {
  await mkdir(outputRoot, { recursive: true });
  const started = Date.now();
  const attempts = [];

  while (Date.now() - started <= timeoutMs) {
    const result = await probe();
    result.index = attempts.length + 1;
    attempts.push(result);
    if (result.verdict.ok) break;
    await sleep(intervalMs);
  }

  const final = attempts.at(-1);
  const status = final?.verdict.ok ? "PASS" : "NEEDS_FIXES";
  const data = {
    status,
    generatedAt: new Date().toISOString(),
    runId,
    apiBase,
    timeoutMs,
    intervalMs,
    requireWorker,
    requireWorkerStrict,
    final: final || null,
    attempts,
  };

  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));
  console.log(JSON.stringify({
    status,
    apiBase,
    attempts: attempts.length,
    finalHttpStatus: final?.httpStatus,
    finalWorker: final?.body?.async?.worker,
    workerStrict: final?.body?.async?.worker_strict,
    report: artifacts.md,
  }, null, 2));
  if (status !== "PASS") process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
