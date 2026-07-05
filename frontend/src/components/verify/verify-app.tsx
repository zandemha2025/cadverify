"use client";

/**
 * The product Verify app — the founder-approved "light instrument" recreated in
 * the production stack and wired to the real engine. One client shell (rail + top
 * bar + screen router) holding all state, behind NEXT_PUBLIC_VERIFY_UI. Explicit-
 * hex, theme-independent (the rest of the app is dark-first); flag-off this whole
 * tree is unreachable, so the existing app is byte-identical.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { C, MONO, SANS } from "@/lib/verify/tokens";
import { runVerification, type VerifyResult } from "@/lib/verify/run";
import { listMachines } from "@/lib/verify/machine-api";
import { Stage } from "./stage";
import { VerifyScreen } from "./verify-screen";
import { MachinesScreen } from "./machines-screen";
import { RecordsScreen } from "./records-screen";
import { TriageScreen } from "./triage-screen";
import { HomeScreen } from "./home-screen";
import { StubScreen, AcquisitionModal, CommandPalette, NotificationsPanel } from "./stub-screens";
import { ToastProvider } from "./toast";
import { ShortcutsOverlay } from "./shortcuts-overlay";
import { CalibrationSwitcher } from "./calibration-switcher";

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

type Screen =
  | "home" | "verify" | "catalog" | "compare" | "records" | "programs" | "machines" | "triage" | "calibration"
  | "acquisition" | "palette";

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

const CRUMB: Record<string, string> = {
  home: "Home",
  verify: "Verify",
  catalog: "Parts",
  records: "Records",
  programs: "Programs",
  machines: "Your machines",
  triage: "Triage at scale",
  calibration: "Calibration & truth",
};

export function VerifyApp() {
  const [screen, setScreen] = useState<Screen>("home");
  const [env, setEnv] = useState({ temp: false, sour: false, pressure: false });
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [running, setRunning] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [notifOpen, setNotifOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  // A REAL signal for the rail footer: are any of the org's machines declaring an
  // hourly rate (i.e. a shop rate is actually bound)? null while loading → the dot
  // stays hollow/neutral until a bound rate is detected — never a hardcoded claim.
  const [ratesBound, setRatesBound] = useState<boolean | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  // The last part the user verified — so a change to the declared world can re-run
  // the verification (re-persist the env + re-cost against it) for the same part.
  const latestFile = useRef<File | null>(null);

  const nav = useCallback((s: string) => {
    if (s === "acquisition") return setScreen("acquisition");
    if (s === "palette") return setScreen("palette");
    setScreen(s as Screen);
  }, []);

  const pickFile = useCallback(() => fileRef.current?.click(), []);

  const runVerify = useCallback(
    async (f: File) => {
      setFile(f);
      latestFile.current = f;
      setScreen("verify");
      setRunning(true);
      setResult(null);
      try {
        const r = await runVerification({ file: f, env, materialClass: "polymer" });
        setResult(r);
      } finally {
        setRunning(false);
      }
    },
    [env]
  );

  const onReverify = useCallback(() => {
    if (file) void runVerify(file);
    else pickFile();
  }, [file, runVerify, pickFile]);

  // The rail footer's bound-rate signal.
  useEffect(() => {
    listMachines().then(
      (p) => setRatesBound(p.machines.some((m) => typeof m.hourly_rate_usd === "number" && Number.isFinite(m.hourly_rate_usd))),
      () => setRatesBound(false)
    );
  }, []);

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
        setNotifOpen(false);
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

  const onVerify = screen === "verify";

  return (
    <ToastProvider>
    <div style={{ height: "100vh", display: "flex", background: C.bg, color: C.ink, fontFamily: SANS, WebkitFontSmoothing: "antialiased", fontSize: 14 }}>
      <style>{KEYFRAMES}</style>
      <input
        ref={fileRef}
        type="file"
        accept=".stl,.step,.stp,model/stl,application/step"
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void runVerify(f);
          e.target.value = "";
        }}
      />

      {/* rail */}
      <nav style={{ width: 64, flexShrink: 0, borderRight: `1px solid ${C.hair2}`, background: C.panel, display: "flex", flexDirection: "column", alignItems: "center", padding: "14px 0", gap: 6 }}>
        <div style={{ width: 30, height: 30, borderRadius: 8, background: C.ink, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 600, fontSize: 13, marginBottom: 14 }}>C</div>
        {RAIL.map((r) => {
          const active = screen === r.key || (r.key === "catalog" && screen === "compare");
          return (
            <button
              key={r.key}
              type="button"
              onClick={() => setScreen(r.key)}
              title={r.label}
              style={{ width: 40, height: 40, borderRadius: 10, border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", background: active ? "#eceef1" : "transparent", color: active ? C.ink : C.ink40, transition: "all 150ms" }}
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d={r.d} />
              </svg>
            </button>
          );
        })}
        <div style={{ marginTop: "auto" }}>
          <button
            type="button"
            onClick={() => setScreen("calibration")}
            title={
              ratesBound
                ? "Your shop rates are bound · ● SHOP — open Calibration & truth"
                : "Calibration & truth — no shop rate bound yet"
            }
            style={{ border: "none", background: "none", padding: 4, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}
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
        </div>
      </nav>

      {/* main */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <header style={{ height: 52, flexShrink: 0, borderBottom: `1px solid ${C.hair2}`, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 20px", background: C.panel }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: C.ink50 }}>
            <span>{CRUMB[screen] ?? "CadVerify"}</span>
            {onVerify && result?.file && (
              <>
                <span style={{ color: C.ink35 }}>/</span>
                <span style={{ color: C.ink, fontFamily: MONO, fontSize: 12.5 }}>{result.file.name}</span>
              </>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <CalibrationSwitcher onOpenCalibration={() => setScreen("calibration")} />
            <button type="button" onClick={() => setScreen("palette")} title="Command palette (⌘K)" style={{ display: "inline-flex", alignItems: "center", gap: 6, border: `1px solid ${C.hair}`, background: "#fff", borderRadius: 999, padding: "7px 13px", fontFamily: MONO, fontSize: 11, color: C.ink55, cursor: "pointer" }}>⌘K</button>
            <button type="button" onClick={() => setNotifOpen((v) => !v)} title="Notifications" style={{ width: 32, height: 32, borderRadius: "50%", border: `1px solid ${C.hair}`, background: "#fff", cursor: "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center", color: C.ink55 }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>
            </button>
            <button type="button" onClick={pickFile} style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 999, padding: "8px 18px", fontSize: 13, fontWeight: 500, cursor: "pointer", fontFamily: "inherit" }}>Verify a part</button>
          </div>
        </header>

        {notifOpen && <NotificationsPanel onClose={() => setNotifOpen(false)} />}

        {screen === "home" && <HomeScreen onPickFile={pickFile} nav={nav} />}
        {screen === "verify" && (
          <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
            <Stage
              file={file}
              partName={result?.file?.name ?? file?.name ?? "No part yet"}
              meta1={
                result?.cost?.geometry
                  ? `Ø/bbox ${result.cost.geometry.bbox_mm.map((n) => n.toFixed(1)).join(" × ")} mm · ${result.cost.geometry.volume_cm3.toFixed(2)} cm³`
                  : running
                    ? "measuring geometry…"
                    : "drop a STEP or STL to measure"
              }
              meta2={result?.cost?.geometry ? `watertight ${String(result.cost.geometry.watertight)} · ● MEASURED` : undefined}
              bbox={result?.cost?.geometry?.bbox_mm ?? null}
              hostile={env.temp || env.sour || env.pressure}
              autoOrbit={running}
            />
            <VerifyScreen
              result={result}
              running={running}
              fileName={result?.file?.name ?? file?.name ?? null}
              env={env}
              setEnv={setEnv}
              onPickFile={pickFile}
              onReverify={onReverify}
              nav={nav}
            />
          </div>
        )}
        {screen === "machines" && <MachinesScreen />}
        {screen === "records" && <RecordsScreen nav={nav} />}
        {screen === "triage" && <TriageScreen nav={nav} />}
        {(screen === "catalog" || screen === "compare" || screen === "programs" || screen === "calibration") && (
          <StubScreen id={screen} />
        )}
      </div>

      {screen === "acquisition" && <AcquisitionModal onClose={() => setScreen("verify")} />}
      {screen === "palette" && <CommandPalette onClose={() => setScreen("home")} nav={nav} />}
      {shortcutsOpen && <ShortcutsOverlay onClose={() => setShortcutsOpen(false)} />}
    </div>
    </ToastProvider>
  );
}

const KEYFRAMES = `
@keyframes vspin { to { transform: rotate(360deg); } }
@keyframes vscreenIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes vstepIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@keyframes vtraceIn { from { opacity: 0; transform: translateX(-5px); } to { opacity: 1; transform: translateX(0); } }
@keyframes vtoastIn { from { opacity: 0; transform: translate(-50%, 8px); } to { opacity: 1; transform: translate(-50%, 0); } }
`;
