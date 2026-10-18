"use client";

import { WbHead } from "./chrome";
import type { TabProps } from "./workbench";

export function GlassTab({ part }: TabProps) {
  return <WbHead tab="glass" part={part} meta={["Coming next"]} />;
}
