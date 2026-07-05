"use client";

/**
 * /teams/design-engineering — "For Design Engineering" (Teams / Design
 * engineering). A faithful production port of
 * `handoff_cadverify_2026-07-04/site/For Design Engineering.dc.html`.
 *
 * Register: dark theater. Cinematic composition — a fixed WebGL shaft studio
 * (shared PartStage) behind five scroll acts:
 *   hero (the verdict, while you design) → 01 the flag (DFM names the failing
 *   draft face) → 02 the dial (the brief changes with the volume) → 03 the fix
 *   (add the draft, the route unlocks) → 04 the gate ("did you consider
 *   molding?") → CTA.
 *
 * Copy is VERBATIM from the audited canonical design. Every figure was checked
 * against the sanctioned fixture list (DESIGN-DECISIONS.md): $14.14 (qty-10 MJF)
 * and the 1,962-unit crossover are the real fixture; the 0.4° draft is the
 * measured value behind the sanctioned "1 sidewall <1.0°"; the qty-5,000 IM
 * $8.01 always carries its conditional qualifier ("requires ≥1.0° draft" /
 * "[illustrative rev]"); the 120 °C world is a declared-input materials gate.
 * No fabricated figure is presented as engine output — nothing to rewrite.
 *
 * The WebGL choreography lives in ./design-choreography (page-local); caption
 * reveals are driven here via useRafLoop so copy reveals even without WebGL.
 */

import * as React from "react";
import Link from "next/link";
import {
  SiteNav,
  SiteFooterTagline,
  PartStage,
  Eyebrow,
  DisplayHeading,
  useRafLoop,
  measureSection,
  applyCaptionReveal,
  smooth,
  clamp01,
} from "@/components/site";
import { makeDesignChoreography } from "./design-choreography";

const CINE = "cubic-bezier(0.16,1,0.3,1)";

