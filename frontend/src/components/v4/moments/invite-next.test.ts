import assert from "node:assert/strict";
import test from "node:test";
import { inviteNext } from "./invite-next.ts";

test("an invite opens the run it was sent for, and only a page in the app (oo-18)", () => {
  assert.equal(inviteNext("/app/many/01M5H5DZATJCQAN6SMMTGCCYD7"), "/app/many/01M5H5DZATJCQAN6SMMTGCCYD7");
  for (const bad of ["https://evil.example/app/x", "//evil.example", "/app//x", "/app/../x", "/login", "", null]) assert.equal(inviteNext(bad), null);
});
