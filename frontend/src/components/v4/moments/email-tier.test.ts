import { test } from "node:test";
import assert from "node:assert/strict";
import { emailTier, tierHint } from "./email-tier.ts";

test("work and personal domains", () => {
  assert.equal(emailTier("austin@acme-aero.com"), "work");
  assert.equal(emailTier("someone@gmail.com"), "personal");
  assert.equal(emailTier("Some.One+x@GMAIL.COM"), "personal");
  assert.equal(emailTier("me@icloud.com."), "personal");
  assert.equal(emailTier("me@sub.gmail.com"), "work");
});

test("not an address yet", () => {
  for (const v of ["", "austin", "austin@", "austin@acme", "a b@acme.com", "@acme.com"]) assert.equal(emailTier(v), null, v);
});

test("hint text uses the live allowance sizes", () => {
  const free = { work: 15, personal: 3 };
  assert.deepEqual(tierHint("a@acme-aero.com", free), { tone: "ok", chip: "15 free checks", text: "Work email" });
  assert.deepEqual(tierHint("a@gmail.com", free), { tone: "warn", chip: "3 free checks", text: "Personal email · work email gets 15" });
  assert.deepEqual(tierHint("a", { work: 20, personal: 5 }), { tone: "unk", chip: "Free checks", text: "Work email 20 · personal 5" });
});