export default function DesignEngineeringPage() {
  // act sections (measured for camera + caption acts)
  const sec1 = React.useRef<HTMLElement | null>(null);
  const sec2 = React.useRef<HTMLElement | null>(null);
  const sec3 = React.useRef<HTMLElement | null>(null);
  const sec4 = React.useRef<HTMLElement | null>(null);
  const cta = React.useRef<HTMLElement | null>(null);
  // caption nodes (revealed each frame)
  const cap0 = React.useRef<HTMLElement | null>(null);
  const cap1 = React.useRef<HTMLElement | null>(null);
  const cap2 = React.useRef<HTMLElement | null>(null);
  const cap3 = React.useRef<HTMLElement | null>(null);
  const cap4 = React.useRef<HTMLElement | null>(null);
  const cap5 = React.useRef<HTMLElement | null>(null);

  const choreography = React.useMemo(
    () => makeDesignChoreography({ sec1, sec2, sec3, sec4 }),
    // refs are stable — the choreography is built once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // caption reveals (WebGL-independent): the hero fades out as act 1 ramps; the
  // acts fade in/out on their sticky range; the CTA fades in on approach.
  useRafLoop(() => {
    const m1 = measureSection(sec1.current);
    const m2 = measureSection(sec2.current);
    const m3 = measureSection(sec3.current);
    const m4 = measureSection(sec4.current);
    const mCta = measureSection(cta.current);
    applyCaptionReveal(cap1.current, m1.vis);
    applyCaptionReveal(cap2.current, m2.vis);
    applyCaptionReveal(cap3.current, m3.vis);
    applyCaptionReveal(cap4.current, m4.vis);
    applyCaptionReveal(cap5.current, smooth(mCta.ramp));
    if (cap0.current) cap0.current.style.opacity = (1 - smooth(clamp01(m1.ramp / 0.55))).toFixed(3);
  });

  return (
    <>
      {/* fixed WebGL stage + atmosphere */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0 }}>
        <PartStage choreography={choreography} style={{ position: "fixed", zIndex: 0 }} />
      </div>
      <div className="st-vignette" />

      <SiteNav variant="cinematic" activeHref="/teams" />

      {/* hero */}
      <section
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
        <div ref={cap0 as React.RefObject<HTMLDivElement>} style={{ maxWidth: 700 }}>
          <Eyebrow
            style={{
              color: "rgba(245,245,247,0.5)",
              animation: `st-heroIn 1.4s ${CINE} 0.5s both`,
            }}
          >
            <Link href="/teams" style={{ color: "inherit", textDecoration: "none" }}>
              Teams
            </Link>{" "}
            / Design engineering
          </Eyebrow>
          <DisplayHeading
            as="h1"
            size="clamp(48px, 5.8vw, 84px)"
            style={{ marginTop: 22, lineHeight: 1.02, animation: `st-heroIn 1.4s ${CINE} 0.75s both` }}
          >
            The verdict,
            <br />
            while you design.
          </DisplayHeading>
          <p
            style={{
              margin: "24px 0 0",
              maxWidth: 520,
              fontSize: 18,
              lineHeight: 1.6,
              fontWeight: 300,
              color: "rgba(245,245,247,0.65)",
              animation: `st-heroIn 1.4s ${CINE} 1s both`,
            }}
          >
            You already design to stress, weight, and tolerance — because you can measure them while you work. Now
            makeability is measurable too: envelope, materials-for-the-world, physics, and what it really takes — at
            design speed.
          </p>
        </div>
      </section>

      {/* act 1 — the flag */}
      <section ref={sec1} style={act(150)}>
        <div style={sticky("center")}>
          <div ref={cap1 as React.RefObject<HTMLDivElement>} style={{ maxWidth: 460, opacity: 0 }}>
            <Eyebrow index="01" style={{ color: "var(--st-conditional)" }}>
              Upload mid-design
            </Eyebrow>
            <DisplayHeading size={ACT_H} style={{ marginTop: 18 }}>
              The DFM check names things.
            </DisplayHeading>
            <p style={ACT_BODY}>
              Not &ldquo;moldability: poor&rdquo; — the failing threshold, the measured value, and the exact faces, lit
              on your part while the geometry is still cheap to change.
            </p>
            <p className="st-mono" style={{ ...MONO, color: "var(--st-conditional)" }}>
              ▲ IM_DRAFT_001 — draft 0.4° measured · ≥1.0° required
              <br />
              <span style={{ color: "var(--st-ink-45)" }}>1 sidewall · faces highlighted · will not eject cleanly</span>
              <br />
              <span style={{ color: "var(--st-ink-45)" }}>
                declared world 120 °C → <span style={{ textDecoration: "line-through" }}>PP</span> HDT fails · PEEK /
                17-4PH pass
              </span>
            </p>
          </div>
        </div>
      </section>

      {/* act 2 — the dial */}
      <section ref={sec2} style={act(160)}>
        <div style={sticky("flex-end")}>
          <div ref={cap2 as React.RefObject<HTMLDivElement>} style={{ maxWidth: 470, opacity: 0 }}>
            <Eyebrow index="02">Turn the quantity dial</Eyebrow>
            <DisplayHeading size={ACT_H} style={{ marginTop: 18 }}>
              The design brief changes with the volume.
            </DisplayHeading>
            <p style={ACT_BODY}>
              At qty 10, MJF wins and the draft doesn&rsquo;t matter. At 5,000, molding wins by half —{" "}
              <em style={{ fontStyle: "normal", color: "var(--st-conditional)" }}>if</em> the part is redesigned to
              eject. The crossover at 1,962 units decides whether this week&rsquo;s task is &ldquo;ship it&rdquo; or
              &ldquo;add the draft.&rdquo;
            </p>
            <p className="st-mono" style={{ ...MONO, color: "var(--st-ink-45)" }}>
              qty 10 → MJF $14.14 <span style={{ color: "var(--st-pass)" }}>no change needed</span>
              <br />
              qty 5,000 → IM $8.01 <span style={{ color: "var(--st-conditional)" }}>requires ≥1.0° draft</span>
            </p>
          </div>
        </div>
      </section>

      {/* act 3 — the fix */}
      <section ref={sec3} style={act(160)}>
        <div style={sticky("center")}>
          <div ref={cap3 as React.RefObject<HTMLDivElement>} style={{ maxWidth: 460, opacity: 0 }}>
            <Eyebrow index="03" style={{ color: "var(--st-pass)" }}>
              Fix it, re-run
            </Eyebrow>
            <DisplayHeading size={ACT_H} style={{ marginTop: 18 }}>
              Watch the route unlock.
            </DisplayHeading>
            <p style={ACT_BODY}>
              Add the draft, re-upload, and injection molding flips from fail to pass — the conditional cost becomes
              real. The loop is minutes, so cost iteration happens at design speed, in your hands.
            </p>
            <p className="st-mono" style={{ ...MONO, color: "var(--st-ink-45)" }}>
              rev B · draft 1.2° <span style={{ color: "var(--st-pass)" }}>✓ passes</span> · injection_molding{" "}
              <span style={{ color: "var(--st-fail)" }}>fail</span> →{" "}
              <span style={{ color: "var(--st-pass)" }}>issues 0.9</span>
              <br />
              $8.01 now unconditional <span style={{ color: "var(--st-ink-35)" }}>[illustrative rev]</span>
            </p>
          </div>
        </div>
      </section>

      {/* act 4 — the gate */}
      <section ref={sec4} style={act(150)}>
        <div
          style={{
            position: "sticky",
            top: 0,
            height: "100vh",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
          }}
        >
          <div ref={cap4 as React.RefObject<HTMLDivElement>} style={{ opacity: 0, maxWidth: 720, padding: "0 48px" }}>
            <Eyebrow index="04">The gate review</Eyebrow>
            <p
              style={{
                margin: "18px 0 0",
                fontSize: "clamp(40px, 5.4vw, 78px)",
                lineHeight: 1.03,
                fontWeight: 200,
                letterSpacing: "-0.035em",
              }}
            >
              &ldquo;Did you consider molding?&rdquo;
              <br />
              <span style={{ color: "var(--st-ink-55)" }}>The answer is on screen.</span>
            </p>
            <p
              style={{
                margin: "24px auto 0",
                maxWidth: 540,
                fontSize: 16.5,
                lineHeight: 1.6,
                fontWeight: 300,
                color: "var(--st-ink-60)",
              }}
            >
              The part arrives carrying its cost record — routed, DFM-clean at the target process, banded honestly —
              with the crossover chart showing exactly when molding wins.
            </p>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section
        ref={cta}
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
        <div ref={cap5 as React.RefObject<HTMLDivElement>} style={{ opacity: 0 }}>
          <DisplayHeading as="h2" size="clamp(38px, 4.4vw, 64px)" style={{ letterSpacing: "-0.03em", lineHeight: 1.05 }}>
            Bring the part you&rsquo;re designing right now.
          </DisplayHeading>
          <div style={{ marginTop: 38, display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
            <Link href="/company#pilot" className="st-pill st-pill-solid" style={{ padding: "15px 34px", fontSize: 15.5 }}>
              Request a pilot
            </Link>
            <Link href="/teams" className="st-pill st-pill-ghost" style={{ padding: "15px 34px", fontSize: 15.5 }}>
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

/* ── page-local style helpers (verbatim metrics from the design) ────────────── */

const ACT_H = "clamp(34px, 3.4vw, 50px)";

const ACT_BODY: React.CSSProperties = {
  margin: "20px 0 0",
  fontSize: 16.5,
  lineHeight: 1.6,
  fontWeight: 300,
  color: "var(--st-ink-60)",
};

const MONO: React.CSSProperties = {
  margin: "20px 0 0",
  fontSize: 12,
  lineHeight: 1.9,
};

/** A tall act section (relative, above the fixed stage). `vh` is its height. */
function act(vh: number): React.CSSProperties {
  return { position: "relative", zIndex: 10, height: `${vh}vh` };
}

/** The pinned inner frame of an act; `justify` places the caption column. */
function sticky(justify: React.CSSProperties["justifyContent"]): React.CSSProperties {
  return {
    position: "sticky",
    top: 0,
    height: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: justify,
    padding: "0 48px",
  };
}
