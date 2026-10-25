"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, Check, Download, Info, TriangleAlert } from "lucide-react";
import { ESTIMATE, ROUTING, BLOCKERS } from "@/app/(app)/design-system/fixture";
import { UPLOAD_HREF } from "./site-shell";

export const SAMPLE_VIEWS = ["process", "design", "resources"] as const;
export type SampleView = typeof SAMPLE_VIEWS[number];
const labels = ["Process fit", "Design review", "Resource estimate"];
const money = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });

export function SampleExplorer({ initialView = "process", standalone = false }: { initialView?: SampleView; standalone?: boolean }) {
  const [view, setView] = useState(initialView);
  return <div className="cv-sample" id="sample-evidence">
    <div className="cv-sample-bar"><span><BoxMark /> <strong>object.stl</strong><span className="cv-record-label">Recorded example</span></span>{standalone ? <a className="cv-text-link" download="scalecad-sample.json" href={`data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify({ note: "Recorded demonstration. Not a new analysis or supplier quote. Geometry illustration is schematic.", routing: ROUTING, estimate: ESTIMATE, blockers: BLOCKERS }, null, 2))}`}><Download size={15} aria-hidden="true" /> Download record</a> : <Link className="cv-text-link" href="/sample">Open sample <ArrowUpRight size={16} aria-hidden="true" /></Link>}</div>
    <div className="cv-sample-layout">
      <figure className="cv-part-figure"><Image src="/site/sample-part.png" alt="Illustration of the sample’s stepped rotational geometry" width={1200} height={1000} sizes="(max-width: 700px) 90vw, 45vw" /><div className="cv-part-dimensions"><span>21.16 × 21.43 × 21.48 mm</span><span>4.63 cm³</span></div><figcaption>Geometry illustration · measurements from the recorded part</figcaption></figure>
      <div className="cv-sample-evidence"><div className="cv-view-switch" role="group" aria-label="Sample view">{SAMPLE_VIEWS.map((key, i) => <button type="button" key={key} aria-pressed={view === key} onClick={() => setView(key)}>{labels[i]}</button>)}</div>
        <div className="cv-sample-content" aria-live="polite" aria-atomic="true">
          {view === "process" && <><h3>Start with CNC turning.</h3><p className="cv-status"><Check size={16} aria-hidden="true" /> A process to investigate</p><p>The part’s rotational shape points to turning. Check the findings and your machine setup before making the call.</p><dl className="cv-evidence-rows"><div><dt>Geometry</dt><dd>Rotational <span>Measured</span></dd></div><div><dt>Suggested route</dt><dd>CNC turning <span>Model</span></dd></div><div><dt>Alternatives</dt><dd>5-axis CNC · MJF</dd></div><div><dt>Your machine fit</dt><dd>Needs your inventory</dd></div></dl><p className="cv-sample-note"><Info size={16} aria-hidden="true" /> A route suggestion is not production approval. Your machine and operating conditions still need review.</p></>}
          {view === "design" && <><h3>See what needs a second look.</h3><p className="cv-status cv-status-warn"><TriangleAlert size={16} aria-hidden="true" /> Resolve before manufacture</p><p>Findings belong to a process. A problem with molding does not automatically rule out turning.</p><dl className="cv-evidence-rows"><div><dt>Injection molding</dt><dd>{BLOCKERS.injection_molding}</dd></div><div><dt>3-axis CNC</dt><dd>{BLOCKERS.cnc_3axis}</dd></div><div><dt>Next step</dt><dd>Review draft and tool access</dd></div></dl><p className="cv-sample-note"><Info size={16} aria-hidden="true" /> Change the geometry or choose another route, then rerun the analysis. A person approves the design.</p></>}
          {view === "resources" && <><h3>See what goes into the cost.</h3><p className="cv-status cv-status-warn"><Info size={16} aria-hidden="true" /> Assumption-based estimate</p><p>MJF in polypropylene · quantity {ESTIMATE.quantity} · Midwest Precision CNC example calibration.</p><dl className="cv-cost-rows">{[["Labor",ESTIMATE.line_items.labor],["Setup / fixed allocation",ESTIMATE.line_items.amortized_fixed],["Machine",ESTIMATE.line_items.machine],["Material",ESTIMATE.line_items.material]].map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{money(Number(value))}</dd></div>)}<div className="cv-cost-total"><dt>Estimated cost per part</dt><dd>{money(ESTIMATE.unit_cost_usd)}</dd></div></dl><p className="cv-sample-note"><Info size={16} aria-hidden="true" /><span>Range {money(ESTIMATE.confidence!.low_usd)}–{money(ESTIMATE.confidence!.high_usd)}. No measured outcomes yet. This is a resource estimate, not a supplier quote.</span></p></>}
        </div>
        <Link className="cv-text-link" href={standalone ? UPLOAD_HREF : `/sample?view=${view}`}>{standalone ? "Continue with your own part" : "Inspect the full example"}<ArrowRight size={17} aria-hidden="true" /></Link>
      </div>
    </div>
    {standalone && <div className="cv-source-details"><h2>Follow the evidence back to its source.</h2><p>The cost view is the recorded MJF alternative; the geometry-led recommendation is CNC turning. These are different processes, with different assumptions.</p>{ESTIMATE.drivers.map(driver => <details key={driver.name}><summary>{driver.name.replaceAll("_", " ")}<span>{driver.provenance}</span></summary><p>{driver.source}</p></details>)}<p className="cv-caption">Source: ScaleCad’s recorded object.stl example. Sample controls change the view; they do not call the engine. Values are not shop-validated.</p></div>}
  </div>;
}

function BoxMark() { return <span className="cv-file-mark" aria-hidden="true">STL</span>; }
