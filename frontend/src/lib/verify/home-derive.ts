/**
 * Pure derivations for the Home "verification desk". No fabrication: every row is
 * built from a REAL engine/DB output the caller passed in, or it is omitted. The
 * design's illustrative demo data (V-0117, object.stl, 268-in-house,
 * "labor_rate $52 → $54", etc.) is NEVER hardcoded here — this module only shapes
 * what the org actually has. Unit-tested in home-derive.test.ts.
 *
 * Honesty contract proven by the tests:
 *   - the Needs-Your-Action queue is EMPTY when there is nothing real to act on;
 *   - a nudge appears ONLY on a KNOWN zero (machineCount === 0, realActuals === 0
 *     with verified records present), never on an unknown (null) count;
 *   - governed change-requests surface only while status === "proposed";
 *   - the activity feed merges only real records + real governance events, sorted
 *     newest-first, and invents no entries.
 */
import type { CostDecisionSummary } from "@/lib/api";
import type { ChangeRequest } from "./governance-api";

/** A row in the Needs-Your-Action queue. `go` is a screen key the shell navigates
 *  to — kept as a plain string so this module stays pure (no closures/nav). */
export interface QueueRow {
  key: string;
  /** severity → dot + accent colour on the surface (cond=amber, fail=red). */
  severity: "cond" | "fail";
  title: string;
  meta: string;
  action: string;
  go: string;
  /** true → render the hatched (assumption, n=0) band treatment on the row. */
  hatched?: boolean;
}

export interface ActivityItem {
  key: string;
  /** short label e.g. "Jul 4" — deterministic (UTC), locale-independent. */
  d: string;
  t: string;
  /** epoch ms used only for sorting; not rendered. */
  at: number;
}

export type DayZeroStepState = "pending" | "needed" | "optional" | "locked" | "unavailable" | "done";
export type DayZeroStepKey = "machines" | "verify" | "program" | "truth";

export interface DayZeroStep {
  key: DayZeroStepKey;
  title: string;
  meta: string;
  state: DayZeroStepState;
}

/**
 * Build the first-run checklist in achievable dependency order. Programs and
 * actuals both require a verified record, so they stay visibly locked until one
 * exists. Optional enrichment is never presented as a prerequisite, and every
 * completion marker comes from persisted organization state.
 */
export function buildDayZeroSetup(input: {
  machineCount: number | null;
  recordCount: number | null;
  programCount: number | null;
  realActualCount: number | null;
  unavailable?: {
    machines?: boolean;
    records?: boolean;
    programs?: boolean;
    actuals?: boolean;
  };
}): DayZeroStep[] {
  const hasRecord = (input.recordCount ?? 0) > 0;
  const unavailable = input.unavailable ?? {};

  return [
    {
      key: "machines",
      title: "Declare machines + rates",
      meta:
        unavailable.machines && input.machineCount == null
          ? "inventory unavailable — retry above"
          : input.machineCount == null
          ? "checking inventory..."
          : input.machineCount > 0
            ? `${input.machineCount} machine${input.machineCount === 1 ? "" : "s"} declared`
            : "add owned machines and their hourly rates",
      state:
        unavailable.machines && input.machineCount == null
          ? "unavailable"
          : input.machineCount == null
            ? "pending"
            : input.machineCount > 0
              ? "done"
              : "needed",
    },
    {
      key: "verify",
      title: "Verify first part",
      meta:
        unavailable.records && input.recordCount == null
          ? "records unavailable — retry above"
          : input.recordCount == null
          ? "checking records..."
          : input.recordCount > 0
            ? `${input.recordCount} record${input.recordCount === 1 ? "" : "s"}`
            : "drop STL, STEP or IGES",
      state:
        unavailable.records && input.recordCount == null
          ? "unavailable"
          : input.recordCount == null
            ? "pending"
            : input.recordCount > 0
              ? "done"
              : "needed",
    },
    {
      key: "program",
      title: "Add program context",
      meta: unavailable.records && input.recordCount == null
        ? "records unavailable — retry above"
        : !hasRecord
        ? "available after your first verified part"
        : unavailable.programs && input.programCount == null
          ? "programs unavailable — retry above"
          : input.programCount == null
          ? "checking programs..."
          : input.programCount > 0
            ? `${input.programCount} program${input.programCount === 1 ? "" : "s"} declared`
            : "optional · assign a part and annual volume",
      state: unavailable.records && input.recordCount == null
        ? "unavailable"
        : !hasRecord
        ? "locked"
        : unavailable.programs && input.programCount == null
          ? "unavailable"
          : input.programCount == null
          ? "pending"
          : input.programCount > 0
            ? "done"
            : "optional",
    },
    {
      key: "truth",
      title: "Send actuals for validation",
      meta: unavailable.records && input.recordCount == null
        ? "records unavailable — retry above"
        : !hasRecord
        ? "available after your first verification"
        : unavailable.actuals && input.realActualCount == null
          ? "ground truth unavailable — retry above"
          : input.realActualCount == null
          ? "checking ground truth..."
          : input.realActualCount > 0
            ? `${input.realActualCount} actual${input.realActualCount === 1 ? "" : "s"} received`
            : "optional · upload actual hours and invoiced costs",
      state: unavailable.records && input.recordCount == null
        ? "unavailable"
        : !hasRecord
        ? "locked"
        : unavailable.actuals && input.realActualCount == null
          ? "unavailable"
          : input.realActualCount == null
          ? "pending"
          : input.realActualCount > 0
            ? "done"
            : "optional",
    },
  ];
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** Deterministic short date ("Jul 4") from an ISO string; "" when unparseable. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const dt = new Date(t);
  return `${MONTHS[dt.getUTCMonth()]} ${dt.getUTCDate()}`;
}

