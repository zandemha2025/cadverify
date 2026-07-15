import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { isIP } from "node:net";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  configuredClientIp,
  runScopedClientIp,
} from "./run-scoped-client-ip.mjs";

test("run-scoped client identities are stable, distinct, and valid RFC 3849 IPv6", () => {
  const first = runScopedClientIp("run-a", "signup");
  assert.equal(first, runScopedClientIp("run-a", "signup"));
  assert.notEqual(first, runScopedClientIp("run-b", "signup"));
  assert.notEqual(first, runScopedClientIp("run-a", "second-user"));
  assert.equal(isIP(first), 6);
  assert.match(first, /^2001:db8:/);
});

test("an explicit valid client identity wins and malformed overrides fail closed", () => {
  assert.equal(
    configuredClientIp("run-a", "signup", { E2E_CLIENT_IP: "203.0.113.42" }),
    "203.0.113.42",
  );
  assert.throws(
    () => configuredClientIp("run-a", "signup", { E2E_CLIENT_IP: "203.0.113.42, 10.0.0.1" }),
    /one exact IPv4 or IPv6 address/,
  );
});

test("browser runners never fall back to a fixed documentation IPv4 identity", () => {
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const offenders = readdirSync(scriptDir)
    .filter((name) => name.endsWith(".mjs"))
    .filter((name) => /198\.51\.100\./.test(readFileSync(path.join(scriptDir, name), "utf8")));
  assert.deepEqual(offenders, []);
});
