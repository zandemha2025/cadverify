"use client";

/**
 * Home — "Direction - Cinematic" (route "/").
 *
 * Faithful production recreation of
 * `handoff_cadverify_2026-07-04/site/Direction - Cinematic.dc.html`:
 * a fixed WebGL part-choreography stage behind five scroll acts, a metrology
 * HUD, a live crossover dial, the three-gates band, the platform strip, and the
 * pilot close. Copy is verbatim (post-pivot canonical).
 *
 * Composition (per SITE-ROUTE-PLAN §2): SiteNav variant="cinematic" +
 * PartStage(makeHomeChoreography) fixed behind + SiteFooterTagline. WebGL and
 * the exact five-act choreography come from the shared foundation; this page
 * only wires its own section refs and drives the page-owned DOM reveals
 * (caption fades, progress rail, conversion pill) with a useRafLoop.
 *
 * HONESTY (this page is the last line):
 *  - Only the real fixture is presented as engine output: $14.14 · drivers
 *    6.39/3.89/3.82/0.04 · band $8.49–19.80 ±40% n=0 · crossover 1,962 ·
 *    routing cnc_turning 0.80 · DFM 1 sidewall <1.0° · Midwest rates
 *    $52/$30 · util 0.80.
 *  - The copilot ($8.01) is a modeled what-if; the design dressed it in
 *    a filled ● "ENGINE OUTPUT — COMPUTED" chip. That is a filled provenance
 *    dot on a non-fixture figure — a honesty-rule violation. Corrected here to
 *    an [illustrative] tag under a scenario marker. Nothing else changed.
 */

import * as React from "react";
import Link from "next/link";
import {
  SiteNav,
  SiteFooterTagline,
  PartStage,
  makeHomeChoreography,
  ProvenanceChip,
  IllustrativeTag,
  ScenarioChip,
  ScrollHint,
  PILOT_HREF,
  useRafLoop,
  measureSection,
  applyCaptionReveal,
  smooth,
  clamp01,
  scrollToSection,
} from "@/components/site";
import { CrossoverDial } from "./_home/crossover-dial";

const RAIL_STOPS = ["PART", "ROUTED", "OPENED", "SEATED", "THE NUMBER", "PROOF"] as const;

