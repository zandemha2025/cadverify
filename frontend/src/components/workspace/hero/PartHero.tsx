"use client";

/**
 * PartHero — the D5 "retable" of the single-part loop (FE-2). When the stage flag
 * is on, this replaces the five-tab workspace with the staged hero:
 *
 *     INSPECTION  │   CadViewer stage   │   DECISION      (co-primary columns)
 *
 * around the ONE persistent part. Findings are co-equal with cost, never a tab
 * under it (D1 truth: a design where findings hide behind a tab fails review).
 * The five tabs' content SURVIVES: Routing & DFM → the Inspection depth panel;
 * the Glass Box → the Decision depth panel; Compare / History → the secondary
 * nav. Everything binds to the real /validate + /validate/cost response.
 *
 * The two-way face↔finding wiring (highlightFaces / onFaceClick) is promoted out
 * of the old routing tab so a locate works straight from the hero column and a
 * face-click selects its finding. Canonical dfm-scope keys are used across the
 * column, the stage, and the depth panel so a selection is coherent everywhere.
 *
 * Reveal order = compute order in the showcase tempo (stage → findings stagger →
 * decision rises); instant in the working tempo. All motion is `<Rise>`/`dur()`.
 *
 * This file is only mounted when NEXT_PUBLIC_STAGE_UI is on; flag-off keeps
 * PartWorkspace's tabs untouched.
 */

import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { toast } from "sonner";
import { Scale, History as HistoryIcon, Copy, ExternalLink } from "lucide-react";

import type {
  CostReport,
  CostOptions,
  CostAssumption,
  CostGeometry,
  ShopProfileInfo,
  ValidationResult,
} from "@/lib/api";
import { flattenIssues, partitionDfmByRoute, type IndexedIssue } from "@/lib/dfm-scope";
import { reportCostBlockerLocators } from "@/lib/inspection-bind";
import { deriveBreakeven } from "@/lib/breakeven";
import { deriveFindings } from "@/lib/findings";
import { severityTone, verdictLabel, verdictTone, procLabel } from "@/lib/status";
import type { CalibrationView } from "@/lib/cost-views";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ErrorState } from "@/components/ui/error-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { Rise } from "@/components/ui/motion";

import { RoutingDfmView } from "@/components/workspace/RoutingDfmView";
import { GlassBoxView, type ScenarioSummary } from "@/components/workspace/GlassBoxView";
import { CompareView } from "@/components/workspace/CompareView";
import { UnitWarningBanner } from "@/components/workspace/UnitWarningBanner";
import { CostGeometryInvalidCard } from "@/components/CostDecisionCard";
import { CalibrationBar, RoleLens, type RoleId } from "@/components/glass-box";
import {
  CostOptionsForm,
  validateQty,
  type SetOpt,
} from "@/components/cost/CostOptionsForm";

import { InspectionColumn } from "./InspectionColumn";
import { DecisionColumn } from "./DecisionColumn";
import { DepthPanel } from "./DepthPanel";

const CadViewer = dynamic(() => import("@/components/ui/cad-viewer"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center rounded-[var(--radius)] border border-border bg-muted">
      <p className="text-sm text-muted-foreground">Loading 3D viewer…</p>
    </div>
  ),
});

/* Stage-register face-highlight hues (D5 severity lane). PartHero only mounts
   under the stage flag, so these are the always-on register. */
const SEVERITY_HEX: Record<string, string> = {
  fail: "#e05252",
  warn: "#e5a83b",
  info: "#8fa0a6",
  pass: "#cfa84e",
  neutral: "#78828a",
};

/* reveal choreography (base showcase ms; ×0.1 working, 0 reduced motion) */
const INSPECTION_BASE = 360;
const DECISION_DELAY = 640;

type Depth = "inspection" | "decision" | "compare" | "history" | null;

export interface PartHeroProps {
  file: File;
  report: CostReport | null;
  validation: ValidationResult | null;
  opts: CostOptions;
  setOpt: SetOpt;
  assumptions: CostAssumption[];
  overrideKeys: string[];
  scenarios: (ScenarioSummary & { opts: CostOptions })[];
  shops: ShopProfileInfo[];
  calibration: CalibrationView | null;
  role: RoleId;
  costLoading: boolean;
  dfmLoading: boolean;
  costError: string | null;
  dfmError: string | null;
  geomError: { reason: string | null; geometry: CostGeometry | null } | null;
  onChangeRole: (r: RoleId) => void;
  onSelectShop: (id: string | null) => void;
  onApplyOverride: (key: string, value: number) => void;
  onSetCavities: (v: number) => void;
  onClearOverrides: () => void;
  onSaveScenario: () => void;
  onRecallScenario: (id: string) => void;
  handleRecost: () => void;
  runDfm: (f: File) => void;
  reset: () => void;
}

