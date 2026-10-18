"use client";

import { WbHead } from "./chrome";
import type { TabProps } from "./workbench";

export function HistoryTab({ part }: TabProps) {
  return <WbHead tab="history" part={part} meta={["Coming next"]} />;
}
