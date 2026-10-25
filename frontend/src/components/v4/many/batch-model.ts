/**
 * Batch screens' pure logic: status names, progress and ETA lines, the cancel
 * question, item notes and sorting, lane grouping, the new-batch form checks and
 * the manifest template. No React or fetch, so `node --test` runs it.
 */
import type { BatchItem, BatchProgress, UploadProgress } from "@/lib/api/batch";
import type { MakeRow } from "./makeability.ts";
import { LANE_ORDER, laneKey } from "./makeability.ts";

type Tone = "ok" | "warn" | "bad" | "unk";

export const TERMINAL = new Set(["completed", "failed", "cancelled"]);

const BATCH_STATUS: Record<string, [string, Tone]> = {
  pending: ["Queued", "unk"],
  extracting: ["Preparing", "unk"],
  processing: ["Running", "unk"],
  completed: ["Completed", "ok"],
  failed: ["Failed", "bad"],
  cancelled: ["Cancelled", "warn"],
};

export function batchStatus(status: string): { label: string; tone: Tone } {
  const s = BATCH_STATUS[status];
  return s ? { label: s[0], tone: s[1] } : { label: status ? status[0].toUpperCase() + status.slice(1) : "Unknown", tone: "unk" };
}

const ITEM_STATUS: Record<string, [string, Tone]> = {
  pending: ["Pending", "unk"],
  processing: ["Processing", "unk"],
  completed: ["Completed", "ok"],
  failed: ["Failed", "bad"],
  skipped: ["Skipped", "warn"],
};

export function itemStatus(status: string): { label: string; tone: Tone } {
  const s = ITEM_STATUS[status];
  return s ? { label: s[0], tone: s[1] } : { label: status ? status[0].toUpperCase() + status.slice(1) : "Unknown", tone: "unk" };
}

export const ITEM_FILTERS: [string, string][] = [
  ["all", "All"],
  ["pending", "Pending"],
  ["processing", "Processing"],
  ["completed", "Completed"],
  ["failed", "Failed"],
  ["skipped", "Skipped"],
];

/** "7 of 9 checked · 1 failed · 1 waiting" */
export function progressText(p: BatchProgress): string {
  const checked = p.completed_items;
  const bits = [`${checked.toLocaleString("en-US")} of ${p.total_items.toLocaleString("en-US")} checked`];
  if (p.failed_items) bits.push(`${p.failed_items.toLocaleString("en-US")} failed`);
  if (p.skipped_items) bits.push(`${p.skipped_items.toLocaleString("en-US")} skipped`);
  if (p.pending_items && !TERMINAL.has(p.status)) bits.push(`${p.pending_items.toLocaleString("en-US")} waiting`);
  if (p.status === "cancelled" && p.pending_items) bits.push(`${p.pending_items.toLocaleString("en-US")} finishing`);
  return bits.join(" · ");
}

/** Share of items that reached a final state, 0..1. */
export function doneFraction(p: BatchProgress): number {
  if (!p.total_items) return 0;
  return Math.min(1, (p.completed_items + p.failed_items + p.skipped_items) / p.total_items);
}

/**
 * "~6 h 30 min left at 45 parts an hour" from the server's measured pace, or
 * why there's no estimate yet, or "" when it can't be said.
 *
 * The server measures the pace (op-26): nothing until 10 parts or 10 minutes
 * have finished since the run (re)started ("Time left after 10 parts or 10
 * minutes"), then the work done over the last 30 minutes. Not for the last
 * items in flight (the slowest parts finish last: "Last 3 items" instead). An
 * older server without the pace fields falls back to the rate since the start.
 */
