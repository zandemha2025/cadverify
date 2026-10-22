import test from "node:test";
import assert from "node:assert/strict";
import { alternativeOf, appliesTo, buildProblems, callout, findProblem, fixText, forProcessLine, methodHead, notListedKind, pickMethod, problemInContext, plainReason, problemFigs, problemForIssue, ruleOf, shortText, tidy, whereLine } from "./problems.ts";
import { canFixLine, fixRoute, studioParam, studioValueProblem, whoFixes, type FixOrigin } from "./capabilities.ts";
import { cadPath as cadSteps, withDraftAngles } from "./cad-tools.ts";
import { enclosureCostOnly, shellCost, shellValidation } from "./fixtures.test-data.ts";

const shell = () => buildProblems({ validation: shellValidation(), cost: shellCost() });

test("findings group into one problem per kind; setup, precision and info notes aren't listed", () => {
  const set = shell();
  const ids = set.problems.map((p) => p.id);
  assert.deepEqual([...ids].sort(), ["bodies", "corners", "draft", "drain", "flat", "overhang", "round", "thin", "undercut"]);
  const thin = findProblem(set, "thin")!;
  assert.deepEqual(thin.codes.sort(), ["THIN_WALL", "THIN_WALL_MOLDING"]);
  assert.deepEqual(thin.blocks.sort(), ["cnc_3axis", "cnc_5axis", "cnc_turning", "die_casting", "fdm", "sls"]);
  assert.equal(set.notListed, "Not listed: 2 setup reviews, 1 measurement-precision note and 1 process note. They aren’t design problems.");
  assert.equal(notListedKind({ code: "THIN_WALL", severity: "error" }), null);
  assert.equal(notListedKind({ code: "SHEET_GAUGE_UNVERIFIED", severity: "warning" }), "setup");
  // An error is always a problem, whatever its code.
  assert.equal(notListedKind({ code: "SHEET_GAUGE_UNVERIFIED", severity: "error" }), null);
});

test("errors come first, the most-blocking first", () => {
  const set = shell();
  assert.equal(set.problems[0].id, "thin");
  assert.ok(set.problems.findIndex((p) => p.severity === "warning") > set.problems.findIndex((p) => p.id === "round"));
});

test("where lines read the engine's own counts", () => {
  const set = shell();
  // An STL has no faces but its triangles: counted as such (de-03).
  assert.equal(findProblem(set, "thin")!.where, "Every wall · 24 of 24 mesh triangles");
  assert.equal(findProblem(set, "draft")!.where, "Side walls · 100% of side-wall area · 16 mesh triangles");
  assert.equal(findProblem(set, "drain")!.where, "Sealed cavity · 6,859 mm³");
  assert.equal(findProblem(set, "corners")!.where, "12 sharp inside corners");
  assert.equal(findProblem(set, "flat")!.where, "761 mm² flat, facing down");
  assert.equal(findProblem(set, "bodies")!.title, "2 bodies in one file");
  const open = { id: "open", primary: { code: "NON_WATERTIGHT", severity: "error", message: "Mesh is not watertight — has 945 boundary edges.", fix_suggestion: null }, faceCount: null, scope: "whole_part", methods: [] } as never;
  assert.equal(whereLine(open, 149997), "945 open edges");
});

test("one problem for one method: figures, callout, reason and rule follow the picked method", () => {
  const set = shell();
  const thin = findProblem(set, "thin")!;
  const mill = pickMethod(thin, "cnc_3axis", null)!;
  assert.deepEqual(problemFigs(thin, mill, 8).map((f) => [f.k, f.v]), [["Measured", "0.5 mm"], ["Needs", "0.8 mm"], ["Short by", "0.3 mm"]]);
  assert.deepEqual(callout(thin, mill), { main: "0.5 mm here", sub: "needs 0.8 mm for 3-axis milling" });
  assert.equal(plainReason(thin, mill, 8), "The thinnest wall measures 0.5 mm. 3-axis milling needs at least 0.8 mm, so it can’t make this part as drawn.");
  assert.deepEqual(ruleOf(thin, mill), { text: "Thin walls vibrate; 0.8 mm min metals.", source: "No standard named · applies to 3-axis milling" });
  const sls = pickMethod(thin, "sls", null)!;
  assert.deepEqual(ruleOf(thin, sls), { text: "0.7 mm min wall.", source: "EOS PA12 · applies to nylon powder printing" });
  assert.equal(callout(thin, sls).sub, "needs 0.7 mm for nylon powder printing");
  assert.equal(shortText(thin, sls), "−0.2 mm");
  // No citation at all: the engine's own check.
  const five = pickMethod(thin, "cnc_5axis", null)!;
  assert.equal(ruleOf(thin, five).source, "ScaleCAD check, no external standard · applies to 5-axis milling");
});

