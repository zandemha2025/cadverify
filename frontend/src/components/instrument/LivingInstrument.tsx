"use client";

/**
 * THE LIVING INSTRUMENT — CadVerify's core, rebuilt as a FULL-BLEED instrument
 * rather than a dashboard panel.
 *
 * Intake: there is no dashed dropzone card. The ENTIRE workspace is the drop
 * target — a blueprint field with a ghost machined part that lights up as a
 * file is dragged over it. Powering the tool on feels like an instrument coming
 * alive, not filling in a form.
 *
 * Loaded: the beautiful machined part (cad-viewer's studio-lit render) commands
 * the WHOLE canvas, large and central. The decision — make-by, the monumental
 * $/unit, lead time, crossover — reads as instrument HUD panels floating over
 * the part, not a fixed right sidebar. The quantity scrubber is a real control
 * seated along the bottom edge; drag it and the recommendation flips live from
 * lib/breakeven's fitted curves (zero server roundtrip). Shop/material/region/
 * labor stay tucked behind Recalibrate; the glass-box drivers reveal on demand;
 * DFM flags float in their own panel and highlight ON the geometry. The part's
 * identity + verdict + reset live in the slim top strip (published via the
 * instrument-chrome context) — the chrome is contextual, not a persistent bar.
 *
 * Bound to the cost-truth engine's real report_to_dict — never a fabricated
 * figure. Session-authed via the same-origin proxy.
 */

import * as React from "react";
import dynamic from "next/dynamic";
import { toast } from "sonner";
import { ChevronDown, Crosshair, RotateCcw, UploadCloud } from "lucide-react";
import {
  costEstimate,
  validateFile,
  getShops,
  CostGeometryInvalidError,
  type CostOptions,
  type CostReport,
  type CostGeometry,
  type ShopProfileInfo,
  type ValidationResult,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { procLabel, severityTone } from "@/lib/status";
import {
  deriveBreakeven,
  recommendAt,
  posToQty,
  qtyToPos,
} from "@/lib/breakeven";
import { pickEstimate } from "@/lib/cost-views";
import { flattenIssues, type IndexedIssue } from "@/components/IssueList";
import { DEFAULT_COST_OPTIONS, validateQty } from "@/components/cost/CostOptionsForm";
import { StatusBadge } from "@/components/ui/status-badge";
import { QuantityScrubber } from "./QuantityScrubber";
import { DecisionReadout } from "./DecisionReadout";
import { InstrumentControls } from "./InstrumentControls";
import { GlassBoxDrawer } from "./GlassBoxDrawer";
import { GhostPart } from "./GhostPart";
import {
  useInstrumentChrome,
  type PartFact,
} from "./instrument-chrome";

const CadViewer = dynamic(() => import("@/components/ui/cad-viewer"), {
  ssr: false,
  loading: () => (
    <div
      className="flex h-full items-center justify-center"
      style={{
        background:
          "radial-gradient(66% 58% at 50% 47%, rgba(50,124,188,0.22) 0%, rgba(50,124,188,0) 62%), radial-gradient(120% 118% at 50% -6%, #15273f 0%, #0c1828 50%, #070d17 100%)",
      }}
    >
      <p className="num text-sm text-[#6f8099]">loading 3D viewer…</p>
    </div>
  ),
});

const ACCEPT = ".stl,.step,.stp";

/* DFM highlight hues tuned to read on the steel-blue mesh under twilight. */
const SEVERITY_HEX: Record<string, string> = {
  fail: "#f8716e",
  warn: "#f0b429",
  info: "#3fa3e8",
  pass: "#34d399",
  neutral: "#94a3b8",
};

export type InstrumentFocus = "decision" | "dfm";

/** A frosted instrument panel that floats legibly over the 3D part. */
function Panel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius)] border border-[#274563]",
        className
      )}
      style={{
        background: "rgba(10,17,30,0.86)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        boxShadow:
          "inset 0 1px 0 rgb(255 255 255 / 0.06), 0 24px 64px -28px rgb(2 8 18 / 0.9)",
      }}
    >
      {children}
    </div>
  );
}

