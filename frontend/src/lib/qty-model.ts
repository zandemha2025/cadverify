/**
 * The price at any quantity from the model's own structure (ce-06, ce-15): the
 * same arithmetic as backend/src/costing/quantity_model.py, which tests hold to the
 * engine's own price at every quantity for every process. A record priced before
 * the model was kept has no `qty_model`: then there is no number, only "Price N".
 *
 *   core(q) = once ÷ q + per part + machine + learning × A(q) + Σ lot × max(1, q ÷ parts) ÷ q
 *   unit(q) = max(order minimum ÷ q, core(q)) + Σ declared finishes, heat treatments and inspection
 */

export interface CostQtyModel {
  v: number;
  once_usd: number;
  per_part_usd: number;
  machine_usd: number;
  learning_usd: number;
  learning: { rate: number; first_lot: number; floor: number } | null;
  per_plate: { lot_usd: number; parts: number }[];
  order_min_usd: number;
  specs: ({ min_usd: number; per_part_usd: number } | { once_usd: number; per_part_usd: number })[];
}

export const QTY_MODEL_VERSION = 1;

/** The lot-average learning factor an order of `qty` pays on its touch labor (backend learning.py). */
export function lotAverageFactor(rate: number, firstLot: number, floor: number, qty: number): number {
  if (!rate || rate >= 1 || firstLot <= 0 || qty <= firstLot) return 1;
  const b = Math.log(rate) / Math.log(2);
  const k = 1 + b;
  const fl = floor > 0 ? floor : 0;
  const xFloor = fl > 0 ? firstLot * fl ** (1 / b) : Infinity;
  const upper = Math.min(qty, xFloor);
  const curve = Math.abs(k) < 1e-12 ? firstLot * Math.log(upper / firstLot) : (firstLot * ((upper / firstLot) ** k - 1)) / k;
  const total = firstLot + curve + (qty > xFloor ? fl * (qty - xFloor) : 0);
  return total / qty;
}

export function modelAt(m: CostQtyModel, q: number): number {
  const learn = m.learning;
  const a = learn ? lotAverageFactor(learn.rate, learn.first_lot, learn.floor, q) : 1;
  let core = m.once_usd / q + m.per_part_usd + m.machine_usd + m.learning_usd * a;
  for (const p of m.per_plate ?? []) core += (p.lot_usd * Math.max(1, q / p.parts)) / q;
  let unit = Math.max((m.order_min_usd ?? 0) / q, core);
  for (const s of m.specs ?? []) {
    if ("min_usd" in s) unit += Math.max(s.min_usd, s.per_part_usd * q) / q;
    else unit += (s.once_usd ?? 0) / q + (s.per_part_usd ?? 0);
  }
  return unit;
}

interface WithModel {
  qty_model?: CostQtyModel | null;
  calibration?: { hours_factor?: number | null; cost_factor?: number | null } | null;
}

function isModel(m: unknown): m is CostQtyModel {
  return !!m && typeof m === "object" && (m as CostQtyModel).v === QTY_MODEL_VERSION && Number.isFinite((m as CostQtyModel).once_usd);
}

/** The estimate's own model priced at `q` parts, or null (no model on the record, or no such quantity). */
export function unitCostAt(e: WithModel | null | undefined, q: number): number | null {
  const m = e?.qty_model;
  if (!isModel(m) || !(q >= 1) || !Number.isFinite(q)) return null;
  let unit = modelAt(m, q);
  const h = e?.calibration?.hours_factor;
  const c = e?.calibration?.cost_factor;
  if (typeof h === "number" && h > 0) unit += m.machine_usd * (h - 1);
  if (typeof c === "number" && c > 0) unit *= c;
  return Number.isFinite(unit) ? unit : null;
}

/** What the order pays once at `q`, and what each part adds: the words under a quick price. */
export function onceAndEach(m: CostQtyModel, q: number): { once: number; each: number } {
  let once = m.once_usd;
  for (const s of m.specs ?? []) if (!("min_usd" in s)) once += s.once_usd ?? 0;
  return { once, each: modelAt(m, q) - once / q };
}
