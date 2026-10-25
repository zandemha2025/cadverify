/**
 * What a check shows while ScaleCAD is busy (capacity test D1–D3): one calm state,
 * "ScaleCAD is busy. Checking again in 8 s…", while it asks again by itself, then
 * "Still busy. Your file is kept; try again in a minute." with a button. Busy is
 * about the server, so none of it reads as a file problem or an error.
 *
 * The same calm state covers a request that stopped on ScaleCAD's side (a gateway
 * timeout, an analysis timeout, any 5xx that isn't busy, or no answer): "That took
 * too long on our side. Your file is kept." with one Try again, never retried by itself.
 * Pure (types and words), for node --test.
 */
import { secondsUntil, serverTrouble, type BusyKind, type BusyStep, type BusyWait } from "../../../lib/verify/busy.ts";

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
  | { phase: "still"; still: StillBusyState }
  /** Stopped on ScaleCAD's side: `status` is the HTTP status (0: no answer came back). */
  | { phase: "server"; step: BusyStep; status: number };

/** The parts of a check session this reads (store.ts `CheckSession`). */
export interface BusySessionLike {
  busy?: BusyWaits | null;
  failure?: { kind: string; step?: BusyStep; busy?: BusyKind; waitedMs?: number; status?: number } | null;
  result?: { cost?: unknown; costError?: string | null; costStatus?: number | null; costBusy?: { kind: BusyKind; waitedMs: number } | null } | null;
  costRetrying?: boolean;
}

/** The request a view is about. */
export function viewStep(view: BusyView): BusyStep {
  return view.phase === "still" ? view.still.step : view.step;
}

/** The check's own requests come before its 3D views; of those, the one that tries next. */
const ORDER: BusyStep[] = ["probe", "validate", "cost", "assembly", "preview", "assembly3d"];
const PICTURE = new Set<BusyStep>(["preview", "assembly3d"]);

export function shownWait(waits: BusyWaits | null | undefined): (BusyWait & { step: BusyStep }) | null {
  let best: (BusyWait & { step: BusyStep }) | null = null;
  for (const step of ORDER) {
    const w = waits?.[step];
    if (!w) continue;
    if (PICTURE.has(step) && best && !PICTURE.has(best.step)) break;
    if (!best || w.until < best.until) best = { ...w, step };
  }
  return best;
}

/** The parts of an assembly's state this reads (store.ts `AssemblyState`). */
export interface AssemblyLike {
  glbUrl?: string | null;
  glbBusy?: { kind: BusyKind; waitedMs: number } | null;
  glbServer?: number | null;
  analysis?: unknown;
  analyzing?: boolean;
  analysisBusy?: { kind: BusyKind; waitedMs: number } | null;
  analysisStatus?: number | null;
  analysisError?: string | null;
}

/**
 * An assembly's two busy states, the same as a part's: the per-part analysis (the
 * sheet) and its 3D view (the stage), each waiting with a countdown, still busy after
 * the bound, or stopped on ScaleCAD's side.
 */
export function assemblyViews(waits: BusyWaits | null | undefined, a: AssemblyLike | null | undefined): { sheet: BusyView | null; stage: BusyView | null } {
  const at = (step: "assembly" | "assembly3d"): BusyView | null => {
    const w = waits?.[step];
    return w ? { phase: "waiting", step, wait: w } : null;
  };
  let sheet = at("assembly");
  if (!sheet && a && !a.analysis && !a.analyzing) {
    if (a.analysisBusy) sheet = { phase: "still", still: { step: "assembly", kind: a.analysisBusy.kind, waitedMs: a.analysisBusy.waitedMs } };
    else if (a.analysisError && serverTrouble(a.analysisStatus)) sheet = { phase: "server", step: "assembly", status: a.analysisStatus! };
  }
  let stage = at("assembly3d");
  if (!stage && a && !a.glbUrl) {
    if (a.glbBusy) stage = { phase: "still", still: { step: "assembly3d", kind: a.glbBusy.kind, waitedMs: a.glbBusy.waitedMs } };
    else if (a.glbServer != null && serverTrouble(a.glbServer)) stage = { phase: "server", step: "assembly3d", status: a.glbServer };
  }
  return { sheet, stage };
}

