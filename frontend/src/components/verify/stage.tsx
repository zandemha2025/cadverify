"use client";

/**
 * The part stage — a light studio with the part floating in it, its name + the
 * MEASURED geometry read overlaid, and the X-ray / drag-to-orbit affordances. The
 * WebGL canvas is dynamically imported (ssr:false) like the app's other viewers.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { C, MONO } from "@/lib/verify/tokens";
import type { PartContext } from "@/lib/verify/part-context-read";
import type { StageAssemblyContext, StageRenderKind } from "./stage-canvas";
import { fetchPreviewMesh, type PreviewMesh } from "@/lib/verify/preview-mesh";
import { GhostButton, ProvChip } from "./primitives";
import { probeWebGlSupport } from "@/lib/site/webgl";

const StageCanvas = dynamic(() => import("./stage-canvas"), {
  ssr: false,
  loading: () => null,
});

/** Honest assembly overlay data for the stage — the whole is real context, not a
 *  declared parent. Present only when the upload is a multi-part assembly. */
export interface StageAssembly {
  /** object URL for the combined assembly GLB (all parts, world positions). */
  glbUrl: string;
  /** id of the highlighted part-of-interest (matches a GLB node). */
  selectedId: string | null;
  partCount: number;
  /** the highlighted part's readable name + product-tree path, for the label. */
  selectedName: string | null;
  selectedTreePath: string | null;
  /** true once the REAL per-part analysis (DFM + cost + interference) has landed. */
  analysisReady?: boolean;
}

