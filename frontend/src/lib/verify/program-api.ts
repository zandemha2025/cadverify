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
 *    (`service_environment`) — the world that stays attached to each assigned part.
 *    Its response also carries a `portfolio_delta` (Wave-B W6-1) so the view PATCHES
 *    local state instead of refetching the whole (rate-limited) portfolio per edit.
 *
 * Every call goes SAME-ORIGIN through the Next authed proxy (`/api/proxy/*`), so
 * the httpOnly session cookie authenticates it and no API key touches the browser.
 * Honesty: a declared context is a USER assertion (`provenance: "user"`), never
 * inferred; exposure is withheld until a volume is declared.
 *
 * The portfolio SHAPES and the PURE roll-up/patch helpers live in
 * `program-rollup.ts` (no runtime imports, unit-tested under `node --test`); this
 * module is the `fetch` layer over them and re-exports them for callers.
 */
import { API_BASE } from "@/lib/api-base";
import type { Portfolio, PortfolioDelta } from "./program-rollup";

export type {
  PortfolioUnitCost,
  PortfolioContext,
  PortfolioSavings,
  PortfolioRow,
  ProgramRollup,
  PortfolioSummary,
  Portfolio,
  PortfolioDelta,
} from "./program-rollup";
export {
  declaredPrograms,
  rowsInProgram,
  assignableRows,
  applyPortfolioDelta,
} from "./program-rollup";

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

/** The PUT /part-context response: the declared context plus the portfolio delta. */
export interface AssignResult {
  context: DeclaredContext;
  delta: PortfolioDelta | null;
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
 * `service_environment` — the world the part keeps while assigned), applying only
 * the caller's patch. This keeps the honesty invariant: assigning to a program
 * never silently discards a part's declared world.
 *
 * Returns the declared context AND the write's `portfolio_delta` (W6-1) so the
 * caller can patch its in-memory portfolio instead of a full refetch.
 */
export async function assignContext(
  meshHash: string,
  patch: ContextPatch
): Promise<AssignResult> {
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
  const json = await res.json();
  // The write returns the declared context AND (W6-1) the portfolio delta the
  // Programs view patches from. `portfolio_delta` is nested; the rest is context.
  const { portfolio_delta, ...context } = json ?? {};
  return {
    context: context as DeclaredContext,
    delta: (portfolio_delta as PortfolioDelta | undefined) ?? null,
  };
}
