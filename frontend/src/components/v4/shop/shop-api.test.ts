// Rates and Real costs read their saved records in ONE request per screen load.
// They used to read up to 16 records one by one, against a 60/hour per-route
// limit, so browsing between the two screens hit it within minutes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const requirePackage = createRequire(import.meta.url);

function loadShopApi(fetchImpl: (url: string, init?: RequestInit) => Promise<Response>) {
  const file = new URL("./shop-api.ts", import.meta.url);
  const output = ts.transpileModule(readFileSync(file, "utf8"), {
    fileName: file.pathname,
    compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
  }).outputText;
  const module = { exports: {} as Record<string, unknown> };
  runInNewContext(output, {
    module,
    exports: module.exports,
    fetch: fetchImpl,
    URL,
    URLSearchParams,
    require: (name: string) => (name === "@/lib/api-base" ? { API_BASE: "/api/proxy" } : requirePackage(name)),
  });
  return module.exports as {
    getLatestPerPart: (n?: number) => Promise<{ parts: unknown[]; details: unknown[] }>;
  };
}

test("the screens' records come from one latest-per-part request", async () => {
  const calls: string[] = [];
  const api = loadShopApi(async (url) => {
    calls.push(url);
    return new Response(JSON.stringify({ parts: [{ id: "a" }], total_parts: 1, has_more: false, details: [{ id: "a", result: null }] }), { status: 200 });
  });
  const body = await api.getLatestPerPart(12);
  assert.deepEqual(calls, ["/api/proxy/cost-decisions/latest-per-part?detail_limit=12"]);
  assert.equal(body.parts.length, 1);
  assert.equal(body.details.length, 1);
});

test("Rates, Real costs and Changes make no per-record reads on load", () => {
  for (const name of ["rates-screen.tsx", "actuals-screen.tsx", "changes-screen.tsx"]) {
    const src = readFileSync(new URL(`./${name}`, import.meta.url), "utf8");
    assert.match(src, /usePartRecords\((12|6)\)/, name);
    assert.doesNotMatch(src, /recordDetail\(|getRecord\(|useRecords\(|listRecords\(/, name);
  }
});
