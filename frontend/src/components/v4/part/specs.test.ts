import test from "node:test";
import assert from "node:assert/strict";
import { derivedNadcap, draftFrom, mustHold, normalizeSpecs, parseRa, raText, sameSpecs, specExclusions, specLines, specsChangedSinceRun, specsFromDraft, toggle, toleranceText } from "./specs.ts";

test("stored specs normalize: duplicates and standard inspection drop, Ra keeps its unit", () => {
  assert.equal(normalizeSpecs(null), null);
  assert.equal(normalizeSpecs({ inspection: ["standard"] }), null);
  assert.deepEqual(normalizeSpecs({ finishes: ["bead_blast", "bead_blast"], ra_um: 0.8128, ra_unit: "uin" }), {
    finishes: ["bead_blast"],
    ra_um: 0.8128,
    ra_unit: "uin",
  });
});

test("Ra typed in either unit, exact, and checked against the range", () => {
  assert.deepEqual(parseRa("0.8", "um"), { um: 0.8, unit: "um", error: null });
  assert.deepEqual(parseRa("32", "uin"), { um: 0.8128, unit: "uin", error: null });
  assert.deepEqual(parseRa("32 µin", "um"), { um: 0.8128, unit: "uin", error: null });
  assert.equal(parseRa("1,6um", "uin").um, 1.6);
  assert.match(parseRa("smooth", "um").error ?? "", /must be a number/);
  assert.match(parseRa("80", "um").error ?? "", /from 0.012 to 50/);
  assert.equal(parseRa("", "um").um, null);
  assert.equal(raText({ ra_um: 0.8128, ra_unit: "uin" }), "Ra 32 µin (0.813 µm)");
});

test("the editor round-trips a declaration and says what's missing", () => {
  const stored = { finishes: ["anodize_iii"], ra_um: 0.8128, ra_unit: "uin" as const, certifications: ["as9100", "nadcap"] };
  const d = draftFrom(stored);
  assert.equal(d.ra, "32");
  assert.equal(d.raUnit, "uin");
  const back = specsFromDraft(d);
  assert.deepEqual(back.errors, []);
  assert.ok(sameSpecs(back.specs, stored));
  assert.deepEqual(specsFromDraft({ ...d, finishes: [], certs: ["nadcap"] }).errors, ["Name the NADCAP special process, for example heat treating."]);
  assert.deepEqual(specsFromDraft(draftFrom(null)), { specs: null, errors: [] });
});

test("as machined and the named finishes exclude each other", () => {
  assert.deepEqual(toggle(["bead_blast"], "as_machined", "finishes"), ["as_machined"]);
  assert.deepEqual(toggle(["as_machined"], "anodize_ii", "finishes"), ["anodize_ii"]);
  assert.deepEqual(toggle(["as9100"], "itar"), ["as9100", "itar"]);
  assert.deepEqual(toggle(["as9100", "itar"], "as9100"), ["itar"]);
});

test("what whoever makes it must hold, NADCAP named by the special process", () => {
  const s = { finishes: ["anodize_ii"], heat_treatments: ["solution_age"], certifications: ["as9100", "nadcap", "itar"] };
  assert.deepEqual(derivedNadcap(s), ["chemical_processing", "heat_treating"]);
  assert.deepEqual(mustHold(s), ["AS9100", "NADCAP, chemical processing", "NADCAP, heat treating", "ITAR registration"]);
  assert.deepEqual(specLines({ ...s, ra_um: 1.6, ra_unit: "um" }), [
    "Anodize, Type II, Ra 1.6 µm",
    "Solution treat and age",
    "Supplier must hold AS9100, NADCAP, chemical processing, NADCAP, heat treating, ITAR registration",
  ]);
});

test("the check's own record of the specs tells when they changed", () => {
  const cost = { specs: { declared: { finishes: ["bead_blast"] } } };
  assert.equal(specsChangedSinceRun(cost, { finishes: ["bead_blast"] }), false);
  assert.equal(specsChangedSinceRun(cost, { finishes: ["anodize_ii"] }), true);
  assert.equal(specsChangedSinceRun({ specs: null }, null), false);
  assert.equal(specsChangedSinceRun({}, { ra_um: 0.8 }), true);
  assert.equal(specsChangedSinceRun(null, { ra_um: 0.8 }), false);
});

test("routes the specs rule out, once each", () => {
  const ex = specExclusions([
    { process: "fdm", quantity: 1, spec_excluded: true, spec_exclusion_reason: "FDM prints at Ra 10–25 µm", spec_findings: [{ code: "SPEC_RA_UNREACHABLE", message: "m" }] },
    { process: "fdm", quantity: 10, spec_excluded: true, spec_exclusion_reason: "FDM prints at Ra 10–25 µm" },
    { process: "cnc_3axis", quantity: 1 },
  ]);
  assert.equal(ex.length, 1);
  assert.equal(ex[0].process, "fdm");
  assert.equal(ex[0].findings[0].code, "SPEC_RA_UNREACHABLE");
});

test("a general tolerance is an ISO 2768 class or a ± value; it reaches the specs line but not the stale check (buyer-06, buyer-15)", () => {
  const iso = specsFromDraft({ ...draftFrom(null), tolKind: "iso", tolIso: "m" });
  assert.deepEqual(iso, { specs: { general_tolerance: { iso2768: "m" } }, errors: [] });
  assert.deepEqual(specLines(iso.specs), ["General tolerance ISO 2768-m (medium)"]);
  const inch = specsFromDraft({ ...draftFrom(null), tolKind: "pm", tolValue: "±0.005", tolUnit: "in" });
  assert.deepEqual(inch.specs, { general_tolerance: { plus_minus: 0.005, unit: "in" } });
  assert.equal(toleranceText(inch.specs!.general_tolerance), "±0.005 in (0.127 mm)");
  assert.deepEqual(draftFrom(inch.specs).tolValue, "0.005");
  assert.match(specsFromDraft({ ...draftFrom(null), tolKind: "pm", tolValue: "20", tolUnit: "mm" }).errors[0], /at most ±10 mm/);
  assert.match(specsFromDraft({ ...draftFrom(null), tolKind: "pm", tolValue: "abc", tolUnit: "mm" }).errors[0], /number above 0/);
  // The price doesn't use the tolerance: a record priced without it isn't out of date.
  const cost = { specs: { declared: { finishes: ["anodize_ii"] } } };
  assert.equal(specsChangedSinceRun(cost, { finishes: ["anodize_ii"], general_tolerance: { iso2768: "f" } }), false);
  assert.equal(specsChangedSinceRun(cost, { finishes: ["bead_blast"], general_tolerance: { iso2768: "f" } }), true);
  assert.equal(sameSpecs({ general_tolerance: { iso2768: "f" } }, { general_tolerance: { iso2768: "m" } }), false);
});
