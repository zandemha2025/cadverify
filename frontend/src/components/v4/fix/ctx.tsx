"use client";

/**
 * Find and fix on the part page: which problem is open (K1), the list of all of
 * them (K4), the ask-to-fix dialog (K2) and the before/after comparison (K3). The
 * part page calls `useFixController` once and provides the value; the sheets and
 * dialogs read it with `useFix()`. The open problem lives in the URL (?problem=,
 * ?method=, ?problems=all) so a link opens the same view.
 */
import * as React from "react";
import type { Method } from "../part/model";
import { KIND_COLOR } from "../part/model";
import type { PartData } from "../part/ctx";
import type { PinState, ViewerController, ViewerHighlight, ViewerMarker } from "../part/viewer";
import { buildProblems, callout, findProblem, pickMethod, type Problem, type ProblemMethod, type ProblemSet } from "./problems";
import { placesOf, rankProblems, unlockOf, type Unlock } from "./rank";
import type { FixOrigin } from "./capabilities";
import { useStudioOrigin } from "./origin";
import { serverFixesOf, useServerOptions } from "./server";
import { useFixRun } from "./runs";

export type FixView = { kind: "problem"; id: string; method: string | null } | { kind: "all"; sel: string | null; q: number | null; by: "rank" | "place" };
export type AskVariant = "repair" | "studio" | "upload" | "server";

export interface FixCtxValue {
  set: ProblemSet;
  origin: FixOrigin;
  view: FixView | null;
  /** The open problem and the method it's shown for (K1). */
  problem: Problem | null;
  method: ProblemMethod | null;
  openProblem: (id: string, method?: string | null) => void;
  openAll: (sel?: string | null) => void;
  close: () => void;
  setMethod: (code: string) => void;
  setAll: (p: Partial<Extract<FixView, { kind: "all" }>>) => void;
  /** K4's ranking at its quantity. */
  ranked: Unlock[];
  allQty: number;
  ask: { problem: string; variant: AskVariant } | null;
  openAsk: (problem: string, variant: AskVariant) => void;
  closeAsk: (opts?: { notFixed?: boolean }) => void;
  after: boolean;
  setAfter: (on: boolean) => void;
  pin: PinState;
  /** Turn the part to the open problem (or turn on X-ray when it's inside the part). */
  turn: () => void;
  canTurn: boolean;
  /** The flagged faces can be lit on this 3D view (same analysis mesh). */
  lit: boolean;
  /** How many faces the 3D view lit (null before it reports). */
  litCount: number | null;
}

const Ctx = React.createContext<FixCtxValue | null>(null);
export const FixProvider = Ctx.Provider;

export function useFix(): FixCtxValue {
  const v = React.useContext(Ctx);
  if (!v) throw new Error("useFix outside FixProvider");
  return v;
}

/** The quantities K4 toggles between: 10, 1,000 and 10,000 where the check priced them. */
export function allQuantities(qs: number[]): number[] {
  const want = [10, 1000, 10000].filter((n) => qs.includes(n));
  return want.length ? want : qs.slice(0, 3);
}

/** The method K1 opens on: asked for, else the page's pick, else the cheapest one this fix unlocks. */
export function defaultMethod(p: Problem, set: ProblemSet, methods: Method[], q: number, asked: string | null, pageSel: string | null): ProblemMethod | null {
  if (asked && p.methods.some((m) => m.code === asked)) return pickMethod(p, asked, null);
  if (pageSel && p.methods.some((m) => m.code === pageSel)) return pickMethod(p, pageSel, null);
  const u = unlockOf(p, set, methods, q);
  const best = u.priced.find((x) => p.methods.some((m) => m.code === x.m.code));
  return pickMethod(p, best?.m.code ?? null, null);
}

function readUrl(): FixView | null {
  try {
    const u = new URLSearchParams(window.location.search);
    const id = u.get("problem");
    if (id) return { kind: "problem", id, method: u.get("method") };
    if (u.get("problems") === "all") return { kind: "all", sel: null, q: null, by: u.get("by") === "place" ? "place" : "rank" };
  } catch {
    /* no URL state */
  }
  return null;
}

function writeUrl(v: FixView | null) {
  try {
    const u = new URL(window.location.href);
    for (const k of ["problem", "method", "problems", "by"]) u.searchParams.delete(k);
    if (v?.kind === "problem") {
      u.searchParams.set("problem", v.id);
      if (v.method) u.searchParams.set("method", v.method);
    } else if (v?.kind === "all") {
      u.searchParams.set("problems", "all");
      if (v.by === "place") u.searchParams.set("by", "place");
    }
    window.history.replaceState(window.history.state, "", u.toString());
  } catch {
    /* the view still changes */
  }
}

