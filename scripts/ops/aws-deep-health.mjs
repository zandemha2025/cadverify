import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const apiOrigin = canonicalHttpsOrigin("AWS_PUBLIC_API_ORIGIN");
const dashboardOrigin = canonicalHttpsOrigin("AWS_DASHBOARD_ORIGIN");
const directUploadOrigin = canonicalHttpsOrigin("AWS_DIRECT_UPLOAD_ORIGIN");
const deepHealthToken = required("CADVERIFY_DEEP_HEALTH_TOKEN");
const expectedRelease = required("RELEASE_SHA");
const timeoutMs = integer("AWS_HEALTH_TIMEOUT_MS", 600_000, 30_000);
const intervalMs = integer("AWS_HEALTH_INTERVAL_MS", 5_000, 1_000);
const requestTimeoutMs = integer("AWS_HEALTH_REQUEST_TIMEOUT_MS", 30_000, 1_000);
const evidencePath = process.env.AWS_PROMOTION_EVIDENCE_PATH?.trim() || "";

if (apiOrigin !== dashboardOrigin) {
  throw new Error("AWS API and dashboard origins must be the same canonical CloudFront HTTPS origin");
}
if (directUploadOrigin === dashboardOrigin) {
  throw new Error("AWS direct-upload origin must be physically distinct from the application origin");
}

function required(name) {
  const value = process.env[name]?.trim() || "";
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function integer(name, fallback, minimum) {
  const value = Number.parseInt(process.env[name] || String(fallback), 10);
  if (!Number.isFinite(value) || value < minimum) {
    throw new Error(`${name} must be an integer of at least ${minimum}`);
  }
  return value;
}

function canonicalHttpsOrigin(name) {
  const raw = required(name);
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error(`${name} must be a valid HTTPS origin`);
  }
  if (
    parsed.protocol !== "https:" ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash ||
    parsed.origin !== raw
  ) {
    throw new Error(`${name} must be a canonical HTTPS origin with no path or credentials`);
  }
  return raw;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function jsonProbe(url, options = {}) {
  const startedAt = Date.now();
  try {
    const response = await fetch(url, {
      cache: "no-store",
      redirect: "error",
      ...options,
      signal: AbortSignal.timeout(requestTimeoutMs),
    });
    const text = await response.text();
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      body = { invalidJson: true };
    }
    return {
      ok: response.ok,
      status: response.status,
      durationMs: Date.now() - startedAt,
      body,
    };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      durationMs: Date.now() - startedAt,
      error: error instanceof Error ? error.message : String(error),
      body: null,
    };
  }
}

async function frontendProbe(url) {
  const startedAt = Date.now();
  try {
    const response = await fetch(url, {
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(requestTimeoutMs),
    });
    const csp = response.headers.get("content-security-policy") || "";
    const connectDirective = csp
      .split(";")
      .map((directive) => directive.trim())
      .find((directive) => directive.startsWith("connect-src ")) || "";
    return {
      ok: response.ok,
      status: response.status,
      durationMs: Date.now() - startedAt,
      build: response.headers.get("x-proofshape-build"),
      csp,
      connectSources: connectDirective.split(/\s+/).slice(1),
    };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      durationMs: Date.now() - startedAt,
      error: error instanceof Error ? error.message : String(error),
      build: null,
      csp: "",
      connectSources: [],
    };
  }
}

