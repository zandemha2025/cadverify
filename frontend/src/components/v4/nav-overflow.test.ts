import { test } from "node:test";
import assert from "node:assert/strict";

const { navOverflow } = await import("./nav-overflow.ts");

test("the tab row fades the edge that has more tabs past it", () => {
  assert.deepEqual(navOverflow(0, 366, 366), { left: false, right: false });
  assert.deepEqual(navOverflow(0, 366, 520), { left: false, right: true });
  assert.deepEqual(navOverflow(80, 366, 520), { left: true, right: true });
  assert.deepEqual(navOverflow(154, 366, 520), { left: true, right: false });
});
