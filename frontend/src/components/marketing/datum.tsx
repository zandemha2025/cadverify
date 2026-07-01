"use client";

/**
 * The DATUM RAIL — the restrained metrology motif (identity signature 3). These
 * are the quiet, recurring engineering marks the marketing site is built on: a
 * witness-tick eyebrow, a CAD dimension-line callout, and the hero-number
 * "settle" hook. Used with discipline (a whisper, not a costume blueprint skin).
 */

import * as React from "react";
import { cn } from "@/lib/utils";

/** Witness-tick eyebrow — a section label prefixed by the 2px Datum dimension
 *  tick. (The `.cv-eyebrow` ::before draws the tick; this adds an optional index
 *  readout in mono so the rail reads like a drawing callout.) */
export function Eyebrow({
  children,
  index,
  className,
}: {
  children: React.ReactNode;
  index?: string;
  className?: string;
}) {
  return (
    <span className={cn("cv-eyebrow", className)}>
      {index && <span className="num not-italic opacity-60">{index}</span>}
      {children}
    </span>
  );
}

/**
 * A real CAD dimension-line callout: two extension ticks, a span line with
 * arrowheads, and a value label centered on it. Used ONCE per page (under the
 * hero number) — the engineering provenance of the answer, drawn, not asserted.
 */
export function DimensionLine({
  label,
  tone = "datum",
  className,
}: {
  label: React.ReactNode;
  tone?: "datum" | "muted";
  className?: string;
}) {
  const stroke =
    tone === "datum" ? "var(--cv-primary)" : "var(--cv-muted-foreground)";
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <svg
        viewBox="0 0 120 12"
        preserveAspectRatio="none"
        className="h-3 flex-1"
        aria-hidden
      >
        {/* left + right extension ticks */}
        <line x1="1" y1="1" x2="1" y2="11" stroke={stroke} strokeWidth="1.5" />
        <line x1="119" y1="1" x2="119" y2="11" stroke={stroke} strokeWidth="1.5" />
        {/* span line */}
        <line x1="1" y1="6" x2="119" y2="6" stroke={stroke} strokeWidth="1.5" />
        {/* arrowheads */}
        <path d="M1 6 L7 3 L7 9 Z" fill={stroke} />
        <path d="M119 6 L113 3 L113 9 Z" fill={stroke} />
      </svg>
      <span className="num shrink-0 text-micro uppercase tracking-[0.14em] text-[color:var(--cv-primary)]">
        {label}
      </span>
    </div>
  );
}

/** The provenance dot, drawn for the dark hero / faceplate context (fill =
 *  grounded, hollow ring = a guess) with a mono label. */
export function ProvDot({
  tone,
  label,
  onDark = false,
}: {
  tone: "measured" | "shop" | "user" | "default";
  label: string;
  onDark?: boolean;
}) {
  const color =
    tone === "measured"
      ? onDark
        ? "#3fa3e8"
        : "var(--cv-prov-measured)"
      : tone === "shop"
        ? onDark
          ? "#d08b4c"
          : "var(--cv-prov-shop)"
        : tone === "user"
          ? "var(--cv-prov-user)"
          : onDark
            ? "#8aa0bf"
            : "var(--cv-prov-default)";
  const filled = tone !== "default";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden
        className="inline-block size-2 rounded-full"
        style={
          filled
            ? { background: color }
            : { border: `2px solid ${color}`, background: "transparent" }
        }
      />
      <span
        className="num text-micro tracking-wide"
        style={{ color: onDark ? "#9fb6d6" : "var(--cv-muted-foreground)" }}
      >
        {label}
      </span>
    </span>
  );
}

/**
 * The single earned "settle": a tabular roll to the final value, then lock —
 * like a caliper coming to rest. One time, hero only. Reduced motion → the
 * value appears final immediately.
 */
export function useCountUp(target: number, durationMs = 540): number {
  const [v, setV] = React.useState(target);
  React.useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setV(target);
      return;
    }
    let raf = 0;
    const start = performance.now();
    setV(0);
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      // decisive entry, calm settle (matches --ease-instrument)
      const eased = 1 - Math.pow(1 - t, 3);
      setV(target * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else setV(target);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);
  return v;
}
