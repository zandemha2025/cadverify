/**
 * Home derivations (board P1): the "Needs attention" queue and the sheet each
 * item opens, the fact line, the recent records and the four setup steps.
 * Pure and import-light so it unit-tests under `node --test`.
 *
 * Honesty: an item appears only from a KNOWN signal (a loaded count that says
 * something needs doing). A source that is still loading (null) or failed
 * produces no item and no zero; the screen says which sources didn't load.
 */
import { R } from "../routes.ts";
import type { Bucket, ChangeRow, MachineRow, MakeSummary, PartRow, Posture, RateSource, RecordRow } from "./model.ts";
import { needsDesignChange, tidyReason } from "./parts-derive.ts";
import { plural, shortWhen, wayName } from "./words.ts";

export interface HomeInput {
  records: RecordRow[] | null;
  /** more records exist than were loaded (the list endpoint pages at 100) */
  recordsMore: boolean;
  parts: PartRow[] | null;
  /** org-wide part count from the catalog facets */
  partsTotal: number | null;
  make: MakeSummary | null;
  machines: MachineRow[] | null;
  changes: ChangeRow[] | null;
  actuals: number | null;
  posture: Posture | null;
  rates: RateSource | null;
  programs: number | null;
  withVolume: number | null;
}

export type Tone = "ok" | "warn" | "bad" | "yours";

export interface SheetFig {
  k: string;
  v: string;
  s?: string;
  c?: "ok" | "warn" | "bad";
}

export interface InvolvedPart {
  name: string;
  note: string;
  href?: string;
}

export interface QueueItem {
  key: string;
  icon: string;
  tone: Tone;
  n: string;
  title: string;
  short: string;
  name: string;
  meta: string;
  figs: SheetFig[];
  partsLabel: string;
  parts: InvolvedPart[];
  /** buckets whose parts the sheet loads on demand (the rollup carries counts only) */
  lazyBuckets?: Bucket[];
  /** only the parts the drill-down marks stale */
  lazyStale?: boolean;
  kv: [string, string][];
  act: { label: string; href: string };
  alt?: { label: string; href: string };
  foot?: string;
}

export function machineCount(machines: MachineRow[] | null): number | null {
  if (!machines) return null;
  // Same rule as the inventory service: an undeclared count is one machine.
  return machines.reduce((n, m) => n + (m.count ?? 1), 0);
}

export function yoursOf(p: Posture | null): { yours: number; total: number } | null {
  if (!p || !p.total) return null;
  return { yours: p.shop + p.user, total: p.total };
}

/** "default_rate_card_v0" → "Default rate card (v0)"; a governed card → "Your rate card". */
export function rateCardName(r: RateSource | null): string {
  if (!r) return "";
  if (r.using_governed) return "Your rate card";
  const m = /^default_rate_card_(v\d+)$/.exec(r.source);
  if (m) return `Default rate card (${m[1]})`;
  return r.source.replace(/_/g, " ");
}

function partsByFile(parts: PartRow[]): InvolvedPart[] {
  return parts.slice(0, 3).map((p) => ({ name: p.filename, note: tidyReason(p.unit_cost?.withheld_reason) || "Blocked as drawn", href: R.part(p.part_key) }));
}

