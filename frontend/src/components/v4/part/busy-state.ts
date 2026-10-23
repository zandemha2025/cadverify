/**
 * What a check shows while ScaleCAD is busy (capacity test D1–D3): one calm state,
 * "ScaleCAD is busy. Checking again in 8 s…", while it asks again by itself, then
 * "Still busy. Your file is kept; try again in a minute." with a button. Busy is
 * about the server, so none of it reads as a file problem or an error.
 * Pure (types and words), for node --test.
 */
import { secondsUntil, type BusyKind, type BusyStep, type BusyWait } from "../../../lib/verify/busy.ts";

/** The waits a check has open now, by request (a session's `busy`). */
export type BusyWaits = Partial<Record<BusyStep, BusyWait>>;

/** A check, or its prices, still refused as busy after the waiting. */
export interface StillBusyState {
  step: BusyStep;
  kind: BusyKind;
  waitedMs: number;
}

export type BusyView =
  | { phase: "waiting"; step: BusyStep; wait: BusyWait }
  | { phase: "still"; still: StillBusyState };

/** The parts of a check session this reads (store.ts `CheckSession`). */
export interface BusySessionLike {
  busy?: BusyWaits | null;
  failure?: { kind: string; step?: BusyStep; busy?: BusyKind; waitedMs?: number } | null;
  result?: { cost?: unknown; costBusy?: { kind: BusyKind; waitedMs: number } | null } | null;
  costRetrying?: boolean;
}

/** The check's own requests come before its 3D view; of those, the one that tries next. */
const ORDER: BusyStep[] = ["probe", "validate", "cost", "preview"];

export function shownWait(waits: BusyWaits | null | undefined): (BusyWait & { step: BusyStep }) | null {
  let best: (BusyWait & { step: BusyStep }) | null = null;
  for (const step of ORDER) {
    const w = waits?.[step];
    if (!w) continue;
    if (step === "preview" && best) break;
    if (!best || w.until < best.until) best = { ...w, step };
  }
  return best;
}

/** The busy state to show for a session, or null when it isn't waiting on a busy server. */
export function busyView(s: BusySessionLike | null | undefined): BusyView | null {
  if (!s) return null;
  const w = shownWait(s.busy);
  const f = s.failure;
  const still = f?.kind === "busy" && f.step && f.busy ? ({ phase: "still", still: { step: f.step, kind: f.busy, waitedMs: f.waitedMs ?? 0 } } as const) : null;
  // The check itself gave up: that is the state, even while its 3D view is still finishing its last wait.
  if (w && !(still && w.step === "preview")) return { phase: "waiting", step: w.step, wait: w };
  if (still) return still;
  const cb = s.result?.costBusy;
  if (cb && !s.result?.cost && !s.costRetrying) return { phase: "still", still: { step: "cost", kind: cb.kind, waitedMs: cb.waitedMs } };
  return null;
}

/**
 * Which run notice the part's sheet shows: "busy" (the one busy state), "panel" (nothing:
 * the progress panel over the sheet shows it), or "other" (the sheet's own: an
 * interruption, prices that didn't finish). While busy it is never "other": a busy
 * server never reads as "Check interrupted" or "Cost didn't finish", seen or under the panel.
 */
export function sheetRunNotice(o: { busy: BusyView | null; panelOpen: boolean; checking: boolean; interrupted: boolean; costOff: boolean; costRetrying: boolean }): "busy" | "panel" | "other" {
  if (o.busy && (o.checking || o.interrupted || o.costOff || o.costRetrying)) return o.panelOpen ? "panel" : "busy";
  return "other";
}

/** A progress step that is waiting on a busy server says this, never "Didn't finish". */
export const WAITING_FOR_ROOM = "Waiting for room";

export const STILL_BUSY_TITLE = "Still busy. Your file is kept; try again in a minute.";

/** "ScaleCAD is busy. Checking again in 8 s…", counting down to the next try ("…now…" while it's out). */
export function busyTitle(view: { step: BusyStep; wait: BusyWait }, now: number): string {
  const s = secondsUntil(view.wait.until, now);
  const when = s > 0 ? `in ${s} s…` : "now…";
  return view.step === "preview" ? `The 3D view is waiting for room. Trying again ${when}` : `ScaleCAD is busy. Checking again ${when}`;
}

function roomLine(kind: BusyKind): string {
  return kind === "org"
    ? "Your organization already has as many checks running as ScaleCAD runs for it at once"
    : "ScaleCAD's servers are full right now";
}

/** The fact line under the countdown: whose room ran out, what waits, and that the file is fine to keep. */
export function busyMeta(view: { step: BusyStep; wait: BusyWait }): string {
  const room = roomLine(view.wait.kind);
  if (view.step === "preview") return `${room}. It's drawn from your file once there's room.`;
  if (view.step === "cost") return `${room}. The process checks are ready; prices start once there's room. This isn't about your file.`;
  return `${room}. This isn't about your file: it stays here and is checked once there's room.`;
}

/** Under "Still busy": how long ScaleCAD kept asking, and what didn't run. */
export function stillBusyMeta(still: StillBusyState): string {
  const mins = Math.max(1, Math.round(still.waitedMs / 60000));
  const asked = `ScaleCAD asked again for ${mins} ${mins === 1 ? "minute" : "minutes"} and had no room.`;
  if (still.step === "cost") return `${asked} The process checks are ready; prices haven't run.`;
  if (still.step === "preview") return `${asked} The 3D view wasn't drawn.`;
  return `${asked} Nothing was checked.`;
}

/** The progress sheet's button while it's hidden (desktop: short, at the stage's corner). */
export function busyReopenLabel(view: BusyView, now: number): string {
  if (view.phase === "still") return "Still busy · Show";
  const s = secondsUntil(view.wait.until, now);
  return s > 0 ? `Busy · checking again in ${s} s` : "Busy · checking again now";
}

/** The same button on a phone, a bar across the screen above the tab bar: the busy state itself. */
export function busyReopenBar(view: BusyView, now: number): string {
  if (view.phase === "still") return view.still.step === "cost" ? "Still busy · prices didn't run · Show" : "Still busy · your file is kept · Show";
  const s = secondsUntil(view.wait.until, now);
  return `ScaleCAD is busy · checking again ${s > 0 ? `in ${s} s` : "now"}`;
}
