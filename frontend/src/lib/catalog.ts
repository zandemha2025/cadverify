/**
 * catalog — the PURE derivations behind the cost-engineer catalog grid (D5 FE-4,
 * Door B). No React, no DOM, no runtime imports (only erased type imports), so it
 * is unit-testable with `node --test` and shares one implementation with the
 * render layer — the same discipline as `lib/dfm-scope`, `lib/findings`,
 * `lib/cost-views`.
 *
 * The grid is a table over the user's REAL saved should-cost decisions
 * (`/cost-decisions` + per-decision `result_json`). Each row's numbers are read
 * VERBATIM off the engine's `report_to_dict` — nothing is invented:
 *
 *   • route          — decision.make_now_process / material (the recommended make).
 *   • unit $         — the make-now estimate's unit_cost_usd. WITHHELD (null) when
 *                      the route is DFM-blocked, so the grid never prints a price
 *                      for a part that can't be made as-designed (D1 honesty).
 *   • posture        — the provenance mix of that estimate's drivers: filled =
 *                      grounded (MEASURED / SHOP / USER), hollow = guess (DEFAULT).
 *   • route blockers — the make-now estimate's `dfm_blockers` count (route-scoped,
 *                      real). NOTE: this is NOT the full DFM findings count — the
 *                      saved cost decision does not embed the DFM Issue array that
 *                      `lib/dfm-scope` scopes, so a severity-bucketed findings count
 *                      per row is a BACKEND item (join the analysis / catalog
 *                      aggregate), flagged in the UI, never faked here.
 *   • lifecycle      — the grounding state of the make-now route, derived from real
 *                      fields (blocked → validated → overridden → calibrated →
 *                      assumption). "validated" only when the engine's confidence
 *                      band is actually validated (a real quote) — not reachable
 *                      today, and honestly so.
 *
 * IMPORTS ARE TYPE-ONLY (erased at runtime) so this module resolves under the
 * repo's `node --test` type-stripping runner exactly like the other pure libs.
 */
import type { CostReport, CostEstimate, CostDriver, Provenance } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

/** The provenance mix across an estimate's drivers — the posture atom. */
export interface PostureCounts {
  measured: number;
  shop: number;
  user: number;
  default: number;
  /** total drivers counted */
  total: number;
  /** grounded = MEASURED + SHOP + USER (filled markers) */
  grounded: number;
  /** guess = DEFAULT (hollow ring) */
  guess: number;
  /** grounded / total in [0,1]; 0 when total is 0 */
  groundedPct: number;
}

/**
 * The grounding lifecycle of a decision's make-now route, in priority order.
 *   blocked     — the recommended route is not DFM-ready (price withheld).
 *   validated   — the confidence band is a validated quote (brass). Honestly not
 *                 reachable today (every band is `validated:false`), kept for when
 *                 real residuals accrue.
 *   overridden  — a make-now driver was manually overridden (USER) — the override queue.
 *   calibrated  — a make-now driver is bound to your shop's rate (SHOP).
 *   assumption  — otherwise: generic default rates (DEFAULT-heavy).
 *   unknown     — no decision / no costed estimate (e.g. GEOMETRY_INVALID).
 */
export type CatalogLifecycle =
  | "blocked"
  | "validated"
  | "overridden"
  | "calibrated"
  | "assumption"
  | "unknown";

export interface CatalogMetrics {
  /** raw engine process id of the recommended make-now route ("" → none) */
  routeProcess: string | null;
  /** the make-now material class, when the estimate carries one */
  routeMaterial: string | null;
  /** the quantity the unit price is quoted at (the make-now estimate's qty) */
  refQty: number | null;
  /** the recommended route's unit cost — null when withheld (blocked) or absent */
  unitUsd: number | null;
  /** true when the recommended route is DFM-blocked → the price is withheld */
  blocked: boolean;
  /** the first DFM blocker on the route (the honest reason a price is withheld) */
  withheldReason: string | null;
  /** DFM blockers on the make-now route (route-scoped, real) */
  routeBlockerCount: number;
  /** provenance posture of the make-now estimate's drivers */
  posture: PostureCounts;
  /** the grounding lifecycle state of the make-now route */
  lifecycle: CatalogLifecycle;
}

/* ------------------------------------------------------------------ */
/*  Self-contained helpers (no lib imports — node --test friendly)     */
/* ------------------------------------------------------------------ */

const EMPTY_POSTURE: PostureCounts = {
  measured: 0,
  shop: 0,
  user: 0,
  default: 0,
  total: 0,
  grounded: 0,
  guess: 0,
  groundedPct: 0,
};

/** The provenance mix across a set of drivers (filled vs hollow). */
export function posture(drivers: readonly CostDriver[] | null | undefined): PostureCounts {
  if (!drivers || drivers.length === 0) return { ...EMPTY_POSTURE };
  const c = { measured: 0, shop: 0, user: 0, default: 0 };
  for (const d of drivers) {
    switch (d.provenance) {
      case "MEASURED":
        c.measured++;
        break;
      case "SHOP":
        c.shop++;
        break;
      case "USER":
        c.user++;
        break;
      default:
        c.default++;
        break;
    }
  }
  const total = c.measured + c.shop + c.user + c.default;
  const grounded = c.measured + c.shop + c.user;
  const guess = c.default;
  return {
    ...c,
    total,
    grounded,
    guess,
    groundedPct: total > 0 ? grounded / total : 0,
  };
}

