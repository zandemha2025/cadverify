"use client";

/**
 * PARTS CATALOG — the org-scoped parts×decisions grid, real GET /api/v1/catalog.
 * "Every part the org has asked about", unified into one grid: recommended route,
 * unit cost (withheld on a blocked route), and route-scoped DFM findings — every
 * cell straight from the engine or honestly absent.
 *
 * REUSE, don't rewrite: the wired client `fetchCatalog` (@/lib/api) and the pure,
 * unit-tested mapper `mapCatalogItems` (@/lib/catalog-api) already own the fetch +
 * snake→camel reshape for exactly this endpoint. This screen is only the light-
 * instrument render layer + append pagination (the records-screen pattern) + the
 * design's facets/search/saved-views/empty states.
 *
 * HONESTY: geometry previews are WITHHELD — production serves no org-scoped part
 * mesh to the product, so a neutral glyph stands in and no shape is invented. A
 * DFM-blocked route shows no price; an un-analyzed part shows no findings; the
 * cost band is an assumption (validated=false, n=0) so it renders HATCHED with an
 * ○ MODEL marker, never as measured. The full part-standing page is wired from
 * the selected catalog row.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchCatalog, type CatalogFacets, type CatalogPagination } from "@/lib/api";
import { mapCatalogItems, stateFacetCount, type CatalogItem } from "@/lib/catalog-api";
import { setSelectedPart } from "@/lib/verify/part-selection";
import { C, MONO, USD, NUM, procLabel } from "@/lib/verify/tokens";
import {
  Kicker,
  ProvDot,
  GhostButton,
  EmptyState,
  Spinner,
  ConfidenceBand,
} from "./primitives";
import { LibraryOnboard } from "./library-onboard";

// The endpoint caps page_size at 100; 48 keeps the "one grid" feel of the design
// while real pagination stays honest for a large org (Load more appends pages).
const PAGE = 48;

// The single-select facet key encodes which real endpoint filter it maps to.
type FacetKey = "all" | "state:Costed" | "state:Drafted" | "findings:true" | "findings:false";

function facetQuery(f: FacetKey): {
  state?: "Drafted" | "Costed" | null;
  hasFindings?: boolean | null;
} {
  if (f === "state:Costed") return { state: "Costed" };
  if (f === "state:Drafted") return { state: "Drafted" };
  if (f === "findings:true") return { hasFindings: true };
  if (f === "findings:false") return { hasFindings: false };
  return {};
}

interface CardStatus {
  tag: string;
  color: string;
}

/** Derive the card's status tag from REAL fields only — never an invented standing. */
function cardStatus(item: CatalogItem): CardStatus {
  const uc = item.unitCost;
  if (uc?.withheld) return { tag: "ROUTE BLOCKED", color: C.fail };
  if (item.lifecycleState === "Costed") {
    if (uc?.usd != null) return { tag: "COSTED", color: C.pass };
    // A costed artifact with no priced estimate (e.g. geometry invalid).
    return { tag: "COSTED · NO PRICE", color: C.cond };
  }
  return { tag: "DRAFTED · DFM", color: C.cond };
}

function costText(item: CatalogItem): string {
  const uc = item.unitCost;
  if (uc?.withheld) return "withheld";
  if (uc?.usd != null) return USD(uc.usd);
  return "—";
}

function routeText(item: CatalogItem): string {
  if (!item.routeProcess) return "no recommended route";
  const mat = item.routeMaterial ? ` · ${item.routeMaterial}` : "";
  const qty = item.unitCost?.qty != null ? ` · qty ${NUM(item.unitCost.qty)}` : "";
  return `${procLabel(item.routeProcess)}${mat}${qty}`;
}

function findingsText(item: CatalogItem): string {
  const f = item.findings;
  if (f == null) return "DFM not run · findings unknown";
  if (f.total === 0) return "0 findings on route";
  const crit = f.critical > 0 ? ` · ${f.critical} critical` : "";
  return `${f.total} finding${f.total === 1 ? "" : "s"} on route${crit}`;
}

