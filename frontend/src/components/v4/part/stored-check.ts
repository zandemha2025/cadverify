"use client";

/**
 * A big (or compressed) part's check: upload straight to storage, then the
 * check runs on the worker (POST /checks, GET /checks/{id}); nothing big is
 * parsed in a web request or held in this tab's memory.
 *
 * One module-level store, like the live check's (store.ts), so the check page
 * can be left and come back to, and the work bar shows the same progress on
 * every page: uploading (resumes after a dropped connection; after a reload,
 * picking the same file again sends only the missing parts), then the
 * worker's own stages, then "Ready" linking to the part's page.
 *
 * A part imported from a share link (startLinkCheck) is the same check without
 * the browser's half: the link goes to POST /uploads/from-link, the worker
 * fetches the file ("Fetching from Dropbox") and checks it. The link itself
 * stays in this tab's memory only (for Try again); the server keeps it sealed
 * until its worker reads it.
 */
import * as React from "react";
import { API_BASE } from "@/lib/api-base";
import { forgetResume, PartUploadError, uploadPart, type UploadProgress } from "@/lib/api/part-upload";
import { sizeText } from "@/lib/upload-limit";
import { LINK_FAILURE_TITLE, readLink } from "@/lib/link-import";
import { markWorkSeen, pausedUploadKey, registerWork, removeWork } from "../work/work-bar";
import { R } from "../routes";
import { WAITING_FOR_ROOM_ON_CHECKER, type StoredPhaseName } from "./stored-check-model";

export type StoredPhase = StoredPhaseName;

export interface StoredFailure {
  title: string;
  detail: string;
  code: string | null;
  /** Re-sending the same file can help (a dropped connection, a server error). */
  retry: boolean;
}

export interface StoredCheck {
  id: number;
  file: File | null;
  name: string;
  size: number;
  materialClass: string;
  orientation: string | null;
  phase: StoredPhase;
  /** Bytes hashed or uploaded (of ``size``) while in the browser phases. */
  sent: number;
  resumed: number;
  /** The worker's own fraction for its stage, when it reports one. */
  frac: number | null;
  uploadId: string | null;
  checkId: string | null;
  partName: string | null;
  partBytes: number | null;
  key: string | null;
  memory: { need_bytes: number; budget_bytes: number } | null;
  geometryInvalid: string | null;
  failure: StoredFailure | null;
  startedAt: number;
  finishedAt: number | null;
  opened?: boolean;
  /** A part imported from a share link: the link (this tab's memory only) and its source. */
  link: { url: string; filename: string | null } | null;
  linkLabel: string | null;
  fetchedBytes: number | null;
  /** The worker is waiting for room in its compute budget (the job's `waiting_for_room`). */
  waitingForRoom?: boolean;
}

const checks = new Map<number, StoredCheck>();
const byServer = new Map<string, number>();
const subs = new Set<() => void>();
let nextId = 1;

function emit() {
  for (const s of subs) s();
}

export const storedWorkKey = (checkId: string) => `stored:${checkId}`;
const localWorkKey = (id: number) => `stored-local:${id}`;

const STAGE_WORD: Record<StoredPhase, string> = {
  hashing: "Reading the file",
  uploading: "Uploading",
  finishing: "Finishing the upload",
  starting: "Starting the check",
  queued: "Waiting for a worker",
  fetching: "Fetching the file",
  verifying: "Checking the upload",
  unpacking: "Unpacking",
  sizing: "Sizing the check",
  measuring: "Measuring",
  pricing: "Pricing",
  done: "Ready",
  failed: "Not checked",
};

/** "Importing bracket.step", or "Importing from Google Drive" while the link's file has no name yet. */
export function importingLabel(c: Pick<StoredCheck, "name" | "partName" | "linkLabel">): string {
  const name = c.partName ?? c.name;
  return c.linkLabel && name === unnamedLink(c.linkLabel) ? `Importing from ${c.linkLabel}` : `Importing ${name}`;
}

