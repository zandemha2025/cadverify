"use client";

/**
 * FOUNDATION SCAFFOLDING — /site-preview.
 *
 * NOT a design page. This exercises every shared foundation piece end-to-end
 * (SiteNav cinematic · PartStage + makeHomeChoreography · scroll-act measured
 * sections · mono-evidence primitives · SiteFooterTagline) so the stack builds
 * and runs, and so page builders have a live reference for wiring them.
 *
 * REMOVE AT CUTOVER: the real Home (Direction - Cinematic) is built by a page
 * builder at `(site)/page.tsx` → "/". This file and its route are disposable.
 *
 * Only the real fixture is shown as engine output ($14.14 · drivers
 * 6.39/3.89/3.82/0.04 · band $8.49–19.80 ±40% n=0). The copilot figure is
 * fabricated, so it wears [illustrative] + IN DEVELOPMENT, never a ● SHOP chip.
 */

import * as React from "react";
import {
  SiteNav,
  SiteFooterTagline,
  PartStage,
  makeHomeChoreography,
  Eyebrow,
  DisplayHeading,
  Mono,
  MonoRow,
  ProvenanceChip,
  IllustrativeTag,
  InDevelopmentChip,
  HonestyBand,
  ScrollHint,
  Panel,
} from "@/components/site";

