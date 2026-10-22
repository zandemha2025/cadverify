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

test("safeLocalPath rejects paths that collapse into another site after parsing", () => {
  for (const raw of [
    "/.//evil.example",
    "/..//evil.example",
    "/%2e//evil.example",
    "/a/..//evil.example",
    "/./\\evil.example",
    "/.//evil.example/path?x=1#y",
  ]) {
    const out = safeLocalPath(raw);
    assert.equal(out, "/verify", raw);
    assert.equal(new URL(out, "https://scalecad.ai").origin, "https://scalecad.ai", raw);
  }
  assert.equal(loginHrefForReturnPath("/.//evil.example"), "/login");
});

test("the magic-link page uses the shared return-path check", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(
    new URL("../app/(auth)/magic/verify/magic-verify-client.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /import \{ safeLocalPath \} from "@\/lib\/safe-return-path"/);
  assert.doesNotMatch(source, /function safeLocalPath/);
});
