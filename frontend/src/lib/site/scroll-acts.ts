/**
 * Scroll-act measurement utility for the marketing site (dark-theater).
 *
 * A faithful port of the per-section measurement in
 * `handoff_cadverify_2026-07-04/site/Direction - Cinematic.dc.html` — the
 * cinematic pages measure each act's progress from the section's REAL layout
 * position every frame, so the choreography never desyncs from the DOM (no
 * hard-coded scroll offsets, no IntersectionObserver thresholds to drift).
 *
 * Pure math + a `measureSection` reader here; the WebGL loop lives in
 * `@/components/site/part-stage`. Page builders read acts for their DOM
 * (caption opacity, progress rail) via {@link useRafLoop} + {@link measureSection}.
 *
 * SHARED FOUNDATION — do not edit in a page branch.
 */

import { useEffect, useRef } from "react";

// ── scalar helpers (verbatim intent from the design's render loop) ──────────

/** Linear interpolate a→b by t. */
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/** Clamp to [0, 1]. */
export const clamp01 = (v: number): number => Math.max(0, Math.min(1, v));

/** Smoothstep easing (3t² − 2t³) on a 0..1 value. */
export const smooth = (v: number): number => v * v * (3 - 2 * v);

/** Remap t from the window [a, b] into 0..1, clamped. */
export const seg = (t: number, a: number, b: number): number => clamp01((t - a) / (b - a));

// ── per-section measurement ─────────────────────────────────────────────────

/**
 * Section-local progress, measured from the element's live bounding rect:
 *  - `ramp`: 0 → 1 as the section top travels from viewport-bottom to
 *    viewport-top, then stays 1 after (drives "has arrived" acts).
 *  - `pin`: 0 → 1 across the section's sticky range (`height − vh`); drives
 *    choreography that plays out while a tall section is pinned.
 *  - `vis`: caption visibility — smoothstepped, in while entering/pinned and
 *    out as the section leaves the viewport.
 */
export type ActMeasure = { ramp: number; pin: number; vis: number };

const ZERO: ActMeasure = { ramp: 0, pin: 0, vis: 0 };

/**
 * Measure one section against the current viewport. Call every frame (cheap:
 * one `getBoundingClientRect`). Returns zeros for a null element so callers can
 * pass refs that may not be mounted yet.
 */
export function measureSection(el: HTMLElement | null | undefined): ActMeasure {
  if (!el || typeof window === "undefined") return ZERO;
  const vh = window.innerHeight;
  const r = el.getBoundingClientRect();
  const ramp = clamp01((vh - r.top) / vh);
  const span = Math.max(1, r.height - vh);
  const pin = clamp01(-r.top / span);
  const enter = clamp01((vh - r.top) / (vh * 0.55));
  const exit = clamp01((r.bottom - vh) / (vh * 0.45));
  return { ramp, pin, vis: smooth(Math.min(enter, exit)) };
}

/** Whole-document scroll progress, 0 at top → 1 at the last pixel. */
export function documentScrollProgress(): number {
  if (typeof window === "undefined" || typeof document === "undefined") return 0;
  const max = document.documentElement.scrollHeight - window.innerHeight;
  return max > 0 ? clamp01(window.scrollY / max) : 0;
}

/**
 * Apply the design's caption reveal to a DOM node: fade + a small upward
 * settle tied to a 0..1 visibility value. Mirrors `setOp` in the source.
 */
export function applyCaptionReveal(el: HTMLElement | null | undefined, v: number): void {
  if (!el) return;
  el.style.opacity = v.toFixed(3);
  el.style.transform = `translateY(${((1 - v) * 28).toFixed(1)}px)`;
}

// ── React glue (client-only) ────────────────────────────────────────────────

/**
 * Drive a per-frame callback with a requestAnimationFrame loop plus a
 * scroll-smoothed global progress value. The callback receives:
 *  - `dt`: seconds since last frame (clamped for tab-restore safety)
 *  - `elapsed`: total seconds since mount
 *  - `scrollT`: eased whole-document scroll progress (lerped toward the raw
 *    target at `dt * 5`, exactly as the cinematic stage smooths it)
 *
 * The callback ref is kept live so a page can close over changing state without
 * restarting the loop. Honors `prefers-reduced-motion` by pinning `scrollT` to
 * the raw target (no easing) — the page still updates, it just doesn't glide.
 */
export function useRafLoop(
  onFrame: (f: { dt: number; elapsed: number; scrollT: number }) => void,
  opts: { enabled?: boolean } = {},
): void {
  const { enabled = true } = opts;
  const cb = useRef(onFrame);
  cb.current = onFrame;

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let raf = 0;
    let last = performance.now();
    const start = last;
    let scrollT = documentScrollProgress();
    let target = scrollT;

    const onScroll = () => {
      target = documentScrollProgress();
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });

    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      scrollT = reduce ? target : lerp(scrollT, target, Math.min(1, dt * 5));
      cb.current({ dt, elapsed: (now - start) / 1000, scrollT });
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [enabled]);
}

/**
 * Smoothly scroll the window to a section's top (used by progress-rail jumps).
 * `null`/index 0 scroll to the very top, matching the home rail's behavior.
 */
export function scrollToSection(el: HTMLElement | null | undefined): void {
  if (typeof window === "undefined") return;
  const top = el ? window.scrollY + el.getBoundingClientRect().top : 0;
  window.scrollTo({ top, behavior: "smooth" });
}
