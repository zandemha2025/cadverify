import { test } from "node:test";
import assert from "node:assert/strict";
import {
  isAssemblyCandidate,
  looksLikeFastener,
  defaultPartOfInterest,
  type PartInstance,
} from "./assembly.ts";

function part(id: string, name: string, volume: number): PartInstance {
  return {
    id,
    name,
    occurrence: name.toUpperCase(),
    instance: 1,
    tree_path: `as1/${name}`,
    occ_label: name,
    world: {
      bbox_min: [0, 0, 0],
      bbox_max: [1, 1, 1],
      bbox_size: [1, 1, 1],
      centroid: [0, 0, 0],
      volume,
    },
    geometry_summary: {
      num_boundary_faces: 6,
      num_triangles: 12,
      num_vertices: 8,
      bbox_dims: [1, 1, 1],
    },
    mesh_ref: id,
  };
}

test("isAssemblyCandidate accepts only STEP/IGES suffixes", () => {
  assert.equal(isAssemblyCandidate("as1.stp"), true);
  assert.equal(isAssemblyCandidate("AS1.STEP"), true);
  assert.equal(isAssemblyCandidate("x.iges"), true);
  assert.equal(isAssemblyCandidate("x.igs"), true);
  // STL and others stay on the unchanged single-part path.
  assert.equal(isAssemblyCandidate("bracket.stl"), false);
  assert.equal(isAssemblyCandidate("bracket.sldprt"), false);
  assert.equal(isAssemblyCandidate("noext"), false);
});

test("looksLikeFastener flags hardware by name", () => {
  assert.equal(looksLikeFastener(part("1", "bolt", 5)), true);
  assert.equal(looksLikeFastener(part("2", "M6-NUT", 3)), true);
  assert.equal(looksLikeFastener(part("3", "L-bracket", 100)), false);
  assert.equal(looksLikeFastener(part("4", "plate", 200)), false);
});

test("defaultPartOfInterest picks the largest non-fastener", () => {
  const parts = [
    part("bolt1", "bolt", 999), // largest overall but a fastener
    part("plate", "plate", 200),
    part("bracket", "L-bracket", 300),
    part("nut1", "nut", 50),
  ];
  assert.equal(defaultPartOfInterest(parts), "bracket");
});

test("defaultPartOfInterest falls back to largest when all are fasteners", () => {
  const parts = [part("bolt1", "bolt", 10), part("bolt2", "bolt", 40)];
  assert.equal(defaultPartOfInterest(parts), "bolt2");
});

test("defaultPartOfInterest returns null for empty", () => {
  assert.equal(defaultPartOfInterest([]), null);
});

test("probeAssembly refuses a backend assembly parse error instead of falling back", async () => {
  const { probeAssembly } = await import("./assembly.ts");
  const post = async () => new Response(
    JSON.stringify({ detail: "Licensed reader required; export STEP AP242." }),
    { status: 400, headers: { "content-type": "application/json" } },
  );
  const outcome = await probeAssembly(new File(["ISO-10303-21"], "gearbox.step"), post);
  assert.equal(outcome.kind, "refused");
  if (outcome.kind === "refused") assert.match(outcome.action, /export STEP AP242/i);
});

test("probeAssembly permits single-part fallback only after explicit classification", async () => {
  const { probeAssembly } = await import("./assembly.ts");
  const post = async () => new Response(JSON.stringify({
    kind: "single_part",
    part_count: 1,
    parts: [],
  }), { status: 200, headers: { "content-type": "application/json" } });
  const outcome = await probeAssembly(new File(["ISO-10303-21"], "bracket.step"), post);
  assert.deepEqual(outcome, { kind: "single_part" });
});

test("probeAssembly refuses an empty preview for a confirmed multi-solid assembly", async () => {
  const { probeAssembly } = await import("./assembly.ts");
  let call = 0;
  const post = async () => {
    call += 1;
    if (call === 1) {
      return new Response(JSON.stringify({ kind: "assembly", part_count: 2, parts: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(new Blob([]), { status: 200 });
  };
  const outcome = await probeAssembly(new File(["ISO-10303-21"], "gearbox.step"), post);
  assert.equal(outcome.kind, "refused");
  if (outcome.kind === "refused") assert.match(outcome.title, /preview was empty/i);
});

test("STEP failures preserve file diagnostics and distinguish service/session recovery", async () => {
  const { probeAssembly } = await import("./assembly.ts");
  for (const [status, body, expected, recovery] of [
    [400, { code: "BAD_REQUEST", message: "Empty file uploaded" }, /empty file/i, undefined],
    [413, { message: "File exceeds 100MB limit" }, /100MB/, undefined],
    [500, {}, /service.*try again/i, "retry"],
    [503, { detail: { message: "Parser temporarily unavailable" } }, /temporarily unavailable/i, "retry"],
    [504, {}, /service.*try again/i, "retry"],
    [429, {}, /try again in 12 seconds/i, "retry"],
    [401, {}, /session expired.*sign in/i, "sign_in"],
    [403, {}, /permission.*admin/i, undefined],
  ] as const) {
    const result = await probeAssembly(new File(["ISO-10303-21"], "valid.STP"), async () =>
      Response.json(body, { status, headers: { "retry-after": "12" } }));
    assert.equal(result.kind, "refused");
    if (result.kind !== "refused") continue;
    assert.match(result.action, expected);
    assert.equal(result.recovery, recovery);
    if (status >= 500 || status === 429) assert.doesNotMatch(result.action, /export/i);
  }
  for (const body of ["null", "not JSON"]) {
    const result = await probeAssembly(new File(["ISO-10303-21"], "valid.STP"), async () =>
      new Response(body, { status: 200 }));
    assert.equal(result.kind, "refused");
    if (result.kind === "refused") assert.equal(result.recovery, "retry");
  }
});

test("STEP trial-cap refusal preserves the quota and offers no automatic retry", async () => {
  const { probeAssembly } = await import("./assembly.ts");
  const result = await probeAssembly(new File(["ISO-10303-21"], "valid.STP"), async () =>
    Response.json({ code: "org_validation_cap_exceeded", message: "100 validations in total" }, { status: 429 }));
  assert.equal(result.kind, "refused");
  if (result.kind !== "refused") return;
  assert.match(result.action, /allowance used up/i);
  assert.equal(result.recovery, undefined);
});

test("assembly analysis preserves quota errors and rolling quotas allow later retry", async () => {
  const { fetchAssemblyAnalysis, probeAssembly } = await import("./assembly.ts");
  const file = new File(["ISO-10303-21"], "valid.STP");
  for (const [status, payload, recovery] of [
    [429, { code: "org_validation_cap_exceeded", window_days: 0, message: "100 in total" }, undefined],
    [403, { code: "user_validation_cap_exceeded", window_days: 7, message: "100 in trailing 7 days" }, "retry"],
    [429, { code: "org_quota_exceeded", message: "Daily cap" }, "retry"],
  ] as const) {
    const post = async () => Response.json(payload, { status });
    await assert.rejects(fetchAssemblyAnalysis(file, post), /Verification allowance used up/);
    const result = await probeAssembly(file, post);
    assert.equal(result.kind, "refused");
    if (result.kind === "refused") assert.equal(result.recovery, recovery);
  }
  assert.equal(await fetchAssemblyAnalysis(file, async () => Response.json({})), null);
  await assert.rejects(fetchAssemblyAnalysis(file, async () => new Response(null, { status: 503 })), /try again/i);
});
