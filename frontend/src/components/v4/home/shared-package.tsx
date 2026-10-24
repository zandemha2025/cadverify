/**
 * A package's share link, as its supplier sees it (buyer-12): the request for
 * quote part by part (material, quantity, specs, CAD), who asks, the reply-by
 * date and the buyer's note, and the whole package as a ZIP. The buyer's cost
 * estimate appears only when the package was built with it (backend
 * supplier_links.package_view, rfq_package_service.supplier_view).
 */
import * as React from "react";
import { Fig, Figs } from "../ui";
import { SharedFrame } from "./shared-frame";
import { askerLine, bytesText, dayOf, downloadHref, packagePartLine, usd, type SupplierPackage } from "./supplier-view";

export function SharedPackage({ data }: { data: SupplierPackage }) {
  const ends = dayOf(data.link_expires_at);
  const cad = data.parts.filter((p) => p.cad).length;
  return (
    <SharedFrame kind="Request for quote">
      <main className="world sp-page" aria-label="Request for quote">
        <div className="sp-wrap">
          <section className="panel sp-head">
            <h1 style={{ overflowWrap: "anywhere" }}>{data.title}</h1>
            <p className="smeta">{["Request for quote", data.sent_on ? dayOf(data.sent_on) : null, ends ? `link works until ${ends}` : null].filter(Boolean).join(" · ")}</p>
            <Figs>
              <Fig k="Reply by" v={dayOf(data.reply_by) || "Not given"} sub="the buyer's date" />
              <Fig k="Parts" v={String(data.parts.length)} sub={cad ? `CAD for ${cad}` : "no CAD files"} />
              <Fig k="Supplier must hold" v={data.must_hold.length ? data.must_hold.join(", ") : "Nothing named"} sub="certifications" />
            </Figs>
            <div className="sp-kv">
              <span>Requested by</span>
              <b>{askerLine(data.requested_by)}</b>
              {data.supplier ? (
                <>
                  <span>For</span>
                  <b>{data.supplier}</b>
                </>
              ) : null}
            </div>
            {data.note ? <p className="sp-note">{data.note}</p> : null}
            <div className="sp-acts">
              <a className="btn sm ink" href={downloadHref(data.zip_url)} download>
                Download all (ZIP)
              </a>
              <span className="sp-line">The brief as a PDF, one line per part, and every CAD file below.</span>
            </div>
          </section>
          <section className="panel" aria-label="Parts">
            <div className="ph">
              <h2>Parts</h2>
              <span className="num">{data.parts.length}</span>
            </div>
            {data.parts.map((p) => (
              <div className="sp-part" key={p.line}>
                <div className="sp-ph">
                  <span style={{ minWidth: 0 }}>
                    <b>
                      {p.line}. {p.name}
                    </b>
                    <small>{packagePartLine(p)}</small>
                  </span>
                  {p.cad ? (
                    <a className="btn sm" href={downloadHref(p.cad.url)} download={p.cad.filename}>
                      CAD {bytesText(p.cad.bytes)}
                    </a>
                  ) : (
                    <span className="sp-line">No CAD file</span>
                  )}
                </div>
                {p.specs.length ? (
                  <ul className="sp-specs">
                    {p.specs.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="sp-line">No specs given.</p>
                )}
                {p.process ? <p className="sp-line">Process asked for: {p.process}</p> : null}
                {data.includes_cost_estimate ? (
                  <p className="sp-line">
                    {p.estimate ? `The buyer's estimate: ${usd(p.estimate.unit_cost_usd)} each at ${p.estimate.quantity.toLocaleString("en-US")}${p.estimate.process ? `, ${p.estimate.process}` : ""}. Not a quote.` : "The buyer's estimate: not priced at this quantity."}
                  </p>
                ) : null}
              </div>
            ))}
          </section>
        </div>
      </main>
    </SharedFrame>
  );
}
