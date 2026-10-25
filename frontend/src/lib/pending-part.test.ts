import { test } from "node:test";
import assert from "node:assert/strict";

import {
  holdPendingPart,
  normalizeEmail,
  peekPendingPart,
  takePendingPart,
  PENDING_PART_TTL_MS,
  type PendingPartRecord,
  type PendingPartStore,
} from "./pending-part.ts";

function memoryStore(): PendingPartStore & { record?: PendingPartRecord } {
  const store: PendingPartStore & { record?: PendingPartRecord } = {
    async get() { return store.record; },
    async set(record) { store.record = record; },
    async clear() { store.record = undefined; },
  };
  return store;
}

const part = () => new File([new Uint8Array([1, 2, 3])], "bracket-rev4.step", { type: "application/step", lastModified: 1700000000000 });

test("a held part checks itself once, for the account that dropped it", async () => {
  const store = memoryStore();
  assert.equal(await holdPendingPart(store, part(), "Austin.Lee+cad@gmail.com", 1000), true);
  assert.deepEqual(await peekPendingPart(store, 2000), { name: "bracket-rev4.step", email: "austinlee@gmail.com" });
  const file = await takePendingPart(store, "austinlee@gmail.com", 2000);
  assert.ok(file);
  assert.equal(file.name, "bracket-rev4.step");
  assert.equal(file.type, "application/step");
  assert.deepEqual(new Uint8Array(await file.arrayBuffer()), new Uint8Array([1, 2, 3]));
  assert.equal(await takePendingPart(store, "austinlee@gmail.com", 2000), null);
});

test("another account on the same browser never receives the held part", async () => {
  const store = memoryStore();
  await holdPendingPart(store, part(), "austin@acme-aero.com", 1000);
  assert.equal(await takePendingPart(store, "someone-else@acme-aero.com", 2000), null);
  assert.equal(store.record, undefined, "cleared rather than kept for the next sign-in");
});

test("held parts expire", async () => {
  const store = memoryStore();
  await holdPendingPart(store, part(), "austin@acme-aero.com", 0);
  assert.equal(await peekPendingPart(store, PENDING_PART_TTL_MS + 1), null);
  assert.equal(await takePendingPart(store, "austin@acme-aero.com", PENDING_PART_TTL_MS + 1), null);
});

test("empty, oversized or unstorable parts are refused, not thrown", async () => {
  const store = memoryStore();
  assert.equal(await holdPendingPart(store, new File([], "empty.stl"), "a@b.co"), false);
  assert.equal(await holdPendingPart(store, part(), "no-email"), false);
  const broken: PendingPartStore = { get: async () => { throw new Error("blocked"); }, set: async () => { throw new Error("blocked"); }, clear: async () => {} };
  assert.equal(await holdPendingPart(broken, part(), "a@b.co"), false);
  assert.equal(await takePendingPart(broken, "a@b.co"), null);
  assert.equal(await peekPendingPart(broken), null);
});

test("email normalization matches the backend", () => {
  assert.equal(normalizeEmail("J.Doe+test@Gmail.com"), "jdoe@gmail.com");
  assert.equal(normalizeEmail("j.doe+test@acme.com"), "j.doe@acme.com");
});
