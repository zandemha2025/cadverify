"use client";

/**
 * Honest IN DEVELOPMENT surfaces. Everything outside the wired core loop ships as
 * a visible, labelled, non-fake-interactive state styled in the light-instrument
 * register — never a fabricated screen full of invented numbers. Each states what
 * it WILL be and which real seam it will bind to.
 */
import * as React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { C, MONO } from "@/lib/verify/tokens";
import { Kicker, InDev, GhostButton } from "./primitives";

interface StubDef {
  title: string;
  lede: string;
  seam: string;
}

export const STUBS: Record<string, StubDef> = {
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

interface PaletteCmd {
  id: string;
  label: string;
  hint?: string;
  keys?: string;
  /** search terms (space-separated) matched against the query, in addition to label */
  terms: string;
  run: () => void;
}

/**
 * Command palette — a REAL jump-anywhere launcher. Every row is a genuine local
 * action: navigate to a surface (the same targets the H/V/P/R/G/M/T/C hotkeys
 * hit), open the file picker to verify a part, or open the shortcuts sheet. It
 * fabricates nothing — there are no invented engine answers here. Free-text
 * "ask the engine" and part/lakehouse search are labelled IN DEVELOPMENT rather
 * than faked. Typing filters the list; ↑/↓ move, ↵ runs, Esc closes.
 */
export function CommandPalette({
  onClose,
  nav,
  onVerify,
  onShortcuts,
}: {
  onClose: () => void;
  nav: (s: string) => void;
  onVerify?: () => void;
  onShortcuts?: () => void;
}) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const all: PaletteCmd[] = useMemo(() => {
    const go = (s: string) => () => {
      nav(s);
      onClose();
    };
    const list: PaletteCmd[] = [
      { id: "verify-part", label: "Verify a part", hint: "open a STEP or STL", terms: "verify part upload drop stl step file measure cost", run: () => { onVerify?.(); onClose(); } },
      { id: "home", label: "Go to Home", keys: "H", terms: "home desk start", run: go("home") },
      { id: "verify", label: "Go to Verify", keys: "V", terms: "verify verdict result", run: go("verify") },
      { id: "catalog", label: "Go to Parts", hint: "catalog", keys: "P", terms: "parts catalog grid", run: go("catalog") },
      { id: "records", label: "Go to Records", keys: "R", terms: "records history log verifications", run: go("records") },
      { id: "programs", label: "Go to Programs", keys: "G", terms: "programs portfolio exposure", run: go("programs") },
      { id: "machines", label: "Go to Your machines", keys: "M", terms: "machines inventory shop floor", run: go("machines") },
      { id: "triage", label: "Go to Triage", keys: "T", terms: "triage bom batch scale", run: go("triage") },
      { id: "calibration", label: "Go to Calibration & truth", keys: "C", terms: "calibration truth rates rate library governance", run: go("calibration") },
    ];
    if (onShortcuts) {
      list.push({ id: "shortcuts", label: "Keyboard shortcuts", keys: "?", terms: "shortcuts keys help hotkeys", run: () => { onClose(); onShortcuts(); } });
    }
    return list;
  }, [nav, onClose, onVerify, onShortcuts]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return all;
    // Predictable prefix search: the label as a whole, or any single search
    // term, must START with the query (so "cal" hits Calibration, not the
    // "scale" inside Triage's terms).
    return all.filter(
      (c) =>
        c.label.toLowerCase().includes(s) ||
        c.terms.split(" ").some((t) => t.startsWith(s))
    );
  }, [q, all]);

  useEffect(() => {
    setActive(0);
  }, [q]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(filtered.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      filtered[active]?.run();
    }
    // Esc bubbles to the shell's global keydown handler, which closes the palette.
  };

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 70, background: "rgba(23,24,26,0.35)", display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: 120 }} onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        style={{ width: 520, maxWidth: "90%", background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 16, boxShadow: "0 18px 50px -18px rgba(23,24,26,0.35)", overflow: "hidden", animation: "vscreenIn 200ms cubic-bezier(0.2,0,0,1) both" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "13px 16px", borderBottom: `1px solid ${C.hair}` }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={C.ink45} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search or jump to a surface…"
            style={{ flex: 1, border: "none", outline: "none", background: "none", fontSize: 14, color: C.ink, fontFamily: "inherit" }}
          />
          <kbd style={{ fontFamily: MONO, fontSize: 10, border: `1px solid ${C.hair}`, borderRadius: 5, padding: "2px 6px", color: C.ink45, background: C.sunken }}>Esc</kbd>
        </div>
        <div style={{ maxHeight: 340, overflowY: "auto", padding: 6 }}>
          {filtered.length === 0 ? (
            <p style={{ margin: 0, padding: "18px 14px", fontFamily: MONO, fontSize: 12, color: C.ink50, lineHeight: 1.55 }}>
              No matches — the palette jumps and acts; it never invents an answer.
            </p>
          ) : (
            filtered.map((c, i) => (
              <button
                key={c.id}
                type="button"
                onClick={c.run}
                onMouseEnter={() => setActive(i)}
                style={{ width: "100%", textAlign: "left", background: i === active ? C.sunken : "none", border: "none", borderRadius: 10, padding: "10px 14px", cursor: "pointer", fontFamily: "inherit", fontSize: 13, color: C.ink, display: "flex", alignItems: "center", gap: 10 }}
              >
                <span style={{ flex: 1 }}>
                  {c.label}
                  {c.hint && <span style={{ marginLeft: 8, color: C.ink45, fontSize: 12 }}>{c.hint}</span>}
                </span>
                {c.keys && (
                  <kbd style={{ fontFamily: MONO, fontSize: 10.5, minWidth: 20, textAlign: "center", border: `1px solid ${C.hair}`, borderRadius: 5, padding: "2px 6px", color: C.ink55, background: C.panel }}>{c.keys}</kbd>
                )}
              </button>
            ))
          )}
        </div>
        <div style={{ borderTop: `1px solid ${C.hair}`, padding: "9px 16px", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <InDev label="ENGINE ASKS & PART SEARCH — IN DEVELOPMENT" />
          <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink45 }}>the palette jumps and acts — it never fabricates a number</span>
        </div>
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
