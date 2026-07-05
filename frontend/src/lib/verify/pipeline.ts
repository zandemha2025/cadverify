/**
 * The PIPELINE model — the request lifecycle of the two real engine calls
 * (POST /validate + POST /validate/cost), shaped for the pipeline overlay.
 *
 * The overlay narrates five milestones — received → measured → routed → gates →
 * record — and this module maps each to what the engine ACTUALLY returned in the
 * VerifyResult. Nothing here fabricates a figure: every `detail` is either a value
 * read straight off a real response (geometry bbox/volume/watertight, routing +
 * confidence, the makeability verdict, the make-now Σ) or the honest ABSENCE of
 * one (withheld / not evaluated). The walk STOPS at a real failed gate (broken
 * geometry, or a not-makeable / environment-excluded verdict) and the stages past
 * it are marked "not computed" — never faked to fill the overlay.
 *
 * PURE selectors/formatters: no React, no runtime relative imports (only type-only
 * imports, which the type-stripping runner erases), so it runs under the repo's
 * `node --test`. Unit-tested in pipeline.test.ts.
 */
import type { VerifyResult } from "./run";
import type { CostReport } from "@/lib/api";
import type { MakeabilityLattice, Tone, VerificationBlock } from "./verification";

export type StageKey = "received" | "measured" | "routed" | "gates" | "record";
export type StageState = "pending" | "done" | "blocked" | "withheld";

export interface PipelineStage {
  key: StageKey;
  /** the milestone name, e.g. "measured" / "gates walked". */
  title: string;
  state: StageState;
  /** the honest one-line detail: real values, or the honest absence of them. */
  detail: string;
  /** status tone for colouring a landed / conditional / failed gate. */
  tone: Tone;
  /** true only when this stage is a REAL failed gate that stops the walk. */
  blocking: boolean;
  /** ● MEASURED is honest here — the value came straight off the CAD geometry. */
  measured?: boolean;
}

export interface PipelineModel {
  fileName: string | null;
  stages: PipelineStage[];
  /** index into `stages` of the failed gate the walk stops at, or -1 to complete. */
  stopIndex: number;
  /** true while the run is in flight and no result has landed (values withheld). */
  computing: boolean;
}

const TITLES: Record<StageKey, string> = {
  received: "received",
  measured: "measured",
  routed: "routed",
  gates: "gates walked",
  record: "record assembled",
};

const PASS_VERDICTS = new Set<MakeabilityLattice>([
  "makeable_in_house",
  "makeable_with_secondary_op",
]);
const COND_VERDICTS = new Set<MakeabilityLattice>([
  "makeable_not_on_owned",
  "makeable_outsource_only",
]);
const FAIL_VERDICTS = new Set<MakeabilityLattice>([
  "not_makeable",
  "environment_excluded",
]);

function fx(n: number): string {
  return Number.isFinite(n) ? n.toFixed(2) : "—";
}

function usd(n: number): string {
  if (!Number.isFinite(n)) return "—";
  return (
    "$" +
    n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  );
}

/** The make-now route's stable unit resource cost — the largest-quantity estimate
 *  of the engine's own `decision.make_now_process` pool (setup fully amortised).
 *  Selects, never fabricates: null when the engine returned no estimates. Mirrors
 *  derive.makeNowEstimate; inlined so this module stays runtime-import-free. */
function makeNowUnit(cost: CostReport | null): { process: string; unit: number } | null {
  if (!cost || !Array.isArray(cost.estimates) || cost.estimates.length === 0) return null;
  const proc = cost.decision?.make_now_process ?? null;
  const scoped = proc ? cost.estimates.filter((e) => e.process === proc) : cost.estimates;
  const pool = scoped.length > 0 ? scoped : cost.estimates;
  const chosen = pool.reduce((a, b) => (b.quantity > a.quantity ? b : a));
  return { process: chosen.process, unit: chosen.unit_cost_usd };
}

function first<T>(arr: T[] | undefined | null): T | null {
  return Array.isArray(arr) && arr.length > 0 ? arr[0] : null;
}

function gatesFailDetail(verdict: MakeabilityLattice, v: VerificationBlock): string {
  if (verdict === "environment_excluded") {
    const ex = first(v.env_exclusions);
    return ex && ex.human
      ? `environment-excluded — ${ex.human}`
      : "the declared world rules out every material that survives this route";
  }
  const gap = first(v.gap);
  return gap && gap.human
    ? `not makeable — ${gap.human}`
    : "no route clears the gates for this geometry";
}

function gatesCondDetail(verdict: MakeabilityLattice, v: VerificationBlock): string {
  if (verdict === "makeable_not_on_owned") {
    const gap = first(v.gap);
    return gap && gap.human
      ? `makeable — not on owned (${gap.human})`
      : "makeable — but not on the machines you own";
  }
  return "makeable — outsource only (you own nothing of this process family)";
}

function stage(
  key: StageKey,
  state: StageState,
  detail: string,
  opts: { tone?: Tone; blocking?: boolean; measured?: boolean } = {}
): PipelineStage {
  return {
    key,
    title: TITLES[key],
    state,
    detail,
    tone: opts.tone ?? "neutral",
    blocking: opts.blocking ?? false,
    measured: opts.measured,
  };
}