export function Stage({
  file,
  partName,
  meta1,
  meta2,
  bbox,
  hostile,
  autoOrbit,
  context,
  contextError,
  assembly,
}: {
  file: File | null;
  partName: string;
  meta1: string;
  meta2?: string;
  bbox: [number, number, number] | null;
  hostile: boolean;
  autoOrbit: boolean;
  context: PartContext | null;
  contextError: string | null;
  /** when set, the stage renders the WHOLE assembly in context (part-of-interest
   *  highlighted) instead of the single-part shell. */
  assembly: StageAssembly | null;
}) {
  const [xray, setXray] = useState(false);
  const [seat, setSeat] = useState(false);
  const [renderUrl, setRenderUrl] = useState<string | null>(null);
  const [renderKind, setRenderKind] = useState<StageRenderKind | null>(null);
  const [preview, setPreview] = useState<PreviewMesh | null>(null);
  const [resolvingShell, setResolvingShell] = useState(false);
  const [webGlAvailable, setWebGlAvailable] = useState<boolean | null>(null);
  const assemblyContext = useMemo<StageAssemblyContext | null>(
    () => ({
      parentAssembly: context?.parent_assembly ?? null,
      program: context?.program ?? null,
      unitsPerParent: context?.units_per_parent ?? null,
      serviceWorldDeclared: Boolean(
        context?.service_environment && Object.keys(context.service_environment).length > 0
      ),
    }),
    [context]
  );
  const hasParent = Boolean(assemblyContext?.parentAssembly);

  // ISSUE-UX-006: react-three-fiber retries renderer creation whenever the
  // stage re-renders. Probe once before Canvas ever mounts; locked-down/GPU-off
  // browsers stay on the explicit static envelope and never enter that loop.
  useEffect(() => {
    setWebGlAvailable(probeWebGlSupport());
  }, []);

  useEffect(() => {
    if (!hasParent) setSeat(false);
  }, [hasParent]);

  // Resolve the geometry the stage renders.
  //  • STL  → parse the real geometry in-browser (STLLoader), no network needed.
  //  • STEP/IGES → fetch the part's REAL tessellated shell from our own backend
  //    (zero-egress GLB) and render THAT instead of a bbox box. While the shell
  //    is resolving, or if it is genuinely unavailable, the honest box remains.
  useEffect(() => {
    setPreview((prev) => {
      prev?.revoke();
      return null;
    });
    // Assembly mode owns the render (the combined GLB): skip the single-part
    // shell fetch entirely so the two paths never fight over the canvas.
    if (assembly) {
      setRenderUrl(null);
      setRenderKind(null);
      setResolvingShell(false);
      return;
    }
    if (!file) {
      setRenderUrl(null);
      setRenderKind(null);
      setResolvingShell(false);
      return;
    }
    if (file.name.toLowerCase().endsWith(".stl")) {
      const url = URL.createObjectURL(file);
      setRenderUrl(url);
      setRenderKind("stl");
      setResolvingShell(false);
      return () => URL.revokeObjectURL(url);
    }
    // STEP/IGES: stream the decimated shell from the backend.
    let cancelled = false;
    let pm: PreviewMesh | null = null;
    setRenderUrl(null);
    setRenderKind(null);
    setResolvingShell(true);
    void fetchPreviewMesh(file)
      .then((res) => {
        if (cancelled) {
          res?.revoke();
          return;
        }
        if (res) {
          pm = res;
          setPreview(res);
          setRenderUrl(res.url);
          setRenderKind("glb");
        }
        setResolvingShell(false);
      })
      .catch(() => {
        if (!cancelled) setResolvingShell(false);
      });
    return () => {
      cancelled = true;
      pm?.revoke();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, assembly?.glbUrl]);

  // Honest render-mode readout: what the viewer is actually looking at.
  const renderMode: { state: string; label: string } = webGlAvailable === false
    ? {
        state: "static-envelope",
        label: bbox
          ? "measured envelope · interactive 3D unavailable"
          : "static CAD fallback · interactive 3D unavailable",
      }
    : assembly
      ? {
        state: "real-assembly",
        label: `real assembly shell · ${assembly.partCount} parts`,
      }
    : renderKind === "stl"
    ? { state: "real-stl", label: "real geometry · STL" }
    : renderKind === "glb"
      ? {
          state: "real-shell",
          label: preview?.decimated && preview.previewFaces
            ? `real shell · ${Math.round(preview.previewFaces / 1000)}k-tri preview`
            : "real shell · tessellated preview",
        }
      : resolvingShell
        ? { state: "resolving", label: "resolving real shape…" }
        : file
          ? { state: "bbox-envelope", label: "bbox envelope · shell unavailable" }
          : { state: "empty", label: "no part yet" };

  return (
    <main
      className="cv-verify-stage"
      style={{
        width: "42%",
        minWidth: 380,
        flexShrink: 0,
        position: "relative",
        background: "radial-gradient(110% 90% at 50% 38%, #ffffff 0%, #ececef 85%)",
        borderRight: `1px solid ${C.hair2}`,
      }}
    >
      <div style={{ position: "absolute", inset: 0, cursor: "grab" }}>
        {webGlAvailable === true ? (
          <StageCanvas
            renderUrl={renderUrl}
            renderKind={renderKind}
            assemblyUrl={assembly?.glbUrl ?? null}
            assemblySelectedId={assembly?.selectedId ?? null}
            bbox={bbox}
            xray={xray}
            hostile={hostile}
            autoOrbit={autoOrbit}
            seat={seat}
            assemblyContext={assemblyContext}
          />
        ) : (
          <StaticStageFallback
            bbox={bbox}
            hasFile={Boolean(file)}
            checking={webGlAvailable === null}
          />
        )}
      </div>

      <div className="cv-verify-stage-title" style={{ position: "absolute", top: 22, left: 24, pointerEvents: "none" }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 400, letterSpacing: "-0.01em" }}>
          {partName}
        </h1>
        <p style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 11, lineHeight: 1.7, color: C.ink45 }}>
          {meta1}
          {meta2 && (
            <>
              <br />
              <span style={{ color: C.measured }}>{meta2}</span>
            </>
          )}
        </p>
        {/* Honest render-mode readout: is the viewer looking at the part's REAL
            geometry / tessellated shell, or the bbox envelope fallback? A real
            shell is a MESH-LEVEL preview (not B-rep/PMI), served zero-egress. */}
        <p
          data-testid="verify-stage-render-mode"
          data-render-state={renderMode.state}
          style={{
            margin: "6px 0 0",
            fontFamily: MONO,
            fontSize: 10,
            letterSpacing: "0.02em",
            color:
              renderMode.state === "real-shell" ||
              renderMode.state === "real-stl" ||
              renderMode.state === "real-assembly"
                ? C.measured
                : C.ink40,
          }}
        >
          <span aria-hidden>{renderMode.state === "bbox-envelope" || renderMode.state === "static-envelope" ? "▢ " : "● "}</span>
          {renderMode.label}
        </p>
        {/* Assembly mode: name the highlighted part-of-interest + its product-tree
            path, honestly labelled as the selected part inside the whole. */}
        {assembly && (
          <p
            data-testid="verify-stage-selected-part"
            style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, lineHeight: 1.6, color: C.ink55 }}
          >
            <span style={{ color: C.user }}>◆ selected&nbsp;</span>
            <span style={{ color: C.ink }}>{assembly.selectedName ?? "—"}</span>
            {assembly.selectedTreePath && (
              <>
                <br />
                <span style={{ color: C.ink40, overflowWrap: "anywhere" }}>
                  {assembly.selectedTreePath}
                </span>
              </>
            )}
          </p>
        )}
      </div>

      {assembly ? (
        <AssemblyStrip partCount={assembly.partCount} analysisReady={!!assembly.analysisReady} />
      ) : (
      <ContextStrip
        partName={partName}
        context={context}
        contextError={contextError}
        hasParent={hasParent}
      />
      )}

      <div
        style={{
          position: "absolute",
          bottom: 20,
          left: "50%",
          transform: "translateX(-50%)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <GhostButton
          onClick={() => setXray((v) => !v)}
          disabled={webGlAvailable !== true}
          title={webGlAvailable === false ? "X-ray requires interactive 3D support" : "Toggle X-ray view"}
          style={{
            padding: "8px 16px",
            fontSize: 12,
            border: xray ? `1px solid ${C.ink}` : `1px solid #d8d8dc`,
            background: xray ? C.ink : "#ffffff",
            color: xray ? "#ffffff" : C.ink,
          }}
        >
          <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: "currentColor" }} />
          X-ray
        </GhostButton>
        {/* The declared-parent seat is a single-part affordance; in real-assembly
            mode the neighbours are already the context, so it is hidden. */}
        {!assembly && (
          <GhostButton
            onClick={() => {
              if (hasParent && webGlAvailable === true) setSeat((v) => !v);
            }}
            disabled={!hasParent || webGlAvailable !== true}
            title={
              webGlAvailable === false
                ? "Assembly seating requires interactive 3D support"
                : hasParent
                ? "Seat the part in its declared parent assembly"
                : "No parent assembly has been declared for this part"
            }
            style={{
              padding: "8px 16px",
              fontSize: 12,
              border: seat && hasParent ? `1px solid ${C.ink}` : `1px solid #d8d8dc`,
              background: seat && hasParent ? C.ink : "#ffffff",
              color: seat && hasParent ? "#ffffff" : C.ink,
            }}
          >
            {hasParent ? "Seat in assembly" : "No parent assembly"}
          </GhostButton>
        )}
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink35, paddingLeft: 6, whiteSpace: "nowrap" }}>
          {webGlAvailable === false ? "static preview" : webGlAvailable === null ? "checking 3D…" : "drag to orbit"}
        </span>
      </div>
    </main>
  );
}

