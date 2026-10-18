/**
 * Frame for public shared links in the v4 look (boards P7, P9, P8 "turned
 * off"). No session, no app nav, no account menu: the brand, what this page is
 * ("view only"), and Check a part (which asks a visitor to sign in first).
 */
import type * as React from "react";
import Link from "next/link";
import { Instrument_Sans, Sora } from "next/font/google";
import { R } from "../routes";
import { PartGlyph } from "./thumb";
import { LinkOff } from "./states";
import "../v4.css";
import "./home.css";

const sans = Instrument_Sans({ variable: "--font-v4-sans", subsets: ["latin"], display: "swap" });
const disp = Sora({ variable: "--font-v4-disp", subsets: ["latin"], weight: ["500", "600"], display: "swap" });

export function SharedFrame({ kind, children }: { kind: string | null; children: React.ReactNode }) {
  return (
    <div className={`${sans.variable} ${disp.variable}`}>
      <div className="ob" data-ui="v4">
        <header className="bar">
          <Link className="brand" href="/">
            <svg width="20" height="20" viewBox="0 0 26 26" fill="none" aria-hidden="true">
              <path d="M13 2.6 22.4 8v10L13 23.4 3.6 18V8L13 2.6Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
              <path d="M3.6 8 13 13.4 22.4 8M13 13.4v10" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            </svg>
            ScaleCAD
          </Link>
          {kind ? <span className="h-ro">{kind} · view only</span> : null}
          <Link className="btn go sm" href={R.check} style={{ marginLeft: "auto" }}>
            Check a part
          </Link>
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
        <span>{foot} ·</span>
        <Link href="/">View on ScaleCAD</Link>
      </p>
    </section>
  );
}

/** P8 "Shared link · turned off": the link was revoked, or never existed. */
export function SharedOff() {
  return (
    <SharedFrame kind={null}>
      <main className="world h-page" aria-label="Shared link">
        <div className="stage" aria-hidden="true" />
        <div className="h-wrap">
          <div className="h-col" style={{ width: "min(520px, 100%)", marginTop: 80 }}>
            <section className="panel">
              <LinkOff />
            </section>
          </div>
        </div>
      </main>
    </SharedFrame>
  );
}
