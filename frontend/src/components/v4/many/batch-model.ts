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
 * "~40 s left" / "~3 min left" from the rate so far, or "" when it can't be said.
 *
 * Said only when it can be trusted: after a few items and a tenth of the run,
 * and not for the last items in flight (the slowest parts finish last, so the
 * rate so far says nothing about them: "Last 3 items" instead). Minutes round up.
 */
export function etaText(p: BatchProgress, now: number = Date.now(), noun: [string, string] = ["item", "items"]): string {
  if (TERMINAL.has(p.status)) return "";
  const done = p.completed_items + p.failed_items + p.skipped_items;
  const left = p.total_items - done;
  if (!done || left <= 0) return "";
  const inFlight = Math.max(1, p.concurrency_limit || 1);
  if (left <= inFlight && p.total_items > inFlight) return `Last ${left} ${left === 1 ? noun[0] : noun[1]}`;
  // The server's pace: the run's own parts finished over its last half hour.
  if (p.pace_per_hour && p.eta_seconds != null && p.eta_seconds > 0) return `${leftWords(p.eta_seconds)} left at ${paceWords(p.pace_per_hour, noun)}`;
  const started = p.started_at ? new Date(p.started_at).getTime() : NaN;
  if (!Number.isFinite(started)) return "";
  if (done < 3 || done / Math.max(1, p.total_items) < 0.1) return "";
  const elapsed = (now - started) / 1000;
  if (elapsed <= 0) return "";
  const sec = Math.round(left / (done / elapsed));
  if (!Number.isFinite(sec) || sec <= 0) return "";
  return sec < 90 ? `~${sec} s left` : sec < 5400 ? `~${Math.ceil(sec / 60)} min left` : `~${Math.ceil(sec / 3600)} h left`;
}

/** "~40 s", "~43 min", "~6 h", "~6 h 30 min" (minutes round up; hours to the next 10 minutes). */
export function leftWords(sec: number): string {
  if (sec < 90) return `~${Math.max(1, Math.round(sec))} s`;
  if (sec < 5400) return `~${Math.ceil(sec / 60)} min`;
  let h = Math.floor(sec / 3600);
  let m = Math.round((sec - h * 3600) / 600) * 10;
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

/** A run's files counted one way everywhere: checked, not checked (failed or skipped), still to go. */
export interface RunCounts {
  total: number;
  checked: number;
  notChecked: number;
  toGo: number;
}

/**
 * The run's counts from its progress read (durable item states), else from the
 * board's rows (a file checked body by body is one file). The run page, its
 * side panel and the work bar all read this, so they never disagree.
 */
export function runCounts(
  p: Pick<BatchProgress, "total_items" | "completed_items" | "failed_items" | "skipped_items"> | null,
  rows?: { item_id: string; bucket: string }[] | null,
): RunCounts {
  if (p && p.total_items) {
    const checked = p.completed_items;
    const notChecked = p.failed_items + p.skipped_items;
    return { total: p.total_items, checked, notChecked, toGo: Math.max(0, p.total_items - checked - notChecked) };
  }
  const files = new Map<string, string>();
  for (const r of rows ?? []) {
    const id = String(r.item_id).split(":")[0];
    const was = files.get(id);
    // A file is still checking while any of its rows is; not checked when its row says so.
    if (was === "checking" || was === "not_checked") continue;
    files.set(id, r.bucket);
  }
  let checked = 0;
  let notChecked = 0;
  let toGo = 0;
  for (const b of files.values()) {
    if (b === "checking") toGo += 1;
    else if (b === "not_checked") notChecked += 1;
    else checked += 1;
  }
  return { total: files.size, checked, notChecked, toGo };
}

/** "8 of 298 checked · 1 not checked · 289 to go" */
export function runCountsLine(c: RunCounts): string {
  const n = (v: number) => v.toLocaleString("en-US");
  const bits = [`${n(c.checked)} of ${n(c.total)} checked`];
  if (c.notChecked) bits.push(`${n(c.notChecked)} not checked`);
  if (c.toGo) bits.push(`${n(c.toGo)} to go`);
  return bits.join(" · ");
}

/** The run's line in the work bar, the same wherever it's registered: checked of total, and how far along. */
export function runWork(c: RunCounts): { label: string; detail: string; progress: number | null } {
  const n = (v: number) => v.toLocaleString("en-US");
  return {
    label: `Checking ${n(c.total)} ${c.total === 1 ? "part" : "parts"}`,
    detail: `${n(c.checked)} of ${n(c.total)} checked`,
    progress: c.total ? (c.checked + c.notChecked) / c.total : null,
  };
}

/**
 * Home's way back to the newest run, in the run page's own counts:
 * "Stopped · 28 of 298 checked · 270 not checked". A run that checked parts and
 * then stopped is "Stopped"; only one that never checked a part "Didn’t start".
 */
export function lastRunLine(b: Pick<BatchProgress, "total_items" | "completed_items" | "failed_items" | "skipped_items"> & { status: string }): string {
  const c = runCounts(b);
  const state =
    b.status === "completed" ? "Finished" : b.status === "cancelled" ? "Cancelled" : b.status === "failed" ? (c.checked ? "Stopped" : "Didn’t start") : "Running";
  if (state === "Didn’t start" || !c.total) return `${state} · ${c.total.toLocaleString("en-US")} ${c.total === 1 ? "file" : "files"}`;
  return `${state} · ${runCountsLine(c)}`;
}

/** "28 of 298 checked; 270 not checked: the run stopped at 16:55. Check them again." */
export function stoppedLine(c: RunCounts, at: string | null): string {
  const n = (v: number) => v.toLocaleString("en-US");
  const left = c.notChecked + c.toGo;
  return `${n(c.checked)} of ${n(c.total)} checked; ${n(left)} not checked: the run stopped${at ? ` at ${at}` : ""}. Check ${left === 1 ? "it" : "them"} again.`;
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