export function buildQueue(input: HomeInput): QueueItem[] {
  const out: QueueItem[] = [];
  const nMachines = machineCount(input.machines);
  const recordCount = input.records?.length ?? null;
  const more = input.recordsMore ? "+" : "";

  if (nMachines === 0) {
    out.push({
      key: "machines",
      icon: "+",
      tone: "bad",
      n: "0",
      title: "No machines added",
      short: "Shop fit isn't checked until you add one",
      name: "Machines and printers",
      meta: "Verdicts say what your shop can make once you add your machines",
      figs: [{ k: "Machines", v: "0", s: "added" }],
      partsLabel: "",
      parts: [],
      kv: [],
      act: { label: "Add machines", href: `${R.shop}?add=1` },
    });
  }

  const make = input.make;
  if (make && make.stale_count > 0) {
    const n = make.stale_count;
    out.push({
      key: "stale",
      icon: "↻",
      tone: "warn",
      n: String(n),
      title: `${plural(n, "machine verdict")} out of date`,
      short: "Machine list changed after these parts were checked",
      name: "Machine verdicts",
      meta: "Machine list changed after these parts were checked",
      figs: [
        { k: "Out of date", v: `${n} of ${make.total}`, s: "parts", c: "warn" },
        { k: "Current", v: `${make.total - n} of ${make.total}`, s: "parts" },
        { k: "Re-check", v: "1 check", s: "per part" },
      ],
      partsLabel: "Parts",
      parts: [],
      lazyBuckets: ["makeable_in_house", "makeable_outside", "needs_capability", "not_makeable"],
      lazyStale: true,
      kv: [],
      act: { label: `Show ${plural(n, "part")}`, href: `${R.parts}?machines=stale` },
      foot: "Re-check a part from its page. Outside prices don't depend on your machines.",
    });
  }

  const blocked = (input.parts ?? []).filter(needsDesignChange);
  if (blocked.length) {
    const one = blocked.length === 1 ? blocked[0] : null;
    out.push({
      key: "design",
      icon: "!",
      tone: "bad",
      n: String(blocked.length),
      title: one ? `${one.filename} needs a design change` : `${blocked.length} parts need a design change`,
      short: tidyReason(blocked[0].unit_cost?.withheld_reason) || "The way it's made is blocked as drawn",
      name: one ? one.filename : "Design changes",
      meta: "Price withheld until the design changes",
      figs: blocked.slice(0, 3).map((p) => ({ k: p.filename, v: "Withheld", s: p.recommended_route ? wayName(p.recommended_route.process) : "No way found", c: "bad" as const })),
      partsLabel: one ? "Part" : "Parts",
      parts: partsByFile(blocked),
      kv: [],
      act: one ? { label: "Open part", href: R.part(one.part_key) } : { label: `Show ${blocked.length} parts`, href: `${R.parts}?machines=design` },
    });
  }

  if (make && make.needs_capability > 0) {
    const n = make.needs_capability;
    out.push({
      key: "capability",
      icon: "⤢",
      tone: "warn",
      n: String(n),
      title: n === 1 ? "1 part needs a machine you don't have" : `${n} parts need a machine you don't have`,
      short: "No machine you own clears every check",
      name: "Needs a machine",
      meta: "Makeable, but not on the machines you have",
      figs: [{ k: "Parts", v: String(n), s: "need another machine", c: "warn" }],
      partsLabel: n === 1 ? "Part" : "Parts",
      parts: [],
      lazyBuckets: ["needs_capability"],
      kv: [],
      act: { label: "Find a machine", href: R.triage },
      alt: { label: "Build supplier package", href: R.packages },
    });
  }

  if (make && make.not_makeable > 0) {
    const n = make.not_makeable;
    out.push({
      key: "out",
      icon: "✕",
      tone: "bad",
      n: String(n),
      title: n === 1 ? "1 part ruled out" : `${n} parts ruled out`,
      short: "Service conditions or the shape rule out every way",
      name: "Ruled out",
      meta: "No way clears the service conditions or the checks",
      figs: [{ k: "Parts", v: String(n), s: "ruled out", c: "bad" }],
      partsLabel: n === 1 ? "Part" : "Parts",
      parts: [],
      lazyBuckets: ["not_makeable"],
      kv: [],
      act: { label: n === 1 ? "Show the part" : `Show ${n} parts`, href: `${R.parts}?machines=out` },
    });
  }

  const proposed = (input.changes ?? []).filter((c) => c.status === "proposed");
  if (proposed.length) {
    out.push({
      key: "changes",
      icon: "⇄",
      tone: "warn",
      n: String(proposed.length),
      title: `${plural(proposed.length, "change")} to review`,
      short: proposed[0].title.trim() || "Rate change awaiting review",
      name: "Changes to review",
      meta: "Proposed changes to rates and the shop profile",
      figs: [{ k: "Waiting", v: String(proposed.length), s: "proposed" }],
      partsLabel: "",
      parts: [],
      kv: proposed.slice(0, 4).map((c) => [c.title.trim() || "Change", c.asset_type.replace(/_/g, " ")]),
      act: { label: "Review changes", href: R.changes },
    });
  }

  const yours = yoursOf(input.posture);
  if (input.rates && !input.rates.using_governed) {
    const rated = (input.machines ?? []).filter((m) => typeof m.hourly_rate_usd === "number").length;
    const nm = input.machines?.length ?? 0;
    const figs: SheetFig[] = [{ k: "In use", v: rateCardName(input.rates), s: "typical values" }];
    if (yours) figs.push({ k: "Cost inputs yours", v: `${yours.yours} of ${yours.total}`, s: "all costed parts" });
    if (nm) figs.push({ k: "Machine rates", v: `${rated} of ${nm}`, s: "yours" });
    out.push({
      key: "rates",
      icon: "$",
      tone: "yours",
      n: yours ? String(yours.total - yours.yours) : "—",
      title: "Rates are typical",
      short: yours ? `${rateCardName(input.rates)} · ${yours.yours} of ${yours.total} cost inputs yours` : rateCardName(input.rates),
      name: "Rates",
      meta: "Typical values · used on every in-house part",
      figs,
      partsLabel: "",
      parts: [],
      kv: [],
      act: { label: "Set your rates", href: R.rates },
      foot: nm && rated === nm ? "Machine hourly rates are yours; the rest come from the default rate card." : undefined,
    });
  }

  if (input.records && recordCount) {
    const unreviewed = input.records.filter((r) => (r.approval_status ?? "unreviewed") !== "approved");
    const approved = recordCount - unreviewed.length;
    if (unreviewed.length) {
      const byPart = new Map<string, { name: string; n: number }>();
      for (const r of unreviewed) {
        const k = r.mesh_hash ?? r.filename;
        const g = byPart.get(k) ?? { name: r.label || r.filename, n: 0 };
        g.n += 1;
        byPart.set(k, g);
      }
      const groups = [...byPart.entries()].sort((a, b) => b[1].n - a[1].n);
      const parts: InvolvedPart[] = groups.slice(0, 2).map(([k, g]) => ({ name: g.name, note: plural(g.n, "record"), href: k.length >= 32 ? R.part(k) : undefined }));
      if (groups.length > 2) {
        const rest = groups.slice(2).reduce((n, [, g]) => n + g.n, 0);
        parts.push({ name: `${groups.length - 2} more ${groups.length - 2 === 1 ? "part" : "parts"}`, note: plural(rest, "record") });
      }
      out.push({
        key: "review",
        icon: "✓",
        tone: "ok",
        n: `${unreviewed.length}${more}`,
        title: `${unreviewed.length}${more} records not reviewed`,
        short: `${approved} approved`,
        name: "Records",
        meta: "Approval reopens when an outcome changes",
        figs: [
          { k: "Not reviewed", v: `${unreviewed.length}${more}`, s: "records" },
          { k: "Approved", v: String(approved), s: "records" },
        ],
        partsLabel: "By part",
        parts,
        kv: [],
        act: { label: "Review records", href: R.records },
        foot: "Admins approve.",
      });
    }
  }

  if (recordCount && input.actuals === 0) {
    out.push({
      key: "actuals",
      icon: "≈",
      tone: "yours",
      n: "0",
      title: "No actual costs logged",
      short: `0 of ${recordCount}${more} records have a real cost`,
      name: "Actual costs",
      meta: "Real hours and invoices narrow the ranges",
      figs: [
        { k: "Logged", v: "0", s: "jobs" },
        { k: "Ranges", v: "Typical", s: "until real costs exist" },
      ],
      partsLabel: "",
      parts: [],
      kv: [],
      act: { label: "Log actual cost", href: R.actuals },
    });
  }

  return out;
}

