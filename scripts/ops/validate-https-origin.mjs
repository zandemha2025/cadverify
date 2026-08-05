#!/usr/bin/env node

const raw = (process.argv[2] || "").trim();

function fail(message) {
  console.error(`INVALID_HTTPS_ORIGIN: ${message}`);
  process.exit(1);
}

if (!raw) fail("value is empty");

let parsed;
try {
  parsed = new URL(raw);
} catch {
  fail("value is not a valid absolute URL");
}

if (parsed.protocol !== "https:") fail("scheme must be https");
if (!parsed.hostname) fail("hostname is required");
if (parsed.username || parsed.password) fail("credentials are prohibited");
if (parsed.pathname !== "/" || parsed.search || parsed.hash) {
  fail("value must be an origin without path, query, or fragment");
}
if (raw !== parsed.origin && raw !== `${parsed.origin}/`) {
  fail("value must be a canonical HTTPS origin");
}

console.log("PASS: valid HTTPS origin");
