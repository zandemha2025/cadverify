/**
 * Shared should-cost, view only (board P7): the engine's pick at each quoted
 * quantity, every priced way, and the assumptions with where each came from.
 * Inputs the sharer's shop declared arrive hidden and show as "Hidden".
 */
import * as React from "react";
import type { SharedCostDecision } from "@/lib/api";
import { Fig, Figs, Src } from "../ui";
import { SharedFrame, SharedStage } from "./shared-frame";
import { assumptionName, assumptionSource, assumptionValue, crossoverLine, listQty, pickRange, priceFigs, wayRows, type SharedCostLite } from "./shared-derive";
import { longDate, sizeText } from "./words";

export function SharedCost({ data }: { data: SharedCostDecision }) {
  const d = data as unknown as SharedCostLite;
  const title = d.label || d.filename;
  const g = d.geometry ?? {};
  const facts = [sizeText(g.bbox_mm), g.volume_cm3 != null ? `${(Math.round(g.volume_cm3 * 100) / 100).toLocaleString("en-US")} cm³` : "", d.material_class ? `in ${d.material_class}` : ""].filter(Boolean).join(" · ");
  const qty = listQty(d);
  const ways = wayRows(d, qty);
  const range = pickRange(d, qty);
  const cross = crossoverLine(d);
  const figs = priceFigs(d);
  return (
    <SharedFrame kind="Shared should-cost">
      <main className="world h-page" aria-label="Shared should-cost">
        <SharedStage title={title} facts={facts} foot="Model prices, not supplier quotes" />
        <aside className="sheet" aria-label="The should-cost">
          <div className="top">
            <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
              {title}
            </h2>
            <p className="smeta">{["Should-cost", d.material_class, longDate(d.created_at), "view only"].filter(Boolean).join(" · ")}</p>
            {figs.length ? (
              <Figs>
                {figs.map((f) => (
                  <Fig key={f.k} k={f.k} v={f.v} sub={f.s} />
                ))}
              </Figs>
            ) : (
              <p className="smeta">No price: the engine didn&apos;t price a way for this part.</p>
            )}
          </div>
          <div className="scroll">
            {ways.length ? (
              <>
                <div className="gh">
                  <span>Every way priced, at {qty?.toLocaleString("en-US")}</span>
                  <span>each</span>
                </div>
                <div role="list" aria-label={`Every way priced, at ${qty}`}>
                  {ways.map((w) => (
                    <div className="h-way" role="listitem" key={w.key}>
                      <span>
                        {w.name}
                        {w.note ? <small>{w.note}</small> : null}
                      </span>
                      <b className="num">{w.price}</b>
                    </div>
                  ))}
                </div>
                {range || cross ? (
                  <div className="kv" style={{ marginTop: 6 }}>
                    {range ? (
                      <>
                        <span>Range</span>
                        <b>{range}</b>
                      </>
                    ) : null}
                    {cross ? (
                      <>
                        <span>Tooling</span>
                        <b>{cross}</b>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : null}
            {d.assumptions?.length ? (
              <>
                <div className="gh">
                  <span>Assumptions</span>
                  <span />
                </div>
                <div role="list" aria-label="Assumptions">
                  {d.assumptions.map((a) => {
                    const src = assumptionSource(a);
                    return (
                      <div className="h-as" role="listitem" key={a.name}>
                        <span>{assumptionName(a.name)}</span>
                        <Src kind={src.kind}>{src.label}</Src>
                        <b className="num">{assumptionValue(a)}</b>
                        <small>{a.source}</small>
                      </div>
                    );
                  })}
                </div>
              </>
            ) : null}
            <p style={{ margin: "10px 12px", color: "var(--ink3)", fontSize: 12.5 }}>
              Model prices; they shift with cycle times, tooling, batch size and shop rates. Not shown: machines, outcomes, approvals.
            </p>
          </div>
        </aside>
      </main>
    </SharedFrame>
  );
}
