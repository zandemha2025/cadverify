"use client";

/**
 * Work you can leave: a slim bar at the foot of every v4 page for work that
 * keeps going on the server while you do something else, until you open it.
 *
 * Shared. Any screen registers its own item:
 *
 *   registerWork({ key: "check:abc", label: "Checking part.step", detail: "Measured", href, state: "running" })
 *   updateWork("check:abc", { state: "done", detail: "Checked" })
 *   removeWork("check:abc")
 *
 * Items with `persist` survive reloads and other tabs (localStorage). An item
 * hides itself on its own page (`href`), and a finished one stays until it is
 * opened or dismissed. Catalog runs are found on the server (GET /batches), so
 * a run started on another device or before a reload shows here too, and so
 * are big files' checks (GET /checks: a part checked on the worker from its
 * stored upload, part/stored-check.ts).
 */
import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { listBatches } from "@/lib/api/batch";
import { runCounts, runCountsLine, runWork } from "../many/batch-model";
import { API_BASE } from "@/lib/api-base";
import { keptWorkLine, type KeptJobStatus } from "../part/kept-job-model";
import { pendingUploads } from "@/lib/api/part-upload";
import "./work.css";

export type WorkState = "running" | "done" | "stopped";

export interface WorkItem {
  key: string;
  /** "Checking 50 parts", "Checking part.step" */
  label: string;
  /** "12 of 50", "Measured" */
  detail?: string;
  href: string;
  state: WorkState;
  /** 0..1 when known. */
  progress?: number | null;
  /** Keep across reloads and tabs. */
  persist?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Store                                                              */
/* ------------------------------------------------------------------ */

const LS_KEY = "scalecad.work.v1";
const SEEN_KEY = "scalecad.work.seen.v1";
let items = new Map<string, WorkItem>();
const subs = new Set<() => void>();
let loaded = false;

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode or full: the bar still works for this page's life */
  }
}

function load(): void {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  const saved = readJson<WorkItem[]>(LS_KEY, []);
  for (const it of Array.isArray(saved) ? saved : []) if (it && typeof it.key === "string" && typeof it.href === "string") items.set(it.key, it);
}

function emit(): void {
  if (typeof window !== "undefined") writeJson(LS_KEY, [...items.values()].filter((i) => i.persist));
  for (const s of subs) s();
}

export function registerWork(item: WorkItem): void {
  load();
  items = new Map(items);
  items.set(item.key, { ...items.get(item.key), ...item });
  emit();
}

export function updateWork(key: string, patch: Partial<WorkItem>): void {
  load();
  const cur = items.get(key);
  if (!cur) return;
  items = new Map(items);
  items.set(key, { ...cur, ...patch });
  emit();
}

export function removeWork(key: string): void {
  load();
  if (!items.has(key)) return;
  items = new Map(items);
  items.delete(key);
  emit();
}

function seenSet(): Set<string> {
  return new Set(readJson<string[]>(SEEN_KEY, []));
}

/** Marks a finished item opened, so the bar lets it go (and doesn't bring it back from the server). */
export function markWorkSeen(key: string): void {
  const seen = seenSet();
  if (!seen.has(key)) {
    seen.add(key);
    writeJson(SEEN_KEY, [...seen].slice(-200));
  }
  const cur = items.get(key);
  if (cur && cur.state !== "running") removeWork(key);
}

function useWorkItems(): WorkItem[] {
  const [, force] = React.useReducer((x: number) => x + 1, 0);
  React.useEffect(() => {
    load();
    subs.add(force);
    force();
    const onStorage = (e: StorageEvent) => {
      if (e.key !== LS_KEY) return;
      loaded = false;
      items = new Map([...items].filter(([, v]) => !v.persist));
      load();
      force();
    };
    window.addEventListener("storage", onStorage);
    return () => {
      subs.delete(force);
      window.removeEventListener("storage", onStorage);
    };
  }, []);
  return [...items.values()];
}

/* ------------------------------------------------------------------ */
/*  Catalog runs, from the server                                      */
/* ------------------------------------------------------------------ */

