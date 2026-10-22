import test from "node:test";
import assert from "node:assert/strict";
import { area, dims, inText, len, lenValue, mass, parseLen, volume } from "./units.ts";

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

test("in inches, weights read in lb and prices per kg per lb (me-04)", () => {
  // 46.6 kg × 2.20462262 = 102.735 lb; 15.2 kg = 33.51 lb; 0.023 kg = 0.0507 lb = 0.81 oz.
  assert.equal(mass(46.6, "in"), "102.7 lb");
  assert.equal(mass(15.2, "in"), "33.5 lb");
  assert.equal(mass(0.023, "in"), "0.81 oz");
  assert.equal(mass(2.5, "in"), "5.51 lb");
  assert.equal(mass(46.6, "mm"), "46.6 kg");
  assert.equal(inText("machine time on your Haas VF-2 · 46.6 kg AISI 4140 · $37.67 each", "in"), "machine time on your Haas VF-2 · 102.7 lb AISI 4140 · $37.67 each");
  assert.equal(inText("part 40.0kg > machine max 20.0kg", "in"), "part 88.2 lb > machine max 44.1 lb");
  // $4.00/kg × 0.45359237 = $1.81/lb; $12/m² ÷ 10.7639 = $1.11/ft².
  assert.equal(inText("0.84 kg × $4.00/kg", "in"), "1.85 lb × $1.81/lb");
  assert.equal(inText("anodize $12/m² × 0.012 m²", "in"), "anodize $1.11/ft² × 0.13 ft²");
  // Grams of material read in oz; a density (g/cm³) and an alloy name are left alone.
  assert.equal(inText("13.6 g of PLA, density 1.24 g/cm³, AlSi10Mg", "in"), "0.48 oz of PLA, density 1.24 g/cm³, AlSi10Mg");
  assert.equal(inText("46.6 kg AISI 4140", "mm"), "46.6 kg AISI 4140");
});

test("a corner radius says its unit: R2 in engine text is 2 mm (me-04)", () => {
  assert.equal(inText("0.472 in deep takes Ø4 mm or more: at least R2.", "in"), "0.472 in deep takes Ø0.157 in or more: at least R0.079 in.");
  assert.equal(inText("at least R2 mm. R0.7 mm lets a stiffer cutter run", "in"), "at least R0.079 in. R0.028 in lets a stiffer cutter run");
  assert.equal(inText("Ra 0.8 µm, PA12, R2", "mm"), "Ra 0.8 µm, PA12, R2");
});