/**
 * The estimate behind the recommended make-now route — the FIRST estimate for
 * `decision.make_now_process` (the lowest-qty / near-term make), matching the
 * `pickEstimate(report, make_now_process)` convention the saved-decision hero and
 * the resident Inspector already use. Returns null when there is no decision or
 * no matching estimate.
 */
export function makeNowEstimate(report: CostReport | null | undefined): CostEstimate | null {
  const proc = report?.decision?.make_now_process?.trim();
  if (!report || !proc) return null;
  return report.estimates.find((e) => e.process === proc) ?? null;
}

/** Whether any driver carries a given provenance. */
function hasProvenance(est: CostEstimate, p: Provenance): boolean {
  return (est.drivers ?? []).some((d) => d.provenance === p);
}

/* ------------------------------------------------------------------ */
/*  The row derivation                                                 */
/* ------------------------------------------------------------------ */

/**
 * Derive one catalog row's metrics from a saved decision's verbatim report.
 * Every field binds to a real engine field; a missing field yields a null/"—"
 * cell, never a fabricated figure.
 */
export function deriveCatalogMetrics(report: CostReport | null | undefined): CatalogMetrics {
  const est = makeNowEstimate(report);
  if (!est) {
    return {
      routeProcess: report?.decision?.make_now_process?.trim() || null,
      routeMaterial: report?.decision?.make_now_material?.trim() || null,
      refQty: null,
      unitUsd: null,
      blocked: false,
      withheldReason: null,
      routeBlockerCount: 0,
      posture: { ...EMPTY_POSTURE },
      lifecycle: "unknown",
    };
  }

  const blocked = !est.dfm_ready;
  const blockers = est.dfm_blockers ?? [];
  const post = posture(est.drivers);

  let lifecycle: CatalogLifecycle;
  if (blocked) lifecycle = "blocked";
  else if (est.confidence?.validated) lifecycle = "validated";
  else if (hasProvenance(est, "USER")) lifecycle = "overridden";
  else if (hasProvenance(est, "SHOP")) lifecycle = "calibrated";
  else lifecycle = "assumption";

  return {
    routeProcess: est.process || report?.decision?.make_now_process?.trim() || null,
    routeMaterial: est.material || report?.decision?.make_now_material?.trim() || null,
    refQty: Number.isFinite(est.quantity) ? est.quantity : null,
    // Withhold the price on a DFM-blocked route — never print a make-price for a
    // part that can't be made as-designed.
    unitUsd: blocked ? null : est.unit_cost_usd,
    blocked,
    withheldReason: blocked ? blockers[0] ?? "Recommended route is not DFM-ready." : null,
    routeBlockerCount: blockers.length,
    posture: post,
    lifecycle,
  };
}

/* ------------------------------------------------------------------ */
/*  Saved views — REAL client-side filters over the fetched rows       */
/* ------------------------------------------------------------------ */

export type SavedViewId = "all" | "override" | "assumption" | "blocked";

export interface SavedViewDef {
  id: SavedViewId;
  label: string;
  /** one-line meaning (tooltip / legend) */
  description: string;
  /**
   * A saved view is REAL when it filters on a real engine field (never
   * presentational-only). All four here are real; the flag exists so the UI can
   * honestly label any future view that is cosmetic.
   */
  real: boolean;
}

export const SAVED_VIEWS: SavedViewDef[] = [
  {
    id: "all",
    label: "All parts",
    description: "Every saved cost decision.",
    real: true,
  },
  {
    id: "override",
    label: "My override queue",
    description: "Decisions whose make-now route carries a rate you overrode (USER provenance).",
    real: true,
  },
  {
    id: "assumption",
    label: "DEFAULT-heavy",
    description: "Still on generic default rates — no shop bound, no override, not yet grounded.",
    real: true,
  },
  {
    id: "blocked",
    label: "Price withheld",
    description: "The recommended route is DFM-blocked, so the price is withheld.",
    real: true,
  },
];

export function savedViewById(id: SavedViewId): SavedViewDef {
  return SAVED_VIEWS.find((v) => v.id === id) ?? SAVED_VIEWS[0];
}

/**
 * Whether a row's metrics match a saved view. PURE over the derived metrics, so
 * the filter is the same real predicate the tests exercise and the grid applies.
 * (The caller applies this only to HYDRATED rows — an un-hydrated row has no
 * metrics yet and is honestly counted as "still loading", not silently matched.)
 */
export function matchesSavedView(metrics: CatalogMetrics, view: SavedViewId): boolean {
  switch (view) {
    case "all":
      return true;
    case "override":
      return metrics.lifecycle === "overridden";
    case "assumption":
      return metrics.lifecycle === "assumption";
    case "blocked":
      return metrics.blocked;
    default:
      return true;
  }
}

/* ------------------------------------------------------------------ */
/*  Sort + format helpers (pure)                                       */
/* ------------------------------------------------------------------ */

/**
 * A stable rank for sorting the lifecycle column, worst-first (blocked highest).
 * `unknown` sorts last so un-costed rows sink to the bottom.
 */
export function lifecycleRank(l: CatalogLifecycle): number {
  switch (l) {
    case "blocked":
      return 5;
    case "assumption":
      return 4;
    case "calibrated":
      return 3;
    case "overridden":
      return 2;
    case "validated":
      return 1;
    case "unknown":
    default:
      return 0;
  }
}

/** Format a unit price the way the rest of the cost surfaces speak it ($X.XX). */
export function formatUnitUsd(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
