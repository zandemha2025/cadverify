import { test } from "node:test";
import assert from "node:assert/strict";
import type { CostDecisionSummary } from "@/lib/api";
import type { PackagePreviewItem } from "./api";
import { pickerLine } from "./package-words.ts";

const row = { id: "01M5J2JGBJG0QJY3MNC1EB4J2D", filename: "bored-block-mm.iges", make_now_process: "cnc_3axis", quantities: [1, 250, 1000], user_disposition_label: null } as unknown as CostDecisionSummary;
const at = (quantity: number | null, price: PackagePreviewItem["price"]): PackagePreviewItem =>
  ({ id: row.id, name: row.filename, part_number: null, material: "Aluminum", quantity, quantity_source: "run", yearly_volume: null, specs: [], price, cad_kept: null, cad_too_large: false });

test("the picker prices each record at its quantity, with the pick there, never at 1 (buyer-11)", () => {
  // The block at 250: the part page's pick is wire-arc printing, not the 1-off milling.
  assert.deepEqual(pickerLine(row, at(250, { quantity: 250, unit_cost_usd: 3.68, process: "waam", dfm_ready: true })), {
    price: "$3.68 at 250", what: "ScaleCAD’s pick at 250: Wire-arc printing (WAAM)" });
  assert.deepEqual(pickerLine(row, at(1200, null)), { price: "", what: "Not priced at 1,200" });
  assert.deepEqual(pickerLine(row, at(null, null)), { price: "", what: "No quantity set" });
  // No quantity asked for: priced where the part page opens, and it says so.
  assert.deepEqual(pickerLine(row, at(null, { quantity: 100, unit_cost_usd: 30.76, process: "fdm", dfm_ready: true, basis: "part_page" })), {
    price: "$30.76 at 100", what: "ScaleCAD’s pick at 100: filament printing (FDM/FFF) · no quantity set" });
  // Before the preview answers, the record's own line and no price.
  assert.deepEqual(pickerLine(row, undefined), { price: "", what: "ScaleCAD’s pick: 3-axis milling" });
});
