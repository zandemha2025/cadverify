/**
 * A part's share link, as its supplier sees it (board P7; buyer-12): the part,
 * its size and material, the quantity, the specs it must meet, the buyer's
 * note and the CAD file when the buyer included it. Our cost estimate (the
 * engine's pick at each quoted quantity, every priced way, the assumptions) is
 * shown only when the buyer turned it on; routes priced on the sender's own
 * machines are never in it (backend supplier_links.py, outbound.py).
 */
import * as React from "react";
import { Fig, Figs, Src } from "../ui";
import { SharedFrame, SharedStage } from "./shared-frame";
import { assumptionName, assumptionSource, assumptionValue, crossoverLine, listQty, pickRange, wayRows } from "./shared-derive";
import { bytesText, dayOf, downloadHref, partFigs, type SupplierPart } from "./supplier-view";
import { sizeText } from "./words";

export function SharedCost({ data }: { data: SupplierPart }) {
  const title = data.label || data.name || data.filename;
  const size = sizeText(data.bbox_mm);
  const facts = [size, data.material, data.quantity != null ? `quantity ${data.quantity.toLocaleString("en-US")}` : ""].filter(Boolean).join(" · ");
  const ends = dayOf(data.link_expires_at);
  return (
    <SharedFrame kind="Request for quote">
      <main className="world" aria-label="Request for quote">
        <SharedStage title={title} facts={facts} foot={data.cad ? "The CAD file is in the panel" : "Ask the buyer for the CAD file"} />
        <aside className="sheet" aria-label="The part">
          <div className="top">
            <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
              {title}
            </h2>
            <p className="smeta">{["Request for quote", data.file_type?.toUpperCase(), ends ? `link works until ${ends}` : null].filter(Boolean).join(" · ")}</p>
            <Figs>
              {partFigs(data, size).map((f) => (
                <Fig key={f.k} k={f.k} v={f.v} sub={f.s} />
              ))}
            </Figs>
          </div>
          <div className="scroll">
            {data.note ? (
              <>
                <div className="gh">
                  <span>Note from the buyer</span>
                  <span />
                </div>
                <p className="sp-note">{data.note}</p>
              </>
            ) : null}
            <div className="gh">
              <span>Specs</span>
              <span>{data.specs.length ? "" : "none given"}</span>
            </div>
            {data.specs.length ? (
              <ul className="sp-specs">
                {data.specs.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            ) : (
              <p className="sp-line">The buyer declared no finish, inspection or certification for this part.</p>
            )}
            <div className="gh">
              <span>CAD file</span>
              <span />
            </div>
            {data.cad ? (
              <div className="sp-dl">
                <span>
                  <b>{data.cad.filename}</b>
                  <small>{bytesText(data.cad.bytes)}</small>
                </span>
                <a className="btn sm ink" href={downloadHref(data.cad.url)} download={data.cad.filename}>
                  Download
                </a>
              </div>
            ) : (
              <p className="sp-line">Not included with this link. Ask the buyer for it.</p>
            )}
            {data.cost ? <CostEstimate cost={data.cost} /> : null}
          </div>
        </aside>
      </main>
    </SharedFrame>
  );
}

/** Our cost estimate, only when the buyer included it with the link. */
function CostEstimate({ cost }: { cost: NonNullable<SupplierPart["cost"]> }) {
  const qty = listQty(cost);
  const ways = wayRows(cost, qty);
  const range = pickRange(cost, qty);
  const cross = crossoverLine(cost);
  return (
    <>
      <div className="gh">
        <span>The buyer&apos;s cost estimate{qty ? `, at ${qty.toLocaleString("en-US")}` : ""}</span>
        <span>each</span>
      </div>
      <p className="sp-line">Included by the buyer. A model estimate made with ScaleCAD, not a quote or a price you are held to.</p>
      {ways.length ? (
        <div role="list" aria-label="The buyer's cost estimate">
          {ways.map((w) => (
            <div className="h-way" role="listitem" key={w.key}>
              <span>
                {w.name}
                {w.note ? <small>{w.note}</small> : null}
              </span>
              <b className="num">{w.price}</b>
            </div>
          ))}
          {range ? (
            <div className="h-way">
              <span>
                Range
                <small>{range}</small>
              </span>
              <b />
            </div>
          ) : null}
          {cross ? (
            <div className="h-way">
              <span>
                Tooling
                <small>{cross}</small>
              </span>
              <b />
            </div>
          ) : null}
        </div>
      ) : null}
      {cost.assumptions?.length ? (
        <div role="list" aria-label="Assumptions">
          {cost.assumptions.map((a) => {
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
      ) : null}
    </>
  );
}
