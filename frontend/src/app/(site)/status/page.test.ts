import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

test("status page reads live health without caching", () => {
  assert.match(source, /backendUrl\("\/health"\)/);
  assert.match(source, /cache: "no-store"/);
  assert.match(source, /dynamic = "force-dynamic"/);
  assert.doesNotMatch(source, /99\.9%|all systems operational/i);
});

test("status page carries the three customer-facing components and honest states", () => {
  for (const text of ["Engine API", "Worker", "Web app", "Operational", "Degraded", "Down", "build ", "checked "]) {
    assert.match(source, new RegExp(text));
  }
  assert.match(source, /No public incident feed is connected yet/);
  assert.doesNotMatch(source, /No incidents recorded/);
});


test("status page has an explicit narrow-screen layout", () => {
  const css = readFileSync(new URL("./status.module.css", import.meta.url), "utf8");
  assert.match(css, /@media \(max-width: 600px\)/);
  assert.match(css, /grid-template-columns: minmax\(0, 1fr\) auto/);
  assert.match(source, /styles\.statusGrid/);
});
