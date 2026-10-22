import test from "node:test";
import assert from "node:assert/strict";
import { cm3Text, hoursText, massLine, massText, materialFromSource, materialShort, materialSub, ownershipOf, routeResources, runLine, timeLine } from "./resources.ts";

type AnyObj = Record<string, unknown>;

function est(process: string, material: string, quantity: number, drivers: AnyObj[], extra: AnyObj = {}) {
  return {
    process,
    material,
    quantity,
    unit_cost_usd: 10,
    fixed_cost_usd: 0,
    variable_cost_usd: 10,
    est_error_band_pct: 40,
    dfm_ready: true,
    dfm_verdict: "pass" as const,
    dfm_score: 1,
    dfm_blockers: [],
    line_items: {},
    drivers: drivers.map((d) => ({ unit: "$", provenance: "DEFAULT", source: "", error_band_pct: null, value: 0, ...d })),
    lead_time: { low_days: 1, high_days: 3, mid_days: 2, components: {}, capacity: {} },
    ...extra,
  } as never;
}

// Real derivations from staging records (the engine's own words).
const FDM_SRC =
  "filament 10.95 cm³ (shell 8.74 + 15% infill of the other 15.02 of 23.76 cm³) + no support = 10.95 cm³ × PLA density 1.24 g/cm³ (slicer-calibrated estimate, not a quote) = 0.0136 kg × $25/kg (material-DB unit price (DEFAULT book value)) × (1+0.1 scrap) × region-material ×1";
const CNC_SRC =
  "bounding-box billet 108.00 cm³ (oriented candidate 40×45×60 mm; minimum not certified) × 1.10 stock allowance × Delrin (POM) density 1.41 g/cm³ [assumption, not shop-validated] = 0.1675 kg × $5/kg (material-DB unit price (DEFAULT book value)) × (1+0.05 scrap)";
const FORGE_SRC =
  "billet from bar = net 0.0471 kg (CAD volume 6.00 cm³ × Mild Steel density 7.85 g/cm³) × (1+0.25 flash/scale loss) [forge assumption, not shop-validated] = 0.0589 kg × $1.5/kg (material-DB unit price (DEFAULT book value)) × (1+0.05 scrap)";
const SHEET_SRC = "sheet blank 40×50×6mm = 12.00 cm³ × 5052 Aluminum (Sheet) density 2.68 g/cm³ (rectangular blank) = 0.0322 kg × $4/kg (material-DB unit price)";
const MJF_SRC = "CAD volume 23.76 cm³ × PA12 (Nylon 12) density 1.01 g/cm³ = 0.0240 kg × $60/kg (material-DB unit price (DEFAULT book value)) × (1+0.1 scrap) × region-material ×1";

test("material mass and density come from the engine's own derivation", () => {
  assert.deepEqual(materialFromSource(FDM_SRC), { kg: 0.0136, density: 1.24 });
  assert.deepEqual(materialFromSource(CNC_SRC), { kg: 0.1675, density: 1.41 });
  // The net mass named first isn't the charged one: the mass right before "× $" is.
  assert.deepEqual(materialFromSource(FORGE_SRC), { kg: 0.0589, density: 7.85 });
  assert.deepEqual(materialFromSource(SHEET_SRC), { kg: 0.0322, density: 2.68 });
  assert.deepEqual(materialFromSource(""), { kg: null, density: null });
  assert.deepEqual(materialFromSource("material at a flat price"), { kg: null, density: null });
  assert.deepEqual(materialFromSource(undefined), { kg: null, density: null });
});

test("a route's resources: machine time per part and for the run, material used next to the part", () => {
  const e = est("fdm", "PLA", 100, [
    { name: "material_cost", value: 0.37, source: FDM_SRC },
    { name: "cycle_time", value: 0.5156, unit: "hr" },
    { name: "machine_cost", value: 4.12 },
  ]);
  const r = routeResources(e, 23.76)!;
  assert.equal(r.hoursEach, 0.5156);
  assert.ok(Math.abs(r.hoursRun! - 51.56) < 1e-9);
  assert.equal(r.kgEach, 0.0136);
  assert.ok(Math.abs(r.kgRun! - 1.36) < 1e-9);
  assert.ok(Math.abs(r.cm3Each! - 10.968) < 0.01);
  assert.equal(r.runningCostOnly, false);
  assert.equal(timeLine(r), "31 min each · 52 h for 100");
  assert.equal(massLine(r), "13.6 g each · 1.36 kg for 100");
  assert.equal(materialSub(r), "PLA · 11.0 cm³ printed · part 23.8 cm³");
  assert.equal(runLine(r), "52 h machine time · 1.36 kg PLA");
  assert.equal(runLine(r, { grade: false }), "52 h machine time · 1.36 kg");
  assert.equal(runLine(null), null);
});

