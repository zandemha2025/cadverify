import { test } from "node:test";
import assert from "node:assert/strict";

import { loginHrefForReturnPath, safeLocalPath } from "./safe-return-path.ts";

test("safeLocalPath preserves a local route, query, and hash", () => {
  assert.equal(
    safeLocalPath("/designs?revision=2#evidence"),
    "/designs?revision=2#evidence",
  );
});

test("safeLocalPath rejects external and protocol-relative destinations", () => {
  assert.equal(safeLocalPath("https://attacker.example/path"), "/verify");
  assert.equal(safeLocalPath("//attacker.example/path"), "/verify");
  assert.equal(safeLocalPath("not-a-path"), "/verify");
});

test("loginHrefForReturnPath encodes the protected destination", () => {
  assert.equal(
    loginHrefForReturnPath("/designs?revision=2"),
    "/login?next=%2Fdesigns%3Frevision%3D2",
  );
  assert.equal(loginHrefForReturnPath("https://attacker.example"), "/login");
});
