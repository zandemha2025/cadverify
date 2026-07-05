/**
 * Programs / portfolio client for the Verify surface — the REAL org-scoped
 * portfolio roll-up (backend/src/api/catalog.py, GET /api/v1/catalog/portfolio)
 * plus the declared part-context surface (backend/src/api/part_context.py, GET +
 * PUT /api/v1/part-context/{mesh_hash}) that groups a costed part into a program
 * and declares its annual build volume.
 *
 * Every call goes SAME-ORIGIN through the Next authed proxy (`/api/proxy/*`), so
 * the httpOnly session cookie authenticates it and no API key touches the browser.
 *
 * HONESTY: exposure ($/year) is NEVER computed here. The engine already annualized
 * it server-side — `annualized_cost_usd` = the engine's verified unit cost × the
 * user's DECLARED annual_volume — and returns it ONLY when a volume was declared
 * (else null + a reason). No volume → withheld, never $0. A declared program /
 * volume is a USER assertion (`provenance: "user"`), never inferred from the mesh.
 */
import { API_BASE } from "@/lib/api-base";

/** withheld-aware unit cost dict, exactly as the portfolio serializes it. */
export interface PortfolioUnitCost {
  usd: number | null;
  process?: string | null;
  withheld?: boolean;
  withheld_reason?: string | null;
  /** copied from the engine's confidence band — never set client-side. */
  validated?: boolean;
}

/** The USER-DECLARED context block on a portfolio row (null when undeclared). */
export interface PortfolioContext {
  program: string | null;
  parent_assembly: string | null;
  units_per_parent: number | null;
  annual_volume: number | null;
  provenance: "user";
}

export interface PortfolioRow {
  part_key: string; // the part's mesh_hash — the key part-context is declared on
  filename: string | null;
  lifecycle_state: string;
  make_now_process: string | null;
  unit_cost: PortfolioUnitCost | null;
  quantities: number[];
  validated: boolean | null;
  crossover_qty: number | null;
  savings: unknown | null;
  reason?: string;
  // additive — present only when the org has declared at least one context.
  context?: PortfolioContext | null;
  annualized_cost_usd?: number | null;
  annualized_savings_usd?: number | null;
  annualized_reason?: string;
}

/** Per-program roll-up from the summary (present only when ≥1 program declared). */
export interface PortfolioProgram {
  program: string;
  parts: number;
  /** sum of member parts' $/year — null until a member declares an annual_volume. */
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
  programs?: PortfolioProgram[];
}

export interface Portfolio {
  summary: PortfolioSummary;
  rows: PortfolioRow[];
  note?: string;
  context_note?: string;
}

/** A declared part-context, exactly as the backend serializes it. */
export interface DeclaredContext {
  mesh_hash: string;
  program: string | null;
  parent_assembly: string | null;
  units_per_parent: number | null;
  annual_volume: number | null;
  provenance: "user";
  service_environment?: Record<string, unknown> | null;
}

const CATALOG = `${API_BASE}/catalog`;
const CTX = `${API_BASE}/part-context`;

/** Relay the backend's structured `detail` as the thrown Error message. */
async function toError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null);
  const detail =
    (body && (body.detail || body.message)) || `Request failed (${res.status})`;
  return new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
}

export async function fetchPortfolio(): Promise<Portfolio> {
  const res = await fetch(`${CATALOG}/portfolio`, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** The declared context for a part, or null when none (404). */
export async function getPartContext(
  meshHash: string
): Promise<DeclaredContext | null> {
  const res = await fetch(`${CTX}/${encodeURIComponent(meshHash)}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw await toError(res);
  return res.json();
}

/**
 * Group a costed part into a program and/or declare its annual build volume.
 *
 * MERGE-PRESERVING by design: the PUT replaces the WHOLE context row server-side
 * (upsert_context overwrites every declared field), so we first GET the existing
 * context and carry forward its parent_assembly, units_per_parent, AND declared
 * service_environment — assigning a program must NEVER silently wipe a world the
 * user already declared at the Verify door. Only the fields in `patch` change.
 *
 * `annual_volume` must be a positive integer or the backend 400s (a build count
 * of 0 or negative is nonsense); we surface that error verbatim, never swallow it.
 */
export async function declarePartProgram(
  meshHash: string,
  patch: { program?: string | null; annual_volume?: number | null }
): Promise<DeclaredContext> {
  // Best-effort read of the current row so we never clobber prior declarations.
  const existing = await getPartContext(meshHash).catch(() => null);
  const body = {
    program:
      patch.program !== undefined ? patch.program : existing?.program ?? null,
    parent_assembly: existing?.parent_assembly ?? null,
    units_per_parent: existing?.units_per_parent ?? null,
    annual_volume:
      patch.annual_volume !== undefined
        ? patch.annual_volume
        : existing?.annual_volume ?? null,
    service_environment: existing?.service_environment ?? null,
  };
  const res = await fetch(`${CTX}/${encodeURIComponent(meshHash)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** A costed part is assignable/exposable only when it has a REAL unit cost — a
 *  DFM-withheld (blocked-route) price can never be annualized into exposure. */
export function hasVerifiedCost(row: PortfolioRow): boolean {
  const uc = row.unit_cost;
  return !!uc && !uc.withheld && typeof uc.usd === "number" && Number.isFinite(uc.usd);
}

/** The part's declared program name, or null. */
export function programOf(row: PortfolioRow): string | null {
  return row.context?.program ?? null;
}
