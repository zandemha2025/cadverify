"use client";

/**
 * The one busy state (capacity D1–D3): "ScaleCAD is busy. Checking again in 8 s…"
 * counting down while the check asks again by itself, then "Still busy. Your file is
 * kept; try again in a minute." with a button. A request that stopped on ScaleCAD's
 * side reads the same way: "That took too long on our side. Your file is kept." with
 * Try again. A calm notice (the X11 info banner), never a red alert, and nothing in
 * it is about the file.
 */
import * as React from "react";
import { Banner } from "../moments";
import { STILL_BUSY_TITLE, busyMeta, busyTitle, serverMeta, serverTitle, stillBusyMeta, type BusyView } from "./busy-state";

/** The clock, once a second while `on` (the countdown). */
export function useNow(on: boolean): number {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const iv = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(iv);
  }, [on]);
  return now;
}

export function BusyNotice({ view, onRetry, className, style }: { view: BusyView; onRetry?: () => void; className?: string; style?: React.CSSProperties }) {
  const now = useNow(view.phase === "waiting");
  if (view.phase === "waiting") {
    const line = busyTitle(view, now);
    // The seconds move every second; a screen reader hears the sentence once, not each tick.
    const [lead, count] = line.split(/(?= (?:in \d+ s|now)…$)/);
    return (
      <Banner
        tone="info"
        spin
        name="busy"
        className={className}
        style={style}
        title={
          <>
            {lead}
            <span className="busy-count" aria-hidden="true">
              {count}
            </span>
            <span className="sr"> shortly.</span>
          </>
        }
        meta={busyMeta(view)}
      />
    );
  }
  const still = view.phase === "still";
  return (
    <Banner
      tone="info"
      name={still ? "busy" : "server"}
      className={className}
      style={style}
      title={still ? STILL_BUSY_TITLE : serverTitle(view.status)}
      meta={still ? stillBusyMeta(view.still) : serverMeta(view.step, view.status)}
      actions={
        onRetry ? (
          <button className="btn ink sm" type="button" onClick={onRetry}>
            Try again
          </button>
        ) : null
      }
    />
  );
}
