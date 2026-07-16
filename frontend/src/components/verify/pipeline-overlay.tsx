"use client";

/**
 * THE PIPELINE RAIL — the request lifecycle without hiding the part.
 *
 * This compact, non-modal rail opens when verification starts. It leaves the CAD
 * preview visible, then yields as soon as validation produces the first useful
 * routing + DFM answer. Cost continues sequentially to protect worker memory.
 *
 * Honesty: nothing is shown before it is real. While the request is in flight the
 * downstream stages are pending with NO values. When the result lands, every line
 * is read off the response (pipeline.ts) or is the honest absence of one. The walk
 * STOPS at a real failed gate — the stages past it read "not computed", never
 * faked. The user can dismiss (✕ / Esc) at any time to jump straight to the result.
 */
import { useEffect, useRef, useState } from "react";
import { analysisFailureCopy } from "@/lib/verify/failure-copy";
import { C, MONO } from "@/lib/verify/tokens";
import type { VerifyResult } from "@/lib/verify/run";
import { pipelineModelFrom, type PipelineStage, type StageState } from "@/lib/verify/pipeline";
import { useToast } from "./toast";

const SETTLE_MS = 420;

type Phase = "idle" | "computing" | "revealing" | "settled";

function toneColor(t: PipelineStage["tone"]): string {
  return t === "pass" ? C.pass : t === "cond" ? C.cond : t === "fail" ? C.fail : C.ink;
}

function stateColor(s: StageState, tone: PipelineStage["tone"]): string {
  if (s === "blocked") return C.fail;
  if (s === "done") return toneColor(tone) === C.ink ? C.ink : toneColor(tone);
  if (s === "withheld") return C.ink45;
  return C.ink35; // pending
}

