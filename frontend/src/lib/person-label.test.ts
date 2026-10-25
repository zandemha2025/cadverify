import { test } from "node:test";
import assert from "node:assert/strict";

import { DELETED_ACCOUNT, isDeletedAccount, personLabel } from "./person-label.ts";

test("a deleted account's tombstone address or redacted actor reads Deleted account", () => {
  assert.equal(personLabel("deleted-account-52@deleted.invalid"), DELETED_ACCOUNT);
  assert.equal(DELETED_ACCOUNT, "Deleted account");
  assert.equal(personLabel("Deleted-Account-7@DELETED.invalid", null), "Deleted account");
  assert.equal(personLabel("deleted account"), "Deleted account");
  assert.ok(isDeletedAccount(" deleted-account-1@deleted.invalid "));
});

test("a person reads as their name, else their email, and only the exact tombstone shape is a deleted account", () => {
  assert.equal(personLabel("dana@northfieldpumps.com", "Dana Ortiz"), "Dana Ortiz");
  assert.equal(personLabel("dana@northfieldpumps.com"), "dana@northfieldpumps.com");
  assert.equal(personLabel(null), null);
  for (const email of ["deleted-account-x@deleted.invalid", "deleted-account-5@deleted.invalid.com", "dana+deleted-account-5@deleted.invalid.example.com"]) {
    assert.equal(isDeletedAccount(email), false);
    assert.equal(personLabel(email), email);
  }
});
