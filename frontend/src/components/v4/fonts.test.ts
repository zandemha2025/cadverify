import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const here = new URL(".", import.meta.url).pathname;
const src = join(here, "..", "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

test("no v4 screen asks Google for its fonts at build time", () => {
  // next/font/google broke the frontend image build on CI (Sora's font files
  // came back in a form Turbopack could not resolve); the v4 faces ship with the app.
  const users = sources(src).filter((path) => {
    const text = readFileSync(path, "utf8");
    return /import\s*\{[^}]*\b(Instrument_Sans|Sora)\b[^}]*\}\s*from\s*"next\/font\/google"/.test(text);
  });
  assert.deepEqual(users, []);
});

test("the v4 fonts are local files with their licences beside them", () => {
  const fonts = readFileSync(join(here, "fonts.ts"), "utf8");
  assert.match(fonts, /from "next\/font\/local"/);
  for (const file of ["InstrumentSans.woff2", "Sora.woff2", "OFL-InstrumentSans.txt", "OFL-Sora.txt"]) {
    assert.ok(statSync(join(here, "fonts", file)).size > 1000, `${file} is missing`);
    if (file.endsWith(".woff2")) assert.match(fonts, new RegExp(`"\\./fonts/${file.replace(".", "\\.")}"`));
  }
  // Same CSS variables as before, so v4.css needs no change.
  assert.match(fonts, /variable: "--font-v4-sans"/);
  assert.match(fonts, /variable: "--font-v4-disp"/);
});