/** Honest no-WebGL stage: measured envelope, not an invented part silhouette.
 * All geometry/verdict data remains usable while the unavailable interaction is
 * named explicitly. */
function StaticStageFallback({
  bbox,
  hasFile,
  checking,
}: {
  bbox: [number, number, number] | null;
  hasFile: boolean;
  checking: boolean;
}) {
  const dimensions = bbox?.every((n) => Number.isFinite(n) && n > 0)
    ? `${bbox.map((n) => n.toFixed(1)).join(" × ")} mm`
    : null;
  return (
    <div
      data-testid="verify-stage-webgl-fallback"
      data-webgl-state={checking ? "checking" : "unavailable"}
      role="status"
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 14,
        padding: "96px 28px 84px",
        textAlign: "center",
        color: C.ink55,
        cursor: "default",
      }}
    >
      <svg width="188" height="132" viewBox="0 0 188 132" fill="none" aria-hidden>
        <path d="M35 45 90 16l62 31-57 31-60-33Z" fill="rgba(255,255,255,0.55)" stroke="#aeb4bd" />
        <path d="m35 45 60 33v39L35 82V45Z" fill="rgba(210,215,222,0.32)" stroke="#aeb4bd" />
        <path d="m95 78 57-31v39l-57 31V78Z" fill="rgba(190,198,208,0.3)" stroke="#aeb4bd" />
        <path d="M23 117h142M20 112v10m148-10v10" stroke="#c6cbd2" strokeDasharray="4 5" />
        <circle cx="35" cy="45" r="2.5" fill="#3b7bb8" />
        <circle cx="95" cy="78" r="2.5" fill="#3b7bb8" />
        <circle cx="152" cy="47" r="2.5" fill="#3b7bb8" />
      </svg>
      <div style={{ maxWidth: 320 }}>
        <p style={{ margin: 0, fontSize: 13.5, fontWeight: 500, color: C.ink }}>
          {checking
            ? "Checking interactive 3D support…"
            : hasFile
              ? "Interactive 3D is unavailable in this browser."
              : "Interactive 3D is unavailable in this browser."}
        </p>
        <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, lineHeight: 1.6, color: C.ink45 }}>
          {dimensions
            ? `measured envelope · ${dimensions} · geometry and verdict remain available`
            : hasFile
              ? "local CAD preview only · measured dimensions appear if parsing completes"
              : "drop a part to measure its envelope; verification remains fully available"}
        </p>
      </div>
    </div>
  );
}