test("draft with no measured angle says so; a measured angle is shown when the engine reports it", () => {
  const set = shell();
  const draft = findProblem(set, "draft")!;
  const im = pickMethod(draft, "injection_molding", null)!;
  const figs = problemFigs(draft, im, 8);
  assert.deepEqual([figs[0].v, figs[0].s], ["Under 1°", "angle not reported"]);
  assert.equal(callout(draft, im).main, "Under 1° here");
  assert.equal(shortText(draft, pickMethod(draft, "sand_casting", null)!), "under 3°");
  const v = shellValidation();
  for (const ps of v.process_scores) for (const i of ps.issues) if (i.code === "INSUFFICIENT_DRAFT") i.measured_value = 0.4;
  const measured = findProblem(buildProblems({ validation: v, cost: null }), "draft")!;
  const m2 = pickMethod(measured, "injection_molding", null)!;
  assert.deepEqual([problemFigs(measured, m2, 8)[0].v, problemFigs(measured, m2, 8)[0].s], ["0.4°", "smallest draft"]);
  assert.equal(callout(measured, m2).main, "0.4° here");
  assert.equal(shortText(measured, m2), "−0.6°");
});

test("the fix says which methods a wall covers and what the others need", () => {
  const set = shell();
  const thin = findProblem(set, "thin")!;
  const v = shellValidation();
  const f = fixText(thin, pickMethod(thin, "cnc_3axis", null), alternativeOf(v, thin));
  assert.equal(f.fix, "Make the walls at least 0.8 mm thick.");
  assert.match(f.alt!, /^That covers nylon powder printing, 3-axis milling, 5-axis milling, die casting and filament printing\. Others need more: turning 1\.0 mm\. Consider SLA/);
});

test("a saved part with no analysis uses the cost record's blocker details", () => {
  const set = buildProblems({ validation: null, cost: enclosureCostOnly() });
  assert.deepEqual(set.problems.map((p) => p.id), ["draft"]);
  assert.deepEqual(set.problems[0].blocks, ["injection_molding"]);
  assert.equal(set.problems[0].faceCount, 132042);
});

