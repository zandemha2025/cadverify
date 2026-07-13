import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("API-key mutations use finite same-origin responses before refresh", async () => {
  const button = await readFile(new URL("./KeyMutationButton.tsx", import.meta.url), "utf8");
  const modal = await readFile(new URL("../RevealOnceModal.tsx", import.meta.url), "utf8");
  const proxy = await readFile(
    new URL("../../app/api/proxy/[...path]/route.ts", import.meta.url),
    "utf8",
  );
  const page = await readFile(
    new URL("../../app/(app)/settings/developer/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(button, /const text = await response\.text\(\)/);
  assert.match(button, /window\.dispatchEvent\(new Event\(KEY_REVEAL_EVENT\)\)/);
  assert.ok(button.indexOf("await response.text()") < button.indexOf("router.refresh()"));
  assert.match(modal, /addEventListener\(KEY_REVEAL_EVENT, readRevealCookie\)/);
  assert.match(modal, /removeEventListener\(KEY_REVEAL_EVENT, readRevealCookie\)/);
  assert.match(proxy, /path\[0\] === "keys"/);
  assert.match(proxy, /revealCookie\?\.startsWith\("cv_mint_once="\)/);
  assert.doesNotMatch(page, /<form\s+action=/);
  assert.doesNotMatch(page, /createDefaultKey|rotateKey\(|revokeKey\(/);
});