export function useFixController(args: {
  data: PartData;
  methods: Method[];
  qs: number[];
  q: number;
  selCode: string | null;
  has3d: boolean;
  faceAligned: boolean;
  controller: ViewerController;
  xray: boolean;
  setXray: (on: boolean) => void;
  onOpen: () => void;
  toast: (t: { text: string; link?: { label: string; href: string } }) => void;
  /** The org keeps this part's source (only then can the server fix it). */
  sourceKept?: boolean | null;
}): { value: FixCtxValue; highlight: ViewerHighlight | null; markers: ViewerMarker[]; onPin: (s: PinState) => void; onLit: (n: number) => void } {
  const { data, methods, qs, q, selCode, has3d, faceAligned, controller, xray, setXray, onOpen, toast, sourceKept } = args;
  const set = React.useMemo(() => buildProblems({ validation: data.validation, cost: data.cost }), [data.validation, data.cost]);
  const studio = useStudioOrigin(data.key);
  // Ask the server again once a fix it made has finished (its last attempt changes what it offers).
  const run = useFixRun(data.key);
  const serverTick = run?.kind === "server" && run.s !== "running" ? run.startedAt : 0;
  const serverOpts = useServerOptions(sourceKept ? data.key : null, serverTick);
  const server = React.useMemo(() => serverFixesOf(serverOpts), [serverOpts]);
  const origin = React.useMemo<FixOrigin>(
    () => ({ fileType: data.fileType, open: data.validation?.geometry.is_watertight === false || set.problems.some((p) => p.id === "open"), studio, server }),
    [data.fileType, data.validation, set, studio, server],
  );
  const [view, setViewState] = React.useState<FixView | null>(null);
  const [ask, setAsk] = React.useState<FixCtxValue["ask"]>(null);
  const [after, setAfter] = React.useState(false);
  const [pin, setPin] = React.useState<PinState>("none");
  const [litCount, setLitCount] = React.useState<number | null>(null);
  const opened = React.useRef(onOpen);
  React.useEffect(() => {
    opened.current = onOpen;
  }, [onOpen]);

  React.useEffect(() => {
    const v = readUrl();
    if (v) {
      setViewState(v);
      opened.current();
    }
  }, []);

  const setView = React.useCallback((v: FixView | null) => {
    setViewState(v);
    writeUrl(v);
    if (v) opened.current();
  }, []);

  const qAll = allQuantities(qs);
  const allQty = view?.kind === "all" && view.q != null && qAll.includes(view.q) ? view.q : qAll.includes(q) ? q : qAll[0] ?? q;
  const ranked = React.useMemo(() => rankProblems(set, methods, allQty), [set, methods, allQty]);
  const problem = view?.kind === "problem" ? findProblem(set, view.id) : null;
  const method = problem ? defaultMethod(problem, set, methods, q, view?.kind === "problem" ? view.method : null, selCode) : null;
  const allSel = view?.kind === "all" ? findProblem(set, view.sel) ?? ranked[0]?.problem ?? null : null;

  const lit = has3d && faceAligned;
  const shown = problem ?? allSel;
  const places = React.useMemo(() => placesOf(ranked), [ranked]);
  const highlight = React.useMemo<ViewerHighlight | null>(() => {
    if (!shown || !has3d) return null;
    const m = shown === problem ? method : defaultMethod(shown, set, methods, allQty, null, selCode);
    const faces = lit ? (m?.issue.affected_faces_sample?.length ? m.issue.affected_faces_sample : shown.faces) : [];
    const region = lit ? shown.region : null;
    const label = shown === problem ? "1" : places.find((p) => p.ids.includes(shown.id))?.n ?? "1";
    const kind = shown.kind;
    return {
      faces,
      color: kind ? KIND_COLOR[kind] : "#D92D20",
      region,
      label: label === "·" ? "1" : label,
      kindClass: shown === problem ? (kind ? `k-${kind}` : "k-open") : "on-mark",
      callout: callout(shown, m),
      edges: shown.id === "open",
      // The engine sends a sample of a large draft finding; the viewer finds every flagged face again by the same rule.
      draftRule: shown.id === "draft" && lit && m?.need != null && (m.issue.affected_face_count ?? 0) > faces.length ? { deg: m.need, count: m.issue.affected_face_count! } : null,
    };
  }, [shown, problem, method, has3d, lit, selCode, places, set, methods, allQty]);

  const markers = React.useMemo<ViewerMarker[]>(() => {
    if (view?.kind !== "all" || !lit || !allSel) return [];
    const out: ViewerMarker[] = [];
    for (const pl of places) {
      if (!pl.located || pl.ids.includes(allSel.id)) continue;
      const p = pl.ids.map((id) => findProblem(set, id)).find((x) => x && (x.faces.length || x.region));
      if (p) out.push({ key: pl.name, faces: p.faces, region: p.region, label: pl.n });
    }
    return out;
  }, [view, lit, allSel, places, set]);

  const value: FixCtxValue = {
    set,
    origin,
    view,
    problem,
    method,
    openProblem: (id, m = null) => setView({ kind: "problem", id, method: m }),
    openAll: (sel = null) => setView({ kind: "all", sel, q: view?.kind === "all" ? view.q : null, by: view?.kind === "all" ? view.by : "rank" }),
    close: () => {
      setView(null);
      setAsk(null);
    },
    setMethod: (code) => {
      if (view?.kind === "problem") setView({ ...view, method: code });
    },
    setAll: (p) => {
      if (view?.kind === "all") setView({ ...view, ...p });
    },
    ranked,
    allQty,
    ask,
    openAsk: (problemId, variant) => setAsk({ problem: problemId, variant }),
    closeAsk: (opts) => {
      setAsk(null);
      if (opts?.notFixed) toast({ text: "Not fixed. The problem stays on the part and in the list." });
    },
    after,
    setAfter,
    pin,
    turn: () => {
      if (pin === "inside") setXray(true);
      else controller.current?.turnToHighlight();
    },
    canTurn: has3d && !!highlight && pin !== "none" && (pin !== "inside" || !xray),
    lit,
    litCount,
  };
  return { value, highlight, markers, onPin: setPin, onLit: setLitCount };
}