test("what ScaleCAD can fix: open meshes, Design Studio template parameters, nothing else today", () => {
  const set = shell();
  const thin = findProblem(set, "thin")!;
  const upload: FixOrigin = { fileType: "STL", open: false, studio: null, server: null };
  assert.equal(fixRoute(thin, upload), null);
  assert.equal(canFixLine(thin, upload), "ScaleCAD can’t edit this STL. It gives the steps, prices the result and checks the file you upload.");
  const studio: FixOrigin = { ...upload, studio: { designId: "d", designName: "Open enclosure", revision: 1, currentRevision: 1, plan: { kind: "enclosure", width_mm: 120, depth_mm: 80, height_mm: 40, wall_thickness_mm: 0.6 }, volumeCm3: 15.16 } };
  assert.deepEqual(fixRoute(thin, studio), { kind: "studio", param: { key: "wall_thickness_mm", label: "Wall", value: 0.6, unit: "mm" } });
  assert.deepEqual(fixRoute(findProblem(set, "draft")!, studio), { kind: "studio", param: { key: "draft_angle_deg", label: "Draft", value: 0, unit: "°" } });
  // The bracket has no draft parameter.
  assert.equal(studioParam({ kind: "bracket", width_mm: 60, depth_mm: 40, height_mm: 45, thickness_mm: 8 }, "draft"), null);
  assert.deepEqual(whoFixes(findProblem(set, "round")!, upload, true), { label: "Use milling", tone: "c-ok" });
  assert.deepEqual(whoFixes(findProblem(set, "flat")!, upload, true), { label: "At the shop", tone: "c-unk" });
  // A stored draft angle is read; a missing one is 0.
  assert.equal(studioParam({ kind: "plate", width_mm: 80, depth_mm: 50, thickness_mm: 6, holes: [], draft_angle_deg: 1.5 } as never, "draft")?.value, 1.5);
  assert.equal(studioValueProblem({ kind: "plate", width_mm: 80, depth_mm: 50, thickness_mm: 6, holes: [] }, "draft_angle_deg", "12"), "Use 0° to 10°.");
  // The server-side fixer seam.
  const sf = { can: true, fix: "drain_holes", label: "Add drain holes", method: "", param: "diameter_mm", unit: "mm", bounds: [0.5, 50] as [number, number], value: 5, whyNot: null, lastAttempt: null };
  assert.deepEqual(fixRoute(findProblem(set, "drain")!, { ...upload, server: { families: ["drain"], byFamily: { drain: sf }, available: [] } }), { kind: "server", fix: sf });
  // A finding the server tried and couldn't clear is no longer offered.
  assert.equal(fixRoute(findProblem(set, "drain")!, { ...upload, server: { families: [], byFamily: { drain: { ...sf, can: false } }, available: [] } }), null);
});

test("a new wall is checked against the generator's own bounds", () => {
  const plan = { kind: "enclosure" as const, width_mm: 120, depth_mm: 80, height_mm: 40, wall_thickness_mm: 0.6 };
  assert.equal(studioValueProblem(plan, "wall_thickness_mm", "1.0"), null);
  assert.equal(studioValueProblem(plan, "wall_thickness_mm", "0.4"), "Use 0.5 mm or more, and under 20 mm for a 120 × 80 × 40 mm enclosure.");
  assert.equal(studioValueProblem(plan, "wall_thickness_mm", "20"), "Use 0.5 mm or more, and under 20 mm for a 120 × 80 × 40 mm enclosure.");
  assert.equal(studioValueProblem(plan, "wall_thickness_mm", ""), "Enter a number.");
  assert.equal(studioValueProblem(plan, "wall_thickness_mm", "1,2"), null);
});

test("engine prose is tidied, never rewritten", () => {
  assert.equal(tidy("Add drain holes >= 3.5mm diameter. 2x nozzle"), "Add drain holes at least 3.5 mm diameter. 2× nozzle");
  const set = shell();
  assert.equal(problemForIssue(set, "THIN_WALL_MOLDING")?.id, "thin");
  assert.equal(problemForIssue(set, "SETUP_ACCESS_UNVERIFIED"), null);
});

test("CAD steps come from the verified data: the fix, then the tool's STEP export", async () => {
  const { cadPath, CAD_TOOLS } = await import("./cad-tools.ts");
  assert.equal(CAD_TOOLS.length, 6);
  const draft = cadPath("solidworks", "draft");
  assert.equal(draft.verified, true);
  assert.equal(draft.feature, "Draft (Neutral Plane)");
  assert.match(draft.steps[0], /^Insert › Features › Draft/);
  assert.match(draft.steps.at(-1)!, /STEP|Output as Solid/);
  assert.equal(draft.sources.length, 2);
  assert.equal(cadPath("fusion", "drain").feature, "Hole");
  // No verified fix for undercuts: only the export, said plainly.
  const under = cadPath("nx", "undercut");
  assert.equal(under.noFix, true);
  assert.match(under.steps[0], /^File tab › Export/);
});