export const unnamedLink = (label: string) => `File from ${label}`;

export function stageWord(p: StoredPhase, linkLabel?: string | null, waitingForRoom = false): string {
  if (waitingForRoom && p !== "done" && p !== "failed") return WAITING_FOR_ROOM_ON_CHECKER;
  if (p === "fetching" && linkLabel) return `Fetching from ${linkLabel}`;
  return STAGE_WORD[p];
}

function workItem(c: StoredCheck) {
  const key = c.checkId ? storedWorkKey(c.checkId) : localWorkKey(c.id);
  if (c.opened && (c.phase === "done" || c.phase === "failed")) {
    markWorkSeen(key);
    removeWork(localWorkKey(c.id));
    return;
  }
  const name = c.partName ?? c.name;
  const browser = c.phase === "hashing" || c.phase === "uploading" || c.phase === "finishing";
  const fetching = !!c.linkLabel && (c.phase === "starting" || c.phase === "queued" || c.phase === "fetching");
  const href = c.phase === "done" && c.key && !c.geometryInvalid ? R.part(c.key) : c.checkId ? `${R.check}?job=${encodeURIComponent(c.checkId)}` : R.check;
  if (c.phase === "done") {
    registerWork({ key, href, persist: true, state: "done", label: `Checked ${name}`, detail: c.geometryInvalid ? "Not a closed solid" : "Ready", progress: 1 });
  } else if (c.phase === "failed") {
    registerWork({ key, href, persist: true, state: "stopped", label: `${name}: not checked`, detail: c.failure?.title ?? "The check didn’t finish", progress: null });
  } else {
    registerWork({
      key,
      href,
      // Until the server has the check it lives in this tab only; then it outlives the tab.
      persist: !!c.checkId,
      state: "running",
      label: browser ? `Uploading ${name}` : fetching ? importingLabel(c) : `Checking ${name}`,
      detail: browser ? `${sizeText(c.sent)} of ${sizeText(c.size)}` : fetching && !c.waitingForRoom ? (name === unnamedLink(c.linkLabel!) ? "Fetching the file" : `Fetching from ${c.linkLabel}`) : stageWord(c.phase, c.linkLabel, c.waitingForRoom),
      progress: browser ? (c.size ? c.sent / c.size : null) : c.frac,
    });
  }
  // The local item hands over to the server's once the check exists.
  if (c.checkId) removeWork(localWorkKey(c.id));
}

function patch(id: number, p: Partial<StoredCheck>) {
  const cur = checks.get(id);
  if (!cur) return;
  const next = { ...cur, ...p };
  checks.set(id, next);
  if (next.checkId) byServer.set(next.checkId, id);
  workItem(next);
  emit();
}

function failureOf(e: unknown): StoredFailure {
  if (e instanceof PartUploadError) {
    if (e.status === 413) return { title: "Too large to upload", detail: e.message, code: e.code, retry: false };
    if (e.status === 429) return { title: "Uploads are busy for your organization", detail: e.message, code: e.code, retry: true };
    if (e.status === 0) return { title: "The connection dropped", detail: "Pick the same file again to send the rest; the parts already uploaded stay.", code: e.code, retry: true };
    return { title: "The upload stopped", detail: e.message, code: e.code, retry: e.retryable };
  }
  return { title: "The upload stopped", detail: e instanceof Error ? e.message : "Try again.", code: null, retry: true };
}

const SERVER_FAILURE: Record<string, string> = {
  CHECK_TOO_LARGE: "Too large to check on this worker",
  user_validation_cap_exceeded: "Out of checks",
  phone_verification_required: "Verify your phone first",
  DIRECT_UPLOAD_CHECKSUM_MISMATCH: "The upload arrived damaged",
  DIRECT_UPLOAD_SIZE_MISMATCH: "The upload arrived damaged",
  CHECK_UNREADABLE: "We couldn’t read this file",
  CHECK_TIMEOUT: "The check ran out of time",
  CHECK_INTERRUPTED: "The check was interrupted",
  ARCHIVE_MANY_PARTS: "More than one part in the ZIP",
  ARCHIVE_NO_PART: "No part in the ZIP",
  ...LINK_FAILURE_TITLE,
};

