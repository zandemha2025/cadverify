/**
 * What a big file's check shows, step by step, from the real state: the
 * browser's upload (or, for a part imported from a share link, the worker's
 * fetch), then the worker's stages (``stored_check_tasks``). Pure (no React,
 * no fetch) so it runs under node --test.
 */
import { sizeText } from "../../../lib/upload-limit.ts";

export type StoredPhaseName =
  | "hashing"
  | "uploading"
  | "finishing"
  | "starting"
  | "queued"
  | "fetching"
  | "verifying"
  | "unpacking"
  | "sizing"
  | "measuring"
  | "pricing"
  | "done"
  | "failed";

export interface StoredStateIn {
  name: string;
  size: number;
  phase: StoredPhaseName;
  sent: number;
  resumed: number;
  frac: number | null;
  checkId: string | null;
  partName: string | null;
  partBytes: number | null;
  memory: { need_bytes: number; budget_bytes: number } | null;
  geometryInvalid: string | null;
  failure: { title: string; detail: string; code: string | null } | null;
  /** A part imported from a share link: where from ("Dropbox"), and the bytes fetched. */
  linkLabel?: string | null;
  fetchedBytes?: number | null;
}

export type StepState = "done" | "now" | "wait" | "bad" | "skip";
export interface StoredStep {
  key: "upload" | "fetch" | "verify" | "unpack" | "size" | "measure" | "price";
  t: string;
  d: string;
  state: StepState;
}

const ORDER: StoredPhaseName[] = ["hashing", "uploading", "finishing", "starting", "queued", "fetching", "verifying", "unpacking", "sizing", "measuring", "pricing", "done"];
const STEP_OF: Record<StoredPhaseName, StoredStep["key"]> = {
  hashing: "upload",
  uploading: "upload",
  finishing: "upload",
  starting: "verify",
  queued: "verify",
  fetching: "fetch",
  verifying: "verify",
  unpacking: "unpack",
  sizing: "size",
  measuring: "measure",
  pricing: "price",
  done: "price",
  failed: "upload",
};

export function compressed(name: string): boolean {
  const n = name.toLowerCase();
  return n.endsWith(".gz") || n.endsWith(".zip");
}

/** Which step a server failure belongs to, from its code. */
export function failedStep(code: string | null, uploadedToServer: boolean, link = false): StoredStep["key"] {
  const c = code ?? "";
  if (link && (!uploadedToServer || c.startsWith("LINK_") || c.startsWith("DIRECT_UPLOAD_") || c === "UPLOAD_GONE")) return "fetch";
  if (!uploadedToServer) return "upload";
  if (c.startsWith("DIRECT_UPLOAD_") || c === "UPLOAD_GONE") return "verify";
  if (c.startsWith("ARCHIVE_")) return "unpack";
  if (c === "CHECK_TOO_LARGE") return "size";
  return "measure";
}

function pct(f: number): string {
  return `${Math.max(0, Math.min(100, Math.round(f * 100)))}%`;
}

