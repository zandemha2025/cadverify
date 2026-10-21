"use client";

/**
 * N2: three short tips on the first result, each pointing at the part page's
 * real control: the part (drag or arrow keys to turn it), the lit problem pin,
 * and the dial. Shown once per person (remembered in this browser), skippable
 * at any point (Skip tips, Esc), and never on a later visit. Turning the part
 * finishes the first tip, like the board.
 */
import * as React from "react";
import { usePart } from "../part/ctx";
import { findingName } from "../home/words";
import { cx } from "../ui";
import { nextTip, tipNumber, type TipStep } from "./first-run";
import "./onboard.css";

const KIND_WORD: Record<string, string> = { thin: "Red", support: "Blue", reach: "Amber", draft: "Violet" };

type Box = { x: number; y: number; w: number; h: number };

function rel(el: Element | null, host: Element | null): Box | null {
  if (!el || !host) return null;
  const a = el.getBoundingClientRect();
  const b = host.getBoundingClientRect();
  if (!a.width && !a.height) return null;
  return { x: a.left - b.left, y: a.top - b.top, w: a.width, h: a.height };
}

/** The lit problem's pin: the one on view, else one turned away or inside the part (its place still points at the lit faces). */
function visiblePin(host: Element | null): Element | null {
  if (!host) return null;
  const pins = [...host.querySelectorAll(".v4-pin")];
  return pins.find((p) => !p.classList.contains("hid")) ?? pins[0] ?? null;
}

