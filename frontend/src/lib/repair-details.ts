import type { RepairDetails } from "@/lib/api";

/**
 * Why a repair was refused. The API explains every refusal in `reason`; older
 * responses only carried the raw `error`, which is empty on a timeout.
 */
export function repairFailureReason(details: RepairDetails): string | null {
  for (const value of [details.reason, details.error]) {
    const text = value?.trim();
    if (text) return text;
  }
  return null;
}

/** Signed repaired-vs-original volume delta ("+10.4%"), or null when unmeasured. */
export function formatVolumeChange(pct: number | null | undefined): string | null {
  if (pct == null || !Number.isFinite(pct)) return null;
  const rounded = Math.round(pct * 10) / 10;
  if (rounded === 0) return "0.0%";
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(1)}%`;
}
