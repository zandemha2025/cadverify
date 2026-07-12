/**
 * Retrieval-grounded PART IDENTITY — the render-model for the `identity` block the
 * cost route now attaches to POST /validate/cost (backend
 * identity_retrieval_service.IdentityMatchResult). It mirrors the backend shape
 * verbatim and exposes PURE selectors/formatters (no React, no runtime relative
 * imports) so they run under the repo's `node --test` type-stripping runner.
 *
 * Honesty (the whole point): a retrieved identity is ALWAYS a SUGGESTION the user
 * confirms — surfaced with its REAL combined_confidence + bucket + provenance
 * ("RETRIEVED · your part library") + the engine's own caveats, NEVER asserted as
 * fact. `grounded` is the backend's gate (top match cleared its MEDIUM bar); below
 * it we claim NO identity. An empty/low corpus yields NOTHING to render — we never
 * fabricate an identity to fill the card.
 */

/** One ranked retrieved candidate — verbatim from the backend IdentityMatch. */
export interface IdentityMatch {
  mesh_hash: string;
  declared_part_id: string | null;
  declared_name: string | null;
  program: string | null;
  geometry_similarity: number;
  name_similarity: number | null;
  combined_confidence: number;
  confidence_bucket: string; // "HIGH" | "MEDIUM" | "LOW"
  geometry_distance: number;
  provenance: string;
}

/** The `identity` block on a CostReport — verbatim from IdentityMatchResult. */
export interface IdentityResult {
  grounded: boolean;
  matches: IdentityMatch[];
  reason: string | null;
  caveats: string[];
  provenance: string | null;
  corpus_size: number;
  /** Lever 2 — the honest LOW-confidence "closest in your library" candidate. Set
   *  by the backend ONLY when the result is NOT grounded yet the closest prior part
   *  is clearly above noise AND well-separated from the runner-up. It is a
   *  SUGGESTION the user confirms, NEVER an assertion; null when grounded (the
   *  confident card carries it) or when nothing clears the floor (e.g. the torus). */
  closest_unconfirmed: IdentityMatch | null;
}

/** Read the `identity` block off a cost response, or null when absent (anonymous /
 *  demo / empty-corpus → the backend sends `identity: null`, and we render NOTHING). */
export function readIdentity(cost: unknown): IdentityResult | null {
  if (!cost || typeof cost !== "object") return null;
  const id = (cost as { identity?: unknown }).identity;
  if (!id || typeof id !== "object") return null;
  const r = id as Partial<IdentityResult>;
  if (typeof r.grounded !== "boolean" || !Array.isArray(r.matches)) return null;
  const cu = (r as { closest_unconfirmed?: unknown }).closest_unconfirmed;
  return {
    grounded: r.grounded,
    matches: r.matches as IdentityMatch[],
    reason: r.reason ?? null,
    caveats: Array.isArray(r.caveats) ? r.caveats : [],
    provenance: r.provenance ?? null,
    corpus_size: typeof r.corpus_size === "number" ? r.corpus_size : 0,
    closest_unconfirmed:
      cu && typeof cu === "object" ? (cu as IdentityMatch) : null,
  };
}

/** The confidence as an integer percent (real field, never fabricated). */
export function confidencePct(m: IdentityMatch): number {
  return Math.round(Math.max(0, Math.min(1, m.combined_confidence)) * 100);
}

/** The lead line for the grounded top match:
 *    "Looks like your {declared_name} · {declared_part_id}"
 *  Degrades honestly when one side is missing (name-only / part-id-only); never
 *  invents a designation. Returns "" when there is nothing declared to show. */
export function identityLead(m: IdentityMatch): string {
  const name = (m.declared_name ?? "").trim();
  const pid = (m.declared_part_id ?? "").trim();
  const body = name && pid ? `${name} · ${pid}` : name || pid;
  return body ? `Looks like your ${body}` : "";
}

/** The subset the top match's identity is; the runner-up matches for the honest
 *  "other near matches" line. Filters LOW-confidence noise to the two next-best so
 *  the transparency line stays a short, honest tail — never the whole corpus. */
export function runnerUps(id: IdentityResult, limit = 2): IdentityMatch[] {
  return id.matches.slice(1, 1 + Math.max(0, limit));
}

