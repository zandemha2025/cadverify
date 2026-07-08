/**
 * The three front doors (D5 FE-3). CadVerify's three co-equal personas each
 * enter through their own door, with their own hero object and their own first
 * verb (D1 "three real doors, three hero objects, three first verbs"):
 *
 *   part      · "I have a part"     · DROP     · design / mfg engineer
 *   cost      · "I own the numbers" · OVERRIDE · cost / sourcing engineer
 *   portfolio · "I own a portfolio" · TRIAGE   · portfolio / MRO owner
 *
 * This module is PURE logic (no React, no DOM) so the landing router and the
 * door-choice resolution can be unit-tested with `node --test`. The runtime
 * wiring — the localStorage `cv_door` read/write, the first-run chooser UI, the
 * per-door heroes — lives in `components/landing/*`, gated behind
 * `NEXT_PUBLIC_STAGE_UI`.
 *
 * Each door opens a real surface: part upload, governed catalog/cost posture, or
 * portfolio triage.
 */

export type DoorId = "part" | "cost" | "portfolio";

/** localStorage key: the visitor's chosen (persisted) door. */
export const DOOR_STORAGE_KEY = "cv_door";

export interface DoorDef {
  id: DoorId;
  /** the first-run answer this door offers to "Where do you work?" */
  question: string;
  /** the door's first verb — DROP / OVERRIDE / TRIAGE */
  verb: string;
  /** the persona that lives behind it */
  persona: string;
  /** the hero object noun (part · catalog · portfolio) */
  object: string;
  /** one line describing what waits inside */
  blurb: string;
}

export const DOORS: DoorDef[] = [
  {
    id: "part",
    question: "I have a part",
    verb: "DROP",
    persona: "Design / mfg engineer",
    object: "part",
    blurb: "Drop a CAD file — the inspection and the make-vs-buy decision, in minutes.",
  },
  {
    id: "cost",
    question: "I own the numbers",
    verb: "OVERRIDE",
    persona: "Cost / sourcing engineer",
    object: "catalog",
    blurb: "Live in the drivers, rates and calibration — override an assumption, re-cost.",
  },
  {
    id: "portfolio",
    question: "I own a portfolio",
    verb: "TRIAGE",
    persona: "Portfolio / MRO owner",
    object: "portfolio",
    blurb: "Millions of parts — triage the exceptions first, then the savings pipeline.",
  },
];

const DOOR_IDS = new Set<DoorId>(["part", "cost", "portfolio"]);

/** Narrow an arbitrary value to a DoorId, or null when it is not one. */
export function parseDoor(value: string | null | undefined): DoorId | null {
  return value != null && DOOR_IDS.has(value as DoorId) ? (value as DoorId) : null;
}

/** Look up a door by id, falling back to the `part` door (the default front). */
export function doorById(id: DoorId): DoorDef {
  return DOORS.find((d) => d.id === id) ?? DOORS[0];
}

/**
 * Map a recognised persona token to its door. NOTE: the session `role`
 * (analyst / admin / viewer / superadmin) is an RBAC account role, NOT a
 * persona, so it deliberately does not resolve a door — only explicit persona
 * tokens do. Anything unrecognised returns null so the caller falls through to
 * the first-run chooser rather than guessing a door for the user.
 */
const ROLE_DOOR: Record<string, DoorId> = {
  design: "part",
  mfg: "part",
  manufacturing: "part",
  cost: "cost",
  sourcing: "cost",
  buyer: "cost",
  portfolio: "portfolio",
  mro: "portfolio",
};

export function roleToDoor(role: string | null | undefined): DoorId | null {
  if (!role) return null;
  return ROLE_DOOR[role.trim().toLowerCase()] ?? null;
}

/**
 * Resolve the door for an authed app load. Precedence: a persisted choice
 * (`cv_door`) always wins; otherwise a recognised persona `role` maps to a
 * door; otherwise null → show the first-run chooser.
 */
export function resolveDoor(opts: {
  persisted?: string | null;
  role?: string | null;
}): DoorId | null {
  return parseDoor(opts.persisted) ?? roleToDoor(opts.role);
}