test("a maximum is read as a maximum: an overhang is over by, not short by", () => {
  const v = shellValidation();
  for (const ps of v.process_scores) for (const i of ps.issues) if (i.code === "OVERHANG") Object.assign(i, { measured_value: 90, required_value: ps.process === "sla" ? 19 : 45, measurement_unit: "deg" });
  const set = buildProblems({ validation: v, cost: null });
  const over = findProblem(set, "overhang")!;
  const sla = pickMethod(over, "sla", null)!;
  assert.equal(sla.dir, "max");
  assert.equal(shortText(over, sla), "+71°");
  assert.deepEqual(problemFigs(over, sla, 8).map((f) => [f.k, f.v]), [["Measured", "90.0°"], ["Allows", "19° at most"], ["Over by", "71°"]]);
  assert.equal(callout(over, sla).sub, "at most 19° for resin printing");
  assert.match(plainReason(over, sla, 8), /allows at most 19°; this is 90\.0°, so it’s flagged to check first\.$/);
  assert.equal(methodHead(over), "allows at most · over by");
  // A minimum stays a minimum.
  assert.equal(methodHead(findProblem(set, "thin")!), "needs · short by");
  // No required value: the measurement alone, no "needs".
  const thick = { ...over, methods: [{ ...sla, need: null }] };
  assert.equal(shortText(thick, thick.methods[0]), "check");
});

test("mesh repair and ScaleCAD's own fixes are offered on every plan, the free trial included", async () => {
  const capabilities = await import("./capabilities.ts");
  assert.equal("needsPilot" in capabilities, false);
  const set = shell();
  const drain = findProblem(set, "drain")!;
  const sf = { can: true, fix: "drain_holes", label: "Add drain holes", method: "", param: "diameter_mm", unit: "mm", bounds: [0.5, 50] as [number, number], value: 5, whyNot: null, lastAttempt: null };
  const base: FixOrigin = { fileType: "STL", open: false, studio: null, server: { families: ["drain"], byFamily: { drain: sf }, available: [] } };
  assert.equal(fixRoute(drain, base)?.kind, "server");
  assert.deepEqual(whoFixes(drain, base, true), { label: "ScaleCAD can fix", tone: "c-ok" });
  assert.equal(canFixLine(drain, base), "ScaleCAD can add drain holes on a copy of your file and check the copy. Your file stays as it is.");
  const open = findProblem(set, "open");
  if (open) {
    const shellOrigin: FixOrigin = { ...base, open: true, server: null };
    assert.equal(fixRoute(open, shellOrigin)?.kind, "repair");
    assert.doesNotMatch(canFixLine(open, shellOrigin), /pilot|plan/i);
  }
});

test("Show problems for one process: only what it reported, whole-file problems too, and why in its own numbers", () => {
  const set = shell();
  const fdm = set.problems.filter((p) => appliesTo(p, "fdm")).map((p) => p.id);
  assert.ok(fdm.includes("thin"), "thin walls stop filament printing");
  assert.ok(!fdm.includes("draft"), "draft is a molding and casting problem, not a printing one");
  assert.deepEqual(set.problems.filter((p) => appliesTo(p, null)).length, set.problems.length, "no process: every problem");
  const thin = findProblem(set, "thin")!;
  const line = forProcessLine(thin, "fdm", "Filament printing (FDM/FFF)")!;
  assert.match(line, /^Stops filament printing \(FDM\/FFF\): needs at least [0-9.]+ mm, measured [0-9.]+ mm$/);
  // A process the problem doesn't name has no line unless the problem covers the whole file.
  assert.equal(forProcessLine(findProblem(set, "draft")!, "fdm", "Filament printing (FDM/FFF)"), null);
  const bodies = findProblem(set, "bodies")!;
  if (bodies.universal) assert.match(forProcessLine(bodies, "fdm", "Filament printing (FDM/FFF)")!, /every process, filament printing \(FDM\/FFF\) too$/);
});


