/**
 * Pure derivations for the Part standing page — the org's memory of what was
 * asked, answered, and decided about ONE part. There is NO single part-detail
 * endpoint: a standing is ASSEMBLED from the catalog row (identity + latest
 * verdict), the declared part-context (lineage + volume), and that part's
 * cost-decision history.
 *
 * Every function only SELECTS or FORMATS values the engine/DB already returned,
 * or returns an honest empty/null when the value is absent. NOTHING here invents
 * a number: a withheld price stays withheld, a blocker is a REAL DFM finding
 * (measured vs required, faces, citation), and a part with no home stays
 * home-less. Unit-tested in part-standing.test.ts.
 */
import type {
  CatalogRowApi,
  CostDecisionDetail,
  CostDecisionSummary,
  CostEstimate,
  CostReport,
  Issue,
} from "@/lib/api";
import type { MakeabilityLattice } from "./verification";

/** The make-now route's estimate — the largest-quantity point for the decision's
 *  make-now process (setup fully amortized = the stable read). Inlined (not a
 *  runtime import) so this module stays type-only and runs under the repo's
 *  `node --test` type-stripping runner; mirrors derive.ts's makeNowEstimate. */
function makeNowEstimate(cost: CostReport): CostEstimate | null {
  const proc = cost.decision?.make_now_process;
  const pool = proc ? cost.estimates.filter((e) => e.process === proc) : cost.estimates;
  if (pool.length === 0) return cost.estimates[0] ?? null;
  const usable = pool.filter((e) => !e.environment_excluded);
  const ranked = usable.length > 0 ? usable : pool;
  return ranked.reduce((a, b) => (b.quantity > a.quantity ? b : a));
}

// ---------------------------------------------------------------------------
// Standing tag — the corner label + status colour for a part, from real fields.
// ---------------------------------------------------------------------------

export type StandingKind = "costed" | "blocked" | "drafted" | "invalid";

export interface StandingTag {
  label: string;
  /** one of the light status colours (pass / cond / fail / neutral). */
  tone: "pass" | "cond" | "fail" | "neutral";
}

/** Is this part's route DFM-blocked? The strongest honest signal is the catalog
 *  withholding the make-price (never a make-price for a part that can't be made
 *  as-designed); a positive route_blocker_count corroborates it. */
export function isBlocked(row: CatalogRowApi): boolean {
  return Boolean(row.unit_cost?.withheld) || row.route_blocker_count > 0;
}

/** The part's kind from its real lifecycle + blocker posture. */
export function standingKind(row: CatalogRowApi): StandingKind {
  const costed = row.lifecycle_state === "Costed";
  if (isBlocked(row)) return "blocked";
  if (costed) {
    // Costed but no price and not blocked → a cost artifact with no estimate
    // (e.g. GEOMETRY_INVALID). Honestly "invalid", never a fabricated price.
    if (!row.unit_cost || row.unit_cost.usd == null) return "invalid";
    return "costed";
  }
  return "drafted";
}

export function standingTag(row: CatalogRowApi): StandingTag {
  switch (standingKind(row)) {
    case "costed":
      return { label: "COSTED · RECORD", tone: "neutral" };
    case "blocked":
      return { label: "BLOCKED — SEE FINDINGS", tone: "fail" };
    case "invalid":
      return { label: "GEOMETRY INVALID", tone: "fail" };
    case "drafted":
    default:
      return { label: "DRAFTED — COST REQUIRED", tone: "cond" };
  }
}

// ---------------------------------------------------------------------------
// The headline standing — one card, assembled from the row + latest record.
// ---------------------------------------------------------------------------

export interface PartStanding {
  kind: StandingKind;
  process: string | null;
  routeSource: "costed" | "dfm" | null;
  material: string | null;
  /** the make-now unit cost; null when withheld (blocked) or never costed. */
  unitCostUsd: number | null;
  costQty: number | null;
  withheld: boolean;
  /** confidence.validated on the make-now estimate (false for every assumption
   *  band today — no ground truth yet → the band renders HATCHED, n=0). */
  validated: boolean;
  /** the honest band label, VERBATIM from the engine's confidence object, or null. */
  bandLabel: string | null;
  crossoverQty: number | null;
  /** the cost-decision id backing this standing ("open record →"), or null. */
  recordId: string | null;
  /** when this standing was last updated (catalog updated_at, ISO). */
  updatedAt: string;
  /** Persisted machine-fit lattice, independent of route DFM. Null for records
   *  that predate machine verification or where it was not evaluated. */
  makeabilityVerdict: MakeabilityLattice | null;
}

const MAKEABILITY_VALUES = new Set<MakeabilityLattice>([
  "makeable_in_house",
  "makeable_with_secondary_op",
  "makeable_not_on_owned",
  "makeable_outsource_only",
  "environment_excluded",
  "not_makeable",
  "unknown",
]);