export function PipelineOverlay({
  running,
  result,
  fileName,
  guided = false,
  onDone,
}: {
  running: boolean;
  result: VerifyResult | null;
  fileName: string | null;
  guided?: boolean;
  onDone?: () => void;
}) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  // How many stages have "landed" (received counts as 1). During computing only the
  // received stage is landed; the reveal cascade grows this as real values arrive.
  const [reveal, setReveal] = useState(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  const dismiss = () => {
    clearTimers();
    setOpen(false);
    setPhase("idle");
    onDone?.();
  };

  // ── in flight: pop the overlay, hold at "received", nothing downstream faked ──
  useEffect(() => {
    if (running && !result) {
      clearTimers();
      setPhase("computing");
      setReveal(1);
      // Fast runs should feel instant, not flash a spinner. The rail only appears
      // once the operation crosses the standard perceptible-wait threshold.
      timers.current.push(setTimeout(() => setOpen(true), 260));
    } else if (!open) {
      clearTimers();
    }
    // `open` is intentionally excluded: opening after the delay must not restart it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, result]);

  // ── result landed while the overlay is up: reveal the real stages on cadence ──
  useEffect(() => {
    // Only reveal if we actually saw the computing phase for this run (open) — a
    // pre-existing result from navigation must NOT pop the overlay.
    if (!open || !result || phase === "revealing" || phase === "settled") return;
    // The first-run example has its own plain-language result summary. Once the
    // real response lands, hand off immediately instead of making a new user sit
    // through the expert evidence cadence before seeing the answer.
    if (guided) {
      clearTimers();
      setOpen(false);
      setPhase("idle");
      onDone?.();
      return;
    }
    const model = pipelineModelFrom(result, false, fileName);
    // Did the engine actually compute anything? A part that fails to parse/tessellate
    // returns no routing, no DFM, no geometry, no cost — the completion toast would be
    // a lie. (A GEOMETRY_INVALID refusal still MEASURED the geometry, so it counts as
    // analyzed and stops honestly at a real gate.)
    const analyzed = !!(result.cost || result.validation || result.costGeometryInvalid);
    // Validation has landed while cost continues. Hand off immediately to the
    // value-bearing inline DFM card; never narrate unfinished cost as complete.
    if (running) {
      clearTimers();
      setReveal(Math.min(3, model.stages.length));
      setPhase("settled");
      timers.current.push(
        setTimeout(() => {
          setOpen(false);
          setPhase("idle");
          onDone?.();
        }, 220)
      );
      return;
    }
    // The real result is already available, so land it immediately. Motion marks
    // truth; it does not add a theatrical multi-second delay before the answer.
    const target = model.stopIndex >= 0 ? model.stopIndex + 1 : model.stages.length;
    clearTimers();
    setReveal(target);
    setPhase("settled");
    timers.current.push(
      setTimeout(() => {
        setOpen(false);
        setPhase("idle");
        toast(
          analyzed
            ? "Verification complete — deterministic: same input, same verdict, every time"
            : analysisFailureCopy(result.costError || result.validationError).toast
        );
        onDone?.();
      }, SETTLE_MS)
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, result, fileName, guided, running]);

  // An unexpected request failure can end with no result. Do not strand the user
  // behind a forever-running modal; the screen-level recovery state remains visible.
  useEffect(() => {
    if (!open || running || result || phase !== "computing") return;
    clearTimers();
    setOpen(false);
    setPhase("idle");
    onDone?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, running, result, phase]);

  // Esc dismisses (design: Esc closes all).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        dismiss();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => () => clearTimers(), []);

  if (!open) return null;

  const model = pipelineModelFrom(result, running && !result, fileName);

  if (guided) {
    return (
      <div
        role="status"
        aria-label="Checking the sample CAD"
        aria-live="polite"
        style={{
          position: "fixed",
          top: 126,
          right: 24,
          zIndex: 70,
          width: "min(430px, calc(100vw - 32px))",
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            width: "100%",
            background: C.panel,
            border: `1px solid ${C.hair}`,
            borderRadius: 20,
            padding: "28px 30px",
            boxShadow: "0 30px 80px -30px rgba(23,24,26,0.3)",
            animation: "vscreenIn 300ms cubic-bezier(0.2,0,0,1) both",
            pointerEvents: "auto",
          }}
        >
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, fontWeight: 650, letterSpacing: "0.14em", color: C.measured }}>
            REAL SAMPLE · RUNNING
          </p>
          <h2 style={{ margin: "10px 0 0", color: C.ink, fontSize: 25, fontWeight: 450, lineHeight: 1.2, letterSpacing: "-0.02em" }}>
            Reading the shape now. The first answer appears as soon as DFM lands.
          </h2>
          <p style={{ margin: "10px 0 0", color: C.ink55, fontSize: 13, lineHeight: 1.65 }}>
            The 3D stage stays visible while ProofShape measures, routes, and then calculates cost.
          </p>
          <div style={{ marginTop: 20, display: "grid", gap: 10 }}>
            {[
              "Read and measure the CAD",
              "Compare ways to manufacture it",
              "Explain cost and what is still uncertain",
            ].map((label, index) => (
              <div key={label} style={{ display: "flex", alignItems: "center", gap: 11, border: `1px solid ${C.hair2}`, borderRadius: 12, background: C.sunken, padding: "11px 13px" }}>
                <span aria-hidden style={{ width: 24, height: 24, flexShrink: 0, display: "grid", placeItems: "center", borderRadius: "50%", background: index === 0 ? C.measured : C.panel, border: `1px solid ${index === 0 ? C.measured : C.hair}`, color: index === 0 ? "#fff" : C.ink45, fontFamily: MONO, fontSize: 10 }}>
                  {index + 1}
                </span>
                <span style={{ color: C.ink, fontSize: 12.5, fontWeight: 550 }}>{label}</span>
                {index === 0 && <Dots />}
              </div>
            ))}
          </div>
          <p style={{ margin: "18px 0 0", borderTop: `1px solid ${C.hair2}`, paddingTop: 13, color: C.ink45, fontSize: 11.5, lineHeight: 1.55 }}>
            No setup is required for this example. Your own CAD files use the same engine.
          </p>
        </div>
      </div>
    );
  }

  const stopped = model.stopIndex >= 0 && reveal >= model.stopIndex + 1;
  const done = phase === "settled" && !stopped;

  const verdictText = stopped
    ? "THE WALK STOPS AT THE FAILED GATE"
    : done
      ? "COMPLETE — DETERMINISTIC · EVERY NUMBER CARRIES ITS SOURCE"
      : "COMPUTING — GATES CHECKING IN";
  const verdictColor = stopped ? C.fail : done ? C.pass : C.ink45;

  return (
    <div
      role="status"
      aria-label="Verification pipeline"
      aria-live="polite"
      style={{
        position: "fixed",
        top: 126,
        right: 24,
        zIndex: 70,
        width: "min(430px, calc(100vw - 32px))",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          width: "100%",
          background: C.panel,
          border: `1px solid ${C.hair}`,
          borderRadius: 20,
          padding: "26px 28px",
          boxShadow: "0 30px 80px -30px rgba(23,24,26,0.3)",
          animation: "vscreenIn 300ms cubic-bezier(0.2,0,0,1) both",
          pointerEvents: "auto",
        }}
      >
        <style>{"@keyframes vpip{0%,100%{opacity:.25}50%{opacity:1}}"}</style>
        {/* header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.14em", color: C.ink45 }}>
            VERIFYING · {model.fileName ?? "part"}
          </p>
          <button
            type="button"
            onClick={dismiss}
            title="Skip to the walk"
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              padding: 0,
              cursor: "pointer",
              fontFamily: MONO,
              fontSize: 13,
              color: C.ink40,
            }}
          >
            ✕
          </button>
        </div>

        {/* verdict kicker — reads COMPUTING until the walk settles or stops */}
        <p
          style={{
            margin: "12px 0 0",
            fontFamily: MONO,
            fontSize: 10,
            letterSpacing: "0.13em",
            color: verdictColor,
          }}
        >
          THE VERDICT · {verdictText}
        </p>

        {/* the five milestones */}
        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 11 }}>
          {model.stages.map((s, i) => {
            const landed = i < reveal;
            const isBlock = s.state === "blocked" && landed;
            const pastStop = model.stopIndex >= 0 && i > model.stopIndex;
            const showComputing = !landed && phase === "computing" && i === reveal;
            const color = landed ? stateColor(s.state, s.tone) : C.ink35;
            return (
              <div key={s.key}>
                <p
                  style={{
                    margin: 0,
                    fontFamily: MONO,
                    fontSize: 12,
                    lineHeight: 1.5,
                    color,
                    opacity: landed ? 1 : pastStop ? 0.35 : 0.4,
                    transition: "opacity 400ms, color 400ms",
                    display: "flex",
                    alignItems: "baseline",
                    gap: 8,
                  }}
                >
                  <span style={{ color: isBlock ? C.fail : color }}>{landed ? (isBlock ? "✗" : "▸") : "▸"}</span>
                  <span style={{ flexShrink: 0, fontWeight: landed ? 600 : 400 }}>{s.title}</span>
                  <span style={{ color: C.ink35 }}>—</span>
                  <span style={{ color: landed ? color : C.ink35 }}>
                    {landed
                      ? s.detail
                      : showComputing
                        ? s.detail
                        : pastStop
                          ? "not computed"
                          : s.detail}
                  </span>
                  {landed && s.measured && s.state !== "blocked" && (
                    <span style={{ color: C.measured, fontSize: 10 }}>● MEASURED</span>
                  )}
                  {showComputing && <Dots />}
                </p>
              </div>
            );
          })}
        </div>

        {/* the honest failed-gate note */}
        {stopped && (
          <div
            style={{
              marginTop: 16,
              border: `1px solid ${C.hair}`,
              background: "#fbf3f2",
              borderRadius: 12,
              padding: "12px 14px",
            }}
          >
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em", color: C.fail }}>
              THE WALK STOPS HERE
            </p>
            <p style={{ margin: "6px 0 0", fontSize: 12, lineHeight: 1.6, color: C.ink55 }}>
              Materials, physics, hours, and cost are not computed for a part that fails this gate — and they
              are never faked to fill the page. Fix the gate, and the walk continues.
            </p>
          </div>
        )}

        {/* footer — the determinism promise */}
        <p
          style={{
            margin: "18px 0 0",
            borderTop: `1px solid ${C.hair2}`,
            paddingTop: 12,
            fontFamily: MONO,
            fontSize: 10,
            lineHeight: 1.6,
            color: C.ink40,
          }}
        >
          deterministic — same input, same verdict, every time · no step is skipped, none is faked
        </p>
      </div>
    </div>
  );
}

/** A tiny animated ellipsis for the stage currently checking in. */
function Dots() {
  return (
    <span aria-hidden style={{ display: "inline-flex", gap: 2, marginLeft: 2 }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 3,
            height: 3,
            borderRadius: "50%",
            background: C.ink35,
            display: "inline-block",
            animation: `vpip 1000ms ${i * 160}ms infinite`,
          }}
        />
      ))}
    </span>
  );
}
