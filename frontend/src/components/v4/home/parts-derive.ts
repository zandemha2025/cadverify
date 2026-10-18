/**
 * Parts list derivations (board O8): each part's machine verdict, the line
 * under its name, its price text, and the filter/search that runs over every
 * loaded part. Pure: reads only fields the catalog and makeability endpoints
 * return; an absent value stays absent ("Not checked", "—"), never invented.
 */
import type { Bucket, FitGap, Makeability, PartRow } from "./model.ts";
import { money, wayName } from "./words.ts";

/** The verdict groups the Machines filter offers. */
export type VerdictKey = "in" | "design" | "machine" | "out" | "outside" | "unknown" | "invalid";

export interface Verdict {
  key: VerdictKey;
  label: string;
  tone: "ok" | "warn" | "bad" | "unk";
  /** the line under the file name: where it's made, or why not */
  where: string;
  stale: boolean;
}

export const VERDICT_FILTERS: { key: VerdictKey; label: string; always?: boolean }[] = [
  { key: "in", label: "On your machines", always: true },
  { key: "design", label: "Design change", always: true },
  { key: "machine", label: "Needs a machine", always: true },
  { key: "out", label: "Ruled out", always: true },
  { key: "outside", label: "Outside only" },
  { key: "unknown", label: "Not checked" },
  { key: "invalid", label: "Can't read" },
];

const BUCKET_KEY: Record<Bucket, VerdictKey> = {
  makeable_in_house: "in",
  makeable_outside: "outside",
  needs_capability: "machine",
  not_makeable: "out",
  unknown: "unknown",
  geometry_invalid: "invalid",
};

export function bucketKey(b: Bucket): VerdictKey {
  return BUCKET_KEY[b];
}

