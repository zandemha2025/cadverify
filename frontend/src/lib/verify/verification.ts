/**
 * The makeability VERIFICATION block — the engine's §0 verdict lattice, rendered
 * faithfully. Every field here is READ off the real top-level `verification` block
 * the cost route now returns (backend/src/costing/estimate.py::_serialize_verification):
 * per-route machine fit, the acquisition gap, environment exclusions with their
 * cited standard, and the aggregate verdict. NOTHING is fabricated — when the block
 * is absent (no inventory + no declared environment → byte-identical unused path)
 * the walk renders the honest "not evaluated" state instead of a fake pass.
 *
 * These are PURE selectors/formatters (no React, no runtime relative imports) so
 * they run under the repo's `node --test` type-stripping runner. Unit-tested in
 * verification.test.ts.
 */

/** The verdict lattice the engine emits WHEN a makeability block is present. */
export type MakeabilityLattice =
  | "makeable_in_house"
  | "makeable_with_secondary_op"
  | "makeable_not_on_owned"
  | "makeable_outsource_only"
  | "environment_excluded"
  | "not_makeable"
  | "unknown";

/** One failed / unknown gate, verbatim from the engine (`_ff_to_dict`). A concrete
 *  gap carries numeric need/have; an unknown gate carries `have: null`. */
export interface FitFailure {
  gate: string;
  axis: string;
  need: unknown;
  have: unknown;
  human: string;
}

/** Per-route machine fit as `_serialize_verification` emits it. */
export interface PerRouteFit {
  verdict: MakeabilityLattice;
  machines_evaluated: number;
  best_machine: string | null;
  failures: FitFailure[];
  machine_rate_usd?: number | null;
  capital_frac?: number | null;
  secondary_ops?: string[];
}

/** The top-level `verification` block (present only when the org declared machines
 *  and/or a service environment). Rendered faithfully; its ABSENCE — not any
 *  fabricated value — drives the honest "not evaluated" state. */
export interface VerificationBlock {
  verdict: MakeabilityLattice;
  best_machine?: string | null;
  resource?: unknown;
  gap?: FitFailure[];
  env_exclusions?: FitFailure[];
  per_route?: Record<string, PerRouteFit>;
  inventory_declared?: boolean;
  environment_declared?: boolean;
  provenance?: string;
  note?: string;
}

export type Tone = "pass" | "cond" | "fail" | "neutral";

/** The banner content for a verdict lattice value. The verdict — not a DFM guess —
 *  is what a makeability block, when present, drives. */
export interface VerdictBannerModel {
  kicker: string;
  title: string;
  sub: string;
  tone: Tone;
}

const BANNER: Record<MakeabilityLattice, VerdictBannerModel> = {
  makeable_in_house: {
    kicker: "VERDICT · MAKEABLE IN-HOUSE",
    title: "Makeable on your machines.",
    sub: "A machine you own clears every gate for the recommended route — the make-it-ourselves path is live.",
    tone: "pass",
  },
  makeable_with_secondary_op: {
    kicker: "VERDICT · MAKEABLE — WITH A SECONDARY OP",
    title: "Makeable in-house, with a secondary operation.",
    sub: "An owned machine clears the primary route; the verdict names the secondary op it still needs.",
    tone: "pass",
  },
  makeable_not_on_owned: {
    kicker: "VERDICT · MAKEABLE — NOT ON OWNED",
    title: "Makeable — but not on the machines you own.",
    sub: "The geometry is manufacturable, but no owned machine clears every gate. The gap below is a concrete measured-vs-declared delta — what you'd acquire, not a vague 'too big'.",
    tone: "cond",
  },
  makeable_outsource_only: {
    kicker: "VERDICT · OUTSOURCE ONLY",
    title: "Makeable — outsource only.",
    sub: "You own nothing of the recommended process family, so it's a buy for now. Declare or acquire the machine to flip this in-house.",
    tone: "cond",
  },
  environment_excluded: {
    kicker: "VERDICT · ENVIRONMENT-EXCLUDED",
    title: "The declared world rules out this material.",
    sub: "The service environment excludes every candidate that survives on the recommended route — the strikes below cite the material property / standard.",
    tone: "fail",
  },
  not_makeable: {
    kicker: "VERDICT · NOT MAKEABLE",
    title: "Not makeable as modeled.",
    sub: "No route clears the gates for this geometry — the engine will not fabricate a pass to fill the page.",
    tone: "fail",
  },
  unknown: {
    kicker: "VERDICT · UNKNOWN — NOT ENOUGH DECLARED",
    title: "Makeability unknown — not enough is declared.",
    sub: "No inventory (or a required capability) is declared, so the machine verdict is honestly unknown — never a fabricated pass. Declare your floor to resolve it.",
    tone: "neutral",
  },
};

export function verdictBannerModel(verdict: MakeabilityLattice): VerdictBannerModel {
  return BANNER[verdict] ?? BANNER.unknown;
}

const LATTICE_VALUES = new Set<MakeabilityLattice>([
  "makeable_in_house",
  "makeable_with_secondary_op",
  "makeable_not_on_owned",
  "makeable_outsource_only",
  "environment_excluded",
  "not_makeable",
  "unknown",
]);

/** Read the persisted verification block defensively from an engine report.
 * Old records may predate the field; malformed values are treated as absent,
 * never coerced into a pass. */
export function readVerification(report: unknown): VerificationBlock | null {
  if (!report || typeof report !== "object") return null;
  const candidate = (report as { verification?: unknown }).verification;
  if (!candidate || typeof candidate !== "object") return null;
  const verdict = (candidate as { verdict?: unknown }).verdict;
  if (typeof verdict !== "string" || !LATTICE_VALUES.has(verdict as MakeabilityLattice)) {
    return null;
  }
  return candidate as VerificationBlock;
}

