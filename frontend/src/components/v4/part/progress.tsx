"use client";

/** X10: the check's progress, stage by stage, from the real responses as they land. */
import * as React from "react";
import { dimsText, plural, progressSteps, type Step } from "./model";
import { chosenLine } from "./pick-words";
import { readsAsBodies, type CheckSession } from "./store";
import { HeldNote, MaterialAsk } from "../onboard/material-ask";
import { inText } from "../units/units";
import { useUnits } from "../units/use-units";

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

export function progressModel(s: CheckSession) {
  const r = s.result;
  const steps: Step[] = onePick(s, bodySteps(s, progressSteps({
    fileName: s.file.name,
    sample: s.sample,
    validation: s.validation ?? r?.validation ?? null,
    cost: r?.cost ?? null,
    costError: r ? r.costError : null,
    geometryInvalid: s.status === "stopped" ? r?.costGeometryInvalid?.message ?? "not a closed solid" : null,
    done: s.status !== "running",
  })));
  const running = s.status === "running";
  const stopped = s.status === "stopped";
  const elapsed = (s.finishedAt ?? Date.now()) - s.startedAt;
  const title = running ? (s.sample ? "Checking the sample" : "Checking") : stopped ? "Stopped at Measured" : "Checked";
  const meta = running ? [s.file.name, s.sample ? "No check used" : "About 30 s"] : stopped ? [s.file.name, "Not watertight"] : [s.file.name, seconds(elapsed)];
  const foot = running ? "Hiding this doesn’t stop the check." : stopped ? "Nothing after this step ran." : "Same file, same result, every time.";
  return { steps, running, stopped, title, meta, foot };
}

export function ProgressPanel({
  session,
  open,
  onOpenChange,
  action,
}: {
  session: CheckSession;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** "See what's wrong" (stopped) or "Open result" (done). */
  action?: React.ReactNode;
}) {
  const m = progressModel(session);
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
        {m.running ? "Checking · Show progress" : "Show progress"}
      </button>
    );
  return (
    <section className="prog" role="status" aria-live="polite" aria-labelledby="pg-title">
      <div className="hd">
        <div style={{ minWidth: 0 }}>
          <h1 className="stitle" id="pg-title">
            {m.title}
          </h1>
          <p className="pmeta" style={{ marginTop: 4 }}>
            {m.meta.map((t, i) => (
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