export function etaText(p: BatchProgress, now: number = Date.now(), noun: [string, string] = ["item", "items"]): string {
  if (TERMINAL.has(p.status)) return "";
  const done = p.completed_items + p.failed_items + p.skipped_items;
  const left = p.total_items - done;
  if (left <= 0) return "";
  const inFlight = Math.max(1, p.concurrency_limit || 1);
  if (done && left <= inFlight && p.total_items > inFlight) return `Last ${left} ${left === 1 ? noun[0] : noun[1]}`;
  // The server's pace: the work the run's own parts did over its last half hour.
  if (p.pace_per_hour && p.eta_seconds != null && p.eta_seconds > 0) return `${leftWords(p.eta_seconds)} left at ${paceWords(p.pace_per_hour, noun)}`;
  if (p.pace_state === "measuring") return `Time left after 10 ${noun[1]} or 10 minutes`;
  if (p.pace_state === "stalled") return `No ${noun[0]} finished in the last 30 minutes`;
  // The server gives the pace and has none: never a guess from the start time (a re-check's start is hours old).
  if (p.pace_per_hour !== undefined) return "";
  if (!done) return "";
  const started = p.started_at ? new Date(p.started_at).getTime() : NaN;
  if (!Number.isFinite(started)) return "";
  if (done < 3 || done / Math.max(1, p.total_items) < 0.1) return "";
  const elapsed = (now - started) / 1000;
  if (elapsed <= 0) return "";
  const sec = Math.round(left / (done / elapsed));
  if (!Number.isFinite(sec) || sec <= 0) return "";
  return sec < 90 ? `~${sec} s left` : sec < 5400 ? `~${Math.ceil(sec / 60)} min left` : `~${Math.ceil(sec / 3600)} h left`;
}

/** "~40 s", "~43 min", "~2 h 10 min", "~6 h 30 min" (minutes round up; under 3 h to 10 minutes, then to the half hour). */
export function leftWords(sec: number): string {
  if (sec < 90) return `~${Math.max(1, Math.round(sec))} s`;
  if (sec < 5400) return `~${Math.ceil(sec / 60)} min`;
  const step = sec < 3 * 3600 ? 10 : 30;
  let h = Math.floor(sec / 3600);
  let m = Math.round((sec - h * 3600) / (step * 60)) * step;
  if (m === 60) {
    h += 1;
    m = 0;
  }
  return m ? `~${h} h ${m} min` : `~${h} h`;
}

/** "45 parts an hour", "7.5 parts an hour". */
export function paceWords(perHour: number, noun: [string, string] = ["item", "items"]): string {
  const n = perHour >= 10 ? Math.round(perHour) : Math.round(perHour * 10) / 10;
  return `${n.toLocaleString("en-US")} ${n === 1 ? noun[0] : noun[1]} an hour`;
}

/**
 * A run's files counted one way everywhere (op-28): its page, banner, side
 * panel, the work bar, Home and the summary to print. With a parts list,
 * `total` and its split cover the files the list names (the parts the answer
 * and the buckets cover); files it doesn't name are counted apart.
 */
export interface RunCounts {
  total: number;
  checked: number;
  /** Failed or skipped. */
  notChecked: number;
  /** Queued or being checked. */
  toGo: number;
  /** Of those to go, the ones a worker is checking now. */
  checking: number;
  unlisted: number;
  unlistedChecked: number;
  unlistedNotChecked: number;
  unlistedToGo: number;
}

/** The server's counts (GET /batch/{id}/catalog, /batch/{id}, /batches: `run_counts`). */
export interface RunCountsWire {
  total: number;
  checked: number;
  not_checked: number;
  to_go: number;
  checking: number;
  unlisted: number;
  unlisted_checked: number;
  unlisted_not_checked: number;
  unlisted_to_go: number;
}

type CountRow = { item_id: string; bucket: string; status?: string; listed?: boolean };
type CountBoard = { has_list?: boolean; rows: CountRow[]; run_counts?: RunCountsWire | null };

const NO_COUNTS: RunCounts = { total: 0, checked: 0, notChecked: 0, toGo: 0, checking: 0, unlisted: 0, unlistedChecked: 0, unlistedNotChecked: 0, unlistedToGo: 0 };

function fromWire(w: RunCountsWire): RunCounts {
  return {
    total: w.total,
    checked: w.checked,
    notChecked: w.not_checked,
    toGo: w.to_go,
    checking: w.checking ?? 0,
    unlisted: w.unlisted ?? 0,
    unlistedChecked: w.unlisted_checked ?? 0,
    unlistedNotChecked: w.unlisted_not_checked ?? 0,
    unlistedToGo: w.unlisted_to_go ?? 0,
  };
}

