"use client";

/**
 * PART STANDING PAGE — the org's memory of what was asked, answered, and decided
 * about ONE part (design: `renderPart`). There is NO single part-detail endpoint;
 * a standing is ASSEMBLED from three real sources, keyed by the part's mesh hash
 * (the catalog's `part_key`):
 *
 *   GET /api/v1/catalog                     → the row (identity + latest verdict)
 *   GET /api/v1/part-context/{mesh_hash}    → lineage (program→assembly→part) + volume
 *   GET /api/v1/cost-decisions              → this file's decision history
 *   GET /api/v1/cost-decisions/{id}         → a record's full glass-box detail
 *
 * Honesty (adversarial): every number is a real engine/DB field or is WITHHELD.
 * A DFM-blocked route shows its price WITHHELD, never a make-price. Blockers are
 * REAL findings (measured vs required, faces, citation) off the latest verdict —
 * never invented. A part with no declared context has "no home yet". An empty org
 * gets the designed day-zero empty state, not fabricated rows. Bands are HATCHED
 * (assumption, n=0) until the engine reports a validated residual.
 */
import { useCallback, useEffect, useState } from "react";
import {
  fetchCatalog,
  fetchCostDecision,
  fetchCostDecisions,
  type CatalogRowApi,
  type CostDecisionDetail,
  type CostDecisionSummary,
} from "@/lib/api";
import { C, MONO, USD, NUM, procLabel, normProv } from "@/lib/verify/tokens";
import { makeNowEstimate, driverViews } from "@/lib/verify/derive";
import { fetchPartContext, type PartContext } from "@/lib/verify/part-context-read";
import {
  fetchBomAncestry,
  bomBreadcrumbView,
  basisChip,
  type BomAncestry,
} from "@/lib/verify/bom";
import { getSelectedPart } from "@/lib/verify/part-selection";
import {
  deriveStanding,
  extractBlockers,
  lineageView,
  historyForFile,
  standingTag,
  type PartStanding,
  type Blocker,
} from "@/lib/verify/part-standing";
import { verdictBannerModel, type VerdictBannerModel } from "@/lib/verify/verification";
import {
  Kicker,
  ProvChip,
  GhostButton,
  EmptyState,
  Spinner,
  ConfidenceBand,
} from "./primitives";

const TONE: Record<"pass" | "cond" | "fail" | "neutral", string> = {
  pass: C.pass,
  cond: C.cond,
  fail: C.fail,
  neutral: C.ink45,
};