interface ServerCheck {
  check_id: string;
  status: "queued" | "running" | "done" | "failed";
  stage: StoredPhase;
  progress: number | null;
  filename: string | null;
  part_filename: string | null;
  size_bytes: number | null;
  part_bytes: number | null;
  mesh_hash: string | null;
  memory: { need_bytes: number; budget_bytes: number } | null;
  geometry_invalid: string | null;
  error: { code: string; message: string } | null;
  source?: string;
  link?: { provider: string; label: string; host: string } | null;
  fetched_bytes?: number | null;
  /** The worker is waiting for room in its compute budget (or sent the check back to the queue to wait):
   *  true only while queued or running; and how often it went back to wait (0 if never). */
  waiting_for_room?: boolean | null;
  requeued_for_room?: number | null;
}

/** A link's fetch that stopped for a passing reason: the same link again can work. */
const LINK_RETRY = new Set(["LINK_TIMEOUT", "LINK_CONNECT_FAILED", "LINK_PROVIDER_ERROR", "LINK_RATE_LIMITED", "LINK_FETCH_FAILED", "LINK_DISK"]);

function fromServer(s: ServerCheck): Partial<StoredCheck> {
  const phase: StoredPhase = s.status === "done" ? "done" : s.status === "failed" ? "failed" : (s.stage ?? "queued");
  const link = s.source === "link" && s.link ? s.link : null;
  return {
    // A link's name is known once fetched (or from the link itself).
    ...(link ? { linkLabel: link.label, fetchedBytes: s.fetched_bytes ?? null, ...(s.filename ? { name: s.filename } : {}), ...(s.size_bytes ? { size: s.size_bytes } : {}) } : {}),
    phase,
    frac: s.progress ?? null,
    partName: s.part_filename,
    partBytes: s.part_bytes,
    key: s.mesh_hash,
    memory: s.memory ? { need_bytes: s.memory.need_bytes, budget_bytes: s.memory.budget_bytes } : null,
    geometryInvalid: s.geometry_invalid ?? null,
    waitingForRoom: !!s.waiting_for_room && s.status !== "done" && s.status !== "failed",
    failure: s.status === "failed" && s.error ? { title: SERVER_FAILURE[s.error.code] ?? "The check didn’t finish", detail: s.error.message, code: s.error.code, retry: s.error.code === "CHECK_FAILED" || s.error.code === "CHECK_INTERRUPTED" || LINK_RETRY.has(s.error.code) } : null,
    finishedAt: s.status === "done" || s.status === "failed" ? Date.now() : null,
  };
}

async function readCheck(checkId: string): Promise<ServerCheck> {
  const res = await fetch(`${API_BASE}/checks/${encodeURIComponent(checkId)}`, { cache: "no-store", signal: AbortSignal.timeout(15_000) });
  if (!res.ok) throw new Error(`check ${res.status}`);
  return (await res.json()) as ServerCheck;
}

async function follow(id: number) {
  for (let misses = 0; ; ) {
    const c = checks.get(id);
    if (!c?.checkId || c.phase === "done" || c.phase === "failed") return;
    try {
      const s = await readCheck(c.checkId);
      misses = 0;
      patch(id, fromServer(s));
      if (s.status === "done" || s.status === "failed") {
        window.dispatchEvent(new Event("proofshape:usage-changed"));
        return;
      }
    } catch {
      // A slow or dropped poll never ends the watch; the check runs on the server regardless.
      misses += 1;
    }
    await new Promise((r) => setTimeout(r, misses ? Math.min(30_000, 3000 * misses) : 2000));
  }
}

