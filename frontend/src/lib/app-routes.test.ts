import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { isAppPath } from "./app-routes.ts";

test("the app's routes and the pages below them are app paths", () => {
  for (const path of ["/app", "/app/parts/abc", "/verify", "/rfq-packages", "/rfq-packages/01ABC", "/cost-decisions/7", "/batch", "/settings/organization"]) {
    assert.equal(isAppPath(path), true, path);
  }
});

test("public, sign-in and supplier pages are not app paths", () => {
  for (const path of ["/", "/pricing", "/sample", "/login", "/signup", "/reset-password", "/s/abc", "/costing", "/verifying", "/apple", null, undefined, ""]) {
    assert.equal(isAppPath(path), false, String(path));
  }
});

test("the proxy gates exactly these routes and the privacy panel stays off them", async () => {
  const proxy = await readFile(new URL("../proxy.ts", import.meta.url), "utf8");
  assert.match(proxy, /const gated = isAppPath\(pathname\);/);
  const analytics = await readFile(new URL("../components/analytics.tsx", import.meta.url), "utf8");
  assert.match(analytics, /const inApp = isAppPath\(path\);/);
});