test("the estimate's material_mass fields come first; a tiny part keeps its grams (round 7)", () => {
  // The derivation text of a 0.04 g part said "0.0000 kg"; the fields carry the real figure.
  const tiny = est("fdm", "PLA", 10, [
    { name: "material_cost", value: 0.001, source: "filament 0.03 cm³ ... = 0.0000 kg × $25/kg" },
    { name: "cycle_time", value: 0.01, unit: "hr" },
  ], { material_mass: { part_kg: 0.0000248, used_kg: 0.0000412, density_g_cm3: 1.24, usd_per_kg: 25 } });
  const r = routeResources(tiny, 0.02)!;
  assert.equal(r.kgEach, 0.0000412);
  assert.equal(r.density, 1.24);
  assert.ok(Math.abs(r.cm3Each! - 0.0332) < 1e-3);
  assert.equal(massText(r.kgEach), "<1 g");
  // A record without the fields still reads its derivation.
  const old = routeResources(est("fdm", "PLA", 1, [{ name: "material_cost", source: FDM_SRC }]), 23.76)!;
  assert.equal(old.kgEach, 0.0136);
  assert.equal(old.density, 1.24);
  // Fields win over a text that disagrees.
  const both = routeResources(est("fdm", "PLA", 1, [{ name: "material_cost", source: FDM_SRC }], { material_mass: { part_kg: 0.03, used_kg: 0.0141, density_g_cm3: 1.24, usd_per_kg: 25 } }), 23.76)!;
  assert.equal(both.kgEach, 0.0141);
});

test("same volume as the part reads once; machining names its stock", () => {
  const mjf = routeResources(est("mjf", "PA12 (Nylon 12)", 1, [{ name: "material_cost", source: MJF_SRC }, { name: "cycle_time", value: 0.5429, unit: "hr" }, { name: "owned_in_house", value: 0.65, unit: "×", provenance: "USER" }]), 23.76)!;
  assert.equal(materialSub(mjf), "PA12 (Nylon 12) · 23.8 cm³");
  assert.equal(timeLine(mjf), "33 min each");
  assert.equal(mjf.runningCostOnly, true);
  const cnc = routeResources(est("cnc_3axis", "Delrin (POM)", 10, [{ name: "material_cost", source: CNC_SRC }]), 23.76)!;
  assert.equal(materialSub(cnc), "Delrin (POM) · 119 cm³ of stock · part 23.8 cm³");
  assert.equal(materialShort(cnc), "Delrin (POM), 119 cm³ of stock");
  assert.equal(materialShort(mjf), "PA12 (Nylon 12), 23.8 cm³");
  assert.equal(cnc.hoursEach, null);
  assert.equal(timeLine(cnc), "—");
});

test("missing figures stay missing", () => {
  assert.equal(routeResources(null, 10), null);
  const r = routeResources(est("sla", "Standard Resin", 10, [{ name: "cycle_time", value: 1, unit: "min" }]), null)!;
  assert.equal(r.hoursEach, null, "a cycle time in another unit isn't read as hours");
  assert.equal(r.kgEach, null);
  assert.equal(massLine(r), "—");
  assert.equal(materialSub(r), "Standard Resin");
  assert.equal(runLine(r), null);
});

test("formatting", () => {
  assert.equal(hoursText(0.0002), "<1 min");
  assert.equal(hoursText(0.0241), "1 min");
  assert.equal(hoursText(2.41), "2.4 h");
  assert.equal(hoursText(1204.4), "1,204 h");
  assert.equal(hoursText(null), "—");
  assert.equal(massText(0.0004), "<1 g");
  assert.equal(massText(0.0043), "4.3 g");
  assert.equal(massText(0.27), "270 g");
  assert.equal(massText(1.27), "1.27 kg");
  assert.equal(massText(312.4), "312 kg");
  assert.equal(cm3Text(2.72), "2.72 cm³");
  assert.equal(cm3Text(1350), "1,350 cm³");
});

test("ownership: owned at running cost, a machine of yours that doesn't fit, or the machine it would need", () => {
  const mjf = routeResources(est("mjf", "PA12", 10, [{ name: "owned_in_house", value: 0.65, unit: "×" }]), 5)!;
  const shop = [{ name: "HP Jet Fusion 5200", process: "mjf" }, { name: "Haas VF-2", process: "cnc_3axis" }];
  assert.deepEqual(ownershipOf({ code: "mjf", inHouse: "HP Jet Fusion 5200", fit: null }, mjf, shop), {
    kind: "owned",
    v: "HP Jet Fusion 5200",
    s: "you own it · running cost only",
    machine: "HP Jet Fusion 5200",
  });
  const fit = { verdict: "makeable_not_on_owned", machines_evaluated: 1, best_machine: "Haas VF-2", failures: [{ axis: "material", gate: "material", need: "Delrin (POM)", have: ["steel"], human: "not qualified for Delrin (POM)" }] } as never;
  const nf = ownershipOf({ code: "cnc_3axis", inHouse: null, fit }, null, shop);
  assert.equal(nf.kind, "not_fit");
  assert.equal(nf.v, "Doesn't fit yours");
  assert.equal(nf.s, "Haas VF-2: not qualified for Delrin (POM)");
  const out = ownershipOf({ code: "fdm", inHouse: null, fit: { verdict: "makeable_outsource_only", machines_evaluated: 0, best_machine: null, failures: [] } as never }, null, shop);
  assert.deepEqual(out, { kind: "not_owned", v: "Not owned", s: "needs a filament printer", machine: null });
  assert.equal(ownershipOf({ code: "injection_molding", inHouse: null, fit: null }, null, shop, 1444.2).s, "needs an injection molder · tooling pays back from about 1,444 parts");
  assert.equal(ownershipOf({ code: "sand_casting", inHouse: null, fit: null }, null, shop).s, "no sand casting of yours");
  assert.equal(ownershipOf({ code: "fdm", inHouse: null, fit: null }, null, []).kind, "no_machines");
  // You own one for the process, but this check didn't confirm its fit: never read as not owned.
  const unc = ownershipOf({ code: "cnc_3axis", inHouse: null, fit: null }, null, shop);
  assert.deepEqual([unc.kind, unc.v, unc.machine], ["unconfirmed", "Can't confirm", "Haas VF-2"]);
});
