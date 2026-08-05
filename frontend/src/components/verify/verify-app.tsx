"use client";

/**
 * The Verify workspace is wired to the real engine and mounted inside the shared
 * authenticated ProofShape shell. This component owns only Verify-local screens
 * and tools; platform navigation, theme, search, and account controls live in the
 * common shell.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import Link from "next/link";
import { C, MONO, SANS } from "@/lib/verify/tokens";
import {
  QTY_LADDER,
  retryVerificationCost,
  runVerification,
  type VerifyResult,
} from "@/lib/verify/run";
import { geometryFromResult } from "@/lib/verify/pipeline";
import { isCurrentRun } from "@/lib/verify/run-gates";
import { listMachines } from "@/lib/verify/machine-api";
import { CAD_ACCEPT, isSupportedCad, unsupportedCadGuidance } from "@/lib/cad-file";
import { VERIFY_PART_CAD_INPUT } from "@/lib/verify/file-inputs";
import { Stage, type StageAssembly } from "./stage";
import { AssemblyPanel } from "./assembly-panel";
import { fetchAssembly, fetchAssemblyAnalysis, defaultPartOfInterest, type AssemblyRender, type AssemblyAnalysis } from "@/lib/verify/assembly";
import { VerifyScreen } from "./verify-screen";
import { MachinesScreen } from "./machines-screen";
import { RecordsScreen } from "./records-screen";
import { CatalogScreen } from "./catalog-screen";
import { CompareScreen } from "./compare-screen";
import { TriageScreen } from "./triage-screen";
import { CalibrationScreen } from "./calibration-screen";
import { HomeScreen } from "./home-screen";
import { ProgramScreen } from "./program-screen";
import { CommandPalette } from "./command-surfaces";
import { AcquisitionModal } from "./acquisition-modal";
import { PartScreen } from "./part-screen";
import { ToastProvider } from "./toast";
import { ShortcutsOverlay } from "./shortcuts-overlay";
import { CalibrationSwitcher } from "./calibration-switcher";
import { WelcomeGuide, WELCOME_STORAGE_KEY } from "./welcome-guide";
import { GuidedResultSummary } from "./guided-result-summary";
import { sampleBracketFile } from "@/lib/verify/sample-cad";
import { designIdFromSearch, designRevisionFromSearch, importDesignStep } from "@/lib/verify/design-import";
import {
  workspaceScreenFromSearch,
  type WorkspaceScreen,
} from "@/lib/verify/workspace-screen-route";
import type { OrganizationAccess } from "@/lib/organization-access";

// The shared hotkey nav map — matches the design 1:1 (support.js keydown handler):
// H/V/P/R/G/M/T/C jump between the surfaces, `?` opens the shortcuts sheet. `c`
// (Calibration & truth) is the `calibration` screen; `p` is the Parts catalog.
const HOTKEY_NAV: Record<string, Screen> = {
  h: "home",
  v: "verify",
  p: "catalog",
  r: "records",
  g: "programs",
  m: "machines",
  t: "triage",
  c: "calibration",
};

type Screen = WorkspaceScreen | "part" | "program" | "acquisition" | "palette";

const RAIL: { key: Screen; label: string; d: string }[] = [
  { key: "home", label: "Home", d: "M3 10.5 12 3l9 7.5M5 9v11h14V9" },
  { key: "verify", label: "Verify", d: "M20 6 9 17l-5-5M4 6h5M4 12h2" },
  { key: "catalog", label: "Parts", d: "M21 8 12 3 3 8l9 5zM3 8v8l9 5 9-5V8M12 13v8" },
  { key: "records", label: "Records", d: "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7ZM14 2v4a2 2 0 0 0 2 2h4M8 13h8M8 17h5" },
  { key: "programs", label: "Programs", d: "M3 5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" },
  { key: "machines", label: "Your machines", d: "M3 8h18v12H3zM7 8V5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v3M14 13h4M14 16h4" },
  { key: "triage", label: "Triage", d: "M4 5h16M6 12h12M9 19h6" },
  { key: "calibration", label: "Calibration & truth", d: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M2 14h4M10 8h4M18 16h4" },
];

export function VerifyApp({
  organizationAccess,
}: {
  organizationAccess: OrganizationAccess | null;
}) {
  const activeOrganization = organizationAccess?.organizations.find(
    (org) => org.orgId === organizationAccess.activeOrgId,
  ) ?? null;
  const hasActiveOrganization = activeOrganization !== null;
  const [screen, setScreen] = useState<Screen>("home");
  const [welcomeOpen, setWelcomeOpen] = useState(false);
  const [guidedSampleState, setGuidedSampleState] = useState<
    "idle" | "running" | "ready" | "error"
  >("idle");
  const [guidedSummaryOpen, setGuidedSummaryOpen] = useState(false);
  const [env, setEnv] = useState({ temp: false, sour: false, pressure: false });
  const [materialClass, setMaterialClass] = useState("polymer");
  const [materialTouched, setMaterialTouched] = useState(false);
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [running, setRunning] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadRejection, setUploadRejection] = useState<{
    fileName: string;
    title: string;
    action: string;
  } | null>(null);
  // Multi-part assembly render (>= 2 solids): the combined GLB + product tree.
  // null for single parts, which keep the existing single-shell path untouched.
  const [assembly, setAssembly] = useState<AssemblyRender | null>(null);
  const [assemblySelectedId, setAssemblySelectedId] = useState<string | null>(null);
  // The REAL P3 per-part analysis (verdict + should-cost + interference), fetched
  // separately from the fast render because it runs the cost engine on every solid
  // (~15s on AS1). null until it lands; `assemblyAnalyzing` drives the honest
  // "analysing per-part…" state while it is in flight.
  const [assemblyAnalysis, setAssemblyAnalysis] = useState<AssemblyAnalysis | null>(null);
  const [assemblyAnalyzing, setAssemblyAnalyzing] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  // A REAL signal for the rail footer: are any of the org's machines declaring an
  // hourly rate (i.e. a shop rate is actually bound)? null while loading → the dot
  // stays hollow/neutral until a bound rate is detected — never a hardcoded claim.
  const [ratesBound, setRatesBound] = useState<boolean | null>(null);
  const [designImport, setDesignImport] = useState<
    | { state: "loading"; message: string }
    | { state: "running"; message: string }
    | { state: "ready"; message: string }
    | { state: "error"; message: string }
    | null
  >(null);
  const designImportStarted = useRef(false);
  const workspaceDestinationApplied = useRef(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  // The last part the user verified — so a change to the declared world can re-run
  // the verification (re-persist the env + re-cost against it) for the same part.
  const latestFile = useRef<File | null>(null);
  // Monotonic run token. Selecting a material class (or toggling the world) while a
  // prior verification is still in flight dispatches a NEW run; without this guard the
  // two async runs can resolve OUT OF ORDER and a stale result clobbers the fresh one
  // — the material-chip race where the walk still reads "Polymer" after clicking Steel.
  // Only the latest-dispatched run is allowed to write result/running state.
  const runSeq = useRef(0);
  // The sample owns a separate UI lifecycle. Leaving it or starting personal CAD
  // invalidates its completion callback even if the underlying request finishes.
  const guidedRunSeq = useRef(0);

  const nav = useCallback((s: string) => {
    if (s !== "verify") {
      ++guidedRunSeq.current;
      setGuidedSampleState("idle");
      setGuidedSummaryOpen(false);
    }
    if (s === "acquisition") return setScreen("acquisition");
    if (s === "palette") return setScreen("palette");
    setScreen(s as Screen);
  }, []);

  const pickFile = useCallback(() => fileRef.current?.click(), []);
  const pickOwnFile = useCallback(() => {
    ++guidedRunSeq.current;
    setGuidedSampleState("idle");
    setGuidedSummaryOpen(false);
    fileRef.current?.click();
  }, []);

  const runVerify = useCallback(
    async (f: File): Promise<VerifyResult | null> => {
      if (!isSupportedCad(f.name)) {
        const guidance = unsupportedCadGuidance(f.name);
        ++runSeq.current;
        latestFile.current = null;
        setFile(null);
        setScreen("verify");
        setRunning(false);
        setResult(null);
        setUploadRejection({ fileName: f.name, ...guidance });
        setAssembly((prev) => {
          prev?.revoke();
          return null;
        });
        setAssemblySelectedId(null);
        setAssemblyAnalysis(null);
        setAssemblyAnalyzing(false);
        return null;
      }

      const seq = ++runSeq.current;
      setUploadRejection(null);
      setFile(f);
      latestFile.current = f;
      setScreen("verify");
      setRunning(true);
      setResult(null);
      // Reset any prior assembly render (revoke its GLB object URL).
      setAssembly((prev) => {
        prev?.revoke();
        return null;
      });
      setAssemblySelectedId(null);
      setAssemblyAnalysis(null);
      setAssemblyAnalyzing(false);

      // Resolve STEP/IGES assembly structure before dispatching the single-part
      // pipeline. The old parallel path knowingly sent real assemblies through
      // /validate/cost too, producing a browser-visible 400 before the successful
      // assembly result replaced it. A successful assembly now makes only its
      // three truthful requests: structured model, renderable GLB, and per-part
      // analysis. Single solids and non-assembly formats continue below.
      const asm = await fetchAssembly(f).catch(() => null);
      if (runSeq.current !== seq) {
        asm?.revoke();
        return null;
      }
      if (asm) {
        setAssembly(asm);
        setAssemblySelectedId(defaultPartOfInterest(asm.model.parts));
        setRunning(false);
        // The heavier per-part analysis (real DFM + should-cost + interference
        // on every solid, ~15s) now runs; the render is already up. Guarded by
        // the same run token so a superseded upload never merges stale analysis.
        setAssemblyAnalyzing(true);
        void fetchAssemblyAnalysis(f)
          .then((analysis) => {
            if (runSeq.current !== seq) return;
            setAssemblyAnalysis(analysis);
            setAssemblyAnalyzing(false);
          })
          .catch(() => {
            if (runSeq.current !== seq) return;
            setAssemblyAnalyzing(false);
          });
        return null;
      }

      let progressiveResult: VerifyResult | null = null;
      try {
        const r = await runVerification(
          { file: f, env, materialClass },
          {
            onValidation: ({ validation, validationError }) => {
              if (runSeq.current !== seq || !validation) return;
              // First useful answer: render real routing + DFM while the
              // sequential should-cost request continues in the background.
              const nextResult: VerifyResult = {
                file: f,
                validation,
                validationError,
                cost: null,
                costGeometryInvalid: null,
                costError: null,
                machines: [],
                machinesError: null,
                verification: null,
                quantities: QTY_LADDER,
                env,
                envDeclared: env.temp || env.sour || env.pressure,
                envCaptured: false,
                envError: null,
                meshHash: null,
                partContext: null,
                partContextError: null,
              };
              progressiveResult = nextResult;
              setResult(nextResult);
            },
          }
        );
        // Drop a result that a newer run has superseded — last dispatch wins, so the
        // displayed verdict/material always matches the most recent selection.
        if (runSeq.current === seq) {
          setResult(r);
          return r;
        }
        return null;
      } catch (caught) {
        if (runSeq.current === seq) {
          const message =
            caught instanceof Error ? caught.message : "Verification could not finish";
          // The progress callback runs asynchronously; keep its last real value
          // even though TypeScript cannot narrow callback assignments here.
          const preserved = progressiveResult as VerifyResult | null;
          const failedResult: VerifyResult = preserved
            ? { ...preserved, costError: message }
            : {
                file: f,
                validation: null,
                validationError: message,
                cost: null,
                costGeometryInvalid: null,
                costError: message,
                machines: [],
                machinesError: null,
                verification: null,
                quantities: QTY_LADDER,
                env,
                envDeclared: env.temp || env.sour || env.pressure,
                envCaptured: false,
                envError: null,
                meshHash: null,
                partContext: null,
                partContextError: null,
              };
          setResult(failedResult);
          return failedResult;
        }
        return null;
      } finally {
        if (runSeq.current === seq) setRunning(false);
      }
    },
    [env, materialClass]
  );

  const onReverify = useCallback(() => {
    if (file) void runVerify(file);
    else pickFile();
  }, [file, runVerify, pickFile]);

  const onRetryCost = useCallback(async () => {
    if (!file || !result?.validation) {
      onReverify();
      return;
    }
    const seq = ++runSeq.current;
    const previous = result;
    setRunning(true);
    try {
      const retried = await retryVerificationCost(
        { file, env, materialClass },
        previous.machines,
        previous.partContext?.annual_volume
      );
      if (runSeq.current === seq) setResult({ ...previous, ...retried });
    } finally {
      if (runSeq.current === seq) setRunning(false);
    }
  }, [env, file, materialClass, onReverify, result]);

  const runSample = useCallback(() => {
    const guidedSeq = ++guidedRunSeq.current;
    setScreen("verify");
    setGuidedSampleState("running");
    setGuidedSummaryOpen(false);
    void runVerify(sampleBracketFile()).then((sampleResult) => {
      if (!isCurrentRun(guidedSeq, guidedRunSeq.current)) return;
      if (sampleResult?.validation || sampleResult?.cost || sampleResult?.costGeometryInvalid) {
        setGuidedSampleState("ready");
        setGuidedSummaryOpen(true);
      } else {
        setGuidedSampleState("error");
      }
    });
  }, [runVerify]);

  const rememberWelcomeSeen = useCallback(() => {
    try {
      window.localStorage.setItem(WELCOME_STORAGE_KEY, "1");
    } catch {
      // Private browsing can disable storage. The guide still works this visit.
    }
  }, []);

  const closeWelcome = useCallback(() => {
    rememberWelcomeSeen();
    setWelcomeOpen(false);
  }, [rememberWelcomeSeen]);

  const startGuidedSample = useCallback(() => {
    closeWelcome();
    runSample();
  }, [closeWelcome, runSample]);

  const startOwnUpload = useCallback(() => {
    closeWelcome();
    pickOwnFile();
  }, [closeWelcome, pickOwnFile]);

  const startDesign = useCallback(() => {
    rememberWelcomeSeen();
    window.location.assign("/designs");
  }, [rememberWelcomeSeen]);

  const startMachines = useCallback(() => {
    closeWelcome();
    setScreen("machines");
  }, [closeWelcome]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const forced = params.get("welcome") === "1";
    let seen = false;
    try {
      seen = window.localStorage.getItem(WELCOME_STORAGE_KEY) === "1";
    } catch {
      seen = false;
    }
    if (forced || !seen) setWelcomeOpen(true);
    if (forced) {
      params.delete("welcome");
      const next = params.toString();
      window.history.replaceState(null, "", `${window.location.pathname}${next ? `?${next}` : ""}`);
    }
  }, []);

  useEffect(() => {
    if (workspaceDestinationApplied.current) return;
    workspaceDestinationApplied.current = true;
    const destination = workspaceScreenFromSearch(window.location.search);
    if (destination) setScreen(destination);
  }, []);

  // Design Studio handoff: load the exact authenticated STEP revision and feed
  // it through the same File-based verification path as a manual upload. The
  // generated artifact gets no privileged shortcut through DFM or costing.
  useEffect(() => {
    if (!hasActiveOrganization) return;
    if (designImportStarted.current) return;
    const rawDesignId = new URLSearchParams(window.location.search).get("design");
    if (!rawDesignId) return;
    designImportStarted.current = true;
    const designId = designIdFromSearch(window.location.search);
    if (!designId) {
      setDesignImport({ state: "error", message: "That Design Studio link is invalid." });
      return;
    }
    const rawRevision = new URLSearchParams(window.location.search).get("revision");
    const revisionNo = designRevisionFromSearch(window.location.search);
    if (rawRevision !== null && revisionNo === null) {
      setDesignImport({ state: "error", message: "That design revision is invalid." });
      return;
    }
    setDesignImport({ state: "loading", message: "Loading the generated STEP revision…" });
    void importDesignStep(designId, fetch, revisionNo)
      .then(async (imported) => {
        setDesignImport({ state: "running", message: `Imported ${imported.name}. Verification is running.` });
        await runVerify(imported);
        setDesignImport({ state: "ready", message: `Imported ${imported.name}. Verification finished.` });
      })
      .catch((caught) => {
        setDesignImport({
          state: "error",
          message: caught instanceof Error ? caught.message : "Could not import this design.",
        });
      });
  }, [hasActiveOrganization, runVerify]);

  // The rail footer's bound-rate signal.
  useEffect(() => {
    if (!hasActiveOrganization) {
      setRatesBound(null);
      return;
    }
    listMachines().then(
      (p) => setRatesBound(p.machines.some((m) => typeof m.hourly_rate_usd === "number" && Number.isFinite(m.hourly_rate_usd))),
      () => setRatesBound(false)
    );
  }, [hasActiveOrganization]);

  // The environment door is REAL: when the declared world changes and a part is
  // loaded, re-run the verification so the new world is persisted to the part's
  // record and the cost/verdict are recomputed against it. Skips the first mount.
  const firstEnv = useRef(true);
  useEffect(() => {
    if (firstEnv.current) {
      firstEnv.current = false;
      return;
    }
    if (latestFile.current) void runVerify(latestFile.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [env]);

  const firstMaterial = useRef(true);
  useEffect(() => {
    if (firstMaterial.current) {
      firstMaterial.current = false;
      return;
    }
    if (latestFile.current) void runVerify(latestFile.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [materialClass]);

  // hotkeys — ⌘K palette · H/V/P/R/G/M/T/C nav · ? shortcuts · Esc closes all
  // (matches the design's keydown handler in support.js). Typing in a field never
  // triggers nav; modifier chords other than ⌘K are left to the browser.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = ((e.target as HTMLElement | null)?.tagName ?? "").toLowerCase();
      const typing = tag === "input" || tag === "textarea" || tag === "select";
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setShortcutsOpen(false);
        setScreen((s) => (s === "palette" ? "home" : "palette"));
        return;
      }
      if (e.key === "Escape") {
        setShortcutsOpen(false);
        setScreen((s) => (s === "palette" || s === "acquisition" ? "verify" : s));
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      const target = HOTKEY_NAV[k];
      if (target) {
        setShortcutsOpen(false);
        setScreen(target);
      } else if (e.key === "?") {
        setShortcutsOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The stage's assembly overlay: the highlighted part's name + tree path for the
  // in-canvas label. null when the upload is a single part (unchanged path).
  const stageAssembly = useMemo<StageAssembly | null>(() => {
    if (!assembly) return null;
    const sel = assembly.model.parts.find((p) => p.id === assemblySelectedId) ?? null;
    return {
      glbUrl: assembly.glbUrl,
      selectedId: assemblySelectedId,
      partCount: assembly.model.part_count,
      selectedName: sel ? sel.name || sel.occurrence || sel.id : null,
      selectedTreePath: sel?.tree_path ?? null,
      analysisReady: !!assemblyAnalysis,
    };
  }, [assembly, assemblySelectedId, assemblyAnalysis]);
  const stageGeometry = result ? geometryFromResult(result) : null;

  const activeWorkspaceSection: Screen =
    screen === "compare" || screen === "part"
      ? "catalog"
      : screen === "program"
        ? "programs"
        : RAIL.some((item) => item.key === screen)
          ? screen
          : "home";

  if (!hasActiveOrganization) {
    return <OrganizationAccessGate access={organizationAccess} />;
  }

  return (
    <ToastProvider>
    <div className="cv-verify-shell" style={{ height: "100%", minHeight: 0, display: "flex", flexDirection: "column", background: C.bg, color: C.ink, fontFamily: SANS, WebkitFontSmoothing: "antialiased", fontSize: 14 }}>
      <style>{KEYFRAMES}</style>
      <input
        ref={fileRef}
        id={VERIFY_PART_CAD_INPUT.id}
        name={VERIFY_PART_CAD_INPUT.name}
        data-testid={VERIFY_PART_CAD_INPUT.testId}
        aria-label={VERIFY_PART_CAD_INPUT.ariaLabel}
        type="file"
        accept={`${CAD_ACCEPT},model/stl,application/step`}
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) {
            setGuidedSampleState("idle");
            setGuidedSummaryOpen(false);
            void runVerify(f);
          }
          e.target.value = "";
        }}
      />

      <WelcomeGuide
        open={welcomeOpen}
        onOpenChange={(open) => {
          if (open) setWelcomeOpen(true);
          else closeWelcome();
        }}
        onSample={startGuidedSample}
        onUpload={startOwnUpload}
        onDesign={startDesign}
        onMachines={startMachines}
      />
      <GuidedResultSummary
        open={guidedSummaryOpen}
        result={result}
        onOpenChange={setGuidedSummaryOpen}
        onUpload={pickOwnFile}
        onBack={() => {
          setGuidedSummaryOpen(false);
          nav("home");
        }}
      />

      {/* Verify-local navigation. Platform navigation stays in AppShell. */}
      <nav className="cv-verify-workspace-nav" aria-label="Verify workspace sections" style={{ minHeight: 52, flexShrink: 0, borderBottom: `1px solid ${C.hair2}`, background: C.panel, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "6px 14px" }}>
        <div className="cv-verify-workspace-tabs" style={{ display: "flex", alignItems: "center", gap: 4, minWidth: 0, overflowX: "auto" }}>
        {RAIL.map((r) => {
          const active = screen === r.key || (r.key === "catalog" && screen === "compare");
          return (
            <button
              key={r.key}
              type="button"
              aria-label={r.label}
              onClick={() => nav(r.key)}
              title={r.label}
              className="cv-verify-rail-button"
              style={{ minWidth: 44, height: 38, padding: "0 10px", borderRadius: 9, border: active ? `1px solid ${C.hair}` : "1px solid transparent", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 7, background: active ? "#eceef1" : "transparent", color: active ? C.ink : C.ink50, transition: "background-color 150ms, color 150ms, border-color 150ms", whiteSpace: "nowrap", fontFamily: "inherit", fontSize: 12 }}
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d={r.d} />
              </svg>
              <span className="cv-verify-rail-label">{r.label}</span>
            </button>
          );
        })}
        </div>
        <select
          className="cv-verify-mobile-section"
          aria-label="Verify workspace section"
          value={activeWorkspaceSection}
          onChange={(event) => nav(event.target.value)}
        >
          {RAIL.map((item) => (
            <option key={item.key} value={item.key}>{item.label}</option>
          ))}
        </select>
        <div className="cv-verify-workspace-actions" style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <button
            type="button"
            onClick={() => setScreen("calibration")}
            title={
              ratesBound
                ? "Your shop rates are bound · ● SHOP — open Calibration & truth"
                : "Calibration & truth — no shop rate bound yet"
            }
            className="cv-verify-rate-dot"
            style={{ width: 36, height: 36, border: `1px solid ${C.hair}`, borderRadius: 999, background: "#fff", padding: 4, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}
          >
            <span
              aria-hidden
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                display: "block",
                background: ratesBound ? C.shop : "transparent",
                border: ratesBound ? "none" : `1.5px solid ${C.ink40}`,
              }}
            />
          </button>
          <span className="cv-verify-rate-switcher"><CalibrationSwitcher onOpenCalibration={() => setScreen("calibration")} /></span>
          <button
            className="cv-verify-start-button"
            type="button"
            onClick={() => setWelcomeOpen(true)}
            style={{ minHeight: 36, border: `1px solid ${C.measured}`, background: "rgba(55,114,171,0.06)", color: C.measured, borderRadius: 999, padding: "7px 13px", fontFamily: "inherit", fontSize: 11.5, fontWeight: 650, cursor: "pointer" }}
          >
            Start here
          </button>
          <button className="cv-verify-command-button" type="button" onClick={() => setScreen("palette")} title="Verify commands (⌘K)" aria-label="Open Verify command palette" style={{ display: "inline-flex", alignItems: "center", gap: 6, minHeight: 36, border: `1px solid ${C.hair}`, background: "#fff", borderRadius: 999, padding: "7px 12px", fontFamily: MONO, fontSize: 11, color: C.ink55, cursor: "pointer" }}>Jump <span aria-hidden>⌘K</span></button>
          <button className="cv-verify-primary-action" type="button" onClick={pickOwnFile} style={{ minHeight: 36, background: C.ink, color: "#fff", border: "none", borderRadius: 999, padding: "8px 16px", fontSize: 13, fontWeight: 500, cursor: "pointer", fontFamily: "inherit" }}>Check my CAD</button>
        </div>
      </nav>

      {/* main */}
      <div className="cv-verify-main" style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {uploadRejection && (
          <div
            role="alert"
            data-testid="verify-upload-rejection"
            style={{
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "12px 20px",
              borderBottom: "1px solid #e6b8b8",
              background: "#fff2f2",
              color: "#7e2929",
            }}
          >
            <div style={{ minWidth: 0 }}>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 650 }}>{uploadRejection.title}</p>
              <p style={{ margin: "4px 0 0", fontSize: 12, lineHeight: 1.5 }}>
                <span style={{ fontFamily: MONO }}>{uploadRejection.fileName}</span> was not uploaded. {uploadRejection.action}{" "}
                No analysis was started and no record was created.
              </p>
            </div>
            <button
              type="button"
              onClick={pickOwnFile}
              style={{ marginLeft: "auto", flexShrink: 0, minHeight: 40, border: "1px solid currentColor", borderRadius: 999, background: "#fff", color: "inherit", padding: "8px 14px", cursor: "pointer", fontFamily: "inherit", fontWeight: 600 }}
            >
              Choose a STEP export
            </button>
            <button
              type="button"
              aria-label="Dismiss unsupported file guidance"
              onClick={() => setUploadRejection(null)}
              style={{ flexShrink: 0, width: 40, height: 40, border: 0, background: "transparent", color: "inherit", cursor: "pointer", fontSize: 20 }}
            >
              ×
            </button>
          </div>
        )}
        {designImport && (
          <div
            role={designImport.state === "error" ? "alert" : "status"}
            style={{
              minHeight: 38,
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 20px",
              borderBottom: `1px solid ${designImport.state === "error" ? "#e6b8b8" : C.hair2}`,
              background: designImport.state === "error" ? "#fff2f2" : C.sunken,
              color: designImport.state === "error" ? "#9f2f2f" : C.ink55,
              fontSize: 12,
              fontFamily: MONO,
            }}
          >
            {(designImport.state === "loading" || designImport.state === "running") && <span aria-hidden style={{ animation: "vspin 1s linear infinite" }}>◌</span>}
            <span>{designImport.message}</span>
            {designImport.state === "error" && (
              <Link href="/designs" style={{ marginLeft: "auto", color: "inherit", fontWeight: 600 }}>
                Return to Design Studio
              </Link>
            )}
            {designImport.state === "ready" && (
              <button type="button" onClick={() => setDesignImport(null)} style={{ marginLeft: "auto", border: 0, background: "transparent", color: "inherit", cursor: "pointer", fontFamily: "inherit" }}>
                Dismiss
              </button>
            )}
          </div>
        )}

        {guidedSampleState !== "idle" && screen === "verify" && (
          <GuidedExampleBar
            state={guidedSampleState}
            onUpload={pickOwnFile}
            onBack={() => {
              setGuidedSummaryOpen(false);
              nav("home");
            }}
            onRetry={runSample}
          />
        )}

        {screen === "home" && (
          <HomeScreen
            onPickFile={pickOwnFile}
            onDropFile={(dropped) => {
              ++guidedRunSeq.current;
              setGuidedSampleState("idle");
              setGuidedSummaryOpen(false);
              void runVerify(dropped);
            }}
            onSample={startGuidedSample}
            onOpenGuide={() => setWelcomeOpen(true)}
            nav={nav}
          />
        )}
        {screen === "verify" && (
          <div className="cv-verify-screen-split" style={{ flex: 1, minHeight: 0, display: "flex" }}>
            <Stage
              file={file}
              partName={result?.file?.name ?? file?.name ?? "No part yet"}
              meta1={
                stageAssembly
                  ? `assembly · ${stageAssembly.partCount} parts in world position`
                  : stageGeometry
                  ? `Ø/bbox ${stageGeometry.bbox_mm.map((n) => n.toFixed(1)).join(" × ")} mm · ${stageGeometry.volume_cm3.toFixed(2)} cm³`
                  : running
                    ? "measuring geometry…"
                    : "drop STL, STEP or IGES to measure"
              }
              meta2={
                stageAssembly
                  ? undefined
                  : stageGeometry
                  ? `watertight ${String(stageGeometry.watertight)} · ● MEASURED`
                  : undefined
              }
              bbox={stageGeometry?.bbox_mm ?? null}
              hostile={env.temp || env.sour || env.pressure}
              autoOrbit={running && !stageAssembly}
              context={result?.partContext ?? null}
              contextError={result?.partContextError ?? null}
              assembly={stageAssembly}
            />
            {stageAssembly && assembly ? (
              <AssemblyPanel
                model={assembly.model}
                fileName={file?.name ?? null}
                selectedId={assemblySelectedId}
                onSelect={setAssemblySelectedId}
                analysis={assemblyAnalysis}
                analyzing={assemblyAnalyzing}
              />
            ) : (
              <VerifyScreen
                result={result}
                running={running}
                guided={guidedSampleState !== "idle"}
                fileName={result?.file?.name ?? file?.name ?? null}
                env={env}
                setEnv={setEnv}
                materialClass={materialClass}
                materialProvenance={materialTouched ? "USER" : "DEFAULT"}
                setMaterialClass={(next) => {
                  // The backend contract treats "polymer" as the undeclared
                  // default; do not label it USER until the API can preserve an
                  // explicit-default declaration separately.
                  setMaterialTouched(next !== "polymer");
                  setMaterialClass(next);
                }}
                onPickFile={pickOwnFile}
                onReverify={onReverify}
                onRetryCost={onRetryCost}
                nav={nav}
              />
            )}
          </div>
        )}
        {screen === "machines" && <MachinesScreen nav={nav} />}
        {screen === "records" && <RecordsScreen nav={nav} />}
        {screen === "catalog" && <CatalogScreen nav={nav} />}
        {screen === "part" && <PartScreen nav={nav} />}
        {screen === "compare" && <CompareScreen nav={nav} />}
        {(screen === "programs" || screen === "program") && <ProgramScreen nav={nav} screen={screen} />}
        {screen === "triage" && <TriageScreen nav={nav} />}
        {screen === "calibration" && <CalibrationScreen />}
      </div>

      {screen === "acquisition" && <AcquisitionModal onClose={() => setScreen("verify")} result={result} nav={nav} />}
      {screen === "palette" && (
        <CommandPalette
          onClose={() => setScreen("home")}
          nav={nav}
          onVerify={pickOwnFile}
          onSample={startGuidedSample}
          onShortcuts={() => { setScreen("home"); setShortcutsOpen(true); }}
        />
      )}
      {shortcutsOpen && <ShortcutsOverlay onClose={() => setShortcutsOpen(false)} />}
    </div>
    </ToastProvider>
  );
}