export function PartScreen({ nav }: { nav: (s: string) => void }) {
  const [rows, setRows] = useState<CatalogRowApi[] | null>(null);
  const [catError, setCatError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setRows(null);
    setCatError(null);
    try {
      const page = await fetchCatalog({ pageSize: 100 });
      setRows(page.rows);
      setTruncated(page.truncated);
      // Prefer an explicit hand-off (from catalog/records/machine links); else the
      // most-recently-updated part. Never a hardcoded demo part.
      const pending = getSelectedPart();
      const has = (k: string | null) => !!k && page.rows.some((r) => r.part_key === k);
      setSelected(has(pending) ? pending : page.rows[0]?.part_key ?? null);
    } catch (e) {
      setCatError(e instanceof Error ? e.message : "Could not load parts");
      setRows([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const row = rows?.find((r) => r.part_key === selected) ?? null;

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
      <button
        type="button"
        onClick={() => nav("catalog")}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          cursor: "pointer",
          fontFamily: MONO,
          fontSize: 11,
          letterSpacing: "0.1em",
          color: C.ink45,
        }}
      >
        ← PARTS
      </button>

      {catError && (
        <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>
          couldn&apos;t load parts — {catError}
        </p>
      )}

      {rows === null ? (
        <div style={{ marginTop: 24 }}>
          <Spinner label="loading the org's parts…" />
        </div>
      ) : rows.length === 0 ? (
        <div style={{ marginTop: 20, maxWidth: 640 }}>
          <EmptyState
            title="No parts yet — and nothing invented to fill the space."
            body="A part earns a standing page the moment it's verified: its geometry, its verdict, its blockers, and the decision your team made. This becomes the org's memory — one page per part."
          >
            <GhostButton primary onClick={() => nav("verify")}>
              Verify your first part
            </GhostButton>
          </EmptyState>
        </div>
      ) : (
        <>
          <PartSwitcher rows={rows} selected={selected} onSelect={setSelected} truncated={truncated} />
          {row && <Standing key={row.part_key} row={row} nav={nav} />}
        </>
      )}
    </main>
  );
}

/** The on-surface part picker — the standing page's own way to move between parts
 *  (the catalog door will deep-link a specific one). Every chip is a REAL org part. */
function PartSwitcher({
  rows,
  selected,
  onSelect,
  truncated,
}: {
  rows: CatalogRowApi[];
  selected: string | null;
  onSelect: (k: string) => void;
  truncated: boolean;
}) {
  return (
    <div style={{ marginTop: 16, maxWidth: 1100 }}>
      <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 4 }}>
        {rows.map((r) => {
          const on = r.part_key === selected;
          const tag = standingTag(r);
          return (
            <button
              key={r.part_key}
              type="button"
              onClick={() => onSelect(r.part_key)}
              title={`${r.filename} · ${tag.label}`}
              style={{
                flexShrink: 0,
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                border: `1px solid ${on ? C.ink : "#dcdce0"}`,
                background: on ? C.ink : C.panel,
                color: on ? "#fff" : C.ink55,
                borderRadius: 999,
                padding: "7px 14px",
                fontFamily: MONO,
                fontSize: 11.5,
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: TONE[tag.tone],
                  flexShrink: 0,
                }}
              />
              {r.filename}
            </button>
          );
        })}
      </div>
      {truncated && (
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
          older parts beyond the scan cap are not shown here — honest, never silently dropped
        </p>
      )}
    </div>
  );
}