export const runKey = (batchId: string) => `catalog:${batchId}`;
const TERMINAL = new Set(["completed", "failed", "cancelled"]);

/** Watches the account's catalog runs: running ones, and finished ones not yet opened. */
function useCatalogRuns(pathname: string) {
  React.useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      let next = 30_000;
      try {
        // A stalled request must not end the watch: give up after 20 s and try again.
        const r = await Promise.race([
          listBatches({ limit: 10 }),
          new Promise<never>((_, rej) => setTimeout(() => rej(new Error("slow")), 20_000)),
        ]);
        if (!live) return;
        const seen = seenSet();
        for (const b of r.batches as (typeof r.batches[number] & { job_type?: string })[]) {
          if (b.job_type !== "catalog") continue;
          const key = runKey(b.batch_ulid);
          const href = `/app/many/${encodeURIComponent(b.batch_ulid)}`;
          const n = b.total_items;
          const known = items.get(key);
          if (!TERMINAL.has(b.status)) {
            next = 6_000;
            // The run page registers the same line from the same counts (many/batch-model runWork).
            const w = runWork(runCounts(b));
            registerWork({ key, href, persist: true, state: "running", label: n ? w.label : "Checking parts", detail: n ? w.detail : "Starting", progress: n ? w.progress : null });
          } else if (known && known.state === "running" && !seen.has(key)) {
            // The run page's own breakdown: the parts list's files, the rest apart (op-28).
            const c = runCounts(b);
            const left = c.notChecked + c.toGo + c.unlistedNotChecked + c.unlistedToGo;
            registerWork({ key, href, persist: true, state: b.status === "completed" ? "done" : "stopped", label: b.status === "completed" ? (left ? "Run finished" : `${n} ${n === 1 ? "part" : "parts"} checked`) : b.status === "failed" ? "Run stopped" : "Run cancelled", detail: left ? runCountsLine(c) : "Sorted", progress: 1 });
          }
        }
      } catch {
        next = 60_000;
      }
      if (live) timer = setTimeout(tick, next);
    };
    void tick();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [pathname]);
}

/* ------------------------------------------------------------------ */
/*  Big files' checks, from the server                                 */
/* ------------------------------------------------------------------ */

const STAGE_WORDS: Record<string, string> = {
  queued: "Waiting for a worker",
  verifying: "Checking the upload",
  unpacking: "Unpacking",
  sizing: "Sizing the check",
  measuring: "Measuring",
  pricing: "Pricing",
};

interface ServerCheckRow {
  check_id: string;
  status: string;
  stage: string;
  progress: number | null;
  filename: string | null;
  part_filename: string | null;
  mesh_hash: string | null;
  geometry_invalid?: string | null;
  error: { message: string } | null;
  /** "kept": a big kept part's re-price or repair (action "recheck" / "repair"), not an upload's check. */
  source?: string;
  action?: string;
  summary?: string | null;
  part_url?: string | null;
  /** A part imported from a share link: where from (never the link). */
  link?: { label: string } | null;
}

/** Same key as part/stored-check.ts, so the tab's own item and the server's are one. */
const storedKey = (checkId: string) => `stored:${checkId}`;
/** An upload this browser started and didn't finish (its tab closed): pick the file again to send the rest. */
export const pausedUploadKey = (uploadId: string) => `upload:${uploadId}`;

function usePausedUploads() {
  React.useEffect(() => {
    const running = [...items.values()].some((i) => i.state === "running" && i.key.startsWith("stored-local:"));
    if (running) return;
    for (const r of pendingUploads()) {
      if (!r.uploadId) continue;
      const key = pausedUploadKey(r.uploadId);
      if (seenSet().has(key)) continue;
      registerWork({ key, href: "/app/check", persist: false, state: "stopped", label: `${r.name}: upload paused`, detail: "Pick the same file again to send the rest" });
    }
  }, []);
}

