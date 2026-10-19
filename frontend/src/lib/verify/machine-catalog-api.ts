/**
 * Catalog-template client for the Add-machine modal — GET
 * /api/v1/machine-inventory/catalog. The backend returns static MachineProfile
 * reference options as EDITABLE prefill payloads (`provenance: "catalog_template"`):
 * a seed the org edits to its machine's real specs before saving. Same-origin
 * through the Next authed proxy.
 *
 * Honesty: a catalog template is NOT a declaration — it is a starting point. Once
 * saved (POST), the machine is ● USER. This client only READS templates; it never
 * presents a template's numbers as a measured or owned capability. New lib file so
 * the frozen machine-api.ts is not edited.
 */
import { API_BASE } from "@/lib/api-base";
import type { FieldProvenance, MachineInput } from "@/lib/verify/machine-api";

/** What the maker publishes for a catalog machine. A null weight means the
 *  maker publishes none (most printers); the note says so. */
export interface MakerSpecView {
  source_url: string;
  max_workpiece_kg: number | null;
  max_workpiece_kg_note: string;
  materials_basis: "maker_spec" | "maker_described" | null;
  materials_url: string;
  materials_note: string;
  checked: string;
}

/** One catalog reference machine as an editable prefill payload. Its
 *  `capabilities.maker_spec` rides along on save so the server can keep the
 *  labels while the maker's values stay unedited. */
export interface MachineCatalogTemplate extends MachineInput {
  provenance: "catalog_template";
  field_provenance?: Partial<Record<"max_workpiece_kg" | "materials", FieldProvenance>>;
  spec?: MakerSpecView | null;
}

const CATALOG_URL = `${API_BASE}/machine-inventory/catalog`;

/** Every static MachineProfile as an editable prefill payload. Empty on any
 *  non-OK response — the modal simply falls back to a blank declaration. */
export async function fetchMachineCatalog(): Promise<MachineCatalogTemplate[]> {
  const res = await fetch(CATALOG_URL, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail =
      (body && (body.detail || body.message)) ||
      `Could not load catalog (${res.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const body = await res.json().catch(() => null);
  return Array.isArray(body?.catalog) ? (body.catalog as MachineCatalogTemplate[]) : [];
}
