/**
 * What a supplier sees at a share link (backend src/services/supplier_links.py):
 * a part's link (GET /s/cost/{id}) or a package's (GET /s/pkg/{id}). Our cost
 * estimate is in it only when the buyer turned it on ("cost" on a part,
 * "estimate" on each package part). Pure, so every line is tested.
 */
import type { SharedCostLite } from "./shared-derive";

export interface SupplierCad {
  filename: string;
  bytes: number | null;
  url: string;
}

export interface SupplierPart {
  kind: "part";
  name: string;
  filename: string;
  file_type: string;
  label: string | null;
  material: string | null;
  quantity: number | null;
  yearly_volume: number | null;
  bbox_mm: number[] | null;
  specs: string[];
  must_hold: string[];
  note: string | null;
  includes_cost_estimate: boolean;
  cad: SupplierCad | null;
  link_expires_at: string | null;
  /** Only when the buyer included our cost estimate. */
  cost?: SharedCostLite;
}

export interface SupplierPackagePart {
  line: number;
  name: string;
  filename: string;
  part_number: string | null;
  description: string | null;
  material: string | null;
  quantity: number | null;
  yearly_volume: number | null;
  process: string | null;
  size: string | null;
  specs: string[];
  must_hold: string[];
  cad: SupplierCad | null;
  estimate?: { quantity: number; process: string | null; material: string | null; unit_cost_usd: number } | null;
}

export interface SupplierPackage {
  kind: "package";
  title: string;
  supplier: string | null;
  requested_by: { name: string | null; company: string | null; email: string | null };
  reply_by: string | null;
  sent_on: string | null;
  note: string | null;
  includes_cost_estimate: boolean;
  must_hold: string[];
  parts: SupplierPackagePart[];
  zip_url: string;
  link_expires_at: string | null;
}

/** "5 Nov 2026" for an ISO date or instant. */
export function dayOf(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T12:00:00`) : new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** "1.2 MB" for a file size. */
export function bytesText(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** A supplier link's own path through the same-origin proxy (a CAD or ZIP download). */
export function downloadHref(url: string): string {
  return url.startsWith("/s/") ? `/api/public-share${url}` : url;
}

/** The figures at the top of a part's page: quantity, material, size. */
export function partFigs(p: Pick<SupplierPart, "quantity" | "yearly_volume" | "material" | "bbox_mm">, size: string): { k: string; v: string; s: string }[] {
  return [
    { k: "Quantity", v: p.quantity != null ? p.quantity.toLocaleString("en-US") : "Not given", s: p.yearly_volume ? `${p.yearly_volume.toLocaleString("en-US")} a year` : p.quantity != null ? "parts to quote" : "ask the buyer" },
    { k: "Material", v: p.material || "Not given", s: "as the part was checked" },
    { k: "Size", v: size || "Not measured", s: "measured from the CAD" },
  ];
}

/** "Requested by Marcus Bell, Kestrel CM, marcus@kestrel.example". */
export function askerLine(r: SupplierPackage["requested_by"] | null | undefined): string {
  const bits = [r?.name, r?.company, r?.email].filter((x): x is string => !!x && !!x.trim());
  return bits.length ? bits.join(", ") : "Not given";
}

/** One package part's line under its name. */
export function packagePartLine(p: SupplierPackagePart): string {
  return [
    p.part_number ? `Part number ${p.part_number}` : null,
    p.material,
    p.quantity != null ? `quantity ${p.quantity.toLocaleString("en-US")}` : "no quantity given",
    p.yearly_volume ? `${p.yearly_volume.toLocaleString("en-US")} a year` : null,
    p.size,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function usd(n: number): string {
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
