/**
 * BOM / assembly-hierarchy client + pure derivations (customer-context Slice 3).
 *
 * A part's environment and total come from the customer's OWN structure: a door
 * handle (part) belongs to a door assembly (environment) belongs to a vehicle
 * (total). The backend persists that real multi-level tree (`bom_edges`) and rolls
 * a part's annual volume up it. This module reads the ancestry back so the Part
 * page can show the honest breadcrumb —
 *
 *   In context: Bolt → NUT-BOLT-ASSEMBLY → L-BRACKET-ASSEMBLY → as1
 *
 * — and label the derived annual volume with its BASIS: `BOM ROLLUP` (rolled up
 * from the real tree) vs `DECLARED` (the flat user-declared number) vs `—` (none).
 *
 * Honesty: a breadcrumb is shown ONLY when a real tree exists (`has_tree`). When
 * absent, the caller keeps the existing declared/`no home` state — we NEVER invent
 * a parent chain or a volume. Same-origin through the authed proxy (httpOnly
 * session cookie), exactly like the sibling read clients. The proxy base is
 * imported LAZILY (inside the fetch path, mirroring assembly.ts) so the pure,
 * unit-tested derivations below carry no runtime module-alias import and strip
 * cleanly under the repo's `node --test` TS runner.
 */

/** Which input fed a part's annual volume — surfaced verbatim from the backend. */
export type AnnualVolumeBasis = "bom_rollup" | "declared" | "default";

/** The ancestry response shape (bom_service.get_ancestry). `has_tree` is false and
 *  the chains empty when no real tree exists for this part — the honest absent
 *  state, never an error. */
export interface BomAncestry {
  assembly_key: string;
  child_ref: string;
  has_tree: boolean;
  /** [child, parent, …, root] — the one canonical chain (empty when no tree). */
  ancestry: string[];
  /** every distinct root-path when the part is shared (a real DAG); usually one. */
  ancestry_paths: string[][];
  /** units of this part per ONE root/vehicle, or null when there is no rollup. */
  rolled_up_multiplier: number | null;
  roots: string[];
}

export interface BomBreadcrumbView {
  /** true only when a real tree grounds this part — gate for showing the crumb. */
  present: boolean;
  /** child → root, e.g. ["Bolt","NUT-BOLT-ASSEMBLY","L-BRACKET-ASSEMBLY","as1"]. */
  chain: string[];
  /** units of this part per one root/vehicle (the rolled-up multiplier), or null. */
  perVehicle: number | null;
  /** true when the part is shared across >1 sub-assembly (multiple root-paths). */
  shared: boolean;
}

/** Derive the breadcrumb from an ancestry response — PURE. `present` is false
 *  unless a real chain exists, so the caller never renders an invented lineage. */
export function bomBreadcrumbView(a: BomAncestry | null): BomBreadcrumbView {
  const chain = a?.ancestry ?? [];
  const present = Boolean(a?.has_tree && chain.length > 0);
  return {
    present,
    chain: present ? chain : [],
    perVehicle: present ? a?.rolled_up_multiplier ?? null : null,
    shared: (a?.ancestry_paths?.length ?? 0) > 1,
  };
}

/** The chip label + tone for an annual-volume basis. `bom_rollup` is the grounded
 *  win (the real tree fed it); `declared` is the flat user number; `default` means
 *  no volume — never a fabricated figure. Returns null for `default` so the caller
 *  can omit the chip entirely. */
export function basisChip(
  basis: AnnualVolumeBasis | null | undefined
): { text: string; tone: "rollup" | "declared" } | null {
  if (basis === "bom_rollup") return { text: "BOM ROLLUP", tone: "rollup" };
  if (basis === "declared") return { text: "DECLARED", tone: "declared" };
  return null;
}

/** Fetch a part's ancestry through the authed proxy. A missing tree is NOT an
 *  error — it returns `has_tree: false` (the backend never 500s on an absent
 *  tree), which `bomBreadcrumbView` renders as "not present". Returns null on a
 *  genuine failure so the caller silently keeps the existing state. */
export async function fetchBomAncestry(
  assemblyKey: string,
  childRef: string
): Promise<BomAncestry | null> {
  if (!assemblyKey || !childRef) return null;
  try {
    const { API_BASE } = await import("@/lib/api-base");
    const res = await fetch(
      `${API_BASE}/bom/${encodeURIComponent(assemblyKey)}/ancestry?child_ref=${encodeURIComponent(
        childRef
      )}`,
      { credentials: "include" }
    );
    if (!res.ok) return null;
    return (await res.json()) as BomAncestry;
  } catch {
    return null;
  }
}
