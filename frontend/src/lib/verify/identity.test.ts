/**
 * Unit tests for the retrieval-grounded identity render-model (identity.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (see package.json "test"). No vitest/jest; identity.ts is import-free
 * so it type-strips + runs directly.
 *
 * Proves the honesty contract of the identity surface:
 *   (a) a grounded top match becomes a card model with the real % + bucket + lead
 *       "Looks like your {name} · {part_id}", and the engine's SUGGESTION caveat;
 *   (b) NOT grounded → no card (null) but a quiet one-liner when the corpus is
 *       non-empty; empty corpus / null → nothing at all (no fabricated identity);
 *   (c) a top match with no declared identity yields no card (nothing to assert);
 *   (d) runner-ups are surfaced for transparency; readIdentity tolerates junk.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  readIdentity,
  identityCardModel,
  identityLead,
  confidencePct,
  noMatchLine,
  runnerUps,
  runnerUpLabel,
  closestUnconfirmedModel,
  closestLead,
  type IdentityMatch,
  type IdentityResult,
} from "./identity.ts";

function mkMatch(over: Partial<IdentityMatch> = {}): IdentityMatch {
  return {
    mesh_hash: "h1",
    declared_part_id: "PN-1002",
    declared_name: "Mounting plate bracket",
    program: "Chassis",
    geometry_similarity: 0.98,
    name_similarity: 0.67,
    combined_confidence: 0.868,
    confidence_bucket: "HIGH",
    geometry_distance: 0.06,
    provenance: "RETRIEVED (org corpus: geometry k-NN + name match)",
    ...over,
  };
}

function mkResult(over: Partial<IdentityResult> = {}): IdentityResult {
  return {
    grounded: true,
    matches: [mkMatch()],
    reason: "top match is HIGH confidence (87%) — a retrieved suggestion to confirm",
    caveats: [
      "a retrieved SUGGESTION to confirm, not a verified identity; retrieval can be wrong — check before trusting.",
      "geometry_similarity is a documented proxy — NOT a probability.",
    ],
    provenance: "RETRIEVED (org corpus: geometry k-NN + name match)",
    corpus_size: 4,
    closest_unconfirmed: null,
    ...over,
  };
}

test("readIdentity reads a valid block and rejects junk", () => {
  const res = mkResult();
  assert.deepEqual(readIdentity({ identity: res })?.grounded, true);
  assert.equal(readIdentity({ identity: null }), null);
  assert.equal(readIdentity({}), null);
  assert.equal(readIdentity(null), null);
  assert.equal(readIdentity({ identity: { grounded: "yes" } }), null);
});

test("a grounded top match becomes a card model with real % + lead + caveat", () => {
  const model = identityCardModel(mkResult());
  assert.ok(model);
  assert.equal(model.pct, 87); // 0.868 → 87%
  assert.equal(model.bucket, "HIGH");
  assert.equal(model.lead, "Looks like your Mounting plate bracket · PN-1002");
  assert.equal(model.program, "Chassis");
  assert.match(model.caveat, /SUGGESTION/);
});

test("identityLead degrades honestly when a side is missing, never invents", () => {
  assert.equal(identityLead(mkMatch({ declared_part_id: null })), "Looks like your Mounting plate bracket");
  assert.equal(identityLead(mkMatch({ declared_name: null })), "Looks like your PN-1002");
  assert.equal(identityLead(mkMatch({ declared_name: null, declared_part_id: null })), "");
});

test("confidencePct clamps to a real integer percent", () => {
  assert.equal(confidencePct(mkMatch({ combined_confidence: 0.552 })), 55);
  assert.equal(confidencePct(mkMatch({ combined_confidence: 1.4 })), 100);
  assert.equal(confidencePct(mkMatch({ combined_confidence: -0.2 })), 0);
});

test("NOT grounded → no card, but a quiet line when the corpus is non-empty", () => {
  const res = mkResult({ grounded: false, matches: [mkMatch({ confidence_bucket: "LOW" })], corpus_size: 4 });
  assert.equal(identityCardModel(res), null);
  assert.equal(noMatchLine(res), "No confident match in your part library yet");
});

test("empty corpus / null → nothing at all (no fabricated identity)", () => {
  assert.equal(identityCardModel(null), null);
  assert.equal(noMatchLine(null), null);
  const empty = mkResult({ grounded: false, matches: [], corpus_size: 0 });
  assert.equal(identityCardModel(empty), null);
  assert.equal(noMatchLine(empty), null); // empty corpus is silent, not a one-liner
});

test("a grounded match with no declared identity yields no card (nothing to assert)", () => {
  const res = mkResult({ matches: [mkMatch({ declared_name: null, declared_part_id: null })] });
  assert.equal(identityCardModel(res), null);
});

test("Lever 2 — a NOT-grounded result with closest_unconfirmed → a LOW-confidence model", () => {
  const cu = mkMatch({
    declared_name: "Mounting bracket L",
    declared_part_id: "PN-BRK-001",
    program: "Chassis-2024",
    confidence_bucket: "LOW",
    combined_confidence: 0.47,
    geometry_similarity: 0.47,
    name_similarity: null,
  });
  const res = mkResult({
    grounded: false,
    matches: [cu, mkMatch({ combined_confidence: 0.2, geometry_similarity: 0.2 })],
    corpus_size: 6,
    closest_unconfirmed: cu,
  });
  const low = closestUnconfirmedModel(res);
  assert.ok(low);
  assert.equal(low.pct, 47);
  assert.equal(low.lead, "Closest in your library: Mounting bracket L · PN-BRK-001");
  assert.equal(low.program, "Chassis-2024");
  assert.match(low.caveat, /low confidence/i);
  // The confident-card model is NOT produced for a non-grounded result…
  assert.equal(identityCardModel(res), null);
  // …and the quiet no-match line yields to the softer card (returns null here).
  assert.equal(noMatchLine(res), null);
});

test("Lever 2 — no closest_unconfirmed (e.g. an unrelated part) → NOTHING, and the quiet line returns", () => {
  const res = mkResult({
    grounded: false,
    matches: [mkMatch({ confidence_bucket: "LOW", combined_confidence: 0.02, geometry_similarity: 0.0 })],
    corpus_size: 6,
    closest_unconfirmed: null,
  });
  assert.equal(closestUnconfirmedModel(res), null); // never fabricate a suggestion
  assert.equal(noMatchLine(res), "No confident match in your part library yet");
  // A GROUNDED result never produces the low-confidence model (confident card owns it).
  assert.equal(closestUnconfirmedModel(mkResult({ grounded: true, closest_unconfirmed: mkMatch() })), null);
  // A closest candidate with no declared identity → nothing to suggest.
  const noId = mkResult({
    grounded: false,
    closest_unconfirmed: mkMatch({ declared_name: null, declared_part_id: null }),
  });
  assert.equal(closestUnconfirmedModel(noId), null);
});

test("readIdentity round-trips closest_unconfirmed; closestLead degrades honestly", () => {
  const cu = mkMatch({ declared_name: "Widget", declared_part_id: "PN-9" });
  const parsed = readIdentity({ identity: mkResult({ grounded: false, closest_unconfirmed: cu }) });
  assert.equal(parsed?.closest_unconfirmed?.declared_part_id, "PN-9");
  // absent field tolerated → null
  assert.equal(readIdentity({ identity: mkResult() })?.closest_unconfirmed, null);
  assert.equal(closestLead(mkMatch({ declared_part_id: null })), "Closest in your library: Mounting plate bracket");
  assert.equal(closestLead(mkMatch({ declared_name: null, declared_part_id: null })), "");
});

test("runner-ups are surfaced for transparency", () => {
  const res = mkResult({
    matches: [
      mkMatch(),
      mkMatch({ declared_name: "Sensor cover disc", declared_part_id: "PN-1004", combined_confidence: 0.41 }),
      mkMatch({ declared_name: "Drive shaft rod", declared_part_id: "PN-1003", combined_confidence: 0.09 }),
    ],
  });
  const runners = runnerUps(res);
  assert.equal(runners.length, 2);
  assert.equal(runnerUpLabel(runners[0]), "Sensor cover disc · 41%");
});
