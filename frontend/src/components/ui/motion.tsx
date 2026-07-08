"use client";

/**
 * Motion primitives — the shared enter choreography, tempo-aware.
 *
 * Every duration passed here is a BASE (showcase) value in ms; `useTempo().dur`
 * scales it (×0.1 in working, 0 under reduced motion), so a single call site
 * behaves correctly in demo, returning-user, and accessibility modes.
 *
 * `<Rise>` — a quiet opacity + upward-translate entrance on the "strike" spring
 * from the D5 register. `<Stagger>` wraps a list so each child rises a beat after
 * the last (`step` base-ms apart); `staggerDelay(i)` is the same math for callers
 * that need the delay without the wrapper.
 */

import * as React from "react";
import { useTempo } from "@/lib/tempo";

/** the D5 "strike" spring — settles hard, never bounces */
export const STRIKE = "cubic-bezier(0.16, 1, 0.3, 1)";

export interface RiseProps extends React.HTMLAttributes<HTMLDivElement> {
  /** base (showcase) duration in ms */
  ms?: number;
  /** base (showcase) delay in ms before the rise begins */
  delay?: number;
  /** translate distance in px the element rises from */
  distance?: number;
}

export function Rise({
  ms = 340,
  delay = 0,
  distance = 6,
  style,
  children,
  ...rest
}: RiseProps) {
  const { dur } = useTempo();
  const [shown, setShown] = React.useState(false);

  React.useEffect(() => {
    const raf = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const d = dur(ms);
  const dl = dur(delay);

  return (
    <div
      style={{
        opacity: shown ? 1 : 0,
        transform: shown ? "translateY(0)" : `translateY(${distance}px)`,
        transition: `opacity ${d}ms ${STRIKE} ${dl}ms, transform ${d}ms ${STRIKE} ${dl}ms`,
        willChange: "opacity, transform",
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

/** the base (showcase) delay for the i-th item in a staggered list */
export function staggerDelay(index: number, step = 60): number {
  return Math.max(0, index) * step;
}

export interface StaggerProps {
  /** base (showcase) ms between each child's rise */
  step?: number;
  /** base (showcase) duration of each child's rise */
  ms?: number;
  distance?: number;
  children: React.ReactNode;
}

/**
 * Stagger — rise each direct child a beat after the previous. Each child is
 * wrapped in a `<Rise>`, so use it for lists/grids where an extra block wrapper
 * per row is acceptable.
 */
export function Stagger({ step = 60, ms = 340, distance = 6, children }: StaggerProps) {
  const items = React.Children.toArray(children);
  return (
    <>
      {items.map((child, i) => (
        <Rise key={i} ms={ms} delay={staggerDelay(i, step)} distance={distance}>
          {child}
        </Rise>
      ))}
    </>
  );
}
