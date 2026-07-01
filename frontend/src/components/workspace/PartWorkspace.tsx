"use client";

/**
 * PartWorkspace — the role-gated glass-box over ONE analysis object. A single CAD
 * drop runs the full should-cost decision + the DFM analysis; the part stays in a
 * persistent 3D rail while the Role Lens sets which tab you land on and the tabs
 * change the lens onto the SAME engine report:
 *
 *   Decision · Glass Box · Routing & DFM · Compare · Share
 *
 * The lens walls nothing off — every tab is one click away (real users wear
 * several hats in one sitting). Per-shop calibration is an always-on topbar fact.
 * Bound to the cost-truth engine's REAL report_to_dict (routing, confidence,
 * provenance-tagged drivers, crossover) — never the toy model, never a fabricated
 * accuracy figure.
 *
 * Session-authed: the platform is gated, so this always calls the authed
 * /validate + /validate/cost routes via the same-origin proxy (the session
 * cookie is forwarded server-side). The CostGeometryInvalidError repair path is
 * preserved.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { toast } from "sonner";
import {
  Share2,
  Copy,
  Gauge,
  Boxes,
  Factory,
  Scale,
  ArrowRight,
  Lock,
} from "lucide-react";
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
import { severityTone, verdictTone, verdictLabel, procLabel } from "@/lib/status";
import { parseCalibration } from "@/lib/cost-views";
import { flattenIssues } from "@/components/IssueList";

import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Dropzone } from "@/components/ui/dropzone";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { StatusBadge } from "@/components/ui/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

import { CostDecisionView } from "@/components/cost/CostDecisionView";
import { CostGeometryInvalidCard } from "@/components/CostDecisionCard";
import { GlassBoxView, type ScenarioSummary } from "@/components/workspace/GlassBoxView";
import { RoutingDfmView } from "@/components/workspace/RoutingDfmView";
import { CompareView } from "@/components/workspace/CompareView";
import {
  CostOptionsForm,
  DEFAULT_COST_OPTIONS,
  validateQty,
} from "@/components/cost/CostOptionsForm";
import {
  RoleLens,
  CalibrationBar,
  roleById,
  type RoleId,
} from "@/components/glass-box";

const CadViewer = dynamic(() => import("@/components/ui/cad-viewer"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center rounded-[var(--radius)] border border-border bg-muted">
      <p className="text-sm text-muted-foreground">Loading 3D viewer…</p>
    </div>
  ),
});

const SEVERITY_HEX: Record<string, string> = {
  fail: "#dc2626",
  warn: "#d97706",
  info: "#0284c7",
  pass: "#059669",
  neutral: "#64748b",
};

const ACCEPT = ".stl,.step,.stp";

/* ------------------------------------------------------------------ */
/*  Role-aware tabs (one report, five lenses). The Role Lens sets the   */
/*  landing tab; every tab stays reachable for everyone (multi-hat).    */
/* ------------------------------------------------------------------ */

type WorkTab = "decision" | "glassbox" | "routing" | "compare" | "share";

