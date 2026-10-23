"use client";

/** X10: the check's progress, stage by stage, from the real responses as they land. */
import * as React from "react";
import { dimsText, plural, progressSteps, type Step } from "./model";
import { chosenLine } from "./pick-words";
import { readsAsBodies, retryPrices, type CheckSession } from "./store";
import { busyReopenLabel, busyView, type BusyView } from "./busy-state";
import { BusyNotice, useNow } from "./busy-notice";
import { HeldNote, MaterialAsk } from "../onboard/material-ask";
import { inText } from "../units/units";
import { useUnits } from "../units/use-units";
import { API_BASE } from "@/lib/api-base";
import { expectedLine, type CheckTiming } from "./check-timing";

/** How long checks take here and what the server is running, read when a check starts and every 15 s while it runs (me-21). */
function useCheckTiming(running: boolean, sessionId: number): CheckTiming | null {
  const [t, setT] = React.useState<CheckTiming | null>(null);
  React.useEffect(() => {
    if (!running) return;
    let live = true;
    const read = () =>
      fetch(`${API_BASE}/checks/timing`, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((b) => live && b && setT(b as CheckTiming))
        .catch(() => undefined);
    void read();
    const iv = window.setInterval(read, 15000);
    return () => {
      live = false;
      window.clearInterval(iv);
    };
  }, [running, sessionId]);
  return t;
}

/** Re-render once a second while running, so the time so far moves. */
function useTick(on: boolean): void {
  const [, set] = React.useState(0);
  React.useEffect(() => {
    if (!on) return;
    const iv = window.setInterval(() => set((n) => n + 1), 1000);
    return () => window.clearInterval(iv);
  }, [on]);
}

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)} s`;
}

/**
 * A file of several bodies: measured as bodies, and checked body by body on the
 * part page, not stopped as an open shell (closed bodies that share edges aren't
 * one closed solid as a mesh).
 */
function bodySteps(s: CheckSession, steps: Step[]): Step[] {
  const v = s.validation ?? s.result?.validation ?? null;
  const pt = v?.part_type;
  if (!v || !pt || !readsAsBodies(v, s.file.name)) return steps;
  const n = pt.provisional ? "several solids" : plural(pt.body_count, "closed body", "closed bodies");
  const measured: Step = { t: "Measured", d: [dimsText(v.geometry.bounding_box_mm), n].filter(Boolean).join(" · "), state: "done" };
  if (v.geometry.is_watertight && !s.result?.costGeometryInvalid) {
    return steps.map((x) => (x.t === "Measured" && x.state === "done" ? { ...x, d: `${x.d} · ${plural(pt.body_count, "body", "bodies")}` } : x));
  }
  const done = s.status !== "running";
  return [
    steps[0],
    measured,
    { t: "Bodies read", d: pt.summary, state: "done" },
    { t: "Each body checked", d: done ? "On the part page, body by body · no check used" : "Waiting", state: done ? "done" : "wait" },
  ];
}

/** "Process chosen" names the same pick the part page opens with (ScaleCAD’s pick), never the router's usual route. */
function onePick(s: CheckSession, steps: Step[]): Step[] {
  const line = chosenLine(s.result?.cost ?? null);
  return steps.map((x) => {
    if (x.t === "Process chosen" && x.state === "done" && line) return { ...x, d: line };
    return x;
  });
}

/** Which step a busy server holds up, for the steps' "Waiting for room". */
function busyStep(bv: BusyView | null): { step: "measure" | "price"; live: boolean } | null {
  if (!bv) return null;
  const step = bv.phase === "waiting" ? bv.step : bv.still.step;
  if (step === "preview") return null;
  return { step: step === "cost" ? "price" : "measure", live: bv.phase === "waiting" };
}

export function progressModel(s: CheckSession) {
  const r = s.result;
  const bv = busyView(s);
  const steps: Step[] = onePick(s, bodySteps(s, progressSteps({
    fileName: s.file.name,
    sample: s.sample,
    validation: s.validation ?? r?.validation ?? null,
    cost: r?.cost ?? null,
    costError: r ? r.costError : null,
    geometryInvalid: s.status === "stopped" ? r?.costGeometryInvalid?.message ?? "not a closed solid" : null,
    done: s.status !== "running",
    busy: busyStep(bv),
  })));
  const running = s.status === "running";
  const stopped = s.status === "stopped";
  // Still busy before anything was measured: nothing checked, the file kept (the notice offers Try again).
  const unchecked = s.failure?.kind === "busy";
  const elapsed = (s.finishedAt ?? Date.now()) - s.startedAt;
  const title = running ? (s.sample ? "Checking the sample" : "Checking") : stopped ? "Stopped at Measured" : unchecked ? "Not checked yet" : "Checked";
  // The expected time comes from how long checks take here (ProgressPanel fills it); never a fixed promise.
  const meta = running ? [s.file.name, s.sample ? "No check used" : null] : stopped ? [s.file.name, "Not watertight"] : unchecked ? [s.file.name, "The file is kept"] : [s.file.name, seconds(elapsed)];
  const foot = running ? "Hiding this doesn’t stop the check." : stopped ? "Nothing after this step ran." : unchecked ? "Nothing after Received ran." : "Same file, same result, every time.";
  return { steps, running, stopped, title, meta, foot, busy: bv };
}

export function ProgressPanel({
  session,
  open,
  onOpenChange,
  action,
  onRetryCheck,
}: {
  session: CheckSession;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** "See what's wrong" (stopped) or "Open result" (done). */
  action?: React.ReactNode;
  /** "Try again" after the check stayed busy: the same file, checked again. */
  onRetryCheck?: () => void;
}) {
  const m = progressModel(session);
  const now = useNow(!open && m.busy?.phase === "waiting");
  const timing = useCheckTiming(m.running && !session.sample, session.id);
  useTick(m.running);
  const meta = m.meta.map((x) => x ?? expectedLine(timing, Date.now() - session.startedAt, true));
  // Sizes in the person's unit, like the rest of the part (me-04: "60 × 40 × 20 mm · 37.9 cm³" under an inches header).
  const { unit } = useUnits();
  const closeRef = React.useRef<HTMLButtonElement>(null);
  const reopenRef = React.useRef<HTMLButtonElement>(null);
  const wasOpen = React.useRef(open);
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector(".ob [aria-modal='true']")) return;
      e.preventDefault();
      onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);
  React.useEffect(() => {
    if (wasOpen.current && !open) reopenRef.current?.focus();
    wasOpen.current = open;
  }, [open]);
  const hideLabel = m.running ? "Hide progress" : "Close";
  if (!open)
    return (
      <button ref={reopenRef} className="btn sm reopen" type="button" onClick={() => onOpenChange(true)}>
        {m.busy ? busyReopenLabel(m.busy, now) : m.running ? "Checking · Show progress" : "Show progress"}
      </button>
    );
  const bv = m.busy;
  const retry = bv?.phase === "still" ? (bv.still.step === "cost" ? () => void retryPrices(session.id) : onRetryCheck) : undefined;
  return (
    <section className="prog" role="status" aria-live="polite" aria-labelledby="pg-title">
      <div className="hd">
        <div style={{ minWidth: 0 }}>
          <h1 className="stitle" id="pg-title">
            {m.title}
          </h1>
          <p className="pmeta" style={{ marginTop: 4 }}>
            {meta.map((t, i) => (
              <span key={i} style={{ overflowWrap: "anywhere" }}>
                {t}
              </span>
            ))}
          </p>
          <HeldNote session={session} />
        </div>
        <button ref={closeRef} className="btn x" type="button" onClick={() => onOpenChange(false)} aria-label={hideLabel} title={hideLabel}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      {bv ? <BusyNotice view={bv} onRetry={retry} className="prog-busy" /> : null}
      <ol className="steps">
        {m.steps.map((s) => (
          <li key={s.t} className={`st ${s.state}`}>
            <span className="m" aria-hidden="true">
              {s.state === "done" ? "✓" : s.state === "bad" ? "✕" : ""}
            </span>
            <span>
              <b>{s.t}</b>
              <span>
                <span className="sr">{s.state === "done" ? "Done: " : s.state === "now" ? "In progress: " : s.state === "bad" ? "Failed: " : s.state === "skip" ? "Skipped: " : "Waiting: "}</span>
                {inText(s.d, unit)}
              </span>
            </span>
          </li>
        ))}
      </ol>
      <MaterialAsk session={session} />
      <div className="ft">
        <span>{m.foot}</span>
        {action}
      </div>
    </section>
  );
}
