import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { emailTier, PERSONAL_DOMAINS } from "./email-tier.ts";

test("email feedback distinguishes incomplete, personal and work addresses", () => {
  for (const value of ["", "person", "person@", "person@company", "a@@b.com"]) assert.equal(emailTier(value), null);
  for (const domain of PERSONAL_DOMAINS) assert.equal(emailTier(`person@${domain}`), "personal");
  assert.equal(emailTier(" Person@GMAIL.COM "), "personal");
  assert.equal(emailTier("person@gmail.com.example.org"), "work");
  assert.equal(emailTier("engineer@factory.example"), "work");
});
test("signup feedback matches the server entitlement domain list", () => {
  const source = readFileSync(new URL("../../../../backend/src/auth/email_tier.py", import.meta.url), "utf8");
  const domains = [...source.matchAll(/"([a-z0-9.-]+\.[a-z]+)"/g)].map(match => match[1]);
  assert.deepEqual(domains.sort(), [...PERSONAL_DOMAINS].sort());
});
