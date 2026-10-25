/**
 * What Check a part carries from where it was opened. The cost breakdown's
 * "Check another part" passes the material and the order quantity it showed
 * (/app/check?material=aluminum&qty=50): the next check prices in that
 * material, with that quantity as one of its exact priced points, and opens
 * the part on Cost at it. An old issue link (?issue=CODE|…) carries the problem
 * it named: once the same file is checked, the part opens on that problem.
 *
 * Check a part is the one way to add a part; this keeps what the person had
 * set without a second upload screen.
 *
 * Pure (runs under node --test).
 */
import { R } from "../routes.ts";

export const MATERIAL_CLASSES = ["polymer", "aluminum", "steel", "stainless", "titanium"] as const;

const MATERIAL_WORD: Record<string, string> = { polymer: "Plastic", aluminum: "Aluminum", steel: "Steel", stainless: "Stainless steel", titanium: "Titanium" };

const MAX_QTY = 10_000_000;

export interface CheckContext {
  /** The material class to price in, or null (the check asks while it runs). */
  material: string | null;
  /** An order quantity to price exactly and open Cost at, or null. */
  qty: number | null;
  /** An issue code from an old issue link (the part opens on that problem), or null. */
  issue: string | null;
}

function cleanMaterial(v: string | null | undefined): string | null {
  return v && (MATERIAL_CLASSES as readonly string[]).includes(v) ? v : null;
}

function cleanQty(v: string | number | null | undefined): number | null {
  const n = typeof v === "number" ? v : v != null && /^\s*\d+\s*$/.test(v) ? Number(v) : NaN;
  return Number.isInteger(n) && n >= 1 && n <= MAX_QTY ? n : null;
}

function cleanIssue(v: string | null | undefined): string | null {
  const code = (v ?? "").split("|")[0].trim().toUpperCase();
  return /^[A-Z][A-Z0-9_]{1,63}$/.test(code) ? code : null;
}

/** Check a part, carrying the context (only what is valid goes in the address). */
export function checkHref(ctx: Partial<CheckContext>): string {
  const p = new URLSearchParams();
  const m = cleanMaterial(ctx.material);
  const q = cleanQty(ctx.qty);
  const i = cleanIssue(ctx.issue);
  if (m) p.set("material", m);
  if (q) p.set("qty", String(q));
  if (i) p.set("issue", i);
  const s = p.toString();
  return s ? `${R.check}?${s}` : R.check;
}

/** The context in a Check a part address (anything unreadable is dropped). */
export function checkContext(search: string | URLSearchParams): CheckContext {
  const sp = typeof search === "string" ? new URLSearchParams(search) : search;
  return { material: cleanMaterial(sp.get("material")), qty: cleanQty(sp.get("qty")), issue: cleanIssue(sp.get("issue")) };
}

export function hasContext(ctx: CheckContext): boolean {
  return !!(ctx.material || ctx.qty || ctx.issue);
}

/** "Aluminum · 50 parts": what the next check is priced with, for the start screen. */
export function contextLine(ctx: CheckContext): string | null {
  const bits = [ctx.material ? MATERIAL_WORD[ctx.material] : null, ctx.qty ? `${ctx.qty.toLocaleString("en-US")} part${ctx.qty === 1 ? "" : "s"}` : null].filter(Boolean);
  return bits.length ? bits.join(" · ") : null;
}

/**
 * Where the check hands over: the part, on the carried problem (`problemId`,
 * the family the issue code belongs to) or on Cost at the carried quantity.
 */
export function handoverHref(key: string, ctx: CheckContext, problemId: string | null): string {
  if (ctx.issue && problemId) return `${R.part(key)}?problem=${encodeURIComponent(problemId)}`;
  if (ctx.qty) return `${R.part(key)}?lens=cost&qty=${ctx.qty}`;
  return R.part(key);
}
