"use client";

/**
 * useCatalog — the data hook behind the cost-engineer catalog grid (D5 FE-4).
 *
 * ONE call to the REAL org-scoped `/catalog` endpoint (backend
 * `src/api/catalog.py`) paints the whole page: every cell — route, unit price,
 * route-scoped DFM findings, provenance posture, lifecycle state — is derived
 * SERVER-SIDE and read verbatim. There is no client-side per-row hydration and no
 * client join of `/analyses` + `/cost-decisions`: the lakehouse read surface does
 * it once, org-scoped, so the grid is consistent by construction.
 *
 * Facets (state · route · has-findings) map to the endpoint's REAL query params
 * and are applied server-side BEFORE pagination, so the row count and the page
 * are always mutually consistent. Changing a facet resets to page 1.
 *
 * Liveness: a `mountedRef` drops any state write after unmount; a monotonic
 * `runIdRef` (bumped at the start of each fetch) invalidates a superseded
 * request, so a late response from a stale filter/page never overwrites the grid.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchCatalog,
  type CatalogFacets,
  type CatalogPagination,
} from "@/lib/api";
import { mapCatalogItems, type CatalogItem } from "@/lib/catalog-api";

/** Rows per page — the endpoint caps page_size at 100; 20 is a scannable grid. */
export const CATALOG_PAGE_SIZE = 20;

export type CatalogStatus = "loading" | "error" | "ready";

/** The active facet selection (each maps to a real endpoint query param). */
export interface CatalogFilterState {
  state: "Drafted" | "Costed" | null;
  route: string | null;
  hasFindings: boolean | null;
}

const EMPTY_FILTERS: CatalogFilterState = {
  state: null,
  route: null,
  hasFindings: null,
};

export interface UseCatalog {
  status: CatalogStatus;
  error: string | null;
  rows: CatalogItem[];
  facets: CatalogFacets | null;
  pagination: CatalogPagination | null;
  /** true when the org exceeded the scan cap and some older parts were omitted */
  truncated: boolean;
  filters: CatalogFilterState;
  page: number;
  setStateFacet: (s: "Drafted" | "Costed" | null) => void;
  setRouteFacet: (r: string | null) => void;
  setHasFindingsFacet: (h: boolean | null) => void;
  clearFilters: () => void;
  setPage: (p: number) => void;
  retry: () => void;
}

export function useCatalog(): UseCatalog {
  const [status, setStatus] = useState<CatalogStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<CatalogItem[]>([]);
  const [facets, setFacets] = useState<CatalogFacets | null>(null);
  const [pagination, setPagination] = useState<CatalogPagination | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [filters, setFilters] = useState<CatalogFilterState>(EMPTY_FILTERS);
  const [page, setPageState] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);

  const mountedRef = useRef(true);
  const runIdRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const runId = ++runIdRef.current;
    const stale = () => !mountedRef.current || runId !== runIdRef.current;
    setStatus("loading");
    setError(null);
    fetchCatalog({
      page,
      pageSize: CATALOG_PAGE_SIZE,
      state: filters.state,
      route: filters.route,
      hasFindings: filters.hasFindings,
    })
      .then((res) => {
        if (stale()) return;
        setRows(mapCatalogItems(res.rows));
        setFacets(res.facets);
        setPagination(res.pagination);
        setTruncated(res.truncated);
        setStatus("ready");
      })
      .catch((e) => {
        if (stale()) return;
        setError(e instanceof Error ? e.message : "Could not load your cost catalog");
        setStatus("error");
      });
  }, [page, filters, reloadKey]);

  // A facet change resets to page 1 (the old page may not exist post-filter).
  const setStateFacet = useCallback((s: "Drafted" | "Costed" | null) => {
    setFilters((f) => ({ ...f, state: s }));
    setPageState(1);
  }, []);
  const setRouteFacet = useCallback((r: string | null) => {
    setFilters((f) => ({ ...f, route: r }));
    setPageState(1);
  }, []);
  const setHasFindingsFacet = useCallback((h: boolean | null) => {
    setFilters((f) => ({ ...f, hasFindings: h }));
    setPageState(1);
  }, []);
  const clearFilters = useCallback(() => {
    setFilters(EMPTY_FILTERS);
    setPageState(1);
  }, []);
  const setPage = useCallback((p: number) => setPageState(Math.max(1, p)), []);
  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  return {
    status,
    error,
    rows,
    facets,
    pagination,
    truncated,
    filters,
    page,
    setStateFacet,
    setRouteFacet,
    setHasFindingsFacet,
    clearFilters,
    setPage,
    retry,
  };
}
