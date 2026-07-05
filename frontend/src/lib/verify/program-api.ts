/**
 * Program / portfolio client for the Verify surface — the REAL org-scoped
 * roll-up (backend/src/api/catalog.py `GET /portfolio`) plus the declared
 * part-context write (backend/src/api/part_context.py `PUT /part-context/{mesh}`).
 *
 * This is what makes the "Program detail" surface REAL end-to-end:
 *  - GET /catalog/portfolio returns every COSTED part, each optionally carrying a
 *    USER-DECLARED `context` (program / assembly / units / annual_volume) and the
 *    honest annualized `$/year` = engine unit cost × your declared volume — present
 *    ONLY when a volume was declared (else null + a reason), never a fabricated
 *    demand quantity. `summary.programs` is the per-program roll-up.
 *  - PUT /part-context/{mesh} assigns a part to a program and/or declares its
 *    annual volume. We MERGE-then-write (see `assignContext`) so a program
 *    assignment never silently clobbers the part's declared world
 *    (`service_environment`) — the world every part under the program inherits.
 *
 * Every call goes SAME-ORIGIN through the Next authed proxy (`/api/proxy/*`), so
 * the httpOnly session cookie authenticates it and no API key touches the browser.
 * Honesty: a declared context is a USER assertion (`provenance: "user"`), never
 * inferred; exposure is withheld until a volume is declared.
 */
import { API_BASE } from "@/lib/api-base";

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

/** Relay the backend's structured error `detail` as the thrown Error message. */
async function toError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null);
  const detail =
    (body && (body.detail || body.message)) || `Request failed (${res.status})`;
  return new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
}

export async function getPortfolio(): Promise<Portfolio> {
  const res = await fetch(`${API_BASE}/catalog/portfolio`, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** The single declared context for a part (GET /part-context/{mesh}); 404 → null
 *  (no declaration yet). */
export interface DeclaredContext {
  mesh_hash: string;
  program: string | null;
  parent_assembly: string | null;
  units_per_parent: number | null;
  annual_volume: number | null;
  provenance: string;
  service_environment?: Record<string, unknown> | null;
}

export async function getContext(
  meshHash: string
): Promise<DeclaredContext | null> {
  const res = await fetch(
    `${API_BASE}/part-context/${encodeURIComponent(meshHash)}`,
    { cache: "no-store" }
  );
  if (res.status === 404) return null;
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** The fields the program surface can declare. `undefined` = leave as-is (merged
 *  from the existing row); `null` = explicitly clear. `annual_volume` must be a
 *  positive integer or null — the backend 400s on <= 0 (a physical count of 0/-5
 *  is nonsense), and we never send a fabricated volume. */
export interface ContextPatch {
  program?: string | null;
  annual_volume?: number | null;
}

/**
 * Assign a part to a program and/or declare its annual volume.
 *
 * MERGE-then-PUT: the backend's upsert overwrites ALL declared fields, so a naïve
 * `PUT {program}` would wipe the part's declared world and volume. We first read
 * the existing context and re-send the untouched fields (including
 * `service_environment` — the world the program's parts inherit), applying only
 * the caller's patch. This keeps the honesty invariant: assigning to a program
 * never silently discards a part's declared world.
 */
export async function assignContext(
  meshHash: string,
  patch: ContextPatch
): Promise<DeclaredContext> {
  const existing = await getContext(meshHash).catch(() => null);

  const body: Record<string, unknown> = {
    program:
      patch.program !== undefined ? patch.program : existing?.program ?? null,
    parent_assembly: existing?.parent_assembly ?? null,
    units_per_parent: existing?.units_per_parent ?? null,
    annual_volume:
      patch.annual_volume !== undefined
        ? patch.annual_volume
        : existing?.annual_volume ?? null,
  };
  // Preserve the declared world verbatim — never re-declared, never dropped.
  if (existing?.service_environment != null) {
    body.service_environment = existing.service_environment;
  }

  const res = await fetch(
    `${API_BASE}/part-context/${encodeURIComponent(meshHash)}`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    }
  );
  if (!res.ok) throw await toError(res);
  return res.json();
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
      { program: name, parts: 0, annualized_cost_usd: null, annualized_savings_usd: null };
    g.parts += 1;
    if (r.annualized_cost_usd != null) {
      g.annualized_cost_usd = round2((g.annualized_cost_usd ?? 0) + r.annualized_cost_usd);
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

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Rows assigned to a program (context.program === name). */
export function rowsInProgram(p: Portfolio, name: string): PortfolioRow[] {
  return p.rows.filter((r) => r.context?.program === name);
}

/** Costed rows NOT in this program — candidates to assign. */
export function assignableRows(p: Portfolio, name: string): PortfolioRow[] {
  return p.rows.filter((r) => r.context?.program !== name);
}
