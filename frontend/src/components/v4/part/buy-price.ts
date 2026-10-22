/**
 * What the organization pays today to buy this part, on its Decision view:
 * read from the part's declared context (``buy_price``: typed here, or from a
 * catalog run's parts list), typed or cleared here, and set against making it
 * on a machine of yours. A price is the person's own figure, never a model's.
 * It moves the part between make and buy and sets the saving; it never changes
 * the engine's figures, so it never marks the record out of date.
 *
 * Pure except ``saveBuyPrice`` (one PUT through the authed proxy).
 */
import { API_BASE } from "../../../lib/api-base.ts";

export interface BuyPrice {
  usd_each: number;
  price_usd?: number;
  per?: number;
  source: "you" | "parts_list";
  run_id?: string | null;
  updated_at?: string | null;
}

function money(n: number): string {
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** "$1,250.00 per 100 · from your parts list" / "$12.40 each · you entered it". */
export function buyPriceText(b: BuyPrice | null | undefined): string | null {
  if (!b || !Number.isFinite(b.usd_each)) return null;
  const per = b.per && b.per > 1 ? b.per : 1;
  const price = b.price_usd ?? b.usd_each * per;
  return `${money(price)}${per > 1 ? ` per ${per.toLocaleString("en-US")} (${money(b.usd_each)} each)` : " each"} · ${b.source === "you" ? "you entered it" : "from your parts list"}`;
}

/**
 * Making it against what you pay: "Making it on your Haas VF-2 at $38.71 each costs 7.5× what you pay" or
 * "saves $11.29 each, $1,354.80 a year at 120 a year". Null without both figures.
 */
export function buyCompareText(b: BuyPrice | null | undefined, make: { usd: number; machine: string } | null, yearly: number | null): string | null {
  if (!b || !make || !Number.isFinite(b.usd_each) || !Number.isFinite(make.usd) || b.usd_each <= 0) return null;
  const diff = b.usd_each - make.usd;
  const lead = `Making it on your ${make.machine} at ${money(make.usd)} each`;
  if (diff >= 0) {
    const year = yearly && yearly > 0 ? `, ${money(diff * yearly)} a year at ${yearly.toLocaleString("en-US")} a year` : "";
    return `${lead} saves ${money(diff)} each against what you pay${year}.`;
  }
  const times = make.usd / b.usd_each;
  return `${lead} costs ${times >= 1.95 ? `${times.toFixed(1)}×` : `${money(-diff)} more than`} what you pay${times >= 1.95 ? "" : " each"}: buying it is cheaper.`;
}

export type MakeOrBuy = "make" | "buy";

/**
 * Making it on your machine against what you pay today, by the run's own rule
 * (catalog_run_service.make_or_buy_pick): make when your machine costs no more
 * than what you pay; buy when what you pay is below the low end of the in-house
 * range; in between, the two can't be told apart and it stays on your machine.
 */
export function makeOrBuy(make: { usd: number; low?: number | null } | null, priceEach: number | null | undefined): MakeOrBuy | null {
  if (!make || priceEach == null || !Number.isFinite(priceEach) || priceEach <= 0 || !Number.isFinite(make.usd)) return null;
  if (make.usd <= priceEach) return "make";
  const low = make.low != null && Number.isFinite(make.low) ? make.low : make.usd;
  return priceEach < low ? "buy" : "make";
}

/** Why ScaleCAD's pick is to keep buying: "What you pay, $33.05 each, is below making it on your Haas VF-2 ($33.92 each, $31.10–$36.80)." */
export function keepBuyingWhy(make: { usd: number; low?: number | null; high?: number | null; machine: string }, priceEach: number): string {
  const range = make.low != null && make.high != null ? `, ${money(make.low)}–${money(make.high)}` : "";
  return `What you pay today, ${money(priceEach)} each, is below making it on your ${make.machine} (${money(make.usd)} each${range}).`;
}

/** Read a typed price: "$1,250", "12.40", with a "per" count. Null for nothing typed; an error string when it can't be read. */
export function readTypedPrice(price: string, per: string): { price_usd: number; per: number } | null | string {
  const p = price.replace(/[$,\s]|usd/gi, "");
  if (!p) return null;
  const v = Number(p);
  if (!Number.isFinite(v) || v <= 0 || v > 10_000_000) return "Type the price in US dollars, like 12.40.";
  const n = per.trim() ? Number(per.replace(/,/g, "")) : 1;
  if (!Number.isInteger(n) || n < 1 || n > 10_000_000) return "“Per” is how many parts the price buys: 1, 100, …";
  return { price_usd: v, per: n };
}

/** Save (or clear, with null) the part's current price. Answers the stored price, or null when cleared. */
export async function saveBuyPrice(meshHash: string, value: { price_usd: number; per: number } | null): Promise<BuyPrice | null> {
  const res = await fetch(`${API_BASE}/part-context/${encodeURIComponent(meshHash)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ buy_price: value }),
  });
  const body = (await res.json().catch(() => null)) as { buy_price?: BuyPrice; detail?: unknown } | null;
  if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : "The price wasn’t saved.");
  return body?.buy_price ?? null;
}
