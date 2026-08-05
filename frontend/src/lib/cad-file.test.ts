import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CAD_ACCEPT,
  CAD_EXTS,
  fileExt,
  isSupportedCad,
  supportedCadLabel,
  unsupportedCadGuidance,
} from "./cad-file.ts";

test("CAD_ACCEPT lists exactly the engine's CAD extensions", () => {
  assert.equal(CAD_ACCEPT, ".stl,.step,.stp,.iges,.igs");
  assert.deepEqual([...CAD_EXTS], ["stl", "step", "stp", "iges", "igs"]);
});

test("fileExt returns the lowercased extension, or null when there is none", () => {
  assert.equal(fileExt("bracket.STL"), "stl");
  assert.equal(fileExt("housing.step"), "step");
  assert.equal(fileExt("a.b.stp"), "stp");
  assert.equal(fileExt("fixture.IGES"), "iges");
  assert.equal(fileExt("legacy.igs"), "igs");
  assert.equal(fileExt("noext"), null);
  assert.equal(fileExt("trailing."), null);
  assert.equal(fileExt(""), null);
});

test("isSupportedCad accepts engine CAD extensions in any case, rejects the rest", () => {
  assert.equal(isSupportedCad("part.stl"), true);
  assert.equal(isSupportedCad("PART.STEP"), true);
  assert.equal(isSupportedCad("part.Stp"), true);
  assert.equal(isSupportedCad("casting.IGES"), true);
  assert.equal(isSupportedCad("legacy.igs"), true);
  assert.equal(isSupportedCad("part.obj"), false);
  assert.equal(isSupportedCad("part.pdf"), false);
  assert.equal(isSupportedCad("stl"), false); // no extension, not the literal type
  assert.equal(isSupportedCad("part."), false);
});

test("supportedCadLabel reads as a human list", () => {
  assert.equal(supportedCadLabel(), "STL, STEP, STP, IGES or IGS");
});

test("unsupported native CAD receives an actionable export path", () => {
  assert.deepEqual(unsupportedCadGuidance("pump.SLDASM"), {
    title: "SolidWorks files need a STEP export",
    action: "Open the model in SolidWorks, export it as STEP AP242 (.step or .stp), then upload that exported file.",
  });
  assert.match(unsupportedCadGuidance("part.x_t").action, /Export the model as STL, STEP, STP, IGES or IGS/);
});
