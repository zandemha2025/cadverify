"use client";

/** Command palette and notification entrypoints for the Verify shell. */
import * as React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { C, MONO } from "@/lib/verify/tokens";
import { useToast } from "./toast";

function CommandPill({ label }: { label: string }) {
  return (
    <span style={{ border: `1px dashed ${C.hair}`, borderRadius: 999, padding: "3px 8px", fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.08em", color: C.ink45 }}>
      {label}
    </span>
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
 * fabricates nothing — there are no invented engine answers here. The Verify dock
 * owns engine asks; the Part screen owns part lookup. Typing filters the list;
 * ↑/↓ move, ↵ runs, Esc closes.
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
  const toast = useToast();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const all: PaletteCmd[] = useMemo(() => {
    const go = (s: string) => () => {
      nav(s);
    };
    const sample = (label: string) => () => {
      nav("verify");
      toast(`${label} — sample walkthrough selected; upload the sample CAD to compute real outputs.`);
    };
    const list: PaletteCmd[] = [
      { id: "verify-part", label: "Verify a part", hint: "open STL, STEP or IGES", terms: "verify part upload drop stl step stp iges igs file measure cost", run: () => { onVerify?.(); onClose(); } },
      { id: "play-fixture", label: "Play use case · real fixture", hint: "sample walkthrough", terms: "play use case real fixture sample walkthrough", run: sample("Real fixture") },
      { id: "play-impeller", label: "Play use case · negative impeller verdict", hint: "sample walkthrough", terms: "play use case negative impeller sample verdict blocker hostile", run: sample("Negative impeller verdict") },
      { id: "play-day-zero", label: "Play use case · org day zero", hint: "sample walkthrough", terms: "play use case first run org day zero setup", run: () => { nav("home"); toast("Org day zero — use the setup checklist; no tenant data is fabricated."); } },
      { id: "home", label: "Go to Home", keys: "H", terms: "home desk start", run: go("home") },
      { id: "verify", label: "Go to Verify", keys: "V", terms: "verify verdict result", run: go("verify") },
      { id: "catalog", label: "Go to Parts", hint: "catalog", keys: "P", terms: "parts catalog grid", run: go("catalog") },
      { id: "part", label: "Go to Part standing page", hint: "selected part", terms: "part standing detail memory context history blocker", run: go("part") },
      { id: "records", label: "Go to Records", keys: "R", terms: "records history log verifications", run: go("records") },
      { id: "programs", label: "Go to Programs", keys: "G", terms: "programs portfolio exposure", run: go("programs") },
      { id: "machines", label: "Go to Your machines", keys: "M", terms: "machines inventory shop floor", run: go("machines") },
      { id: "triage", label: "Go to Triage", keys: "T", terms: "triage bom batch scale", run: go("triage") },
      { id: "calibration", label: "Go to Calibration & truth", keys: "C", terms: "calibration truth rates rate library governance", run: go("calibration") },
      { id: "add-machine", label: "Add or import machines", hint: "declare your floor", terms: "add machine import csv declare floor capability rate", run: go("machines") },
      { id: "switch-calibration", label: "Switch calibration context", hint: "rates + actuals", terms: "switch calibration context rates truth actuals", run: go("calibration") },
      { id: "create-program", label: "Create or assign a program", hint: "assembly lineage", terms: "create assign program assembly lineage platform", run: go("programs") },
      { id: "compare-decisions", label: "Compare saved decisions", hint: "record diff", terms: "compare saved decisions diff record", run: go("compare") },
      { id: "preview-record", label: "Preview records", hint: "audit memory", terms: "record preview audit memory persisted", run: go("records") },
      { id: "plan-acquisition", label: "Plan capability acquisition", hint: "blocked in-house", terms: "acquisition acquire capability machine gap", run: go("acquisition") },
    ];
    if (onShortcuts) {
      list.push({ id: "shortcuts", label: "Keyboard shortcuts", keys: "?", terms: "shortcuts keys help hotkeys", run: () => { onClose(); onShortcuts(); } });
    }
    return list;
  }, [nav, onClose, onVerify, onShortcuts, toast]);

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
            placeholder="Jump to a surface or action…"
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
          <CommandPill label="JUMP · ACTION · SAMPLE" />
          <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink45 }}>sample walkthroughs never fabricate tenant records</span>
        </div>
      </div>
    </div>
  );
}

// NotificationsPanel derives states from live reads and stays colocated with the
// shell entrypoints for a compact import at the top level.
export { NotificationsPanel } from "./notifications-panel";
