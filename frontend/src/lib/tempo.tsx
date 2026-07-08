"use client";

/**
 * TempoProvider / useTempo — the runtime wiring around `tempo-core`.
 *
 * Resolves the active register (showcase vs working) from the URL (`?tempo=`),
 * localStorage (`cv_seen`), and `prefers-reduced-motion`, then exposes a `dur()`
 * helper that motion primitives call to scale every base (showcase) duration.
 *
 * SSR note: the first paint is always `showcase` with motion enabled (the
 * SSR-safe default — the server can't read localStorage or the media query).
 * The real register is resolved in an effect on mount, and `cv_seen` is stamped
 * so the NEXT session defaults to `working`. Because FE-1 ships no consumer of
 * `dur()` in the rendered tree yet, this reconciliation is visually inert — it
 * exists so FE-2 can choreograph the reveal on the real compute path.
 */

import * as React from "react";
import {
  type Tempo,
  TEMPO_SEEN_KEY,
  resolveInitialTempo,
  scaledDuration,
} from "@/lib/tempo-core";

export interface TempoContextValue {
  /** the active register */
  tempo: Tempo;
  /** true when the OS asks for reduced motion (every `dur()` is then 0) */
  reducedMotion: boolean;
  /** scale a base (showcase) duration in ms for the active register */
  dur: (ms: number) => number;
}

const FALLBACK: TempoContextValue = {
  tempo: "working",
  reducedMotion: false,
  dur: (ms) => ms,
};

const TempoContext = React.createContext<TempoContextValue | null>(null);

export function TempoProvider({ children }: { children: React.ReactNode }) {
  // SSR-safe deterministic first paint; the effect below resolves the real one.
  const [tempo, setTempo] = React.useState<Tempo>("showcase");
  const [reducedMotion, setReducedMotion] = React.useState(false);

  React.useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const onMotion = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", onMotion);

    let override: string | null = null;
    try {
      override = new URLSearchParams(window.location.search).get("tempo");
    } catch {
      override = null;
    }
    let hasSeen = false;
    try {
      hasSeen = window.localStorage.getItem(TEMPO_SEEN_KEY) === "1";
    } catch {
      hasSeen = false;
    }
    setTempo(resolveInitialTempo({ override, hasSeen }));

    // Mark seen so the next session lands in the working default.
    try {
      window.localStorage.setItem(TEMPO_SEEN_KEY, "1");
    } catch {
      /* private mode / disabled storage: stay in showcase, harmless */
    }

    return () => mq.removeEventListener("change", onMotion);
  }, []);

  const dur = React.useCallback(
    (ms: number) => scaledDuration(ms, { tempo, reducedMotion }),
    [tempo, reducedMotion]
  );

  const value = React.useMemo<TempoContextValue>(
    () => ({ tempo, reducedMotion, dur }),
    [tempo, reducedMotion, dur]
  );

  return <TempoContext.Provider value={value}>{children}</TempoContext.Provider>;
}

/**
 * Read the active tempo. Outside a provider it degrades to a `working`, no-scale
 * value so a component never crashes when rendered on a flag-off / unwrapped tree.
 */
export function useTempo(): TempoContextValue {
  return React.useContext(TempoContext) ?? FALLBACK;
}
