"use client";

/**
 * The Workbench (boards F3, F5 to F9): one part, five tabs onto the same
 * engine report. `?tab=` picks the tab (decision | routing | glass | compare |
 * history), `?part=<mesh hash>` the part; without a part it's the F9 cold start.
 * Tab moves use the history API, so the session (file, results, overrides,
 * scenarios) stays mounted.
 */
import * as React from "react";
import { useSearchParams } from "next/navigation";
import { R } from "../routes";
import { usePalette, useRegisterPaletteItems } from "../palette";
import { Failed, Loading } from "../ui";
import { defaultQty } from "./derive";
import { getWb, loadSaved, useWb } from "./session";
import { WbHead, WbProviders, isTab, lensDef, useLens, useWbNav, wbHref, WB_TABS, type WbTab } from "./chrome";
import { NewPart } from "./new-part";
import { DecisionTab } from "./decision";
import { RoutingTab } from "./routing";
import { GlassTab } from "./glass";
import { CompareTab } from "./compare";
import { HistoryTab } from "./history";
import "./workbench.css";

export interface TabProps {
  part: string;
  qty: number | null;
  setQty: (q: number) => void;
}

function Frame({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <main className="world wb" aria-label={label}>
      <div className="stage" aria-hidden="true" />
      {children}
    </main>
  );
}

function Inner() {
  const sp = useSearchParams();
  const tabParam = sp.get("tab");
  const part = sp.get("part");
  const decisionId = sp.get("decision");
  const qParam = sp.get("q");
  const s = useWb();
  const lens = useLens();
  const nav = useWbNav();
  const palette = usePalette();

  // Coming back to the Workbench with a part open resumes it.
  const resume = React.useRef(!part && getWb().key && getWb().report ? getWb().key : null);
  React.useEffect(() => {
    if (resume.current) nav(wbHref(isTab(tabParam) ? tabParam : lensDef(lens).tab, resume.current), true);
    resume.current = null;
    // Only on arrival.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (part) void loadSaved(part, decisionId);
  }, [part, decisionId]);

  // A part without a tab lands on the lens's tab.
  React.useEffect(() => {
    if (part && !isTab(tabParam)) {
      const extra: Record<string, string> = {};
      sp.forEach((v, k) => {
        if (k !== "tab" && k !== "part") extra[k] = v;
      });
      nav(wbHref(lensDef(lens).tab, part, { ...extra, ...(lens === "buyer" ? { trust: "1" } : {}) }), true);
    }
  }, [part, tabParam, lens, nav, sp]);

  // The order quantity is shared by Decision, Routing, Compare and History.
  const [qty, setQtyState] = React.useState<{ report: unknown; q: number } | null>(null);
  const report = s.key === part ? s.report : null;
  const q = report ? (qty && qty.report === report ? qty.q : qParam && Number(qParam) > 0 ? Math.round(Number(qParam)) : defaultQty(report)) : null;
  const setQty = React.useCallback((n: number) => setQtyState({ report: getWb().report, q: n }), []);

  React.useEffect(() => {
    if (part && s.filename) palette.setCurrentPart({ label: s.filename, href: R.part(part) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [part, s.filename]);

  useRegisterPaletteItems(
    "workbench",
    part
      ? WB_TABS.map((t) => ({ id: `wb-${t.tab}`, group: "This part", label: `Workbench · ${t.label}`, sub: s.filename ?? undefined, href: wbHref(t.tab, part) }))
      : [],
  );

  if (!part) {
    return (
      <Frame label="New part">
        <NewPart />
      </Frame>
    );
  }
  const tab: WbTab = isTab(tabParam) ? tabParam : lensDef(lens).tab;
  const ready = s.key === part && (s.source === "session" || s.load.phase === "done");
  if (!ready) {
    return (
      <Frame label="Workbench">
        <WbHead tab={tab} part={part} meta={[s.load.phase === "error" ? "Part not loaded" : "Loading the part"]} />
        <div className="wb-main full">
          {s.load.phase === "error" && s.key === part ? (
            <div className="panel">
              <Failed
                title="This part didn’t open"
                detail={s.load.error}
                onRetry={() => void loadSaved(part, decisionId)}
                extra={
                  <a className="btn sm" href={R.workbench}>
                    New part
                  </a>
                }
              />
            </div>
          ) : (
            <div className="panel">
              <Loading rows={4} label="Loading the part’s records" />
            </div>
          )}
        </div>
      </Frame>
    );
  }
  const props: TabProps = { part, qty: q, setQty };
  const label = WB_TABS.find((t) => t.tab === tab)?.label ?? "Workbench";
  return (
    <Frame label={label}>
      {tab === "decision" ? <DecisionTab {...props} /> : null}
      {tab === "routing" ? <RoutingTab {...props} /> : null}
      {tab === "glass" ? <GlassTab {...props} /> : null}
      {tab === "compare" ? <CompareTab {...props} /> : null}
      {tab === "history" ? <HistoryTab {...props} /> : null}
    </Frame>
  );
}

export function Workbench() {
  return (
    <WbProviders>
      <Inner />
    </WbProviders>
  );
}
