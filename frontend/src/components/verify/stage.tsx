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
import type { StageAssemblyContext } from "./stage-canvas";
import { GhostButton, ProvChip } from "./primitives";

const StageCanvas = dynamic(() => import("./stage-canvas"), {
  ssr: false,
  loading: () => null,
});

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
}) {
  const [xray, setXray] = useState(false);
  const [seat, setSeat] = useState(false);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const isStl = useMemo(
    () => !!file && file.name.toLowerCase().endsWith(".stl"),
    [file]
  );
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

  useEffect(() => {
    if (!hasParent) setSeat(false);
  }, [hasParent]);

  useEffect(() => {
    if (file && file.name.toLowerCase().endsWith(".stl")) {
      const url = URL.createObjectURL(file);
      setFileUrl(url);
      return () => URL.revokeObjectURL(url);
    }
    setFileUrl(null);
  }, [file]);

  return (
    <main
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
        <StageCanvas
          fileUrl={fileUrl}
          isStl={isStl}
          bbox={bbox}
          xray={xray}
          hostile={hostile}
          autoOrbit={autoOrbit}
          seat={seat}
          assemblyContext={assemblyContext}
        />
      </div>

      <div style={{ position: "absolute", top: 22, left: 24, pointerEvents: "none" }}>
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
      </div>

      <ContextStrip
        partName={partName}
        context={context}
        contextError={contextError}
        hasParent={hasParent}
      />

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
        <GhostButton
          onClick={() => {
            if (hasParent) setSeat((v) => !v);
          }}
          disabled={!hasParent}
          title={
            hasParent
              ? "Seat the part in its declared parent context"
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
          {hasParent ? "Seat in context" : "No parent assembly"}
        </GhostButton>
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink35, paddingLeft: 6, whiteSpace: "nowrap" }}>
          drag to orbit
        </span>
      </div>
    </main>
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
