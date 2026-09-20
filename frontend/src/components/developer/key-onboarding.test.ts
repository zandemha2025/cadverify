import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("developer key creation names the key and reveals only the mutation response", async () => {
  const button = await readFile(new URL("./KeyMutationButton.tsx", import.meta.url), "utf8");
  const modal = await readFile(new URL("../RevealOnceModal.tsx", import.meta.url), "utf8");
  const proxy = await readFile(new URL("../../app/api/proxy/[...path]/route.ts", import.meta.url), "utf8");

  assert.match(button, /JSON\.stringify\(\{ name \}\)/);
  assert.match(button, /new CustomEvent<KeyRevealDetail>/);
  assert.match(button, /payload\.token/);
  assert.doesNotMatch(button, /JSON\.stringify\(\{ name: "Default" \}\)/);
  assert.match(modal, /event as CustomEvent<KeyRevealDetail>/);
  assert.doesNotMatch(proxy, /relayed\.append\("set-cookie", revealCookie\)/);
});
