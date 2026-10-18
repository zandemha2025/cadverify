"use client";

/** Shared state for one open part: its data, the computed methods, the lens, quantity and pick. */
import * as React from "react";
import type { CostDecisionDetail, CostReport, ValidationResult } from "@/lib/api";
import type { OwnedMachine } from "@/lib/verify/machine-api";
import type { PartContext } from "@/lib/verify/part-context-read";
import type { IdentityResult } from "@/lib/verify/identity";
import type { ServiceEnvironment } from "@/lib/verify/part-context";
import { buildMethods, cheapestAt, defaultQty, groupUnpriced, quantitiesOf, type Method } from "./model";
import type { CheckSession } from "./store";

export type Lens = "make" | "cost" | "use" | "shop" | "decide";
export const LENSES: [Lens, string, string][] = [
  ["make", "Make", "how"],
  ["cost", "Cost", "how many"],
  ["use", "Use", "where"],
  ["shop", "Shop", "your machines"],
  ["decide", "Decide", "what next"],
];

export interface PartData {
  key: string | null;
  fileName: string;
  fileType: string;
  source: "live" | "saved";
  validation: ValidationResult | null;
  cost: CostReport | null;
  costError: string | null;
  machines: OwnedMachine[];
  context: PartContext | null;
  /** The conditions the shown prices were computed under. */
  runEnvironment: ServiceEnvironment | null;
  decisionId: string | null;
  decision: CostDecisionDetail | null;
  decisionError: string | null;
  identity: IdentityResult | null;
  checks: number | null;
  createdAt: string | null;
}

export interface Toast {
  text: string;
  link?: { label: string; href: string };
}

export interface PartCtxValue {
  data: PartData;
  session: CheckSession | null;
  methods: Method[];
  rows: Method[];
  qs: number[];
  q: number;
  setQ: (q: number) => void;
  oq: string;
  setOq: (v: string) => void;
  lens: Lens;
  setLens: (l: Lens) => void;
  sel: Method | null;
  setSel: (code: string) => void;
  costPick: string | null;
  setCostPick: (code: string | null) => void;
  machinePick: string | null;
  setMachinePick: (id: string) => void;
  decidePick: string | null;
  setDecidePick: (id: string | null) => void;
  checking: boolean;
  interrupted: boolean;
  costOff: boolean;
  has3d: boolean;
  toast: (t: Toast) => void;
  turnTo: () => void;
  canTurn: boolean;
  patchData: (p: Partial<PartData>) => void;
  /** Run the check again: from the file in memory, or ask for it. */
  recheck: (opts?: { materialClass?: string }) => void;
  canRecheck: boolean;
  retryPrices: () => void;
  pickFile: () => void;
}

const Ctx = React.createContext<PartCtxValue | null>(null);

export function usePart(): PartCtxValue {
  const v = React.useContext(Ctx);
  if (!v) throw new Error("usePart outside PartProvider");
  return v;
}

export const PartProvider = Ctx.Provider;

export function useMethods(data: PartData) {
  return React.useMemo(() => {
    const methods = buildMethods({ validation: data.validation, cost: data.cost, machines: data.machines });
    const rows = groupUnpriced(methods);
    const qs = quantitiesOf(data.cost);
    return { methods, rows, qs };
  }, [data.validation, data.cost, data.machines]);
}

export function initialPick(methods: Method[], q: number): string | null {
  const c = cheapestAt(methods, q);
  if (c) return c.code;
  const gp = methods.find((m) => m.geometryPick);
  return gp?.code ?? methods[0]?.code ?? null;
}

export { defaultQty };