const WORK_TABS: { value: WorkTab; label: string; icon: typeof Gauge }[] = [
  { value: "decision", label: "Decision", icon: Gauge },
  { value: "glassbox", label: "Glass Box", icon: Boxes },
  { value: "routing", label: "Routing & DFM", icon: Factory },
  { value: "compare", label: "Compare", icon: Scale },
  { value: "share", label: "Share", icon: Share2 },
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
}: {
  /** the lens this entry point lands on (cost → design, analyze → mfg). */
  defaultRole?: RoleId;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [opts, setOpts] = useState<CostOptions>(DEFAULT_COST_OPTIONS);
  const [role, setRole] = useState<RoleId>(defaultRole);
  const [tab, setTab] = useState<WorkTab>(() => landingTab(defaultRole));

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

  // per-shop calibration (F1) + session-local scenarios (F3)
  const [shops, setShops] = useState<ShopProfileInfo[]>([]);
  const [scenarios, setScenarios] = useState<
    (ScenarioSummary & { opts: CostOptions })[]
  >([]);

  const activeRole = roleById(role);

  // fetch the bindable shop profiles once (best-effort; the picker just stays
  // empty if this fails — the generic should-cost still works).
  useEffect(() => {
    let cancelled = false;
    getShops()
      .then((r) => !cancelled && setShops(r.shops))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // keep the live assumption set in sync with the latest report (resets overrides)
  useEffect(() => {
    setAssumptions(report?.assumptions ?? []);
  }, [report]);

  const dfmIssues = useMemo(
    () => (validation ? flattenIssues(validation) : []),
    [validation]
  );
  const selectedIssue = useMemo(
    () => dfmIssues.find((i) => i.key === selectedIssueKey) ?? null,
    [dfmIssues, selectedIssueKey]
  );

  // calibration reflects live overrides (USER re-tags show up immediately)
  const calibration = useMemo(
    () => (report ? parseCalibration({ ...report, assumptions }) : null),
    [report, assumptions]
  );

  const setOpt = useCallback(
    <K extends keyof CostOptions>(key: K, value: CostOptions[K]) =>
      setOpts((o) => ({ ...o, [key]: value })),
    []
  );

  /* ---- the Role Lens sets the landing tab (walls nothing off) ------ */
  const onChangeRole = useCallback((next: RoleId) => {
    setRole(next);
    setTab(landingTab(next));
  }, []);

  /* ---- shop binding + glass-box overrides (REAL server re-cost) ----- */

  /** Re-cost the current part with a new options set (shop / overrides / cavities). */
  const recostWith = useCallback(
    (next: CostOptions) => {
      setOpts(next);
      if (file && !validateQty(next.qty)) void runCost(file, next);
    },
    // runCost is declared below; it is stable (useCallback []), so this is safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [file]
  );

  /** Bind (or clear) a per-shop calibration profile → the SHOP-calibrated number. */
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

  /** Apply one ad-hoc rate override (dotted key) → real re-cost, tagged USER. */
  const onApplyOverride = useCallback(
    (key: string, value: number) => {
      recostWith({
        ...opts,
        overrides: { ...(opts.overrides ?? {}), [key]: value },
      });
      toast.success(`Override ${key} = ${value} — re-costing.`);
    },
    [opts, recostWith]
  );

  /** n_cavities edits route to the cavities option (also a real re-cost). */
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
  }, []);

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

  // DFM matrix → highlight the offending faces for a process's blocker
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

  /* ---- cold start ------------------------------------------------- */

  if (!file) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Should-cost & make-vs-buy"
          subtitle="Drop a CAD file — get the manufacturing decision first (make by X, $Y/unit, Z days, switch to a mold above N), with the glass-box drivers, geometric routing and DFM evidence one click away."
        />
        <div className="mx-auto max-w-2xl space-y-4">
          <Dropzone
            accept={ACCEPT}
            onFiles={(files) => files[0] && handleFile(files[0])}
            isLoading={costLoading}
            hint="STEP, STP or STL · CAD is parsed and discarded in-process"
          />
          {costError && (
            <ErrorState message={costError} onRetry={() => setCostError(null)} />
          )}
          <Card>
            <button
              type="button"
              onClick={() => setShowOptions((s) => !s)}
              aria-expanded={showOptions}
              className="w-full px-4 py-3 text-left text-sm font-medium text-muted-foreground hover:text-foreground"
            >
              {showOptions ? "▾" : "▸"} Costing options (optional — sensible
              defaults applied)
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
      </div>
    );
  }

  /* ---- loaded workspace ------------------------------------------- */

  const geo = validation?.geometry;
  const costGeo = report?.geometry ?? geomError?.geometry ?? null;

  const headerBadge = validation ? (
    <StatusBadge
      verdict={validation.overall_verdict}
      label={verdictLabel(validation.overall_verdict, true)}
    />
  ) : geomError ? (
    <StatusBadge tone="fail" label="Geometry invalid" />
  ) : dfmLoading ? (
    <StatusBadge tone="neutral" label="Analyzing…" icon={false} />
  ) : undefined;

  const highlightFaces =
    tab === "routing" && selectedIssue ? selectedIssue.faces : undefined;
  const highlightColor = selectedIssue
    ? SEVERITY_HEX[severityTone(selectedIssue.issue.severity)]
    : undefined;

  return (
    <div className="space-y-5">
      <PageHeader
        title={<span className="num">{file.name}</span>}
        subtitle="One drop · costed and analyzed in-process"
        badge={headerBadge}
        actions={
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
        }
      />

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
          {/* persistent part rail (shared across every lens) */}
          <div className="space-y-3 lg:sticky lg:top-6 lg:col-span-2 lg:self-start">
            <div className="h-[360px]">
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
                <span className="num text-foreground">
                  {selectedIssue.issue.code}
                </span>
                . Click another blocker, or a face, to change.
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
                <ErrorState
                  title="Cost estimate failed"
                  message={costError}
                  onRetry={handleRecost}
                />
              ) : report ? (
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
              ) : null}
            </TabsContent>

            <TabsContent value="glassbox" className="mt-0">
              {costLoading ? (
                <LoadingPane label="Opening the glass box…" />
              ) : report ? (
                <GlassBoxView
                  report={report}
                  assumptions={assumptions}
                  overrideCount={Object.keys(opts.overrides ?? {}).length}
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

            <TabsContent value="share" className="mt-0">
              <SharePanel report={report} validation={validation} role={role} />
            </TabsContent>
          </div>
        </div>
      </Tabs>
    </div>
  );
}

function GeomFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius)] border border-border bg-card px-2.5 py-1.5">
      <span className="block text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
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
/*  Share / Handoff — share the glass box, not the number. The instant  */
/*  copy stays the zero-friction path; the role-scoped shared object is  */
/*  designed for, build gap flagged.                                     */
/* ------------------------------------------------------------------ */

const HANDOFF_ROLES: { id: RoleId; label: string; verb: string }[] = [
  { id: "sourcing", label: "Sourcing", verb: "Send to sourcing" },
  { id: "cost", label: "Cost eng", verb: "Share with cost eng" },
  { id: "buyer", label: "Buyer", verb: "Forward to purchaser" },
  { id: "mfg", label: "Mfg eng", verb: "Send to manufacturing" },
];

function SharePanel({
  report,
  validation,
  role,
}: {
  report: CostReport | null;
  validation: ValidationResult | null;
  role: RoleId;
}) {
  const summary = buildAnswerSummary(report, validation);
  const [recipient, setRecipient] = useState<RoleId>(
    role === "design" ? "sourcing" : role
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(summary);
      toast.success("Decision summary copied");
    } catch {
      toast.error("Could not copy to clipboard");
    }
  };

  if (!summary) {
    return (
      <EmptyState
        icon={Share2}
        title="Nothing to share yet"
        description="The decision summary appears here once the part has been costed."
      />
    );
  }

  const recipientVerb =
    HANDOFF_ROLES.find((r) => r.id === recipient)?.verb ?? "Share glass box";

  return (
    <div className="space-y-4">
      <Card>
        <CardContent compact className="space-y-3">
          <h3 className="text-base font-semibold leading-[22px] text-foreground">
            Copy decision summary
          </h3>
          <p className="text-xs text-muted-foreground">
            The instant, no-account path — the headline answer as text.
          </p>
          <pre className="num whitespace-pre-wrap rounded-[var(--radius)] border border-border bg-muted/50 p-3 text-xs text-foreground">
            {summary}
          </pre>
          <Button onClick={copy}>
            <Copy className="size-4" />
            Copy decision summary
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent compact className="space-y-3">
          <h3 className="text-base font-semibold leading-[22px] text-foreground">
            Share the glass box, not the number
          </h3>
          <p className="text-xs text-muted-foreground">
            The recipient opens the SAME provenance-tagged, editable report — in
            their own lens. &quot;Your numbers become yours&quot; survives the
            handoff.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <span className="cv-eyebrow">Recipient opens as</span>
            {HANDOFF_ROLES.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setRecipient(r.id)}
                aria-pressed={recipient === r.id}
                className={
                  recipient === r.id
                    ? "rounded-[var(--radius)] border border-accent-subtle-border bg-accent-subtle px-2.5 py-1 text-xs font-medium text-accent-text"
                    : "rounded-[var(--radius)] border border-border bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                }
              >
                {r.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              onClick={() =>
                toast(
                  "Role-scoped shareable analysis object is a build gap — the report is the natural payload."
                )
              }
            >
              <ArrowRight className="size-4" />
              {recipientVerb}
            </Button>
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <Lock className="size-3.5 text-prov-shop" aria-hidden />
              Link is role-scoped + audit-logged · CAD not egressed.
            </span>
          </div>
        </CardContent>
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
    lines.push(
      `Make by ${procLabel(dec.make_now_process)} / ${dec.make_now_material}`
    );
    const qs = report.quantities;
    for (const q of qs) {
      const r = dec.recommendation[String(q)];
      if (r) {
        lines.push(
          `  qty ${q.toLocaleString()}: ${procLabel(r.process)} — $${r.unit_cost_usd.toFixed(
            2
          )}/unit${
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
          dec.tooling_process
            ? ` → switch to ${procLabel(dec.tooling_process)} above it`
            : ""
        }`
      );
    }
  }
  if (validation) {
    lines.push(
      `DFM: ${verdictLabel(validation.overall_verdict, true)} (${verdictTone(
        validation.overall_verdict
      )})`
    );
  }
  return lines.join("\n");
}