export function storedSteps(c: StoredStateIn): StoredStep[] {
  const link = c.linkLabel != null;
  const zipped = compressed(c.name);
  const failed = c.phase === "failed";
  const badKey = failed ? failedStep(c.failure?.code ?? null, !!c.checkId, link) : null;
  // A link's fetch takes the file's size and SHA-256 as it streams: one step for both.
  const atKey = failed ? badKey! : link && (c.phase === "starting" || c.phase === "queued" || c.phase === "fetching") ? "fetch" : STEP_OF[c.phase];
  const keys: StoredStep["key"][] = [...(link ? (["fetch"] as const) : (["upload", "verify"] as const)), ...(zipped ? (["unpack"] as const) : []), "size", "measure", "price"];
  const at = keys.indexOf(atKey);
  const stateOf = (k: StoredStep["key"]): StepState => {
    const i = keys.indexOf(k);
    if (c.phase === "done") return k === "price" && c.geometryInvalid ? "skip" : "done";
    if (failed) return i < at ? "done" : i === at ? "bad" : "wait";
    return i < at ? "done" : i === at ? "now" : "wait";
  };
  const steps: StoredStep[] = [];
  const st = (key: StoredStep["key"], t: string, d: string) => steps.push({ key, t, d, state: stateOf(key) });

  if (link) {
    const f = stateOf("fetch");
    st(
      "fetch",
      `From ${c.linkLabel}`,
      f === "bad"
        ? c.failure?.detail ?? "The file didn’t arrive."
        : f === "done"
          ? `${c.fetchedBytes ? `${sizeText(c.fetchedBytes)} fetched` : "Fetched"} · its SHA-256 taken as it arrived`
          : c.phase === "fetching"
            ? `Fetching on the server${c.fetchedBytes ? ` · ${sizeText(c.fetchedBytes)}` : ""} · nothing downloads to this browser`
            : c.phase === "starting"
              ? "Sending the link"
              : "Waiting for a worker",
    );
  }
  const up = link ? null : stateOf("upload");
  if (up) st(
    "upload",
    "Upload",
    up === "bad"
      ? c.failure?.detail ?? "The upload stopped."
      : up === "done"
        ? `${sizeText(c.size)} uploaded`
        : c.phase === "hashing"
          ? `Reading the file for its fingerprint · ${pct(c.size ? c.sent / c.size : 0)}`
          : c.phase === "finishing"
            ? "Joining the parts in storage"
            : `${sizeText(c.sent)} of ${sizeText(c.size)}${c.resumed ? ` · ${c.resumed} ${c.resumed === 1 ? "part was" : "parts were"} already there` : ""} · resumes if the connection drops`,
  );
  const v = link ? null : stateOf("verify");
  if (v) st(
    "verify",
    "Fingerprint",
    v === "bad" ? c.failure?.detail ?? "The upload didn’t match." : v === "done" ? "Matches the file this browser sent" : c.phase === "queued" || c.phase === "starting" ? "Waiting for a worker" : "The server reads the whole file and checks its SHA-256",
  );
  if (zipped) {
    const u = stateOf("unpack");
    st(
      "unpack",
      "Unpack",
      u === "bad" ? c.failure?.detail ?? "It couldn’t be unpacked." : u === "done" && c.partName ? `${c.partName}${c.partBytes ? ` · ${sizeText(c.partBytes)}` : ""}` : `${c.name} on the worker, size and ratio limits checked as it goes`,
    );
  }
  const s = stateOf("size");
  st(
    "size",
    "Memory",
    s === "bad"
      ? c.failure?.detail ?? "Too large to check."
      : s === "done" && c.memory
        ? `About ${sizeText(c.memory.need_bytes)} of ${sizeText(c.memory.budget_bytes)} this worker has for one check`
        : "Estimating what the check needs before it starts",
  );
  const m = stateOf("measure");
  st(
    "measure",
    "Measure",
    m === "bad" ? c.failure?.detail ?? "The check didn’t finish." : m === "done" ? "Geometry, walls and every process measured" : "Geometry, walls, holes and every process, on the worker",
  );
  const p = stateOf("price");
  st(
    "price",
    "Price",
    p === "skip" ? `Not a closed solid, so nothing was priced: ${c.geometryInvalid}` : p === "done" ? "Priced at your quantities on your machines" : "Cost at your quantities, on your machines",
  );
  return steps;
}

/** Overall fraction for a progress bar: the upload is most of the wait in a browser. */
export function overallFraction(c: StoredStateIn): number | null {
  if (c.phase === "done") return 1;
  if (c.phase === "failed") return null;
  if (c.linkLabel != null && (c.phase === "starting" || c.phase === "queued")) return 0.03;
  // A link's fetch is most of the wait before the check: up to 0.6, by the worker's own fraction.
  if (c.linkLabel != null && c.phase === "fetching") return 0.05 + 0.55 * (c.frac ?? 0);
  const i = ORDER.indexOf(c.phase);
  if (c.phase === "hashing") return 0.05 * (c.size ? c.sent / c.size : 0);
  if (c.phase === "uploading") return 0.05 + 0.6 * (c.size ? c.sent / c.size : 0);
  return Math.min(0.98, 0.65 + (0.33 * (i - 2)) / (ORDER.length - 3) + (c.frac ? 0.03 * c.frac : 0));
}
