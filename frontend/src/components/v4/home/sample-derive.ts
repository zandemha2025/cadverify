/**
 * The sample's result summary (board X9 "Sample result"), from the real run's
 * VerifyResult (validation + cost + machine verdict). Pure and structural so it
 * tests under `node --test`; every figure is read off the run or left out.
 */
import { findingName, money, sizeText, wayName } from "./words.ts";

interface IssueLite {
  code: string;
  severity: string;
  message: string;
  fix_suggestion?: string | null;
}

export interface SampleRunLite {
  file: { name: string };
  validation: {
    process_scores: { process: string; verdict: string; score: number; issues: IssueLite[] }[];
    geometry?: { bounding_box_mm?: number[]; volume_mm3?: number; faces?: number; is_watertight?: boolean } | null;
  } | null;
  cost: {
    saved?: { id: string } | null;
    geometry?: { bbox_mm?: number[]; volume_cm3?: number; face_count?: number; watertight?: boolean } | null;
    decision?: { recommendation?: Record<string, { process: string; material: string; unit_cost_usd: number } | null> } | null;
    assumptions?: { provenance: string }[];
  } | null;
  verification: { verdict: string; best_machine?: string | null } | null;
}

export interface SampleFig {
  k: string;
  v: string;
  s: string;
  c?: "ok";
  text?: boolean;
}

export interface SampleSummary {
  file: string;
  saved: boolean;
  can: number;
  total: number;
  cant: number;
  figs: SampleFig[];
  firstIssue: { way: string; tone: "warn" | "bad" | "unk"; chip: string; text: string } | null;
  cantText: string | null;
  measured: [string, string][];
  ratesNote: string;
}

const SEV: Record<string, number> = { error: 0, warning: 1, info: 2 };

function shopFig(v: SampleRunLite["verification"]): SampleFig {
  switch (v?.verdict) {
    case "makeable_in_house":
    case "makeable_with_secondary_op":
      return { k: "Your shop", v: "In-house", s: v.best_machine ?? "On a machine you own", text: true };
    case "makeable_not_on_owned":
      return { k: "Your shop", v: "Not on your machines", s: "Makeable elsewhere", text: true };
    case "makeable_outsource_only":
      return { k: "Your shop", v: "Outside", s: "No machine of this kind", text: true };
    case "environment_excluded":
    case "not_makeable":
      return { k: "Your shop", v: "Ruled out", s: "Service conditions or the checks", text: true };
    default:
      return { k: "Your shop", v: "Not checked", s: "Add machines to check fit", text: true };
  }
}

export function sampleSummary(r: SampleRunLite): SampleSummary {
  const scores = r.validation?.process_scores ?? [];
  const total = scores.length;
  const cant = scores.filter((p) => p.verdict === "fail").length;
  const rec = r.cost?.decision?.recommendation ?? {};
  const qtys = Object.keys(rec)
    .map(Number)
    .filter((q) => Number.isFinite(q) && rec[String(q)])
    .sort((a, b) => a - b);
  const figs: SampleFig[] = [];
  if (total) figs.push({ k: "Can make it", v: `${total - cant} of ${total}`, s: `${cant} can't as drawn`, c: "ok" });
  const first = qtys[0];
  if (first != null) {
    const x = rec[String(first)]!;
    figs.push({ k: `Make now · ${first.toLocaleString("en-US")}`, v: money(x.unit_cost_usd), s: `${wayName(x.process)} · ${x.material}` });
  }
  const at10 = qtys.includes(10) && first !== 10 ? 10 : qtys.find((q) => q > (first ?? 0));
  if (at10 != null) {
    const x = rec[String(at10)]!;
    figs.push({ k: `Each at ${at10.toLocaleString("en-US")}`, v: money(x.unit_cost_usd), s: `${wayName(x.process)} · ${x.material}` });
  }
  figs.push(shopFig(r.verification));

  // The first issue on the way it's made now (the cheapest at the first quantity).
  const route = first != null ? rec[String(first)]!.process : null;
  const routeIssues = route ? scores.find((p) => p.process === route)?.issues ?? [] : [];
  const top = [...routeIssues].sort((a, b) => (SEV[a.severity] ?? 3) - (SEV[b.severity] ?? 3))[0] ?? null;
  const firstIssue = top
    ? {
        way: wayName(route),
        tone: top.severity === "error" ? ("bad" as const) : top.severity === "warning" ? ("warn" as const) : ("unk" as const),
        chip: top.severity === "error" ? "Must change" : top.severity === "warning" ? "Warning" : "Info",
        text: [top.message, top.fix_suggestion].filter(Boolean).join(" "),
      }
    : null;

  // Ways that can't make it as drawn, grouped by the reason that stops them.
  const groups = new Map<string, string[]>();
  for (const p of scores.filter((x) => x.verdict === "fail")) {
    const e = [...p.issues].sort((a, b) => (SEV[a.severity] ?? 3) - (SEV[b.severity] ?? 3))[0];
    const why = e ? findingName(e.code, e.message) : "Doesn't clear the checks";
    groups.set(why, [...(groups.get(why) ?? []), wayName(p.process)]);
  }
  const cantText = groups.size
    ? [...groups.entries()].map(([why, ways]) => `${ways.join(", ")}: ${why.toLowerCase()}`).join(". ") + "."
    : null;

  const cg = r.cost?.geometry ?? null;
  const vg = r.validation?.geometry ?? null;
  const measured: [string, string][] = [];
  const size = sizeText(cg?.bbox_mm ?? vg?.bounding_box_mm);
  if (size) measured.push(["Size", size]);
  const vol = cg?.volume_cm3 ?? (vg?.volume_mm3 != null ? vg.volume_mm3 / 1000 : null);
  if (vol != null) measured.push(["Volume", `${Math.round(vol * 100) / 100} cm³`]);
  const faces = cg?.face_count ?? vg?.faces;
  if (faces != null) measured.push(["Faces", faces.toLocaleString("en-US")]);
  const tight = cg?.watertight ?? vg?.is_watertight;
  if (tight != null) measured.push(["Watertight", tight ? "Yes" : "No"]);

  const yours = (r.cost?.assumptions ?? []).some((a) => /^(USER|SHOP)$/i.test(a.provenance));
  return {
    file: r.file.name,
    saved: Boolean(r.cost?.saved),
    can: total - cant,
    total,
    cant,
    figs,
    firstIssue,
    cantText,
    measured,
    ratesNote: yours ? "Costs use your rates where you set them and typical values elsewhere; not supplier quotes." : "Costs use typical rates, not supplier quotes.",
  };
}

/** The sample bar line once the result dialog is closed. */
export function sampleBarLine(s: SampleSummary): string {
  return [s.file, s.total ? `${s.can} of ${s.total} can make it` : null, s.saved ? "saved to Records" : null].filter(Boolean).join(" · ");
}