function GuidedExampleBar({
  state,
  onUpload,
  onBack,
  onRetry,
}: {
  state: "running" | "ready" | "error";
  onUpload: () => void;
  onBack: () => void;
  onRetry: () => void;
}) {
  const failed = state === "error";
  return (
    <section
      role={failed ? "alert" : "status"}
      data-testid="guided-example-status"
      className="cv-verify-guided-bar"
      style={{
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 14,
        flexWrap: "wrap",
        borderBottom: `1px solid ${failed ? "rgba(150,102,20,0.36)" : "rgba(55,114,171,0.3)"}`,
        background: failed ? "#fff8ea" : "#eef5fb",
        padding: "11px 18px",
        color: C.ink,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 26,
          height: 26,
          flexShrink: 0,
          display: "grid",
          placeItems: "center",
          borderRadius: "50%",
          background: failed ? C.cond : C.measured,
          color: "#fff",
          fontFamily: MONO,
          fontSize: 11,
        }}
      >
        {state === "running" ? "1" : failed ? "!" : "✓"}
      </span>
      <div style={{ flex: 1, minWidth: 240 }}>
        <p style={{ margin: 0, fontSize: 12.5, fontWeight: 650 }}>
          {state === "running"
            ? "Guided example: analyzing a real routing bracket"
            : failed
              ? "The guided example was interrupted"
              : "Example complete: this is a manufacturing answer"}
        </p>
        <p style={{ margin: "3px 0 0", color: C.ink55, fontSize: 11.5, lineHeight: 1.5 }}>
          {state === "running"
            ? "ProofShape is measuring geometry, checking manufacturability, choosing processes, and estimating cost."
            : failed
              ? "No completed result was created. Retry the example or check one of your own CAD files."
              : "Read geometry and DFM first; route, first issue, resource cost, and shop fit follow in decision order."}
        </p>
      </div>
      {failed ? (
        <button type="button" onClick={onRetry} style={guidedBarButton(C.cond)}>
          Retry example
        </button>
      ) : state === "ready" ? (
        <button type="button" onClick={onUpload} style={guidedBarButton(C.measured)}>
          Check my CAD next
        </button>
      ) : null}
      <button type="button" onClick={onBack} style={guidedBarButton(C.ink55, true)}>
        Back to start
      </button>
    </section>
  );
}