export interface RecordVerdictModel {
  text: string;
  kicker: string;
  tone: Tone;
}

/** The verdict label for persisted records. Machine fit wins whenever the
 * report carries it. DFM is only a fallback dimension and can never be used to
 * fabricate an in-house claim. */
export function recordVerdictModel(
  report: unknown,
  state: {
    hasCostedRoute: boolean;
    dfmReady?: boolean | null;
    dfmVerdict?: string | null;
  },
): RecordVerdictModel {
  if (!state.hasCostedRoute) {
    return { text: "Verdict withheld.", kicker: "VERDICT · WITHHELD", tone: "neutral" };
  }

  const verification = readVerification(report);
  if (verification) {
    const model = verdictBannerModel(verification.verdict);
    return { text: model.title, kicker: model.kicker, tone: model.tone };
  }

  if (state.dfmReady === false || state.dfmVerdict === "fail") {
    return { text: "Blocked by route geometry.", kicker: "DFM · BLOCKED", tone: "fail" };
  }
  if (state.dfmVerdict === "issues") {
    return {
      text: "Makeable as modeled — DFM advisories.",
      kicker: "DFM · ADVISORIES · MACHINE FIT NOT EVALUATED",
      tone: "cond",
    };
  }
  return {
    text: "Costed route — machine fit not evaluated.",
    kicker: "SHOULD-COST · MACHINE FIT NOT EVALUATED",
    tone: "neutral",
  };
}

/** ✓ for a clear pass, ✗ for a real failure, ? for an undeclared/unknown gate. */
export function fitMark(verdict: MakeabilityLattice): { glyph: string; tone: Tone } {
  if (verdict === "makeable_in_house" || verdict === "makeable_with_secondary_op")
    return { glyph: "✓", tone: "pass" };
  if (verdict === "unknown") return { glyph: "?", tone: "neutral" };
  return { glyph: "✗", tone: "fail" };
}

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function fmtBound(v: unknown): string {
  if (v == null) return "—";
  if (isNum(v)) {
    const rounded = Math.round(v * 100) / 100;
    return String(rounded);
  }
  if (Array.isArray(v)) return v.map(fmtBound).join(" × ");
  return String(v);
}

/** A gate failure as "need N, have M" when both are quantified, else the engine's
 *  own `human` string. Never invents a number the engine didn't send. */
export function gapText(f: FitFailure): string {
  if (isNum(f.need) && isNum(f.have)) {
    return `need ${fmtBound(f.need)}, have ${fmtBound(f.have)}`;
  }
  if (f.human) return f.human;
  if (f.have == null && f.need != null) {
    return `needs ${fmtBound(f.need)} — undeclared`;
  }
  return f.gate;
}

/** One rendered per-route fit row. `envelope`/`mass`/etc. failures ride `failures`. */
export interface RouteFitRow {
  process: string;
  verdict: MakeabilityLattice;
  glyph: string;
  tone: Tone;
  machinesEvaluated: number;
  bestMachine: string | null;
  failures: FitFailure[];
}

/** The per-route fit rows, in_house first then by verdict severity, else route id. */
export function perRouteRows(v: VerificationBlock | null | undefined): RouteFitRow[] {
  if (!v || !v.per_route) return [];
  const order: MakeabilityLattice[] = [
    "makeable_in_house",
    "makeable_with_secondary_op",
    "makeable_not_on_owned",
    "makeable_outsource_only",
    "environment_excluded",
    "not_makeable",
    "unknown",
  ];
  const rank = (verdict: MakeabilityLattice) => {
    const i = order.indexOf(verdict);
    return i === -1 ? order.length : i;
  };
  return Object.entries(v.per_route)
    .map(([process, fit]) => {
      const mark = fitMark(fit.verdict);
      return {
        process,
        verdict: fit.verdict,
        glyph: mark.glyph,
        tone: mark.tone,
        machinesEvaluated: fit.machines_evaluated ?? 0,
        bestMachine: fit.best_machine ?? null,
        failures: Array.isArray(fit.failures) ? fit.failures : [],
      };
    })
    .sort((a, b) => rank(a.verdict) - rank(b.verdict) || a.process.localeCompare(b.process));
}

/** One struck-out material with its cited exclusion reason (axis = material). */
export interface EnvStrike {
  material: string;
  reason: string;
}

/** The environment exclusions — each cites the material property / standard that
 *  ruled it out (e.g. "… excluded by NACE MR0175 under sour service"). */
export function envStrikes(v: VerificationBlock | null | undefined): EnvStrike[] {
  if (!v || !Array.isArray(v.env_exclusions)) return [];
  return v.env_exclusions.map((f) => ({
    material: f.axis || "material",
    reason: f.human || `excluded by the declared service environment (${f.gate})`,
  }));
}

/** The machine-specific marginal rate for a route, when a PASSING owned machine
 *  re-costs it at its OWN declared rate (SHOP provenance, names the machine). */
export interface MarginalRate {
  machine: string | null;
  rateUsd: number | null;
}

export function marginalRate(
  v: VerificationBlock | null | undefined,
  process: string | null | undefined
): MarginalRate | null {
  if (!v || !v.per_route || !process) return null;
  const fit = v.per_route[process];
  if (!fit) return null;
  const rate = fit.machine_rate_usd;
  if (!isNum(rate)) return null;
  return { machine: fit.best_machine ?? v.best_machine ?? null, rateUsd: rate };
}

/** The top-level acquisition gap (concrete measured-vs-declared deltas) — what an
 *  org would need to acquire to make this in-house. */
export function acquisitionGap(v: VerificationBlock | null | undefined): FitFailure[] {
  if (!v || !Array.isArray(v.gap)) return [];
  return v.gap;
}
