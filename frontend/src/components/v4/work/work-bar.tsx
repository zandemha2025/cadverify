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
 * a run started on another device or before a reload shows here too.
 */
import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { listBatches } from "@/lib/api/batch";
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
        const r = await listBatches({ limit: 10 });
        if (!live) return;
        const seen = seenSet();
        for (const b of r.batches as (typeof r.batches[number] & { job_type?: string })[]) {
          if (b.job_type !== "catalog") continue;
          const key = runKey(b.batch_ulid);
          const href = `/app/many/${encodeURIComponent(b.batch_ulid)}`;
          const n = b.total_items;
          const done = b.completed_items + b.failed_items + b.skipped_items;
          const known = items.get(key);
          if (!TERMINAL.has(b.status)) {
            next = 6_000;
            registerWork({ key, href, persist: true, state: "running", label: `Checking ${n || ""} ${n === 1 ? "part" : "parts"}`.replace("  ", " "), detail: n ? `${done} of ${n}` : "Starting", progress: n ? done / n : null });
          } else if (known && known.state === "running" && !seen.has(key)) {
            registerWork({ key, href, persist: true, state: b.status === "completed" ? "done" : "stopped", label: b.status === "completed" ? `${n} ${n === 1 ? "part" : "parts"} checked` : `Run ${b.status}`, detail: b.failed_items ? `${b.failed_items} couldn’t be checked` : "Sorted", progress: 1 });
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
  const shown = all.filter((i) => i.href !== pathname && !pathname.startsWith(`${i.href}/`));
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
