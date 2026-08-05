import assert from "node:assert/strict";
import { test } from "node:test";

import { cloudFrontViewerIp, requestClientIp } from "./auth-proxy-ip.ts";

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
  });

  assert.equal(requestClientIp(req, "fly"), "198.51.100.1");
  assert.equal(requestClientIp(req, "nginx"), "198.51.100.2");
  assert.equal(requestClientIp(req, "cloudfront"), "198.51.100.4");
  assert.equal(requestClientIp(req, "unknown"), null);
});

test("ALB X-Forwarded-For is never treated as an authenticated viewer source", () => {
  const req = request({ "x-forwarded-for": "198.51.100.8, 10.0.1.4" });
  for (const source of ["fly", "nginx", "cloudfront", "auto"]) {
    assert.equal(requestClientIp(req, source), null);
  }
});
