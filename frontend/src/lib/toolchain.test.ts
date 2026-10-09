import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const { getRootDirs } = require("@next/eslint-plugin-next/dist/utils/get-root-dirs.js");
const nextPlugin = require("@next/eslint-plugin-next");
const { ESLint } = require("eslint");

// The scoped tinyglobby override must keep Next's monorepo discovery and its
// internal-link rule working; a clean dependency audit alone cannot prove that.
test("Next lint root globs select directories and preserve internal-link checks", async () => {
  const fixture = mkdtempSync(join(tmpdir(), "scalecad-eslint-"));
  try {
    const web = join(fixture, "apps", "web");
    const docs = join(fixture, "apps", "docs");
    mkdirSync(join(web, "pages"), { recursive: true });
    mkdirSync(docs, { recursive: true });
    writeFileSync(join(fixture, "apps", "README.md"), "not an app directory");
    writeFileSync(join(web, "pages", "dashboard.jsx"), "export default function Page() {}");
    const rootDir = join(fixture, "apps", "*");
    const normalized = (paths: string[]) => paths.map((path) => resolve(path)).sort();
    assert.deepEqual(normalized(getRootDirs({ cwd: fixture, settings: { next: { rootDir } } })), [docs, web]);
    assert.deepEqual(normalized(getRootDirs({ cwd: fixture, settings: { next: { rootDir: [rootDir] } } })), [docs, web]);

    const eslint = new ESLint({
      cwd: fixture,
      overrideConfigFile: true,
      overrideConfig: [{
        files: ["**/*.jsx"],
        languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
        plugins: { "@next/next": nextPlugin },
        settings: { next: { rootDir } },
        rules: { "@next/next/no-html-link-for-pages": "error" },
      }],
    });
    const [result] = await eslint.lintText(
      'const nav = <a href="/dashboard">Dashboard</a>;',
      { filePath: join(fixture, "navigation.jsx") },
    );
    assert.equal(result.errorCount, 1);
    assert.equal(result.messages[0].ruleId, "@next/next/no-html-link-for-pages");
  } finally {
    rmSync(fixture, { recursive: true, force: true });
  }
});
