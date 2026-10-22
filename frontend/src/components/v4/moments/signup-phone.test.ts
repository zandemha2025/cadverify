import { test } from "node:test";
import assert from "node:assert/strict";

const { CODE_FRESH_MS, clearSignupPhone, gateStart, readSignupPhone, rememberSignupPhone } = await import("./signup-phone.ts");

function memory() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
}

test("a code sent at sign-up opens the phone check on the code, with the resend wait left", () => {
  const store = memory();
  rememberSignupPhone(store, { phone: "+1 616 555 0142", sentAt: 1_000_000, error: null });
  const start = gateStart(readSignupPhone(store, 1_012_000), null, 1_012_000);
  assert.deepEqual(start, { step: "code", phone: "+1 616 555 0142", error: null, resendIn: 18 });
});

test("a code that didn't go keeps the number and says why", () => {
  const store = memory();
  rememberSignupPhone(store, { phone: "+1 616 555 0142", sentAt: null, error: "That number is already linked to another ScaleCAD account." });
  assert.deepEqual(gateStart(readSignupPhone(store), "+16165550199"), {
    step: "phone",
    phone: "+1 616 555 0142",
    error: "That number is already linked to another ScaleCAD account.",
    resendIn: 0,
  });
});

test("an old code asks to send again; nothing from sign-up uses the number on the account", () => {
  const store = memory();
  rememberSignupPhone(store, { phone: "+16165550142", sentAt: 0, error: null });
  assert.equal(gateStart(readSignupPhone(store, CODE_FRESH_MS + 1), null).step, "phone");
  clearSignupPhone(store);
  assert.equal(readSignupPhone(store), null);
  assert.deepEqual(gateStart(null, "+16165550142"), { step: "phone", phone: "+16165550142", error: null, resendIn: 0 });
  assert.deepEqual(gateStart(null, null), { step: "phone", phone: "", error: null, resendIn: 0 });
});

test("storage that throws or holds junk reads as nothing", () => {
  const broken = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); }, removeItem: () => undefined };
  rememberSignupPhone(broken, { phone: "+1", sentAt: 1, error: null });
  assert.equal(readSignupPhone(broken), null);
  const junk = memory();
  junk.setItem("scalecad.signup-phone", "{not json");
  assert.equal(readSignupPhone(junk), null);
  assert.equal(readSignupPhone(null), null);
});
