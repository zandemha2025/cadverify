"use client";

/**
 * PartWorkspace — the L2 DECISION object frame (the re-founded home of the
 * single-part loop). A CAD drop runs the full should-cost decision + the DFM
 * analysis; the studio-lit part stays in a persistent rail while the tabs change
 * the lens onto the SAME engine report and the resident Inspector traces any
 * number back to its governed sources:
 *
 *   Decision · Routing & DFM · Glass Box · Compare · History        [ Inspector ]
 *
 * A Decision contains Estimates (per-quantity / per-scenario). The Role Lens sets
 * the landing tab but walls nothing off. The make-vs-buy crossover SCRUBBER (the
 * "aha") survives in the Decision lens, re-hosted in FLAT platform chrome — no
 * bloom, no well, no gauge-needle settle. The Inspector reframes the retired
 * GlassBoxDrawer as infrastructure (Lineage / Governance / Sources / Audit).
 *
 * Session-authed via the same-origin proxy (the session cookie is forwarded
 * server-side). The CostGeometryInvalidError repair path and the Phase-2 cost
 * artifact (save / export / share) are preserved.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Gauge, Boxes, Factory, Scale, History as HistoryIcon, Copy } from "lucide-react";
import {
  costEstimate,
  validateFile,
  getShops,
  CostGeometryInvalidError,
  type CostOptions,
  type CostReport,
  type CostGeometry,
  type CostAssumption,
  type ShopProfileInfo,
  type ValidationResult,
} from "@/lib/api";
import { severityTone, verdictLabel, verdictTone, procLabel } from "@/lib/status";
import { parseCalibration, pickEstimate } from "@/lib/cost-views";
import { costPersistUiEnabled } from "@/lib/cost-decision";
import { flattenIssues } from "@/components/IssueList";

import { Button } from "@/components/ui/button";
import { Dropzone } from "@/components/ui/dropzone";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { StatusBadge } from "@/components/ui/status-badge";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

import { CostDecisionView } from "@/components/cost/CostDecisionView";
import { CostGeometryInvalidCard } from "@/components/CostDecisionCard";
import { GlassBoxView, type ScenarioSummary } from "@/components/workspace/GlassBoxView";
import { RoutingDfmView } from "@/components/workspace/RoutingDfmView";
import { CompareView } from "@/components/workspace/CompareView";
import { DecisionInspector } from "@/components/workspace/DecisionInspector";
import { CostArtifactBar } from "@/components/instrument/CostArtifactBar";
import {
  CostOptionsForm,
  DEFAULT_COST_OPTIONS,
  validateQty,
} from "@/components/cost/CostOptionsForm";
import { RoleLens, CalibrationBar, roleById, type RoleId } from "@/components/glass-box";
import { useInstrumentChrome, type PartFact } from "@/components/instrument/instrument-chrome";
import { STAGE_UI } from "@/lib/stage-flag";

/* PartHero (~1900 lines, stage-only) is code-split into its own lazy chunk so a
   flag-off build never ships it in the main bundle: it is rendered solely from
   the `if (STAGE_UI)` branch below, so flag-off never mounts it and the chunk is
   never requested. ssr:false is fine — the hero is a client-only surface (it
   hosts the WebGL CadViewer, itself ssr:false). Flag-off behaviour is unchanged. */
const PartHero = dynamic(
  () => import("@/components/workspace/hero/PartHero").then((m) => m.PartHero),
  { ssr: false }
);

const CadViewer = dynamic(() => import("@/components/ui/cad-viewer"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center rounded-[var(--radius)] border border-border bg-muted">
      <p className="text-sm text-muted-foreground">Loading 3D viewer…</p>
    </div>
  ),
});

/* Face-highlight hues that read on the machined mesh. Stage register: the D5
   severity lane (ERROR crimson · WARN amber · INFO steel) with brass = validated
   / default neutral steel; legacy: the cool-graphite tones. Gated on the flag so
   flag-off is byte-identical. */
const SEVERITY_HEX: Record<string, string> = STAGE_UI
  ? {
      fail: "#e05252",
      warn: "#e5a83b",
      info: "#8fa0a6",
      pass: "#cfa84e",
      neutral: "#78828a",
    }
  : {
      fail: "#e0736b",
      warn: "#d9a441",
      info: "#4c90f0",
      pass: "#3fb37f",
      neutral: "#93a1b3",
    };