/** Where each anchor is, re-read every frame while a tip shows (the pin moves as the part turns). */
function useAnchors(step: TipStep, hostRef: React.RefObject<HTMLElement | null>) {
  const [a, setA] = React.useState<{ obj: Box | null; pin: Box | null; dial: Box | null; host: Box | null }>({ obj: null, pin: null, dial: null, host: null });
  React.useEffect(() => {
    if (step === "done") return;
    let raf = 0;
    let last = "";
    const tick = () => {
      const host = hostRef.current?.closest(".world") ?? null;
      const next = {
        obj: rel(host?.querySelector(".obj") ?? null, host),
        pin: rel(visiblePin(host), host),
        dial: rel(host?.querySelector("nav.dial") ?? null, host),
        host: host ? { x: 0, y: 0, w: host.clientWidth, h: host.clientHeight } : null,
      };
      const k = JSON.stringify(next, (_k, v) => (typeof v === "number" ? Math.round(v) : v));
      if (k !== last) {
        last = k;
        setA(next);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [step, hostRef]);
  return a;
}

export function Tips({
  plan,
  step,
  onStep,
  onDone,
  teamMachines,
}: {
  /** the tips this part shows, fixed when they started */
  plan: TipStep[];
  step: TipStep;
  onStep: (s: TipStep) => void;
  onDone: () => void;
  /** names of the organization's machines when a teammate set them up (N6), else null */
  teamMachines: string[] | null;
}) {
  const p = usePart();
  const hostRef = React.useRef<HTMLDivElement>(null);
  const tipRef = React.useRef<HTMLElement>(null);
  const [tipH, setTipH] = React.useState(150);
  const a = useAnchors(step, hostRef);
  React.useLayoutEffect(() => {
    const h = tipRef.current?.offsetHeight;
    if (h && Math.abs(h - tipH) > 2) setTipH(h);
  }, [step, a, tipH]);
  const sel = p.sel;
  const finding = p.lens === "make" ? sel?.finding ?? null : null;
  const num = tipNumber(plan, step);
  const phone = typeof window !== "undefined" && window.matchMedia("(max-width:900px)").matches;

  // Turning the part finishes the first tip.
  React.useEffect(() => {
    if (step !== "tip1") return;
    let start: number | null = null;
    const down = (e: PointerEvent) => {
      if ((e.target as Element | null)?.closest?.(".obj")) start = e.clientX;
    };
    const move = (e: PointerEvent) => {
      if (start != null && Math.abs(e.clientX - start) > 30) {
        start = null;
        onStep(nextTip(plan, "tip1"));
      }
    };
    const up = () => (start = null);
    const key = (e: KeyboardEvent) => {
      if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && (e.target as Element | null)?.closest?.(".obj")) onStep(nextTip(plan, "tip1"));
    };
    document.addEventListener("pointerdown", down, true);
    document.addEventListener("pointermove", move, true);
    document.addEventListener("pointerup", up, true);
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("pointerdown", down, true);
      document.removeEventListener("pointermove", move, true);
      document.removeEventListener("pointerup", up, true);
      document.removeEventListener("keydown", key, true);
    };
  }, [step, onStep, plan]);

  // Esc skips the tips (when no dialog is open).
  React.useEffect(() => {
    if (step === "done") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector(".ob [aria-modal='true']")) return;
      onDone();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, onDone]);

  if (step === "done") return <div ref={hostRef} hidden />;

  const faces = p.data.validation?.geometry.faces ?? p.data.cost?.geometry.face_count ?? null;
  const next = () => onStep(nextTip(plan, step));
  const W = 304;
  const clampX = (x: number) => (a.host ? Math.max(12, Math.min(x, a.host.w - W - 12)) : x);

  let body: { id: string; title: string; text: React.ReactNode; live: string } ;
  let pos: React.CSSProperties = {};
  let dir = "";
  let ring: React.CSSProperties | null = null;
  if (step === "tip1") {
    body = {
      id: "nb-tip1",
      title: "Drag to turn it",
      text: (
        <>
          Or select the part and use <kbd>←</kbd> <kbd>→</kbd>.{faces ? ` It’s drawn from your file’s real shell, ${faces.toLocaleString("en-US")} faces.` : " It’s drawn from your file."}
        </>
      ),
      live: `Tip ${num.n} of ${num.of}: drag to turn it.`,
    };
    if (a.obj) {
      // Under the part, but never over the dial.
      const below = a.obj.y + a.obj.h + 10;
      const room = a.dial ? a.dial.y - tipH - 16 : below;
      pos = { left: clampX(a.obj.x + a.obj.w / 2 - W / 2), top: Math.min(below, room) };
      dir = "up";
    }
  } else if (step === "tip2") {
    const kind = finding?.kind ?? null;
    const n = finding?.issue.affected_face_count ?? finding?.faces.length ?? null;
    const what = finding ? findingName(finding.issue.code, finding.issue.message).toLowerCase() : "a problem";
    body = {
      id: "nb-tip2",
      title: "Problems are lit on the part",
      text: `${kind ? `${KIND_WORD[kind]} marks ` : ""}${what}${n ? ` on ${n.toLocaleString("en-US")} faces` : ""}${sel ? `, for ${sel.name.toLowerCase()}` : ""}. Pick another way on the right to light its problems.`,
      live: `Tip ${num.n} of ${num.of}: problems are lit on the part.`,
    };
    // At the pin; without one on screen, at the part itself (its faces are lit).
    const at = a.pin ?? (a.obj ? { x: a.obj.x + a.obj.w / 2 - 13, y: a.obj.y + a.obj.h / 2 - 13, w: 26, h: 26 } : null);
    if (at) {
      const cx0 = at.x + at.w / 2;
      const cy0 = at.y + at.h / 2;
      if (a.pin) ring = { left: cx0 - 22, top: cy0 - 22, width: 44, height: 44 };
      pos = { left: clampX(cx0 + 34), top: cy0 - 44 };
      dir = "left";
    }
  } else {
    const team = teamMachines && teamMachines.length ? teamMachines : null;
    body = team
      ? {
          id: "nb-tip3",
          title: "In-house is your team’s machines",
          text: `${listWords(team)}, set up by your team. You and your team see the same answers.`,
          live: `Tip ${num.n} of ${num.of}: In-house is your team’s machines.`,
        }
      : {
          id: "nb-tip3",
          title: "Five views of the same part",
          text: `Process: can it be made, and how (DFM). Cost: price by quantity. Conditions: where it’s used. In-house: your machines. Decision: make or buy.${p.data.machines.length ? "" : " In-house is empty until you add machines."}`,
          live: `Tip ${num.n} of ${num.of}: five views of the same part.`,
        };
    if (a.dial && a.host) {
      ring = team
        ? { left: a.dial.x + (a.dial.w / 5) * 3 - 2, top: a.dial.y - 2, width: a.dial.w / 5 + 4, height: a.dial.h + 4 }
        : { left: a.dial.x - 4, top: a.dial.y - 4, width: a.dial.w + 8, height: a.dial.h + 8 };
      const centre = team ? a.dial.x + (a.dial.w / 5) * 3.5 : a.dial.x + a.dial.w / 2;
      pos = { left: clampX(centre - W / 2), bottom: a.host.h - a.dial.y + 14 };
      dir = "down";
    }
  }

  const last = nextTip(plan, step) === "done";
  return (
    <div ref={hostRef} className="nb-tips">
      {ring && !phone ? <span className="nb-ring" aria-hidden="true" style={ring} /> : null}
      <aside ref={tipRef} key={step} className={cx("nb-tip", !phone && dir)} role="note" aria-labelledby={`${body.id}-t`} style={phone ? undefined : pos}>
        <span className="n">
          <span>
            Tip {num.n} of {num.of}
          </span>
          <span className="dots" aria-hidden="true">
            {Array.from({ length: num.of }, (_, i) => (
              <i key={i} className={cx(i === num.n - 1 && "on")} />
            ))}
          </span>
        </span>
        <b id={`${body.id}-t`}>{body.title}</b>
        <p>{body.text}</p>
        <span className="acts">
          {last ? (
            <button className="btn w" type="button" onClick={onDone}>
              Done
            </button>
          ) : (
            <>
              <button className="btn w" type="button" onClick={next}>
                Next
              </button>
              <button className="btn q" type="button" onClick={onDone}>
                Skip tips
              </button>
            </>
          )}
        </span>
      </aside>
      <p className="nb-sr" aria-live="polite">
        {body.live}
      </p>
    </div>
  );
}

function listWords(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  if (names.length > 4) return `${names.slice(0, 3).join(", ")} and ${names.length - 3} more`;
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
