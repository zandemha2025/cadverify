/**
 * Frame for public shared links in the v4 look (boards P7, P9, P8 "turned
 * off"). A share link is what a buyer sends a supplier, so the page is the
 * buyer's, not ScaleCAD's: no session, no app nav, no sign-up call to action,
 * only what this page is ("view only") and a small "Sent with ScaleCAD" line
 * (buyer-14).
 */
import type * as React from "react";
import { Instrument_Sans, Sora } from "next/font/google";
import { PartGlyph } from "./thumb";
import { LinkOff, type LinkOffReason } from "./states";
import "../v4.css";
import "./home.css";
import "./supplier.css";

const sans = Instrument_Sans({ variable: "--font-v4-sans", subsets: ["latin"], display: "swap" });
const disp = Sora({ variable: "--font-v4-disp", subsets: ["latin"], weight: ["500", "600"], display: "swap" });

export function SharedFrame({ kind, children }: { kind: string | null; children: React.ReactNode }) {
  return (
    <div className={`${sans.variable} ${disp.variable}`}>
      <div className="ob" data-ui="v4">
        <header className="bar">
          {kind ? <span className="h-ro">{kind} · view only</span> : null}
          <span className="h-sent">Sent with ScaleCAD</span>
        </header>
        {children}
      </div>
    </div>
  );
}

/** The part on the stage. Shared links carry no mesh, so the neutral outline stands in. */
export function SharedStage({ title, facts, foot }: { title: string; facts: string; foot: React.ReactNode }) {
  return (
    <section className="stage" aria-label="The part">
      <div className="floor" />
      <div className="hud">
        <h1 style={{ overflowWrap: "anywhere" }}>{title}</h1>
        <span className="num">{facts}</span>
      </div>
      <div className="h-still" role="img" aria-label={`Outline standing in for ${title}; the 3D preview isn't shared`}>
        <PartGlyph size={170} />
        <small>3D preview isn&apos;t shared</small>
      </div>
      <p className="h-foot2">
        <span>{foot}</span>
      </p>
    </section>
  );
}

/** P8 "Shared link · turned off": switched off, expired, unknown (or its part was deleted), or unreachable. */
export function SharedOff({ reason = "missing", endedOn = "" }: { reason?: LinkOffReason; endedOn?: string }) {
  return (
    <SharedFrame kind={null}>
      <main className="world h-page" aria-label="Shared link">
        <div className="stage" aria-hidden="true" />
        <div className="h-wrap">
          <div className="h-col" style={{ width: "min(520px, 100%)", marginTop: 80 }}>
            <section className="panel">
              <LinkOff reason={reason} endedOn={endedOn} cta={false} />
            </section>
          </div>
        </div>
      </main>
    </SharedFrame>
  );
}
