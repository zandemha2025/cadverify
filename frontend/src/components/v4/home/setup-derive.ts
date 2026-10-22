/**
 * Organization setup checklist (board X13): six steps built from the org's own
 * data. A step whose source didn't load is "Unknown", never "To do"; steps that
 * need a checked part stay Locked until one exists.
 */
import { R } from "../routes.ts";
import type { MachineRow, Posture, RateSource } from "./model.ts";
import { machineCount, rateCardName, yoursOf } from "./home-derive.ts";
import { plural } from "./words.ts";

/** Backend floors (groundtruth_service.MIN_REAL_RECORDS, confidence.MIN_RESIDUALS). */
export const RECALIBRATE_MIN = 8;
export const HELD_OUT_MIN = 3;

export type Tone = "done" | "part" | "warn" | "unk" | "lock" | "bad";

export interface Step {
  key: "check" | "machines" | "rates" | "programs" | "actuals" | "team";
  title: string;
  detail: string;
  sub?: string;
  chip: string;
  tone: Tone;
  go?: { label: string; href: string };
}

export interface SetupInput {
  records: number | null;
  parts: number | null;
  machines: MachineRow[] | null;
  rates: RateSource | null;
  posture: Posture | null;
  programs: { programs: number; inProgram: number } | null;
  actuals: number | null;
  members: { email: string; org_role: string; is_active: boolean }[] | null;
  me: string | null;
  failed: Partial<Record<"records" | "machines" | "rates" | "programs" | "actuals" | "members", boolean>>;
}

function names(machines: MachineRow[]): string {
  const n = machines.map((m) => m.name).filter(Boolean);
  if (n.length <= 3) return n.join(", ");
  return `${n.slice(0, 3).join(", ")} and ${n.length - 3} more`;
}

