"use client";

/**
 * /teams/sourcing — "For Sourcing" (Teams / Sourcing & procurement).
 *
 * A faithful recreation of `handoff_cadverify_2026-07-04/site/For Sourcing.dc.html`
 * in the production stack, on the shared dark-theater foundation. Copy is
 * verbatim (post-pivot canonical). The WebGL choreography lives in the
 * page-local SourcingStage (the three-quote-ghosts / copper-lever / portfolio
 * scene); caption reveals are measured per-section here so the copy still
 * reveals where WebGL is unavailable.
 *
 * MUST-KEEP (recreated): the sourcing-native verdict (make in-house / make
 * outside / acquire), banded-not-fake-exact ($26.92 ±50%), the three-quote-
 * ghosts visual.
 *
 * HONESTY PASS (I am the last line — see summary): the design presents three
 * fabricated figures as if measured — the outside should-cost $26.92 ±50%, the
 * acquire economics ($7,800 tool → $6.45/unit), and the competing labor rate
 * ($14/hr against the real $52/hr Midwest loaded rate). Only the real fixture
 * may be shown as engine output ($14.14, crossover 1,962, $52/hr). So every
 * invented figure here wears an [illustrative] / ILLUSTRATIVE DATA tag, and the
 * catalog-triage board carries a scenario marker. $14.14, the
 * crossover 1,962, and $52/hr stay untagged as the only real engine output.
 */

import * as React from "react";
import Link from "next/link";
import {
  SiteNav,
  SiteFooterTagline,
  PILOT_HREF,
  Eyebrow,
  DisplayHeading,
  IllustrativeTag,
  ScenarioChip,
  measureSection,
  smooth,
  clamp01,
  applyCaptionReveal,
  useRafLoop,
} from "@/components/site";
import { SourcingStage } from "./sourcing-stage";