function guidedBarButton(color: string, quiet = false): CSSProperties {
  return {
    minHeight: 36,
    border: `1px solid ${quiet ? C.hair : color}`,
    borderRadius: 999,
    background: quiet ? C.panel : color,
    color: quiet ? C.ink : "#fff",
    padding: "7px 13px",
    fontFamily: "inherit",
    fontSize: 11.5,
    fontWeight: 650,
    cursor: "pointer",
  };
}

function OrganizationAccessGate({
  access,
}: {
  access: OrganizationAccess | null;
}) {
  const unavailable = access === null;
  const hasMemberships = Boolean(access?.organizations.length);
  return (
    <main
      data-testid="verify-organization-gate"
      className="cv-verify-shell"
      style={{
        minHeight: "100%",
        display: "grid",
        placeItems: "center",
        background: C.bg,
        color: C.ink,
        padding: 24,
        fontFamily: SANS,
      }}
    >
      <section
        style={{
          width: "min(100%, 620px)",
          border: `1px solid ${unavailable ? "rgba(190,61,45,0.34)" : C.hair}`,
          borderRadius: 18,
          background: C.panel,
          padding: "28px 30px",
          boxShadow: "0 18px 50px rgba(23,24,26,0.08)",
        }}
      >
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em", color: unavailable ? C.fail : C.ink45 }}>
          {unavailable ? "WORKSPACE CHECK UNAVAILABLE" : "ORGANIZATION REQUIRED"}
        </p>
        <h1 style={{ margin: "10px 0 0", fontSize: 27, fontWeight: 400, letterSpacing: "-0.02em" }}>
          {unavailable
            ? "We couldn’t confirm your active organization."
            : hasMemberships
              ? "Choose an active organization."
              : "You haven’t joined an organization yet."}
        </h1>
        <p style={{ margin: "12px 0 0", color: C.ink55, fontSize: 14, lineHeight: 1.65 }}>
          {unavailable
            ? "ProofShape stopped before requesting organization CAD, machine, or ground-truth data. Retry the check; if it continues, your administrator can verify the workspace connection."
            : hasMemberships
              ? "Your account has an organization membership, but no workspace is active. Select it in Organization settings before opening org-scoped records or CAD tools."
              : "Open the invitation link sent by your organization administrator. If you do not have one, ask them to invite this exact account email. No organization data has been loaded or treated as empty."}
        </p>
        <div style={{ marginTop: 22, display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Link
            href="/settings/organization"
            style={{ minHeight: 42, display: "inline-flex", alignItems: "center", borderRadius: 999, background: C.ink, color: "#fff", padding: "9px 17px", textDecoration: "none", fontSize: 13, fontWeight: 600 }}
          >
            Open organization settings
          </Link>
          {unavailable ? (
            <a
              href="/verify"
              style={{ minHeight: 42, display: "inline-flex", alignItems: "center", border: `1px solid ${C.hair}`, borderRadius: 999, color: C.ink, padding: "9px 17px", textDecoration: "none", fontSize: 13, fontWeight: 600 }}
            >
              Retry organization check
            </a>
          ) : null}
        </div>
      </section>
    </main>
  );
}

const KEYFRAMES = `
@keyframes vspin { to { transform: rotate(360deg); } }
@keyframes vscreenIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes vstepIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@keyframes vtraceIn { from { opacity: 0; transform: translateX(-5px); } to { opacity: 1; transform: translateX(0); } }
@keyframes vtoastIn { from { opacity: 0; transform: translate(-50%, 8px); } to { opacity: 1; transform: translate(-50%, 0); } }

/* One shared keyboard-focus indicator for every interactive element inside the
   Verify shell. #17181a on the light instrument surface is 16.4:1 vs #f6f6f7 —
   far above the WCAG 2.4.7 / non-text-contrast 3:1 floor. Covers native controls
   plus custom rows/cards that opt in via role="button" or a tabindex, and never
   fires for tabindex="-1" (programmatic-only) targets. Individual components must
   NOT set inline outline:none — an inline rule would beat this stylesheet one. */
.cv-verify-shell button:focus-visible,
.cv-verify-shell input:focus-visible,
.cv-verify-shell select:focus-visible,
.cv-verify-shell textarea:focus-visible,
.cv-verify-shell a:focus-visible,
.cv-verify-shell [role="button"]:focus-visible,
.cv-verify-shell [role="option"]:focus-visible,
.cv-verify-shell [role="checkbox"]:focus-visible,
.cv-verify-shell [tabindex]:not([tabindex="-1"]):focus-visible {
  outline: 2px solid #17181a;
  outline-offset: 2px;
}

.cv-verify-mobile-section {
  display: none;
}

@media (max-width: 1320px) {
  .cv-verify-rail-label,
  .cv-verify-rate-switcher {
    display: none !important;
  }
}

@media (max-width: 900px) {
  .cv-verify-start-grid {
    grid-template-columns: minmax(0, 1fr) !important;
  }
  .cv-verify-home-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
  }
  .cv-verify-setup > div:last-child,
  .cv-verify-home-grid {
    grid-template-columns: minmax(0, 1fr) !important;
  }
  .cv-verify-home-kpis > :last-child {
    grid-column: 1 / -1;
  }
  .cv-verify-screen-split {
    display: block !important;
    overflow-y: auto;
    overflow-x: hidden;
  }
  .cv-verify-stage {
    width: 100% !important;
    min-width: 0 !important;
    height: 420px;
    min-height: 420px;
    border-right: none !important;
    border-bottom: 1px solid #dedee2;
  }
}

@media (max-width: 760px) {
  .cv-verify-shell {
    overflow: hidden;
  }
  .cv-verify-workspace-nav {
    min-height: 52px !important;
    padding-inline: 8px !important;
    gap: 6px !important;
  }
  .cv-verify-workspace-tabs {
    display: none !important;
  }
  .cv-verify-mobile-section {
    display: block;
    min-width: 0;
    flex: 1;
    height: 44px;
    border: 1px solid #dedee2;
    border-radius: 9px;
    background: #fff;
    color: #17181a;
    padding: 0 34px 0 12px;
    font: 500 13px ${SANS};
  }
  .cv-verify-rail-button {
    width: 44px !important;
    min-width: 44px !important;
    height: 44px !important;
    padding-inline: 0 !important;
  }
  .cv-verify-rail-label {
    display: none;
  }
  .cv-verify-workspace-actions {
    gap: 5px !important;
  }
  .cv-verify-rate-dot,
  .cv-verify-command-button,
  .cv-verify-rate-switcher {
    display: none !important;
  }
  .cv-verify-main {
    max-width: 100vw;
    overflow-x: hidden;
  }
  .cv-verify-primary-action {
    min-height: 44px;
    padding-inline: 12px !important;
  }
  .cv-verify-home {
    padding: 24px 14px !important;
    overflow-x: hidden;
  }
  .cv-verify-start {
    padding: 15px 14px !important;
  }
  .cv-verify-guided-bar {
    align-items: flex-start !important;
    padding: 12px 14px !important;
  }
  .cv-verify-guided-bar > button {
    flex: 1 1 140px;
  }
  .cv-verify-home button,
  .cv-verify-walk button {
    min-height: 44px;
  }
  .cv-verify-shell input:not([type="file"]) {
    min-height: 44px;
  }
  .cv-verify-setup {
    padding: 15px 14px !important;
  }
  .cv-verify-walk-scroll {
    padding: 22px 14px 18px !important;
  }
  .cv-verify-stage-title {
    top: 18px !important;
    left: 16px !important;
    right: 16px;
    max-height: 108px;
    overflow: hidden;
  }
  .cv-verify-stage-title h1 {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cv-verify-stage-context-card {
    top: 140px !important;
    left: 16px;
    right: 16px !important;
    width: auto !important;
  }
  .cv-verify-pipeline-rail {
    top: 112px !important;
    right: 8px !important;
    width: calc(100vw - 16px) !important;
    max-height: calc(100dvh - 120px) !important;
  }
  .cv-verify-pipeline-panel {
    border-radius: 16px !important;
    padding: 20px !important;
  }
}
`;
