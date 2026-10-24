import assert from "node:assert/strict";
import { test } from "node:test";

import { cloudFrontViewerIp, requestClientIp, requestUserAgent } from "./auth-proxy-ip.ts";

function request(headers: Record<string, string>): Pick<Request, "headers"> {
  return { headers: new Headers(headers) };
}

test("CloudFront viewer addresses support IPv4 and IPv6 source ports", () => {
  assert.equal(cloudFrontViewerIp("198.51.100.42:54321"), "198.51.100.42");
  assert.equal(cloudFrontViewerIp("[2001:db8::42]:44321"), "2001:db8::42");
  assert.equal(cloudFrontViewerIp("2001:db8::42:44321"), "2001:db8::42");
  assert.equal(cloudFrontViewerIp("2001:db8::42:443"), "2001:db8::42");
});

test("CloudFront viewer parsing rejects chains, bad ports, and hostnames", () => {
  assert.equal(cloudFrontViewerIp("198.51.100.1:443, 203.0.113.8:8443"), null);
  assert.equal(cloudFrontViewerIp("198.51.100.1:0"), null);
  assert.equal(cloudFrontViewerIp("198.51.100.1:65536"), null);
  assert.equal(cloudFrontViewerIp("viewer.example:443"), null);
  assert.equal(cloudFrontViewerIp("198.51.100.1"), null);
  assert.equal(cloudFrontViewerIp("2001:db8::42"), null);
});

test("an explicit ingress source ignores spoofed headers for every other proxy", () => {
  const req = request({
    "fly-client-ip": "198.51.100.1",
    "x-real-ip": "198.51.100.2",
    "x-forwarded-for": "198.51.100.3, 10.0.0.1",
    "cloudfront-viewer-address": "198.51.100.4:51234",
    "cf-connecting-ip": "198.51.100.5",
  });

  assert.equal(requestClientIp(req, "fly"), "198.51.100.1");
  assert.equal(requestClientIp(req, "nginx"), "198.51.100.2");
  assert.equal(requestClientIp(req, "cloudfront"), "198.51.100.4");
  assert.equal(requestClientIp(req, "render"), "198.51.100.5");
  assert.equal(requestClientIp(req, "unknown"), null);
});

test("ALB X-Forwarded-For is never treated as an authenticated viewer source", () => {
  const req = request({ "x-forwarded-for": "198.51.100.8, 10.0.1.4" });
  for (const source of ["fly", "nginx", "cloudfront", "render", "auto"]) {
    assert.equal(requestClientIp(req, source), null);
  }
});

test("on Render only Cloudflare's CF-Connecting-IP names the visitor", () => {
  assert.equal(requestClientIp(request({ "cf-connecting-ip": "2001:db8::7" }), "render"), "2001:db8::7");
  assert.equal(requestClientIp(request({ "cf-connecting-ip": "198.51.100.9, 10.0.0.1" }), "render"), null);
  assert.equal(requestClientIp(request({ "cf-connecting-ip": "not-an-ip" }), "render"), null);
  // Auto (local development) never trusts CF-Connecting-IP: off Render anyone can send it.
  assert.equal(requestClientIp(request({ "cf-connecting-ip": "198.51.100.9" }), "auto"), null);
});

test("a released web server may name render as its client-IP source", async () => {
  const { readFileSync } = await import("node:fs");
  const source = readFileSync(new URL("../../instrumentation.ts", import.meta.url), "utf8");
  assert.match(source, /new Set\(\["fly", "nginx", "cloudfront", "render"\]\)/);
});

test("auth requests carry the browser's user agent so a sign-in row names the browser", () => {
  const ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 Safari/605.1.15";
  assert.deepEqual(requestUserAgent(request({ "user-agent": ua })), { "user-agent": ua });
  assert.deepEqual(requestUserAgent(request({})), {});
  assert.equal(requestUserAgent(request({ "user-agent": "x".repeat(900) }))["user-agent"].length, 500);
});

test("the signed auth proxy headers include the browser's user agent, with or without the secret", async () => {
  const { readFileSync } = await import("node:fs");
  const source = readFileSync(new URL("./auth-proxy.ts", import.meta.url), "utf8");
  assert.match(source, /const browser = requestUserAgent\(req\);/);
  assert.match(source, /if \(!secret \|\| !ip\) return browser;/);
  assert.match(source, /return \{\n    \.\.\.browser,/);
});
