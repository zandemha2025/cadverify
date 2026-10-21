/**
 * "How sure is this?": one line under each view's answer saying what it rests
 * on (measured from your file, set by you or your shop, or a typical default),
 * with the detail one click away. Read from the same engine results the view
 * shows; nothing here is estimated. Pure: only relative `.ts` imports, so it
 * runs under `node --test` (sure.test.ts).
 */
import type { CostEstimate, CostReport, ValidationResult } from "@/lib/api";
import type { OwnedMachine } from "@/lib/verify/machine-api";
import type { ServiceEnvironment } from "@/lib/verify/part-context";
import { MATERIAL_CLASS_LABEL, cheapestAt, costLines, dimsText, money, plural, srcOf, trimNum, type Method } from "./model.ts";

export type SureKind = "file" | "yours" | "typ";
export type SureLens = "make" | "cost" | "use" | "shop" | "decide";

export interface SureItem {
  kind: SureKind;
  /** What it is ("Shape", "Range"). */
  k: string;
  /** What it rests on, in words. */
  v: string;
}

export interface Sure {
  /** The short line shown by default. */
  line: string;
  /** The detail, one click away. */
  items: SureItem[];
  /** What would make it surer, with where to do it. */
  next: { text: string; to: "rates" | "actuals" | "machines" | "conditions" } | null;
}

export interface SureInput {
  validation: ValidationResult | null;
  cost: CostReport | null;
  machines: OwnedMachine[];
  /** The conditions the shown answers were computed under. */
  env: ServiceEnvironment | null;
  methods: Method[];
  q: number;
}

function hasEnv(env: ServiceEnvironment | null | undefined): boolean {
  if (!env) return false;
  return !!(env.sour_service || env.corrosive || env.medium || env.max_temp_c != null || env.min_temp_c != null || env.pressure_bar != null || env.standard);
}

function shapeItem(i: SureInput): SureItem | null {
  const g = i.validation?.geometry;
  const bbox = g?.bounding_box_mm ?? i.cost?.geometry.bbox_mm ?? null;
  const dims = dimsText(bbox);
  if (!dims) return null;
  const faces = g?.faces ?? i.cost?.geometry.face_count ?? null;
  const tight = g?.is_watertight ?? i.cost?.geometry.watertight ?? null;
  return { kind: "file", k: "Shape", v: [`measured from your file: ${dims}`, faces != null ? `${faces.toLocaleString("en-US")} faces` : null, tight == null ? null : tight ? "closed solid" : "not a closed solid"].filter(Boolean).join(", ") };
}

function materialItem(i: SureInput): SureItem {
  const cls = i.cost?.material_class ?? null;
  if (!cls || cls === "polymer") return { kind: "typ", k: "Material", v: `${MATERIAL_CLASS_LABEL.polymer.toLowerCase()}, the default until you choose another in Conditions` };
  return { kind: "yours", k: "Material", v: `${(MATERIAL_CLASS_LABEL[cls] ?? cls).toLowerCase()}, chosen for this check` };
}

function conditionsItem(i: SureInput): SureItem {
  return hasEnv(i.env) ? { kind: "yours", k: "Conditions", v: "the service conditions you set" } : { kind: "typ", k: "Conditions", v: "none set: checked at room temperature, no chemicals or pressure" };
}

/** The price shown at q: the cheapest priced process. */
function headline(i: SureInput): { m: Method; e: CostEstimate } | null {
  const m = cheapestAt(i.methods, i.q);
  const e = m?.prices.get(i.q) ?? null;
  return m && e ? { m, e } : null;
}

