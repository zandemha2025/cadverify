/**
 * A catalog-board row's part specs and its recorded decision's sign-off, in the
 * words the board shows. Pure (runs under node --test).
 */

export interface RowSpecs {
  summary: string[];
  supplier_must_hold: string[];
  excluded_processes: string[];
}

export interface RowSignoff {
  by: string | null;
  at: string | null;
  note: string | null;
  stale: boolean;
  stale_reason: string | null;
}

export interface RowGov {
  bucket?: string | null;
  specs?: RowSpecs | null;
  outcome?: string | null;
  signoff?: RowSignoff | null;
  record_out_of_date?: boolean;
}

const OUTCOME: Record<string, string> = { inhouse: "Make in-house", outside: "Make outside", acquire: "Acquire capability", redesign: "Redesign" };

/** "Anodize, Type II · Ra 1.6 µm · FAI" — the declared specs, without the inspection default. */
export function rowSpecLine(r: RowGov): string | null {
  const s = r.specs;
  if (!s?.summary?.length) return null;
  const parts = s.summary
    .filter((l) => !/^Inspection: Standard inspection$/.test(l) && !/^Supplier must hold:/.test(l))
    .map((l) => l.replace(/^(Finish|Heat treatment|Inspection): /, ""));
  return parts.length ? parts.join(" · ") : null;
}

/** "Supplier must hold AS9100, ITAR registration" for a part bought outside. */
export function rowMustHold(r: RowGov): string | null {
  const must = r.specs?.supplier_must_hold ?? [];
  if (!must.length || (r.bucket !== "outside" && r.bucket !== "new_machine")) return null;
  return `Supplier must hold ${must.join(", ")}`;
}

/** The recorded outcome and its sign-off, said plainly when it went out of date. */
export function rowSignoffLine(r: RowGov): { text: string; tone: "ok" | "warn" | "unk" } | null {
  if (!r.outcome) return null;
  const what = OUTCOME[r.outcome] ?? r.outcome;
  const so = r.signoff;
  if (so) {
    const day = so.at ? new Date(so.at).toLocaleDateString("en-US", { day: "numeric", month: "short" }) : "";
    if (so.stale) return { text: `${what} · signed off${so.by ? ` by ${so.by}` : ""}, now out of date`, tone: "warn" };
    return { text: `${what} · signed off${so.by ? ` by ${so.by}` : ""}${day ? ` ${day}` : ""}`, tone: "ok" };
  }
  return { text: `${what} · not signed off${r.record_out_of_date ? " · record out of date" : ""}`, tone: r.record_out_of_date ? "warn" : "unk" };
}