/** A short label for one runner-up ("Sensor cover disc · PN-1004 · 41%"). */
export function runnerUpLabel(m: IdentityMatch): string {
  const who = (m.declared_name ?? m.declared_part_id ?? "unnamed part").trim();
  return `${who} · ${confidencePct(m)}%`;
}

export interface IdentityCardModel {
  match: IdentityMatch;
  lead: string;
  pct: number;
  bucket: string; // "HIGH" | "MEDIUM"
  program: string | null;
  caveat: string;
  runners: IdentityMatch[];
}

const DEFAULT_CAVEAT =
  "a suggestion matched from your library — confirm before trusting; retrieval can be wrong";

/** Build the card view-model for a GROUNDED identity, or null when there is no
 *  confident identity to show (not grounded, or no declared top match). The caller
 *  renders NOTHING on null — the honest empty. */
export function identityCardModel(id: IdentityResult | null): IdentityCardModel | null {
  if (!id || !id.grounded || id.matches.length === 0) return null;
  const match = id.matches[0];
  const lead = identityLead(match);
  if (!lead) return null; // top match carries no declared identity → nothing to assert
  // Prefer the engine's SUGGESTION caveat verbatim; fall back to the stated line.
  const caveat =
    id.caveats.find((c) => c.toUpperCase().includes("SUGGESTION")) ?? DEFAULT_CAVEAT;
  return {
    match,
    lead,
    pct: confidencePct(match),
    bucket: match.confidence_bucket,
    program: match.program,
    caveat,
    runners: runnerUps(id),
  };
}

/** The lead line for a LOW-confidence closest candidate:
 *    "Closest in your library: {declared_name} · {declared_part_id}"
 *  Degrades honestly when one side is missing; never invents a designation. Returns
 *  "" when there is nothing declared to show. */
export function closestLead(m: IdentityMatch): string {
  const name = (m.declared_name ?? "").trim();
  const pid = (m.declared_part_id ?? "").trim();
  const body = name && pid ? `${name} · ${pid}` : name || pid;
  return body ? `Closest in your library: ${body}` : "";
}

/** The view-model for the Lever-2 LOW-confidence "closest in your library" card —
 *  a distinct, SOFTER variant of the identity card. Deliberately mirrors the shape
 *  of IdentityCardModel where it overlaps so the component can share styling tokens. */
export interface ClosestUnconfirmedModel {
  match: IdentityMatch;
  lead: string;
  pct: number;
  program: string | null;
  caveat: string;
}

const LOW_CONFIDENCE_CAVEAT =
  "low confidence — the closest shape in your library, not a confident match. Confirm only if this is really it; retrieval can be wrong.";

/** Build the LOW-confidence closest-candidate view-model, or null when there is
 *  nothing honest to suggest. Returns a model ONLY when the result is NOT grounded
 *  (a grounded top match is carried by the confident card) AND the backend set
 *  `closest_unconfirmed` to a candidate that carries a declared identity. The caller
 *  renders NOTHING on null — an unrelated part (torus) yields no candidate, so no
 *  card; the system never asserts a low-confidence match. */
export function closestUnconfirmedModel(
  id: IdentityResult | null
): ClosestUnconfirmedModel | null {
  if (!id || id.grounded) return null;
  const match = id.closest_unconfirmed;
  if (!match) return null;
  const lead = closestLead(match);
  if (!lead) return null; // candidate carries no declared identity → nothing to suggest
  return {
    match,
    lead,
    pct: confidencePct(match),
    program: match.program,
    caveat: LOW_CONFIDENCE_CAVEAT,
  };
}

/** The quiet one-liner for a NON-grounded result over a NON-empty corpus (the org
 *  has a library but no confident match yet). Returns null when the corpus is empty,
 *  the result is grounded, OR a LOW-confidence closest candidate is being offered
 *  instead (that softer card is shown, not this line). */
export function noMatchLine(id: IdentityResult | null): string | null {
  if (!id || id.grounded || id.corpus_size <= 0) return null;
  if (closestUnconfirmedModel(id)) return null;
  return "No confident match in your part library yet";
}