export default function LivingInstrument({
  focus = "decision",
}: {
  focus?: InstrumentFocus;
}) {
  const [file, setFile] = React.useState<File | null>(null);
  const [opts, setOpts] = React.useState<CostOptions>(DEFAULT_COST_OPTIONS);

  const [report, setReport] = React.useState<CostReport | null>(null);
  const [costLoading, setCostLoading] = React.useState(false);
  const [recosting, setRecosting] = React.useState(false);
  const [costError, setCostError] = React.useState<string | null>(null);
  const [geomError, setGeomError] = React.useState<{
    reason: string | null;
    geometry: CostGeometry | null;
  } | null>(null);

  const [validation, setValidation] = React.useState<ValidationResult | null>(null);
  const [dfmLoading, setDfmLoading] = React.useState(false);
  const [dfmError, setDfmError] = React.useState<string | null>(null);

  const [shops, setShops] = React.useState<ShopProfileInfo[]>([]);
  const [pos, setPos] = React.useState(0.6);
  const [hoveredKey, setHoveredKey] = React.useState<string | null>(null);
  const [selectedKey, setSelectedKey] = React.useState<string | null>(null);
  const [glassOpen, setGlassOpen] = React.useState(false);
  const [flagsOpen, setFlagsOpen] = React.useState(focus === "dfm");
  const [controlsOpen, setControlsOpen] = React.useState(false);
  const [dragActive, setDragActive] = React.useState(false);

  const recostTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const dragDepth = React.useRef(0);

  const { setPart } = useInstrumentChrome();

  // fetch bindable shops once (best-effort)
  React.useEffect(() => {
    let cancelled = false;
    getShops()
      .then((r) => !cancelled && setShops(r.shops))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  React.useEffect(
    () => () => {
      if (recostTimer.current) clearTimeout(recostTimer.current);
    },
    []
  );

  /* ---- engine calls ------------------------------------------------ */

  const runCost = React.useCallback(
    async (theFile: File, theOpts: CostOptions, mode: "initial" | "recost") => {
      if (mode === "initial") {
        setCostLoading(true);
        setCostError(null);
        setGeomError(null);
        setReport(null);
      } else {
        setRecosting(true);
      }
      try {
        const result = await costEstimate(theFile, theOpts);
        setReport(result);
        if (mode === "initial") {
          const b = deriveBreakeven(result);
          if (b) {
            const seed =
              b.crossoverQty ??
              Math.max(...(result.quantities.length ? result.quantities : [1]));
            setPos(qtyToPos(b, seed));
          }
        }
      } catch (err) {
        if (mode === "initial") {
          if (err instanceof CostGeometryInvalidError) {
            setGeomError({ reason: err.message, geometry: err.geometry });
          } else {
            setCostError(err instanceof Error ? err.message : "Cost estimate failed.");
          }
        } else {
          toast.error(
            err instanceof Error ? err.message : "Re-cost failed — keeping the last figure."
          );
        }
      } finally {
        if (mode === "initial") setCostLoading(false);
        else setRecosting(false);
      }
    },
    []
  );

  const runDfm = React.useCallback(async (theFile: File) => {
    setDfmLoading(true);
    setDfmError(null);
    setValidation(null);
    setSelectedKey(null);
    setHoveredKey(null);
    try {
      const data = await validateFile(theFile);
      setValidation(data);
    } catch (err) {
      // DFM is best-effort — the cost decision still stands without it, so we
      // surface a clean inline error on this panel only (never a full-screen
      // failure) and let the user retry just the geometry analysis.
      setDfmError(
        err instanceof Error ? err.message : "DFM analysis is unavailable."
      );
    } finally {
      setDfmLoading(false);
    }
  }, []);

  const scheduleRecost = React.useCallback(
    (nextOpts: CostOptions) => {
      setOpts(nextOpts);
      if (!file || validateQty(nextOpts.qty)) return;
      if (recostTimer.current) clearTimeout(recostTimer.current);
      recostTimer.current = setTimeout(() => {
        void runCost(file, nextOpts, "recost");
      }, 260);
    },
    [file, runCost]
  );

  const handleFile = React.useCallback(
    (selected: File) => {
      const ext = selected.name.split(".").pop()?.toLowerCase();
      if (!ext || !["stl", "step", "stp"].includes(ext)) {
        toast.error("Unsupported file. Use .stl, .step or .stp");
        return;
      }
      setFile(selected);
      setGlassOpen(false);
      setSelectedKey(null);
      setHoveredKey(null);
      setFlagsOpen(focus === "dfm");
      setControlsOpen(false);
      // Fire BOTH engine runs at once and let them settle independently. The
      // cost decision (the hero) is NOT gated on the slower DFM pass: whichever
      // returns first renders its own panel, and an error in one never blocks
      // the other (each owns its try/catch + error state; allSettled never
      // rejects). With 2 backend workers these run in true parallel, so the
      // hero appears in roughly one engine run instead of two back-to-back.
      void Promise.allSettled([
        runCost(selected, opts, "initial"),
        runDfm(selected),
      ]);
    },
    [opts, focus, runCost, runDfm]
  );

  const reset = React.useCallback(() => {
    setFile(null);
    setReport(null);
    setValidation(null);
    setDfmError(null);
    setGeomError(null);
    setCostError(null);
    setGlassOpen(false);
    setSelectedKey(null);
    setHoveredKey(null);
    setControlsOpen(false);
  }, []);

  const openPicker = React.useCallback(() => fileInputRef.current?.click(), []);

  /* ---- whole-surface drag & drop (both states) --------------------- */

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };
  const onDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current += 1;
    setDragActive(true);
  };
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragActive(false);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    const f = e.dataTransfer.files?.[0];
    if (f) handleFile(f);
  };

  /* ---- derived ----------------------------------------------------- */

  const breakeven = React.useMemo(() => (report ? deriveBreakeven(report) : null), [report]);
  const qty = breakeven ? posToQty(breakeven, pos) : 0;
  const rec = breakeven ? recommendAt(breakeven, qty) : null;
  const recProcess = rec?.curve.process ?? breakeven?.makeNowProcess ?? "";
  const recEstimate =
    rec && report ? pickEstimate(report, rec.curve.process, qty) : null;

  const dfmIssues = React.useMemo(
    () => (validation ? flattenIssues(validation) : []),
    [validation]
  );

  // A calm severity breakdown for the collapsed DFM strip ("76 flags · 2
  // critical · 1 advisory") — the wall of rows only opens on demand.
  const dfmSummary = React.useMemo(() => {
    const counts = { fail: 0, warn: 0, info: 0, other: 0 };
    for (const it of dfmIssues) {
      const t = severityTone(it.issue.severity);
      if (t === "fail") counts.fail++;
      else if (t === "warn") counts.warn++;
      else if (t === "info") counts.info++;
      else counts.other++;
    }
    const parts: { label: string; n: number; color: string }[] = [
      { label: "critical", n: counts.fail, color: "#f8716e" },
      { label: "advisory", n: counts.warn, color: "#f0b429" },
      { label: "info", n: counts.info, color: "#7fa8cf" },
    ].filter((p) => p.n > 0);
    return { total: dfmIssues.length, parts };
  }, [dfmIssues]);

  // auto-spotlight the top priority fix on the part when landing in DFM focus
  React.useEffect(() => {
    if (focus !== "dfm" || !dfmIssues.length || selectedKey) return;
    const top =
      dfmIssues.find((i) => severityTone(i.issue.severity) === "fail" && i.faces.length) ??
      dfmIssues.find((i) => i.faces.length);
    if (top) setSelectedKey(top.key);
  }, [focus, dfmIssues, selectedKey]);

  const activeIssue = React.useMemo(() => {
    const key = hoveredKey ?? selectedKey;
    return dfmIssues.find((i) => i.key === key) ?? null;
  }, [hoveredKey, selectedKey, dfmIssues]);

  const highlightFaces = activeIssue?.faces.length ? activeIssue.faces : undefined;
  const highlightColor = activeIssue
    ? SEVERITY_HEX[severityTone(activeIssue.issue.severity)]
    : undefined;

  const onFaceClick = React.useCallback(
    (faceIndex: number) => {
      const hit = dfmIssues.find((i) => i.faces.includes(faceIndex));
      if (hit) {
        setFlagsOpen(true);
        setSelectedKey(hit.key);
      }
    },
    [dfmIssues]
  );

  const dec = report?.decision ?? null;
  const toolingConditional =
    dec && dec.tooling_process && dec.tooling_dfm_ready === false
      ? {
          process: dec.tooling_process,
          blocker: pickEstimate(report!, dec.tooling_process)?.dfm_blockers?.[0],
        }
      : null;

  const laborDefault =
    report?.assumptions.find((a) => a.name === "labor_rate")?.value ?? null;
  const laborOverride = opts.overrides?.labor_rate ?? null;

  // measured facts — published to the top strip (the part's identity chip)
  const facts = React.useMemo<PartFact[]>(() => {
    const geo = report?.geometry;
    const vgeo = validation?.geometry;
    const out: PartFact[] = [];
    if (geo) {
      out.push({ label: "vol", value: `${geo.volume_cm3.toFixed(1)} cm³` });
      out.push({ label: "bbox", value: `${geo.bbox_mm.map((v) => Math.round(v)).join("×")} mm` });
      out.push({ label: "faces", value: geo.face_count.toLocaleString() });
      out.push({ label: "watertight", value: geo.watertight ? "yes" : "no" });
    } else if (vgeo) {
      out.push({ label: "vol", value: `${(vgeo.volume_mm3 / 1000).toFixed(1)} cm³` });
      out.push({ label: "bbox", value: `${vgeo.bounding_box_mm.map((v) => Math.round(v)).join("×")} mm` });
      out.push({ label: "faces", value: vgeo.faces.toLocaleString() });
    }
    return out;
  }, [report, validation]);

  // Publish the loaded part's identity to the slim top strip; clear on reset.
  React.useEffect(() => {
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

  // Clear the strip if the instrument itself unmounts (navigating away).
  React.useEffect(() => () => setPart(null), [setPart]);

  /* ---- control handlers (fresh opts; debounced re-cost) ------------ */

  const onSelectShop = (id: string | null) => {
    scheduleRecost({ ...opts, shop: id });
    toast(id ? "Recalibrating to shop rates…" : "Back to generic rates…");
  };
  const onMaterial = (v: string) => scheduleRecost({ ...opts, material_class: v });
  const onRegion = (v: string) => scheduleRecost({ ...opts, region: v });
  const onLaborRate = (v: number | null) => {
    const overrides = { ...(opts.overrides ?? {}) };
    if (v == null) delete overrides.labor_rate;
    else overrides.labor_rate = v;
    scheduleRecost({ ...opts, overrides });
  };
  const onGlassOverride = (key: string, value: number) => {
    scheduleRecost({ ...opts, overrides: { ...(opts.overrides ?? {}), [key]: value } });
    toast.success(`Override ${key} = ${value} — re-costing.`);
  };

  /* ---- shared: hidden input + drag overlay ------------------------- */

  const hiddenInput = (
    <input
      ref={fileInputRef}
      type="file"
      accept={ACCEPT}
      className="hidden"
      onChange={(e) => {
        const f = e.target.files?.[0];
        if (f) handleFile(f);
        e.target.value = "";
      }}
    />
  );

  /* ---- render: EMPTY — the full-bleed intake ----------------------- */

  if (!file) {
    return (
      <div
        className="cv-twilight relative h-full w-full overflow-hidden"
        onDragOver={onDragOver}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        {hiddenInput}
        <div
          onClick={openPicker}
          className={cn(
            "cv-hero-field relative flex h-full w-full cursor-pointer flex-col overflow-hidden transition-shadow",
            dragActive && "shadow-[inset_0_0_0_2px_#3fa3e8]"
          )}
        >
          {/* the ghost part — the instrument's idle centerpiece */}
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="w-[min(64vw,560px)] max-w-full translate-y-[-4%]">
              <GhostPart active={dragActive} />
            </div>
          </div>

          {/* the invitation — anchored bottom-left, monumental */}
          <div className="relative z-10 mt-auto max-w-full p-7 sm:p-10 lg:p-14">
            <span className="cv-eyebrow cv-on-dark">Should-cost · live instrument</span>
            <h1 className="cv-display mt-4 max-w-3xl text-[2.1rem] leading-[1.02] text-[#eaeff7] sm:text-[3rem]">
              Drop a part.
              <br />
              Watch the decision resolve.
            </h1>
            <p className="mt-4 max-w-lg text-sm leading-relaxed text-[#9fb0c8] sm:text-base">
              The whole surface is the instrument. Drop one CAD file — and the
              make-vs-buy decision, the cost per unit, and the crossover quantity
              you can scrub by hand resolve around the part in real 3D.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-x-5 gap-y-3">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  openPicker();
                }}
                className="inline-flex items-center gap-2 rounded-[var(--radius-sm)] bg-[#3fa3e8] px-4 py-2.5 text-sm font-semibold text-[#07131f] transition-colors hover:bg-[#6fbcef] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0b1220]"
              >
                <UploadCloud className="size-4" />
                Drop or browse a CAD file
              </button>
              <span className="num text-xs text-[#6f8099]">
                STL renders live · STEP / STP costed too · parsed and discarded in-process
              </span>
            </div>
          </div>

          {/* drag affordance — the field arms itself */}
          {dragActive && (
            <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center">
              <div className="rounded-[var(--radius-lg)] border-2 border-dashed border-[#3fa3e8] bg-[#0b1220]/40 px-8 py-5 text-center backdrop-blur-sm">
                <span className="cv-eyebrow cv-on-dark">Release to load the part</span>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  /* ---- render: LOADED — the HUD instrument ------------------------- */

  return (
    <div
      className="cv-twilight relative h-full w-full overflow-hidden"
      onDragOver={onDragOver}
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {hiddenInput}

      {/* BACKGROUND — the part commands the whole canvas */}
      <div className="absolute inset-0">
        <CadViewer
          file={file}
          surface="instrument"
          className="rounded-none border-0"
          highlightFaces={highlightFaces}
          highlightColor={highlightColor}
          ghostUnhighlighted={!!highlightFaces}
          onFaceClick={onFaceClick}
        />
        {/* corner vignette so the floating readouts seat in shadow, legibly */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(120% 92% at 50% 42%, transparent 46%, rgba(6,11,22,0.5) 100%)",
          }}
        />
      </div>

      {/* DECISION — the hero readout, floating top-left */}
      <div className="absolute left-3 top-3 z-20 w-[min(94vw,360px)] sm:left-4 sm:top-4">
        <Panel className="max-h-[calc(100vh-var(--topbar-h)-8rem)] overflow-y-auto p-4 sm:p-5">
          {costLoading ? (
            <ResolveSequence dfmDone={validation != null || dfmError != null} />
          ) : geomError ? (
            <GeometryInvalid reason={geomError.reason} geometry={geomError.geometry} />
          ) : costError ? (
            <CostFailed
              message={costError}
              onRetry={() => file && runCost(file, opts, "initial")}
            />
          ) : report && breakeven && rec ? (
            <>
              <DecisionReadout
                process={recProcess}
                unitCost={rec.unitCost}
                dfmReady={rec.dfmReady}
                leadLow={rec.curve.leadLow}
                leadHigh={rec.curve.leadHigh}
                qty={qty}
                estimate={recEstimate}
                crossoverSentence={crossoverSentence(report)}
                toolingConditional={toolingConditional}
                onAskWhy={() => setGlassOpen(true)}
                onRecalibrate={() => setControlsOpen((o) => !o)}
                controlsOpen={controlsOpen}
              />
              {controlsOpen && (
                <div className="cv-reveal mt-5">
                  <InstrumentControls
                    shops={shops}
                    activeShopId={opts.shop ?? null}
                    onSelectShop={onSelectShop}
                    materialClass={opts.material_class}
                    onMaterial={onMaterial}
                    region={opts.region}
                    onRegion={onRegion}
                    laborRate={laborOverride}
                    laborDefault={laborDefault}
                    onLaborRate={onLaborRate}
                    recosting={recosting}
                  />
                </div>
              )}
            </>
          ) : report ? (
            <NoDecision report={report} />
          ) : null}
        </Panel>
      </div>

      {/* DFM FLAGS — floating top-right, collapsible; highlights ON the part */}
      {(dfmIssues.length > 0 || dfmLoading || dfmError) && (
        <div className="absolute right-3 top-3 z-20 w-[min(94vw,300px)] sm:right-4 sm:top-4">
          <Panel>
            <button
              type="button"
              onClick={() => setFlagsOpen((o) => !o)}
              aria-expanded={flagsOpen}
              className="flex w-full items-center gap-2.5 rounded-t-[var(--radius)] px-3.5 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8]"
            >
              <Crosshair className="size-3.5 shrink-0 text-[#3fa3e8]" />
              <span className="text-xs font-semibold text-[#eaeff7]">DFM flags</span>
              {dfmLoading ? (
                <span className="num text-[11px] text-[#6f8099]">analyzing…</span>
              ) : dfmError ? (
                <span className="num text-[11px] text-[#f3b3b0]">unavailable</span>
              ) : (
                <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
                  <span className="num text-[11px] text-[#9fb0c8]">
                    {dfmSummary.total} {dfmSummary.total === 1 ? "flag" : "flags"}
                  </span>
                  {dfmSummary.parts.map((p) => (
                    <span
                      key={p.label}
                      className="num inline-flex items-center gap-1 text-[11px] text-[#6f8099]"
                    >
                      <span
                        className="inline-block size-1.5 rounded-full"
                        style={{ background: p.color }}
                        aria-hidden
                      />
                      {p.n} {p.label}
                    </span>
                  ))}
                </span>
              )}
              <ChevronDown
                className={`ml-auto size-4 shrink-0 text-[#6f8099] transition-transform ${flagsOpen ? "rotate-180" : ""}`}
              />
            </button>
            {dfmError && (
              <div className="flex flex-wrap items-center gap-2 border-t border-[#23314a] px-3 py-2.5">
                <p className="min-w-0 flex-1 text-xs text-[#f3b3b0]">
                  DFM analysis unavailable — {dfmError}
                </p>
                <button
                  type="button"
                  onClick={() => file && runDfm(file)}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-sm border border-[#1e3a5f] bg-[#102438] px-2.5 py-1 text-[11px] font-medium text-[#8fc8f2] hover:bg-[#15314c] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8]"
                >
                  <RotateCcw className="size-3" /> Retry DFM
                </button>
              </div>
            )}
            {flagsOpen && dfmIssues.length > 0 && (
              <div className="max-h-[min(42vh,20rem)] space-y-2 overflow-y-auto border-t border-[#23314a] px-3.5 py-3">
                {dfmIssues.map((it) => (
                  <FlagRow
                    key={it.key}
                    item={it}
                    selected={selectedKey === it.key}
                    onHover={(k) => setHoveredKey(k)}
                    onSelect={(k) => setSelectedKey((cur) => (cur === k ? null : k))}
                  />
                ))}
              </div>
            )}
            {flagsOpen && !dfmLoading && !dfmError && dfmIssues.length === 0 && (
              <p className="border-t border-[#23314a] px-3 py-2.5 text-xs text-[#6f8099]">
                No DFM flags — clean as modeled.
              </p>
            )}
          </Panel>
        </div>
      )}

      {/* THE SCRUBBER — the signature control, seated on the bottom edge */}
      {report && breakeven && rec && !costLoading && !geomError && (
        <div className="absolute inset-x-3 bottom-3 z-20 sm:inset-x-4">
          <Panel className="px-4 pb-3 pt-3">
            <div className="mb-1.5 flex items-baseline justify-between">
              <span className="cv-eyebrow">Quantity scrubber</span>
              <span className="num text-[11px] text-[#6f8099]">
                make-vs-buy · $/unit vs quantity
              </span>
            </div>
            <QuantityScrubber
              breakeven={breakeven}
              qty={qty}
              pos={pos}
              recommendedProcess={recProcess}
              onPosChange={setPos}
              recosting={recosting}
            />
          </Panel>
        </div>
      )}

      {/* glass box — drivers revealed on demand */}
      <GlassBoxDrawer
        open={glassOpen}
        onClose={() => setGlassOpen(false)}
        estimate={recEstimate}
        process={recProcess}
        qty={qty}
        materialClass={opts.material_class}
        onOverride={onGlassOverride}
      />

      {/* drag-to-replace overlay */}
      {dragActive && (
        <div className="pointer-events-none absolute inset-0 z-40 flex items-center justify-center bg-[#070d17]/45 backdrop-blur-[1px]">
          <div className="rounded-[var(--radius-lg)] border-2 border-dashed border-[#3fa3e8] bg-[#0b1220]/70 px-8 py-5 text-center">
            <span className="cv-eyebrow cv-on-dark">Release to load a new part</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function FlagRow({
  item,
  selected,
  onHover,
  onSelect,
}: {
  item: IndexedIssue;
  selected: boolean;
  onHover: (key: string | null) => void;
  onSelect: (key: string) => void;
}) {
  const locatable = item.faces.length > 0;
  return (
    <div
      role="button"
      tabIndex={0}
      onMouseEnter={() => onHover(item.key)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(item.key)}
      onBlur={() => onHover(null)}
      onClick={() => onSelect(item.key)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(item.key);
        }
      }}
      className={[
        "cursor-pointer rounded-sm border px-2.5 py-1.5 transition-colors",
        selected
          ? "border-[#3fa3e8] bg-[#12243a]"
          : "border-[#23314a] bg-[#0f1b2e] hover:border-[#33446a]",
      ].join(" ")}
    >
      <div className="flex items-center gap-2">
        <StatusBadge severity={item.issue.severity} size="sm" />
        <span className="num truncate text-[11px] text-[#9fb0c8]">{item.issue.code}</span>
        {locatable && (
          <span className="ml-auto inline-flex shrink-0 items-center gap-1 text-[10px] text-[#3fa3e8]">
            <Crosshair className="size-3" />
            {selected ? "shown" : "locate"}
          </span>
        )}
      </div>
      <p className="mt-0.5 line-clamp-2 text-xs text-[#cdd9ea]">{item.issue.message}</p>
    </div>
  );
}

/**
 * The "figuring it out" reveal — feels like intelligence resolving the part.
 *
 * This is a tasteful reveal, NOT a gate: it only renders while the cost call is
 * in flight and is torn down the instant that call resolves (the hero replaces
 * it), so it can never add time beyond the real wait. Progress is tied to real
 * signals where we have them: the DFM pass genuinely measures the geometry and
 * scores the candidate processes, so the moment it resolves we check those two
 * steps off (`dfmDone`). A gentle, capped timer animates the active pointer for
 * liveliness but never marks the final make-vs-buy fit "done" on a timer alone —
 * that step completes only when the real cost result lands and unmounts this.
 */
function ResolveSequence({ dfmDone }: { dfmDone: boolean }) {
  const steps = [
    "Measuring geometry",
    "Routing the process",
    "Costing across processes",
    "Fitting the make-vs-buy curve",
  ];
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    const id = setInterval(
      () => setTick((n) => Math.min(n + 1, steps.length - 1)),
      1100
    );
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const doneThrough = dfmDone ? 1 : -1;
  const i = Math.max(tick, doneThrough + 1);
  return (
    <div className="space-y-5">
      <div>
        <span className="cv-eyebrow">Resolving the decision</span>
        <div className="mt-3 h-[3.5rem] w-40 rounded-sm bg-gradient-to-r from-[#16314f] to-[#0f1b2e]" />
      </div>
      <ul className="space-y-2.5">
        {steps.map((s, n) => (
          <li key={s} className="flex items-center gap-2.5 text-sm">
            <span
              className={[
                "inline-flex size-4 items-center justify-center rounded-full border text-[10px]",
                n < i
                  ? "border-[#3fa3e8] bg-[#3fa3e8] text-[#07131f]"
                  : n === i
                    ? "border-[#3fa3e8] text-[#3fa3e8]"
                    : "border-[#33446a] text-[#33446a]",
              ].join(" ")}
            >
              {n < i ? "✓" : n === i ? "•" : ""}
            </span>
            <span
              className={n <= i ? "text-[#eaeff7]" : "text-[#52647f]"}
              style={{
                opacity: n === i ? 1 : n < i ? 0.85 : 0.5,
                transition: "opacity 240ms",
              }}
            >
              {s}
              {n === i && <span className="num ml-1 animate-pulse text-[#3fa3e8]">…</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function GeometryInvalid({
  reason,
  geometry,
}: {
  reason: string | null;
  geometry: CostGeometry | null;
}) {
  return (
    <div className="space-y-4">
      <div>
        <span className="cv-eyebrow" style={{ color: "#f8a39e" }}>
          Geometry rejected
        </span>
        <p className="mt-2 text-sm text-[#f3d3d0]">
          {reason ?? "This geometry can't be costed — the engine's gate refuses broken solids."}
        </p>
      </div>
      {geometry && (
        <div className="num grid grid-cols-2 gap-2 text-xs">
          <Fact k="volume" v={`${geometry.volume_cm3.toFixed(2)} cm³`} />
          <Fact k="watertight" v={geometry.watertight ? "yes" : "no"} />
          <Fact k="faces" v={geometry.face_count.toLocaleString()} />
          <Fact k="bbox" v={`${geometry.bbox_mm.map((x) => Math.round(x)).join("×")} mm`} />
        </div>
      )}
      <p className="text-xs text-[#cf9b97]">
        Repair the mesh (watertight, positive volume) and drop it again.
      </p>
    </div>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-sm border border-[#5a2a2a] bg-[#231010] px-2.5 py-1.5">
      <span className="block text-[10px] uppercase tracking-wide text-[#cf9b97]">{k}</span>
      <span className="block text-[#f3d3d0]">{v}</span>
    </div>
  );
}

function NoDecision({ report }: { report: CostReport }) {
  return (
    <div className="space-y-3">
      <span className="cv-eyebrow">Costed · no make-vs-buy crossover</span>
      <p className="text-sm text-[#cdd9ea]">
        This part was costed but the engine returned no make-vs-buy decision to
        scrub — typically a single feasible process at the quantities tested.
      </p>
      {report.notes?.[0] && (
        <p className="num text-xs text-[#6f8099]">{report.notes[0]}</p>
      )}
    </div>
  );
}

function CostFailed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="space-y-3">
      <span className="cv-eyebrow">Cost estimate failed</span>
      <p className="text-sm text-[#cdd9ea]">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 rounded-sm border border-[#1e3a5f] bg-[#102438] px-3 py-1.5 text-sm font-medium text-[#8fc8f2] hover:bg-[#15314c] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8]"
      >
        <RotateCcw className="size-3.5" /> Try again
      </button>
    </div>
  );
}

function crossoverSentence(report: CostReport): string {
  const dec = report.decision;
  if (!dec) return "";
  if (dec.crossover_qty != null) {
    const n = Math.round(dec.crossover_qty).toLocaleString();
    const make = procLabel(dec.make_now_process);
    if (dec.tooling_process) {
      return `Make below ~${n} units with ${make}; tool up with ${procLabel(
        dec.tooling_process
      )} above it.`;
    }
    return `${make} wins below ~${n} units; tooling amortises above it.`;
  }
  return `${procLabel(dec.make_now_process)} stays cheapest at every quantity tested.`;
}