async function run(id: number) {
  const c0 = checks.get(id);
  if (!c0?.file) return;
  const file = c0.file;
  let uploadId: string;
  let resumeKey: string;
  try {
    const up = await uploadPart(file, (p: UploadProgress) => patch(id, { phase: p.phase, sent: p.done, resumed: p.resumed ?? 0 }));
    uploadId = up.uploadId;
    resumeKey = up.resumeKey;
    removeWork(pausedUploadKey(up.uploadId));
  } catch (e) {
    patch(id, { phase: "failed", failure: failureOf(e), finishedAt: Date.now() });
    return;
  }
  patch(id, { phase: "starting", uploadId, sent: file.size });
  try {
    const res = await fetch(`${API_BASE}/checks`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ direct_upload_id: uploadId, material_class: checks.get(id)?.materialClass ?? c0.materialClass, orientation: c0.orientation ?? undefined }),
    });
    const body = (await res.json().catch(() => null)) as ServerCheck & { detail?: { code?: string; message?: string }; code?: string; message?: string };
    if (!res.ok || !body?.check_id) {
      // The API answers {code, message} at the top level, or under detail.
      const d = body?.detail ?? (body ? { code: body.code, message: body.message } : undefined);
      patch(id, { phase: "failed", finishedAt: Date.now(), failure: { title: "The check didn’t start", detail: d?.message ?? `The server answered ${res.status}.`, code: d?.code ?? null, retry: res.status >= 500 } });
      return;
    }
    forgetResume(resumeKey);
    patch(id, { checkId: body.check_id, ...fromServer(body) });
  } catch {
    patch(id, { phase: "failed", finishedAt: Date.now(), failure: { title: "The check didn’t start", detail: "The server couldn’t be reached. The file is uploaded; try again to start its check.", code: "network", retry: true } });
    return;
  }
  void follow(id);
}

function linkFailure(status: number, d: { code?: string; message?: string } | undefined): StoredFailure {
  const code = d?.code ?? null;
  const detail = d?.message ?? `The server answered ${status}.`;
  if (status === 429) return { title: "Uploads are busy for your organization", detail, code, retry: true };
  if (status === 422) return { title: "Can’t import this link", detail, code, retry: false };
  if (status === 403) return { title: code === "LINK_IMPORT_OFF" ? "Import from a link is off" : "The check didn’t start", detail, code, retry: false };
  return { title: "The check didn’t start", detail, code, retry: status >= 500 };
}

async function runLink(id: number) {
  const c0 = checks.get(id);
  if (!c0?.link) return;
  try {
    const res = await fetch(`${API_BASE}/uploads/from-link`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url: c0.link.url, filename: c0.link.filename ?? undefined, material_class: c0.materialClass, orientation: c0.orientation ?? undefined }),
    });
    const body = (await res.json().catch(() => null)) as ServerCheck & { detail?: { code?: string; message?: string }; code?: string; message?: string };
    if (!res.ok || !body?.check_id) {
      const d = body?.detail ?? (body ? { code: body.code, message: body.message } : undefined);
      patch(id, { phase: "failed", finishedAt: Date.now(), failure: linkFailure(res.status, d) });
      return;
    }
    patch(id, { checkId: body.check_id, ...fromServer(body) });
  } catch {
    patch(id, { phase: "failed", finishedAt: Date.now(), failure: { title: "The check didn’t start", detail: "The server couldn’t be reached. Try again.", code: "network", retry: true } });
    return;
  }
  void follow(id);
}

/**
 * Import the part a share link points at and check it on the worker. The link
 * is read here only to name its source; the server applies the rules.
 */
export function startLinkCheck(url: string, opts: { filename?: string | null; materialClass?: string; orientation?: string | null } = {}): number {
  const id = nextId++;
  const read = readLink(url);
  const label = read.ok ? read.label : "the link";
  const name = opts.filename?.trim() || (read.ok ? read.nameHint : null) || unnamedLink(label);
  checks.set(id, {
    id,
    file: null,
    name,
    size: 0,
    materialClass: opts.materialClass ?? "polymer",
    orientation: opts.orientation ?? null,
    phase: "starting",
    sent: 0,
    resumed: 0,
    frac: null,
    uploadId: null,
    checkId: null,
    partName: null,
    partBytes: null,
    key: null,
    memory: null,
    geometryInvalid: null,
    failure: null,
    startedAt: Date.now(),
    finishedAt: null,
    link: { url: url.trim(), filename: opts.filename?.trim() || null },
    linkLabel: label,
    fetchedBytes: null,
  });
  workItem(checks.get(id)!);
  emit();
  void runLink(id);
  return id;
}