export function CatalogScreen({ nav }: { nav: (s: string) => void }) {
  const [rows, setRows] = useState<CatalogItem[] | null>(null);
  const [facets, setFacets] = useState<CatalogFacets | null>(null);
  const [pag, setPag] = useState<CatalogPagination | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [facet, setFacet] = useState<FacetKey>("all");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [peek, setPeek] = useState<CatalogItem | null>(null);

  // A monotonic run id invalidates a superseded fetch, so a late response from a
  // stale facet never overwrites the grid (mirrors useCatalog's liveness guard).
  const runIdRef = useRef(0);

  const load = useCallback(async (f: FacetKey) => {
    const runId = ++runIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const page = await fetchCatalog({ page: 1, pageSize: PAGE, ...facetQuery(f) });
      if (runId !== runIdRef.current) return;
      setRows(mapCatalogItems(page.rows));
      setFacets(page.facets);
      setPag(page.pagination);
      setTruncated(page.truncated);
    } catch (e) {
      if (runId !== runIdRef.current) return;
      setError(e instanceof Error ? e.message : "Could not load the catalog");
      setRows([]);
      setPag(null);
    } finally {
      if (runId === runIdRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(facet);
  }, [facet, load]);

  const loadMore = useCallback(async () => {
    if (!pag?.has_more || loadingMore) return;
    const runId = runIdRef.current; // don't append onto a superseded facet
    setLoadingMore(true);
    try {
      const next = await fetchCatalog({
        page: pag.page + 1,
        pageSize: PAGE,
        ...facetQuery(facet),
      });
      if (runId !== runIdRef.current) return;
      setRows((prev) => [...(prev ?? []), ...mapCatalogItems(next.rows)]);
      setPag(next.pagination);
    } catch (e) {
      if (runId !== runIdRef.current) return;
      setError(e instanceof Error ? e.message : "Could not load more parts");
    } finally {
      if (runId === runIdRef.current) setLoadingMore(false);
    }
  }, [pag, loadingMore, facet]);

  // Client-side name search over loaded rows (the design's catQuery behaviour) —
  // the endpoint has no text-search param, so this filters what has been paged in.
  const query = q.trim().toLowerCase();
  const visible = useMemo(
    () => (rows ?? []).filter((r) => !query || r.filename.toLowerCase().includes(query)),
    [rows, query]
  );

  // The facet summary is computed over the FULL org catalog (pre-filter), so the
  // sum of its state counts is the org's true part total — an honest empty signal.
  const orgTotal = facets ? Object.values(facets.state).reduce((a, b) => a + b, 0) : 0;
  const orgEmpty = !loading && !error && facets != null && orgTotal === 0;

  const savedView = useCallback((f: FacetKey) => {
    setQ("");
    setFacet(f);
  }, []);
  const clearAll = useCallback(() => {
    setQ("");
    setFacet("all");
  }, []);

  const facetDefs: { key: FacetKey; label: string; count: number }[] = facets
    ? [
        { key: "all", label: "All", count: orgTotal },
        { key: "state:Costed", label: "Costed", count: stateFacetCount(facets, "Costed") },
        { key: "state:Drafted", label: "Drafted", count: stateFacetCount(facets, "Drafted") },
        { key: "findings:true", label: "With findings", count: facets.findings.with_findings },
        { key: "findings:false", label: "No findings", count: facets.findings.without_findings },
      ]
    : [];

  return (
    <main
      style={{
        animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both",
        flex: 1,
        overflowY: "auto",
        padding: "30px 34px",
        background: C.bg,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>Parts</h1>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <SavedViewPill label="⭑ Costed parts" onClick={() => savedView("state:Costed")} />
          <SavedViewPill label="⭑ With findings" onClick={() => savedView("findings:true")} />
        </div>
      </div>
      <p style={{ margin: "8px 0 0", maxWidth: 680, fontSize: 13, lineHeight: 1.6, color: C.ink50 }}>
        Every part your org has verified or drafted, unified into one grid — recommended route, unit cost, and DFM
        findings, each straight from the engine or honestly absent. Geometry previews are withheld: production does not
        serve org-scoped part meshes to this grid, so no shape is invented.
      </p>

      {/* Parts-master feeder (identity Slice 2): bulk-onboard the org's existing
          part library so the identity corpus knows their parts by name on day one —
          the flywheel's cold start. Refreshes the grid after a successful onboard. */}
      <LibraryOnboard onChanged={() => void load(facet)} />

      {error && (
        <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>
          couldn&apos;t load the catalog — {error}
        </p>
      )}

      {loading && rows === null ? (
        <div style={{ marginTop: 24 }}>
          <Spinner label="loading catalog…" />
        </div>
      ) : orgEmpty ? (
        <div style={{ marginTop: 24, maxWidth: 640 }}>
          <EmptyState
            title="No parts yet — and the grid won't invent any."
            body="Your catalog fills itself as the org verifies parts: each becomes a row here with its route, its cost, and its findings. Until then this stays honestly empty."
          >
            <GhostButton primary onClick={() => nav("verify")}>Verify your first part</GhostButton>
          </EmptyState>
        </div>
      ) : facets ? (
        <>
          {/* facet chips — built from the endpoint's real facet summary */}
          <div style={{ marginTop: 18, display: "flex", gap: 7, flexWrap: "wrap", alignItems: "center" }}>
            {facetDefs.map((f) => {
              const on = facet === f.key;
              return (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => setFacet(f.key)}
                  style={{
                    border: `1px solid ${on ? C.ink : "#dcdce0"}`,
                    background: on ? C.ink : C.panel,
                    color: on ? "#ffffff" : C.ink55,
                    borderRadius: 999,
                    padding: "7px 15px",
                    fontSize: 12,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    transition: "all 150ms",
                  }}
                >
                  {f.label} · {NUM(f.count)}
                </button>
              );
            })}
            <div style={{ marginLeft: "auto" }}>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search filename…"
                style={{
                  border: `1px solid ${C.hair}`,
                  background: C.panel,
                  borderRadius: 999,
                  padding: "7px 14px",
                  fontSize: 12,
                  fontFamily: MONO,
                  color: C.ink,
                  minWidth: 180,
                  outline: "none",
                }}
              />
            </div>
          </div>

          {truncated && (
            <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.cond }}>
              scan cap exceeded — the grid shows the most recent parts; older parts are not included (never silently
              omitted)
            </p>
          )}

          {visible.length === 0 ? (
            <div
              style={{
                marginTop: 20,
                maxWidth: 560,
                border: "1.5px dashed #d3d3d8",
                borderRadius: 16,
                padding: "34px 30px",
                textAlign: "center",
              }}
            >
              <p style={{ margin: 0, fontSize: 15, fontWeight: 500 }}>No parts match.</p>
              <p style={{ margin: "7px 0 0", fontSize: 12.5, color: C.ink50 }}>
                Nothing in this facet matches your search — and the grid won&apos;t pad itself with lookalikes.
              </p>
              <button
                type="button"
                onClick={clearAll}
                style={{
                  marginTop: 12,
                  background: "none",
                  border: `1px solid #d8d8dc`,
                  borderRadius: 999,
                  color: C.ink,
                  padding: "8px 18px",
                  fontSize: 12,
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                Clear search &amp; filters
              </button>
            </div>
          ) : (
            <div
              style={{
                marginTop: 20,
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
                gap: 14,
              }}
            >
              {visible.map((item) => (
                <CatalogCard key={item.partKey} item={item} onOpen={() => setPeek(item)} />
              ))}
            </div>
          )}

          {pag?.has_more && (
            <div style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 12 }}>
              <GhostButton onClick={() => void loadMore()} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load more"}
              </GhostButton>
              <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
                showing {NUM(rows?.length ?? 0)} of {NUM(pag.total)} · page-scanned
              </span>
            </div>
          )}

          <p style={{ margin: "18px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink35 }}>
            every figure here is engine output or withheld — a blocked route shows no price, an un-analyzed part shows
            no findings, and no card invents a standing it doesn&apos;t have
          </p>
        </>
      ) : null}

      {peek && (
        <PartPeek
          item={peek}
          onClose={() => setPeek(null)}
          onOpenStanding={() => {
            setSelectedPart(peek.partKey);
            setPeek(null);
            nav("part");
          }}
        />
      )}
    </main>
  );
}

function SavedViewPill({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: "1px dashed #d3d3d8",
        background: "none",
        borderRadius: 999,
        padding: "6px 14px",
        fontSize: 11.5,
        color: C.ink55,
        cursor: "pointer",
        fontFamily: "inherit",
      }}
    >
      {label}
    </button>
  );
}