export function deriveStanding(
  row: CatalogRowApi,
  detail: CostDecisionDetail | null
): PartStanding {
  const est = detail?.result ? makeNowEstimate(detail.result) : null;
  const detailWithheld = Boolean(est?.environment_excluded);
  const kind = detailWithheld ? "blocked" : standingKind(row);
  const conf = est?.confidence;
  const rawMakeability = detail?.result.verification?.verdict;
  const makeabilityVerdict =
    typeof rawMakeability === "string" && MAKEABILITY_VALUES.has(rawMakeability as MakeabilityLattice)
      ? (rawMakeability as MakeabilityLattice)
      : null;
  return {
    kind,
    process: row.recommended_route?.process ?? detail?.make_now_process ?? null,
    routeSource: row.recommended_route?.source ?? null,
    material: row.recommended_route?.material ?? est?.material ?? null,
    unitCostUsd:
      row.unit_cost?.withheld || detailWithheld
        ? null
        : row.unit_cost?.usd ?? est?.unit_cost_usd ?? null,
    costQty: row.unit_cost?.qty ?? est?.quantity ?? null,
    withheld: Boolean(row.unit_cost?.withheld || detailWithheld),
    // Prefer the record's own confidence flag; fall back to the row's.
    validated: conf?.validated ?? row.unit_cost?.validated ?? false,
    bandLabel: conf?.label ?? null,
    crossoverQty: detail?.crossover_qty ?? null,
    recordId: row.cost_decision?.id ?? null,
    updatedAt: row.updated_at,
    makeabilityVerdict,
  };
}

// ---------------------------------------------------------------------------
// Blockers — the REAL DFM findings on the latest verdict, never invented.
// ---------------------------------------------------------------------------

export interface Blocker {
  code: string;
  message: string;
  fix: string | null;
  /** measured vs required (e.g. sidewall 0.6° vs 1.0°) — present when the finding
   *  carries them; never fabricated. */
  measured: number | null;
  required: number | null;
  /** honest total of affected faces (the analyzer's true count), or null. */
  affectedFaces: number | null;
  /** formatted standard reference ("NACE MR0175 · §7.2"), or null when uncited. */
  citation: string | null;
  process: string | null;
  /** "localized" (has faces/region) vs "whole_part" (honestly unlocalizable). */
  scope: string | null;
}

function formatCitation(issue: Issue): string | null {
  const c = issue.citation;
  if (!c) return null;
  const parts = [c.standard, c.clause].filter(Boolean);
  if (parts.length === 0) return c.text ?? c.rule_id ?? null;
  return parts.join(" · ");
}

function issueToBlocker(issue: Issue): Blocker {
  return {
    code: issue.code,
    message: issue.message,
    fix: issue.fix_suggestion ?? null,
    measured: issue.measured_value ?? null,
    required: issue.required_value ?? null,
    affectedFaces: issue.affected_face_count ?? null,
    citation: formatCitation(issue),
    process: issue.process ?? null,
    scope: issue.scope ?? null,
  };
}

/**
 * The part's blockers, most-specific source first:
 *   1. the make-now cost estimate's FULL blocker Issues (faces / measured /
 *      required / citation) — the richest, located finding;
 *   2. its blocker MESSAGE strings, when the full Issues predate the relink;
 *   3. the catalog row's `withheld_reason` (a real message) as a last resort.
 * Returns [] when the part is not blocked — the caller shows the makeable or
 * drafted standing instead. Never returns a fabricated blocker.
 */
export function extractBlockers(
  row: CatalogRowApi,
  detail: CostDecisionDetail | null
): Blocker[] {
  if (detail?.result) {
    const est = makeNowEstimate(detail.result);
    const issues = est?.dfm_blocker_details;
    if (issues && issues.length > 0) return issues.map(issueToBlocker);
    const msgs = est?.dfm_blockers;
    if (msgs && msgs.length > 0) {
      return msgs.map((m) => ({
        code: "",
        message: m,
        fix: null,
        measured: null,
        required: null,
        affectedFaces: null,
        citation: null,
        process: est?.process ?? null,
        scope: null,
      }));
    }
  }
  const reason = row.unit_cost?.withheld ? row.unit_cost.withheld_reason : null;
  if (reason) {
    return [
      {
        code: "",
        message: reason,
        fix: null,
        measured: null,
        required: null,
        affectedFaces: null,
        citation: null,
        process: row.recommended_route?.process ?? null,
        scope: null,
      },
    ];
  }
  return [];
}

// ---------------------------------------------------------------------------
// Lineage — program → assembly → part, from the DECLARED context (or "no home").
// ---------------------------------------------------------------------------

export interface LineageView {
  /** true when a program is declared; false → the honest "no home yet" state. */
  hasHome: boolean;
  program: string | null;
  parentAssembly: string | null;
  annualVolume: number | null;
}

export function lineageView(
  context: { program: string | null; parent_assembly: string | null; annual_volume: number | null } | null
): LineageView {
  return {
    hasHome: Boolean(context?.program),
    program: context?.program ?? null,
    parentAssembly: context?.parent_assembly ?? null,
    annualVolume: context?.annual_volume ?? null,
  };
}

// ---------------------------------------------------------------------------
// History — "every verification appends here". The cost-decisions endpoint's
// list items carry filename but NOT mesh_hash, so a part's history is the set of
// saved decisions sharing this file's name, newest first. Real DB rows only;
// each links to its own immutable record.
// ---------------------------------------------------------------------------

export function historyForFile(
  decisions: CostDecisionSummary[],
  filename: string
): CostDecisionSummary[] {
  return decisions
    .filter((d) => d.filename === filename)
    .sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
}
