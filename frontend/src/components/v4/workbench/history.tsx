"use client";

/**
 * F8 · History: this session's scenarios, every saved decision for this file
 * (GET /cost-decisions?mesh_hash=), and the decision as plain text to copy
 * into an email or a ticket.
 */
import * as React from "react";
import { R } from "../routes";
import { Empty, Failed, Loading, cx } from "../ui";
import { decisionSummary, historyRows } from "./derive";
import { recost, reloadDecisions, useWb } from "./session";
import { WbHead, WbLink, useNeedFile, useToast, useWbNav, wbHref } from "./chrome";
import { baseMeta, useShopName } from "./decision";
import { money, qtyText, whenText } from "./words";
import type { TabProps } from "./workbench";

export function HistoryTab({ part, qty }: TabProps) {
  const s = useWb();
  const { need } = useNeedFile();
  const nav = useWbNav();
  const toast = useToast();
  const shopName = useShopName();
  const rows = historyRows(s.decisions ?? [], s.decision?.id ?? null);
  const summary = decisionSummary(s.report, s.validation, qty);
  const [cp, setCp] = React.useState<{ ok: boolean; msg: string } | null>(null);
  React.useEffect(() => setCp(null), [summary]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(summary);
      setCp({ ok: true, msg: "Summary copied." });
    } catch {
      setCp({ ok: false, msg: "Couldn’t copy. Select the text and copy it." });
    }
  };
  const meta = [
    ...baseMeta(s).slice(0, 2),
    s.decisions ? (
      <>
        <b>{s.decisions.length}</b> saved decision{s.decisions.length === 1 ? "" : "s"}
      </>
    ) : (
      ""
    ),
    <>
      <b>{s.scenarios.length}</b> scenario{s.scenarios.length === 1 ? "" : "s"} this session
    </>,
  ];
  return (
    <>
      <WbHead tab="history" part={part} meta={meta} />
      <div className="wb-main">
        <section className="panel" aria-labelledby="hs-h">
          <div className="ph">
            <h2 id="hs-h">Scenarios this session</h2>
            <span>Lost on refresh or New part</span>
          </div>
          {s.scenarios.length ? (
            <div className="scs" style={{ paddingTop: 6 }}>
              {s.scenarios.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  className="sc"
                  aria-label={`Recall ${x.label}`}
                  onClick={() =>
                    need("recall this scenario", async () => {
                      nav(wbHref("glass", part, x.process && x.qty != null ? { proc: x.process, q: x.qty } : undefined));
                      const r = await recost(x.opts);
                      toast(r ? `Recalled ${x.label}. Re-costed.` : "Re-cost didn’t finish. The last good numbers stay.");
                    })
                  }
                >
                  <span>{x.label}</span>
                  <b className="num">
                    {money(x.unit)}
                    {x.qty != null ? ` at ${qtyText(x.qty)}` : ""}
                  </b>
                </button>
              ))}
            </div>
          ) : (
            <Empty
              title="No scenarios yet"
              actions={
                <WbLink className="btn sm" href={wbHref("glass", part)}>
                  Open line by line
                </WbLink>
              }
            >
              Use a shop’s rates or override a rate line by line, then save it.
            </Empty>
          )}
        </section>
        <section className="panel" aria-labelledby="hd-h">
          <div className="ph">
            <h2 id="hd-h">Saved decisions for this file</h2>
            <span>Kept with sources, tags and range</span>
          </div>
          {s.decisionsError && !s.decisions ? (
            <Failed title="Saved decisions didn’t load" detail={s.decisionsError} onRetry={reloadDecisions} />
          ) : !s.decisions ? (
            <Loading rows={3} label="Loading saved decisions" />
          ) : rows.length === 0 ? (
            <Empty title="No saved decisions">A costed run of this file is saved here with its sources and range.</Empty>
          ) : (
            <div style={{ padding: "0 8px 8px" }} role="list" aria-label="Saved decisions for this file">
              {rows.map((r) => (
                <div role="listitem" key={r.id}>
                  <a className={cx("hr", r.cur && "cur")} href={R.record(r.id)} aria-current={r.cur ? "true" : undefined}>
                    <span className="w num">{whenText(r.created_at)}</span>
                    <span style={{ minWidth: 0 }}>
                      <b>{r.title}</b>
                      <small>{r.sub}</small>
                    </span>
                    <span className={cx("chip", r.chip)}>
                      <i />
                      {r.tag}
                    </span>
                    <span className="w">{r.share}</span>
                  </a>
                </div>
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 8, padding: "0 16px 14px", flexWrap: "wrap" }}>
            <a className="btn sm" href={R.records}>
              Open cost history
            </a>
            <a className="btn sm" href={R.compare}>
              Compare two
            </a>
          </div>
        </section>
      </div>
      <aside className="sheet" aria-label="Decision summary">
        <div className="top">
          <h2 className="stitle">Decision summary</h2>
          <p className="smeta">Plain text for email or a ticket</p>
        </div>
        <div className="scroll">
          {summary ? (
            <>
              <div className="sum" id="sumtext">
                {summary}
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", padding: 12, flexWrap: "wrap" }}>
                <button className="btn ink sm" type="button" onClick={() => void copy()} aria-describedby="sumtext">
                  {cp?.ok ? "Copied" : "Copy decision summary"}
                </button>
                {cp ? (
                  <span className={cx("cpy", !cp.ok && "bad")} role="status">
                    {cp.msg}
                  </span>
                ) : null}
              </div>
              <p style={{ margin: "0 12px", color: "var(--ink3)", fontSize: 12.5 }}>
                Reflects the decision at {qty != null ? qtyText(qty) : "—"} parts on {shopName ?? "typical rates"}.
              </p>
            </>
          ) : (
            <p className="smeta" style={{ margin: "8px 12px" }}>
              No cost decision to summarize yet.
            </p>
          )}
        </div>
      </aside>
    </>
  );
}
