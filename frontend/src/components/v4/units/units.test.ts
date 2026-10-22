import test from "node:test";
import assert from "node:assert/strict";
import { area, dims, inText, len, lenValue, parseLen, volume } from "./units.ts";

test("lengths convert exactly and say their unit", () => {
  assert.equal(len(25.4, "mm"), "25.4 mm");
  assert.equal(len(25.4, "in"), "1.000 in");
  assert.equal(len(1306, "in", 0), "51.42 in");
  assert.equal(len(0.5, "in"), "0.020 in");
  assert.equal(len(null, "in"), "—");
  assert.equal(lenValue(50.8, "in"), "2");
  assert.equal(lenValue(12.34, "mm"), "12.3");
});

test("boxes, areas and volumes", () => {
  assert.equal(dims([100, 50, 20], "mm"), "100 × 50 × 20 mm");
  assert.equal(dims([100, 50, 20], "in"), "3.937 × 1.969 × 0.787 in");
  assert.equal(dims([], "in"), null);
  assert.equal(area(6.4516, "in"), "1 in²");
  assert.equal(area(100, "mm"), "100 cm²");
  assert.equal(volume(16.387064, "in"), "1 in³");
  assert.equal(volume(120.5, "mm"), "120.5 cm³");
});

test("inputs accept either unit", () => {
  assert.equal(parseLen("25.4", "mm"), 25.4);
  assert.equal(parseLen("1", "in"), 25.4);
  assert.equal(parseLen("1 in", "mm"), 25.4);
  assert.equal(parseLen('2"', "mm"), 50.8);
  assert.equal(parseLen("10 mm", "in"), 10);
  assert.equal(parseLen("3,5 mm", "in"), 3.5);
  assert.equal(parseLen("ten", "mm"), null);
});

test("engine text shows every mm figure in inches, and nothing else changes", () => {
  assert.equal(inText("too big for your BigRep ONE: needs 1306 mm, has 1005 mm (height)", "in"),
    "too big for your BigRep ONE: needs 51.42 in, has 39.57 in (height)");
  assert.equal(inText("Walls under 0.8 mm: thinnest 0.45 mm", "in"), "Walls under 0.031 in: thinnest 0.018 in");
  assert.equal(inText("Fits its 256 × 256 × 256 mm work area.", "in"), "Fits its 10.08 × 10.08 × 10.08 in work area.");
  assert.equal(inText("1–3 mm walls", "in"), "0.039–0.118 in walls");
  assert.equal(inText("Ra 0.8 µm on 12 parts at $45.00", "in"), "Ra 0.8 µm on 12 parts at $45.00");
  assert.equal(inText("volume 16.387064 cm³", "in"), "volume 1.000 in³");
  assert.equal(inText("needs 1306 mm", "mm"), "needs 1306 mm");
  assert.equal(inText(null, "in"), "");
});