/** From the board's rows: a file checked body by body is one file; with a parts list, the files it doesn't name apart. */
function fromRows(rows: readonly CountRow[], hasList: boolean): RunCounts {
  const files = new Map<string, { bucket: string; processing: boolean; listed: boolean }>();
  for (const r of rows) {
    const id = String(r.item_id).split(":")[0];
    const was = files.get(id);
    // A file is still to go while any of its rows is; not checked when its row says so.
    if (was && (was.bucket === "checking" || was.bucket === "not_checked")) continue;
    files.set(id, { bucket: r.bucket, processing: r.status === "processing", listed: !hasList || !!r.listed });
  }
  const c = { ...NO_COUNTS };
  for (const f of files.values()) {
    const state = f.bucket === "checking" ? "ToGo" : f.bucket === "not_checked" ? "NotChecked" : "Checked";
    if (f.listed) {
      c.total += 1;
      if (state === "ToGo") c.toGo += 1;
      else if (state === "NotChecked") c.notChecked += 1;
      else c.checked += 1;
      if (f.processing && state === "ToGo") c.checking += 1;
    } else {
      c.unlisted += 1;
      if (state === "ToGo") c.unlistedToGo += 1;
      else if (state === "NotChecked") c.unlistedNotChecked += 1;
      else c.unlistedChecked += 1;
    }
  }
  return c;
}

/**
 * The run's counts: the server's one breakdown when it gives it (the board's,
 * else the progress read's), else the board's rows, else the progress read's
 * durable item counts. The run page, its side panel, the work bar and Home all
 * read this, so they never disagree.
 */
export function runCounts(
  p: (Pick<BatchProgress, "total_items" | "completed_items" | "failed_items" | "skipped_items"> & { run_counts?: RunCountsWire | null }) | null,
  src?: CountRow[] | CountBoard | null,
): RunCounts {
  const board = src && !Array.isArray(src) ? src : null;
  const rows = Array.isArray(src) ? src : (board?.rows ?? null);
  if (board?.run_counts) return fromWire(board.run_counts);
  if (p?.run_counts) return fromWire(p.run_counts);
  if (board?.has_list && rows?.length) return fromRows(rows, true);
  if (p && p.total_items) {
    const checked = p.completed_items;
    const notChecked = p.failed_items + p.skipped_items;
    return { ...NO_COUNTS, total: p.total_items, checked, notChecked, toGo: Math.max(0, p.total_items - checked - notChecked) };
  }
  return fromRows(rows ?? [], false);
}

const num = (v: number) => v.toLocaleString("en-US");

/** "2 files aren’t on your parts list" */
function unlistedWords(n: number): string {
  return `${num(n)} ${n === 1 ? "file isn’t" : "files aren’t"} on your parts list`;
}

/** "28 of 296 checked · 268 not checked · 2 files aren’t on your parts list" */
export function runCountsLine(c: RunCounts): string {
  const bits = [`${num(c.checked)} of ${num(c.total)} checked`];
  if (c.notChecked) bits.push(`${num(c.notChecked)} not checked`);
  if (c.toGo) bits.push(`${num(c.toGo)} to go`);
  if (c.unlisted) bits.push(unlistedWords(c.unlisted));
  return bits.join(" · ");
}

/** On a stopped or finished run: "2 files that aren’t on your parts list weren’t checked either." */
export function apartLine(c: RunCounts): string | null {
  const k = c.unlistedNotChecked;
  if (!k) return null;
  return `${num(k)} ${k === 1 ? "file that isn’t" : "files that aren’t"} on your parts list ${k === 1 ? "wasn’t" : "weren’t"} checked${c.notChecked ? " either" : ""}.`;
}

/** A finished run's parts on the list that weren't checked: "268 parts weren’t checked" (null when none). */
export function notCheckedLine(c: RunCounts): string | null {
  return c.notChecked ? `${num(c.notChecked)} ${c.notChecked === 1 ? "part wasn’t" : "parts weren’t"} checked` : null;
}

/**
 * The run's line in the work bar, the same wherever it's registered: the head
 * of the run's breakdown (checked of the list's parts; the bar is too narrow
 * for the rest, which the run page and a stopped run's line say), and how far
 * along every file is.
 */
export function runWork(c: RunCounts): { label: string; detail: string; progress: number | null } {
  const all = c.total + c.unlisted;
  const done = c.checked + c.notChecked + c.unlistedChecked + c.unlistedNotChecked;
  return {
    label: `Checking ${num(c.total)} ${c.total === 1 ? "part" : "parts"}`,
    detail: `${num(c.checked)} of ${num(c.total)} checked`,
    progress: all ? done / all : null,
  };
}

/**
 * Home's way back to the newest run, in the run page's own counts:
 * "Stopped · 28 of 298 checked · 270 not checked". A run that checked parts and
 * then stopped is "Stopped"; only one that never checked a part "Didn’t start".
 */
