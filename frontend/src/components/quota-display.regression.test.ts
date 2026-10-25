// Regression: QA-008 — History asked an approved unlimited account to request paid access.
// Found by /qa on 2026-10-09
// Report: .gstack/qa-reports/qa-report-scalecad-ai-2026-10-09.md
// Render the actual card, including its real child components, for both plans.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const requirePackage = createRequire(import.meta.url);
const modules = new Map<string, { exports: Record<string, unknown> }>();
function loadProjectModule(file: URL): Record<string, unknown> {
  const cached = modules.get(file.href);
  if (cached) return cached.exports;
  const module = { exports: {} as Record<string, unknown> };
  modules.set(file.href, module);
  const output = ts.transpileModule(readFileSync(file, "utf8"), {
    fileName: file.pathname,
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText;
  runInNewContext(output, {
    module, exports: module.exports,
    require: (name: string) => {
      if (!name.startsWith("@/")) return requirePackage(name);
      const target = new URL(`../${name.slice(2)}`, import.meta.url);
      const found = [".tsx", ".ts"].map(suffix => new URL(target.href + suffix)).find(existsSync);
      assert.ok(found, `Project import must resolve: ${name}`);
      return loadProjectModule(found);
    },
  }, { filename: file.pathname });
  return module.exports;
}

type Usage = { plan: string; unlimited: boolean; used: number | null; cap: number | null; remaining: number | null; resets_at?: string | null };
const QuotaDisplay = loadProjectModule(new URL("./QuotaDisplay.tsx", import.meta.url)).default as ComponentType<{ usage: Usage }>;

test("approved unlimited access never asks the account to request paid access", () => {
  const html = renderToStaticMarkup(createElement(QuotaDisplay, {
    usage: { plan: "pilot", unlimited: true, used: null, cap: null, remaining: null },
  }));
  assert.match(html, /Approved access.*unlimited checks/);
  assert.doesNotMatch(html, /Request paid access|Upgrade to Pro|Manage billing|mailto:/);
});

test("exhausted free access keeps the quota and offers Pro in one click", () => {
  const html = renderToStaticMarkup(createElement(QuotaDisplay, {
    usage: { plan: "trial", unlimited: false, used: 3, cap: 3, remaining: 0 },
  }));
  assert.match(html, /3 of 3 used/);
  assert.match(html, /Free checks/);
  assert.match(html, /<button[^>]*>Upgrade to Pro<\/button>/);
  assert.doesNotMatch(html, /lifetime|Request paid access|Approved access/);
});

test("Pro shows this month's checks, the reset date and billing management", () => {
  const html = renderToStaticMarkup(createElement(QuotaDisplay, {
    usage: { plan: "pro", unlimited: false, used: 50, cap: 50, remaining: 0, resets_at: "2026-11-17T00:00:00+00:00" } as Usage,
  }));
  assert.match(html, /Pro checks this month/);
  assert.match(html, /Resets on November 17/);
  assert.match(html, /You&#x27;ve used this month&#x27;s 50 Pro checks/);
  assert.match(html, /Manage billing/);
  assert.doesNotMatch(html, /Upgrade to Pro/);
});
