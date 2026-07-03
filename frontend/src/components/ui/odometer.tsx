"use client";

/**
 * Odometer — a tempo-aware count-up for the hero unit cost. On the decision
 * reveal (and on every slider re-flip) the number rolls from its previous value
 * to the new one over a base (showcase) duration that `useTempo().dur` scales:
 * ×0.1 in the working register, 0 under reduced motion (an instant snap). It
 * eases out (never bounces) to match the D5 "strike" register.
 *
 * Honesty: the animated glyphs are `aria-hidden`; the wrapper carries the real,
 * fully-formatted value as its accessible label, so assistive tech never reads a
 * mid-roll figure. The number shown at rest is exactly the engine's number —
 * the roll is presentation, not a different value.
 */

import * as React from "react";
import { useTempo } from "@/lib/tempo";
import { cn } from "@/lib/utils";

export function Odometer({
  value,
  format,
  ms = 900,
  className,
}: {
  /** the target value (the real engine number) */
  value: number;
  /** how to render the (interpolated) number */
  format: (n: number) => string;
  /** base (showcase) roll duration in ms */
  ms?: number;
  className?: string;
}) {
  const { dur } = useTempo();
  // start below the answer so the first reveal reads as a roll-up to the number.
  const [display, setDisplay] = React.useState(0);
  const currentRef = React.useRef(0);

  React.useEffect(() => {
    const to = Number.isFinite(value) ? value : 0;
    const from = currentRef.current;
    const d = dur(ms);
    if (d <= 0 || from === to) {
      currentRef.current = to;
      setDisplay(to);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / d);
      const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
      const v = from + (to - from) * eased;
      currentRef.current = v;
      setDisplay(v);
      if (t < 1) raf = requestAnimationFrame(step);
      else {
        currentRef.current = to;
        setDisplay(to);
      }
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, dur, ms]);

  const rest = format(Number.isFinite(value) ? value : 0);
  return (
    <span className={cn(className)} aria-label={rest}>
      <span aria-hidden>{format(display)}</span>
    </span>
  );
}