test("a STEP's problems count its own faces, and the draft card states both rules (de-02, de-03, np-18)", () => {
  const v = shellValidation();
  v.geometry = { ...v.geometry, faces: 247114, cad_faces: 11 };
  for (const ps of v.process_scores) {
    for (const i of ps.issues) {
      if (i.code === "INSUFFICIENT_DRAFT" && ps.process === "injection_molding") {
        Object.assign(i, {
          affected_face_count: 169370, cad_face_count: 8, measured_value: 0, required_value: 2, measurement_unit: "deg",
          breakdown: [
            { walls: "outside", need_deg: 1, measured_deg: 0, faces: 90000, cad_faces: 4 },
            { walls: "inside", need_deg: 2, measured_deg: 0, faces: 79370, cad_faces: 4 },
          ],
        });
      }
      if (i.code === "OVERHANG") Object.assign(i, { measured_value: 46, required_value: ps.process === "sla" ? 19 : 45, measurement_unit: "deg", message: `2 faces (8.3%) exceed ${ps.process === "sla" ? 19 : 45}.0° overhang threshold.` });
    }
  }
  const set = buildProblems({ validation: v, cost: null });
  const draft = findProblem(set, "draft")!;
  assert.match(draft.where, /· 8 of 11 faces$/);
  const im = pickMethod(draft, "injection_molding", null)!;
  assert.deepEqual(problemFigs(draft, im, 8).map((f) => [f.k, f.v]), [["Measured", "0.0°"], ["Needs", "1° out · 2° in"], ["Short by", "2°"]]);
  assert.match(fixText(draft, im, null).fix, /^Add at least 1° of draft to the outside walls and 2° to the inside walls/);
  // The overhang row reads the part's own angle, never resin printing's 19° limit.
  const over = findProblem(set, "overhang")!;
  assert.doesNotMatch(over.where, /19°/);
  assert.match(over.where, /steepest 46° past vertical$/);
  // Supports are the printer's setup, not a CAD change.
  assert.equal(whoFixes(over, { fileType: "step", open: false, studio: null, server: null }, false).label, "At the shop");
});

test("the CAD steps give the draft angles the check asks for", () => {
  const steps = withDraftAngles(cadSteps("solidworks", "draft").steps, 1, 2);
  assert.ok(steps.some((x) => x.includes("Draft Angle: 1° (the outside walls’ rule)")));
  assert.ok(steps.some((x) => x.includes("at 2° (the inside walls’ rule)")));
  assert.ok(steps.every((x) => !/the (outside|inside) angle/.test(x)));
});

test("an engine code with no problem family gets a plain title, never the code's words", async () => {
  const { familyOf } = await import("./problems.ts");
  assert.equal(familyOf("WIRE_CANNOT_REACH").title, "A closed-in face a wire can’t cut");
  assert.equal(familyOf("SEALED_VOID_NO_ACCESS").title, "A sealed void no tool can reach");
  assert.equal(familyOf("SOMETHING_NEW").title, "Something new");
});

test("engine numbers read in three figures, and a 0.0% share says under 0.1%", async () => {
  const { plainNumbers, tidy } = await import("./problems.ts");
  assert.equal(plainNumbers("24 faces (0.0%) below 1.5mm min wall. Thinnest: 0.347954mm."), "24 faces (under 0.1%) below 1.5mm min wall. Thinnest: 0.348mm.");
  assert.equal(plainNumbers("1.8833 hr × $8/hr"), "1.88 hr × $8/hr");
  assert.equal(plainNumbers("area 1234.56789 mm²; 45.0° threshold"), "area 1235 mm²; 45.0° threshold");
  assert.equal(tidy("Thinnest: 0.347954mm"), "Thinnest: 0.348 mm");
});

test("a cost driver's derivation reads in plain figures", async () => {
  const { howText } = await import("./problems.ts");
  assert.equal(howText("1.8833 hr × $8/hr × region-labor ×1 · calibrated"), "1.88 hr × $8/hr · calibrated");
  assert.equal(howText("2 hr × $60/hr × region-labor ×1.25"), "2 hr × $60/hr × regional labor ×1.25");
});

test("Upload the fixed file from the list is for the picked problem, else the only one (R3 hand-off)", () => {
  assert.equal(problemInContext(["thin", "draft"], "draft"), "draft");
  assert.equal(problemInContext(["thin"], null), "thin");
  assert.equal(problemInContext(["thin", "draft"], null), null);
  assert.equal(problemInContext(["thin", "draft"], "gone"), null);
});
