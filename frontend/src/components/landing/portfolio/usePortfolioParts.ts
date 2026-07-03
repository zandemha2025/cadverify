"use client";

/**
 * usePortfolioParts — the data hook behind the MRO / portfolio door (D5 FE-5).
 *
 * The portfolio door triages the parts the user ACTUALLY HAS — their real saved
 * should-cost decisions — into exception queues. Like the catalog grid it is
 * built honestly from two real endpoints:
 *
 *   1. `fetchCostDecisions` — the paginated list (part, route, crossover, when).
 *   2. `fetchCostDecision(id)` — the full saved report per row, from which we
 *      derive the SAME `CatalogMetrics` the catalog grid uses (blocked, posture,
 *      lifecycle) plus the crossover inputs the fragility predicate needs. The
 *      decision envelope is kept for the per-part redesign-savings signal.
 *
 * The exception queues, the portfolio pulse KPIs and the ranked savings are all
 * computed (pure, `lib/portfolio`) over the HYDRATED parts only — an un-hydrated
 * row is honestly "still loading", never silently classified. There is no
 * server-side portfolio aggregate yet (the one-call governed rollup is W3 /
 * Phase 3); until then we hydrate client-side rather than invent the numbers.
 *
 * Liveness mirrors useCatalogRows: a `mountedRef` drops writes after unmount and
 * a monotonic `runIdRef` invalidates a superseded load's in-flight fetches so a
 * stale detail response never overwrites a fresh triage.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchCostDecisions,
  fetchCostDecision,
  type CostDecisionSummary,
  type CostDecision,
} from "@/lib/api";
import { deriveCatalogMetrics } from "@/lib/catalog";
import {
  assessPart,
  buildExceptionQueues,
  portfolioPulse,
  rankRedesignSavings,
  type PartSignal,
  type PartExceptions,
  type ExceptionQueue,
  type PortfolioPulse,
  type RedesignSaving,
} from "@/lib/portfolio";

/** page size — a portfolio owner wants a fuller triage sample than the grid. */
const PAGE_LIMIT = 50;
/** max concurrent per-decision detail fetches (kind to the authed proxy). */
const CONCURRENCY = 5;

export type Hydration = "pending" | "ready" | "error";

export interface PortfolioEntry {
  summary: CostDecisionSummary;
  /** the reused catalog-metrics signal, null until hydrated */
  signal: PartSignal | null;
  /** the saved decision envelope (for the redesign-savings signal), null until hydrated */
  decision: CostDecision | null;
  hydration: Hydration;
}

export type ListStatus = "loading" | "error" | "ready";

export interface UsePortfolioParts {
  status: ListStatus;
  error: string | null;
  entries: PortfolioEntry[];
  /** per-part exception assessments over the hydrated parts only */
  assessments: PartExceptions[];
  /** the three ranked exception queues (counts + cohorts) */
  queues: ExceptionQueue[];
  /** the portfolio pulse KPIs (real / derivable numbers only) */
  pulse: PortfolioPulse;
  /** ranked per-part redesign savings (real deltas; no portfolio total) */
  savings: RedesignSaving[];
  /** rows whose detail is still in flight */
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

/** The positive costed order quantities of a report, ascending, deduped. */
function costedQuantities(quantities: readonly number[]): number[] {
  return Array.from(new Set(quantities))
    .filter((q) => q > 0)
    .sort((a, b) => a - b);
}

export function usePortfolioParts(): UsePortfolioParts {
  const [status, setStatus] = useState<ListStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [entries, setEntries] = useState<PortfolioEntry[]>([]);
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

  const stale = useCallback(
    (runId: number) => !mountedRef.current || runId !== runIdRef.current,
    []
  );

  const hydrate = useCallback(
    async (summaries: CostDecisionSummary[], runId: number) => {
      await runPool(summaries, CONCURRENCY, () => stale(runId), async (s) => {
        try {
          const detail = await fetchCostDecision(s.id);
          if (stale(runId)) return;
          const report = detail.result;
          const metrics = deriveCatalogMetrics(report);
          const signal: PartSignal = {
            id: s.id,
            label: s.label || s.filename,
            metrics,
            crossoverQty: report?.decision?.crossover_qty ?? null,
            costedQuantities: costedQuantities(
              report?.estimates?.map((e) => e.quantity) ?? []
            ),
          };
          setEntries((prev) =>
            prev.map((e) =>
              e.summary.id === s.id
                ? { ...e, signal, decision: report?.decision ?? null, hydration: "ready" }
                : e
            )
          );
        } catch {
          if (stale(runId)) return;
          setEntries((prev) =>
            prev.map((e) => (e.summary.id === s.id ? { ...e, hydration: "error" } : e))
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
      setEntries([]);
      try {
        const page = await fetchCostDecisions({ limit: PAGE_LIMIT });
        if (stale(runId)) return;
        const fresh: PortfolioEntry[] = page.cost_decisions.map((summary) => ({
          summary,
          signal: null,
          decision: null,
          hydration: "pending",
        }));
        setEntries(fresh);
        setCursor(page.next_cursor);
        setHasMore(page.has_more);
        setStatus("ready");
        void hydrate(page.cost_decisions, runId);
      } catch (e) {
        if (stale(runId)) return;
        setError(e instanceof Error ? e.message : "Could not load your portfolio");
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
        const more: PortfolioEntry[] = page.cost_decisions.map((summary) => ({
          summary,
          signal: null,
          decision: null,
          hydration: "pending",
        }));
        setEntries((prev) => [...prev, ...more]);
        setCursor(page.next_cursor);
        setHasMore(page.has_more);
        void hydrate(page.cost_decisions, runId);
      })
      .catch((e) => {
        if (stale(runId)) return;
        setError(e instanceof Error ? e.message : "Could not load more parts");
      })
      .finally(() => {
        if (!stale(runId)) setLoadingMore(false);
      });
  }, [cursor, loadingMore, hydrate, stale]);

  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  const assessments = useMemo(
    () =>
      entries
        .filter((e): e is PortfolioEntry & { signal: PartSignal } => e.signal != null)
        .map((e) => assessPart(e.signal)),
    [entries]
  );

  const queues = useMemo(() => buildExceptionQueues(assessments), [assessments]);
  const pulse = useMemo(() => portfolioPulse(assessments), [assessments]);
  const savings = useMemo(
    () =>
      rankRedesignSavings(
        entries
          .filter((e) => e.hydration === "ready" && e.signal)
          .map((e) => ({
            id: e.summary.id,
            label: e.summary.label || e.summary.filename,
            decision: e.decision,
          }))
      ),
    [entries]
  );

  const hydratingCount = entries.reduce(
    (n, e) => (e.hydration === "pending" ? n + 1 : n),
    0
  );

  return {
    status,
    error,
    entries,
    assessments,
    queues,
    pulse,
    savings,
    hydratingCount,
    hasMore,
    loadingMore,
    loadMore,
    retry,
  };
}