export default function HomePage() {
  // act sections (measured every frame by the WebGL + DOM loops)
  const sec1 = React.useRef<HTMLElement | null>(null); // Act 2 — routed
  const sec2 = React.useRef<HTMLElement | null>(null); // Act 3 — glass box
  const sec2b = React.useRef<HTMLElement | null>(null); // Act 3.5 — assembly
  const sec3 = React.useRef<HTMLElement | null>(null); // Act 4 — the number
  const sec4 = React.useRef<HTMLElement | null>(null); // Act 5 — close
  const secDial = React.useRef<HTMLElement | null>(null); // Act 4.2 — live dial

  // captions revealed per section
  const cap0 = React.useRef<HTMLDivElement | null>(null);
  const cap1 = React.useRef<HTMLDivElement | null>(null);
  const cap2 = React.useRef<HTMLDivElement | null>(null);
  const cap2b = React.useRef<HTMLDivElement | null>(null);
  const cap3 = React.useRef<HTMLDivElement | null>(null);
  const cap4 = React.useRef<HTMLDivElement | null>(null);

  // the counting number + the two projected HUD labels
  const numberEl = React.useRef<HTMLElement | null>(null);
  const hud1 = React.useRef<HTMLElement | null>(null);
  const hud2 = React.useRef<HTMLElement | null>(null);

  // the persistent conversion pill (shown mid-story)
  const ctaBar = React.useRef<HTMLDivElement | null>(null);

  // the progress rail (6 stops)
  const railDots = React.useRef<(HTMLSpanElement | null)[]>([]);
  const railLabels = React.useRef<(HTMLSpanElement | null)[]>([]);

  // WebGL choreography — the exact five-act home choreography (foundation).
  const choreography = React.useMemo(
    () => {
      // The factory stores these refs; it reads `.current` only in animation frames.
      // eslint-disable-next-line react-hooks/refs
      return makeHomeChoreography({
        routed: sec1,
        glassBox: sec2,
        assembly: sec2b,
        number: sec3,
        close: sec4,
        numberEl,
        hud1,
        hud2,
      });
    },
    // refs are stable; the choreography is built once.
    [],
  );

  // Page-owned DOM reveals: caption fades, the conversion pill, and the rail —
  // the same math the design's loop ran for the DOM, measured every frame.
  useRafLoop(() => {
    const m1 = measureSection(sec1.current);
    const m2 = measureSection(sec2.current);
    const m2b = measureSection(sec2b.current);
    const m3 = measureSection(sec3.current);
    const m4 = measureSection(sec4.current);
    const mDial = measureSection(secDial.current);

    const aRoute = smooth(clamp01(m1.ramp * 0.55 + m1.pin * 0.45));
    const aXray = smooth(clamp01(m2.ramp * 0.45 + m2.pin * 0.55));
    const aAsm = smooth(clamp01(m2b.ramp * 0.4 + m2b.pin * 0.6));
    const aNum = smooth(clamp01(m3.ramp * 0.5 + m3.pin * 0.5));
    const aClose = smooth(m4.ramp);

    // hero fades as the routed act rises; each caption tied to its own section
    if (cap0.current) cap0.current.style.opacity = (1 - smooth(clamp01(m1.ramp / 0.55))).toFixed(3);
    applyCaptionReveal(cap1.current, m1.vis);
    applyCaptionReveal(cap2.current, m2.vis);
    applyCaptionReveal(cap2b.current, m2b.vis);
    applyCaptionReveal(cap3.current, m3.vis);
    applyCaptionReveal(cap4.current, aClose);

    // conversion pill: visible mid-story, gone at hero and close
    if (ctaBar.current) {
      const show = aXray > 0.6 && aClose < 0.25 ? 1 : 0;
      ctaBar.current.style.opacity = String(show);
      ctaBar.current.style.transform = `translateY(${show ? 0 : 10}px)`;
      ctaBar.current.style.pointerEvents = show ? "auto" : "none";
    }

    // progress rail: light the active act
    const acts = [
      1 - aRoute,
      aRoute * (1 - aXray),
      aXray * (1 - aAsm),
      aAsm * (1 - aNum),
      aNum * (1 - mDial.ramp),
      mDial.vis,
    ];
    let hi = 0;
    for (let i = 1; i < acts.length; i++) if (acts[i] > acts[hi]) hi = i;
    for (let i = 0; i < 6; i++) {
      const d = railDots.current[i];
      const l = railLabels.current[i];
      if (d) {
        d.style.background = i === hi ? "var(--st-ink)" : "var(--st-ink-25)";
        d.style.transform = i === hi ? "scale(1.5)" : "scale(1)";
      }
      if (l) l.style.opacity = i === hi ? "1" : "0";
    }
  });

  const railJump = (i: number) => {
    const target = [null, sec1.current, sec2.current, sec2b.current, sec3.current, secDial.current][i];
    scrollToSection(target);
  };

  return (
    <>
      {/* fixed WebGL stage */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0 }}>
        <PartStage choreography={choreography} style={{ position: "fixed", zIndex: 0 }} />
      </div>

      {/* fixed vignette atmosphere */}
      <div className="st-vignette" />

      {/* metrology HUD labels (projected from 3D each frame) */}
      <div aria-hidden="true" style={{ position: "fixed", inset: 0, zIndex: 2, pointerEvents: "none", overflow: "hidden" }}>
        <span ref={hud1 as React.RefObject<HTMLSpanElement>} className="st-mono" style={hudStyle}>
          &Oslash; 21.16 mm
        </span>
        <span ref={hud2 as React.RefObject<HTMLSpanElement>} className="st-mono" style={hudStyle}>
          21.43 mm &middot; watertight &#10003;
        </span>
      </div>

      {/* act progress rail */}
      <nav aria-label="Story progress" style={railNav}>
        {RAIL_STOPS.map((label, i) => (
          <button key={label} type="button" onClick={() => railJump(i)} style={railButton}>
            <span
              ref={(el) => {
                railLabels.current[i] = el;
              }}
              className="st-mono"
              style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--st-ink-55)", opacity: 0, transition: "opacity 250ms" }}
            >
              {label}
            </span>
            <span
              ref={(el) => {
                railDots.current[i] = el;
              }}
              style={{ display: "block", width: 6, height: 6, borderRadius: "50%", background: "var(--st-ink-25)", transition: "all 250ms" }}
            />
          </button>
        ))}
      </nav>

      {/* persistent conversion pill (appears mid-story, hides at close) */}
      <div ref={ctaBar} style={ctaBarStyle}>
        <Link href={PILOT_HREF} className="st-pill st-pill-solid" style={{ boxShadow: "0 12px 40px rgba(0,0,0,0.6)" }}>
          See it on your part <span aria-hidden="true">&rarr;</span>
        </Link>
      </div>

      <SiteNav variant="cinematic" activeHref="/" />

      {/* ═══ ACT 1 · the part ═══ */}
      <section
        data-screen-label="Act 1 — Hero"
        style={{ position: "relative", zIndex: 10, height: "100vh", display: "flex", flexDirection: "column", justifyContent: "flex-end", padding: "0 48px 9vh" }}
      >
        <div ref={cap0} style={{ maxWidth: 720 }}>
          <p style={{ margin: 0, fontSize: 14, letterSpacing: "0.32em", textTransform: "uppercase", color: "var(--st-ink-45)", animation: "st-heroIn 1.4s var(--st-ease-cine) 0.6s both" }}>
            Makeability verification
          </p>
          <h1 style={{ margin: "22px 0 0", fontSize: "clamp(52px, 6.5vw, 92px)", lineHeight: 1.02, fontWeight: 300, letterSpacing: "-0.03em", animation: "st-heroIn 1.4s var(--st-ease-cine) 0.85s both" }}>
            Every part arrives
            <br />
            with a question.
          </h1>
          <p style={{ margin: "26px 0 0", maxWidth: 560, fontSize: 19, lineHeight: 1.55, fontWeight: 300, color: "var(--st-ink-65, rgba(245,245,247,0.65))", animation: "st-heroIn 1.4s var(--st-ease-cine) 1.1s both" }}>
            Can it be made — on your machines, in materials that survive its world — and what will it really take?
          </p>
        </div>
        <ScrollHint />
      </section>

      {/* ═══ ACT 2 · it reads the shape ═══ */}
      <section ref={sec1} data-screen-label="Act 2 — Routed" style={{ position: "relative", zIndex: 10, height: "140vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", alignItems: "center", padding: "0 48px" }}>
          <div ref={cap1} style={{ maxWidth: 460, opacity: 0 }}>
            <p style={eyebrow}>01 — Routed by geometry</p>
            <h2 style={{ ...actHeading }}>
              It reads the shape,
              <br />
              and chooses the machine.
            </h2>
            <p style={actBody}>
              Axisymmetric. &Oslash;21 mm. Undercut. Before a single dollar is computed, the engine routes the part the way a manufacturing engineer would — and says its reasoning out loud.
            </p>
            <p className="st-mono" style={{ margin: "22px 0 0", fontSize: 12.5, lineHeight: 1.7, color: "var(--st-ink-40)" }}>
              rotational &rarr; mjf · confidence 0.80
              <br />
              envelope — fits 6 of 6 machines you&rsquo;d declare · size is not the constraint
            </p>
          </div>
        </div>
      </section>

      {/* ═══ ACT 3 · it opens ═══ */}
      <section ref={sec2} data-screen-label="Act 3 — Glass box" style={{ position: "relative", zIndex: 10, height: "160vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", alignItems: "center", justifyContent: "flex-end", padding: "0 48px" }}>
          <div ref={cap2} style={{ maxWidth: 460, textAlign: "left", opacity: 0 }}>
            <p style={eyebrow}>02 — The glass box</p>
            <h2 style={{ ...actHeading }}>Then it opens.</h2>
            <p style={actBody}>
              No sealed total. Five drivers — material, machine, labor, setup, nesting — each measured off the geometry or bound to your shop&rsquo;s real rates, each carrying its source.
            </p>
            <div style={{ marginTop: 26, display: "flex", flexDirection: "column", gap: 9 }} className="st-mono">
              {([
                ["material", "$0.04"],
                ["machine", "$3.82"],
                ["labor", "$6.39"],
                ["setup", "$3.89"],
              ] as const).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", borderBottom: "1px solid var(--st-line-12)", paddingBottom: 8, fontSize: 13, color: "var(--st-ink-55)" }}>
                  <span>{k}</span>
                  <span style={{ color: "var(--st-ink)" }}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ═══ ACT 3.5 · it takes its place ═══ */}
      <section ref={sec2b} data-screen-label="Act 3.5 — Assembly" style={{ position: "relative", zIndex: 10, height: "170vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", alignItems: "flex-end", padding: "0 48px 10vh" }}>
          <div ref={cap2b} style={{ maxWidth: 520, opacity: 0 }}>
            <p style={eyebrow}>03 — Context, earned</p>
            <h2 style={{ ...actHeading }}>Then it takes its place.</h2>
            <p style={actBody}>
              A part never lives alone. When your assembly data is present, the housing seats into its enclosure — and one unit cost becomes a program-level spend.
            </p>
            <div style={{ marginTop: 22, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }} className="st-mono">
              <span style={{ color: "var(--st-ink-40)", fontSize: 12.5 }}>program &rarr; assembly &rarr; part</span>
              <span style={{ color: "var(--st-ink-85, rgba(245,245,247,0.85))", border: "1px solid var(--st-line-strong)", borderRadius: 5, padding: "4px 10px", fontSize: 12.5 }}>
                exposure = unit cost &times; your program volume
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ═══ ACT 4 · the number ═══ */}
      <section ref={sec3} data-screen-label="Act 4 — The number" style={{ position: "relative", zIndex: 10, height: "160vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
          <div ref={cap3} style={{ opacity: 0 }}>
            <p style={{ ...eyebrow }}>04 — What it really takes</p>
            <p ref={numberEl as React.RefObject<HTMLParagraphElement>} className="st-readout" style={{ margin: "18px 0 0", fontSize: "clamp(110px, 15vw, 220px)" }}>
              $14.14
            </p>
            <p style={{ margin: "22px 0 0", fontSize: 17, fontWeight: 300, color: "var(--st-ink-60)" }}>
              per unit · MJF (PP) · quantity 10 — the should-cost, one line inside the decision
            </p>
            <p className="st-mono" style={{ margin: "10px 0 0", fontSize: 11.5, color: "var(--st-ink-35)" }}>
              captured cost-truth-engine output · object.stl · Midwest Precision shop calibration — the same part on every page of this site
            </p>
            <p className="st-mono" style={{ margin: "14px 0 0", fontSize: 12.5, color: "var(--st-ink-40)" }}>
              $8.49 ······ ±40%, assumption-based, not yet validated ······ $19.80
            </p>
            <p style={{ margin: "30px auto 0", maxWidth: 520, fontSize: 16, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-55)" }}>
              And the decision behind it: make by MJF below 1,962 units.
              <br />
              Tool up beyond — stated honestly as &ldquo;if redesigned.&rdquo;
            </p>
          </div>
        </div>
      </section>

      {/* ═══ ACT 4.2 · the proof — a live instrument, not a claim ═══ */}
      <CrossoverDial sectionRef={secDial} />

      {/* ═══ ACT 4.3 · the three gates ═══ */}
      <section data-screen-label="Three gates" style={{ position: "relative", zIndex: 10, background: "rgba(7,7,9,0.9)", padding: "12vh 48px" }}>
        <div style={{ maxWidth: 1180, margin: "0 auto" }}>
          <p style={{ ...eyebrow, textAlign: "center" }}>What nobody else answers</p>
          <div style={{ marginTop: 34, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 18 }}>
            <div className="st-card" style={{ padding: 26 }}>
              <p className="st-mono" style={gateKicker}>YOUR MACHINES, BY NAME</p>
              <p style={{ margin: "12px 0 0", fontSize: 19, fontWeight: 300, letterSpacing: "-0.015em", lineHeight: 1.3 }}>
                &ldquo;Yes — on your M2 Pro.&rdquo;
                <br />
                <span style={{ fontSize: 14, color: "var(--st-ink-55)" }}>Owned &rarr; marginal cost. Missing &rarr; an acquisition consideration, stated as one.</span>
              </p>
            </div>
            <div className="st-card" style={{ padding: 26 }}>
              <p className="st-mono" style={gateKicker}>THE ENVIRONMENT GATE</p>
              <p style={{ margin: "12px 0 0", fontSize: 19, fontWeight: 300, letterSpacing: "-0.015em", lineHeight: 1.3 }}>
                <span style={{ textDecoration: "line-through", color: "var(--st-ink-35)" }}>Al 6061</span>{" "}
                <span className="st-mono" style={{ fontSize: 12, color: "var(--st-fail)" }}>fails NACE MR0175</span>
                <br />
                <span style={{ fontSize: 14, color: "var(--st-ink-55)" }}>Declare the part&rsquo;s service conditions; what can&rsquo;t survive them is struck — visibly, with the reason.</span>
              </p>
            </div>
            <div className="st-card" style={{ padding: 26 }}>
              <p className="st-mono" style={gateKicker}>TRIAGE AT SCALE</p>
              <p style={{ margin: "12px 0 0", fontSize: 19, fontWeight: 300, letterSpacing: "-0.015em", lineHeight: 1.3 }}>
                A legacy catalog, honestly bucketed.
                <br />
                <span style={{ fontSize: 14, color: "var(--st-ink-55)" }}>In-house · outside · needs capability · not makeable — every count opens to its verdicts.</span>
              </p>
            </div>
          </div>
          <p style={{ margin: "22px 0 0", textAlign: "center" }}>
            <Link href="/platform" className="st-underline" style={{ fontSize: 14 }}>
              The full platform &rarr;
            </Link>
          </p>
        </div>
      </section>

      {/* ═══ ACT 4.5 · the platform ═══ */}
      <section data-screen-label="Platform" style={{ position: "relative", zIndex: 10, background: "linear-gradient(180deg, rgba(5,5,6,0) 0%, rgba(7,7,9,0.94) 12%, #070709 100%)", padding: "18vh 48px 10vh" }}>
        <div style={{ maxWidth: 1180, margin: "0 auto" }}>
          <p style={{ ...eyebrow, textAlign: "center" }}>05 — The platform</p>
          <h2 className="st-display-2" style={{ margin: "20px 0 0", textAlign: "center", fontSize: "clamp(38px, 4.2vw, 60px)", lineHeight: 1.06, letterSpacing: "-0.028em" }}>
            The governed decision layer
            <br />
            for everything you make.
          </h2>
          <p style={{ margin: "22px auto 0", maxWidth: 560, textAlign: "center", fontSize: 17, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
            One engine, three surfaces. Every number on every one of them is computed, sourced, and reconciled — nothing is generated.
          </p>

          <div style={{ marginTop: 64, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 20 }}>
            {/* copilot panel */}
            <div className="st-card" style={{ padding: 30, display: "flex", flexDirection: "column", gap: 18 }}>
              <div>
                <p className="st-mono" style={{ margin: 0, display: "flex", alignItems: "center", gap: 10, fontSize: 11, letterSpacing: "0.18em", color: "var(--st-ink-40)" }}>
                  ASK THE ENGINE <ScenarioChip />
                </p>
                <h3 style={{ margin: "10px 0 0", fontSize: 26, fontWeight: 300, letterSpacing: "-0.02em" }}>A copilot that cannot hallucinate a number.</h3>
                <p style={{ margin: "12px 0 0", fontSize: 14.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-55)" }}>
                  Ask in plain language; the answer is a decision artifact. Every figure inside it is an engine run with provenance — the model writes the sentences, never the numbers.
                </p>
              </div>
              <div className="st-card-well" style={{ padding: "18px 20px" }}>
                <p style={{ margin: 0, fontSize: 13.5, fontWeight: 300, color: "var(--st-ink-70)", borderBottom: "1px solid var(--st-line-soft)", paddingBottom: 12 }}>
                  &ldquo;Should we tool up for 5,000 units next year?&rdquo;
                </p>
                {/* HONEST FIX: the design put a filled ● "ENGINE OUTPUT — COMPUTED"
                    chip on $8.01. $8.01 is not the real fixture, so a filled
                    provenance dot here would violate the honesty rules. Marked
                    [illustrative] instead. */}
                <div style={{ marginTop: 14, display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
                  <span className="st-readout" style={{ fontSize: 34 }}>$8.01</span>
                  <IllustrativeTag />
                  <span className="st-mono" style={{ fontSize: 11, color: "var(--st-conditional)" }}>
                    CONDITIONAL — if redesigned · 1 sidewall &lt; 1.0° draft
                  </span>
                </div>
                <p className="st-mono" style={{ margin: "10px 0 0", fontSize: 11, color: "var(--st-ink-40)" }}>
                  ±60% · assumption-based · n=0 · crossover 1,962 units
                </p>
              </div>
            </div>

            {/* calibration panel */}
            <div className="st-card" style={{ padding: 30, display: "flex", flexDirection: "column" }}>
              <p className="st-mono" style={{ margin: 0, fontSize: 11, letterSpacing: "0.18em", color: "var(--st-ink-40)" }}>GOVERNED, NOT GUESSED</p>
              <h3 style={{ margin: "10px 0 0", fontSize: 26, fontWeight: 300, letterSpacing: "-0.02em" }}>Your rates, bound and visible.</h3>
              <p style={{ margin: "12px 0 0", fontSize: 14.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-55)" }}>
                Calibrate to a shop and the whole model re-costs. What&rsquo;s bound is tagged. What isn&rsquo;t stays a visible default — the gaps are governance, not shame.
              </p>
              <div style={{ marginTop: 22, display: "flex", flexDirection: "column", gap: 9, fontSize: 12 }} className="st-mono">
                <CalRow label="labor_rate" value="$52/hr" prov="SHOP" />
                <CalRow label="machine MJF" value="$30/hr" prov="SHOP" />
                <CalRow label="utilization" value="0.80" prov="SHOP" />
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", border: "1px solid rgba(217,168,86,0.3)", borderRadius: 6, padding: "6px 10px", margin: "2px -10px 0" }}>
                  <span style={{ color: "var(--st-conditional)" }}>n_cavities</span>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--st-ink-40)" }}>
                    1 <ProvenanceChip provenance="DEFAULT" />
                  </span>
                </div>
              </div>
              <p className="st-mono" style={{ margin: "auto 0 0", paddingTop: 18, fontSize: 11, color: "var(--st-ink-35)" }}>
                19 rates bound · Midwest Precision CNC · source: 2026-Q2 accounting export
              </p>
            </div>
          </div>

          {/* flywheel */}
          <div className="st-card" style={{ marginTop: 20, padding: 40, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 40, alignItems: "center" }}>
            <div>
              <p className="st-mono" style={{ margin: 0, fontSize: 11, letterSpacing: "0.18em", color: "var(--st-ink-40)" }}>THE GROUND-TRUTH FLYWHEEL</p>
              <h3 style={{ margin: "12px 0 0", fontSize: "clamp(26px, 2.6vw, 36px)", fontWeight: 300, letterSpacing: "-0.022em", lineHeight: 1.15 }}>
                Send back real costs.
                <br />
                Watch the band go solid.
              </h3>
              <p style={{ margin: "14px 0 0", fontSize: 15, lineHeight: 1.65, fontWeight: 300, color: "var(--st-ink-55)" }}>
                Every estimate starts unvalidated — assumption-based, and labeled so. Feed your invoices back and the model checks itself against parts you kept back (never shared with us). That flip from assumption to measured is the only accuracy claim we will ever make.
              </p>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
              <div>
                <div className="st-mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--st-ink-40)", marginBottom: 9 }}>
                  <span>DAY 1 — ASSUMPTION-BASED</span>
                  <span>±40% · n=0</span>
                </div>
                <div className="st-band st-band-hatch" role="img" aria-label="assumption-based band, not yet validated">
                  <span aria-hidden="true" style={{ position: "absolute", top: -2, bottom: -2, left: "50%", width: 2, background: "var(--st-ink)" }} />
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "center" }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--st-ink-40)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 5v14" />
                  <path d="m19 12-7 7-7-7" />
                </svg>
              </div>
              <div>
                <div className="st-mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--st-pass)", marginBottom: 9 }}>
                  <span>AFTER YOUR INVOICES — VALIDATED</span>
                  <span>±ᵐᵉᵃˢᵘʳᵉᵈ · n = your parts</span>
                </div>
                <div className="st-band st-band-solid" role="img" aria-label="validated band">
                  <span aria-hidden="true" style={{ position: "absolute", top: -2, bottom: -2, left: "52%", width: 2, background: "var(--st-ink)" }} />
                </div>
              </div>
            </div>
          </div>

          {/* enterprise strip */}
          <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 20 }}>
            <div className="st-card" style={{ padding: 26 }}>
              <p className="st-mono" style={gateKicker}>YOUR IP STAYS PUT</p>
              <p style={enterpriseBody}>CAD parsed in-process and discarded. Zero network egress on the local path — built for export-controlled programs.</p>
            </div>
            <div className="st-card" style={{ padding: 26 }}>
              <p className="st-mono" style={gateKicker}>EVERY NUMBER AUDITABLE</p>
              <p style={enterpriseBody}>Each driver carries provenance and a source string. A cost engineer can defend the answer in review — line by line.</p>
            </div>
            <div className="st-card" style={{ padding: 26 }}>
              <p className="st-mono" style={gateKicker}>Σ ALWAYS RECONCILES</p>
              <p style={enterpriseBody}>Line items sum to the unit cost on screen. No naked totals, no black-box rollups, no invented precision.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ═══ ACT 5 · close ═══ */}
      <section ref={sec4} data-screen-label="Act 5 — Close" style={{ position: "relative", zIndex: 10, minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "0 48px" }}>
        <div ref={cap4} style={{ opacity: 0 }}>
          <h2 className="st-display-2" style={{ margin: 0, fontSize: "clamp(40px, 4.6vw, 68px)", lineHeight: 1.05, letterSpacing: "-0.03em" }}>Bring your hardest part.</h2>
          <p style={{ margin: "22px auto 0", maxWidth: 520, fontSize: 18, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
            A pilot is a measurement, not a demo: your parts, your shops&rsquo; rates, validated against invoices we never saw — including the parts we get wrong.
          </p>
          <div style={{ margin: "40px auto 0", display: "flex", alignItems: "center", gap: 10, maxWidth: 460, border: "1px solid rgba(245,245,247,0.22)", borderRadius: 999, padding: "6px 6px 6px 22px", background: "rgba(245,245,247,0.04)" }}>
            <input
              placeholder="you@company.com"
              aria-label="Work email"
              style={{ flex: 1, minWidth: 0, background: "none", border: "none", outline: "none", fontSize: 15, color: "var(--st-ink)", fontFamily: "inherit", fontWeight: 300 }}
            />
            <Link href={PILOT_HREF} className="st-pill st-pill-solid" style={{ flexShrink: 0, padding: "12px 26px", fontSize: 14.5 }}>
              Request a pilot
            </Link>
          </div>
          <p className="st-mono" style={{ margin: "16px 0 0", fontSize: 11, color: "var(--st-ink-35)" }}>
            reply in two business days · cloud, VPC, or air-gapped ·{" "}
            <Link href="/method" style={{ color: "var(--st-ink-55)", textDecoration: "none" }}>
              or read the method first &rarr;
            </Link>
          </p>
          <div style={{ margin: "72px 0 40px" }}>
            <SiteFooterTagline />
          </div>
        </div>
      </section>
    </>
  );
}

