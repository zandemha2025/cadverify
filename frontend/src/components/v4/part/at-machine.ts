/**
 * What an operator needs at the machine (me-16): overall size, a turned part's
 * steps (diameter and length, end to end), holes and bores, the setups and what
 * each does, the stock and machine the price assumes, and the tightest
 * tolerance declared. Every size is measured from the file (the check's
 * detected features); the setup plan is ScaleCAD's, from those steps, and says
 * so; what isn't measured (threads, milling setups) is said as not measured.
 * Sizes are in mm here; the page shows them in the person's unit.
 *
 * Pure: type-only imports, for node --test (at-machine.test.ts).
 */
import type { CostEstimate, FeatureInfo } from "@/lib/api";

export interface TurnStep {
  dia: number;
  len: number;
}

export interface HoleGroup {
  n: number;
  dia: number;
  depth: number | null;
}

export interface MachineFacts {
  /** The part's box, mm, as measured. */
  size: readonly number[] | null;
  turned: boolean;
  /** A turned part's diameters along its axis, from the end with the biggest diameter. */
  steps: TurnStep[];
  holes: HoleGroup[];
  /** Setups and what each does: ScaleCAD's plan from the measured steps (turned parts), else null. */
  plan: { setups: number; ops: string[] } | null;
  /** What the price assumes: its setups and the stock, in the engine's own words. */
  priced: { setupHours: number | null; setups: number | null; stock: string | null } | null;
  machine: string | null;
  tolerance: string | null;
}

const fmt = (mm: number) => `${Number(mm.toFixed(2))}`;

function close(a: number, b: number, tol = 0.02): boolean {
  return Math.abs(a - b) <= tol * Math.max(Math.abs(a), Math.abs(b), 1);
}

/** The axis the bosses line up on: the centroid coordinate that varies while the other two stay put. */
function axisOf(fs: FeatureInfo[]): number | null {
  if (fs.length < 2) return fs.length === 1 ? 2 : null;
  const spread = [0, 1, 2].map((i) => {
    const v = fs.map((f) => f.centroid[i]);
    return Math.max(...v) - Math.min(...v);
  });
  const axis = spread.indexOf(Math.max(...spread));
  const others = [0, 1, 2].filter((i) => i !== axis);
  return others.every((i) => spread[i] < 0.05 * Math.max(spread[axis], 1)) ? axis : null;
}

/** A turned part's steps from the check's cylinder bosses, ordered end to end from the biggest diameter's end. */
export function turnedSteps(features: readonly FeatureInfo[] | null | undefined): TurnStep[] {
  const bosses = (features ?? []).filter((f) => f.kind === "cylinder_boss" && typeof f.radius === "number" && f.radius > 0 && typeof f.depth === "number" && f.depth > 0);
  const axis = axisOf(bosses);
  if (axis == null) return [];
  const along = [...bosses].sort((a, b) => a.centroid[axis] - b.centroid[axis]).map((f) => ({ dia: 2 * (f.radius as number), len: f.depth as number }));
  // Read from the end with the biggest diameter (where the bar is held first).
  const big = Math.max(...along.map((s) => s.dia));
  return along[0].dia === big || along[along.length - 1].dia !== big ? along : along.reverse();
}

/** Holes grouped by size: "2 × Ø4 × 20 deep". */
export function holeGroups(features: readonly FeatureInfo[] | null | undefined): HoleGroup[] {
  const out: HoleGroup[] = [];
  for (const f of features ?? []) {
    if (f.kind !== "cylinder_hole" || typeof f.radius !== "number" || !(f.radius > 0)) continue;
    const dia = 2 * f.radius;
    const depth = typeof f.depth === "number" && f.depth > 0 ? f.depth : null;
    const g = out.find((x) => close(x.dia, dia) && (x.depth == null ? depth == null : depth != null && close(x.depth, depth)));
    if (g) g.n += 1;
    else out.push({ n: 1, dia, depth });
  }
  return out.sort((a, b) => b.n - a.n || b.dia - a.dia);
}

/**
 * The setups for a turned part, from its steps. Diameters that only fall from
 * one end are all turned from the free end in one setup, then the part is
 * flipped to face the parted end; a biggest diameter in the middle means each
 * side is turned in its own setup.
 */
export function turningPlan(steps: readonly TurnStep[]): { setups: number; ops: string[] } | null {
  if (!steps.length) return null;
  const big = steps[0];
  const total = steps.reduce((n, s) => n + s.len, 0);
  const falls = steps.every((s, i) => i === 0 || s.dia <= steps[i - 1].dia + 1e-6);
  const rest = steps.slice(1);
  if (falls) {
    return {
      setups: 2,
      ops: [
        `OP10: hold the Ø${fmt(big.dia)} mm stock in the chuck; face, turn ${rest.length ? rest.map((s) => `Ø${fmt(s.dia)} mm × ${fmt(s.len)} mm`).join(", then ") : `Ø${fmt(big.dia)} mm`} from the free end; part off at ${fmt(total)} mm`,
        `OP20: flip, grip a turned diameter (soft jaws); face the parted end to the ${fmt(total)} mm length`,
      ],
    };
  }
  const i = steps.findIndex((s) => s.dia === Math.max(...steps.map((x) => x.dia)));
  const left = steps.slice(0, i);
  const right = steps.slice(i + 1);
  const words = (xs: TurnStep[]) => xs.map((s) => `Ø${fmt(s.dia)} mm × ${fmt(s.len)} mm`).join(", ");
  return {
    setups: 2,
    ops: [`OP10: turn one side up to the Ø${fmt(steps[i].dia)} mm collar: ${words(right) || "its face"}`, `OP20: flip, grip the turned side; turn the other: ${words(left) || "its face"}`],
  };
}

