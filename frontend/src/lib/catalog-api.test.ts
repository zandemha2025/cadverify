import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mapPosture,
  resolveHref,
  mapCatalogItem,
  mapCatalogItems,
  routeFacets,
  stateFacetCount,
  hasActiveFilters,
} from "./catalog-api.ts";
import type {
  CatalogRowApi,
  CatalogPosture,
  CatalogFacets,
} from "./api.ts";

/* ------------------------------------------------------------------ */
/*  Real-shaped fixtures (mirror catalog_service.derive_row output)    */
/* ------------------------------------------------------------------ */

function posture(over: Partial<CatalogPosture> = {}): CatalogPosture {
  return {
    measured: 1,
    shop: 1,
    user: 0,
    default: 2,
    total: 4,
    grounded: 2,
    guess: 2,
    grounded_pct: 0.5,
    ...over,
  };
}

function row(over: Partial<CatalogRowApi> = {}): CatalogRowApi {
  return {
    part_key: "meshA",
    filename: "bracket.step",
    file_type: "step",
    lifecycle_state: "Costed",
    recommended_route: { process: "cnc_3axis", material: "aluminum", source: "costed" },
    unit_cost: {
      usd: 12.5,
      qty: 50,
      currency: "USD",
      withheld: false,
      withheld_reason: null,
      validated: false,
    },
    findings: { total: 2, critical: 1, advisory: 1, info: 0, scoped_process: "cnc_3axis" },
    provenance_posture: posture(),
    route_blocker_count: 0,
    cost_decision: { id: "cd_1", url: "/api/v1/cost-decisions/cd_1" },
    analysis: { id: "an_1", url: "/api/v1/analyses/an_1" },
    updated_at: "2026-07-01T00:00:00+00:00",
    ...over,
  };
}

/* ------------------------------------------------------------------ */
/*  mapPosture — snake→camel, verbatim, null-safe                      */
/* ------------------------------------------------------------------ */

test("mapPosture: renames grounded_pct → groundedPct and copies counts verbatim", () => {
  const p = mapPosture(posture({ measured: 3, grounded: 4, total: 6, grounded_pct: 0.6667 }));
  assert.equal(p?.measured, 3);
  assert.equal(p?.grounded, 4);
  assert.equal(p?.total, 6);
  assert.equal(p?.groundedPct, 0.6667);
  // never recomputed — we trust the server number verbatim
});

test("mapPosture: null/undefined posture → null (honest absence, no zero object)", () => {
  assert.equal(mapPosture(null), null);
  assert.equal(mapPosture(undefined), null);
});

/* ------------------------------------------------------------------ */
/*  resolveHref — costed → decision hero, drafted → analysis           */
/* ------------------------------------------------------------------ */

test("resolveHref: a costed part opens its saved decision hero", () => {
  assert.equal(resolveHref(row()), "/cost-decisions/cd_1");
});

test("resolveHref: a drafted part (analysis only) opens its analysis", () => {
  const r = row({ lifecycle_state: "Drafted", cost_decision: null });
  assert.equal(resolveHref(r), "/analyses/an_1");
});

test("resolveHref: no source artifact → empty string (non-clickable, never routes nowhere)", () => {
  assert.equal(resolveHref(row({ cost_decision: null, analysis: null })), "");
});

/* ------------------------------------------------------------------ */
/*  mapCatalogItem — field-for-field, honest nulls                     */
/* ------------------------------------------------------------------ */

test("mapCatalogItem: a costed, clean, priced row maps every real field", () => {
  const it = mapCatalogItem(row());
  assert.equal(it.partKey, "meshA");
  assert.equal(it.lifecycleState, "Costed");
  assert.equal(it.routeProcess, "cnc_3axis");
  assert.equal(it.routeMaterial, "aluminum");
  assert.equal(it.routeSource, "costed");
  assert.equal(it.unitCost?.usd, 12.5);
  assert.equal(it.unitCost?.withheld, false);
  assert.equal(it.unitCost?.validated, false);
  assert.equal(it.findings?.total, 2);
  assert.equal(it.findings?.critical, 1);
  assert.equal(it.findings?.scopedProcess, "cnc_3axis");
  assert.equal(it.posture?.groundedPct, 0.5);
  assert.equal(it.href, "/cost-decisions/cd_1");
});

test("mapCatalogItem: a DFM-blocked route withholds the price honestly (usd null, reason kept)", () => {
  const it = mapCatalogItem(
    row({
      unit_cost: {
        usd: null,
        qty: 50,
        currency: "USD",
        withheld: true,
        withheld_reason: "Wall too thin for CNC.",
        validated: false,
      },
    })
  );
  assert.equal(it.unitCost?.usd, null);
  assert.equal(it.unitCost?.withheld, true);
  assert.equal(it.unitCost?.withheldReason, "Wall too thin for CNC.");
});

test("mapCatalogItem: a Drafted part has no cost artifact → unitCost null, route from DFM", () => {
  const it = mapCatalogItem(
    row({
      lifecycle_state: "Drafted",
      recommended_route: { process: "cnc_3axis", material: null, source: "dfm" },
      unit_cost: null,
      provenance_posture: null,
      cost_decision: null,
    })
  );
  assert.equal(it.unitCost, null);
  assert.equal(it.posture, null);
  assert.equal(it.routeSource, "dfm");
  assert.equal(it.href, "/analyses/an_1");
});

test("mapCatalogItem: findings null (no analysis) stays null — not faked as zero", () => {
  const it = mapCatalogItem(row({ findings: null, analysis: null }));
  assert.equal(it.findings, null);
});

test("mapCatalogItem: a null recommended route yields null route fields, no throw", () => {
  const it = mapCatalogItem(row({ recommended_route: null }));
  assert.equal(it.routeProcess, null);
  assert.equal(it.routeMaterial, null);
  assert.equal(it.routeSource, null);
});

test("mapCatalogItems: maps a list preserving order", () => {
  const items = mapCatalogItems([row({ part_key: "a" }), row({ part_key: "b" })]);
  assert.deepEqual(
    items.map((i) => i.partKey),
    ["a", "b"]
  );
});

/* ------------------------------------------------------------------ */
/*  Facet helpers                                                      */
/* ------------------------------------------------------------------ */

const FACETS: CatalogFacets = {
  state: { Costed: 3, Drafted: 1 },
  route: { cnc_3axis: 4, sheet_metal: 2, sls: 2 },
  findings: { with_findings: 2, without_findings: 1, unknown: 1 },
};

test("routeFacets: sorted by count desc, then process asc as a stable tiebreak", () => {
  assert.deepEqual(routeFacets(FACETS), [
    { process: "cnc_3axis", count: 4 },
    { process: "sheet_metal", count: 2 },
    { process: "sls", count: 2 },
  ]);
});

test("stateFacetCount: reads the real count, 0 when the state is absent", () => {
  assert.equal(stateFacetCount(FACETS, "Costed"), 3);
  assert.equal(stateFacetCount(FACETS, "Drafted"), 1);
  assert.equal(stateFacetCount({ ...FACETS, state: {} }, "Costed"), 0);
});

test("hasActiveFilters: true iff any facet dimension is set", () => {
  assert.equal(hasActiveFilters({ state: null, route: null, hasFindings: null }), false);
  assert.equal(hasActiveFilters({ state: "Costed", route: null, hasFindings: null }), true);
  assert.equal(hasActiveFilters({ state: null, route: "cnc_3axis", hasFindings: null }), true);
  assert.equal(hasActiveFilters({ state: null, route: null, hasFindings: false }), true);
});
