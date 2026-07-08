import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../..");
const outputRoot = process.env.E2E_ARTIFACT_DIR
  ? path.resolve(process.env.E2E_ARTIFACT_DIR)
  : path.join(repoRoot, ".gstack", "qa-reports");
const runId = process.env.E2E_RUN_ID || new Date().toISOString().slice(0, 10);
const apiBase = (process.env.CADVERIFY_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const requests = Number.parseInt(process.env.CADVERIFY_LOAD_REQUESTS || "6", 10);
const concurrency = Number.parseInt(process.env.CADVERIFY_LOAD_CONCURRENCY || "2", 10);
const maxP95Ms = Number.parseInt(process.env.CADVERIFY_LOAD_MAX_P95_MS || "30000", 10);
const cubePath = path.join(repoRoot, "backend", "tests", "assets", "cube.step");

const artifacts = {
  json: path.join(outputRoot, `api-load-smoke-${runId}.json`),
  md: path.join(outputRoot, `qa-report-api-load-smoke-${runId}.md`),
};

function assert(condition, detail) {
  if (!condition) throw new Error(detail);
}

function percentile(values, p) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[index];
}

function lineItemsMatch(body) {
  for (const estimate of body.estimates || []) {
    const lineItems = estimate.line_items || {};
    const sum = Object.values(lineItems).reduce((acc, value) => acc + Number(value), 0);
    if (Math.abs(Number(estimate.unit_cost_usd) - Math.round(sum * 100) / 100) >= 0.02) {
      return false;
    }
  }
  return true;
}

async function postCost(index, cubeBytes) {
  const started = performance.now();
  try {
    const form = new FormData();
    form.append("file", new Blob([cubeBytes], { type: "application/octet-stream" }), `load-smoke-${index}.step`);
    form.append("qty", "50,5000");
    form.append("material_class", "aluminum");
    form.append("region", "US");

    const response = await fetch(`${apiBase}/api/v1/validate/cost/demo`, {
      method: "POST",
      body: form,
    });
    const text = await response.text();
    let body = null;
    try {
      body = JSON.parse(text);
    } catch {
      body = { raw: text.slice(0, 300) };
    }
    assert(response.ok, `HTTP ${response.status}: ${text.slice(0, 300)}`);
    assert(body.status === "OK", `cost status was ${body.status}`);
    assert(body.geometry?.watertight === true, "cube STEP did not cost as watertight");
    assert(Array.isArray(body.estimates) && body.estimates.length > 0, "missing estimates");
    assert(lineItemsMatch(body), "line-item sum invariant failed");
    return {
      index,
      status: "PASS",
      durationMs: Math.round(performance.now() - started),
      estimateCount: body.estimates.length,
      faceCount: body.geometry.face_count,
      unitCostUsd: body.estimates[0]?.unit_cost_usd,
    };
  } catch (error) {
    return {
      index,
      status: "FAIL",
      durationMs: Math.round(performance.now() - started),
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

async function runPool(cubeBytes) {
  const results = [];
  let next = 0;
  async function worker() {
    while (next < requests) {
      const index = next;
      next += 1;
      results.push(await postCost(index, cubeBytes));
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, concurrency) }, () => worker()));
  return results.sort((a, b) => a.index - b.index);
}

async function main() {
  await mkdir(outputRoot, { recursive: true });
  const healthStarted = performance.now();
  const health = await fetch(`${apiBase}/health`);
  const healthText = await health.text();
  assert(health.ok, `/health failed: ${health.status} ${healthText.slice(0, 200)}`);
  const healthMs = Math.round(performance.now() - healthStarted);

  const cubeBytes = await readFile(cubePath);
  const started = performance.now();
  const results = await runPool(cubeBytes);
  const durations = results.map((item) => item.durationMs);
  const failed = results.filter((item) => item.status !== "PASS");
  const p95 = percentile(durations, 95);
  const max = Math.max(...durations);
  const status = failed.length === 0 && p95 <= maxP95Ms ? "PASS" : "NEEDS_FIXES";
  const data = {
    status,
    generatedAt: new Date().toISOString(),
    runId,
    apiBase,
    requests,
    concurrency,
    threshold: { maxP95Ms },
    health: { status: health.status, durationMs: healthMs },
    summary: {
      passed: results.length - failed.length,
      failed: failed.length,
      p50Ms: percentile(durations, 50),
      p95Ms: p95,
      maxMs: max,
      totalMs: Math.round(performance.now() - started),
    },
    results,
    failed,
  };

  await writeFile(artifacts.json, `${JSON.stringify(data, null, 2)}\n`);
  await writeFile(artifacts.md, markdown(data));
  console.log(
    JSON.stringify(
      {
        status,
        apiBase,
        requests,
        passed: data.summary.passed,
        failed: data.summary.failed,
        p95Ms: data.summary.p95Ms,
        report: artifacts.md,
      },
      null,
      2
    )
  );
  if (status !== "PASS") process.exitCode = 1;
}

function markdown(data) {
  const rows = data.results
    .map((item) => `| ${item.status} | ${item.index} | ${item.durationMs} | ${item.error || item.unitCostUsd} |`)
    .join("\n");
  return `# API Load Smoke

- Run: ${data.runId}
- Status: ${data.status}
- API: ${data.apiBase}
- Requests: ${data.requests}
- Concurrency: ${data.concurrency}
- P95: ${data.summary.p95Ms} ms
- Threshold: ${data.threshold.maxP95Ms} ms

| Result | Request | Duration ms | Evidence |
| --- | ---: | ---: | --- |
${rows}
`;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
