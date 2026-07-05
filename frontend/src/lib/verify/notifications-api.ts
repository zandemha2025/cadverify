/**
 * Notifications data layer for the Verify surface — "states, never nags".
 *
 * There is no separate message-inbox table, so nothing here is invented. Instead
 * we DERIVE the org's real "needs-your-action" states from read surfaces that
 * already exist, each behind the same-origin
 * authed proxy (`/api/proxy/*` → backend `/api/v1/*`, httpOnly session cookie):
 *
 *   GET /cost-decisions                      → the latest recorded verification
 *   GET /governance/change-requests?status=  → governed changes awaiting review
 *   GET /ground-truth                        → bands still hatched (n=0 actuals)
 *   GET /admin/webhook-deliveries            → latest delivery status
 *
 * Every field on a derived notification is a verbatim engine/DB value or is
 * withheld. When a read yields nothing, that state is simply absent — never a
 * fabricated row.
 */
import { API_BASE } from "@/lib/api-base";
import { fetchCostDecisions } from "@/lib/api";
import { procLabel, NUM } from "@/lib/verify/tokens";
import { listWebhookDeliveries } from "@/lib/verify/calibration-api";

/** Where a state row navigates in the shell (screen keys). */
export type NotifDest = "records" | "calibration" | "verify";

/** Visual tone → status colour (pass/cond) or neutral info. */
export type NotifTone = "pass" | "cond" | "info";

export interface DerivedNotif {
  id: string;
  tone: NotifTone;
  title: string;
  /** mono sub-line — every value is real or the row is not emitted. */
  meta: string;
  dest: NotifDest;
  /** true → render the HATCHED assumption band (n=0 encoding). */
  hatched?: boolean;
}

export interface NotifState {
  loading: boolean;
  notifs: DerivedNotif[];
  deliveryCount: number | null;
  /** set ONLY when every read failed (e.g. not signed in) — an honest error,
   *  never a fabricated fallback. Partial failures degrade silently to fewer
   *  states rather than a wrong count. */
  error: string | null;
}

// ── raw read shapes (only the fields we consume) ────────────────────────────

interface ChangeRequest {
  id: number;
  asset_type: string | null;
  status: string;
  title: string | null;
  note: string | null;
  proposed_by: number | string | null;
  created_at: string | null;
}

interface GroundTruthList {
  records: unknown[];
  total: number;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail =
      (body && (body.detail || body.message)) || `Request failed (${res.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

/** Compact relative time ("today" / "3d ago") from an ISO timestamp. */
function relTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const days = Math.floor((Date.now() - t) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return new Date(t).toLocaleDateString();
}

/**
 * Fetch the reads in parallel and fold them into the real state list.
 * Each read is isolated: one failing never fakes the others. If every read fails
 * the caller gets `error` (typically "not signed in"), not a hollow empty state.
 */
export async function loadNotifications(): Promise<NotifState> {
  const [decisions, changes, truth, deliveries] = await Promise.allSettled([
    fetchCostDecisions({ limit: 1 }),
    getJson<{ change_requests: ChangeRequest[] }>(
      "/governance/change-requests?status=proposed"
    ),
    getJson<GroundTruthList>("/ground-truth"),
    listWebhookDeliveries(1),
  ]);

  const notifs: DerivedNotif[] = [];

  // 1 ── latest recorded verification (real record, a state — not a nag).
  if (decisions.status === "fulfilled") {
    const d = decisions.value.cost_decisions[0];
    if (d) {
      const route = d.make_now_process ? procLabel(d.make_now_process) : null;
      const cross =
        d.crossover_qty != null ? ` · crossover ${NUM(d.crossover_qty)}` : "";
      notifs.push({
        id: `decision:${d.id}`,
        tone: "pass",
        title: `Verification recorded — ${d.label || d.filename}`,
        meta: `${route ? `make-now ${route}` : "recorded"}${cross} · ${relTime(d.created_at)}`,
        dest: "records",
      });
    }
  }

  // 2 ── governed changes awaiting review (genuinely needs a reviewer).
  if (changes.status === "fulfilled") {
    const proposed = (changes.value.change_requests ?? []).filter(
      (c) => c.status === "proposed"
    );
    for (const c of proposed.slice(0, 4)) {
      const who = c.proposed_by != null ? ` · proposed by ${c.proposed_by}` : "";
      const what = c.title || c.asset_type || "rate-library change";
      notifs.push({
        id: `change:${c.id}`,
        tone: "cond",
        title: "Governed change awaiting review",
        meta: `${what}${who} · ${relTime(c.created_at)}`,
        dest: "calibration",
      });
    }
  }

  // 3 ── bands still hatched: zero ground-truth actuals → assumption bands.
  if (truth.status === "fulfilled") {
    if ((truth.value.total ?? 0) === 0) {
      notifs.push({
        id: "hatched:n0",
        tone: "cond",
        title: "Bands still hatched — n=0",
        meta: "send actuals back to flip them solid",
        dest: "calibration",
        hatched: true,
      });
    }
  }

  // 4 ── latest webhook delivery state (real durable delivery row).
  let deliveryCount: number | null = null;
  if (deliveries.status === "fulfilled") {
    deliveryCount = deliveries.value.deliveries.length;
    const d = deliveries.value.deliveries[0];
    if (d) {
      const tone: NotifTone =
        d.status === "delivered" ? "pass" : d.status === "failed" ? "cond" : "info";
      const code = d.response_code != null ? ` · HTTP ${d.response_code}` : "";
      notifs.push({
        id: `webhook:${d.id}`,
        tone,
        title: `Webhook ${d.status} — ${d.event_type}`,
        meta: `${d.attempts} attempt${d.attempts === 1 ? "" : "s"}${code} · ${relTime(d.last_attempt_at ?? d.created_at)}`,
        dest: "calibration",
      });
    }
  }

  const allFailed =
    decisions.status === "rejected" &&
    changes.status === "rejected" &&
    truth.status === "rejected" &&
    deliveries.status === "rejected";

  const firstError =
    decisions.status === "rejected"
      ? decisions.reason
      : changes.status === "rejected"
        ? changes.reason
        : truth.status === "rejected"
          ? truth.reason
          : deliveries.status === "rejected"
            ? deliveries.reason
          : null;

  return {
    loading: false,
    notifs,
    deliveryCount,
    error: allFailed
      ? firstError instanceof Error
        ? firstError.message
        : "could not load"
      : null,
  };
}
