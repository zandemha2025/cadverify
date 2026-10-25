/**
 * The Bodies sheet's view model: a file of several bodies, body by body.
 *
 * Reads the check's `part_type` (what the file holds) and, once it has run, the
 * body check (POST /parts/{hash}/bodies). Every figure is the engine's: a body
 * not checked yet shows no price, a weldment shows its members' material and
 * says what isn't priced, never a made-up weld cost.
 *
 * Pure: relative `.ts` imports only, so it runs under `node --test`.
 */
import type { BodiesCheck, BodyDesignCheck, BodyInfo, PartType } from "../../../lib/verify/bodies.ts";
import { methodName, money, plural, trimNum } from "./model.ts";

export const KIND_TITLE: Record<string, string> = {
  separate_bodies: "Separate bodies",
  weldment: "Weldment",
  assembly: "Assembly",
  bodies: "Bodies",
};

export interface Chip {
  cls: "c-ok" | "c-warn" | "c-bad" | "c-unk";
  label: string;
}

export interface BodyRow {
  id: number;
  title: string;
  sub: string;
  chip: Chip;
  price: string;
  priceNote: string;
  copyOf: number | null;
}

export function designOf(check: BodiesCheck | null | undefined, body: BodyInfo): BodyDesignCheck | null {
  return check?.designs.find((d) => d.bodies.includes(body.id)) ?? null;
}

export function bodyTitle(b: BodyInfo): string {
  return b.name ? `${b.name}` : b.label;
}

function volumeText(mm3: number): string {
  return mm3 >= 1000 ? `${trimNum(mm3 / 1000, 1)} cm³` : `${Math.round(mm3)} mm³`;
}

export function bodySub(b: BodyInfo): string {
  const bits = [b.shape];
  if (b.closed && b.volume_mm3 > 0) bits.push(volumeText(b.volume_mm3));
  if (!b.closed) bits.push("not a closed solid");
  if (b.voids) bits.push(plural(b.voids, "sealed void"));
  return bits.join(" · ");
}

export function chipOf(d: BodyDesignCheck | null, weldment: boolean, loaded: boolean): Chip {
  if (!loaded) return { cls: "c-unk", label: "Not checked yet" };
  if (!d) return { cls: "c-unk", label: "Not checked" };
  if (d.status === "open") return { cls: "c-bad", label: "Not closed" };
  if (d.status === "not_checked") return { cls: "c-unk", label: "Not checked" };
  if (d.status === "error") return { cls: "c-bad", label: "Didn’t check" };
  if (d.cots?.is_cots) return { cls: "c-unk", label: "Buy" };
  if (weldment && d.stock_material) return { cls: "c-ok", label: "Cut from stock" };
  if (d.status === "geometry_invalid") return { cls: "c-bad", label: "Can’t as drawn" };
  const v = d.verdict;
  if (v === "pass") return { cls: "c-ok", label: "Can make" };
  if (v === "fail" && !d.processes?.can_make) return { cls: "c-bad", label: "Can’t as drawn" };
  return { cls: "c-warn", label: "Check first" };
}

/** The figure on a body's row at file quantity q: a price each, a buy price, or the member's material. */
export function priceOf(d: BodyDesignCheck | null, q: number, weldment: boolean): { value: string; note: string } {
  if (!d) return { value: "—", note: "" };
  if (d.cots?.is_cots && d.cots.buy_price_usd != null) return { value: money(d.cots.buy_price_usd), note: "catalog estimate, each" };
  if (weldment) {
    const cut = d.cut_blank?.[String(q)];
    if (cut) return { value: money(cut.unit_cost_usd), note: "laser-cut blank, each" };
    if (d.stock_material) return { value: money(d.stock_material.usd), note: `material, ${trimNum(d.stock_material.mass_kg, 2)} kg ${d.stock_material.material.toLowerCase()}` };
    return { value: "—", note: "not stock: no member price" };
  }
  const p = d.by_quantity?.[String(q)];
  if (!p || p.unit_cost_usd == null) return { value: "—", note: d.status === "ok" ? "no makeable route priced" : d.reason ?? "" };
  return { value: money(p.unit_cost_usd), note: `${methodName(p.process)}${p.material ? ` · ${p.material}` : ""}` };
}

export function bodyRows(pt: PartType, check: BodiesCheck | null, q: number): BodyRow[] {
  const weldment = pt.kind === "weldment";
  return (pt.bodies ?? []).map((b) => {
    const d = designOf(check, b);
    const price = priceOf(d, q, weldment);
    return {
      id: b.id,
      title: bodyTitle(b),
      sub: bodySub(b),
      chip: chipOf(d, weldment, !!check),
      price: price.value,
      priceNote: price.note,
      copyOf: b.same_as,
    };
  });
}

/** "4 bodies · 2 shapes" and the like, for the sheet's meta line. */
export function metaLine(pt: PartType, check: BodiesCheck | null): string {
  if (pt.provisional) return "Several solids · read from the file’s product tree when checked";
  const n = pt.body_count;
  const bits = [plural(n, "body", "bodies")];
  if (pt.designs && pt.designs < n) bits.push(plural(pt.designs, "shape"));
  if (pt.source === "step_product_tree") bits.push("from the file's product tree");
  if (check?.checked) bits.push(`${check.checked.bodies} of ${check.checked.of} checked`);
  return bits.join(" · ");
}

/** The file's total at quantity q, or why there isn't one. */
export function totalOf(check: BodiesCheck | null, q: number): { value: string; note: string } {
  if (!check) return { value: "—", note: "check the bodies to see it" };
  if (check.weldment) {
    const w = check.weldment;
    return { value: money(w.material_usd), note: `members’ material${w.material_complete ? "" : ", stock members only"}; welding not priced` };
  }
  const t = check.total;
  const v = t?.per_file_usd?.[String(q)];
  if (v == null) return { value: "—", note: t && !t.complete ? "not every body has a price" : "no total" };
  return { value: money(v), note: "sum of the bodies, each made as its own part" };
}

export function weldmentLines(check: BodiesCheck | null, pt: PartType): { k: string; v: string; note?: string }[] {
  const j = pt.joints;
  const w = check?.weldment;
  const out: { k: string; v: string; note?: string }[] = [];
  if (j) out.push({ k: "Joints", v: plural(j.count, "joint"), note: "where members touch" });
  if (j?.weld_length_mm_estimate != null) out.push({ k: "Weld length", v: `≈ ${Math.round(j.weld_length_mm_estimate).toLocaleString("en-US")} mm`, note: "an estimate: each contact welded all round" });
  if (w?.material_kg != null) out.push({ k: "Members’ weight", v: `${trimNum(w.material_kg, 2)} kg`, note: check?.material_class ? `in ${check.material_class === "steel" ? "steel" : check.material_class}` : undefined });
  if (w?.material_usd != null) out.push({ k: "Members’ material", v: money(w.material_usd), note: "list price per kg, net weight" });
  if (w?.cut_blanks) out.push({ k: "Cut plates", v: plural(w.cut_blanks, "blank"), note: "priced on the sheet-metal route" });
  if (w) out.push({ k: "Not priced", v: w.not_priced.join(", ") });
  return out;
}

/** The quantities the body check priced (per file), else the part's own. */
export function quantitiesOf(check: BodiesCheck | null, fallback: number[]): number[] {
  return check?.quantities?.length ? check.quantities : fallback;
}

export function materialNote(check: BodiesCheck | null): string | null {
  if (!check?.material_class) return null;
  if (check.material_basis === "weldment_default") return "Priced in steel: welded plate and tube is metal, and no material was given. Change it with the part’s material.";
  return null;
}
