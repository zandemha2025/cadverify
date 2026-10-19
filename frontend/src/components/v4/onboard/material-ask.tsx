"use client";

/**
 * N1: "What will it be made of?", asked in the check's progress panel while the
 * geometry check runs. The shape checks don't depend on the material, the
 * prices do: the answer is the material the first price uses, and a later
 * change re-prices the same file under the same check (setCheckMaterial: no
 * new check, the server reuses the geometry it analysed). Skipping prices in
 * plastic, and the panel says so.
 */
import * as React from "react";
import { setCheckMaterial, type CheckSession } from "../part/store";
import { cx } from "../ui";
import { MATERIALS, askCopy } from "./first-run";
import { isHeld } from "./state";
import "./onboard.css";

/** The answer per check, kept across the hand-over from the check page to the part page. */
const answers = new Map<number, string>();

export function MaterialAsk({ session }: { session: CheckSession }) {
  const groupRef = React.useRef<HTMLSpanElement>(null);
  // Picked by the person here (the session starts in plastic, the default, unasked).
  const [picked, setPicked] = React.useState<string | null>(() => answers.get(session.id) ?? null);
  if (!session.askMaterial || session.sample) return null;
  if (session.status !== "running" && session.status !== "done") return null;
  const current = picked ?? null;
  const done = session.status === "done";
  const copy = askCopy(current, session.pricedWith, done);
  const state = current && session.costRetrying ? `Re-pricing in ${MATERIALS.find(([k]) => k === current)?.[1].toLowerCase()}` : copy.state;
  const focusIdx = current ? Math.max(0, MATERIALS.findIndex(([k]) => k === current)) : 0;

  const pick = (k: string) => {
    answers.set(session.id, k);
    setPicked(k);
    setCheckMaterial(session.id, k);
  };
  const onKey = (i: number) => (e: React.KeyboardEvent) => {
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const j = (i + d + MATERIALS.length) % MATERIALS.length;
    pick(MATERIALS[j][0]);
    groupRef.current?.querySelectorAll<HTMLButtonElement>("[role=radio]")[j]?.focus();
  };

  return (
    <div className={cx("nb-ask", current && "set")} role="group" aria-labelledby={`mat-q-${session.id}`}>
      <div className="q">
        <b id={`mat-q-${session.id}`}>What will it be made of?</b>
        <span aria-live="polite">{state}</span>
      </div>
      <span className="seg" role="radiogroup" aria-label="Material class" ref={groupRef}>
        {MATERIALS.map(([k, label], i) => (
          <button key={k} type="button" role="radio" className={cx(current === k && "on")} aria-checked={current === k} tabIndex={i === focusIdx ? 0 : -1} onClick={() => pick(k)} onKeyDown={onKey(i)}>
            {label}
          </button>
        ))}
      </span>
      <p>{copy.note}</p>
    </div>
  );
}

/** "Held from sign-up": the part dropped before signing in, checking now. */
export function HeldNote({ session }: { session: CheckSession }) {
  if (!isHeld(session.file)) return null;
  return (
    <span className="nb-held">
      <i aria-hidden="true" />
      Held from sign-up
    </span>
  );
}
