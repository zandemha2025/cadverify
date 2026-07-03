"use client";

/**
 * useCatalogRows — the data hook behind the cost-engineer catalog grid (D5 FE-4).
 *
 * The catalog is a table over the user's REAL saved should-cost decisions. It is
 * built from two real endpoints, honestly:
 *
 *   1. `fetchCostDecisions` — the paginated list. Its columns (part, make-now
 *      route, crossover, when, shared) paint IMMEDIATELY; they are real.
 *   2. `fetchCostDecision(id)` — the full saved report per row. Unit $, provenance
 *      posture, route DFM blockers and the lifecycle state are read from it and
 *      hydrate progressively (bounded concurrency). Each is a real engine field.
 *
 * This client-side hydration is the honest v1: the list endpoint does not carry
 * per-row posture / price, and the ONE-CALL catalog aggregate (posture + findings
 * per row, server-side) lands with the Governed Catalog (Phase 1). Until then we
 * fetch each saved decision on demand rather than invent the columns — a row whose
 * detail fails to load shows its real list fields and an honest error on the rest.
 *
 * Liveness: a `mountedRef` drops any state write after unmount; a monotonic
 * `runIdRef` (bumped at the start of each load effect) invalidates the in-flight
 * fetches of a superseded load (e.g. after Retry), so late detail responses from a
 * stale run never overwrite the fresh grid.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchCostDecisions,
  fetchCostDecision,
  type CostDecisionSummary,
} from "@/lib/api";
import { deriveCatalogMetrics, type CatalogMetrics } from "@/lib/catalog";

/** first page size; a page's rows all hydrate before it is considered settled. */
const PAGE_LIMIT = 30;
/** max concurrent per-decision detail fetches (kind to the authed proxy). */
const CONCURRENCY = 5;

export type Hydration = "pending" | "ready" | "error";

export interface CatalogRow {
  summary: CostDecisionSummary;
  metrics: CatalogMetrics | null;
  hydration: Hydration;
}

export type ListStatus = "loading" | "error" | "ready";

export interface UseCatalogRows {
  status: ListStatus;
  error: string | null;
  rows: CatalogRow[];
  /** rows whose detail is still in flight (their metric cells show skeletons) */
  hydratingCount: number;
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
  retry: () => void;
}

/** Run `worker` over `items` with at most `concurrency` in flight. */
async function runPool<T>(
  items: readonly T[],
  concurrency: number,
  stopped: () => boolean,
  worker: (item: T) => Promise<void>
): Promise<void> {
  let cursor = 0;
  const lanes = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (cursor < items.length) {
      if (stopped()) return;
      const item = items[cursor++];
      await worker(item);
    }
  });
  await Promise.all(lanes);
}

export function useCatalogRows(): UseCatalogRows {
  const [status, setStatus] = useState<ListStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<CatalogRow[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const mountedRef = useRef(true);
  const runIdRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  /** true when this run has been superseded or the component has unmounted. */
  const stale = useCallback((runId: number) => !mountedRef.current || runId !== runIdRef.current, []);

  const hydrate = useCallback(
    async (summaries: CostDecisionSummary[], runId: number) => {
      await runPool(summaries, CONCURRENCY, () => stale(runId), async (s) => {
        try {
          const detail = await fetchCostDecision(s.id);
          if (stale(runId)) return;
          const metrics = deriveCatalogMetrics(detail.result);
          setRows((prev) =>
            prev.map((r) =>
              r.summary.id === s.id ? { ...r, metrics, hydration: "ready" } : r
            )
          );
        } catch {
          if (stale(runId)) return;
          setRows((prev) =>
            prev.map((r) => (r.summary.id === s.id ? { ...r, hydration: "error" } : r))
          );
        }
      });
    },
    [stale]
  );

  const loadFirst = useCallback(
    async (runId: number) => {
      setStatus("loading");
      setError(null);
      setRows([]);
      try {
        const page = await fetchCostDecisions({ limit: PAGE_LIMIT });
        if (stale(runId)) return;
        const fresh: CatalogRow[] = page.cost_decisions.map((summary) => ({
          summary,
          metrics: null,
          hydration: "pending",
        }));
        setRows(fresh);
        setCursor(page.next_cursor);
        setHasMore(page.has_more);
        setStatus("ready");
        void hydrate(page.cost_decisions, runId);
      } catch (e) {
        if (stale(runId)) return;
        setError(e instanceof Error ? e.message : "Could not load your cost catalog");
        setStatus("error");
      }
    },
    [hydrate, stale]
  );

  useEffect(() => {
    const runId = ++runIdRef.current;
    void loadFirst(runId);
  }, [loadFirst, reloadKey]);

  const loadMore = useCallback(() => {
    if (!cursor || loadingMore) return;
    const runId = runIdRef.current;
    setLoadingMore(true);
    fetchCostDecisions({ cursor, limit: PAGE_LIMIT })
      .then((page) => {
        if (stale(runId)) return;
        const more: CatalogRow[] = page.cost_decisions.map((summary) => ({
          summary,
          metrics: null,
          hydration: "pending",
        }));
        setRows((prev) => [...prev, ...more]);
        setCursor(page.next_cursor);
        setHasMore(page.has_more);
        void hydrate(page.cost_decisions, runId);
      })
      .catch((e) => {
        if (stale(runId)) return;
        setError(e instanceof Error ? e.message : "Could not load more decisions");
      })
      .finally(() => {
        if (!stale(runId)) setLoadingMore(false);
      });
  }, [cursor, loadingMore, hydrate, stale]);

  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  const hydratingCount = rows.reduce(
    (n, r) => (r.hydration === "pending" ? n + 1 : n),
    0
  );

  return {
    status,
    error,
    rows,
    hydratingCount,
    hasMore,
    loadingMore,
    loadMore,
    retry,
  };
}
