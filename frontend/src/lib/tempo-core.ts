/**
 * Tempo — pure logic (no React, no DOM) so it can be unit-tested with
 * `node --test`. The provider in `lib/tempo.tsx` wires these to localStorage,
 * the URL, and the reduced-motion media query.
 *
 * Two registers (D5 "TEMPO system"):
 *   - `showcase` — full choreography (first session, demo mode, ?tempo=showcase)
 *   - `working`  — durations ×0.1, no compute theater (the returning default)
 * `prefers-reduced-motion` collapses everything to 0ms.
 */

export type Tempo = "showcase" | "working";

/** localStorage key: presence means the visitor has seen the choreography once. */
export const TEMPO_SEEN_KEY = "cv_seen";

/** working durations are one-tenth of showcase (the "no compute theater" scale). */
export const WORKING_SCALE = 0.1;

/** Parse a `?tempo=` override; anything not a known register is ignored (null). */
export function parseTempoOverride(value: string | null | undefined): Tempo | null {
  if (value === "showcase" || value === "working") return value;
  return null;
}

/**
 * Resolve the tempo for a session. Precedence: an explicit `?tempo=` override
 * wins; otherwise a returning visitor (has seen it) defaults to `working` and a
 * first-time visitor gets the full `showcase`.
 */
export function resolveInitialTempo(opts: {
  override?: string | null;
  hasSeen: boolean;
}): Tempo {
  const override = parseTempoOverride(opts.override);
  if (override) return override;
  return opts.hasSeen ? "working" : "showcase";
}

/**
 * Scale a base (showcase) duration for the active register. Reduced motion always
 * collapses to 0. Negative inputs clamp to 0 so callers can pass raw deltas.
 */
export function scaledDuration(
  ms: number,
  opts: { tempo: Tempo; reducedMotion: boolean }
): number {
  if (opts.reducedMotion) return 0;
  const base = ms > 0 ? ms : 0;
  return opts.tempo === "working" ? base * WORKING_SCALE : base;
}
