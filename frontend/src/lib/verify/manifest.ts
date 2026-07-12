/**
 * DECLARED MANIFEST render-model — the sourcing lead's BOM after it lands.
 *
 * Pure selectors/formatters only (no React, no fetch) so they run under the repo's
 * `node --test` type-stripping runner, exactly like `lib/verify/library`. The fetch
 * functions live in `lib/verify/triage-api` (client); these shape and phrase the
 * data honestly.
 *
 * HONESTY (the whole point of this fix): a declared manifest part with no geometry
 * is a USER-DECLARED FACT, never a makeability/cost claim. It gets NO cost, NO
 * make-vs-buy, NO verdict — only its declared fields and an honest "awaiting
 * geometry" state. Coverage is stated exactly as the backend counts it: if 8 are
 * declared and 0 have geometry, the headline SAYS so — it is never rounded up.
 */

/** One declared part — verbatim from `GET /manifest` (manifest_service.part_to_public). */
export interface ManifestPart {
  id: string;
  part_id: string;
  description: string | null;
  material_class: string | null;
  program: string | null;
  parent_assembly: string | null;
  units_per_parent: number | null;
  annual_volume: number | null;
  quantity: number | null;
  region: string | null;
  source: string | null;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** One keyset page of the declared manifest — `GET /manifest`. */
export interface ManifestListPage {
  parts: ManifestPart[];
  next_cursor: string | null;
}

/** One `by_program` rollup entry from coverage. */
export interface ProgramCount {
  program: string;
  count: number;
}

/** The Aramco coverage headline — verbatim from `GET /manifest/coverage`. */
export interface ManifestCoverage {
  org_id: string | null;
  total_declared: number;
  by_program: ProgramCount[];
  geometry: {
    with_geometry: number;
    without_geometry: number;
    /** Honest label: exact match on the normalized stem, NOT fuzzy/semantic. */
    match: string;
  };
}

/** Coerce an unknown API body into a ManifestCoverage, or null if it isn't one. */
export function readManifestCoverage(body: unknown): ManifestCoverage | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (typeof b.total_declared !== "number") return null;
  const geo = (b.geometry && typeof b.geometry === "object" ? b.geometry : {}) as Record<string, unknown>;
  const prog = Array.isArray(b.by_program) ? (b.by_program as unknown[]) : [];
  return {
    org_id: typeof b.org_id === "string" ? b.org_id : null,
    total_declared: b.total_declared,
    by_program: prog
      .map((p) => {
        const r = (p && typeof p === "object" ? p : {}) as Record<string, unknown>;
        return {
          program: typeof r.program === "string" ? r.program : "(unassigned)",
          count: typeof r.count === "number" ? r.count : 0,
        };
      })
      .filter((p) => p.count > 0),
    geometry: {
      with_geometry: typeof geo.with_geometry === "number" ? geo.with_geometry : 0,
      without_geometry: typeof geo.without_geometry === "number" ? geo.without_geometry : 0,
      match: typeof geo.match === "string" ? geo.match : "normalized-stem, exact",
    },
  };
}

/** True when the org has any declared parts at all — the cohort is worth rendering. */
export function hasDeclared(cov: ManifestCoverage | null): cov is ManifestCoverage {
  return !!cov && cov.total_declared > 0;
}

/**
 * True when EVERY declared part is still awaiting geometry (none matched an upload).
 * Only then is it honest to tag each individual row "awaiting geometry"; when some
 * do have geometry we can't tell WHICH per row (coverage is an aggregate), so rows
 * carry the neutral "declared" tag and the split is stated at the headline instead.
 */
export function allAwaitingGeometry(cov: ManifestCoverage): boolean {
  return cov.total_declared > 0 && cov.geometry.with_geometry === 0;
}

/** The label for the awaiting-geometry cohort, e.g. "Declared · awaiting geometry — 8 parts". */
export function awaitingGeometryLabel(cov: ManifestCoverage): string {
  const n = cov.geometry.without_geometry;
  return `Declared · awaiting geometry — ${n} part${n === 1 ? "" : "s"}`;
}

/**
 * The honest one-line coverage headline. States the declared total and the exact
 * geometry split — never overstated. If 8 are declared and 0 have geometry, it says
 * every one of them awaits a part upload before it can be costed.
 */
export function coverageHeadline(cov: ManifestCoverage): string {
  const n = cov.total_declared;
  if (n === 0) {
    return "No declared parts yet — import a BOM to register your inventory.";
  }
  const withGeo = cov.geometry.with_geometry;
  const withoutGeo = cov.geometry.without_geometry;
  const declared = `${n} declared part${n === 1 ? "" : "s"}`;
  if (withGeo === 0) {
    return `${declared} · none have geometry yet — all ${withoutGeo} await a part upload before they can be costed.`;
  }
  if (withoutGeo === 0) {
    return `${declared} · all ${withGeo} have matching geometry and are costed in the buckets above.`;
  }
  return `${declared} · ${withGeo} with geometry (costed above) · ${withoutGeo} still awaiting geometry.`;
}

/** A compact declared-fields summary for one part row (only stated fields, no fabrication). */
export function partMetaBits(p: ManifestPart): string[] {
  const bits: string[] = [];
  if (p.material_class) bits.push(p.material_class);
  if (p.quantity != null) bits.push(`qty ${p.quantity}`);
  if (p.annual_volume != null) bits.push(`${p.annual_volume}/yr`);
  if (p.parent_assembly) bits.push(`↳ ${p.parent_assembly}`);
  if (p.region) bits.push(p.region);
  return bits;
}