export interface MetaLink {
  n: string;
  t: string;
  href?: string;
}

/** The fact line under "Home". A count that hasn't loaded is left out, not shown as 0. */
export function homeFacts(input: HomeInput, queueLen: number | null): MetaLink[] {
  const out: MetaLink[] = [];
  if (queueLen != null) out.push({ n: String(queueLen), t: "need attention" });
  if (input.partsTotal != null) out.push({ n: input.partsTotal.toLocaleString("en-US"), t: input.partsTotal === 1 ? "part" : "parts", href: R.parts });
  if (input.records) out.push({ n: `${input.records.length}${input.recordsMore ? "+" : ""}`, t: input.records.length === 1 && !input.recordsMore ? "record" : "records", href: R.records });
  const nm = machineCount(input.machines);
  if (nm != null) out.push({ n: String(nm), t: nm === 1 ? "machine" : "machines", href: R.shop });
  if (input.changes) {
    const p = input.changes.filter((c) => c.status === "proposed").length;
    out.push({ n: String(p), t: p === 1 ? "change to review" : "changes to review", href: R.changes });
  }
  if (input.actuals != null) out.push({ n: String(input.actuals), t: input.actuals === 1 ? "actual cost" : "actual costs", href: R.actuals });
  const y = yoursOf(input.posture);
  if (y) out.push({ n: `${y.yours} of ${y.total}`, t: "cost inputs yours", href: R.rates });
  return out;
}

export interface RecentRow {
  id: string;
  file: string;
  sub: string;
  time: string;
  href: string;
}

/** One line per recent record: what the engine picked and where the record stands. */
export function recentRows(records: RecordRow[] | null, now: Date = new Date(), n = 8): RecentRow[] {
  return (records ?? []).slice(0, n).map((r) => {
    const way = r.make_now_process ? wayName(r.make_now_process) : "No price";
    const state = r.user_disposition_label
      ? `decided: ${r.user_disposition_label.toLowerCase()}`
      : r.approval_status === "approved"
        ? "approved"
        : r.is_stale
          ? "out of date"
          : "not reviewed";
    return { id: r.id, file: r.label || r.filename, sub: `${way} · ${state}`, time: shortWhen(r.created_at, now), href: R.record(r.id) };
  });
}

export type StepState = "done" | "started" | "needed" | "optional" | "locked" | "loading" | "failed";

