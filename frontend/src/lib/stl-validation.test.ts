import { test } from "node:test";
import assert from "node:assert/strict";

import {
  CLIENT_STL_CORRUPT_MESSAGE,
  clientStlIntegrityError,
} from "./stl-validation.ts";

function binaryStl(declaredTriangles: number, actualTriangles: number): File {
  const bytes = new Uint8Array(84 + actualTriangles * 50);
  new DataView(bytes.buffer).setUint32(80, declaredTriangles, true);
  return new File([bytes], "cube.stl", { type: "model/stl" });
}

test("one-byte STL gets the plain client refusal before parsing", async () => {
  const file = new File([new Uint8Array([0])], "one-byte.stl", { type: "model/stl" });
  assert.equal(await clientStlIntegrityError(file), CLIENT_STL_CORRUPT_MESSAGE);
});

test("truncated binary STL gets the plain client refusal", async () => {
  assert.equal(await clientStlIntegrityError(binaryStl(12, 11)), CLIENT_STL_CORRUPT_MESSAGE);
});

test("complete binary STL passes the bounded client integrity check", async () => {
  assert.equal(await clientStlIntegrityError(binaryStl(12, 12)), null);
});
