import { test } from "node:test";
import assert from "node:assert/strict";
import { askerLine, bytesText, dayOf, downloadHref, packagePartLine, partFigs } from "./supplier-view.ts";

test("a supplier's view of a part: quantity, material and size in plain words", () => {
  assert.deepEqual(partFigs({ quantity: 250, yearly_volume: null, material: "Aluminum", bbox_mm: [300, 200, 10.8] }, "300 × 200 × 11 mm"), [
    { k: "Quantity", v: "250", s: "parts to quote" },
    { k: "Material", v: "Aluminum", s: "as the part was checked" },
    { k: "Size", v: "300 × 200 × 11 mm", s: "measured from the CAD" },
  ]);
  assert.equal(partFigs({ quantity: null, yearly_volume: null, material: null, bbox_mm: null }, "")[0].v, "Not given");
  assert.equal(partFigs({ quantity: 250, yearly_volume: 1000, material: null, bbox_mm: null }, "")[0].s, "1,000 a year");
});

test("a package's lines, who asks, dates, sizes and download links", () => {
  assert.equal(askerLine({ name: "Marcus Bell", company: "Kestrel CM", email: "m@kestrel.example" }), "Marcus Bell, Kestrel CM, m@kestrel.example");
  assert.equal(askerLine({ name: null, company: null, email: null }), "Not given");
  assert.equal(dayOf("2026-11-05"), "5 Nov 2026");
  assert.equal(bytesText(29_800), "29 KB");
  assert.equal(downloadHref("/s/pkg/Ab3dEf6hIj9K/cad/2"), "/api/public-share/s/pkg/Ab3dEf6hIj9K/cad/2");
  assert.equal(packagePartLine({ line: 1, name: "plate", filename: "plate.step", part_number: "KCM-1022", description: null, material: "Aluminum", quantity: 250, yearly_volume: 250, process: null, size: "300 × 200 × 10.8 mm", specs: [], must_hold: [], cad: null }),
    "Part number KCM-1022 · Aluminum · quantity 250 · 250 a year · 300 × 200 × 10.8 mm");
});
