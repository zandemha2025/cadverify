import assert from "node:assert/strict";
import test from "node:test";

import { directUploadConnectOrigin } from "./direct-upload-csp.ts";

test("accepts one exact HTTPS object-store origin", () => {
  assert.equal(
    directUploadConnectOrigin(
      "https://proofshape-incoming.s3.us-east-1.amazonaws.com",
      "production",
    ),
    "https://proofshape-incoming.s3.us-east-1.amazonaws.com",
  );
});

test("allows loopback HTTP only for local proof runs", () => {
  assert.equal(
    directUploadConnectOrigin("http://127.0.0.1:5001", "dev"),
    "http://127.0.0.1:5001",
  );
  assert.throws(
    () => directUploadConnectOrigin("http://127.0.0.1:5001", "production"),
    /must use HTTPS/,
  );
});

test("rejects broad, credentialed, and path-scoped CSP inputs", () => {
  for (const value of [
    "https://*.amazonaws.com",
    "https://user:secret@example.com",
    "https://example.com/upload",
    "https://example.com?bucket=x",
  ]) {
    assert.throws(() => directUploadConnectOrigin(value, "production"));
  }
});

test("empty configuration adds no connect source", () => {
  assert.equal(directUploadConnectOrigin(undefined, "dev"), null);
  assert.equal(directUploadConnectOrigin("  ", "production"), null);
});