export function lastRunLine(b: Pick<BatchProgress, "total_items" | "completed_items" | "failed_items" | "skipped_items"> & { status: string; run_counts?: RunCountsWire | null }): string {
  const c = runCounts(b);
  const files = c.total + c.unlisted;
  const state =
    b.status === "completed" ? "Finished" : b.status === "cancelled" ? "Cancelled" : b.status === "failed" ? (c.checked + c.unlistedChecked ? "Stopped" : "Didn’t start") : "Running";
  if (state === "Didn’t start" || !files) return `${state} · ${num(files)} ${files === 1 ? "file" : "files"}`;
  return `${state} · ${runCountsLine(c)}`;
}

/**
 * "28 of 296 checked; 268 not checked." (when and why: stopWhy; files not on the list: apartLine).
 * What to do is the stored reason's ("Check the parts again", or "Start a new run with them" when the
 * files are gone) and the banner's button, never said here as well.
 */
export function stoppedLine(c: RunCounts): string {
  const left = c.notChecked + c.toGo;
  return `${num(c.checked)} of ${num(c.total)} checked; ${num(left)} not checked.`;
}

/**
 * When and why a run stopped, from the reason it kept (op-25): "The run
 * stopped at 16:55: its files are no longer stored, …". A run stopped before
 * runs kept a reason says so: "The run stopped at 16:55 before ScaleCAD kept
 * a reason." Never nothing.
 */
export function stopWhy(at: string | null, failureMessage: string | null | undefined): string {
  const when = at ? ` at ${at}` : "";
  const msg = (failureMessage ?? "").trim();
  if (!msg) return `The run stopped${when} before ScaleCAD kept a reason.`;
  const why = (msg.includes(": ") ? msg.slice(msg.indexOf(": ") + 2) : msg).replace(/\.$/, "");
  const lead = why.length > 1 && /[a-z]/.test(why[1]) ? why[0].toLowerCase() + why.slice(1) : why;
  return `The run stopped${when}: ${lead}.`;
}

/** The cancel question's body. Unfinished items include any in progress: the server skips those too. */
export function cancelText(p: BatchProgress | null): string {
  const n = p?.pending_items ?? 0;
  const lead = n > 0 ? `${n.toLocaleString("en-US")} unfinished ${n === 1 ? "item" : "items"} will be skipped, including any in progress.` : "Unfinished items will be skipped.";
  return `${lead} Finished results stay. This can’t be undone.`;
}

