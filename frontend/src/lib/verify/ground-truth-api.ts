/**
 * Ground-truth client for the Verify surface — the REAL W5 ingest store
 * (backend/src/api/groundtruth.py, mounted at /api/v1/ground-truth). Every call
 * goes SAME-ORIGIN through the Next authed proxy (`/api/proxy/ground-truth`), so
 * the httpOnly session cookie authenticates it and no API key touches the browser.
 *
 * Honesty: a ground-truth record is a REAL historical cost/quote the org sent back
 * (`stand_in: false`) or a synthetic stand-in (`stand_in: true`) that can shape a
 * band's spread but can NEVER flip a band to validated. The Home flywheel counts
 * ONLY real records — n=0 means every band is still a hatched assumption, shown
 * honestly. Absent data -> an empty list, byte-identical to the feature unused.
 */
import { API_BASE } from "@/lib/api-base";

/** One stored ground-truth record (groundtruth_service.row_to_public). */
export interface GroundTruthRecord {
  id: string;
  part_id: string;
  process: string;
  quantity: number;
  actual_unit_cost_usd: number;
  material_class: string;
  shop: string | null;
  region: string | null;
  currency: string;
  source: string;
  stand_in: boolean;
  part_path: string | null;
  notes: string;
  created_at: string | null;
}

export interface GroundTruthPage {
  records: GroundTruthRecord[];
  total: number;
}

const BASE = `${API_BASE}/ground-truth`;

async function toError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null);
  const detail =
    (body && (body.detail || body.message)) || `Request failed (${res.status})`;
  return new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
}

/** The caller org's ground-truth records (newest first). */
export async function listGroundTruth(): Promise<GroundTruthPage> {
  const res = await fetch(BASE, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** Count of REAL (non-stand-in) records — the only ones that can validate a band. */
export function realActualCount(records: GroundTruthRecord[]): number {
  return records.reduce((n, r) => (r.stand_in ? n : n + 1), 0);
}
