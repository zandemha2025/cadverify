"use client";

/**
 * Honest IN DEVELOPMENT surfaces. Everything outside the wired core loop ships as
 * a visible, labelled, non-fake-interactive state styled in the light-instrument
 * register — never a fabricated screen full of invented numbers. Each states what
 * it WILL be and which real seam it will bind to.
 */
import { C, MONO } from "@/lib/verify/tokens";
import { Kicker, InDev, GhostButton } from "./primitives";

interface StubDef {
  title: string;
  lede: string;
  seam: string;
}

export const STUBS: Record<string, StubDef> = {
  catalog: {
    title: "Parts catalog",
    lede: "Every part the org has asked about, thumbnails rendered from the geometry itself, facets and search over the real lakehouse read surface.",
    seam: "binds to GET /api/v1/catalog (org-scoped parts×decisions grid)",
  },
  compare: {
    title: "Compare",
    lede: "Same part, two questions: which calibration, and which route. Every figure banded, never fake-exact.",
    seam: "binds to GET /api/v1/cost-decisions/compare",
  },
  programs: {
    title: "Programs",
    lede: "Declare a world once, at the program — every part underneath inherits it. Exposure = verified unit cost × your entered volume, computed only when a verified part is assigned.",
    seam: "binds to the program/context surface (volume × unit cost = exposure)",
  },
  triage: {
    title: "Triage at scale",
    lede: "A whole BOM walked through the same verification, collapsed into honest makeability buckets — nothing silently skipped, every count opens into its verdicts.",
    seam: "binds to the batch / manifest ingest surface",
  },
  calibration: {
    title: "Calibration & truth",
    lede: "Your rates, the Hallmark ceremony (send actuals → bands flip solid), governed version-pinned changes, members, webhooks, usage, audit log.",
    seam: "binds to /rate-library, /governance, /ground-truth, webhooks",
  },
};

export function StubScreen({ id }: { id: string }) {
  const def = STUBS[id] ?? { title: id, lede: "This surface is not yet built.", seam: "" };
  return (
    <main style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "30px 34px", background: C.bg }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>{def.title}</h1>
        <InDev />
      </div>
      <p style={{ margin: "8px 0 0", maxWidth: 640, fontSize: 14, lineHeight: 1.6, color: C.ink55 }}>{def.lede}</p>
      <div style={{ marginTop: 24, maxWidth: 640, border: "1.5px dashed #c9cbd0", borderRadius: 18, background: C.panel, padding: "34px 30px" }}>
        <Kicker color={C.ink45}>NOT YET BUILT — AND NOT FAKED</Kicker>
        <p style={{ margin: "10px 0 0", fontSize: 14, lineHeight: 1.65, color: C.ink60 }}>
          This surface is designed and its backend seam is ready. It renders as an honest placeholder rather than
          inventing rows of example data. When it&apos;s wired, every figure here will be engine-computed.
        </p>
        {def.seam && <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>{def.seam}</p>}
      </div>
    </main>
  );
}

/** Acquisition-consideration modal — honest placeholder (no invented capex math). */
export function AcquisitionModal({ onClose }: { onClose: () => void }) {
  return (
    <Overlay onClose={onClose}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <p style={{ margin: 0, fontSize: 18, fontWeight: 500 }}>Acquisition consideration</p>
        <InDev />
        <button type="button" onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontFamily: MONO, fontSize: 14, color: C.ink40 }}>✕</button>
      </div>
      <p style={{ margin: "12px 0 0", fontSize: 13, lineHeight: 1.65, color: C.ink60 }}>
        A not-owned route is stated as a capital consideration — capex vs marginal, org-wide, with the crossover the
        engine already computed. The full capex model (payback, shared-cell amortization across the BOM) is designed and
        not yet wired, so no capex figures are invented here.
      </p>
    </Overlay>
  );
}

/** Command palette — honest, navigational only (no fabricated engine answers). */
export function CommandPalette({ onClose, nav }: { onClose: () => void; nav: (s: string) => void }) {
  const cmds: { label: string; go: string }[] = [
    { label: "Go to Home", go: "home" },
    { label: "Go to Verify", go: "verify" },
    { label: "Go to Records", go: "records" },
    { label: "Go to Your machines", go: "machines" },
    { label: "Go to Parts (catalog)", go: "catalog" },
    { label: "Go to Programs", go: "programs" },
    { label: "Go to Triage", go: "triage" },
    { label: "Go to Calibration & truth", go: "calibration" },
  ];
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 70, background: "rgba(23,24,26,0.35)", display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: 120 }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 520, maxWidth: "90%", background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 16, boxShadow: "0 18px 50px -18px rgba(23,24,26,0.35)", padding: 10, animation: "vscreenIn 200ms cubic-bezier(0.2,0,0,1) both" }}>
        <p style={{ margin: 0, padding: "10px 14px 8px", fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em", color: C.ink45 }}>JUMP ANYWHERE · scripted use-cases and engine asks are IN DEVELOPMENT</p>
        {cmds.map((c) => (
          <button key={c.go} type="button" onClick={() => { nav(c.go); onClose(); }} style={{ width: "100%", textAlign: "left", background: "none", border: "none", borderRadius: 10, padding: "10px 14px", cursor: "pointer", fontFamily: "inherit", fontSize: 13, color: C.ink }}>
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function NotificationsPanel({ onClose }: { onClose: () => void }) {
  return (
    <div style={{ position: "fixed", top: 58, right: 18, zIndex: 45, width: 340, background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 16, boxShadow: "0 18px 50px -18px rgba(23,24,26,0.25)", padding: 8, animation: "vscreenIn 200ms cubic-bezier(0.2,0,0,1) both" }}>
      <div style={{ display: "flex", alignItems: "center", padding: "10px 14px 8px" }}>
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em", color: C.ink45 }}>NOTIFICATIONS</p>
        <span style={{ marginLeft: 8 }}><InDev /></span>
        <button type="button" onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontFamily: MONO, fontSize: 12, color: C.ink40 }}>✕</button>
      </div>
      <p style={{ margin: 0, padding: "4px 14px 14px", fontFamily: MONO, fontSize: 11, color: C.ink50, lineHeight: 1.6 }}>
        States, never nags. Real notifications bind to the webhook delivery log (verification.completed, band flips) — not
        yet wired, so nothing is invented here.
      </p>
    </div>
  );
}

function Overlay({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(23,24,26,0.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 480, maxWidth: "100%", background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 18, boxShadow: "0 18px 50px -18px rgba(23,24,26,0.35)", padding: 24, animation: "vscreenIn 220ms cubic-bezier(0.2,0,0,1) both" }}>
        {children}
        <div style={{ marginTop: 18, display: "flex", justifyContent: "flex-end" }}>
          <GhostButton onClick={onClose}>Close</GhostButton>
        </div>
      </div>
    </div>
  );
}
