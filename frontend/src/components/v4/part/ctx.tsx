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
import type { EarlierChoice } from "./choice";

/** The five views of one part. Ids stay as they are in links (?lens=make); the names are what engineers call them. */
export type Lens = "make" | "cost" | "use" | "shop" | "decide";
export const LENSES: [Lens, string, string][] = [
  ["make", "Process", "can it be made"],
  ["cost", "Cost", "by quantity"],
  // "Specs" first (buyer-06): finish, inspection, certifications and tolerance were halfway down a
  // view called "Conditions, where it's used", under the sour gas and pressure fields.
  ["use", "Specs", "finish, tolerance, use"],
  ["shop", "In-house", "your machines"],
  ["decide", "Decision", "make or buy"],
];

/** A view's name, for copy that points at it ("See it in Process"). */
export function lensName(l: Lens): string {
  return LENSES.find(([k]) => k === l)?.[1] ?? l;
}

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
  /** A way to make it chosen on an earlier check of this part, offered to keep on this one. */
  earlierChoice?: EarlierChoice | null;
}

export interface Toast {
  text: string;
  link?: { label: string; href: string };
  /** Stays until dismissed (a share link's toast: the way to Share links). */
  sticky?: boolean;
}

export interface PartCtxValue {
  data: PartData;
  session: CheckSession | null;
  methods: Method[];
  rows: Method[];
  qs: number[];
  q: number;
  setQ: (q: number) => void;
  /** A quantity a link asked for (?qty=N) that isn't one the check priced; cleared once a quantity is picked. */
  askedQty: number | null;
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
  /** Price it again from the kept file: in another material, or at a quantity the user typed (computed, not interpolated). */
  recheck: (opts?: { materialClass?: string; qty?: number }) => void;
  canRecheck: boolean;
  retryPrices: () => void;
  pickFile: () => void;
  /** A file of several bodies: open it body by body (null for one body). */
  openBodies?: (() => void) | null;
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
