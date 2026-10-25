/**
 * "Link sent to <address>" names the address the link really went to (security
 * review R1-1). The API mails the link to the account it signs into (lowercased,
 * "+tag" dropped) and answers `sent_to`; the card shows that, never the typed one.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const src = readFileSync(new URL("./sign-in.tsx", import.meta.url), "utf8");

test("the link-sent card shows the API's sent_to, not the typed email", () => {
  assert.match(src, /setSentTo\(typeof data\?\.sent_to === "string" && data\.sent_to \? data\.sent_to : null\)/);
  assert.match(src, /To <b>\{sentTo\}<\/b>/);
  assert.doesNotMatch(src, /To <b>\{email\}<\/b>/);
});