/** The route is blocked by its own geometry: the catalog withholds its price. */
export function needsDesignChange(row: PartRow): boolean {
  return Boolean(row.unit_cost?.withheld) || row.route_blocker_count > 0;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function mm(v: number): string {
  return v >= 10 ? String(Math.round(v)) : String(Math.round(v * 10) / 10);
}

/** One machine gap in plain words: "Needs 269 mm; your machines take 254 mm", or the engine's own text. */
export function gapLine(g: FitGap | null | undefined): string {
  if (!g) return "";
  const need = num(g.need);
  const have = num(g.have);
  if (g.gate === "envelope" && need != null && have != null && /_mm$/.test(g.axis)) {
    return `Needs ${mm(need)} mm; your machines take ${mm(have)} mm`;
  }
  if (g.gate === "material" && typeof g.need === "string") return `Your machines aren't set up for ${g.need}`;
  const human = (g.human || "").split(". ")[0].replace(/\.$/, "");
  return human ? human[0].toUpperCase() + human.slice(1) : "";
}

/** "24 faces (100.0%) below 1.5mm min wall for ded. Thinnest: 0.5mm." → "24 faces below 1.5 mm min wall · thinnest 0.5 mm". */
export function tidyReason(reason: string | null | undefined): string {
  if (!reason) return "";
  return reason
    .replace(/\s*\(\d+(\.\d+)?%\)/g, "")
    .replace(/(\d)mm\b/g, "$1 mm")
    .replace(/\s+for [a-z0-9_]+(?=\.|$)/i, "")
    .replace(/\.\s*Thinnest:\s*/i, " · thinnest ")
    .replace(/\.$/, "")
    .trim();
}

function routeLine(row: PartRow): string {
  const r = row.recommended_route;
  if (!r) return "No way found yet";
  return [wayName(r.process), r.material].filter(Boolean).join(" · ");
}

/**
 * The part's verdict. A blocked route (the engine withheld its price) wins: it
 * needs a design change whatever the machines say. Otherwise the machine
 * verdict from its makeability bucket; a part with no bucket row is "Not checked".
 */
export function verdictOf(row: PartRow, make: Makeability | null | undefined): Verdict {
  const stale = Boolean(make?.stale);
  if (make?.verdict === "geometry_invalid") {
    return { key: "invalid", label: "Can't read", tone: "bad", where: "The geometry can't be read", stale };
  }
  if (needsDesignChange(row)) {
    const reason = tidyReason(row.unit_cost?.withheld_reason);
    const wall = /wall/i.test(row.unit_cost?.withheld_reason ?? "");
    return { key: "design", label: wall ? "Thicker wall needed" : "Design change", tone: "warn", where: reason || `${routeLine(row)} · blocked as drawn`, stale };
  }
  const v = make?.verdict;
  if (v === "makeable_in_house" || v === "makeable_with_secondary_op") {
    return { key: "in", label: "On your machines", tone: "ok", where: routeLine(row), stale };
  }
  if (v === "makeable_not_on_owned") {
    const g = make?.gap?.gap?.[0];
    const big = g?.gate === "envelope";
    return { key: "machine", label: big ? "Bigger machine" : "Needs a machine", tone: "warn", where: gapLine(g) || "No machine you own clears every check", stale };
  }
  if (v === "makeable_outsource_only") {
    return { key: "outside", label: "Outside only", tone: "unk", where: `Outside · ${routeLine(row)}`, stale };
  }
  if (v === "environment_excluded") {
    return { key: "out", label: "Ruled out", tone: "bad", where: "Service conditions rule out every material", stale };
  }
  if (v === "not_makeable") {
    return { key: "out", label: "Ruled out", tone: "bad", where: "No way clears the checks as drawn", stale };
  }
  return { key: "unknown", label: "Not checked", tone: "unk", where: routeLine(row), stale };
}

/** The tile's price: the unit cost when the engine priced the route, "—" when withheld or never priced. */
export function priceText(row: PartRow): string {
  const uc = row.unit_cost;
  if (!uc || uc.withheld || uc.usd == null) return "—";
  return money(uc.usd);
}

export interface PartFilter {
  q: string;
  stage: "all" | "costed" | "drafted";
  finds: "any" | "with" | "none";
  machines: "all" | "stale" | VerdictKey;
}

export const NO_FILTER: PartFilter = { q: "", stage: "all", finds: "any", machines: "all" };

export function isFiltered(f: PartFilter): boolean {
  return f.q.trim() !== "" || f.stage !== "all" || f.finds !== "any" || f.machines !== "all";
}

/** Search matches the file name or the part id (mesh hash prefix), case-insensitive. */
export function matches(row: PartRow, verdict: Verdict, f: PartFilter): boolean {
  const q = f.q.trim().toLowerCase();
  if (q && !row.filename.toLowerCase().includes(q) && !row.part_key.toLowerCase().startsWith(q)) return false;
  if (f.stage === "costed" && row.lifecycle_state !== "Costed") return false;
  if (f.stage === "drafted" && row.lifecycle_state !== "Drafted") return false;
  if (f.finds === "with" && !(row.findings && row.findings.total > 0)) return false;
  if (f.finds === "none" && !(row.findings && row.findings.total === 0)) return false;
  if (f.machines === "stale") return verdict.stale;
  if (f.machines !== "all" && verdict.key !== f.machines) return false;
  return true;
}

/** Read a filter from URL search params (Home links here with `?machines=design` etc.). */
export function filterFromSearch(sp: { get(k: string): string | null }): PartFilter {
  const stage = sp.get("stage");
  const finds = sp.get("findings");
  const machines = sp.get("machines");
  const keys = new Set<string>(["all", "stale", ...VERDICT_FILTERS.map((v) => v.key)]);
  return {
    q: sp.get("q") ?? "",
    stage: stage === "costed" || stage === "drafted" ? stage : "all",
    finds: finds === "with" || finds === "none" ? finds : "any",
    machines: machines && keys.has(machines) ? (machines as PartFilter["machines"]) : "all",
  };
}

/** The query string for a filter (empty values left out), for a shareable URL. */
export function searchFromFilter(f: PartFilter): string {
  const p = new URLSearchParams();
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.stage !== "all") p.set("stage", f.stage);
  if (f.finds !== "any") p.set("findings", f.finds);
  if (f.machines !== "all") p.set("machines", f.machines);
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function countBy(verdicts: Verdict[]): Record<VerdictKey | "stale", number> {
  const out: Record<VerdictKey | "stale", number> = { in: 0, design: 0, machine: 0, out: 0, outside: 0, unknown: 0, invalid: 0, stale: 0 };
  for (const v of verdicts) {
    out[v.key] += 1;
    if (v.stale) out.stale += 1;
  }
  return out;
}

export interface Fact {
  n: string;
  t: string;
}

/** The page's fact line: "9 parts · 9 costed · 5 on your machines as drawn · …", only the non-zero facts. */
export function partsFacts(total: number, costed: number, c: Record<VerdictKey | "stale", number>): Fact[] {
  const n = (v: number) => v.toLocaleString("en-US");
  const facts: Fact[] = [{ n: n(total), t: total === 1 ? "part" : "parts" }];
  if (costed) facts.push({ n: n(costed), t: "costed" });
  if (c.in) facts.push({ n: n(c.in), t: "on your machines as drawn" });
  if (c.design) facts.push({ n: n(c.design), t: c.design === 1 ? "needs a design change" : "need a design change" });
  if (c.machine) facts.push({ n: n(c.machine), t: c.machine === 1 ? "needs a machine you don't have" : "need a machine you don't have" });
  if (c.outside) facts.push({ n: n(c.outside), t: "outside only" });
  if (c.out) facts.push({ n: n(c.out), t: "ruled out" });
  return facts;
}

/** The parts of GET /cost-decisions/{id} the peek reads. */
export interface DecisionLite {
  created_at?: string;
  result?: {
    geometry?: { bbox_mm?: number[] } | null;
    estimates?: { process: string; quantity: number; unit_cost_usd: number; confidence?: { low_usd: number; high_usd: number; half_width_pct: number; validated: boolean } }[];
    verification?: { per_route?: Record<string, { verdict: string; best_machine: string | null }> } | null;
  } | null;
}

export interface PeekFig {
  k: string;
  v: string;
  s?: string;
  c?: "ok" | "warn" | "bad";
}

/**
 * The peek's key figures: the price at the quoted quantity (and who makes it),
 * the engine's range at that quantity, and the machine verdict. A figure whose
 * source hasn't loaded or doesn't exist is left out, not guessed.
 */
export function peekFigs(row: PartRow, v: Verdict, d: DecisionLite | null): PeekFig[] {
  const figs: PeekFig[] = [];
  const uc = row.unit_cost;
  const route = row.recommended_route?.process ?? null;
  const fit = route ? d?.result?.verification?.per_route?.[route] : undefined;
  const maker = fit && (fit.verdict === "makeable_in_house" || fit.verdict === "makeable_with_secondary_op") && fit.best_machine ? `${fit.best_machine}, yours` : fit ? "Outside" : route ? wayName(route) : "";
  if (uc?.withheld) figs.push({ k: "Price", v: "Withheld", c: "warn", s: "Way needs a design change" });
  else if (uc && uc.usd != null) figs.push({ k: uc.qty != null ? `Each, at ${uc.qty.toLocaleString("en-US")}` : "Each", v: money(uc.usd), s: maker });
  else figs.push({ k: "Price", v: "Not priced", s: row.lifecycle_state === "Drafted" ? "Checked, not costed" : "No price for this way" });
  if (uc && !uc.withheld && uc.usd != null && route && d?.result?.estimates) {
    const e = d.result.estimates.find((x) => x.process === route && x.quantity === uc.qty);
    const c = e?.confidence;
    if (c && Number.isFinite(c.low_usd) && Number.isFinite(c.high_usd)) {
      figs.push({ k: "Range", v: `${money(c.low_usd)}–${money(c.high_usd)}`, s: `±${Math.round(c.half_width_pct)}%${c.validated ? ", from your real costs" : ", no real costs yet"}` });
    }
  }
  figs.push({ k: "Machines", v: v.label, c: v.tone === "ok" ? "ok" : v.tone === "bad" ? "bad" : v.tone === "warn" ? "warn" : undefined, s: v.stale ? `${v.where} · out of date` : v.where });
  return figs;
}