/** Human label for a governed asset type. */
export function assetLabel(assetType: string | null | undefined): string {
  switch (assetType) {
    case "rate_card":
      return "Rate card";
    case "shop_profile":
      return "Shop profile";
    default:
      return String(assetType ?? "asset").replace(/_/g, " ");
  }
}

/** Count of change-requests that NEED a reviewer (status === "proposed"). */
export function proposedCount(changeRequests: ChangeRequest[]): number {
  return changeRequests.reduce((n, cr) => (cr.status === "proposed" ? n + 1 : n), 0);
}

/**
 * The Needs-Your-Action queue, built only from real signals:
 *   1. every proposed governed change-request (awaiting review);
 *   2. "declare your floor" — ONLY when machineCount is a KNOWN 0;
 *   3. "send actuals back" — ONLY when the org has verified records but a KNOWN 0
 *      real ground-truth actuals (so every band is still hatched, n=0).
 * A null count means "unknown / still loading" and never produces a nudge.
 */
export function buildQueue(input: {
  changeRequests: ChangeRequest[];
  machineCount: number | null;
  recordCount: number | null;
  realActualCount: number | null;
}): QueueRow[] {
  const rows: QueueRow[] = [];

  for (const cr of input.changeRequests) {
    if (cr.status !== "proposed") continue;
    const asset = assetLabel(cr.asset_type);
    const title = cr.title.trim() || `${asset} change awaiting review`;
    rows.push({
      key: `cr-${cr.id}`,
      severity: "cond",
      title,
      meta: `${asset} · v${cr.target_version_id} draft · governed change awaiting review`,
      action: "Review",
      go: "calibration",
    });
  }

  if (input.machineCount === 0) {
    rows.push({
      key: "declare-floor",
      severity: "fail",
      title: "Declare your floor",
      meta: "everything starts from the denominator — no machines declared yet",
      action: "Declare",
      go: "machines",
    });
  }

  if ((input.recordCount ?? 0) > 0 && input.realActualCount === 0) {
    rows.push({
      key: "send-actuals",
      severity: "cond",
      title: "No validated bands yet — send actuals back",
      meta: "n=0 · drop real hours & invoiced costs to flip a hatched band solid",
      action: "Calibrate",
      go: "calibration",
      hatched: true,
    });
  }

  return rows;
}

/**
 * The activity feed — a merge of real verifications (cost-decisions) and real
 * governance events (change-requests), newest first. Draft change-requests are
 * pending records, so they are skipped. Nothing is invented; an org with no
 * activity yields an empty list.
 */
export function buildActivity(
  input: {
    records: CostDecisionSummary[];
    changeRequests: ChangeRequest[];
  },
  limit = 6
): ActivityItem[] {
  const items: ActivityItem[] = [];

  for (const r of input.records) {
    const at = Date.parse(r.created_at);
    items.push({
      key: `rec-${r.id}`,
      d: shortDate(r.created_at),
      t: `engine verified ${r.label || r.filename}`,
      at: Number.isFinite(at) ? at : 0,
    });
  }

  for (const cr of input.changeRequests) {
    const asset = assetLabel(cr.asset_type);
    let t: string | null = null;
    let when = cr.created_at;
    if (cr.status === "proposed") {
      t = `proposed ${asset} v${cr.target_version_id} · awaiting review`;
    } else if (cr.status === "approved") {
      t = `approved ${asset} v${cr.target_version_id} → published`;
      when = cr.decided_at || cr.created_at;
    } else if (cr.status === "rejected") {
      t = `rejected ${asset} v${cr.target_version_id} change`;
      when = cr.decided_at || cr.created_at;
    }
    if (t == null) continue; // draft: not an event yet
    const at = Date.parse(when || "");
    items.push({
      key: `cr-${cr.id}-${cr.status}`,
      d: shortDate(when),
      t,
      at: Number.isFinite(at) ? at : 0,
    });
  }

  items.sort((a, b) => b.at - a.at);
  return items.slice(0, limit);
}
