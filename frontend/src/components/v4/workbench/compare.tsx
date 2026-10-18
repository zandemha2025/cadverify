"use client";

import { WbHead } from "./chrome";
import type { TabProps } from "./workbench";

export function CompareTab({ part }: TabProps) {
  return <WbHead tab="compare" part={part} meta={["Coming next"]} />;
}
