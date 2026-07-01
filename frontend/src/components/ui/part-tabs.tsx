"use client";

import { ScanLine, Calculator, Ruler, Share2 } from "lucide-react";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";

export type PartTab = "analyze" | "cost" | "tolerances" | "share";

const TABS: { value: PartTab; label: string; icon: typeof ScanLine }[] = [
  { value: "analyze", label: "Analyze", icon: ScanLine },
  { value: "cost", label: "Cost / Decide", icon: Calculator },
  { value: "tolerances", label: "Tolerances", icon: Ruler },
  { value: "share", label: "Share", icon: Share2 },
];

/**
 * The part-as-object tab strip (Analyze · Cost · Tolerances · Share). Render
 * inside a <Tabs> root; the workspace (Screen Builder A) owns the state and
 * <TabsContent> panels so a single upload serves every tab.
 */
export function PartTabs() {
  return (
    <TabsList className="w-full justify-start">
      {TABS.map(({ value, label, icon: Icon }) => (
        <TabsTrigger key={value} value={value}>
          <Icon className="size-4" />
          {label}
        </TabsTrigger>
      ))}
    </TabsList>
  );
}
