/**
 * Every screen that navigates to a `next` (or the API's `redirect`) after
 * sign-in routes it through the one helper, safeLocalPath, which refuses what
 * normalises to another site (security review R4, F1). A local copy of the
 * check is how the magic-link page kept the bypass after the helper was fixed.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const src = new URL("../", import.meta.url);
const read = (p: string) => readFileSync(new URL(p, src), "utf8");

const CONSUMERS = [
  "app/(auth)/login/login-form.tsx",
  "app/(auth)/signup/signup-form.tsx",
  "app/(auth)/login/two-step/legacy-two-step.tsx",
  "app/(auth)/magic/verify/magic-verify-client.tsx",
  "components/v4/moments/sign-in.tsx",
  "components/v4/moments/sign-up.tsx",
  "components/v4/moments/magic.tsx",
  "components/v4/moments/two-step.tsx",
  "components/v4/moments/phone-page.tsx",
  "components/v4/moments/invite-next.ts",
];

for (const file of CONSUMERS) {
  test(`${file} checks its return path with the shared safeLocalPath`, () => {
    const text = read(file);
    assert.match(text, /import \{[^}]*\bsafeLocalPath\b[^}]*\} from "(@\/lib|(\.\.\/)+lib)\/safe-return-path(\.ts)?"/);
    assert.doesNotMatch(text, /function safeLocalPath\s*\(/, "a local copy of the check");
  });
}

test("the magic-link page sends its fragment next and the API's redirect through the helper", () => {
  const text = read("app/(auth)/magic/verify/magic-verify-client.tsx");
  assert.match(text, /safeLocalPath\(requestedNext/);
  assert.match(text, /safeLocalPath\(data\?\.two_step \? null : data\?\.redirect/);
});