/** The analysis id inside an item's analysis_url (/api/v1/analyses/{id}). */
export function analysisIdOf(item: Pick<BatchItem, "analysis_url">): string | null {
  const m = /\/analyses\/([^/?#]+)/.exec(item.analysis_url ?? "");
  return m ? decodeURIComponent(m[1]) : null;
}

export function seconds(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  const s = ms / 1000;
  if (s < 0.1) return "<0.1 s";
  return s < 10 ? `${s.toFixed(1)} s` : s < 90 ? `${Math.round(s)} s` : `${(s / 60).toFixed(1)} min`;
}

const VERDICT: Record<string, string> = { pass: "Pass", issues: "Issues", fail: "Fail" };

/** "Pass · Resin printing, DLP · 2 findings" from the DFM fields, or "—". */
export function resultText(item: BatchItem, procName: (p: string | null | undefined) => string): string {
  if (item.status !== "completed") return "—";
  const bits: string[] = [];
  if (item.verdict) bits.push(VERDICT[item.verdict] ?? item.verdict);
  if (item.best_process) bits.push(procName(item.best_process));
  if (item.issue_count != null) bits.push(`${item.issue_count} ${item.issue_count === 1 ? "finding" : "findings"}`);
  return bits.length ? bits.join(" · ") : "—";
}

export type SortKey = "arrival" | "name" | "time";

/** Sorted copy; arrival keeps the server's order. */
export function sortItems<T extends Pick<BatchItem, "filename" | "duration_ms">>(items: readonly T[], sort: SortKey): T[] {
  if (sort === "arrival") return [...items];
  if (sort === "name") return [...items].sort((a, b) => a.filename.localeCompare(b.filename, "en", { numeric: true }));
  return [...items].sort((a, b) => (b.duration_ms ?? -1) - (a.duration_ms ?? -1));
}

/**
 * Item counts per status filter. Final states come from the progress counters;
 * pending and processing are split only when every item is loaded (the counters
 * don't separate them), otherwise they are null and the filter shows no count.
 */
export function filterCounts(p: BatchProgress | null, loaded: readonly Pick<BatchItem, "status">[], allLoaded: boolean): Record<string, number | null> {
  const fromLoaded = (s: string) => loaded.filter((i) => i.status === s).length;
  const terminal = p ? TERMINAL.has(p.status) && !p.pending_items : false;
  return {
    all: p ? p.total_items : allLoaded ? loaded.length : null,
    pending: terminal ? 0 : allLoaded ? fromLoaded("pending") : null,
    processing: terminal ? 0 : allLoaded ? fromLoaded("processing") : null,
    completed: p ? p.completed_items : allLoaded ? fromLoaded("completed") : null,
    failed: p ? p.failed_items : allLoaded ? fromLoaded("failed") : null,
    skipped: p ? p.skipped_items : allLoaded ? fromLoaded("skipped") : null,
  };
}

export interface LanedItem {
  item: BatchItem;
  bucket: string;
  lane: string;
  row: MakeRow | null;
}

/**
 * Groups finished items into lanes by their part's makeability. A completed item
 * whose analysis isn't the part's latest check (or isn't found) sits in "unknown":
 * never guessed into a bucket.
 */
export function laneItems(items: readonly BatchItem[], lookup: ReadonlyMap<string, { bucket: string; row: MakeRow }> | null): Map<string, LanedItem[]> {
  const out = new Map<string, LanedItem[]>();
  for (const k of LANE_ORDER) out.set(k, []);
  for (const item of items) {
    if (item.status !== "completed") continue;
    const id = analysisIdOf(item);
    const hit = id && lookup ? lookup.get(id) ?? null : null;
    const bucket = hit?.bucket ?? "unknown";
    const lane = laneKey(bucket, hit?.row ?? null);
    if (!out.has(lane)) out.set(lane, []);
    out.get(lane)!.push({ item, bucket, lane, row: hit?.row ?? null });
  }
  return out;
}

/* ------------------------------------------------------------------ */
/*  New batch form                                                     */
/* ------------------------------------------------------------------ */

export const MAX_ZIP_BYTES = 5 * 1024 * 1024 * 1024;

/** Problem with a chosen ZIP, or null when it can be sent. */
export function zipProblem(file: { name: string; size: number }): string | null {
  if (!file.name.toLowerCase().endsWith(".zip")) return "Choose a .zip file.";
  if (file.size > MAX_ZIP_BYTES) return "This ZIP is over 5 GB. Split it into smaller batches.";
  if (file.size === 0) return "This ZIP is empty.";
  return null;
}

/** Files-at-a-time value, or null when it isn't a whole number from 1 to 12. */
export function parseConcurrency(raw: string): number | null {
  if (!/^\d+$/.test(raw.trim())) return null;
  const n = Number(raw.trim());
  return n >= 1 && n <= 12 ? n : null;
}

export function sizeLabel(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Upload stage copy, in the order the upload goes through them. */
export function uploadStageCopy(progress: Pick<UploadProgress, "stage">): string {
  switch (progress.stage) {
    case "checking":
      return "Checking available upload path…";
    case "hashing":
      return "Checking ZIP integrity before upload…";
    case "preparing":
      return "Preparing secure direct upload…";
    case "uploading":
      return "Uploading ZIP directly…";
    case "retrying":
      return "Upload paused for an automatic retry";
    case "completing":
      return "Verifying uploaded parts…";
    case "complete":
      return "ZIP upload complete";
    case "proxying":
      return "Uploading ZIP through the application…";
    case "creating":
      return "Upload complete · Creating batch…";
    default:
      return "Uploading…";
  }
}

export function retryCopy(p: UploadProgress): string | null {
  if (p.stage !== "retrying" || p.partNumber == null || p.nextAttempt == null || p.maxAttempts == null || p.retryDelayMs == null) return null;
  const s = p.retryDelayMs / 1000;
  return `Part ${p.partNumber} hit a temporary error. Retrying automatically in ${s} ${s === 1 ? "second" : "seconds"} (attempt ${p.nextAttempt} of ${p.maxAttempts}).`;
}

/** The manifest the batch reads: one row per file in the ZIP. process_types is a comma list. */
export const MANIFEST_TEMPLATE = "filename,process_types,rule_pack,priority\nbracket.step,\"cnc_3axis,fdm\",,normal\nhousing.stl,,,high\n";
