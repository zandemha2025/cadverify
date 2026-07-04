"use client";

/**
 * The part stage — a light studio with the part floating in it, its name + the
 * MEASURED geometry read overlaid, and the X-ray / drag-to-orbit affordances. The
 * WebGL canvas is dynamically imported (ssr:false) like the app's other viewers.
 */
import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { C, MONO } from "@/lib/verify/tokens";
import { GhostButton } from "./primitives";

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
}: {
  file: File | null;
  partName: string;
  meta1: string;
  meta2?: string;
  bbox: [number, number, number] | null;
  hostile: boolean;
  autoOrbit: boolean;
}) {
  const [xray, setXray] = useState(false);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const isStl = useMemo(
    () => !!file && file.name.toLowerCase().endsWith(".stl"),
    [file]
  );

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
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink35, paddingLeft: 6, whiteSpace: "nowrap" }}>
          drag to orbit
        </span>
      </div>
    </main>
  );
}