/** The assembly counterpart of ContextStrip: honest that this is a real
 *  multi-part assembly (N parts) and that the render shows the part-of-interest
 *  in its true neighbours — NOT a declared/synthetic parent envelope. */
function AssemblyStrip({ partCount, analysisReady }: { partCount: number; analysisReady: boolean }) {
  return (
    <div
      className="cv-verify-stage-context-card"
      data-testid="verify-stage-assembly"
      data-assembly-parts={partCount}
      style={{
        position: "absolute",
        top: 22,
        right: 20,
        width: "min(300px, calc(100% - 44px))",
        border: `1px solid rgba(59,123,184,0.28)`,
        background: "rgba(255,255,255,0.78)",
        backdropFilter: "blur(14px)",
        borderRadius: 12,
        padding: "12px 13px",
        boxShadow: "0 12px 34px rgba(23,24,26,0.08)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.13em", color: C.ink45 }}>
          ASSEMBLY
        </p>
        <span style={{ fontFamily: MONO, fontSize: 10, color: C.measured }}>● real shell</span>
      </div>
      <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, lineHeight: 1.5, color: C.ink }}>
        {partCount} parts in world position
      </p>
      <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 6 }}>
        <ContextPill color={C.measured}>part in context</ContextPill>
        {analysisReady ? (
          <ContextPill color={C.measured}>per-part DFM + cost</ContextPill>
        ) : (
          <ContextPill>analysing per-part…</ContextPill>
        )}
      </div>
    </div>
  );
}

function ContextStrip({
  partName,
  context,
  contextError,
  hasParent,
}: {
  partName: string;
  context: PartContext | null;
  contextError: string | null;
  hasParent: boolean;
}) {
  const serviceEnv = context?.service_environment;
  const envDeclared = Boolean(serviceEnv && Object.keys(serviceEnv).length > 0);
  const lineage = hasParent
    ? [context?.program, context?.parent_assembly, partName].filter(Boolean).join(" -> ")
    : "no parent assembly declared";

  return (
    <div
      className="cv-verify-stage-context-card"
      data-testid="verify-stage-context"
      data-context-state={hasParent ? "declared-parent" : "no-parent"}
      style={{
        position: "absolute",
        top: 22,
        right: 20,
        width: "min(300px, calc(100% - 44px))",
        border: `1px solid ${hasParent ? "rgba(122,99,201,0.28)" : C.hair}`,
        background: "rgba(255,255,255,0.78)",
        backdropFilter: "blur(14px)",
        borderRadius: 12,
        padding: "12px 13px",
        boxShadow: "0 12px 34px rgba(23,24,26,0.08)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.13em", color: C.ink45 }}>
          CONTEXT
        </p>
        {hasParent ? (
          <ProvChip p="USER" />
        ) : (
          <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}>not declared</span>
        )}
      </div>
      <p
        style={{
          margin: "8px 0 0",
          fontFamily: MONO,
          fontSize: 11,
          lineHeight: 1.5,
          color: hasParent ? C.ink : C.ink50,
          overflowWrap: "anywhere",
        }}
      >
        {lineage}
      </p>
      <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 6 }}>
        {context?.units_per_parent != null && (
          <ContextPill>{context.units_per_parent} / parent</ContextPill>
        )}
        {envDeclared && <ContextPill color={C.user}>service world</ContextPill>}
        {contextError && <ContextPill color={C.fail}>context read failed</ContextPill>}
        {!hasParent && !contextError && <ContextPill>orphan until declared</ContextPill>}
      </div>
    </div>
  );
}

function ContextPill({ children, color = C.ink45 }: { children: ReactNode; color?: string }) {
  return (
    <span
      style={{
        border: `1px solid ${C.hair}`,
        borderRadius: 999,
        padding: "3px 7px",
        fontFamily: MONO,
        fontSize: 9.5,
        color,
        background: "rgba(246,246,247,0.72)",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}