function evaluate(health, deep, proxy, frontend) {
  const checks = [
    ["health_http", health.status === 200, `HTTP ${health.status}`],
    ["health_status", health.body?.status === "ok", String(health.body?.status)],
    ["release", health.body?.build_id === expectedRelease, String(health.body?.build_id)],
    ["postgres", health.body?.postgres === true, String(health.body?.postgres)],
    ["redis", health.body?.redis === true, String(health.body?.redis)],
    ["worker", health.body?.async?.worker === "ok", String(health.body?.async?.worker)],
    ["worker_strict", health.body?.async?.worker_strict === true, String(health.body?.async?.worker_strict)],
    ["deep_http", deep.status === 200, `HTTP ${deep.status}`],
    ["deep_status", deep.body?.status === "ok", String(deep.body?.status)],
    ["deep_postgres", deep.body?.checks?.postgres?.ok === true, String(deep.body?.checks?.postgres?.ok)],
    ["deep_redis", deep.body?.checks?.redis?.ok === true, String(deep.body?.checks?.redis?.ok)],
    ["deep_worker", deep.body?.checks?.worker?.state === "ok", String(deep.body?.checks?.worker?.state)],
    ["object_expected", deep.body?.checks?.object_store?.expected === true, String(deep.body?.checks?.object_store?.expected)],
    ["object_store", deep.body?.checks?.object_store?.ok === true, String(deep.body?.checks?.object_store?.ok)],
    ["auth_proxy", proxy.status === 200 && proxy.body?.ok === true, `HTTP ${proxy.status}`],
    ["frontend_http", frontend.status === 200, `HTTP ${frontend.status}`],
    ["frontend_release", frontend.build === expectedRelease, String(frontend.build)],
    ["direct_upload_csp", frontend.connectSources.includes(directUploadOrigin), frontend.connectSources.join(" ")],
    [
      "direct_upload_csp_no_aws_wildcard",
      !frontend.connectSources.some((source) => source.includes("*.amazonaws.com")),
      frontend.connectSources.join(" "),
    ],
  ];
  return {
    ok: checks.every(([, ok]) => ok),
    checks: checks.map(([name, ok, detail]) => ({ name, ok, detail })),
  };
}

async function attempt(index) {
  const health = await jsonProbe(`${apiOrigin}/health`);
  const deep = await jsonProbe(`${apiOrigin}/health/deep`, {
    headers: { "X-CadVerify-Health-Token": deepHealthToken },
  });
  const proxy = await jsonProbe(`${dashboardOrigin}/api/auth/proxy-health`);
  const frontend = await frontendProbe(`${dashboardOrigin}/`);
  const verdict = evaluate(health, deep, proxy, frontend);
  return {
    index,
    verdict,
    health: {
      status: health.status,
      durationMs: health.durationMs,
      release: health.body?.build_id ?? null,
      postgres: health.body?.postgres ?? null,
      redis: health.body?.redis ?? null,
      worker: health.body?.async?.worker ?? null,
    },
    deep: {
      status: deep.status,
      durationMs: deep.durationMs,
      postgres: deep.body?.checks?.postgres?.ok ?? null,
      redis: deep.body?.checks?.redis?.ok ?? null,
      worker: deep.body?.checks?.worker?.state ?? null,
      objectStore: deep.body?.checks?.object_store?.ok ?? null,
    },
    proxy: {
      status: proxy.status,
      durationMs: proxy.durationMs,
      ok: proxy.body?.ok ?? null,
    },
    frontend: {
      status: frontend.status,
      durationMs: frontend.durationMs,
      release: frontend.build,
      directUploadOriginAllowed: frontend.connectSources.includes(directUploadOrigin),
      connectSources: frontend.connectSources,
    },
  };
}

const startedAt = Date.now();
const attempts = [];
while (Date.now() - startedAt <= timeoutMs) {
  const result = await attempt(attempts.length + 1);
  attempts.push(result);
  if (result.verdict.ok) break;
  await sleep(intervalMs);
}

const final = attempts.at(-1);
const evidence = {
  status: final?.verdict.ok ? "PASS" : "NEEDS_FIXES",
  generatedAt: new Date().toISOString(),
  apiOrigin,
  dashboardOrigin,
  directUploadOrigin,
  expectedRelease,
  elapsedMs: Date.now() - startedAt,
  attempts,
};

if (evidencePath) {
  await mkdir(path.dirname(path.resolve(evidencePath)), { recursive: true });
  await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, { mode: 0o600 });
}

console.log(JSON.stringify({
  status: evidence.status,
  origin: apiOrigin,
  release: expectedRelease,
  attemptCount: attempts.length,
  final: final || null,
  evidencePath: evidencePath || null,
}, null, 2));

if (evidence.status !== "PASS") process.exitCode = 1;