export function SourcingView() {
  const sec1 = React.useRef<HTMLElement | null>(null);
  const sec2 = React.useRef<HTMLElement | null>(null);
  const sec3 = React.useRef<HTMLElement | null>(null);
  const sec4 = React.useRef<HTMLElement | null>(null);
  const secCta = React.useRef<HTMLElement | null>(null);

  const cap0 = React.useRef<HTMLDivElement | null>(null);
  const cap1 = React.useRef<HTMLDivElement | null>(null);
  const cap2 = React.useRef<HTMLDivElement | null>(null);
  const cap3 = React.useRef<HTMLDivElement | null>(null);
  const cap4 = React.useRef<HTMLDivElement | null>(null);
  const cap5 = React.useRef<HTMLDivElement | null>(null);

  // Caption reveals, measured from each act's live layout — mirrors the design's
  // `setOp(cap, m.vis)` and the hero's fade-out on scroll into act 1.
  useRafLoop(() => {
    const m1 = measureSection(sec1.current);
    const m2 = measureSection(sec2.current);
    const m3 = measureSection(sec3.current);
    const m4 = measureSection(sec4.current);
    const mCta = measureSection(secCta.current);
    if (cap0.current) {
      cap0.current.style.opacity = (1 - smooth(clamp01(m1.ramp / 0.55))).toFixed(3);
    }
    applyCaptionReveal(cap1.current, m1.vis);
    applyCaptionReveal(cap2.current, m2.vis);
    applyCaptionReveal(cap3.current, m3.vis);
    applyCaptionReveal(cap4.current, m4.vis);
    applyCaptionReveal(cap5.current, smooth(mCta.ramp));
  });

  const heroIn = (delay: number): React.CSSProperties => ({
    animation: `st-heroIn 1.4s var(--st-ease-cine) ${delay}s both`,
  });
  const sticky: React.CSSProperties = {
    position: "sticky",
    top: 0,
    height: "100vh",
    display: "flex",
    alignItems: "center",
    padding: "0 48px",
  };
  const monoLine: React.CSSProperties = {
    margin: "20px 0 0",
    fontSize: 12,
    lineHeight: 1.9,
    color: "var(--st-ink-45)",
  };

  return (
    <>
      {/* fixed WebGL stage + atmosphere */}
      <SourcingStage refs={{ sec1, sec2, sec3, sec4 }} />
      <div className="st-vignette" />

      <SiteNav variant="cinematic" />

      {/* hero */}
      <section
        data-screen-label="Hero"
        style={{
          position: "relative",
          zIndex: 10,
          height: "100vh",
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
          padding: "0 48px 9vh",
        }}
      >
        <div ref={cap0} style={{ maxWidth: 700 }}>
          <p className="st-eyebrow" style={{ ...heroIn(0.5), color: "var(--st-ink-55)" }}>
            <Link href="/teams" style={{ color: "inherit", textDecoration: "none" }}>
              Teams
            </Link>{" "}
            / Sourcing &amp; procurement
          </p>
          <DisplayHeading as="h1" size="clamp(48px, 5.8vw, 84px)" style={{ marginTop: 22, ...heroIn(0.75) }}>
            Make it, buy it, or
            <br />
            build the capability?
          </DisplayHeading>
          <p
            style={{
              margin: "24px 0 0",
              maxWidth: 520,
              fontSize: 18,
              lineHeight: 1.6,
              fontWeight: 300,
              color: "var(--st-ink-60)",
              ...heroIn(1),
            }}
          >
            The sourcing-native verdict: for every part, the computed choice — make in-house on the floor you own,
            make outside, or acquire the capability — with the resource math underneath.
          </p>
        </div>
      </section>

      {/* act 1: three quotes */}
      <section ref={sec1} data-screen-label="Three quotes" style={{ position: "relative", zIndex: 10, height: "150vh" }}>
        <div style={sticky}>
          <div ref={cap1} style={{ maxWidth: 460, opacity: 0 }}>
            <Eyebrow index="01" style={{ color: "var(--st-ink-45)" }}>
              The RFQ comes back
            </Eyebrow>
            <DisplayHeading style={{ marginTop: 18 }} size="clamp(34px, 3.4vw, 50px)">
              Three options.
              <br />
              One computed answer.
            </DisplayHeading>
            <p style={{ margin: "20px 0 0", fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
              For the same flange: make it in-house at marginal cost, buy it outside, or acquire the tooling. The engine
              computes all three against your floor and your calibrations — the meeting starts from a verdict, not a
              posture.
            </p>
            <p className="st-mono" style={monoLine}>
              in-house — M2 Pro marginal $14.14 · outside — banded yardstick $26.92 ±50%{" "}
              <IllustrativeTag />
              <br />
              acquire — IM $7,800 tool → $6.45/unit past 1,962 <IllustrativeTag />{" "}
              <span style={{ color: "var(--st-conditional)" }}>· if redesigned</span>
            </p>
          </div>
        </div>
      </section>

      {/* act 2: the lever */}
      <section ref={sec2} data-screen-label="The lever" style={{ position: "relative", zIndex: 10, height: "160vh" }}>
        <div style={{ ...sticky, justifyContent: "flex-end" }}>
          <div ref={cap2} style={{ maxWidth: 470, opacity: 0 }}>
            <Eyebrow index="02" style={{ color: "var(--st-prov-shop)" }}>
              Find the divergent driver
            </Eyebrow>
            <DisplayHeading style={{ marginTop: 18 }} size="clamp(34px, 3.4vw, 50px)">
              One line moved.
              <br />
              The board shows which.
            </DisplayHeading>
            <p style={{ margin: "20px 0 0", fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
              Not totals — drivers. Here it&apos;s labor: $52/hr loaded versus $14/hr, while material and machine sit
              within noise. The outside option isn&apos;t expensive everywhere; it carries one assumption you can
              challenge with a number.
            </p>
            <p className="st-mono" style={{ margin: "20px 0 0", fontSize: 12, color: "var(--st-prov-shop)" }}>
              NEGOTIATION LEVER — labor_rate $52/hr vs $14/hr{" "}
              <IllustrativeTag style={{ color: "var(--st-ink-40)" }} />
            </p>
          </div>
        </div>
      </section>

      {/* act 3: the meeting */}
      <section ref={sec3} data-screen-label="The meeting" style={{ position: "relative", zIndex: 10, height: "160vh" }}>
        <div
          style={{
            ...sticky,
            flexDirection: "column",
            justifyContent: "center",
            textAlign: "center",
            padding: 0,
          }}
        >
          <div ref={cap3} style={{ opacity: 0, maxWidth: 760, padding: "0 48px" }}>
            <Eyebrow index="03" style={{ color: "var(--st-ink-45)" }}>
              Walk in with the stack
            </Eyebrow>
            <p
              style={{
                margin: "18px 0 0",
                fontSize: "clamp(44px, 6vw, 88px)",
                lineHeight: 1.02,
                fontWeight: 200,
                letterSpacing: "-0.035em",
              }}
            >
              &ldquo;We compute $26.92 ±50%
              <br />
              at your rates. Walk us through the delta.&rdquo;
            </p>
            <div style={{ marginTop: 20, display: "flex", justifyContent: "center" }}>
              <IllustrativeTag block />
            </div>
            <p style={{ margin: "26px auto 0", maxWidth: 560, fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
              A banded should-cost is more wieldable than a fake-exact point. The supplier can argue with an assumption —
              sometimes they&apos;re right, and the model absorbs it. Either way, the conversation is about drivers now,
              not postures.
            </p>
          </div>
        </div>
      </section>

      {/* act 4: the portfolio */}
      <section ref={sec4} data-screen-label="Portfolio" style={{ position: "relative", zIndex: 10, height: "150vh" }}>
        <div style={sticky}>
          <div ref={cap4} style={{ maxWidth: 470, opacity: 0 }}>
            <Eyebrow index="04" style={{ color: "var(--st-ink-45)" }}>
              Then do it for everything
            </Eyebrow>
            <DisplayHeading style={{ marginTop: 18 }} size="clamp(34px, 3.4vw, 50px)">
              The whole catalog, triaged into honest buckets.
            </DisplayHeading>
            <p style={{ margin: "20px 0 0", fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
              Triage runs this verdict across every part in the org: makeable in-house, makeable outside, needs new
              capability, not makeable as drawn. Savings appear only where a paid baseline exists — validated reads
              solid, assumption-based stays hatched, no baseline means withheld.
            </p>
            <p className="st-mono" style={monoLine}>
              validated savings read solid · assumption-based stay hatched · no baseline = withheld{" "}
              <span style={{ color: "var(--st-conditional)" }}>· portfolio context required</span>{" "}
              <ScenarioChip />
            </p>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section
        ref={secCta}
        data-screen-label="CTA"
        style={{
          position: "relative",
          zIndex: 10,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          padding: "0 48px",
        }}
      >
        <div ref={cap5} style={{ opacity: 0 }}>
          <DisplayHeading as="h2" size="clamp(38px, 4.4vw, 64px)">
            Bring the category you&apos;d rather not re-quote.
          </DisplayHeading>
          <div style={{ marginTop: 38, display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
            <Link href={PILOT_HREF} className="st-pill st-pill-solid">
              Request a pilot
            </Link>
            <Link href="/teams" className="st-pill st-pill-ghost">
              All teams
            </Link>
          </div>
          <div style={{ marginTop: 64, marginBottom: 40 }}>
            <SiteFooterTagline />
          </div>
        </div>
      </section>
    </>
  );
}
