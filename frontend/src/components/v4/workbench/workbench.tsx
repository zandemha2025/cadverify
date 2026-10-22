"use client";

/**
 * Cost breakdown (boards F3, F5, F7 to F9): the detail behind a part's Cost
 * view, four tabs onto the same engine report, at /app/part/{key}/cost under
 * the part. `?tab=` picks the tab (summary | lines | compare | history; the
 * older decision and glass still work); without a part it's the F9 cold start.
 * The old DFM tab (`?tab=routing` or `dfm`) opens the part page's problem list,
 * so a part's problems live in one place. Tab moves use the history API, so
 * the session (file, results, overrides, scenarios) stays mounted.
 */
import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { R } from "../routes";
import { usePalette, useRegisterPaletteItems } from "../palette";
import { Failed, Loading } from "../ui";
import { defaultQty } from "./derive";
import { getWb, loadSaved, useWb } from "./session";
import { WbHead, WbProviders, lastTab, rememberTab, tabOf, useWbNav, wbHref, WB_TABS, type WbTab } from "./chrome";
import { familyOf } from "../fix/problems";
import { NewPart } from "./new-part";
import { DecisionTab } from "./decision";
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

function Inner({ part }: { part: string | null }) {
  const sp = useSearchParams();
  const tabParam = sp.get("tab");
  const decisionId = sp.get("decision");
  const qParam = sp.get("q");
  const s = useWb();
  const nav = useWbNav();
  const router = useRouter();
  const palette = usePalette();
  const asked = tabOf(tabParam);

  // The old DFM tab: the part's problems and processes are on its part page.
  const toPart = part && asked === "routing";
  React.useEffect(() => {
    if (!toPart || !part) return;
    const issue = sp.get("issue")?.split("|")[0] ?? null;
    router.replace(`${R.part(part)}?${issue ? `problem=${encodeURIComponent(familyOf(issue).id)}` : "problems=all"}`);
  }, [toPart, part, sp, router]);

  // Coming back to the cost breakdown with a part open resumes it.
  const resume = React.useRef(!part && getWb().key && getWb().report ? getWb().key : null);
  React.useEffect(() => {
    if (resume.current) nav(wbHref(asked && asked !== "routing" ? asked : lastTab(), resume.current), true);
    resume.current = null;
    // Only on arrival.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (part) void loadSaved(part, decisionId);
  }, [part, decisionId]);

  // A part without a tab opens on the tab you used last.
  React.useEffect(() => {
    if (part && !asked) {
      const extra: Record<string, string> = {};
      sp.forEach((v, k) => {
        if (k !== "tab" && k !== "part") extra[k] = v;
      });
      nav(wbHref(lastTab(), part, extra), true);
    }
  }, [part, asked, nav, sp]);
  React.useEffect(() => {
    if (asked) rememberTab(asked);
  }, [asked]);

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
      ? WB_TABS.map((t) => ({ id: `wb-${t.tab}`, group: "This part", label: `Cost breakdown · ${t.label}`, sub: s.filename ?? undefined, href: wbHref(t.tab, part) }))
      : [],
  );

  if (!part) {
    return (
      <Frame label="New part">
        <NewPart />
      </Frame>
    );
  }
  if (toPart) {
    return (
      <Frame label="Problems and processes">
        <div className="wb-main full">
          <div className="panel">
            <Loading rows={2} label="Opening the part’s problems" />
          </div>
        </div>
      </Frame>
    );
  }
  const tab: WbTab = asked ?? lastTab();
  const ready = s.key === part && (s.source === "session" || s.load.phase === "done");
  if (!ready) {
    return (
      <Frame label="Cost breakdown">
        <WbHead tab={tab} part={part} meta={[s.load.phase === "error" ? "Part not loaded" : "Loading the part"]} />
        <div className="wb-main full">
          {s.load.phase === "error" && s.key === part ? (
            <div className="panel">
              <Failed
                title="This part didn’t open"
                detail={s.load.error}
                onRetry={() => void loadSaved(part, decisionId)}
                extra={
                  <a className="btn sm" href={R.part(part)}>
                    Open the part
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
  const label = WB_TABS.find((t) => t.tab === tab)?.label ?? "Cost breakdown";
  return (
    <Frame label={label}>
      {tab === "decision" ? <DecisionTab {...props} /> : null}
      {tab === "glass" ? <GlassTab {...props} /> : null}
      {tab === "compare" ? <CompareTab {...props} /> : null}
      {tab === "history" ? <HistoryTab {...props} /> : null}
    </Frame>
  );
}

/** `part`: the mesh hash from the path (/app/part/{key}/cost); null on the cold start. */
export function Workbench({ part }: { part: string | null }) {
  return (
    <WbProviders>
      <Inner part={part} />
    </WbProviders>
  );
}