/* ── page-local styles ─────────────────────────────────────────────────────── */

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

const railNav: React.CSSProperties = {
  position: "fixed",
  right: 30,
  top: "50%",
  transform: "translateY(-50%)",
  zIndex: 25,
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-end",
  gap: 16,
};

const railButton: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "flex-end",
  gap: 10,
  minWidth: 44,
  minHeight: 44,
  background: "none",
  border: "none",
  padding: 0,
  cursor: "pointer",
};

const ctaBarStyle: React.CSSProperties = {
  position: "fixed",
  bottom: 26,
  right: 26,
  zIndex: 30,
  opacity: 0,
  pointerEvents: "none",
  transition: "opacity 500ms, transform 500ms",
  transform: "translateY(10px)",
};

const eyebrow: React.CSSProperties = {
  margin: 0,
  fontSize: 13,
  letterSpacing: "0.32em",
  textTransform: "uppercase",
  color: "var(--st-ink-45)",
};

const actHeading: React.CSSProperties = {
  margin: "18px 0 0",
  fontSize: "clamp(36px, 3.6vw, 54px)",
  lineHeight: 1.08,
  fontWeight: 300,
  letterSpacing: "-0.025em",
};

const actBody: React.CSSProperties = {
  margin: "20px 0 0",
  fontSize: 17,
  lineHeight: 1.6,
  fontWeight: 300,
  color: "var(--st-ink-60)",
};

const gateKicker: React.CSSProperties = {
  margin: 0,
  fontSize: 10.5,
  letterSpacing: "0.16em",
  color: "var(--st-ink-40)",
};

const enterpriseBody: React.CSSProperties = {
  margin: "12px 0 0",
  fontSize: 14.5,
  lineHeight: 1.6,
  fontWeight: 300,
  color: "var(--st-ink-60)",
};

/** One calibration row: label + bound value tagged with a filled ● provenance chip. */
function CalRow({ label, value, prov }: { label: string; value: string; prov: "SHOP" }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ color: "var(--st-ink-55)" }}>{label}</span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--st-prov-shop)" }}>
        {value} <ProvenanceChip provenance={prov} />
      </span>
    </div>
  );
}
