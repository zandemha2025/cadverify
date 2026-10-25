/**
 * Pure helpers for Changes to review (board S3): what a rate card draft changes
 * against the card in effect, the review pipeline, and who's asking.
 */
import type { Assumption } from "./shop-api";
import { CARD_ROWS } from "./rates-derive.ts";
import { procName } from "./shop-derive.ts";

export type DiffRow = { key: string; name: string; from: string; to: string };

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * The card values a draft changes. `base` is the governed card in effect, or
 * (for the default v0) the defaults a saved check recorded; a value the base
 * doesn't state isn't compared, so nothing is guessed.
 */
export function diffCard(
  draft: unknown,
  base: { payload?: unknown; assumptions?: Assumption[] | null }
): DiffRow[] {
  const to = (draft as { global?: Record<string, unknown> } | null)?.global ?? {};
  const fromPayload = (base.payload as { global?: Record<string, unknown> } | null)?.global ?? null;
  const fromV0 = new Map((base.assumptions ?? []).filter((a) => a.provenance === "DEFAULT").map((a) => [a.name, a.value]));
  const out: DiffRow[] = [];
  for (const r of CARD_ROWS) {
    const b = num(fromPayload ? fromPayload[r.key] : fromV0.get(r.key));
    const t = num(to[r.key]);
    if (b == null || t == null || Math.abs(b - t) < 1e-9) continue;
    out.push({ key: r.key, name: r.name, from: r.fmt(b), to: r.fmt(t) });
  }
  const mp = (p: unknown) => Object.keys(((p as { material_prices?: object } | null)?.material_prices as object) ?? {}).length;
  if (base.payload && mp(base.payload) !== mp(draft)) {
    out.push({ key: "material_prices", name: "Material price overrides", from: String(mp(base.payload)), to: String(mp(draft)) });
  }
  return out;
}

const money2 = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const PROC_FIELD: Record<string, [string, (v: number) => string]> = {
  machine_rate: ["machine rate", (v) => `${money2(v)}/h`],
  setup_hr: ["setup", (v) => `${v} h`],
  nre_hr: ["programming", (v) => `${v} h`],
  fai_hr: ["first article", (v) => `${v} h`],
  inspect_hr_part: ["inspection a part", (v) => `${v} h`],
  post_hr_part: ["hand work and handling a part", (v) => `${v} h`],
  min_charge: ["order minimum", (v) => money2(v)],
};

/**
 * The rows of a version's server-side `changes` (every value it sets differently
 * from the card in effect): labor, overhead and margin, each machine rate and
 * each material price, in words (ce-13).
 */
export function changeRows(changes: { path: string; from: unknown; to: unknown }[] | null | undefined): DiffRow[] {
  const out: DiffRow[] = [];
  for (const c of changes ?? []) {
    const [head, a, b] = c.path.split(".");
    const f = num(c.from);
    const t = num(c.to);
    if (head === "global") {
      const r = CARD_ROWS.find((x) => x.key === a);
      const fmt = r?.fmt ?? ((v: number) => String(v));
      if (t == null) continue;
      out.push({ key: c.path, name: r?.name ?? a.replace(/_/g, " "), from: f == null ? "—" : fmt(f), to: fmt(t) });
    } else if (head === "process" && a && b) {
      const [word, fmt] = PROC_FIELD[b] ?? [b.replace(/_/g, " "), (v: number) => String(v)];
      if (t == null) continue;
      out.push({ key: c.path, name: `${procName(a)} ${word}`, from: f == null ? "—" : fmt(f), to: fmt(t) });
    } else if (head === "material_prices" && a) {
      const name = c.path.slice("material_prices.".length);
      out.push({ key: c.path, name: `${name.replace(/^@/, "")} price`, from: f == null ? "typical" : `${money2(f)}/kg`, to: t == null ? "typical" : `${money2(t)}/kg` });
    }
  }
  return out;
}

/**
 * Who can approve a waiting change (ce-13): any admin, except the person who
 * proposed it when the organization has another admin. A sole admin's approval
 * of their own change is recorded as self-approved.
 */
export function approvalRule(o: { mine: boolean; admin: boolean; admins: number | null }): "approve" | "self" | "other-admin" | "not-admin" {
  if (!o.admin) return "not-admin";
  if (!o.mine) return "approve";
  return o.admins != null && o.admins > 1 ? "other-admin" : "self";
}

export type Stage = { label: string; state: "done" | "cur" | "todo" | "bad" };

export function pipeline(status: string, version: number | null): Stage[] {
  const v = version != null ? ` v${version}` : "";
  if (status === "approved")
    return [
      { label: "Proposed", state: "done" },
      { label: "Reviewed", state: "done" },
      { label: "Approved", state: "done" },
      { label: `Published${v}`, state: "done" },
    ];
  if (status === "rejected")
    return [
      { label: "Proposed", state: "done" },
      { label: "Rejected", state: "bad" },
    ];
  return [
    { label: "Proposed", state: "done" },
    { label: "In review", state: "cur" },
    { label: "Approve", state: "todo" },
    { label: `Publish${v}`, state: "todo" },
  ];
}

export const ASSET_NAMES: Record<string, string> = { rate_card: "Rate card", shop_profile: "Supplier rate profile", material_catalog: "Material catalog" };

/** "you", the member's email, or "a former member". */
export function personName(id: number | null, me: number | null, emails: Map<number, string>): string {
  if (id == null) return "unknown";
  if (me != null && id === me) return "you";
  return emails.get(id) ?? "a former member";
}

/** Two letters for the avatar circle. */
export function initials(name: string): string {
  if (name === "you") return "You";
  if (!name.includes("@")) return "?";
  const local = name.split("@")[0] ?? "";
  const parts = local.split(/[._-]+/).filter(Boolean);
  const two = parts.length >= 2 ? parts[0][0] + parts[1][0] : local.slice(0, 2);
  return two.toUpperCase() || "?";
}

/** The proposer's note and the reviewer's, which the API appends on a new line. */
export function noteLines(note: string | null | undefined): string[] {
  return (note ?? "").split("\n").map((s) => s.trim()).filter(Boolean);
}