export function PartHero({
  file,
  report,
  validation,
  opts,
  setOpt,
  assumptions,
  overrideKeys,
  scenarios,
  shops,
  calibration,
  role,
  costLoading,
  dfmLoading,
  costError,
  dfmError,
  geomError,
  onChangeRole,
  onSelectShop,
  onApplyOverride,
  onSetCavities,
  onClearOverrides,
  onSaveScenario,
  onRecallScenario,
  handleRecost,
  runDfm,
  reset,
}: PartHeroProps) {
  // hero owns its own finding selection (canonical dfm-scope keys), decoupled
  // from the flag-off tab path in PartWorkspace.
  const [selectedKey, setSelectedKey] = React.useState<string | null>(null);
  const [depth, setDepth] = React.useState<Depth>(null);
  const [showRecost, setShowRecost] = React.useState(false);

  const recProcess =
    report?.decision?.make_now_process ?? report?.routing?.recommended_process ?? null;

  const breakeven = React.useMemo(
    () => (report ? deriveBreakeven(report) : null),
    [report]
  );

  // ALL issues (canonical keys) for face lookups; the ROUTE subset is displayed.
  const allIssues = React.useMemo(
    () => (validation ? flattenIssues(validation) : []),
    [validation]
  );
  const partition = React.useMemo(
    () => (validation ? partitionDfmByRoute(validation, recProcess) : null),
    [validation, recProcess]
  );
  const heroIssues = React.useMemo(() => partition?.route ?? [], [partition]);

  const findings = React.useMemo(
    () => (report ? deriveFindings(report, breakeven) : []),
    [report, breakeven]
  );

  // Cost-side DFM blockers relinked to locatable rows (the backend relink),
  // deduped across estimates. These share the CadViewer highlight path with the
  // DFM findings via `selectedKey`; their `cost:`-prefixed keys never collide.
  const costLocators = React.useMemo(
    () => (report ? reportCostBlockerLocators(report.estimates) : []),
    [report]
  );

  const selectedIssue = React.useMemo(
    () =>
      allIssues.find((i) => i.key === selectedKey) ??
      costLocators.find((i) => i.key === selectedKey) ??
      null,
    [allIssues, costLocators, selectedKey]
  );

  const highlightFaces = selectedIssue?.faces?.length ? selectedIssue.faces : undefined;
  const highlightColor = selectedIssue
    ? SEVERITY_HEX[severityTone(selectedIssue.issue.severity)]
    : undefined;

  /* ---- two-way wiring (promoted out of the routing tab) ------------ */
  const onFaceClick = React.useCallback(
    (faceIndex: number) => {
      // prefer a visible (route) card, fall back to any candidate-process issue
      const hit =
        heroIssues.find((i) => i.faces.includes(faceIndex)) ??
        allIssues.find((i) => i.faces.includes(faceIndex));
      if (hit) setSelectedKey(hit.key);
    },
    [heroIssues, allIssues]
  );

  const onSelectIssue = React.useCallback(
    (it: IndexedIssue) => setSelectedKey(it.key),
    []
  );

  const onHighlightProcess = React.useCallback(
    (process: string) => {
      const hit =
        allIssues.find((i) => i.issue.process === process && i.faces.length) ??
        allIssues.find((i) => i.issue.process === process);
      if (hit) setSelectedKey(hit.key);
      else toast(`No geometry-linked faces reported for ${procLabel(process)}.`);
    },
    [allIssues]
  );

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

  const geo = validation?.geometry;
  const costGeo = report?.geometry ?? geomError?.geometry ?? null;

  return (
    <div className="min-w-0 flex-1 overflow-y-auto">
      <div className="space-y-5 p-6">
        {/* ── frame header: identity + calibration + role + secondary nav ── */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="cv-eyebrow">Decision · estimate@live</span>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <h1 className="num truncate text-lg font-semibold text-foreground">{file.name}</h1>
              {headerBadge}
            </div>
            <p className="text-xs text-muted-foreground">
              One drop · inspected and costed in-process
            </p>
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
            {/* secondary nav — Compare / History reachable, never the only path */}
            {report && (
              <div className="flex items-center gap-1 rounded-[var(--radius)] border border-border bg-card p-0.5">
                <SecondaryNavButton icon={Scale} label="Compare" onClick={() => setDepth("compare")} />
                <SecondaryNavButton icon={HistoryIcon} label="History" onClick={() => setDepth("history")} />
              </div>
            )}
            <RoleLens value={role} onChange={onChangeRole} />
            <Button variant="secondary" onClick={reset}>
              New part
            </Button>
          </div>
        </div>

        <UnitWarningBanner warnings={report?.unit_warnings} />

        {/* ── the three co-primary columns ─────────────────────────────── */}
        <div className="grid grid-cols-1 gap-5 min-[980px]:grid-cols-[1fr_1.15fr_1fr]">
          {/* INSPECTION (left on desktop) */}
          <div className="min-w-0">
            <InspectionColumn
              issues={heroIssues}
              findings={findings}
              selectedKey={selectedKey}
              onSelect={setSelectedKey}
              analyzing={dfmLoading}
              error={!validation ? dfmError : null}
              onRetry={() => runDfm(file)}
              onOpenDepth={validation ? () => setDepth("inspection") : undefined}
              candidateProcessCount={partition?.candidateProcessCount}
              revealBase={INSPECTION_BASE}
            />
          </div>

          {/* STAGE (centre on desktop, first on mobile — the part leads) */}
          <div className="order-first min-w-0 min-[980px]:order-none min-[980px]:sticky min-[980px]:top-4 min-[980px]:self-start">
            <Rise ms={380}>
              <div className="h-[360px] min-[980px]:h-[440px]">
                <CadViewer
                  file={file}
                  highlightFaces={highlightFaces}
                  highlightColor={highlightColor}
                  ghostUnhighlighted={!!highlightFaces}
                  onFaceClick={onFaceClick}
                />
              </div>
              {costGeo || geo ? (
                <div className="num mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
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
              <p className="cv-eyebrow mt-2">measured · from your geometry</p>
              {selectedIssue && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Highlighting <span className="num text-foreground">{selectedIssue.issue.code}</span>.
                  Click another finding, or a face, to change ·{" "}
                  <button
                    type="button"
                    onClick={() => setSelectedKey(null)}
                    className="text-accent-text underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    clear
                  </button>
                </p>
              )}
            </Rise>
          </div>

          {/* DECISION (right on desktop) */}
          <div className="min-w-0">
            <Rise delay={DECISION_DELAY}>
              {costLoading && !report ? (
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
                <DecisionColumn
                  report={report}
                  breakeven={breakeven}
                  filename={file.name}
                  costBlockers={costLocators}
                  selectedKey={selectedKey}
                  onLocateBlocker={setSelectedKey}
                  onOpenGlassBox={() => setDepth("decision")}
                  onSeeRouting={() => setDepth("inspection")}
                />
              ) : null}
            </Rise>
          </div>
        </div>
      </div>

      {/* ── depth panels (slide-overs) ─────────────────────────────────── */}
      <DepthPanel
        open={depth === "inspection"}
        onOpenChange={(o) => !o && setDepth(null)}
        eyebrow="Inspection · depth"
        title="Per-process DFM audit"
      >
        <RoutingDfmView
          report={report}
          validation={validation}
          selectedIssueKey={selectedKey}
          onSelectIssue={onSelectIssue}
          onHighlightProcess={onHighlightProcess}
        />
      </DepthPanel>

      <DepthPanel
        open={depth === "decision"}
        onOpenChange={(o) => !o && setDepth(null)}
        eyebrow="Decision · depth"
        title="Glass box"
      >
        {report ? (
          <div className="space-y-4">
            {/* adjust inputs & re-cost (real server re-cost) — parity with the tab */}
            <Card className="overflow-hidden">
              <button
                type="button"
                onClick={() => setShowRecost((s) => !s)}
                aria-expanded={showRecost}
                className="w-full px-4 py-3 text-left text-sm font-medium text-muted-foreground hover:text-foreground"
              >
                {showRecost ? "▾" : "▸"} Adjust inputs &amp; re-cost — material · region · complexity · quantities
              </button>
              {showRecost && (
                <div className="space-y-4 border-t border-border px-4 pb-4 pt-3">
                  <CostOptionsForm
                    opts={opts}
                    setOpt={setOpt}
                    qtyError={validateQty(opts.qty)}
                    disabled={costLoading}
                  />
                  <Button onClick={handleRecost} loading={costLoading} disabled={!!validateQty(opts.qty)}>
                    Re-cost with these inputs
                  </Button>
                </div>
              )}
            </Card>
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
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">The glass box opens once the part is costed.</p>
        )}
      </DepthPanel>

      <DepthPanel
        open={depth === "compare"}
        onOpenChange={(o) => !o && setDepth(null)}
        eyebrow="Compare · depth"
        title="Decision board"
      >
        {report ? (
          <CompareView report={report} onDrill={() => setDepth("decision")} />
        ) : (
          <p className="text-sm text-muted-foreground">The decision board opens once the part is costed.</p>
        )}
      </DepthPanel>

      <DepthPanel
        open={depth === "history"}
        onOpenChange={(o) => !o && setDepth(null)}
        eyebrow="History · depth"
        title="Scenarios & decisions"
      >
        <HeroHistory
          report={report}
          validation={validation}
          scenarios={scenarios}
          onRecallScenario={onRecallScenario}
        />
      </DepthPanel>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Small local pieces                                                 */
/* ------------------------------------------------------------------ */

function SecondaryNavButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-sm px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Icon className="size-3.5" />
      {label}
    </button>
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

/**
 * HeroHistory — the History depth surface: this-session scenarios (recall &
 * re-cost) + the durable cost-decision catalog link. Kept compact and local so
 * the flag-off PartWorkspace history path is untouched.
 */
function HeroHistory({
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
      <p className="text-sm text-muted-foreground">
        Scenarios you save this session appear here, alongside your durable cost decisions.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <span className="cv-eyebrow">Saved scenarios · this session</span>
        {scenarios.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Bind a shop or override a rate in the glass box, then “Save as scenario” to compare
            variants of this Decision.
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
          <Link
            href="/cost-decisions"
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ExternalLink className="size-3.5" /> Open cost history
          </Link>
          <Button variant="ghost" onClick={copy} disabled={!summary}>
            <Copy className="size-4" /> Copy decision summary
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
    lines.push(`ProofShape — ${report.filename}`);
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
