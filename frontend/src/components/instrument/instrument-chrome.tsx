"use client";

/**
 * Instrument chrome context — how the FULL-BLEED instrument talks to the slim
 * top strip. The shell owns no knowledge of the loaded part; the Living
 * Instrument PUBLISHES the part's identity (name, measured facts, verdict, a
 * reset handle) here, and the top strip renders it. This is what makes the
 * chrome *contextual* instead of a persistent admin bar: empty when no part is
 * loaded, the part's identity when one is. Cleared automatically on unmount so
 * navigating away from the instrument wipes the strip.
 */

import * as React from "react";

export type PartFact = { label: string; value: string };

export type PartIdentity = {
  /** the dropped file name — the part's identity */
  name: string;
  /** measured geometry facts (vol / bbox / faces / watertight) */
  facts: PartFact[];
  /** engine verdict enum, rendered as a StatusBadge in the strip */
  verdict?: string | null;
  /** DFM pass still running */
  analyzing?: boolean;
  /** clear the instrument back to intake */
  onReset?: () => void;
};

type ChromeCtx = {
  part: PartIdentity | null;
  setPart: (p: PartIdentity | null) => void;
};

const InstrumentChromeContext = React.createContext<ChromeCtx>({
  part: null,
  setPart: () => {},
});

export function InstrumentChromeProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [part, setPart] = React.useState<PartIdentity | null>(null);
  const value = React.useMemo<ChromeCtx>(() => ({ part, setPart }), [part]);
  return (
    <InstrumentChromeContext.Provider value={value}>
      {children}
    </InstrumentChromeContext.Provider>
  );
}

export function useInstrumentChrome() {
  return React.useContext(InstrumentChromeContext);
}
