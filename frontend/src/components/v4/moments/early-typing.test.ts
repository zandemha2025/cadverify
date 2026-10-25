import { test } from "node:test";
import assert from "node:assert/strict";

const { adoptTyped } = await import("./early-typing.ts");

test("text typed before hydration goes into state; empty fields and missing ones are left alone", () => {
  const dom: Record<string, { value: string }> = { name: { value: "Dana Ruiz" }, email: { value: "dana@ridgelinefluid.com" }, phone: { value: "" } };
  const form = { elements: { namedItem: (n: string) => dom[n] ?? null } };
  const got: Record<string, string> = {};
  adoptTyped(form, {
    name: (v) => (got.name = v),
    email: (v) => (got.email = v),
    phone: (v) => (got.phone = v),
    password: (v) => (got.password = v),
  });
  assert.deepEqual(got, { name: "Dana Ruiz", email: "dana@ridgelinefluid.com" });
  adoptTyped(null, { name: () => assert.fail("no form, nothing read") });
});