export default function SitePreviewPage() {
  const routed = React.useRef<HTMLElement | null>(null);
  const glassBox = React.useRef<HTMLElement | null>(null);
  const assembly = React.useRef<HTMLElement | null>(null);
  const number = React.useRef<HTMLElement | null>(null);
  const close = React.useRef<HTMLElement | null>(null);
  const numberEl = React.useRef<HTMLElement | null>(null);
  const hud1 = React.useRef<HTMLElement | null>(null);
  const hud2 = React.useRef<HTMLElement | null>(null);

  const choreography = React.useMemo(
    () => makeHomeChoreography({ routed, glassBox, assembly, number, close, numberEl, hud1, hud2 }),
    // refs are stable across renders — the choreography is built once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const cap: React.CSSProperties = { maxWidth: 460, position: "relative", zIndex: 10 };
  const act: React.CSSProperties = { position: "relative", zIndex: 10, height: "150vh" };
  const sticky: React.CSSProperties = {
    position: "sticky",
    top: 0,
    height: "100vh",
    display: "flex",
    alignItems: "center",
    padding: "0 48px",
  };

  return (
    <>
      {/* fixed WebGL stage + atmosphere */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0 }}>
        <PartStage choreography={choreography} style={{ position: "fixed", zIndex: 0 }} />
      </div>
      <div className="st-vignette" />
      <div aria-hidden style={{ position: "fixed", inset: 0, zIndex: 2, pointerEvents: "none", overflow: "hidden" }}>
        <span ref={hud1 as React.RefObject<HTMLSpanElement>} className="st-mono" style={hudStyle}>
          Ø 21.16 mm
        </span>
        <span ref={hud2 as React.RefObject<HTMLSpanElement>} className="st-mono" style={hudStyle}>
          21.43 mm · watertight ✓
        </span>
      </div>

      <SiteNav variant="cinematic" activeHref="/" />

      {/* ACT 1 — hero */}
      <section style={{ position: "relative", zIndex: 10, height: "100vh", display: "flex", flexDirection: "column", justifyContent: "flex-end", padding: "0 48px 9vh" }}>
        <div style={{ maxWidth: 720 }}>
          <Eyebrow style={{ letterSpacing: "0.32em", color: "var(--st-ink-45)" }}>Foundation preview · scaffolding</Eyebrow>
          <DisplayHeading as="h1" size="clamp(52px, 6.5vw, 92px)" style={{ marginTop: 22 }}>
            Every part arrives
            <br />
            with a question.
          </DisplayHeading>
          <p style={{ margin: "26px 0 0", maxWidth: 560, fontSize: 19, lineHeight: 1.55, fontWeight: 300, color: "var(--st-ink-60)" }}>
            Can it be made — on your machines, in materials that survive its world — and what will it really take?
          </p>
        </div>
        <ScrollHint />
      </section>

      {/* ACT 2 — routed */}
      <section ref={routed as React.RefObject<HTMLElement>} style={act}>
        <div style={sticky}>
          <div ref={setCap} style={{ ...cap, opacity: 0 }}>
            <Eyebrow index="01">Routed by geometry</Eyebrow>
            <DisplayHeading style={{ marginTop: 18 }}>
              It reads the shape,
              <br />
              and chooses the machine.
            </DisplayHeading>
            <p className="st-mono" style={{ margin: "22px 0 0", fontSize: 12.5, lineHeight: 1.7, color: "var(--st-ink-40)" }}>
              rotational → cnc_turning · confidence 0.80
              <br />
              envelope — fits 6 of 6 machines · size is not the constraint
            </p>
          </div>
        </div>
      </section>

      {/* ACT 3 — the glass box (x-ray) */}
      <section ref={glassBox as React.RefObject<HTMLElement>} style={{ ...act, height: "160vh" }}>
        <div style={{ ...sticky, justifyContent: "flex-end" }}>
          <Panel style={{ ...cap, opacity: 0, padding: 26 }}>
            <Eyebrow index="02">The glass box</Eyebrow>
            <DisplayHeading style={{ marginTop: 14 }} size="clamp(30px,3vw,44px)">
              Then it opens.
            </DisplayHeading>
            <div style={{ marginTop: 22 }}>
              <MonoRow label="material" value="$0.04" chip={<ProvenanceChip provenance="MEASURED" label={false} />} />
              <MonoRow label="machine" value="$3.82" chip={<ProvenanceChip provenance="SHOP" label={false} />} />
              <MonoRow label="labor" value="$6.39" chip={<ProvenanceChip provenance="SHOP" label={false} />} />
              <MonoRow label="setup" value="$3.89" chip={<ProvenanceChip provenance="SHOP" label={false} />} />
            </div>
          </Panel>
        </div>
      </section>

      {/* ACT 3.5 — assembly seats */}
      <section ref={assembly as React.RefObject<HTMLElement>} style={{ ...act, height: "170vh" }}>
        <div style={{ ...sticky, alignItems: "flex-end", paddingBottom: "10vh" }}>
          <div ref={setCap} style={{ ...cap, maxWidth: 520, opacity: 0 }}>
            <Eyebrow index="03">Context, earned</Eyebrow>
            <DisplayHeading style={{ marginTop: 18 }}>Then it takes its place.</DisplayHeading>
            <p style={{ margin: "20px 0 0", fontSize: 16, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
              When your assembly data is present, the shaft seats into its gearbox — and one unit cost becomes a program number.
            </p>
          </div>
        </div>
      </section>

      {/* ACT 4 — the number (real fixture) */}
      <section ref={number as React.RefObject<HTMLElement>} style={{ ...act, height: "160vh" }}>
        <div style={{ ...sticky, flexDirection: "column", justifyContent: "center", textAlign: "center", padding: 0 }}>
          <div ref={setCap} style={{ opacity: 0, position: "relative", zIndex: 10 }}>
            <Eyebrow index="04" style={{ textAlign: "center" }}>What it really takes</Eyebrow>
            <p ref={numberEl as React.RefObject<HTMLParagraphElement>} className="st-readout" style={{ margin: "18px 0 0", fontSize: "clamp(110px, 15vw, 220px)" }}>
              $14.14
            </p>
            <p style={{ margin: "22px 0 0", fontSize: 17, fontWeight: 300, color: "var(--st-ink-60)" }}>
              per unit · MJF (PP) · quantity 10 — one artifact inside the verdict
            </p>
            <p className="st-mono" style={{ margin: "14px 0 0", fontSize: 12.5, color: "var(--st-ink-40)" }}>
              $8.49 ······ ±40%, assumption-based, not yet validated ······ $19.80
            </p>
          </div>
        </div>
      </section>

      {/* fabricated example — MUST be labeled, never a ● SHOP chip */}
      <section style={{ position: "relative", zIndex: 10, padding: "12vh 48px", background: "rgba(7,7,9,0.9)" }}>
        <div style={{ maxWidth: 760, margin: "0 auto" }}>
          <Eyebrow style={{ textAlign: "center" }}>An illustrative what-if</Eyebrow>
          <Panel well style={{ marginTop: 24, padding: 20 }}>
            <p style={{ margin: 0, display: "flex", alignItems: "center", gap: 10 }}>
              <Mono style={{ fontSize: 11, letterSpacing: "0.12em", color: "var(--st-ink-40)" }}>
                &ldquo;Should we tool up for 5,000 units?&rdquo;
              </Mono>
              <InDevelopmentChip />
            </p>
            <div style={{ marginTop: 12, display: "flex", alignItems: "baseline", gap: 14 }}>
              <span className="st-readout" style={{ fontSize: 34 }}>$8.01</span>
              <IllustrativeTag />
              <Mono style={{ fontSize: 11, color: "var(--st-conditional)" }}>±60% · assumption-based · n=0</Mono>
            </div>
          </Panel>
          <div style={{ marginTop: 34 }}>
            <Mono style={{ fontSize: 11, color: "var(--st-ink-40)" }}>DAY 1 — ASSUMPTION-BASED · ±40% · n=0</Mono>
            <HonestyBand state="assumption" style={{ marginTop: 9 }} />
            <Mono style={{ display: "block", marginTop: 18, fontSize: 11, color: "var(--st-pass)" }}>AFTER YOUR INVOICES — VALIDATED</Mono>
            <HonestyBand state="validated" style={{ marginTop: 9 }} />
          </div>
        </div>
      </section>

      {/* ACT 5 — close */}
      <section ref={close as React.RefObject<HTMLElement>} style={{ position: "relative", zIndex: 10, minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "0 48px" }}>
        <div style={{ position: "relative", zIndex: 10 }}>
          <DisplayHeading as="h2" size="clamp(40px,4.6vw,68px)">Bring your hardest part.</DisplayHeading>
          <p style={{ margin: "22px 0 40px", maxWidth: 520, fontSize: 18, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
            A pilot is a measurement, not a demo: your parts, your shops&apos; rates, validated against invoices we never saw.
          </p>
          <SiteFooterTagline />
        </div>
      </section>
    </>
  );
}

const hudStyle: React.CSSProperties = {
  position: "absolute",
  left: 0,
  top: 0,
  opacity: 0,
  fontSize: 11,
  letterSpacing: "0.08em",
  color: "var(--st-accent)",
  whiteSpace: "nowrap",
  textShadow: "0 1px 8px rgba(0,0,0,0.8)",
};

/** Ref setter for the caption nodes the choreography can't reach directly. */
function setCap(el: HTMLDivElement | null) {
  // The scroll-act choreography drives WebGL; caption reveals are page-owned.
  // Kept minimal here (opacity animates via CSS on scroll in the real pages).
  if (el) el.style.opacity = "1";
}