export interface SetupStep {
  key: "check" | "machines" | "programs" | "actuals";
  title: string;
  meta: string;
  state: StepState;
  /** progress bar fill, 0–100 */
  pct: number;
  act: { label: string; href: string } | null;
}

export const STEP_CHIP: Record<StepState, { label: string; tone: "ok" | "warn" | "unk" }> = {
  done: { label: "Done", tone: "ok" },
  started: { label: "Started", tone: "unk" },
  needed: { label: "Needed", tone: "warn" },
  optional: { label: "Optional", tone: "unk" },
  locked: { label: "Locked", tone: "unk" },
  loading: { label: "Checking", tone: "unk" },
  failed: { label: "Retry above", tone: "unk" },
};

/**
 * The four Home setup steps in the order they can be done. Programs and actual
 * costs need a checked part first, so they stay Locked until a record exists.
 * `failed` names a source that didn't load (shown as "Couldn't load").
 */
export function setupSteps(input: HomeInput, failed: { records?: boolean; machines?: boolean; programs?: boolean; actuals?: boolean }): SetupStep[] {
  const nr = input.records?.length ?? null;
  const nm = machineCount(input.machines);
  const hasRecord = (nr ?? 0) > 0;
  const recMore = input.recordsMore ? "+" : "";
  const typical = input.rates ? !input.rates.using_governed : null;

  const check: SetupStep =
    nr == null
      ? { key: "check", title: "Check a part", meta: failed.records ? "Couldn't load" : "Checking records", state: failed.records ? "failed" : "loading", pct: 0, act: null }
      : nr > 0
        ? { key: "check", title: "Check a part", meta: `${nr}${recMore} ${nr === 1 && !recMore ? "record" : "records"}`, state: "done", pct: 100, act: { label: "Records", href: R.records } }
        : { key: "check", title: "Check a part", meta: "No records", state: "needed", pct: 0, act: { label: "Check a part", href: R.check } };

  let machines: SetupStep;
  if (nm == null) {
    machines = { key: "machines", title: "Machines and rates", meta: failed.machines ? "Couldn't load" : "Checking machines", state: failed.machines ? "failed" : "loading", pct: 0, act: null };
  } else if (nm === 0) {
    machines = { key: "machines", title: "Machines and rates", meta: "No machines", state: "optional", pct: 0, act: { label: "Add machines", href: `${R.shop}?add=1` } };
  } else if (typical === false) {
    machines = { key: "machines", title: "Machines and rates", meta: `${plural(nm, "machine")} · your rate card`, state: "done", pct: 100, act: { label: "Your shop", href: R.shop } };
  } else {
    machines = { key: "machines", title: "Machines and rates", meta: `${plural(nm, "machine")}${typical ? " · rates typical" : ""}`, state: "started", pct: 50, act: { label: "Your shop", href: R.shop } };
  }

  const locked = (key: "programs" | "actuals", title: string): SetupStep => ({ key, title, meta: "After your first part", state: "locked", pct: 0, act: null });

  let programs: SetupStep;
  if (!hasRecord) programs = nr == null ? { ...locked("programs", "Volume and programs"), meta: failed.records ? "Needs records" : "Checking records", state: failed.records ? "failed" : "loading" } : locked("programs", "Volume and programs");
  else if (input.programs == null) programs = { key: "programs", title: "Volume and programs", meta: failed.programs ? "Couldn't load" : "Checking programs", state: failed.programs ? "failed" : "loading", pct: 0, act: null };
  else {
    const vol = input.withVolume ?? 0;
    programs = {
      key: "programs",
      title: "Volume and programs",
      meta: `${plural(vol, "part")} with a yearly volume · ${plural(input.programs, "program")}`,
      state: input.programs > 0 ? "done" : "optional",
      pct: input.programs > 0 ? 100 : vol > 0 ? 50 : 0,
      act: { label: "Programs", href: R.programs },
    };
  }

  let actuals: SetupStep;
  if (!hasRecord) actuals = nr == null ? { ...locked("actuals", "Actual costs"), meta: failed.records ? "Needs records" : "Checking records", state: failed.records ? "failed" : "loading" } : locked("actuals", "Actual costs");
  else if (input.actuals == null) actuals = { key: "actuals", title: "Actual costs", meta: failed.actuals ? "Couldn't load" : "Checking actual costs", state: failed.actuals ? "failed" : "loading", pct: 0, act: null };
  else
    actuals = {
      key: "actuals",
      title: "Actual costs",
      meta: `${input.actuals} logged`,
      state: input.actuals > 0 ? "done" : "optional",
      pct: input.actuals > 0 ? 100 : 0,
      act: { label: input.actuals > 0 ? "Real costs" : "Log a job", href: R.actuals },
    };

  return [check, machines, programs, actuals];
}