function driver(e: CostEstimate | null | undefined, name: string) {
  return e?.drivers?.find((d) => d.name === name) ?? null;
}

/** What the price assumes about setups and stock, read from the estimate's own lines. */
export function pricedSetup(e: CostEstimate | null | undefined): MachineFacts["priced"] {
  if (!e) return null;
  const setup = driver(e, "setup_cost")?.source ?? "";
  const insp = driver(e, "inspection_cost")?.source ?? "";
  const mat = driver(e, "material_cost")?.source ?? "";
  const h = /setup\s+([\d.]+)\s*hr/.exec(setup);
  const n = /×\s*([\d.]+)\s*setup\(s\)/.exec(insp);
  const stock = /^(bounding cylinder [^=]+?|stock [^=]+?|billet [^=]+?|block [^=]+?)\s*=/.exec(mat);
  return { setupHours: h ? Number(h[1]) : null, setups: n ? Number(n[1]) : null, stock: stock ? stock[1].trim() : null };
}

export function machineFacts(i: {
  features: readonly FeatureInfo[] | null | undefined;
  size: readonly number[] | null;
  rotational: boolean | null;
  estimate: CostEstimate | null;
  machine: string | null;
  tolerance: string | null;
}): MachineFacts {
  const steps = i.rotational === false ? [] : turnedSteps(i.features);
  const turned = steps.length > 0;
  return {
    size: i.size,
    turned,
    steps,
    holes: holeGroups(i.features),
    plan: turned ? turningPlan(steps) : null,
    priced: pricedSetup(i.estimate),
    machine: i.machine,
    tolerance: i.tolerance,
  };
}

export interface FactRow {
  k: string;
  v: string;
}

/** The facts as rows (sizes in mm; the page converts them to the person's unit). */
export function factRows(f: MachineFacts): FactRow[] {
  const rows: FactRow[] = [];
  if (f.size) rows.push({ k: "Overall", v: `${f.size.map(fmt).join(" × ")} mm` });
  if (f.turned) rows.push({ k: "Steps", v: f.steps.map((s) => `Ø${fmt(s.dia)} mm × ${fmt(s.len)} mm`).join(" · ") });
  rows.push({ k: "Holes", v: f.holes.length ? f.holes.map((h) => `${h.n} × Ø${fmt(h.dia)} mm${h.depth != null ? ` × ${fmt(h.depth)} mm deep` : ""}`).join(" · ") : "None detected" });
  rows.push({ k: "Threads", v: "Not measured: the file's shape carries no thread data. Check the print." });
  if (f.plan) f.plan.ops.forEach((op, n) => rows.push({ k: n === 0 ? `Setups: ${f.plan!.setups}` : "", v: op }));
  else rows.push({ k: "Setups", v: "Not planned: ScaleCAD plans setups for turned parts only." });
  if (f.priced) {
    const bits = [f.priced.setups != null ? `${f.priced.setups} setup${f.priced.setups === 1 ? "" : "s"}` : null, f.priced.setupHours != null ? `${fmt(f.priced.setupHours)} h to set up` : null, f.priced.stock ? `from ${f.priced.stock}` : null].filter(Boolean);
    if (bits.length) rows.push({ k: "The price assumes", v: bits.join(", ") });
  }
  rows.push({ k: "Machine", v: f.machine ?? "Not chosen" });
  rows.push({ k: "Tightest tolerance", v: f.tolerance ? `General ${f.tolerance} (declared on Specs)` : "Not declared. Tighter callouts are on the print." });
  return rows;
}

/** One line for the section header: "Ø30 × 20 mm, Ø16 × 30 mm, Ø10 × 10 mm · 2 setups · Haas ST-20". */
export function factLine(f: MachineFacts): string {
  const bits: string[] = [];
  if (f.turned) bits.push(f.steps.map((s) => `Ø${fmt(s.dia)} × ${fmt(s.len)} mm`).join(", "));
  else if (f.size) bits.push(`${f.size.map(fmt).join(" × ")} mm`);
  if (f.holes.length) bits.push(`${f.holes.reduce((n, h) => n + h.n, 0)} hole${f.holes.reduce((n, h) => n + h.n, 0) === 1 ? "" : "s"}`);
  if (f.plan) bits.push(`${f.plan.setups} setups`);
  if (f.machine) bits.push(f.machine);
  return bits.join(" · ");
}

/** Whether a typed question asks for setups or for sizes ("how many setups", "what are the step diameters"). */
export function machineQuestion(text: string): "setups" | "sizes" | null {
  const t = text.toLowerCase();
  const setups = /\bsetups?\b|\bset-?ups?\b|\bop\s?\d0\b|\boperations?\b|\bfixtur|\bflip\b|\bchuck\b|\bvise\b|\bjaws?\b/.test(t);
  const sizes = /diameter|\bdia\b|ø|\bsteps?\b|\blengths?\b|\bdimensions?\b|\bsize\b|\bholes?\b|\bbores?\b|\bthreads?\b|\btolerance/.test(t);
  if (setups) return "setups";
  if (sizes) return "sizes";
  return null;
}


/** The Ask answer to "how many setups" or "what diameters": the same facts, computed from this check. */
export function machineAnswer(f: MachineFacts): { tag: "Computed"; title: string; rows: FactRow[]; text: string } {
  return {
    tag: "Computed",
    title: f.turned ? "Setups and step sizes" : "Sizes and setups",
    rows: factRows(f).filter((r) => r.k !== "Threads"),
    text: "Sizes are measured from the file; the setups are ScaleCAD’s plan from the measured steps. Threads and toleranced callouts are on the print.",
  };
}