/** A geometry glyph — the honest stand-in for a withheld part mesh (never a fake
 *  render of the real shape, which production does not serve to the product). */
function GeometryGlyph() {
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="rgba(23,24,26,0.22)" strokeWidth="1" strokeLinejoin="round">
        <path d="M12 2 3 7v10l9 5 9-5V7z" />
        <path d="M3 7l9 5 9-5M12 12v10" />
      </svg>
      <span style={{ fontFamily: MONO, fontSize: 8, letterSpacing: "0.12em", color: C.ink35 }}>PREVIEW WITHHELD</span>
    </span>
  );
}

function CatalogCard({ item, onOpen }: { item: CatalogItem; onOpen: () => void }) {
  const status = cardStatus(item);
  return (
    <button
      type="button"
      onClick={onOpen}
      style={{
        textAlign: "left",
        border: `1px solid ${C.hair}`,
        borderRadius: 16,
        background: C.panel,
        padding: 0,
        cursor: "pointer",
        overflow: "hidden",
        fontFamily: "inherit",
        color: "inherit",
      }}
    >
      <div
        style={{
          height: 150,
          background: "radial-gradient(90% 80% at 50% 42%, #ffffff 0%, #ececef 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
        }}
      >
        <GeometryGlyph />
        <span
          style={{
            position: "absolute",
            top: 11,
            left: 13,
            fontFamily: MONO,
            fontSize: 9.5,
            letterSpacing: "0.1em",
            color: status.color,
          }}
        >
          {status.tag}
        </span>
      </div>
      <div style={{ padding: "13px 15px 15px", borderTop: `1px solid #efeff2` }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
          <span
            style={{
              fontFamily: MONO,
              fontSize: 12.5,
              color: C.ink,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {item.filename}
          </span>
          <span style={{ fontFamily: MONO, fontSize: 12.5, color: C.ink55, whiteSpace: "nowrap" }}>{costText(item)}</span>
        </div>
        <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.55, color: C.ink40 }}>
          {routeText(item)}
        </p>
        <p style={{ margin: "3px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.55, color: item.findings?.critical ? C.fail : C.ink40 }}>
          {findingsText(item)}
        </p>
      </div>
    </button>
  );
}

/** A compact, honest peek at a part's real derived standing — every field is a
 *  cell already in the catalog row (no new fetch). The full standing page opens
 *  with this part selected. */
function PartPeek({ item, onClose, onOpenStanding }: { item: CatalogItem; onClose: () => void; onOpenStanding: () => void }) {
  const status = cardStatus(item);
  const uc = item.unitCost;
  const pp = item.posture;
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
        background: "rgba(23,24,26,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 520,
          maxWidth: "100%",
          maxHeight: "90vh",
          overflowY: "auto",
          background: C.panel,
          border: `1px solid ${C.hair}`,
          borderRadius: 18,
          boxShadow: "0 18px 50px -18px rgba(23,24,26,0.35)",
          padding: 24,
          animation: "vscreenIn 220ms cubic-bezier(0.2,0,0,1) both",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 15, color: C.ink }}>{item.filename}</p>
          <span style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.1em", color: status.color }}>{status.tag}</span>
          <button
            type="button"
            onClick={onClose}
            style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontFamily: MONO, fontSize: 14, color: C.ink40 }}
          >
            ✕
          </button>
        </div>
        <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
          {item.lifecycleState} · {item.fileType} · updated {new Date(item.updatedAt).toLocaleDateString()}
        </p>

        {/* recommended route + unit cost (withheld-aware, hatched assumption band) */}
        <div style={{ marginTop: 16, border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "16px 18px" }}>
          <Kicker color={C.ink45}>RECOMMENDED ROUTE</Kicker>
          <p style={{ margin: "8px 0 0", fontSize: 15 }}>
            {item.routeProcess ? procLabel(item.routeProcess) : "No recommended route"}
            {item.routeMaterial ? <span style={{ color: C.ink50, fontSize: 13 }}> · {item.routeMaterial}</span> : null}
          </p>
          {item.routeProcess && (
            <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
              source: {item.routeSource === "costed" ? "costed decision" : "DFM suggestion (not costed)"}
            </p>
          )}
          <div style={{ marginTop: 12, display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontSize: 22, fontWeight: 400 }}>{costText(item)}</span>
            <span style={{ fontSize: 12, color: C.ink45 }}>
              {uc?.withheld ? "price withheld" : uc?.usd != null ? `/unit${uc.qty != null ? ` at qty ${NUM(uc.qty)}` : ""}` : "not costed"}
            </span>
          </div>
          {uc?.withheld && uc.withheldReason && (
            <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>route blocked · {uc.withheldReason}</p>
          )}
          {uc && !uc.withheld && uc.usd != null && (
            <div style={{ marginTop: 12 }}>
              <ConfidenceBand validated={uc.validated} />
              <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink45 }}>
                {uc.validated ? "validated band" : "assumption band · n=0 · not shop-validated"} · hours are ○ MODEL
              </p>
            </div>
          )}
        </div>

        {/* provenance posture — grounded (filled) vs guess (hollow) drivers */}
        {pp && pp.total > 0 && (
          <div style={{ marginTop: 12, border: `1px solid ${C.hair}`, borderRadius: 14, padding: "14px 18px" }}>
            <Kicker color={C.ink45}>DRIVER PROVENANCE</Kicker>
            <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              {Array.from({ length: pp.measured }).map((_, i) => <ProvDot key={`m${i}`} p="MEASURED" />)}
              {Array.from({ length: pp.shop }).map((_, i) => <ProvDot key={`s${i}`} p="SHOP" />)}
              {Array.from({ length: pp.user }).map((_, i) => <ProvDot key={`u${i}`} p="USER" />)}
              {Array.from({ length: pp.default }).map((_, i) => <ProvDot key={`d${i}`} p="DEFAULT" />)}
              <span style={{ marginLeft: 6, fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
                {NUM(pp.grounded)} of {NUM(pp.total)} drivers grounded
              </span>
            </div>
          </div>
        )}

        {/* route-scoped findings — honestly absent when no DFM analysis ran */}
        <div style={{ marginTop: 12, border: `1px solid ${C.hair}`, borderRadius: 14, padding: "14px 18px" }}>
          <Kicker color={C.ink45}>DFM FINDINGS (ROUTE-SCOPED)</Kicker>
          {item.findings == null ? (
            <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
              no DFM analysis on this part — findings unknown, never a fabricated zero
            </p>
          ) : (
            <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink55 }}>
              {NUM(item.findings.total)} total · {NUM(item.findings.critical)} critical · {NUM(item.findings.advisory)} advisory · {NUM(item.findings.info)} info
            </p>
          )}
        </div>

        <p style={{ margin: "16px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          full standing includes history, blockers, context, and record detail
          <GhostButton onClick={onOpenStanding} style={{ padding: "6px 12px", fontSize: 11 }}>Open standing →</GhostButton>
        </p>
      </div>
    </div>
  );
}
