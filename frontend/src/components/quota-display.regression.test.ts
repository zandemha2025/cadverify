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

type Usage = { plan: string; unlimited: boolean; used: number | null; cap: number | null; remaining: number | null };
const QuotaDisplay = loadProjectModule(new URL("./QuotaDisplay.tsx", import.meta.url)).default as ComponentType<{ usage: Usage }>;

test("approved unlimited access never asks the account to request paid access", () => {
  const html = renderToStaticMarkup(createElement(QuotaDisplay, {
    usage: { plan: "pilot", unlimited: true, used: null, cap: null, remaining: null },
  }));
  assert.match(html, /Approved access.*unlimited checks/);
  assert.doesNotMatch(html, /Request paid access|to continue checking parts|mailto:/);
});

test("exhausted trial access keeps the quota and the request-access route", () => {
  const html = renderToStaticMarkup(createElement(QuotaDisplay, {
    usage: { plan: "trial", unlimited: false, used: 10, cap: 10, remaining: 0 },
  }));
  assert.match(html, /10 of 10 used/);
  assert.match(html, /Request paid access/);
  assert.match(html, /mailto:/);
  assert.doesNotMatch(html, /Approved access/);
});