/** Upload ``file`` and check it on the worker. Returns the id the pages subscribe to. */
export function startStoredCheck(file: File, opts: { materialClass?: string; orientation?: string | null } = {}): number {
  const id = nextId++;
  checks.set(id, {
    id,
    file,
    name: file.name,
    size: file.size,
    materialClass: opts.materialClass ?? "polymer",
    orientation: opts.orientation ?? null,
    phase: "hashing",
    sent: 0,
    resumed: 0,
    frac: null,
    uploadId: null,
    checkId: null,
    partName: null,
    partBytes: null,
    key: null,
    memory: null,
    geometryInvalid: null,
    failure: null,
    startedAt: Date.now(),
    finishedAt: null,
    link: null,
    linkLabel: null,
    fetchedBytes: null,
  });
  workItem(checks.get(id)!);
  emit();
  void run(id);
  return id;
}

/** Follow a check already running on the server (opened from the work bar, another tab, a reload). */
export function followServerCheck(checkId: string): number {
  const known = byServer.get(checkId);
  if (known != null) return known;
  const id = nextId++;
  checks.set(id, {
    id,
    file: null,
    name: "Part",
    size: 0,
    materialClass: "polymer",
    orientation: null,
    phase: "queued",
    sent: 0,
    resumed: 0,
    frac: null,
    uploadId: null,
    checkId,
    partName: null,
    partBytes: null,
    key: null,
    memory: null,
    geometryInvalid: null,
    failure: null,
    startedAt: Date.now(),
    finishedAt: null,
    link: null,
    linkLabel: null,
    fetchedBytes: null,
  });
  byServer.set(checkId, id);
  void readCheck(checkId)
    .then((s) => patch(id, { name: s.filename ?? (s.link ? unnamedLink(s.link.label) : "Part"), size: s.size_bytes ?? 0, sent: s.size_bytes ?? 0, ...fromServer(s) }))
    .catch(() => undefined)
    .finally(() => void follow(id));
  emit();
  return id;
}

/** The same file (or link) and options again, after a dropped upload or a server error. */
export function retryStoredCheck(id: number, file?: File, filename?: string | null): number | null {
  const c = checks.get(id);
  if (c?.link && !file) return startLinkCheck(c.link.url, { filename: filename ?? c.link.filename, materialClass: c.materialClass, orientation: c.orientation });
  const f = file ?? c?.file;
  if (!c || !f) return null;
  return startStoredCheck(f, { materialClass: c.materialClass, orientation: c.orientation });
}

/** The material the check prices in; it can change until the check starts (the upload runs first). */
export function setStoredMaterial(id: number, materialClass: string): boolean {
  const c = checks.get(id);
  if (!c || c.checkId || c.phase === "failed" || c.phase === "done") return false;
  patch(id, { materialClass });
  return true;
}

export function markStoredOpened(id: number) {
  const c = checks.get(id);
  if (!c || c.opened || (c.phase !== "done" && c.phase !== "failed")) return;
  checks.set(id, { ...c, opened: true });
  if (c.checkId) markWorkSeen(storedWorkKey(c.checkId));
  markWorkSeen(localWorkKey(id));
  emit();
}

export function getStoredCheck(id: number | null): StoredCheck | null {
  return id == null ? null : checks.get(id) ?? null;
}

export function useStoredCheck(id: number | null): StoredCheck | null {
  return React.useSyncExternalStore(
    (l) => {
      subs.add(l);
      return () => subs.delete(l);
    },
    () => getStoredCheck(id),
    () => null,
  );
}