/** The busy state to show for a session, or null when it isn't waiting on a busy server. */
export function busyView(s: BusySessionLike | null | undefined): BusyView | null {
  if (!s) return null;
  const w = shownWait(s.busy);
  const f = s.failure;
  const still = f?.kind === "busy" && f.step && f.busy ? ({ phase: "still", still: { step: f.step, kind: f.busy, waitedMs: f.waitedMs ?? 0 } } as const) : null;
  const server = f?.kind === "server" && f.step && f.status != null ? ({ phase: "server", step: f.step, status: f.status } as const) : null;
  const stopped = still ?? server;
  // The check itself stopped: that is the state, even while its 3D view is still finishing its last wait.
  if (w && !(stopped && PICTURE.has(w.step))) return { phase: "waiting", step: w.step, wait: w };
  if (stopped) return stopped;
  const r = s.result;
  const cb = r?.costBusy;
  if (cb && !r?.cost && !s.costRetrying) return { phase: "still", still: { step: "cost", kind: cb.kind, waitedMs: cb.waitedMs } };
  if (r && !r.cost && r.costError && !s.costRetrying && serverTrouble(r.costStatus, !!cb)) return { phase: "server", step: "cost", status: r.costStatus! };
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
  return PICTURE.has(view.step) ? `The 3D view is waiting for room. Trying again ${when}` : `ScaleCAD is busy. Checking again ${when}`;
}

function roomLine(kind: BusyKind): string {
  return kind === "org"
    ? "Your organization already has as many checks running as ScaleCAD runs for it at once"
    : "ScaleCAD's servers are full right now";
}

/** The fact line under the countdown: whose room ran out, what waits, and that the file is fine to keep. */
export function busyMeta(view: { step: BusyStep; wait: BusyWait }): string {
  const room = roomLine(view.wait.kind);
  if (PICTURE.has(view.step)) return `${room}. It's drawn from your file once there's room.`;
  if (view.step === "assembly") return `${room}. The product tree is ready; the per-part analysis starts once there's room. This isn't about your file.`;
  if (view.step === "cost") return `${room}. The process checks are ready; prices start once there's room. This isn't about your file.`;
  return `${room}. This isn't about your file: it stays here and is checked once there's room.`;
}

/** Under "Still busy": how long ScaleCAD kept asking, and what didn't run. */
export function stillBusyMeta(still: StillBusyState): string {
  const mins = Math.max(1, Math.round(still.waitedMs / 60000));
  const asked = `ScaleCAD asked again for ${mins} ${mins === 1 ? "minute" : "minutes"} and had no room.`;
  if (still.step === "cost") return `${asked} The process checks are ready; prices haven't run.`;
  if (PICTURE.has(still.step)) return `${asked} The 3D view wasn't drawn.`;
  if (still.step === "assembly") return `${asked} The product tree is ready; the per-part analysis hasn't run.`;
  return `${asked} Nothing was checked.`;
}

/** "That took too long on our side. Your file is kept.": a request that stopped on ScaleCAD's side. */
export function serverTitle(status: number): string {
  if (status === 0) return "ScaleCAD didn't answer. Your file is kept.";
  if (status === 500) return "That didn't finish on our side. Your file is kept.";
  return "That took too long on our side. Your file is kept.";
}

/** Under it: what stopped (with the status, a fact), what didn't run, and that one press runs it again. */
export function serverMeta(step: BusyStep, status: number): string {
  const what = status === 0 ? "No answer came back; check the connection." : `ScaleCAD stopped before answering (${status}).`;
  if (step === "cost") return `${what} The process checks are ready; prices haven't run. Try again prices it once more.`;
  if (PICTURE.has(step)) return `${what} The 3D view wasn't drawn. Try again asks for it once more.`;
  if (step === "assembly") return `${what} The product tree is ready; the per-part analysis hasn't run. Try again runs it once more.`;
  return `${what} Nothing was checked. Try again runs the check once more.`;
}

/** A progress step stopped on ScaleCAD's side, in a few words. */
export function serverStepText(status: number): string {
  return status === 0 ? "No answer from ScaleCAD" : status === 500 ? "Didn’t finish on our side" : "Took too long on our side";
}

/** The progress sheet's button while it's hidden (desktop: short, at the stage's corner). */
export function busyReopenLabel(view: BusyView, now: number): string {
  if (view.phase === "server") return "Stopped on our side · Show";
  if (view.phase === "still") return "Still busy · Show";
  const s = secondsUntil(view.wait.until, now);
  return s > 0 ? `Busy · checking again in ${s} s` : "Busy · checking again now";
}

/** The same button on a phone, a bar across the screen above the tab bar: the busy state itself. */
export function busyReopenBar(view: BusyView, now: number): string {
  if (view.phase === "server") return `${serverStepText(view.status)} · your file is kept · Show`;
  if (view.phase === "still") return view.still.step === "cost" ? "Still busy · prices didn't run · Show" : "Still busy · your file is kept · Show";
  const s = secondsUntil(view.wait.until, now);
  return `ScaleCAD is busy · checking again ${s > 0 ? `in ${s} s` : "now"}`;
}