const ACCEPT = ".stl,.step,.stp";

type WorkTab = "decision" | "routing" | "glassbox" | "compare" | "history";

const WORK_TABS: { value: WorkTab; label: string; icon: typeof Gauge }[] = [
  { value: "decision", label: "Decision", icon: Gauge },
  { value: "routing", label: "Routing & DFM", icon: Factory },
  { value: "glassbox", label: "Glass Box", icon: Boxes },
  { value: "compare", label: "Compare", icon: Scale },
  { value: "history", label: "History", icon: HistoryIcon },
];

/** map a role's `lands` label to the tab id it lands on */
const LANDS_TO_TAB: Record<string, WorkTab> = {
  Decision: "decision",
  "Glass Box": "glassbox",
  Compare: "compare",
  "Routing & DFM": "routing",
};

function landingTab(role: RoleId): WorkTab {
  return LANDS_TO_TAB[roleById(role).lands] ?? "decision";
}

export default function PartWorkspace({
  defaultRole = "design",
  initialFile = null,
  onExit,
}: {
  /** the lens this entry point lands on (cost → design, analyze → mfg). */
  defaultRole?: RoleId;
  /**
   * A file to seed the workspace with — used by the FE-3 part door, which drops
   * the user straight into the hero. Flag-off / direct routes pass nothing and
   * behave exactly as before (cold-start dropzone).
   */
  initialFile?: File | null;
  /**
   * Called when the user resets ("New part"). When provided (part door), the
   * caller returns to its own landing instead of this workspace's cold-start.
   */
  onExit?: () => void;
}) {
  const [file, setFile] = useState<File | null>(initialFile ?? null);
  const [opts, setOpts] = useState<CostOptions>(DEFAULT_COST_OPTIONS);
  const [role, setRole] = useState<RoleId>(defaultRole);
  const [tab, setTab] = useState<WorkTab>(() => landingTab(defaultRole));
  const [inspectorOpen, setInspectorOpen] = useState(() => defaultRole === "cost");

  // cost state
  const [report, setReport] = useState<CostReport | null>(null);
  const [assumptions, setAssumptions] = useState<CostAssumption[]>([]);
  const [costLoading, setCostLoading] = useState(false);
  const [costError, setCostError] = useState<string | null>(null);
  const [geomError, setGeomError] = useState<{
    reason: string | null;
    geometry: CostGeometry | null;
  } | null>(null);

  // dfm state
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [dfmLoading, setDfmLoading] = useState(false);
  const [dfmError, setDfmError] = useState<string | null>(null);

  // analyze ↔ geometry linking
  const [selectedIssueKey, setSelectedIssueKey] = useState<string | null>(null);
  const [showOptions, setShowOptions] = useState(false);

  // per-shop calibration + session-local scenarios
  const [shops, setShops] = useState<ShopProfileInfo[]>([]);
  const [scenarios, setScenarios] = useState<(ScenarioSummary & { opts: CostOptions })[]>([]);

  const activeRole = roleById(role);
  const { setPart } = useInstrumentChrome();

  useEffect(() => {
    let cancelled = false;
    getShops()
      .then((r) => !cancelled && setShops(r.shops))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setAssumptions(report?.assumptions ?? []);
  }, [report]);

  const dfmIssues = useMemo(() => (validation ? flattenIssues(validation) : []), [validation]);
  const selectedIssue = useMemo(
    () => dfmIssues.find((i) => i.key === selectedIssueKey) ?? null,
    [dfmIssues, selectedIssueKey]
  );

  const calibration = useMemo(
    () => (report ? parseCalibration({ ...report, assumptions }) : null),
    [report, assumptions]
  );

  // the resident Inspector anchors to the Decision's make-now recommendation —
  // the number the whole frame is about — and traces it to its governed sources.
  const inspectorEstimate = useMemo(() => {
    if (!report?.decision) return null;
    return pickEstimate(report, report.decision.make_now_process);
  }, [report]);
  const overrideKeys = useMemo(() => Object.keys(opts.overrides ?? {}), [opts.overrides]);

  const setOpt = useCallback(
    <K extends keyof CostOptions>(key: K, value: CostOptions[K]) =>
      setOpts((o) => ({ ...o, [key]: value })),
    []
  );

  const onChangeRole = useCallback((next: RoleId) => {
    setRole(next);
    setTab(landingTab(next));
    if (next === "cost") setInspectorOpen(true);
  }, []);

  /* ---- shop binding + glass-box overrides (REAL server re-cost) ----- */

  const recostWith = useCallback(
    (next: CostOptions) => {
      setOpts(next);
      if (file && !validateQty(next.qty)) void runCost(file, next);
    },
    // runCost is stable (useCallback []); safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [file]
  );

  const onSelectShop = useCallback(
    (shopId: string | null) => {
      recostWith({ ...opts, shop: shopId });
      const name = shops.find((s) => s.id === shopId)?.name;
      toast.success(
        shopId
          ? `Calibrating to ${name ?? "shop"} — re-costing with its real rates.`
          : "Cleared shop — re-costing on generic defaults."
      );
    },
    [opts, shops, recostWith]
  );

  const onApplyOverride = useCallback(
    (key: string, value: number) => {
      recostWith({ ...opts, overrides: { ...(opts.overrides ?? {}), [key]: value } });
      toast.success(`Override ${key} = ${value} — re-costing.`);
    },
    [opts, recostWith]
  );

  const onSetCavities = useCallback(
    (value: number) => recostWith({ ...opts, cavities: value }),
    [opts, recostWith]
  );

  const onClearOverrides = useCallback(() => {
    recostWith({ ...opts, overrides: {} });
    toast("Cleared overrides — back to the shop/default rates.");
  }, [opts, recostWith]);

  const onSaveScenario = useCallback(() => {
    if (!report?.decision) return;
    const firstQty = report.quantities[0];
    const rec = report.decision.recommendation[String(firstQty)];
    const shopName = shops.find((s) => s.id === opts.shop)?.name;
    const ovr = Object.keys(opts.overrides ?? {}).length;
    const label = `${shopName ?? "Generic"}${ovr ? ` · ${ovr} ovr` : ""} · qty ${firstQty.toLocaleString()}`;
    setScenarios((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${prev.length}`,
        label,
        unitCost: rec?.unit_cost_usd ?? null,
        process: rec?.process ?? report.decision?.make_now_process ?? null,
        opts,
      },
    ]);
    toast.success("Saved to this session — click it to recall and re-cost.");
  }, [report, opts, shops]);

  const onRecallScenario = useCallback(
    (id: string) => {
      const scn = scenarios.find((s) => s.id === id);
      if (scn) recostWith(scn.opts);
    },
    [scenarios, recostWith]
  );

  /* ---- API calls -------------------------------------------------- */

  const runCost = useCallback(async (theFile: File, theOpts: CostOptions) => {
    setCostLoading(true);
    setCostError(null);
    setGeomError(null);
    setReport(null);
    try {
      const result = await costEstimate(theFile, theOpts);
      setReport(result);
    } catch (err) {
      if (err instanceof CostGeometryInvalidError) {
        setGeomError({ reason: err.message, geometry: err.geometry });
      } else {
        setCostError(err instanceof Error ? err.message : "Cost estimate failed.");
      }
    } finally {
      setCostLoading(false);
    }
  }, []);

  const runDfm = useCallback(async (theFile: File) => {
    setDfmLoading(true);
    setDfmError(null);
    setValidation(null);
    setSelectedIssueKey(null);
    try {
      const data = await validateFile(theFile);
      setValidation(data);
    } catch (err) {
      setDfmError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setDfmLoading(false);
    }
  }, []);

  const handleFile = useCallback(
    (selected: File) => {
      const ext = selected.name.split(".").pop()?.toLowerCase();
      if (!ext || !["stl", "step", "stp"].includes(ext)) {
        setCostError("Unsupported file type. Use .stl, .step, or .stp");
        return;
      }
      if (validateQty(opts.qty)) {
        setShowOptions(true);
        setCostError("Fix the quantity list before submitting.");
        return;
      }
      setFile(selected);
      setTab(landingTab(role));
      void runCost(selected, opts);
      void runDfm(selected);
    },
    [opts, role, runCost, runDfm]
  );

  /* Seed from a caller-provided file (FE-3 part door hands off here). `file`
     state is initialised to it so the hero paints immediately with no cold-start
     flash; this effect runs the real cost + DFM pass once, reusing handleFile. */
  const seededRef = useRef(false);
  useEffect(() => {
    if (initialFile && !seededRef.current) {
      seededRef.current = true;
      handleFile(initialFile);
    }
    // handleFile is stable enough; we intentionally seed only on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialFile]);

  const handleRecost = useCallback(() => {
    if (!file || validateQty(opts.qty)) return;
    void runCost(file, opts);
  }, [file, opts, runCost]);

  const reset = useCallback(() => {
    setFile(null);
    setReport(null);
    setGeomError(null);
    setCostError(null);
    setValidation(null);
    setDfmError(null);
    setSelectedIssueKey(null);
    setScenarios([]);
    // Part-door mode: hand control back to the door landing instead of showing
    // this workspace's own cold-start dropzone. No-op on flag-off / direct routes.
    onExit?.();
  }, [onExit]);

  const onFaceClick = useCallback(
    (faceIndex: number) => {
      const hit = dfmIssues.find((i) => i.faces.includes(faceIndex));
      if (hit) {
        setTab("routing");
        setSelectedIssueKey(hit.key);
      }
    },
    [dfmIssues]
  );

  const onHighlightProcess = useCallback(
    (process: string) => {
      const hit =
        dfmIssues.find((i) => i.issue.process === process && i.faces.length) ??
        dfmIssues.find((i) => i.issue.process === process);
      if (hit) {
        setSelectedIssueKey(hit.key);
      } else {
        toast(`No geometry-linked faces reported for ${procLabel(process)}.`);
      }
    },
    [dfmIssues]
  );

  /* ---- publish the loaded part's identity to the context-bar breadcrumb --- */
  const geoForFacts = report?.geometry;
  const vgeoForFacts = validation?.geometry;
  const facts = useMemo<PartFact[]>(() => {
    const out: PartFact[] = [];
    if (geoForFacts) {
      out.push({ label: "vol", value: `${geoForFacts.volume_cm3.toFixed(1)} cm³` });
      out.push({ label: "bbox", value: `${geoForFacts.bbox_mm.map((v) => Math.round(v)).join("×")} mm` });
      out.push({ label: "faces", value: geoForFacts.face_count.toLocaleString() });
    } else if (vgeoForFacts) {
      out.push({ label: "vol", value: `${(vgeoForFacts.volume_mm3 / 1000).toFixed(1)} cm³` });
      out.push({ label: "bbox", value: `${vgeoForFacts.bounding_box_mm.map((v) => Math.round(v)).join("×")} mm` });
      out.push({ label: "faces", value: vgeoForFacts.faces.toLocaleString() });
    }
    return out;
  }, [geoForFacts, vgeoForFacts]);

  useEffect(() => {
    if (!file) {
      setPart(null);
      return;
    }
    setPart({
      name: file.name,
      facts,
      verdict: validation?.overall_verdict ?? null,
      analyzing: dfmLoading,
      onReset: reset,
    });
  }, [file, facts, validation, dfmLoading, reset, setPart]);
  useEffect(() => () => setPart(null), [setPart]);

  /* ---- cold start ------------------------------------------------- */

  if (!file) {
    return (
      <div className="mx-auto max-w-2xl space-y-5 p-6">
        <div>
          <span className="cv-eyebrow">Should-cost · make-vs-buy</span>
          <h1 className="mt-2 text-display font-semibold text-foreground">
            Drop a CAD file — get the decision, then the receipts.
          </h1>
          <p className="mt-1.5 max-w-prose text-sm text-muted-foreground">
            The manufacturing decision first (make by X, $Y/unit, Z days, switch to a mold above N),
            with the glass-box drivers, geometric routing and DFM evidence one click away — and the
            resident Inspector tracing any number to its governed source.
          </p>
        </div>
        <Dropzone
          accept={ACCEPT}
          onFiles={(files) => files[0] && handleFile(files[0])}
          isLoading={costLoading}
          hint="STEP, STP or STL · CAD is parsed and discarded in-process · zero egress"
        />
        {costError && <ErrorState message={costError} onRetry={() => setCostError(null)} />}
        <Card>
          <button
            type="button"
            onClick={() => setShowOptions((s) => !s)}
            aria-expanded={showOptions}
            className="w-full px-4 py-3 text-left text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            {showOptions ? "▾" : "▸"} Costing options (optional — sensible defaults applied)
          </button>
          {showOptions && (
            <div className="border-t border-border px-4 pb-4 pt-3">
              <CostOptionsForm
                opts={opts}
                setOpt={setOpt}
                qtyError={validateQty(opts.qty)}
                disabled={costLoading}
              />
            </div>
          )}
        </Card>
      </div>
    );
  }

  /* ---- staged hero (D5 FE-2) — flag-gated; flag-off keeps the tabs -- */
  if (STAGE_UI) {
    return (
      <PartHero
        file={file}
        report={report}
        validation={validation}
        opts={opts}
        setOpt={setOpt}
        assumptions={assumptions}
        overrideKeys={overrideKeys}
        scenarios={scenarios}
        shops={shops}
        calibration={calibration}
        role={role}
        costLoading={costLoading}
        dfmLoading={dfmLoading}
        costError={costError}
        dfmError={dfmError}
        geomError={geomError}
        onChangeRole={onChangeRole}
        onSelectShop={onSelectShop}
        onApplyOverride={onApplyOverride}
        onSetCavities={onSetCavities}
        onClearOverrides={onClearOverrides}
        onSaveScenario={onSaveScenario}
        onRecallScenario={onRecallScenario}
        handleRecost={handleRecost}
        runDfm={runDfm}
        reset={reset}
      />
    );
  }

  /* ---- loaded workspace ------------------------------------------- */

  const geo = validation?.geometry;
  const costGeo = report?.geometry ?? geomError?.geometry ?? null;

  const headerBadge = validation ? (
    <StatusBadge verdict={validation.overall_verdict} label={verdictLabel(validation.overall_verdict, true)} />
  ) : geomError ? (
    <StatusBadge tone="fail" label="Geometry invalid" />
  ) : dfmLoading ? (
    <StatusBadge tone="neutral" label="Analyzing…" icon={false} />
  ) : undefined;

  const highlightFaces = tab === "routing" && selectedIssue ? selectedIssue.faces : undefined;
  const highlightColor = selectedIssue
    ? SEVERITY_HEX[severityTone(selectedIssue.issue.severity)]
    : undefined;

  return (
    <div className="flex h-full min-h-0">
      {/* ── content column ─────────────────────────────────────────── */}
      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="space-y-5 p-6">
          {/* frame header: identity + Role Lens + Calibration + reset */}
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <span className="cv-eyebrow">Decision · estimate@live</span>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <h1 className="num truncate text-lg font-semibold text-foreground">{file.name}</h1>
                {headerBadge}
              </div>
              <p className="text-xs text-muted-foreground">One drop · costed and analyzed in-process</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {report && calibration && (
                <CalibrationBar
                  shopName={calibration.shopName}
                  source={calibration.source}
                  note={calibration.note}
                  shopRates={calibration.shopRates}
                  defaultRates={calibration.defaultRates}
                  shops={shops}
                  activeShopId={opts.shop ?? null}
                  recosting={costLoading}
                  onSelectShop={onSelectShop}
                />
              )}
              <RoleLens value={role} onChange={onChangeRole} />
              <Button variant="secondary" onClick={reset}>
                New part
              </Button>
            </div>
          </div>

          <Tabs value={tab} onValueChange={(v) => setTab(v as WorkTab)}>
            <TabsList className="w-full justify-start overflow-x-auto">
              {WORK_TABS.map(({ value, label, icon: Icon }) => (
                <TabsTrigger key={value} value={value}>
                  <Icon className="size-4" />
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>

            <div className="mt-4 grid gap-6 lg:grid-cols-5">
              {/* persistent studio-lit part rail (flat platform chrome) */}
              <div className="space-y-3 lg:sticky lg:top-0 lg:col-span-2 lg:self-start">
                <div className="h-[340px]">
                  <CadViewer
                    file={file}
                    highlightFaces={highlightFaces}
                    highlightColor={highlightColor}
                    ghostUnhighlighted={!!highlightFaces}
                    onFaceClick={tab === "routing" ? onFaceClick : undefined}
                  />
                </div>
                {costGeo || geo ? (
                  <div className="num grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                    <GeomFact
                      label="Volume"
                      value={
                        costGeo
                          ? `${costGeo.volume_cm3.toFixed(1)} cm³`
                          : geo
                            ? `${(geo.volume_mm3 / 1000).toFixed(1)} cm³`
                            : "—"
                      }
                    />
                    <GeomFact
                      label="Bounding box"
                      value={
                        costGeo
                          ? `${costGeo.bbox_mm.map((v) => Math.round(v)).join(" × ")} mm`
                          : geo
                            ? geo.bounding_box_mm.map((v) => Math.round(v)).join(" × ") + " mm"
                            : "—"
                      }
                    />
                    <GeomFact
                      label="Faces"
                      value={(costGeo?.face_count ?? geo?.faces ?? 0).toLocaleString()}
                    />
                    <GeomFact
                      label="Watertight"
                      value={(costGeo?.watertight ?? geo?.is_watertight) ? "Yes" : "No"}
                    />
                  </div>
                ) : null}
                <p className="cv-eyebrow">measured · from your geometry</p>
                {tab === "routing" && selectedIssue && (
                  <p className="text-xs text-muted-foreground">
                    Highlighting{" "}
                    <span className="num text-foreground">{selectedIssue.issue.code}</span>. Click
                    another blocker, or a face, to change.
                  </p>
                )}
              </div>

              {/* active lens */}
              <div className="lg:col-span-3">
                <TabsContent value="decision" className="mt-0">
                  {costLoading ? (
                    <LoadingPane label="Computing should-cost across processes…" />
                  ) : geomError ? (
                    <CostGeometryInvalidCard
                      reason={geomError.reason}
                      geometry={geomError.geometry}
                      filename={file.name}
                    />
                  ) : costError ? (
                    <ErrorState title="Cost estimate failed" message={costError} onRetry={handleRecost} />
                  ) : report ? (
                    <div className="space-y-5">
                      <CostDecisionView
                        report={report}
                        opts={opts}
                        setOpt={setOpt}
                        onRecost={handleRecost}
                        recosting={costLoading}
                        role={activeRole}
                        onOpenGlassBox={() => setTab("glassbox")}
                        onSeeRouting={() => setTab("routing")}
                      />
                      {costPersistUiEnabled() && report.saved && (
                        <CostArtifactBar saved={report.saved} filename={file.name} />
                      )}
                    </div>
                  ) : null}
                </TabsContent>

                <TabsContent value="routing" className="mt-0">
                  {dfmLoading && !report ? (
                    <LoadingPane label="Analyzing across all manufacturing processes…" />
                  ) : dfmError && !report ? (
                    <ErrorState
                      title="Analysis unavailable"
                      message={dfmError}
                      onRetry={() => file && runDfm(file)}
                    />
                  ) : (
                    <RoutingDfmView
                      report={report}
                      validation={validation}
                      selectedIssueKey={selectedIssueKey}
                      onSelectIssue={(it) => setSelectedIssueKey(it.key)}
                      onHighlightProcess={onHighlightProcess}
                    />
                  )}
                </TabsContent>

                <TabsContent value="glassbox" className="mt-0">
                  {costLoading ? (
                    <LoadingPane label="Opening the glass box…" />
                  ) : report ? (
                    <GlassBoxView
                      report={report}
                      assumptions={assumptions}
                      overrideCount={overrideKeys.length}
                      recosting={costLoading}
                      scenarios={scenarios}
                      onApplyOverride={onApplyOverride}
                      onSetCavities={onSetCavities}
                      onClearOverrides={onClearOverrides}
                      onSaveScenario={onSaveScenario}
                      onRecallScenario={onRecallScenario}
                    />
                  ) : (
                    <EmptyState
                      icon={Boxes}
                      title="No cost breakdown yet"
                      description="The glass box opens once the part is costed."
                    />
                  )}
                </TabsContent>

                <TabsContent value="compare" className="mt-0">
                  {costLoading ? (
                    <LoadingPane label="Building the decision board…" />
                  ) : report ? (
                    <CompareView report={report} onDrill={() => setTab("glassbox")} />
                  ) : (
                    <EmptyState
                      icon={Scale}
                      title="Nothing to compare yet"
                      description="The decision board opens once the part is costed."
                    />
                  )}
                </TabsContent>

                <TabsContent value="history" className="mt-0">
                  <HistoryPanel
                    report={report}
                    validation={validation}
                    scenarios={scenarios}
                    onRecallScenario={onRecallScenario}
                  />
                </TabsContent>
              </div>
            </div>
          </Tabs>
        </div>
      </div>

      {/* ── resident Inspector (the reframed glass box) ────────────── */}
      <DecisionInspector
        open={inspectorOpen}
        onToggle={() => setInspectorOpen((o) => !o)}
        estimate={inspectorEstimate}
        process={report?.decision?.make_now_process ?? ""}
        qty={inspectorEstimate?.quantity ?? report?.quantities[0] ?? 0}
        materialClass={report?.material_class ?? opts.material_class}
        overrideKeys={overrideKeys}
        onOverride={onApplyOverride}
        defaultTab={role === "cost" ? "sources" : "lineage"}
      />
    </div>
  );
}

function GeomFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius)] border border-border bg-card px-2.5 py-1.5">
      <span className="block text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="block font-medium text-foreground">{value}</span>
    </div>
  );
}

function LoadingPane({ label }: { label: string }) {
  return (
    <div className="flex h-64 flex-col items-center justify-center gap-3">
      <Spinner />
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  History — session scenarios + the durable cost artifact + a quick   */
/*  no-account copy path. Cost decisions live at /cost-decisions today.  */
/* ------------------------------------------------------------------ */

function HistoryPanel({
  report,
  validation,
  scenarios,
  onRecallScenario,
}: {
  report: CostReport | null;
  validation: ValidationResult | null;
  scenarios: (ScenarioSummary & { opts: CostOptions })[];
  onRecallScenario: (id: string) => void;
}) {
  const router = useRouter();
  const summary = buildAnswerSummary(report, validation);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(summary);
      toast.success("Decision summary copied");
    } catch {
      toast.error("Could not copy to clipboard");
    }
  };

  if (!report) {
    return (
      <EmptyState
        icon={HistoryIcon}
        title="No history yet"
        description="Scenarios you save this session appear here, alongside your durable cost decisions."
      />
    );
  }

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <span className="cv-eyebrow">Saved scenarios · this session</span>
        {scenarios.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Bind a shop or override a rate in the Glass Box, then “Save as scenario” to compare
            variants of this Decision. A Decision contains Estimates.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {scenarios.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => onRecallScenario(s.id)}
                className="num inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="text-muted-foreground">{s.label}</span>
                {s.unitCost != null && (
                  <span className="font-semibold">
                    ${s.unitCost.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </Card>

      <Card className="space-y-3 p-4">
        <span className="cv-eyebrow">Durable cost decisions</span>
        <p className="text-xs text-muted-foreground">
          Saved should-cost decisions are exportable, shareable and comparable — they keep their
          provenance tags and the “assumption-based, not yet validated” band verbatim.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => router.push("/cost-decisions")}>
            Open cost history
          </Button>
          <Button variant="ghost" onClick={copy} disabled={!summary}>
            <Copy className="size-4" />
            Copy decision summary
          </Button>
        </div>
      </Card>
    </div>
  );
}

function buildAnswerSummary(
  report: CostReport | null,
  validation: ValidationResult | null
): string {
  const lines: string[] = [];
  if (report?.decision) {
    const dec = report.decision;
    lines.push(`CadVerify — ${report.filename}`);
    lines.push(`Make by ${procLabel(dec.make_now_process)} / ${dec.make_now_material}`);
    for (const q of report.quantities) {
      const r = dec.recommendation[String(q)];
      if (r) {
        lines.push(
          `  qty ${q.toLocaleString()}: ${procLabel(r.process)} — $${r.unit_cost_usd.toFixed(2)}/unit${
            r.lead_low_days != null && r.lead_high_days != null
              ? `, ${r.lead_low_days}-${r.lead_high_days} days`
              : ""
          }`
        );
      }
    }
    if (dec.crossover_qty != null) {
      lines.push(
        `Crossover ≈ ${Math.round(dec.crossover_qty).toLocaleString()} units${
          dec.tooling_process ? ` → switch to ${procLabel(dec.tooling_process)} above it` : ""
        }`
      );
    }
  }
  if (validation) {
    lines.push(
      `DFM: ${verdictLabel(validation.overall_verdict, true)} (${verdictTone(validation.overall_verdict)})`
    );
  }
  return lines.join("\n");
}
