// Local load PROFILE for CADVerify hot endpoints — real numbers, honestly scoped.
//
// Drives a locally-started backend and reports REAL latency percentiles
// (p50/p95/p99), throughput (req/s), and error rate per endpoint:
//   - GET  /health              (liveness, cheap)
//   - GET  /health/deep         (dependency-level probes)
//   - POST /api/v1/validate/cost/demo  (the costed hot path: parse -> DFM ->
//                                        should-cost, unauthenticated demo route)
//
// This is a SINGLE-CONTAINER SMOKE on shared CI-grade hardware. It is NOT a
// production-scale or SLA benchmark and the numbers must not be extrapolated.
// k6 is not installed in this environment, so this uses Node's fetch (see the
// artifact header for that disclosure).
//
// Env:
//   CADVERIFY_API_URL          default http://127.0.0.1:8000
//   LOAD_HEALTH_REQUESTS       default 200
//   LOAD_HEALTH_CONCURRENCY    default 20
//   LOAD_COST_REQUESTS         default 12
//   LOAD_COST_CONCURRENCY      default 4
//   LOAD_OUT                   output txt path (default outputs/ops-proof/load-smoke-<date>.txt)

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const apiBase = (process.env.CADVERIFY_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const runId = process.env.LOAD_RUN_ID || new Date().toISOString().slice(0, 10);
const cubePath = path.join(repoRoot, "backend", "tests", "assets", "cube.step");
const outPath = process.env.LOAD_OUT
  || path.join(repoRoot, "outputs", "ops-proof", `load-smoke-${runId}.txt`);

const cfg = {
  health: {
    requests: int("LOAD_HEALTH_REQUESTS", 200),
    concurrency: int("LOAD_HEALTH_CONCURRENCY", 20),
  },
  healthDeep: {
    requests: int("LOAD_HEALTHDEEP_REQUESTS", 100),
    concurrency: int("LOAD_HEALTHDEEP_CONCURRENCY", 10),
  },
  cost: {
    requests: int("LOAD_COST_REQUESTS", 12),
    concurrency: int("LOAD_COST_CONCURRENCY", 4),
  },
};

function int(name, dflt) {
  return Number.parseInt(process.env[name] || String(dflt), 10);
}

function percentile(values, p) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[idx];
}

function stats(durations, wallMs, errors) {
  const n = durations.length;
  return {
    count: n,
    errors,
    errorRate: n === 0 ? 0 : errors / n,
    p50Ms: Math.round(percentile(durations, 50) * 1000) / 1000,
    p95Ms: Math.round(percentile(durations, 95) * 1000) / 1000,
    p99Ms: Math.round(percentile(durations, 99) * 1000) / 1000,
    maxMs: n === 0 ? 0 : Math.round(Math.max(...durations) * 1000) / 1000,
    reqPerSec: wallMs === 0 ? 0 : Math.round((n / (wallMs / 1000)) * 100) / 100,
    wallMs: Math.round(wallMs),
  };
}

// Run `total` requests via `fn(index)`, `concurrency` at a time. fn returns
// {ok:boolean}; timing is measured around each fn() call.
async function drive(total, concurrency, fn) {
  const durations = [];
  let errors = 0;
  let next = 0;
  const started = performance.now();
  async function worker() {
    while (next < total) {
      const index = next++;
      const t0 = performance.now();
      let ok = false;
      try {
        ok = await fn(index);
      } catch {
        ok = false;
      }
      durations.push(performance.now() - t0);
      if (!ok) errors++;
    }
  }
  await Promise.all(Array.from({ length: Math.max(1, concurrency) }, () => worker()));
  return stats(durations, performance.now() - started, errors);
}

async function getOk(pathname) {
  const resp = await fetch(`${apiBase}${pathname}`);
  // /health and /health/deep return 200 (healthy) or 503 (honestly degraded).
  // Both are non-error RESPONSES from the app; we count only transport/5xx>=500
  // that are NOT the deliberate 503 degradation as errors.
  await resp.text();
  return resp.status === 200 || resp.status === 503;
}

async function postCost(index, cubeBytes) {
  const form = new FormData();
  form.append("file", new Blob([cubeBytes], { type: "application/octet-stream" }), `load-${index}.step`);
  form.append("qty", "50,5000");
  form.append("material_class", "aluminum");
  form.append("region", "US");
  const resp = await fetch(`${apiBase}/api/v1/validate/cost/demo`, { method: "POST", body: form });
  const text = await resp.text();
  if (!resp.ok) return false;
  try {
    const body = JSON.parse(text);
    return body.status === "OK";
  } catch {
    return false;
  }
}

function fmt(label, s) {
  return [
    `${label}`,
    `  requests=${s.count}  errors=${s.errors}  error_rate=${(s.errorRate * 100).toFixed(2)}%`,
    `  throughput=${s.reqPerSec} req/s  wall=${s.wallMs}ms`,
    `  latency_ms  p50=${s.p50Ms}  p95=${s.p95Ms}  p99=${s.p99Ms}  max=${s.maxMs}`,
  ].join("\n");
}

async function main() {
  await mkdir(path.dirname(outPath), { recursive: true });

  // Preflight: backend must be up.
  const pre = await fetch(`${apiBase}/health`).catch(() => null);
  if (!pre) throw new Error(`backend not reachable at ${apiBase} (start uvicorn first)`);
  const preBody = await pre.text();

  const cubeBytes = await readFile(cubePath);

  const health = await drive(cfg.health.requests, cfg.health.concurrency, () => getOk("/health"));
  const healthDeep = await drive(cfg.healthDeep.requests, cfg.healthDeep.concurrency, () => getOk("/health/deep"));
  const cost = await drive(cfg.cost.requests, cfg.cost.concurrency, (i) => postCost(i, cubeBytes));

  const header = [
    "=== CADVerify local load smoke ===",
    `generated: ${new Date().toISOString()}`,
    `api: ${apiBase}`,
    `driver: Node ${process.version} fetch (k6 NOT installed in this container)`,
    "",
    "SCOPE / HONESTY: single-container smoke on shared CI-grade hardware. NOT a",
    "production-scale or SLA benchmark. Latencies are wall-clock per request from",
    "THIS host to a co-located uvicorn; do not extrapolate to production concurrency.",
    "/health & /health/deep 503 = honest dependency degradation (Redis/worker",
    "absent in this container), NOT a load failure — they are counted as served.",
    `preflight /health status: ${pre.status}  body: ${preBody.slice(0, 200)}`,
    "",
  ].join("\n");

  const body = [
    fmt("GET /health", health),
    "",
    fmt("GET /health/deep", healthDeep),
    "",
    fmt("POST /api/v1/validate/cost/demo (parse -> DFM -> should-cost, cube.step)", cost),
    "",
    "config: " + JSON.stringify(cfg),
    "",
  ].join("\n");

  const out = header + body;
  await writeFile(outPath, out);
  console.log(out);
  console.log(`\nWROTE ${outPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
