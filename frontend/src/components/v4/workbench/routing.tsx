"use client";

import { WbHead } from "./chrome";
import type { TabProps } from "./workbench";

export function RoutingTab({ part }: TabProps) {
  return <WbHead tab="routing" part={part} meta={["Coming next"]} />;
}