function costItems(i: SureInput): { items: SureItem[]; line: string | null; typicalTop: boolean; validated: boolean } {
  const h = headline(i);
  if (!h) return { items: [], line: null, typicalTop: false, validated: false };
  const { e } = h;
  const items: SureItem[] = [];
  const c = e.confidence;
  const band = c ? c.half_width_pct : e.est_error_band_pct;
  const validated = !!c?.validated;
  items.push(
    validated
      ? { kind: "yours", k: "Range", v: `${money(c!.low_usd)}–${money(c!.high_usd)} (±${trimNum(band, 0)}%), checked against ${plural(c!.n_samples, "of your real job", "of your real jobs")}` }
      : { kind: "typ", k: "Range", v: `${c ? `${money(c.low_usd)}–${money(c.high_usd)} ` : ""}(±${trimNum(band, 0)}%): a stated assumption band, not yet checked against real jobs` },
  );
  const n = { file: 0, yours: 0, typ: 0 };
  for (const d of e.drivers) n[srcOf(d.provenance).kind] += 1;
  const total = e.drivers.length;
  if (total) {
    items.push({ kind: "file", k: "From your file", v: n.file ? `${plural(n.file, "cost input")} (volume, size, faces)` : "no cost input marked as measured" });
    items.push({ kind: "yours", k: "From your shop or you", v: n.yours ? `${plural(n.yours, "cost input")} (your rates or machines)` : "none yet" });
    items.push({ kind: "typ", k: "Typical defaults", v: plural(n.typ, "cost input") });
  }
  const top = costLines(e)[0];
  const typicalTop = !!top && top.src.kind === "typ" && e.unit_cost_usd > 0;
  if (top && e.unit_cost_usd > 0) {
    const share = Math.round((top.value / e.unit_cost_usd) * 100);
    const kind = top.src.kind;
    items.push({ kind, k: "Biggest line", v: `${top.name}, ${share}% of the price: ${kind === "typ" ? "a typical value" : kind === "file" ? "measured from your file" : "your value"}` });
  }
  const grounded = n.file + n.yours;
  const line = `±${trimNum(band, 0)}% · ${grounded} of ${total} inputs from your file or shop · ${validated ? "checked against real jobs" : "not yet checked against real jobs"}`;
  return { items, line, typicalTop, validated };
}

/** What a view's answer rests on, for its "How sure is this?" line; null when there's nothing to say yet. */
export function sureOf(lens: SureLens, i: SureInput): Sure | null {
  const shape = shapeItem(i);
  if (lens === "make") {
    if (!i.validation && !i.cost) return null;
    const pack = i.validation?.rule_pack;
    const items: SureItem[] = [];
    if (shape) items.push(shape);
    items.push(pack ? { kind: "yours", k: "Design rules", v: `rule pack ${pack.name} ${pack.version}` } : { kind: "typ", k: "Design rules", v: "typical limits for each process, cited on each problem" });
    items.push(materialItem(i));
    items.push(conditionsItem(i));
    const line = `Shape from your file · ${pack ? "your rule pack" : "typical design rules"} · ${items.find((x) => x.k === "Material")!.kind === "typ" ? "default material" : "your material"}`;
    return { line, items, next: hasEnv(i.env) ? null : { text: "Set where it’s used", to: "conditions" } };
  }
  if (lens === "cost" || lens === "decide") {
    const c = costItems(i);
    if (!c.line) return null;
    const items = shape ? [...c.items, shape] : c.items;
    if (lens === "decide") items.push(machinesItem(i));
    const next = c.typicalTop ? { text: "Add your rates", to: "rates" as const } : !c.validated ? { text: "Log real job costs", to: "actuals" as const } : null;
    return { line: c.line, items, next };
  }
  if (lens === "use") {
    const items = [conditionsItem(i), materialItem(i)];
    return { line: hasEnv(i.env) ? "Your conditions · ruled-out materials cite their standard" : "No conditions set · nothing ruled out yet", items, next: null };
  }
  // In-house
  const m = machinesItem(i);
  const items = shape ? [shape, m] : [m];
  return { line: i.machines.length ? `${plural(i.machines.length, "machine")} as you entered them · part size from your file` : "No machines yet · nothing checked in-house", items, next: i.machines.length ? null : { text: "Add a machine", to: "machines" } };
}

function machinesItem(i: SureInput): SureItem {
  return i.machines.length
    ? { kind: "yours", k: "Your machines", v: `${plural(i.machines.length, "machine")}: work area, weight limit and materials as you entered them` }
    : { kind: "typ", k: "Your machines", v: "none entered, so nothing is checked in-house" };
}
