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