function Standing({ row, nav }: { row: CatalogRowApi; nav: (s: string) => void }) {
  const [detail, setDetail] = useState<CostDecisionDetail | null>(null);
  const [context, setContext] = useState<PartContext | null>(null);
  const [ctxError, setCtxError] = useState<string | null>(null);
  const [bom, setBom] = useState<BomAncestry | null>(null);
  const [history, setHistory] = useState<CostDecisionSummary[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setDetail(null);
    setContext(null);
    setCtxError(null);
    setBom(null);
    setHistory(null);

    const recordId = row.cost_decision?.id ?? null;
    const jobs: Promise<void>[] = [
      // the declared world → lineage + volume (404 = "no home yet", not an error)
      fetchPartContext(row.part_key).then((r) => {
        if (cancelled) return;
        setContext(r.context);
        setCtxError(r.error);
      }),
      // this file's decision history (list items carry filename, not mesh_hash)
      fetchCostDecisions({ limit: 100 }).then(
        (page) => {
          if (!cancelled) setHistory(historyForFile(page.cost_decisions, row.filename));
        },
        () => {
          if (!cancelled) setHistory([]);
        }
      ),
    ];
    if (recordId) {
      jobs.push(
        fetchCostDecision(recordId).then(
          (d) => {
            if (!cancelled) setDetail(d);
          },
          () => {
            if (!cancelled) setDetail(null);
          }
        )
      );
    }
    void Promise.all(jobs).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [row.part_key, row.cost_decision?.id, row.filename]);

  // Slice 3: when the declared context ties this part to a real BOM tree, read its
  // ancestry so we can show the honest "In context: part → … → vehicle" breadcrumb
  // and the BOM-rollup basis. No linkage (or no tree) → the crumb stays absent; we
  // never fetch or invent a hierarchy the customer never declared.
  const bomKey = context?.bom_assembly_key ?? null;
  const bomChild = context?.bom_child_ref ?? null;
  useEffect(() => {
    if (!bomKey || !bomChild) {
      setBom(null);
      return;
    }
    let cancelled = false;
    void fetchBomAncestry(bomKey, bomChild).then((a) => {
      if (!cancelled) setBom(a);
    });
    return () => {
      cancelled = true;
    };
  }, [bomKey, bomChild]);

  const standing = deriveStanding(row, detail);
  const blockers = extractBlockers(row, detail);
  const lin = lineageView(context);
  const geom = detail?.result?.geometry ?? null;

  return (
    <div
      style={{
        marginTop: 16,
        display: "grid",
        gridTemplateColumns: "360px 1fr",
        gap: 18,
        alignItems: "start",
        maxWidth: 1100,
      }}
    >
      {/* ── identity (left) ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div
          style={{
            border: `1px solid ${C.hair}`,
            borderRadius: 16,
            background: "radial-gradient(90% 80% at 50% 42%, #ffffff 0%, #ececef 100%)",
            height: 280,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            position: "relative",
          }}
        >
          <span style={{ fontFamily: MONO, fontSize: 42, fontWeight: 300, color: C.ink35, letterSpacing: "0.05em" }}>
            .{row.file_type}
          </span>
          <span
            style={{
              position: "absolute",
              top: 14,
              left: 16,
              fontFamily: MONO,
              fontSize: 10,
              letterSpacing: "0.1em",
              color: TONE[standingTag(row).tone],
            }}
          >
            {standingTag(row).label}
          </span>
        </div>

        <div style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "18px 20px" }}>
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 13, color: C.ink }}>{row.filename}</p>
          <p style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 10.5, lineHeight: 1.7, color: C.ink45 }}>
            {row.lifecycle_state.toLowerCase()}
            {standing.process ? ` · ${procLabel(standing.process)}` : ""}
            {standing.routeSource === "dfm" ? " [DFM suggested, not costed]" : ""}
            {" · updated "}
            {new Date(row.updated_at).toLocaleDateString()}
          </p>
          {geom && (
            <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, lineHeight: 1.7, color: C.measured }}>
              bbox {geom.bbox_mm.map((n) => n.toFixed(2)).join(" × ")} mm · {geom.volume_cm3.toFixed(2)} cm³ ·
              watertight {geom.watertight ? "✓" : "✗"} · ● MEASURED
            </p>
          )}
          <div style={{ marginTop: 14, display: "flex", flexWrap: "wrap", gap: 8 }}>
            <GhostButton
              primary
              onClick={() => nav("verify")}
              title="Re-verification re-reads the geometry — drop the file again on Verify"
            >
              Re-verify
            </GhostButton>
            {standing.recordId && (
              <GhostButton onClick={() => nav("compare")} title="Compare this part across calibrations / routes">
                Compare
              </GhostButton>
            )}
          </div>
          {!lin.hasHome && (
            <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
              next → assign to a program · exposure computes the moment it has a home
            </p>
          )}
        </div>

        {/* lineage (dashed) — DECLARED context only, or the honest "no home yet" */}
        <div
          style={{
            border: `1.5px dashed ${lin.hasHome ? C.user : "#d3d3d8"}`,
            borderRadius: 14,
            padding: "14px 18px",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <p style={{ margin: 0, flex: 1, fontFamily: MONO, fontSize: 10.5, lineHeight: 1.6, color: C.ink45 }}>
            {lin.hasHome
              ? `${lin.program} → ${lin.parentAssembly ?? "—"} → ${row.filename} · ● USER`
              : "no home yet — program → assembly → part"}
            {lin.hasHome && lin.annualVolume != null && (
              <span style={{ color: C.ink40 }}>{` · ${NUM(lin.annualVolume)}/yr declared`}</span>
            )}
          </p>
          <button
            type="button"
            onClick={() => nav("programs")}
            style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.user }}
          >
            {lin.hasHome ? "open program →" : "assign →"}
          </button>
        </div>

        {/* BOM ancestry (Slice 3) — shown ONLY when a real tree grounds this part.
            "In context: part → sub-assembly → … → vehicle", plus the derived annual
            volume with its BASIS chip (BOM ROLLUP vs DECLARED). Never invented. */}
        <BomContextBar
          view={bomBreadcrumbView(bom)}
          basis={basisChip(bom?.has_tree ? "bom_rollup" : context?.annual_volume != null ? "declared" : "default")}
          rootsPerYear={context?.bom_roots_per_year ?? null}
          declaredVolume={context?.annual_volume ?? null}
        />
        {ctxError && (
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, color: C.cond }}>
            lineage unavailable — {ctxError}
          </p>
        )}
      </div>

      {/* ── standing (right) ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {loading && !detail && (
          <div style={{ padding: "4px 2px" }}>
            <Spinner label="assembling this part's standing…" />
          </div>
        )}

        <StandingCard standing={standing} blockers={blockers} nav={nav} />

        {(history?.length ?? 0) > 0 ? (
          <HistoryCard history={history ?? []} currentId={standing.recordId} />
        ) : (
          standing.kind !== "costed" &&
          blockers.length === 0 && (
            <EmptyState
              title="No saved decision yet."
              body="This part has a standing page waiting for its first costed verdict. Nothing here will ever be invented to fill the space."
            >
              <GhostButton primary onClick={() => nav("verify")}>
                Verify it now
              </GhostButton>
            </EmptyState>
          )
        )}
      </div>
    </div>
  );
}

// BOM ancestry breadcrumb (Slice 3). Renders NOTHING unless a real tree grounds
// this part (view.present) — the honest absent state keeps the flat declared
// lineage above untouched. When present: "In context: part → … → vehicle", the
// rolled-up per-vehicle count, and the annual volume with its BASIS chip.
function BomContextBar({
  view,
  basis,
  rootsPerYear,
  declaredVolume,
}: {
  view: ReturnType<typeof bomBreadcrumbView>;
  basis: ReturnType<typeof basisChip>;
  rootsPerYear: number | null;
  declaredVolume: number | null;
}) {
  if (!view.present) return null;
  const rollup = basis?.tone === "rollup";
  const chipColor = rollup ? C.measured : C.user;
  const perYear =
    view.perVehicle != null && rootsPerYear != null
      ? view.perVehicle * rootsPerYear
      : declaredVolume;
  return (
    <div
      style={{
        border: `1.5px solid ${chipColor}`,
        borderRadius: 14,
        padding: "12px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: 0.4, color: C.ink40 }}>
          IN CONTEXT
        </span>
        {basis && (
          <span
            style={{
              fontFamily: MONO,
              fontSize: 9,
              letterSpacing: 0.6,
              color: "#fff",
              background: chipColor,
              borderRadius: 5,
              padding: "2px 6px",
            }}
          >
            {basis.text}
          </span>
        )}
        {view.shared && (
          <span style={{ fontFamily: MONO, fontSize: 9, color: C.ink40 }}>
            shared · summed over {view.chain.length ? "all paths" : "paths"}
          </span>
        )}
      </div>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 11, lineHeight: 1.6, color: C.ink70 }}>
        {view.chain.join("  →  ")}
      </p>
      {view.perVehicle != null && (
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, color: C.ink45 }}>
          {`${NUM(view.perVehicle)} per vehicle`}
          {rootsPerYear != null && perYear != null && (
            <span style={{ color: C.ink40 }}>
              {`  ·  ${NUM(view.perVehicle)} × ${NUM(rootsPerYear)}/yr = ${NUM(perYear)}/yr`}
              {rollup ? " (BOM rollup)" : ""}
            </span>
          )}
        </p>
      )}
    </div>
  );
}

function StandingCard({
  standing,
  blockers,
  nav,
}: {
  standing: PartStanding;
  blockers: Blocker[];
  nav: (s: string) => void;
}) {
  if (standing.kind === "costed") {
    const machine: VerdictBannerModel = standing.makeabilityVerdict
      ? verdictBannerModel(standing.makeabilityVerdict)
      : {
          kicker: "SHOULD-COST · MACHINE FIT NOT EVALUATED",
          title: "Costed route — machine fit not evaluated.",
          sub: "This record predates a machine-fit verdict or was computed without declared inventory.",
          tone: "neutral",
        };
    const tone = TONE[machine.tone];
    const border =
      machine.tone === "pass"
        ? "rgba(31,138,91,0.45)"
        : machine.tone === "cond"
          ? "rgba(176,120,24,0.45)"
          : machine.tone === "fail"
            ? "rgba(194,69,58,0.4)"
            : C.hair;
    const background =
      machine.tone === "pass"
        ? "rgba(31,138,91,0.04)"
        : machine.tone === "cond"
          ? "rgba(176,120,24,0.04)"
          : machine.tone === "fail"
            ? "rgba(194,69,58,0.03)"
            : C.panel;
    return (
      <div
        style={{
          border: `1.5px solid ${border}`,
          borderRadius: 16,
          background,
          padding: "20px 22px",
        }}
      >
        <Kicker color={tone}>
          {machine.kicker}{standing.recordId ? ` · RECORD #${standing.recordId.slice(-6)}` : ""}
        </Kicker>
        <p style={{ margin: "10px 0 0", fontSize: 21, fontWeight: 400, letterSpacing: "-0.015em" }}>
          {machine.title}
        </p>
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11.5, color: C.ink55 }}>
          should-cost route{standing.process ? ` · ${procLabel(standing.process)}` : ""}
          {standing.unitCostUsd != null ? ` · ${USD(standing.unitCostUsd)}/unit` : ""}
          {standing.costQty ? ` @ qty ${NUM(standing.costQty)}` : ""}
        </p>
        <div style={{ margin: "12px 0 0", maxWidth: 320 }}>
          <ConfidenceBand validated={standing.validated} />
        </div>
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
          {standing.bandLabel ?? (standing.validated ? "validated band" : "assumption band — not shop-validated")}
          {!standing.validated ? " · n=0" : ""}
          {standing.crossoverQty != null ? ` · crossover ${NUM(standing.crossoverQty)}` : ""}
        </p>
      </div>
    );
  }

  if (standing.kind === "blocked" || standing.kind === "invalid") {
    return (
      <div
        style={{
          border: `1.5px solid rgba(194,69,58,0.35)`,
          borderRadius: 18,
          background: "rgba(194,69,58,0.03)",
          padding: "24px 26px",
        }}
      >
        <Kicker color={C.fail}>
          {standing.kind === "invalid" ? "GEOMETRY INVALID — NOTHING COSTED" : "NOT MAKEABLE AS-DESIGNED · PRICE WITHHELD"}
        </Kicker>
        <p style={{ margin: "10px 0 0", fontSize: 17, fontWeight: 500 }}>
          {standing.process
            ? `No owned route passes on ${procLabel(standing.process)}.`
            : "The engine won't cost a part it can't make as-designed."}
        </p>
        {blockers.length > 0 ? (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
            {blockers.map((b, i) => (
              <BlockerRow key={`${b.code}-${i}`} b={b} />
            ))}
          </div>
        ) : (
          <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
            the blocking finding is on the record — open the verdict to see it located on the part
          </p>
        )}
        <div style={{ marginTop: 16 }}>
          <GhostButton primary onClick={() => nav("verify")}>
            Re-verify after repair
          </GhostButton>
        </div>
      </div>
    );
  }

  // drafted — analyzed, cost required
  return (
    <div
      style={{
        border: `1.5px solid rgba(176,120,24,0.4)`,
        borderRadius: 16,
        background: "rgba(176,120,24,0.04)",
        padding: "20px 22px",
      }}
    >
      <Kicker color={C.cond}>DRAFTED — ANALYZED, COST REQUIRED</Kicker>
      <p style={{ margin: "10px 0 0", fontSize: 19, fontWeight: 400 }}>
        {standing.process
          ? `DFM route so far: ${procLabel(standing.process)}`
          : "Geometry parsed — route costing required."}
      </p>
      <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
        no should-cost until it&apos;s costed against your floor — nothing here is guessed
      </p>
      <div style={{ marginTop: 14 }}>
        <GhostButton primary onClick={() => nav("verify")}>
          Verify to cost it
        </GhostButton>
      </div>
    </div>
  );
}

function BlockerRow({ b }: { b: Blocker }) {
  const bits: string[] = [];
  if (b.measured != null && b.required != null) bits.push(`measured ${b.measured} vs required ${b.required}`);
  if (b.affectedFaces != null) bits.push(`${NUM(b.affectedFaces)} face${b.affectedFaces === 1 ? "" : "s"}`);
  if (b.citation) bits.push(b.citation);
  return (
    <div>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 11.5, lineHeight: 1.6, color: C.ink70 }}>▸ {b.message}</p>
      {bits.length > 0 && (
        <p style={{ margin: "3px 0 0 14px", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>{bits.join(" · ")}</p>
      )}
      {b.fix && (
        <p style={{ margin: "3px 0 0 14px", fontFamily: MONO, fontSize: 10.5, color: C.ink50 }}>fix → {b.fix}</p>
      )}
    </div>
  );
}

function HistoryCard({ history, currentId }: { history: CostDecisionSummary[]; currentId: string | null }) {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <div style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
      <Kicker color={C.ink45}>HISTORY — EVERY VERIFICATION APPENDS HERE</Kicker>
      <div style={{ marginTop: 8, display: "flex", flexDirection: "column" }}>
        {history.map((h) => (
          <div key={h.id} style={{ borderBottom: `1px solid #f0f0f3` }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 14, padding: "12px 2px" }}>
              <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink40, minWidth: 92 }}>
                {new Date(h.created_at).toLocaleDateString()}
              </span>
              <span style={{ flex: 1, fontSize: 13, color: C.ink }}>
                Cost decision — {procLabel(h.make_now_process)}
                {h.crossover_qty != null ? ` · crossover ${NUM(h.crossover_qty)}` : ""}
                {h.id === currentId ? "  · current" : ""}
              </span>
              <button
                type="button"
                onClick={() => setOpenId(openId === h.id ? null : h.id)}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.measured }}
              >
                {openId === h.id ? "hide record" : "open record →"}
              </button>
            </div>
            {openId === h.id && <RecordInline id={h.id} />}
          </div>
        ))}
      </div>
      <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink35 }}>
        this page is the part&apos;s standing — the org&apos;s memory of what was asked, answered, and decided
      </p>
    </div>
  );
}

/** Inline glass-box of one saved decision — GET /cost-decisions/{id}, drivers
 *  with real provenance. Reuses the walk's pure derivations; never fabricates. */
function RecordInline({ id }: { id: string }) {
  const [detail, setDetail] = useState<CostDecisionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchCostDecision(id).then(
      (d) => {
        if (!cancelled) setDetail(d);
      },
      (e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "load failed");
      }
    );
    return () => {
      cancelled = true;
    };
  }, [id]);

  const est = detail?.result ? makeNowEstimate(detail.result) : null;
  const drivers = driverViews(est);

  return (
    <div style={{ padding: "4px 2px 16px", background: C.sunken, borderRadius: 12, marginBottom: 8 }}>
      {error && <p style={{ margin: "8px 12px", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>{error}</p>}
      {!detail && !error && (
        <div style={{ padding: "8px 12px" }}>
          <Spinner label="loading record…" />
        </div>
      )}
      {detail && (
        <div style={{ padding: "8px 14px" }}>
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, color: C.ink45 }}>
            {new Date(detail.created_at).toLocaleString()} · engine {detail.engine_version ?? "—"} ·{" "}
            {USD(est?.unit_cost_usd)}/unit @ qty {est ? NUM(est.quantity) : "—"}
          </p>
          {drivers.length > 0 ? (
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column" }}>
              {drivers.map((d) => (
                <div
                  key={d.name}
                  style={{ display: "flex", alignItems: "baseline", gap: 12, padding: "7px 0", borderBottom: `1px solid #eceef1` }}
                >
                  <span style={{ fontSize: 12, color: C.ink, minWidth: 120 }}>{d.label}</span>
                  <span style={{ fontFamily: MONO, fontSize: 11.5, color: C.ink }}>
                    {d.unit === "usd" ? USD(d.value) : NUM(d.value)}
                  </span>
                  <span style={{ marginLeft: "auto" }}>
                    <ProvChip p={normProv(d.provenance)} />
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
              no per-driver breakdown on this record
            </p>
          )}
        </div>
      )}
    </div>
  );
}