function useStoredChecks(pathname: string) {
  React.useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      let next = 30_000;
      try {
        const res = await fetch(`${API_BASE}/checks?limit=10`, { cache: "no-store", signal: AbortSignal.timeout(20_000) });
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as { checks: ServerCheckRow[] };
        if (!live) return;
        const seen = seenSet();
        for (const c of body.checks ?? []) {
          const key = storedKey(c.check_id);
          if (seen.has(key)) continue;
          const from = c.source === "link" ? c.link?.label ?? null : null;
          const name = c.part_filename ?? c.filename ?? "part";
          const known = items.get(key);
          if (c.source === "kept") {
            // A big kept part's re-price or repair: its own words, linking to the part.
            const line = keptWorkLine({ ...c, status: c.status as KeptJobStatus["status"], error: c.error ? { code: "", message: c.error.message } : null, part_url: c.part_url ?? null });
            if (line.state === "running") next = 6_000;
            if (line.state === "running" || (known && known.state === "running")) registerWork({ key, persist: true, ...line });
            continue;
          }
          if (c.status === "queued" || c.status === "running") {
            next = 6_000;
            // A link's file is still on its way: "Importing …, Fetching from Dropbox".
            const fetching = !!from && (c.stage === "queued" || c.stage === "fetching");
            registerWork({ key, href: `/app/check?job=${encodeURIComponent(c.check_id)}`, persist: true, state: "running", label: fetching ? (c.part_filename ?? c.filename ? `Importing ${name}` : `Importing from ${from}`) : `Checking ${name}`, detail: fetching ? (c.part_filename ?? c.filename ? `Fetching from ${from}` : "Fetching the file") : STAGE_WORDS[c.stage] ?? "Checking", progress: c.progress });
          } else if (known && known.state === "running") {
            const ok = c.status === "done";
            registerWork({
              key,
              href: ok && c.mesh_hash && !c.geometry_invalid ? `/app/part/${encodeURIComponent(c.mesh_hash)}` : `/app/check?job=${encodeURIComponent(c.check_id)}`,
              persist: true,
              state: ok ? "done" : "stopped",
              label: ok ? `Checked ${name}` : `${name}: not checked`,
              detail: ok ? (c.geometry_invalid ? "Not a closed solid" : "Ready") : c.error?.message?.split(". ")[0] ?? "The check didn’t finish",
              progress: 1,
            });
          }
        }
      } catch {
        next = 60_000;
      }
      if (live) timer = setTimeout(tick, next);
    };
    void tick();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [pathname]);
}

/* ------------------------------------------------------------------ */
/*  The bar                                                            */
/* ------------------------------------------------------------------ */

export function WorkBar() {
  const pathname = usePathname() ?? "";
  const all = useWorkItems();
  useCatalogRuns(pathname);
  useStoredChecks(pathname);
  usePausedUploads();
  const shown = all.filter((i) => {
    const path = i.href.split("?")[0];
    return path !== pathname && !pathname.startsWith(`${path}/`);
  });
  if (!shown.length) return null;
  const first = shown.slice(0, 2);
  return (
    <div className="wk" role="region" aria-label="Work in progress">
      {first.map((i) => (
        <div key={i.key} className={`wk-i ${i.state}`} role="status" aria-live="polite">
          <span className="wk-m" aria-hidden="true">
            {i.state === "running" ? <i /> : i.state === "done" ? "✓" : "!"}
          </span>
          <span className="wk-t">
            <b>{i.label}</b>
            {i.detail ? <small className="num">{i.detail}</small> : null}
          </span>
          {i.state === "running" && i.progress != null ? (
            <span className="wk-pb" aria-hidden="true">
              <i style={{ transform: `scaleX(${Math.max(0.02, Math.min(1, i.progress))})` }} />
            </span>
          ) : null}
          <Link className="btn sm ink" href={i.href} onClick={() => i.state !== "running" && markWorkSeen(i.key)}>
            Open
          </Link>
          {i.state !== "running" ? (
            <button type="button" className="wk-x" aria-label={`Dismiss: ${i.label}`} onClick={() => markWorkSeen(i.key)}>
              <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                <path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            </button>
          ) : null}
        </div>
      ))}
      {shown.length > 2 ? <span className="wk-more">+{shown.length - 2} more</span> : null}
    </div>
  );
}
