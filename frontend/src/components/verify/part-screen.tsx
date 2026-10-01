"use client";

import { formatIssueMeasure } from "@/lib/inspection-bind";

/**
 * PART STANDING PAGE — the org's memory of what was asked, answered, and decided
 * about ONE part (design: `renderPart`). There is NO single part-detail endpoint;
 * a standing is ASSEMBLED from three real sources, keyed by the part's mesh hash
 * (the catalog's `part_key`):
 *
 *   GET /api/v1/catalog                     → the row (identity + latest verdict)
 *   GET /api/v1/part-context/{mesh_hash}    → lineage (program→assembly→part) + volume
 *   GET /api/v1/cost-decisions?mesh_hash=…  → this part's decision history
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
import { assignContext } from "@/lib/verify/program-api";
import { Button } from "@/components/ui/button";
import {
  fetchBomAncestry,
  bomBreadcrumbView,
  bomAnnualVolume,
  basisChip,
  type BomAncestry,
} from "@/lib/verify/bom";
import { getSelectedPart } from "@/lib/verify/part-selection";
import {
  deriveStanding,
  extractBlockers,
  lineageView,
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

export function PartScreen({ nav, onOpenProgram, onCompare }: {
  nav: (s: string) => void;
  onOpenProgram: (name: string) => void;
  onCompare: (recordId: string) => void;
}) {
  const [rows, setRows] = useState<CatalogRowApi[] | null>(null);
  const [catError, setCatError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setRows(null);
    setCatError(null);
    try {
      const page = await fetchCatalog({ pageSize: 100 });
      const pending = getSelectedPart();
      if (pending && !page.rows.some((r) => r.part_key === pending)) {
        const match = await fetchCatalog({ partKey: pending });
        const exact = match.rows.find((r) => r.part_key === pending);
        if (!exact) throw new Error("The selected part is unavailable in this organization. Return to Parts to choose another.");
        page.rows = [...page.rows, exact];
      }
      setRows(page.rows);
      setTruncated(page.truncated);
      // Prefer an explicit hand-off (from catalog/records/machine links); else the
      // most-recently-updated part. Never a hardcoded demo part.
      setSelected(pending ?? page.rows[0]?.part_key ?? null);
    } catch (e) {
      setCatError(e instanceof Error ? e.message : "Could not load parts");
      setRows([]);
      setSelected(null);
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

      {catError ? null : rows === null ? (
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
          {row && <Standing key={row.part_key} row={row} nav={nav} onOpenProgram={onOpenProgram} onCompare={onCompare} />}
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

function Standing({ row, nav, onOpenProgram, onCompare }: {
  row: CatalogRowApi;
  nav: (s: string) => void;
  onOpenProgram: (name: string) => void;
  onCompare: (recordId: string) => void;
}) {
  const [detail, setDetail] = useState<CostDecisionDetail | null>(null);
  const [context, setContext] = useState<PartContext | null>(null);
  const [ctxError, setCtxError] = useState<string | null>(null);
  const [bom, setBom] = useState<BomAncestry | null>(null);
  const [bomError, setBomError] = useState<string | null>(null);
  const [bomAttempt, setBomAttempt] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setDetail(null);
    setContext(null);
    setCtxError(null);
    setBom(null);

    const recordId = row.cost_decision?.id ?? null;
    const jobs: Promise<void>[] = [
      // the declared world → lineage + volume (404 = "no home yet", not an error)
      fetchPartContext(row.part_key).then((r) => {
        if (cancelled) return;
        setContext(r.context);
        setCtxError(r.error);
      }),
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
    setBom(null);
    setBomError(null);
    if (!bomKey || !bomChild) {
      return;
    }
    let cancelled = false;
    void fetchBomAncestry(bomKey, bomChild).then((a) => {
      if (!cancelled) setBom(a);
    }).catch((e) => {
      if (!cancelled) setBomError(e instanceof Error ? e.message : "Could not load the BOM. Please retry.");
    });
    return () => {
      cancelled = true;
    };
  }, [bomKey, bomChild, bomAttempt]);

  const standing = deriveStanding(row, detail);
  const blockers = extractBlockers(row, detail);
  const lin = lineageView(context);
  const geom = detail?.result?.geometry ?? null;

  return (
    <div
      style={{
        marginTop: 16,
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))",
        gap: 18,
        alignItems: "start",
        maxWidth: 1100,
        overflowWrap: "anywhere",
      }}
    >
      {/* ── identity (left) ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
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
              <GhostButton onClick={() => onCompare(standing.recordId!)} title="Compare this part across calibrations / routes">
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
            onClick={() => lin.program ? onOpenProgram(lin.program) : nav("programs")}
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
          pathsTruncated={bom?.ancestry_paths_truncated ?? false}
          rootsPerYear={context?.bom_roots_per_year ?? null}
          declaredVolume={context?.annual_volume ?? null}
        />
        {(bomError || bom?.error || (bom && !bom.has_tree)) && (
          <div role="alert" style={{ fontFamily: MONO, fontSize: 11, color: C.cond }}>
            <p>BOM unavailable — {bomError || bom?.error || "The linked assembly does not contain this part."}</p>
            <GhostButton onClick={() => setBomAttempt((n) => n + 1)}>Retry BOM</GhostButton>
          </div>
        )}
        {!loading && !ctxError && <BomLinkEditor meshHash={row.part_key} context={context} onSaved={(next) => {
          setContext(next);
          setBomAttempt((n) => n + 1);
        }} />}
        {ctxError && (
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, color: C.cond }}>
            lineage unavailable — {ctxError}
          </p>
        )}
      </div>

      {/* ── standing (right) ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
        {loading && !detail && (
          <div style={{ padding: "4px 2px" }}>
            <Spinner label="assembling this part's standing…" />
          </div>
        )}

        <StandingCard standing={standing} blockers={blockers} nav={nav} />

        <HistoryCard key={row.cost_decision?.id ?? "uncosted"} partKey={row.part_key} currentId={standing.recordId} />
      </div>
    </div>
  );
}

function BomLinkEditor({ meshHash, context, onSaved }: {
  meshHash: string; context: PartContext | null; onSaved: (context: PartContext) => void;
}) {
  const [assembly, setAssembly] = useState(context?.bom_assembly_key ?? "");
  const [child, setChild] = useState(context?.bom_child_ref ?? "");
  const [roots, setRoots] = useState(context?.bom_roots_per_year?.toString() ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function save(remove = false) {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const key = assembly.trim(), ref = child.trim();
      const yearly = roots.trim() ? Number(roots) : null;
      if (!remove) {
        if (!key || !ref) throw new Error("Enter the saved assembly name and this part's BOM reference.");
        if (yearly !== null && (!Number.isInteger(yearly) || yearly < 1 || yearly > 2147483647)) {
          throw new Error("Root assemblies per year must be a whole number between 1 and 2147483647.");
        }
        const ancestry = await fetchBomAncestry(key, ref);
        if (!ancestry?.has_tree || ancestry.error || ancestry.rolled_up_multiplier == null) {
          throw new Error(ancestry?.error || "This saved assembly does not contain that part. Check the assembly name and exact BOM reference.");
        }
        if (yearly !== null && bomAnnualVolume(ancestry.rolled_up_multiplier, yearly) === null) {
          throw new Error("BOM annual demand exceeds the supported exact integer range.");
        }
      }
      const result = await assignContext(meshHash, {
        bom_assembly_key: remove ? null : key,
        bom_child_ref: remove ? null : ref,
        bom_roots_per_year: remove ? null : yearly,
      });
      onSaved(result.context);
      if (remove) { setAssembly(""); setChild(""); setRoots(""); }
      setMessage(remove ? "BOM link removed. Any flat annual-volume declaration is preserved." : "BOM link saved. The current hierarchy is shown above.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the BOM link. Please retry.");
    } finally { setBusy(false); }
  }

  return <details style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "18px 20px" }}>
    <summary className="cursor-pointer font-medium">Link this part to a saved BOM</summary>
    <form aria-label="Part BOM link" className="mt-3 space-y-3 text-sm" onSubmit={(event) => { event.preventDefault(); void save(); }} onChange={() => { setError(""); setMessage(""); }}>
      <p>Match this CAD part to an imported assembly. This is your declaration of part identity. Annual demand follows the saved hierarchy and your yearly assembly count; saved cost decisions stay unchanged.</p>
      <fieldset disabled={busy} className="grid gap-3">
        <label className="grid gap-1"><span>Saved BOM assembly name</span><input className="rounded border border-border bg-background px-3 py-2" value={assembly} onChange={(e) => setAssembly(e.target.value)} required /></label>
        <label className="grid gap-1"><span>Part reference in BOM</span><input className="rounded border border-border bg-background px-3 py-2" value={child} onChange={(e) => setChild(e.target.value)} required /></label>
        <label className="grid gap-1"><span>Root assemblies per year (optional)</span><input className="rounded border border-border bg-background px-3 py-2" type="number" min={1} max={2147483647} step={1} value={roots} onChange={(e) => setRoots(e.target.value)} /></label>
        <p className="text-xs text-muted-foreground">Use the exact child reference from your BOM. For Windchill, use its part iteration ID. Without a yearly count, the flat annual-volume declaration is used when present.</p>
        <div className="flex flex-wrap gap-2">
          <Button type="submit">{busy ? "Saving…" : "Save BOM link"}</Button>
          <Button type="button" variant="secondary" disabled={!context?.bom_assembly_key && !context?.bom_child_ref} onClick={() => void save(true)}>Remove BOM link</Button>
        </div>
      </fieldset>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {message && <p role="status">{message}</p>}
    </form>
  </details>;
}

// BOM ancestry breadcrumb (Slice 3). Renders NOTHING unless a real tree grounds
// this part (view.present) — the honest absent state keeps the flat declared
// lineage above untouched. When present: "In context: part → … → vehicle", the
// rolled-up per-vehicle count, and the annual volume with its BASIS chip.
function BomContextBar({
  view,
  pathsTruncated,
  rootsPerYear,
  declaredVolume,
}: {
  view: ReturnType<typeof bomBreadcrumbView>;
  pathsTruncated: boolean;
  rootsPerYear: number | null;
  declaredVolume: number | null;
}) {
  if (!view.present) return null;
  const perYear = bomAnnualVolume(view.perVehicle, rootsPerYear);
  const basis = basisChip(perYear != null ? "bom_rollup" : declaredVolume != null ? "declared" : "default");
  const rollup = basis?.tone === "rollup";
  const chipColor = rollup ? C.measured : C.user;
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
        {pathsTruncated && <span style={{ fontFamily: MONO, fontSize: 9, color: C.ink40 }}>path preview limited · count includes all paths</span>}
      </div>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 11, lineHeight: 1.6, color: C.ink70 }}>
        {view.chain.join("  →  ")}
      </p>
      {view.perVehicle != null && (
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, color: C.ink45 }}>
          {`${NUM(view.perVehicle)} per root assembly`}
          {rootsPerYear != null && perYear != null && (
            <span style={{ color: C.ink40 }}>
              {`  ·  ${NUM(view.perVehicle)} × ${NUM(rootsPerYear)}/yr = ${NUM(perYear)}/yr`}
              {rollup ? " (BOM rollup)" : ""}
            </span>
          )}
        </p>
      )}
      {perYear == null && (
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, color: C.ink45 }}>
          {rootsPerYear == null
            ? "Yearly root assembly production has not been supplied."
            : "BOM annual demand exceeds the supported exact integer range."}
          {declaredVolume != null ? ` Using ${NUM(declaredVolume)}/yr declared.` : " Annual demand is unavailable."}
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
          {!standing.validated ? ` · n=${standing.nSamples ?? 0}` : ""}
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
  if (b.measured != null && b.required != null) bits.push(`measured ${formatIssueMeasure(b.measured, b.required)} vs required ${formatIssueMeasure(b.required, b.measured)}`);
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

function HistoryCard({ partKey, currentId }: { partKey: string; currentId: string | null }) {
  const [history, setHistory] = useState<CostDecisionSummary[]>([]);
  const [cursor, setCursor] = useState<string | undefined>();
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchCostDecisions({ meshHash: partKey, limit: 20, cursor }).then((page) => {
      // Fail closed if an older/incompatible API ignores the identity filter.
      if (page.cost_decisions.some((d) => d.mesh_hash !== partKey)) {
        throw new Error("The history response does not match this part.");
      }
      if (cancelled) return;
      setHistory((prev) => cursor ? [...prev, ...page.cost_decisions] : page.cost_decisions);
      setNextCursor(page.has_more ? page.next_cursor : null);
    }).catch((e) => {
      if (!cancelled) setError(e instanceof Error ? e.message : "History could not be loaded.");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [partKey, cursor, retry]);

  return (
    <section aria-label="Part cost history" style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
      <Kicker color={C.ink45}>HISTORY — SAVED COST DECISIONS</Kicker>
      <div style={{ marginTop: 8, display: "flex", flexDirection: "column" }}>
        {history.map((h) => (
          <div key={h.id} data-cost-decision-id={h.id} style={{ borderBottom: `1px solid #f0f0f3` }}>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 14, padding: "12px 2px" }}>
              <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink40, minWidth: 92 }}>
                {new Date(h.created_at).toLocaleDateString()}
              </span>
              <span style={{ flex: "1 1 150px", fontSize: 13, color: C.ink }}>
                {h.filename} — {procLabel(h.make_now_process)}
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
      {loading && <Spinner label="loading part history…" />}
      {error && (
        <div role="alert">
          <p style={{ fontSize: 12, color: C.fail }}>History unavailable — {error}</p>
          <GhostButton onClick={() => setRetry((n) => n + 1)}>Retry history</GhostButton>
        </div>
      )}
      {!loading && !error && history.length === 0 && (
        <p style={{ fontSize: 12, color: C.ink45 }}>No saved cost decisions for this part yet.</p>
      )}
      {!loading && !error && nextCursor && (
        <GhostButton onClick={() => setCursor(nextCursor)}>Load older decisions</GhostButton>
      )}
      <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink35 }}>
        this page is the part&apos;s standing — the org&apos;s memory of what was asked, answered, and decided
      </p>
    </section>
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
                  style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 12, padding: "7px 0", borderBottom: `1px solid #eceef1` }}
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
