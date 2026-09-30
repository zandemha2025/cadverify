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
import { severityLabel, severityTone, verdictLabel, verdictTone, procLabel } from "@/lib/status";
import { parseCalibration, makeNowStableEstimate } from "@/lib/cost-views";
import { costPersistUiEnabled } from "@/lib/cost-decision";
import { flattenIssues } from "@/components/IssueList";
import { CAD_ACCEPT, isSupportedCad, supportedCadLabel } from "@/lib/cad-file";
import { clientStlIntegrityError } from "@/lib/stl-validation";
import { analysisFailureCopy } from "@/lib/verify/failure-copy";
import { C, MONO, procLabel as verifyProcLabel, PROCESS_LABELS } from "@/lib/verify/tokens";
import { listMachines, createMachine, type OwnedMachine } from "@/lib/verify/machine-api";

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
import { UnitWarningBanner } from "@/components/workspace/UnitWarningBanner";
import { CostArtifactBar } from "@/components/instrument/CostArtifactBar";
import {
  CostOptionsForm,
  DEFAULT_COST_OPTIONS,
  validateQty,
} from "@/components/cost/CostOptionsForm";
import { RoleLens, CalibrationBar, roleById, type RoleId } from "@/components/glass-box";
import { useInstrumentChrome, type PartFact } from "@/components/instrument/instrument-chrome";
import { STAGE_UI } from "@/lib/stage-flag";
import type { PinpointOverlay } from "@/components/ui/cad-viewer";
import { groupForIssueKey, groupPinpointIssues } from "@/lib/pinpoint-groups";

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
  // Both analysis requests share one parse but have separate HTTP lifecycles. A
  // canonical /validate 4xx outranks a sibling transport exception.
  const dfmTerminalFailureRef = useRef<string | null>(null);
  const analysisAttemptRef = useRef(0);

  // analyze ↔ geometry linking
  const [selectedIssueKey, setSelectedIssueKey] = useState<string | null>(null);
  const [pendingIssueLink, setPendingIssueLink] = useState<string | null>(null);
  useEffect(() => {
    setPendingIssueLink(new URLSearchParams(window.location.search).get("issue"));
  }, []);
  const [showOptions, setShowOptions] = useState(false);
  const [draggingLanding, setDraggingLanding] = useState(false);
  const landingInputRef = useRef<HTMLInputElement>(null);

  // machine picker (cold start only)
  const [machinePickerOpen, setMachinePickerOpen] = useState(false);
  const [pickerMachines, setPickerMachines] = useState<OwnedMachine[] | null>(null);
  const [selectedMachineId, setSelectedMachineId] = useState<string | null>(null);
  const [addingMachine, setAddingMachine] = useState(false);
  const [newProcess, setNewProcess] = useState(Object.keys(PROCESS_LABELS)[0]);
  const [newMachineName, setNewMachineName] = useState("");
  const [newMachineRate, setNewMachineRate] = useState("");
  const [savingMachine, setSavingMachine] = useState(false);

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
  const pinpointGroups = useMemo(() => groupPinpointIssues(dfmIssues), [dfmIssues]);
  const canonicalIssues = useMemo(
    () => pinpointGroups.map((group) => ({
      key: group.key,
      issue: group.issue,
      faces: group.faces,
    })),
    [pinpointGroups]
  );
  const processImplications = useMemo(
    () => new Map(pinpointGroups.map((group) => [group.key, group.processes] as const)),
    [pinpointGroups]
  );
  const selectedGroup = useMemo(
    () => groupForIssueKey(pinpointGroups, selectedIssueKey)
      ?? pinpointGroups.find((group) => group.key === selectedIssueKey)
      ?? null,
    [pinpointGroups, selectedIssueKey]
  );
  const selectedIssue = selectedGroup
    ? { key: selectedGroup.key, issue: selectedGroup.issue, faces: selectedGroup.faces }
    : null;
  const pinpointOverlays = useMemo<PinpointOverlay[]>(() => {
    if (!validation || !selectedGroup) return [];
    const issue = selectedGroup.issue;
    const units = validation.geometry.units ? ` ${validation.geometry.units}` : "";
    const measured = issue.measured_value;
    return [{
      key: selectedGroup.key,
      code: issue.code,
      severity: selectedGroup.severity,
      faces: selectedGroup.faces,
      regionCenter: selectedGroup.regionCenter,
      valueLabel: measured == null ? issue.code : `${Number(measured.toFixed(3))}${units}`,
      requiredLabel: issue.required_value == null ? null : `${Number(issue.required_value.toFixed(3))}${units}`,
      markerLabel: "",
      suggestion: issue.fix_suggestion ?? issue.message,
      color: selectedGroup.severity === "error" ? SEVERITY_HEX.fail : SEVERITY_HEX.warn,
    }];
  }, [selectedGroup, validation]);
  const selectedIndex = selectedGroup
    ? pinpointGroups.findIndex((group) => group.key === selectedGroup.key)
    : -1;

  const clearPinpoint = useCallback(() => {
    setSelectedIssueKey(null);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("issue");
      window.history.replaceState(window.history.state, "", url);
    }
  }, []);

  const selectPinpoint = useCallback((key: string) => {
    if (key === selectedIssueKey) {
      clearPinpoint();
      return;
    }
    setSelectedIssueKey(key);
    setTab("routing");
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("issue", key);
      window.history.replaceState(window.history.state, "", url);
    }
  }, [clearPinpoint, selectedIssueKey]);

  const selectGroupAt = useCallback((index: number) => {
    const count = pinpointGroups.length;
    if (!count) return;
    selectPinpoint(pinpointGroups[(index + count) % count].key);
  }, [pinpointGroups, selectPinpoint]);

  useEffect(() => {
    if (!selectedGroup) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        clearPinpoint();
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        selectGroupAt(selectedIndex - 1);
      } else if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        selectGroupAt(selectedIndex + 1);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [clearPinpoint, selectGroupAt, selectedGroup, selectedIndex]);

  useEffect(() => {
    if (typeof window === "undefined" || pinpointGroups.length === 0) return;
    const linked = new URLSearchParams(window.location.search).get("issue");
    if (linked && pinpointGroups.some((group) => group.key === linked)) {
      setSelectedIssueKey(linked);
    }
  }, [pinpointGroups]);

  const calibration = useMemo(
    () => (report ? parseCalibration({ ...report, assumptions }) : null),
    [report, assumptions]
  );

  // the resident Inspector anchors to the Decision's make-now recommendation —
  // the number the whole frame is about — and traces it to its governed sources.
  const inspectorEstimate = useMemo(() => {
    if (!report?.decision) return null;
    // Anchor to the make-now route's STABLE (largest, setup-amortized) quantity —
    // the reading the should-cost headline shows — so the Inspector's drivers
    // reconcile to the SAME qty's unit cost. (F5: this used pickEstimate() with no
    // qty, which returns the FIRST/smallest-qty estimate and disagreed with the
    // headline — drivers @qty 100 under a headline @qty 10,000.)
    return makeNowStableEstimate(report);
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

  const runCost = useCallback(async (
    theFile: File,
    theOpts: CostOptions,
    attempt = analysisAttemptRef.current,
  ) => {
    setCostLoading(true);
    setCostError(null);
    setGeomError(null);
    setReport(null);
    try {
      const result = await costEstimate(theFile, theOpts);
      if (attempt !== analysisAttemptRef.current) return;
      setReport(result);
    } catch (err) {
      if (attempt !== analysisAttemptRef.current) return;
      if (err instanceof CostGeometryInvalidError) {
        setGeomError({ reason: err.message, geometry: err.geometry });
      } else {
        setCostError(
          dfmTerminalFailureRef.current ??
            (err instanceof Error ? err.message : "Cost estimate failed."),
        );
      }
    } finally {
      if (attempt === analysisAttemptRef.current) setCostLoading(false);
    }
  }, []);

  const runDfm = useCallback(async (
    theFile: File,
    sourceUnits: CostOptions["units"],
    attempt = analysisAttemptRef.current,
  ) => {
    setDfmLoading(true);
    setDfmError(null);
    setValidation(null);
    setSelectedIssueKey(null);
    try {
      const data = await validateFile(theFile, undefined, undefined, undefined, sourceUnits);
      if (attempt !== analysisAttemptRef.current) return;
      setValidation(data);
    } catch (err) {
      if (attempt !== analysisAttemptRef.current) return;
      const message = err instanceof Error ? err.message : "Analysis failed";
      dfmTerminalFailureRef.current = message;
      setDfmError(message);
      // /validate is the canonical geometry-analysis response. If it refuses the
      // upload, end the sibling cost loader and retain this server diagnosis even
      // when the other streamed request failed at the transport layer.
      setCostError(message);
      setCostLoading(false);
    } finally {
      if (attempt === analysisAttemptRef.current) setDfmLoading(false);
    }
  }, []);

  const handleFile = useCallback(
    async (selected: File) => {
      if (!isSupportedCad(selected.name)) {
        setCostError(`Unsupported file type. Use ${supportedCadLabel()}.`);
        return;
      }
      if (validateQty(opts.qty)) {
        setShowOptions(true);
        setCostError("Fix the quantity list before submitting.");
        return;
      }
      if (selected.name.toLowerCase().endsWith(".stl")) {
        const integrityError = await clientStlIntegrityError(selected);
        if (integrityError) {
          // Keep malformed bytes out of both CadViewer/STLLoader and the API.
          setFile(null);
          setReport(null);
          setValidation(null);
          setCostError(integrityError);
          setDfmError(integrityError);
          return;
        }
      }
      dfmTerminalFailureRef.current = null;
      const attempt = ++analysisAttemptRef.current;
      setFile(selected);
      setTab(landingTab(role));
      void runCost(selected, opts, attempt);
      void runDfm(selected, opts.units, attempt);
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
      void handleFile(initialFile);
    }
    // handleFile is stable enough; we intentionally seed only on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialFile]);

  const handleRecost = useCallback(() => {
    if (!file || validateQty(opts.qty)) return;
    void runCost(file, opts);
    // Source units change geometry, not just price. Re-run DFM from the same
    // declaration so Routing and Decision can never describe different parts.
    void runDfm(file, opts.units);
  }, [file, opts, runCost, runDfm]);

  const reset = useCallback(() => {
    setFile(null);
    setReport(null);
    setGeomError(null);
    setCostError(null);
    setValidation(null);
    setDfmError(null);
    dfmTerminalFailureRef.current = null;
    ++analysisAttemptRef.current;
    setSelectedIssueKey(null);
    setScenarios([]);
    // Part-door mode: hand control back to the door landing instead of showing
    // this workspace's own cold-start dropzone. No-op on flag-off / direct routes.
    onExit?.();
  }, [onExit]);

  const onFaceClick = useCallback(
    (faceIndex: number) => {
      const hit = pinpointGroups.find((group) => group.faces.includes(faceIndex));
      if (hit) {
        selectPinpoint(hit.key);
      }
    },
    [pinpointGroups, selectPinpoint]
  );

  const onHighlightProcess = useCallback(
    (process: string) => {
      const hit = pinpointGroups.find((group) => group.processes.includes(process));
      if (hit) {
        selectPinpoint(hit.key);
      } else {
        toast(`No geometry-linked faces reported for ${procLabel(process)}.`);
      }
    },
    [pinpointGroups, selectPinpoint]
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

  useEffect(() => {
    if (!machinePickerOpen || pickerMachines !== null) return;
    listMachines().then((p) => setPickerMachines(p.machines)).catch(() => setPickerMachines([]));
  }, [machinePickerOpen, pickerMachines]);

  const pickerSelectedMachine = pickerMachines?.find((m) => m.id === selectedMachineId);

  async function handleAddMachine() {
    setSavingMachine(true);
    try {
      const m = await createMachine({ process: newProcess, name: newMachineName.trim() || null, hourly_rate_usd: newMachineRate ? parseFloat(newMachineRate) : null });
      setPickerMachines((prev) => [...(prev ?? []), m]);
      setSelectedMachineId(m.id);
      setAddingMachine(false);
      setNewMachineName("");
      setNewMachineRate("");
    } finally {
      setSavingMachine(false);
    }
  }

  if (!file) {
    const PROCESS_OPTIONS = Object.keys(PROCESS_LABELS);
    const fieldStyle = { width: "100%", boxSizing: "border-box" as const, height: 34, border: `1px solid ${C.hair}`, borderRadius: 8, background: C.bg, padding: "0 10px", fontFamily: "inherit", fontSize: 13, color: C.ink, outline: "none" };

    return (
      <div style={{ flex: 1, overflowY: "auto", padding: "36px 44px", background: C.bg }}>
        <input
          ref={landingInputRef}
          type="file"
          accept={CAD_ACCEPT}
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
            e.target.value = "";
          }}
        />

        <div style={{ maxWidth: 760 }}>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 350, letterSpacing: "-0.02em", lineHeight: 1.25, color: C.ink }}>
            Drop a CAD file — get the decision, then the receipts.
          </h1>
          <p style={{ margin: "10px 0 0", fontSize: 13.5, lineHeight: 1.65, color: C.ink55, maxWidth: 680 }}>
            The manufacturing decision first — make by X, $Y/unit, Z days, switch to a mold above N — with the
            glass-box drivers, geometric routing, and DFM evidence one click away. The resident Inspector traces
            any number to its governed source.
          </p>

          {pendingIssueLink && (
            <div role="status" style={{ marginTop: 16, border: `1px solid ${C.hair}`, borderRadius: 12, background: C.panel, padding: "14px 16px" }}>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: C.ink }}>Issue link ready: {pendingIssueLink}</p>
              <p style={{ margin: "4px 0 0", fontSize: 12, color: C.ink55 }}>Upload the original CAD file to restore this issue. The file is not stored in the URL.</p>
            </div>
          )}

          {/* Drop zone card */}
          <div
            style={{
              marginTop: 28,
              border: `1.5px dashed ${draggingLanding ? C.measured : C.hair}`,
              borderRadius: 18,
              background: draggingLanding ? "rgba(55,114,171,0.04)" : C.panel,
              transition: "border-color 120ms, background 120ms",
              overflow: "hidden",
            }}
          >
            <button
              type="button"
              disabled={costLoading}
              onClick={() => landingInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setDraggingLanding(true); }}
              onDragLeave={() => setDraggingLanding(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDraggingLanding(false);
                const f = e.dataTransfer.files?.[0];
                if (f) handleFile(f);
              }}
              style={{
                width: "100%",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                padding: "44px 32px 36px",
                background: "transparent",
                border: "none",
                cursor: costLoading ? "default" : "pointer",
                fontFamily: "inherit",
                color: "inherit",
                textAlign: "center",
                opacity: costLoading ? 0.6 : 1,
              }}
            >
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke={draggingLanding ? C.measured : C.ink35} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginBottom: 14, transition: "stroke 120ms", flexShrink: 0 }}>
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <p style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: draggingLanding ? C.measured : C.ink, transition: "color 120ms" }}>
                {costLoading ? "Processing…" : "Drag and drop or click to upload"}
              </p>
              <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.035em", color: C.ink45, lineHeight: 1.7 }}>
                STL, STEP, STP, IGES or IGS<br />
                CAD is parsed and discarded in-process · zero egress
              </p>
              {!costLoading && (
                <span style={{ display: "inline-block", marginTop: 20, background: C.ink, color: "#fff", borderRadius: 999, padding: "8px 22px", fontSize: 12.5, fontWeight: 500, pointerEvents: "none" }}>
                  Browse files
                </span>
              )}
            </button>

            {costError && (
              <div style={{ borderTop: `1px solid rgba(190,61,45,0.2)`, background: "rgba(190,61,45,0.04)", padding: "12px 20px", display: "flex", alignItems: "center", gap: 12 }}>
                <p style={{ margin: 0, flex: 1, fontSize: 12.5, color: C.fail }}>{costError}</p>
                <button type="button" onClick={() => setCostError(null)} style={{ border: `1px solid ${C.fail}`, borderRadius: 999, background: "transparent", color: C.fail, padding: "5px 12px", fontFamily: "inherit", fontSize: 11.5, cursor: "pointer" }}>Dismiss</button>
              </div>
            )}

            {/* Costing options accordion */}
            <div style={{ borderTop: `1px solid ${C.hair}` }}>
              <button
                type="button"
                onClick={() => setShowOptions((s) => !s)}
                aria-expanded={showOptions}
                style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "11px 20px", background: "transparent", border: "none", cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "left" }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={C.ink45} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: showOptions ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 160ms", flexShrink: 0 }}>
                  <polyline points="9 18 15 12 9 6" />
                </svg>
                <span style={{ fontFamily: MONO, fontSize: 11, color: C.ink55 }}>Options</span>
                <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink35, marginLeft: 4 }}>optional — sensible defaults applied</span>
              </button>
              {showOptions && (
                <div style={{ padding: "4px 20px 20px" }}>
                  <CostOptionsForm
                    opts={opts}
                    setOpt={setOpt}
                    qtyError={validateQty(opts.qty)}
                    disabled={costLoading}
                  />
                  <div style={{ marginTop: 12 }}>
                    <label style={{ display: "block", fontFamily: MONO, fontSize: 10, letterSpacing: "0.07em", color: C.ink45, marginBottom: 5 }}>
                      YOUR MACHINES
                    </label>
                    <button
                      type="button"
                      onClick={() => { setMachinePickerOpen((o) => !o); setAddingMachine(false); }}
                      style={{ width: "100%", height: 34, border: `1px solid ${C.hair}`, borderRadius: machinePickerOpen ? "8px 8px 0 0" : 8, background: C.bg, padding: "0 10px", fontFamily: MONO, fontSize: 11, color: pickerSelectedMachine ? C.ink : C.measured, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
                    >
                      <span>{pickerSelectedMachine ? `${pickerSelectedMachine.name || verifyProcLabel(pickerSelectedMachine.process)} · ${verifyProcLabel(pickerSelectedMachine.process)}` : "Choose or add a machine"}</span>
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: machinePickerOpen ? "rotate(180deg)" : "none", transition: "transform 160ms" }}>
                        <polyline points="6 9 12 15 18 9" />
                      </svg>
                    </button>
                    {machinePickerOpen && (
                      <div style={{ border: `1px solid ${C.hair}`, borderTop: "none", borderRadius: "0 0 8px 8px", background: C.panel, overflow: "hidden" }}>
                        {pickerMachines === null ? (
                          <p style={{ margin: 0, padding: "10px 12px", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>Loading…</p>
                        ) : pickerMachines.length === 0 && !addingMachine ? (
                          <p style={{ margin: 0, padding: "10px 12px", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>No machines declared yet.</p>
                        ) : (
                          pickerMachines.map((m) => (
                            <button key={m.id} type="button" onClick={() => { setSelectedMachineId(m.id === selectedMachineId ? null : m.id); setMachinePickerOpen(false); }} style={{ width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", background: m.id === selectedMachineId ? "rgba(55,114,171,0.06)" : "transparent", border: "none", borderBottom: `1px solid ${C.hair}`, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                              <span style={{ flex: 1, fontSize: 12.5, color: C.ink }}>{m.name || verifyProcLabel(m.process)}<span style={{ fontFamily: MONO, fontSize: 10, color: C.ink45, marginLeft: 8 }}>{verifyProcLabel(m.process)}</span></span>
                              {m.hourly_rate_usd != null && <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>${m.hourly_rate_usd}/hr</span>}
                              {m.id === selectedMachineId && <span style={{ fontFamily: MONO, fontSize: 10, color: C.measured }}>✓</span>}
                            </button>
                          ))
                        )}
                        {addingMachine ? (
                          <div style={{ padding: "12px", display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8, alignItems: "end", borderTop: pickerMachines && pickerMachines.length > 0 ? `1px solid ${C.hair}` : "none" }}>
                            <div>
                              <label style={{ display: "block", fontFamily: MONO, fontSize: 9.5, color: C.ink45, marginBottom: 4 }}>PROCESS</label>
                              <select value={newProcess} onChange={(e) => setNewProcess(e.target.value)} style={{ ...fieldStyle, height: 32, fontSize: 12 }}>
                                {PROCESS_OPTIONS.map((p) => <option key={p} value={p}>{verifyProcLabel(p)}</option>)}
                              </select>
                            </div>
                            <div>
                              <label style={{ display: "block", fontFamily: MONO, fontSize: 9.5, color: C.ink45, marginBottom: 4 }}>NAME (optional)</label>
                              <input type="text" placeholder="e.g. Haas VF-2" value={newMachineName} onChange={(e) => setNewMachineName(e.target.value)} style={{ ...fieldStyle, height: 32, fontSize: 12 }} />
                            </div>
                            <div>
                              <label style={{ display: "block", fontFamily: MONO, fontSize: 9.5, color: C.ink45, marginBottom: 4 }}>$/HR</label>
                              <input type="number" placeholder="85" value={newMachineRate} onChange={(e) => setNewMachineRate(e.target.value)} style={{ ...fieldStyle, height: 32, fontSize: 12, width: 72 }} />
                            </div>
                            <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8 }}>
                              <button type="button" onClick={() => void handleAddMachine()} disabled={savingMachine} style={{ height: 30, background: C.ink, color: "#fff", border: "none", borderRadius: 6, padding: "0 14px", fontFamily: "inherit", fontSize: 12, fontWeight: 500, cursor: savingMachine ? "default" : "pointer", opacity: savingMachine ? 0.6 : 1 }}>{savingMachine ? "Saving…" : "Save"}</button>
                              <button type="button" onClick={() => setAddingMachine(false)} style={{ height: 30, background: "transparent", color: C.ink55, border: `1px solid ${C.hair}`, borderRadius: 6, padding: "0 12px", fontFamily: "inherit", fontSize: 12, cursor: "pointer" }}>Cancel</button>
                            </div>
                          </div>
                        ) : (
                          <button type="button" onClick={() => setAddingMachine(true)} style={{ width: "100%", padding: "8px 12px", background: "transparent", border: "none", borderTop: pickerMachines && pickerMachines.length > 0 ? `1px solid ${C.hair}` : "none", cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.measured, textAlign: "left" }}>
                            + Add a machine
                          </button>
                        )}
                      </div>
                    )}
                    <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>declared machines set the marginal cost of in-house routes</p>
                  </div>
                </div>
              )}
            </div>
          </div>

        </div>
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
        runDfm={(candidate) => void runDfm(candidate, opts.units)}
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
      <div className="min-w-0 max-w-full flex-1 overflow-x-hidden overflow-y-auto">
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

          <UnitWarningBanner warnings={report?.unit_warnings} />

          <Tabs value={tab} onValueChange={(v) => setTab(v as WorkTab)}>
            <TabsList className="w-full justify-start overflow-x-auto">
              {WORK_TABS.map(({ value, label, icon: Icon }) => (
                <TabsTrigger key={value} value={value}>
                  <Icon className="size-4" />
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>

            <div className="mt-4 grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-5">
              {/* persistent studio-lit part rail (flat platform chrome) */}
              <div className="min-w-0 space-y-3 lg:sticky lg:top-0 lg:col-span-2 lg:self-start">
                <div className="relative h-[340px]">
                  <CadViewer
                    file={file}
                    highlightFaces={highlightFaces}
                    highlightColor={highlightColor}
                    ghostUnhighlighted={!!highlightFaces}
                    onFaceClick={tab === "routing" ? onFaceClick : undefined}
                    pinpointOverlays={tab === "routing" && selectedGroup ? pinpointOverlays : undefined}
                    onSelectPinpoint={selectPinpoint}
                    pinpointCallout={selectedIssue ? {
                      title: `${severityLabel(selectedIssue.issue.severity)} - ${selectedIssue.issue.code}`,
                      detail: "",
                      color: selectedGroup?.severity === "error" ? SEVERITY_HEX.fail : SEVERITY_HEX.warn,
                    } : null}
                  />
                  {tab === "routing" && selectedIssue && (
                    <div
                      data-testid="pinpoint-issue-card"
                      className="absolute bottom-3 left-3 right-3 z-20 rounded-[var(--radius)] border border-border bg-card/95 p-3 shadow-lg backdrop-blur-sm"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="num text-xs font-semibold text-foreground">
                            {severityLabel(selectedIssue.issue.severity)} - {selectedIssue.issue.code}
                          </p>
                          {selectedIssue.issue.measured_value != null && (
                            <p className="num mt-1 text-xs text-muted-foreground">
                              {Number(selectedIssue.issue.measured_value.toFixed(3))} {validation?.geometry.units ?? ""}
                              {selectedIssue.issue.required_value != null && (
                                <> measured - needs {Number(selectedIssue.issue.required_value.toFixed(3))} {validation?.geometry.units ?? ""}</>
                              )}
                            </p>
                          )}
                          <p className="mt-1 text-xs leading-5 text-foreground">
                            {selectedIssue.issue.fix_suggestion ?? selectedIssue.issue.message}
                          </p>
                          {selectedGroup && selectedGroup.processes.length > 0 && (
                            <p className="mt-1 text-[11px] text-muted-foreground">
                              Applies to: {selectedGroup.processes.map(procLabel).join(", ")}
                            </p>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <button type="button" aria-label="Clear selected issue" title="Clear selection (Escape)" className="min-h-9 min-w-9 rounded border border-border hover:bg-muted" onClick={clearPinpoint}>×</button>
                          <button type="button" aria-label="Previous issue" className="min-h-9 min-w-9 rounded border border-border hover:bg-muted" onClick={() => selectGroupAt(selectedIndex - 1)}>‹</button>
                          <span className="num text-[11px] text-muted-foreground">{selectedIndex + 1}/{pinpointGroups.length}</span>
                          <button type="button" aria-label="Next issue" className="min-h-9 min-w-9 rounded border border-border hover:bg-muted" onClick={() => selectGroupAt(selectedIndex + 1)}>›</button>
                        </div>
                      </div>
                    </div>
                  )}
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
                      title={analysisFailureCopy(dfmError).title}
                      message={`${analysisFailureCopy(dfmError).explanation} ${analysisFailureCopy(dfmError).action}`}
                      onRetry={() => file && void handleFile(file)}
                    />
                  ) : (
                    <RoutingDfmView
                      report={report}
                      validation={validation}
                      selectedIssueKey={selectedIssueKey}
                      onSelectIssue={(it) => selectPinpoint(it.key)}
                      onHighlightProcess={onHighlightProcess}
                      canonicalIssues={canonicalIssues}
                      processImplications={processImplications}
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
