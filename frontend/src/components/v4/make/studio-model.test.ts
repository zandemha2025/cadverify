/**
 * Design Studio words and numbers: template fields and limits, status chips,
 * the interpreter line, geometry facts, the diff rows and the check link.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/make/studio-model.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_DESIGN_FORM } from "../../../lib/design-plan.ts";
import {
  INTERPRET_IDLE,
  checkHref,
  countText,
  defaultPair,
  deltaText,
  designChip,
  diffRows,
  diffValue,
  envelopeText,
  fieldProblem,
  fieldsFor,
  formatBytes,
  interpretView,
  kindLabel,
  revisionSub,
  sameRevisionPair,
  viewText,
  volumeText,
} from "./studio-model.ts";

test("each template takes its own fields with the server's limits", () => {
  assert.deepEqual(fieldsFor("plate").map((f) => f.key), ["width", "depth", "thickness"]);
  assert.deepEqual(fieldsFor("bracket").map((f) => f.key), ["width", "depth", "height", "thickness"]);
  assert.deepEqual(fieldsFor("enclosure").map((f) => f.key), ["width", "depth", "height", "wallThickness"]);
  assert.equal(fieldsFor("enclosure")[0].min, 20);
  assert.equal(fieldsFor("enclosure")[0].lim, "20 to 1,000");
  assert.equal(fieldsFor("plate")[2].lim, "0.5 to 100");
  assert.equal(fieldsFor("enclosure")[3].label, "Wall, mm");
});

test("out-of-range and empty fields are named before anything is sent", () => {
  assert.equal(fieldProblem({ ...DEFAULT_DESIGN_FORM }), null);
  assert.equal(fieldProblem({ ...DEFAULT_DESIGN_FORM, width: 5 }), "Width must be 10 to 1,000 mm.");
  assert.equal(fieldProblem({ ...DEFAULT_DESIGN_FORM, depth: Number.NaN }), "Depth needs a number.");
  assert.equal(fieldProblem({ ...DEFAULT_DESIGN_FORM, kind: "enclosure", width: 15 }), "Width must be 20 to 1,000 mm.");
  assert.equal(fieldProblem({ ...DEFAULT_DESIGN_FORM, holeDiameter: 0.5 }), "Hole diameter must be 1 to 100 mm.");
  // Holes off: their fields don't matter.
  assert.equal(fieldProblem({ ...DEFAULT_DESIGN_FORM, fourCornerHoles: false, holeInset: 0 }), null);
  // Height only matters where the template has one.
  assert.equal(fieldProblem({ ...DEFAULT_DESIGN_FORM, kind: "plate", height: 0 }), null);
  assert.equal(fieldProblem({ ...DEFAULT_DESIGN_FORM, kind: "bracket", height: 0 }), "Height must be 10 to 1,000 mm.");
});

test("status chips and revision words", () => {
  assert.deepEqual(designChip("ready"), { tone: "ok", label: "Ready" });
  assert.deepEqual(designChip("failed"), { tone: "bad", label: "Needs attention" });
  assert.deepEqual(designChip("generating"), { tone: "unk", label: "Generating" });
  assert.equal(revisionSub({ status: "ready", number: 2 }, 2), "Ready · current");
  assert.equal(revisionSub({ status: "ready", number: 1 }, 2), "Ready");
  assert.equal(revisionSub({ status: "queued", number: 3 }, 3), "Queued · current");
  assert.equal(viewText(2, 2), "Viewing R2 · current");
  assert.equal(viewText(1, 2), "Viewing R1 · current is R2");
  assert.equal(kindLabel("bracket"), "L bracket");
  assert.equal(kindLabel(undefined), "Design");
});

test("the interpreter line uses the server's own words", () => {
  const ready = interpretView({
    status: "ready",
    kind: "bracket",
    name: "L bracket 60 × 40 × 45 mm",
    plan: { kind: "bracket", width_mm: 60, depth_mm: 40, height_mm: 45, thickness_mm: 6 },
    assumptions: ["All extracted dimensions are millimetres; review them before generation."],
    message: "Safe dimensions extracted.",
  });
  assert.deepEqual(ready, { tone: "ok", label: "Ready: L bracket", text: "Local rules, no AI · All extracted dimensions are millimetres; review them before generation." });
  const need = interpretView({ status: "needs_input", kind: null, missing_fields: ["shape"], message: "Choose a supported starting shape.", prefill: {} });
  assert.deepEqual(need, { tone: "warn", label: "Needs input", text: "Choose a supported starting shape." });
  assert.equal(INTERPRET_IDLE.tone, "unk");
});

test("geometry facts never invent a value", () => {
  assert.equal(envelopeText([60, 40, 45]), "60 × 40 × 45 mm");
  assert.equal(envelopeText([60.04, 40.25, 45]), "60 × 40.3 × 45 mm");
  assert.equal(envelopeText(null), "—");
  assert.equal(envelopeText([1, Number.NaN, 2]), "—");
  assert.equal(volumeText(31.0412), "31.04");
  assert.equal(volumeText(null), "—");
  assert.equal(countText(8446), "8,446");
  assert.equal(countText(undefined), "—");
  assert.equal(formatBytes(null), "—");
  assert.equal(formatBytes(900), "900 B");
  assert.equal(formatBytes(22 * 1024), "22 KB");
  assert.equal(formatBytes(3.5 * 1024 * 1024), "3.5 MB");
});

test("diff rows show before, after and a signed change", () => {
  assert.equal(deltaText(2), "+2");
  assert.equal(deltaText(-1.5), "−1.5");
  assert.equal(deltaText(0), "0");
  assert.equal(deltaText(null), "—");
  assert.equal(diffValue([]), "[]");
  assert.equal(diffValue(undefined), "—");
  assert.equal(diffValue(31.04123), "31.041");
  assert.deepEqual(diffRows([{ path: "thickness_mm", before: 6, after: 8, delta: 2 }]), [{ path: "thickness_mm", before: "6", after: "8", change: "+2" }]);
  assert.deepEqual(diffRows([{ path: "holes[0].x_mm", before: -30, after: null, delta: null }]), [{ path: "holes[0].x_mm", before: "-30", after: "—", change: "—" }]);
});

test("compare defaults to the two newest ready revisions", () => {
  assert.equal(defaultPair([{ number: 1, status: "ready" }]), null);
  assert.deepEqual(
    defaultPair([
      { number: 3, status: "failed" },
      { number: 1, status: "ready" },
      { number: 2, status: "ready" },
      { number: 4, status: "ready" },
    ]),
    [2, 4],
  );
  assert.equal(sameRevisionPair(2, 2), true);
  assert.equal(sameRevisionPair(1, 2), false);
  assert.equal(sameRevisionPair(null, null), false);
});

test("a revision opens in a check as ?design=<id>&revision=<n>", () => {
  assert.equal(checkHref("/app/check", "01JABCDEFGHJKMNPQRSTVWXYZ0", 2), "/app/check?design=01JABCDEFGHJKMNPQRSTVWXYZ0&revision=2");
});
