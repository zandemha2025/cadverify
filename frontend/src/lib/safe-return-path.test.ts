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

// Security review R4 (F1): the URL parser removes dot segments and decodes %2e, so
// these came back as "//evil.example": another site for location.href and router.push.
const NORMALISE_TO_ANOTHER_HOST = [
  "/.//evil.example",
  "/..//evil.example",
  "/%2e//evil.example",
  "/a/..//evil.example",
  "/./\\evil.example",
  "/\t/evil.example",
  "/\n/evil.example",
];

for (const raw of NORMALISE_TO_ANOTHER_HOST) {
  test(`safeLocalPath never returns a path that opens another site for ${JSON.stringify(raw)}`, () => {
    const out = safeLocalPath(raw, "/verify");
    // What window.location.href = out / router.push(out) would open from the app.
    const landed = new URL(out, "https://cadverify.com");
    assert.equal(landed.origin, "https://cadverify.com", `navigates to ${landed.href}`);
    assert.ok(!out.startsWith("//") && !out.startsWith("/\\"), `returned ${out}`);
    assert.equal(out, "/verify");
    assert.equal(loginHrefForReturnPath(raw), "/login");
  });
}

test("safeLocalPath keeps an ordinary local path whose dot segments resolve on the site", () => {
  assert.equal(safeLocalPath("/app/parts?joined=1"), "/app/parts?joined=1");
  assert.equal(safeLocalPath("/a/../app/parts"), "/app/parts");
  assert.equal(safeLocalPath("/orgs/accept?token=abc&next=%2Fapp%2Fmany%2Fx"), "/orgs/accept?token=abc&next=%2Fapp%2Fmany%2Fx");
  assert.equal(safeLocalPath(42, "/x"), "/x");
  assert.equal(safeLocalPath(undefined, ""), "");
});
