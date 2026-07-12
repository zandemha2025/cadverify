/**
 * Portfolio SHAPES + PURE roll-up/patch helpers for the Programs surface.
 *
 * Deliberately split out of `program-api.ts` (which carries the runtime `fetch`
 * layer + its `@/lib/api-base` import): this module has NO runtime imports — only
 * erased type shapes — so it unit-tests under the repo's `node --test`
 * type-stripping runner exactly like `lib/catalog`, `lib/dfm-scope`, etc., and
 * shares ONE implementation with the render layer. It invents nothing: every
 * figure it returns is a passthrough or a sum of engine/DB-supplied numbers.
 */

/** Withheld-aware unit cost, exactly as the portfolio serializes it
 *  (catalog_service.derive_row). `usd` is null on a DFM-blocked route; `validated`
 *  rides the engine's confidence band (False for every assumption-based band). */
export interface PortfolioUnitCost {
  usd: number | null;
  qty: number | null;
  currency: string;
  withheld: boolean;
  withheld_reason: string | null;
  validated: boolean;
}

/** The USER-DECLARED business context on a portfolio row (or null). */
export interface PortfolioContext {
  program: string | null;
  parent_assembly: string | null;
  units_per_parent: number | null;
  annual_volume: number | null;
  service_environment?: Record<string, unknown> | null;
  provenance: string;
}

export interface PortfolioSavings {
  qty: number | string;
  make_now_unit_usd: number;
  redesigned_unit_usd: number;
  save_unit_usd: number;
  save_pct: number;
  redesigned_process: string | null;
  caveat: string | null;
}

/** Exact engine recommendation used for $/year. Its qty always matches the
 *  resolved annual volume; absent means exposure is deliberately withheld. */
export interface AnnualizedUnitCost {
  usd: number;
  qty: number;
  currency: string;
  process: string;
  material: string | null;
  validated: boolean;
  basis: "decision.recommendation";
}

export interface PortfolioRow {
  part_key: string;
  filename: string;
  lifecycle_state: string;
  make_now_process: string | null;
  unit_cost: PortfolioUnitCost | null;
  quantities: number[];
  validated: boolean | null;
  crossover_qty: number | null;
  savings: PortfolioSavings | null;
  reason?: string;
  // Additive declared-context enrichment (present only when the org has declared
  // at least one context — otherwise the row is byte-identical to the base W3).
  context?: PortfolioContext | null;
  annualized_unit_cost?: AnnualizedUnitCost | null;
  annualized_cost_usd?: number | null;
  annualized_savings_usd?: number | null;
  annualized_reason?: string;
}

/** Per-program roll-up (summary.programs) — sums are honest: a part's $/year only
 *  contributes when its owner declared an annual_volume. */
export interface ProgramRollup {
  program: string;
  parts: number;
  annualized_cost_usd: number | null;
  annualized_savings_usd: number | null;
  declared_volume_parts?: number;
  exposed_parts?: number;
}

export interface PortfolioSummary {
  parts: number;
  costed: number;
  drafted: number;
  excluded_no_cost_count: number;
  truncated: boolean;
  posture: Record<string, number>;
  programs?: ProgramRollup[];
}

export interface Portfolio {
  summary: PortfolioSummary;
  rows: PortfolioRow[];
  note?: string;
  context_note?: string;
}

/**
 * The portfolio slice the PUT /part-context write returns (Wave-B W6-1) so the
 * Programs view can PATCH its in-memory portfolio instead of refetching the whole
 * (rate-limited) portfolio on every edit. Both figures are computed by the backend
 * on the SAME `build_portfolio` path `GET /portfolio` uses, so patching from them
 * is byte-identical to a full refetch — the rollup never drifts from the engine.
 */
export interface PortfolioDelta {
  /** the recomputed row for the edited part (or null when it is no longer a
   *  costed portfolio row) — carries its context + honest annualized $/year. */
  row: PortfolioRow | null;
  /** the FULL recomputed per-program rollup — replaces summary.programs verbatim
   *  (empty when no declared program remains). */
  programs: ProgramRollup[];
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Declared programs derived from the portfolio: the authoritative
 *  `summary.programs` roll-up when present, else grouped from the rows (so a
 *  freshly-loaded portfolio with contexts but no roll-up still lists them). Rows
 *  without a declared program are ignored. Sorted by name for a stable order. */
export function declaredPrograms(p: Portfolio): ProgramRollup[] {
  if (p.summary.programs && p.summary.programs.length) {
    return [...p.summary.programs].sort((a, b) =>
      a.program.localeCompare(b.program)
    );
  }
  const groups = new Map<string, ProgramRollup>();
  for (const r of p.rows) {
    const name = r.context?.program;
    if (!name) continue;
    const g =
      groups.get(name) ??
      {
        program: name,
        parts: 0,
        annualized_cost_usd: null,
        annualized_savings_usd: null,
        declared_volume_parts: 0,
        exposed_parts: 0,
      };
    g.parts += 1;
    if (r.context?.annual_volume != null) g.declared_volume_parts = (g.declared_volume_parts ?? 0) + 1;
    if (r.annualized_cost_usd != null) {
      g.annualized_cost_usd = round2((g.annualized_cost_usd ?? 0) + r.annualized_cost_usd);
      g.exposed_parts = (g.exposed_parts ?? 0) + 1;
    }
    if (r.annualized_savings_usd != null) {
      g.annualized_savings_usd = round2(
        (g.annualized_savings_usd ?? 0) + r.annualized_savings_usd
      );
    }
    groups.set(name, g);
  }
  return [...groups.values()].sort((a, b) => a.program.localeCompare(b.program));
}

/** Rows assigned to a program (context.program === name). */
export function rowsInProgram(p: Portfolio, name: string): PortfolioRow[] {
  return p.rows.filter((r) => r.context?.program === name);
}

/** Costed rows NOT in this program — candidates to assign. */
export function assignableRows(p: Portfolio, name: string): PortfolioRow[] {
  return p.rows.filter((r) => r.context?.program !== name);
}

/**
 * PATCH an in-memory portfolio with a write's `PortfolioDelta` — the same result a
 * full `GET /portfolio` refetch would produce, without the extra rate-limited read
 * (Wave-B W6-1). Replaces the edited part's row with the backend's recomputed row
 * (removing it if the part is no longer a costed portfolio row) and swaps in the
 * backend's recomputed per-program rollup verbatim. Pure — returns a new object.
 *
 * Byte-identity is guaranteed by construction: `delta.row` and `delta.programs`
 * are lifted straight from `build_portfolio` (the read endpoint's code path), so
 * the patched portfolio's displayed rollup never drifts from the engine's.
 */
export function applyPortfolioDelta(
  portfolio: Portfolio,
  meshHash: string,
  delta: PortfolioDelta
): Portfolio {
  const rows = portfolio.rows.filter((r) => r.part_key !== meshHash);
  if (delta.row) rows.push(delta.row);
  return {
    ...portfolio,
    rows,
    summary: { ...portfolio.summary, programs: delta.programs },
  };
}
