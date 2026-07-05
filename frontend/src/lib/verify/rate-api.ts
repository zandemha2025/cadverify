/**
 * Rate-library client for the shared shell's CALIBRATION SWITCHER — the REAL
 * governed rate-card registry (backend/src/api/rate_library.py, mounted at
 * /api/v1/rate-library). Same-origin through the Next authed proxy, so the
 * httpOnly session cookie authenticates it and no API key touches the browser.
 *
 * Honesty: the switcher NEVER invents a shop name or a rate count (the design's
 * "Midwest Precision CNC · 19 rates" is illustrative mockup data). It reports
 * exactly what the engine reports: how many authored rate-card VERSIONS the org
 * has, and whether the engine is currently costing against a GOVERNED published
 * card or the hardcoded default (RATE_CARD_V0). When the org has none, it says so.
 */
import { API_BASE } from "@/lib/api-base";

const BASE = `${API_BASE}/rate-library`;

/** One authored rate-card version as the backend serializes it. Only the fields
 *  the switcher/Calibration surface actually read are typed; the rest pass
 *  through untyped so a backend addition never silently breaks the client. */
export interface RateCardVersion {
  id: string;
  version?: number | null;
  label?: string | null;
  status?: string | null; // draft | published | archived
  is_published?: boolean | null;
  created_at?: string | null;
  published_at?: string | null;
  [k: string]: unknown;
}

export interface RateVersionsPage {
  versions: RateCardVersion[];
  flag_enabled: boolean;
}

/** What the engine ACTUALLY costs against right now — the switcher's truth. */
export interface EffectiveRateCard {
  flag_enabled: boolean;
  /** true ONLY when a published governed card is in effect; false → default v0. */
  using_governed: boolean;
  source: string; // "governed_rate_card" | "default_rate_card_v0"
  provenance: string;
  validated: boolean;
  payload: unknown | null;
}

async function toError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null);
  const detail =
    (body && (body.detail || body.message)) || `Request failed (${res.status})`;
  return new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
}

/** All authored rate-card versions for the caller's org, newest first. */
export async function listRateVersions(): Promise<RateVersionsPage> {
  const res = await fetch(BASE, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** The card the engine is using right now (governed published card, or v0). */
export async function effectiveRateCard(): Promise<EffectiveRateCard> {
  const res = await fetch(`${BASE}/effective`, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** The switcher chip's honest label, computed from the two real reads. Returns a
 *  loading dash until both resolve; never a hardcoded shop name or rate count. */
export function calibrationLabel(
  eff: EffectiveRateCard | null,
  page: RateVersionsPage | null
): { label: string; grounded: boolean } {
  if (!eff || !page) return { label: "calibration…", grounded: false };
  const published = page.versions.filter(
    (v) => v.status === "published" || v.is_published
  ).length;
  if (eff.using_governed) {
    const n = page.versions.length;
    return {
      label: `Governed rate card · ${published || n} published`,
      grounded: true,
    };
  }
  if (page.versions.length > 0) {
    return {
      label: `Default rate card (v0) · ${page.versions.length} authored, none in effect`,
      grounded: false,
    };
  }
  return { label: "Default rate card (v0) · none authored", grounded: false };
}
