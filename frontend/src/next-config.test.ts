import { test } from "node:test";
import assert from "node:assert/strict";

const { default: nextConfig } = await import("../next.config.ts");

test("the dev server serves its scripts to 127.0.0.1 as well as localhost", () => {
  assert.ok(Array.isArray(nextConfig.allowedDevOrigins));
  assert.ok(nextConfig.allowedDevOrigins.includes("127.0.0.1"));
});