const pend = (key: StageKey, detail: string) => stage(key, "pending", detail);
const notComputed = (key: StageKey) => stage(key, "pending", "not computed past the failed gate");

/**
 * Build the pipeline model from a real VerifyResult (or the in-flight running
 * state). Every landed value comes off a real response; every absence is stated,
 * never faked; the walk stops at a real failed gate.
 */
export function pipelineModelFrom(
  result: VerifyResult | null,
  running: boolean,
  fileName: string | null
): PipelineModel {
  const name = fileName ?? result?.file?.name ?? null;

  const received = stage(
    "received",
    running || result ? "done" : "pending",
    "parsed in-process · mesh discarded after measurement"
  );

  // ── in flight: received has landed, everything downstream is honestly pending ──
  if (running && !result) {
    return {
      fileName: name,
      computing: true,
      stopIndex: -1,
      stages: [
        received,
        pend("measured", "measuring geometry…"),
        pend("routed", "routing the part…"),
        pend("gates", "walking the gates…"),
        pend("record", "assembling the record…"),
      ],
    };
  }

  // ── idle, nothing dropped yet ──
  if (!result) {
    return {
      fileName: name,
      computing: false,
      stopIndex: -1,
      stages: [
        received,
        pend("measured", "awaiting a part"),
        pend("routed", ""),
        pend("gates", ""),
        pend("record", ""),
      ],
    };
  }

  const stages: PipelineStage[] = [received];
  let stopIndex = -1;

  // ── measured (geometry, ● MEASURED) ──
  const geom = result.cost?.geometry ?? result.costGeometryInvalid?.geometry ?? null;
  if (geom) {
    const [x, y, z] = geom.bbox_mm;
    const measuredDetail = `bbox ${fx(x)} × ${fx(y)} × ${fx(z)} mm · ${fx(
      geom.volume_cm3
    )} cm³ · watertight ${geom.watertight}`;
    if (result.costGeometryInvalid) {
      stages.push(
        stage("measured", "blocked", `${measuredDetail} — ${result.costGeometryInvalid.message}`, {
          tone: "fail",
          blocking: true,
          measured: true,
        })
      );
      stopIndex = stages.length - 1;
    } else {
      stages.push(
        stage("measured", "done", measuredDetail, {
          tone: geom.watertight ? "pass" : "cond",
          measured: true,
        })
      );
    }
  } else {
    stages.push(
      stage(
        "measured",
        "withheld",
        result.costError ? `geometry not returned — ${result.costError}` : "geometry not returned",
        { tone: "neutral" }
      )
    );
    // Nothing downstream is computable without geometry — the walk stops honestly.
    stopIndex = stages.length - 1;
  }

  if (stopIndex >= 0) {
    stages.push(notComputed("routed"), notComputed("gates"), notComputed("record"));
    return { fileName: name, computing: false, stopIndex, stages };
  }

  // ── routed (geometric routing + confidence) ──
  const routing = result.cost?.routing ?? null;
  const proc = routing?.recommended_process ?? result.validation?.best_process ?? null;
  const conf = routing?.confidence;
  if (proc) {
    const arche = routing?.archetype ? `${routing.archetype} → ` : "";
    const confStr =
      typeof conf === "number" && Number.isFinite(conf) ? ` · confidence ${conf.toFixed(2)}` : "";
    stages.push(stage("routed", "done", `${arche}${proc}${confStr}`));
  } else {
    stages.push(stage("routed", "withheld", "routing not surfaced by this build"));
  }

  // ── gates (the makeability verification block) ──
  const v = result.verification;
  if (v && v.verdict) {
    const verdict = v.verdict;
    if (PASS_VERDICTS.has(verdict)) {
      const bm = v.best_machine ? `${v.best_machine} · ` : "";
      stages.push(stage("gates", "done", `${bm}a machine you own clears every gate ✓`, { tone: "pass" }));
    } else if (FAIL_VERDICTS.has(verdict)) {
      stages.push(stage("gates", "blocked", gatesFailDetail(verdict, v), { tone: "fail", blocking: true }));
      stopIndex = stages.length - 1;
    } else if (COND_VERDICTS.has(verdict)) {
      stages.push(stage("gates", "done", gatesCondDetail(verdict, v), { tone: "cond" }));
    } else {
      stages.push(stage("gates", "withheld", "makeability not evaluated — declare your floor"));
    }
  } else {
    stages.push(
      stage("gates", "withheld", "makeability not evaluated — no inventory or environment declared")
    );
  }

  if (stopIndex >= 0) {
    stages.push(notComputed("record"));
    return { fileName: name, computing: false, stopIndex, stages };
  }

  // ── record (Σ = the make-now unit resource cost) ──
  const mk = makeNowUnit(result.cost);
  if (mk) {
    stages.push(stage("record", "done", `Σ ${usd(mk.unit)} · make-now ${mk.process}`, { tone: "pass" }));
  } else {
    stages.push(
      stage(
        "record",
        "withheld",
        result.costError ? `cost not returned — ${result.costError}` : "cost not returned"
      )
    );
  }

  return { fileName: name, computing: false, stopIndex, stages };
}
