/**
 * catalog-api — the PURE mapping from a `/catalog` API row (backend
 * `catalog_service.derive_row`) into the catalog door's view model. No React, no
 * DOM, no runtime imports (only erased type imports) so it unit-tests under
 * `node --test` and shares one implementation with the render layer — the same
 * discipline as `lib/dfm-scope`, `lib/findings`, `lib/catalog`.
 *
 * The endpoint already derived every number server-side; this module only
 * RESHAPES it for the grid (snake_case → camelCase, the part-hero href, the
 * findings/unit-cost view atoms). It invents NOTHING: a field the endpoint does
 * not return maps to null, never a fabricated figure. In particular:
 *   • `unit_cost` is null on a Drafted part and its `usd` is null (withheld) on a
 *     DFM-blocked route — the grid never shows a make-price for an unmakeable part.
 *   • `findings` is null when the part has no DFM analysis — an honest absence,
 *     surfaced as "—", never faked as zero.
 *
 * IMPORTS ARE TYPE-ONLY (erased at runtime) so this resolves under the repo's
 * `node --test` type-stripping runner exactly like the other pure libs.
 */
import type {
  CatalogRowApi,
  CatalogPosture,
  CatalogFacets,
} from "@/lib/api";
import type { PostureCounts } from "@/lib/catalog";

/** The backend lifecycle facet: Drafted (analysis only) or Costed (has a decision). */
export type CatalogLifecycleState = "Drafted" | "Costed";

/** Route-scoped DFM findings, camelCased for the grid. */
export interface CatalogFindingsView {
  total: number;
  critical: number;
  advisory: number;
  info: number;
  scopedProcess: string;
}

/** Unit cost for the recommended route, camelCased for the grid. */
export interface CatalogUnitCostView {
  /** the make price; null when withheld (blocked) — never fabricated. */
  usd: number | null;
  /** the quantity the unit price is quoted at */
  qty: number | null;
  /** true when the route is DFM-blocked → the price is honestly withheld */
  withheld: boolean;
  /** the first DFM blocker (the honest reason a price is withheld) */
  withheldReason: string | null;
  /** false for every assumption-based band today (no ground truth yet) */
  validated: boolean;
}

/** One mapped catalog row — the shape the door renders. */
export interface CatalogItem {
  partKey: string;
  filename: string;
  fileType: string;
  /** Drafted | Costed — the endpoint's real lifecycle state */
  lifecycleState: CatalogLifecycleState;
  /** engine process id of the recommended route (null → none) */
  routeProcess: string | null;
  /** the recommended route's material class, when present */
  routeMaterial: string | null;
  /** "costed" (a saved decision's make-now) vs "dfm" (a raw DFM suggestion) */
  routeSource: "costed" | "dfm" | null;
  /** null on a part with no cost artifact (Drafted) */
  unitCost: CatalogUnitCostView | null;
  /** null when the part has no DFM analysis (unknown, not zero) */
  findings: CatalogFindingsView | null;
  /** provenance posture of the make-now estimate's drivers; null when absent */
  posture: PostureCounts | null;
  /** DFM blockers on the costed route (route-scoped, real) */
  routeBlockerCount: number;
  /** the part-hero destination — the saved decision when costed, else the analysis */
  href: string;
  updatedAt: string;
}

/**
 * Map the API posture (snake_case, server-computed) to the shared PostureCounts
 * (camelCase) the PostureCell already speaks — VERBATIM, no recomputation.
 */
export function mapPosture(p: CatalogPosture | null | undefined): PostureCounts | null {
  if (!p) return null;
  return {
    measured: p.measured,
    shop: p.shop,
    user: p.user,
    default: p.default,
    total: p.total,
    grounded: p.grounded,
    guess: p.guess,
    groundedPct: p.grounded_pct,
  };
}

/**
 * The part-hero destination: a costed part opens its saved decision hero, a
 * drafted part opens its analysis. The endpoint guarantees at least one of
 * `cost_decision` / `analysis` is present, so this always resolves; an empty
 * string is the honest fallback if that invariant ever breaks (the row is then
 * rendered non-clickable rather than routing nowhere).
 */
export function resolveHref(row: CatalogRowApi): string {
  if (row.cost_decision) return `/cost-decisions/${row.cost_decision.id}`;
  if (row.analysis) return `/analyses/${row.analysis.id}`;
  return "";
}

/** Map one raw API row into the grid's view model. */
export function mapCatalogItem(row: CatalogRowApi): CatalogItem {
  const uc = row.unit_cost;
  const f = row.findings;
  return {
    partKey: row.part_key,
    filename: row.filename,
    fileType: row.file_type,
    lifecycleState: row.lifecycle_state,
    routeProcess: row.recommended_route?.process ?? null,
    routeMaterial: row.recommended_route?.material ?? null,
    routeSource: row.recommended_route?.source ?? null,
    unitCost: uc
      ? {
          usd: uc.usd,
          qty: uc.qty,
          withheld: uc.withheld,
          withheldReason: uc.withheld_reason,
          validated: uc.validated,
        }
      : null,
    findings: f
      ? {
          total: f.total,
          critical: f.critical,
          advisory: f.advisory,
          info: f.info,
          scopedProcess: f.scoped_process,
        }
      : null,
    posture: mapPosture(row.provenance_posture),
    routeBlockerCount: row.route_blocker_count,
    href: resolveHref(row),
    updatedAt: row.updated_at,
  };
}

export function mapCatalogItems(rows: readonly CatalogRowApi[]): CatalogItem[] {
  return rows.map(mapCatalogItem);
}

/* ------------------------------------------------------------------ */
/*  Facet helpers — real counts off the endpoint's facet summary       */
/* ------------------------------------------------------------------ */

export interface RouteFacet {
  process: string;
  count: number;
}

/**
 * The route facets as a stable chip list: most-populated route first, then
 * process id ascending as a deterministic tiebreak. Every count is the real
 * server-computed count over the full org catalog.
 */
export function routeFacets(facets: CatalogFacets): RouteFacet[] {
  return Object.entries(facets.route)
    .map(([process, count]) => ({ process, count }))
    .sort((a, b) => b.count - a.count || a.process.localeCompare(b.process));
}

/** Count of a lifecycle state in the facet summary (0 when absent). */
export function stateFacetCount(
  facets: CatalogFacets,
  state: CatalogLifecycleState
): number {
  return facets.state[state] ?? 0;
}

/**
 * Whether the grid should show its "empty because filtered" state rather than
 * the true "you have no parts yet" empty — i.e. any facet filter is active.
 */
export function hasActiveFilters(f: {
  state: string | null;
  route: string | null;
  hasFindings: boolean | null;
}): boolean {
  return f.state != null || f.route != null || f.hasFindings != null;
}
