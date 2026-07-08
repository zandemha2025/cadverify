/**
 * Machine-inventory client for the Verify surface — the REAL org-owned machine
 * registry (backend/src/api/machine_inventory.py, mounted at
 * /api/v1/machine-inventory). Every call goes SAME-ORIGIN through the Next authed
 * proxy (`/api/proxy/machine-inventory/*`), so the httpOnly session cookie
 * authenticates it and no API key ever touches the browser.
 *
 * Honesty: every capability is a USER declaration (`provenance: "user"`), never a
 * measurement of the machine. Absent inventory → an empty list, byte-identical to
 * the feature unused.
 */
import { API_BASE } from "@/lib/api-base";

/** One owned machine as the backend serializes it (machine_to_public). */
export interface OwnedMachine {
  id: string;
  name: string | null;
  process: string;
  count: number | null;
  max_workpiece_kg: number | null;
  hourly_rate_usd: number | null;
  capital_frac: number | null;
  capabilities: Record<string, unknown>;
  materials: string[] | null;
  material_thickness_map: Record<string, unknown> | null;
  notes: string | null;
  provenance: "user";
  created_at: string | null;
  updated_at: string | null;
}

export interface MachineListPage {
  machines: OwnedMachine[];
  next_cursor: string | null;
}

/** Body for POST/PATCH — only `process` is required by the backend on create. */
export interface MachineInput {
  name?: string | null;
  process: string;
  count?: number | null;
  max_workpiece_kg?: number | null;
  hourly_rate_usd?: number | null;
  capital_frac?: number | null;
  capabilities?: Record<string, unknown> | null;
  materials?: string[] | null;
  material_thickness_map?: Record<string, unknown> | null;
  notes?: string | null;
}

export interface MachineImportSummary {
  imported: number;
  skipped: number;
  total: number;
  errors: { line: number; reason: string }[];
}

const BASE = `${API_BASE}/machine-inventory`;

/** Relay the backend's structured error `detail` as the thrown Error message. */
async function toError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null);
  const detail =
    (body && (body.detail || body.message)) || `Request failed (${res.status})`;
  return new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
}

export async function listMachines(): Promise<MachineListPage> {
  const res = await fetch(BASE, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function getMachine(id: string): Promise<OwnedMachine> {
  const res = await fetch(`${BASE}/${encodeURIComponent(id)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function createMachine(input: MachineInput): Promise<OwnedMachine> {
  const res = await fetch(BASE, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function updateMachine(
  id: string,
  patch: Partial<MachineInput>
): Promise<OwnedMachine> {
  const res = await fetch(`${BASE}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function deleteMachine(id: string): Promise<void> {
  const res = await fetch(`${BASE}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw await toError(res);
}

/** Bulk CSV import. Partial success is honest: 200 with per-line errors. */
export async function importMachinesCsv(
  file: File
): Promise<MachineImportSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/import`, { method: "POST", body: form });
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** The exact CSV header a customer produces for a machine-inventory import. */
export async function machineImportTemplate(): Promise<string> {
  const res = await fetch(`${BASE}/import/template`, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.text();
}

/** Engine process ids the org OWNS in-house — fed to /validate/cost so those
 *  routes are costed at the MARGINAL machine rate (owned capital is sunk). */
export function ownedProcessesFrom(machines: OwnedMachine[]): string[] {
  return Array.from(new Set(machines.map((m) => m.process).filter(Boolean)));
}

/** A machine's declared work envelope, read verbatim from its capability bag —
 *  a USER declaration, never a measurement. Returns null when undeclared. */
export function envelopeSummary(m: OwnedMachine): string | null {
  const cap = m.capabilities || {};
  const n = (k: string): number | null => {
    const v = cap[k];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  };
  const swing = n("swing_dia") ?? n("swing_dia_mm");
  const between = n("between_centers");
  if (swing != null) {
    return `Ø${swing} × ${between ?? "?"} mm swing`;
  }
  const x = n("x") ?? n("bed_x") ?? n("platen_x");
  const y = n("y") ?? n("bed_y") ?? n("platen_y");
  const z = n("z") ?? n("daylight");
  if (x != null && y != null) {
    return z != null ? `${x} × ${y} × ${z} mm` : `${x} × ${y} mm`;
  }
  return null;
}