export function setupChecklist(i: SetupInput): Step[] {
  const f = i.failed;
  const hasRecord = (i.records ?? 0) > 0;
  const steps: Step[] = [];

  if (i.records == null) steps.push({ key: "check", title: "Check your first part", detail: f.records ? "Records not loaded" : "Checking records", chip: "Unknown", tone: f.records ? "bad" : "unk" });
  else if (i.records > 0)
    steps.push({ key: "check", title: "Check your first part", detail: [plural(i.records, "record"), i.parts != null ? plural(i.parts, "part") : null].filter(Boolean).join(" · "), chip: "Done", tone: "done", go: { label: "Open records", href: R.records } });
  else steps.push({ key: "check", title: "Check your first part", detail: "Run the sample or upload STEP, STL or IGES", chip: "To do", tone: "warn", go: { label: "Check a part", href: `${R.home}?welcome=1` } });

  const nm = machineCount(i.machines);
  if (nm == null) steps.push({ key: "machines", title: "Add machines and printers", detail: f.machines ? "Machines not loaded" : "Checking machines", chip: "Unknown", tone: f.machines ? "bad" : "unk" });
  else if (nm > 0) steps.push({ key: "machines", title: "Add machines and printers", detail: `${plural(nm, "machine")} · ${names(i.machines!)}`, chip: "Done", tone: "done", go: { label: "Open machines", href: R.shop } });
  else steps.push({ key: "machines", title: "Add machines and printers", detail: "No machines yet · shop fit isn't checked", chip: "To do", tone: "warn", go: { label: "Add machines", href: `${R.shop}?add=1` } });

  const y = yoursOf(i.posture);
  if (!i.rates) steps.push({ key: "rates", title: "Set your rates", detail: f.rates ? "Rates not loaded" : "Checking rates", chip: "Unknown", tone: f.rates ? "bad" : "unk" });
  else {
    const card = rateCardName(i.rates);
    const detail = y ? `${card} · ${y.yours} of ${y.total} cost inputs yours` : card;
    const allRated = Boolean(i.machines && i.machines.length && i.machines.every((m) => typeof m.hourly_rate_usd === "number"));
    if (i.rates.using_governed) steps.push({ key: "rates", title: "Set your rates", detail, chip: "Done", tone: "done", go: { label: "Open rates", href: R.rates } });
    else if (y && y.yours > 0)
      steps.push({ key: "rates", title: "Set your rates", detail, sub: allRated ? "Machine hourly rates are yours. Labor, setup and programming are typical." : undefined, chip: "Partly", tone: "part", go: { label: "Open rates", href: R.rates } });
    else steps.push({ key: "rates", title: "Set your rates", detail, chip: "Typical", tone: "unk", go: { label: "Open rates", href: R.rates } });
  }

  if (i.records == null) steps.push({ key: "programs", title: "Programs and yearly volume", detail: "Needs records", chip: "Unknown", tone: f.records ? "bad" : "unk" });
  else if (!hasRecord) steps.push({ key: "programs", title: "Programs and yearly volume", detail: "After your first checked part", chip: "Locked", tone: "lock" });
  else if (!i.programs) steps.push({ key: "programs", title: "Programs and yearly volume", detail: f.programs ? "Programs not loaded" : "Checking programs", chip: "Unknown", tone: f.programs ? "bad" : "unk" });
  else {
    const notIn = i.parts != null ? Math.max(0, i.parts - i.programs.inProgram) : null;
    const detail = [plural(i.programs.programs, "program"), notIn != null ? `${plural(notIn, "part")} not in a program` : null].filter(Boolean).join(" · ");
    steps.push({ key: "programs", title: "Programs and yearly volume", detail, chip: i.programs.programs > 0 ? "Done" : "Optional", tone: i.programs.programs > 0 ? "done" : "unk", go: { label: "Open programs", href: R.programs } });
  }

  if (i.records == null) steps.push({ key: "actuals", title: "Actual costs", detail: "Needs records", chip: "Unknown", tone: f.records ? "bad" : "unk" });
  else if (!hasRecord) steps.push({ key: "actuals", title: "Actual costs", detail: "After your first checked part", chip: "Locked", tone: "lock" });
  else if (i.actuals == null) steps.push({ key: "actuals", title: "Actual costs", detail: f.actuals ? "Actual costs not loaded" : "Checking actual costs", chip: "Unknown", tone: f.actuals ? "bad" : "unk" });
  else {
    const n = i.actuals;
    steps.push({
      key: "actuals",
      title: "Actual costs",
      detail: `${n} logged · recalibration needs ${RECALIBRATE_MIN} · measured range needs ${HELD_OUT_MIN} held out per method`,
      sub: "Logging works on every plan. Recalibration is pilot only.",
      chip: n >= RECALIBRATE_MIN ? "Done" : n > 0 ? "Partly" : "Optional",
      tone: n >= RECALIBRATE_MIN ? "done" : n > 0 ? "part" : "unk",
      go: { label: "Add actual costs", href: R.actuals },
    });
  }

  if (!i.members) steps.push({ key: "team", title: "Team", detail: f.members ? "Team not loaded" : "Checking team", chip: f.members ? "Unknown" : "Optional", tone: "unk", go: { label: "Invite", href: R.org } });
  else {
    const active = i.members.filter((m) => m.is_active);
    const admins = active.filter((m) => m.org_role === "admin");
    const meAdmin = admins.some((m) => m.email === i.me);
    const adminText = admins.length === 1 && meAdmin ? "you're the only admin" : plural(admins.length, "admin");
    steps.push({ key: "team", title: "Team", detail: `${plural(active.length, "member")} · ${adminText}`, chip: active.length > 1 ? "Done" : "Optional", tone: active.length > 1 ? "done" : "unk", go: { label: "Invite", href: R.org } });
  }
  return steps;
}

/** Header facts: "2 of 6 done", "1 partly done" (or "Nothing required"). */
export function setupFacts(steps: Step[]): { done: number; partly: number; label: string } {
  const done = steps.filter((s) => s.tone === "done").length;
  const partly = steps.filter((s) => s.tone === "part").length;
  return { done, partly, label: `${done} of ${steps.length} steps done` };
}

/** The first step still to do that has an action gets the strong button. */
export function primaryStep(steps: Step[]): string | null {
  return steps.find((s) => s.tone !== "done" && s.go)?.key ?? null;
}
