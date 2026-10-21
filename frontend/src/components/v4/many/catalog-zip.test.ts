import assert from "node:assert/strict";
import test from "node:test";
import { crc32, storedZip } from "./catalog-zip.ts";

test("CRC-32 matches the standard check value", () => {
  assert.equal(crc32(new TextEncoder().encode("123456789")), 0xcbf43926);
  const whole = crc32(new TextEncoder().encode("hello world"));
  const split = crc32(new TextEncoder().encode(" world"), crc32(new TextEncoder().encode("hello")));
  assert.equal(split, whole);
});

/** Reads a stored ZIP back through its central directory, as any unzip does. */
function readStored(buf: Uint8Array): { name: string; data: string; crc: number }[] {
  const v = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const endAt = buf.length - 22;
  assert.equal(v.getUint32(endAt, true), 0x06054b50);
  const n = v.getUint16(endAt + 10, true);
  let at = v.getUint32(endAt + 16, true);
  const out = [];
  const dec = new TextDecoder();
  for (let i = 0; i < n; i++) {
    assert.equal(v.getUint32(at, true), 0x02014b50);
    const crc = v.getUint32(at + 16, true);
    const size = v.getUint32(at + 20, true);
    const nameLen = v.getUint16(at + 28, true);
    const local = v.getUint32(at + 42, true);
    const name = dec.decode(buf.subarray(at + 46, at + 46 + nameLen));
    assert.equal(v.getUint32(local, true), 0x04034b50);
    assert.equal(v.getUint16(local + 8, true), 0, "stored");
    const lname = v.getUint16(local + 26, true);
    const start = local + 30 + lname;
    const data = buf.subarray(start, start + size);
    assert.equal(crc32(data), crc);
    out.push({ name, data: dec.decode(data), crc });
    at += 46 + nameLen;
  }
  return out;
}

test("a stored ZIP of many files keeps folders, renames exact repeats and reads back byte for byte", async () => {
  let seen = 0;
  const zip = await storedZip(
    [
      { name: "catalog/brackets/a.step", data: new Blob(["ISO-10303-21;"]) },
      { name: "b.stl", data: new Blob(["solid b\nendsolid b\n"]) },
      { name: "b.stl", data: new Blob(["solid c\nendsolid c\n"]) },
      { name: "pièce é.igs", data: new Blob([""]) },
    ],
    (done) => {
      seen = done;
    },
    new Date(2026, 9, 21, 12, 30, 10),
  );
  const entries = readStored(new Uint8Array(await zip.arrayBuffer()));
  assert.deepEqual(entries.map((e) => [e.name, e.data]), [
    ["catalog/brackets/a.step", "ISO-10303-21;"],
    ["b.stl", "solid b\nendsolid b\n"],
    ["b_1.stl", "solid c\nendsolid c\n"],
    ["pièce é.igs", ""],
  ]);
  assert.equal(seen, 13 + 19 + 19);
  assert.equal(zip.type, "application/zip");
});
