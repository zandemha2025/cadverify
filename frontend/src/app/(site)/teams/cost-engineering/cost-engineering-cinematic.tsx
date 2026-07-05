"use client";

/**
 * /teams/cost-engineering — "For Cost Engineering" (dark-theater persona journey).
 *
 * Faithful production port of
 * `handoff_cadverify_2026-07-04/site/For Cost Engineering.dc.html`. A cinematic
 * page: a fixed WebGL shaft (the real object.stl silhouette) plays a four-act
 * scroll choreography behind the copy — it lands, is interrogated (x-ray), the
 * review pushes back on the Σ number (the climax — The Verdict, with should-cost
 * demoted to one openable resource-cost artifact inside it), and finally the
 * assumption band earns its solid green at validation.
 *
 * Composes the shared FOUNDATION (never edits it): SiteNav (cinematic) +
 * PartStage (with a page-local choreography) + evidence primitives +
 * SiteFooterTagline. The choreography is this page's own — the reuse seam of
 * PartStage is the per-frame callback prop (see part-stage.tsx). It measures the
 * four act sections and drives BOTH the WebGL and the page's caption reveals in
 * one loop, exactly as the design's render loop does.
 *
 * HONESTY (this page is the last line — see DESIGN-DECISIONS.md):
 *  - Only the real fixture is engine output: $14.14 · drivers 6.39/3.89/3.82/0.04
 *    (Σ reconciles) · band ±40% n=0 · SHOP rate $30/hr · util 0.80.
 *  - The design's Act-2 machine_cost derivation printed
 *    "0.0682 hr × $30/hr ÷ 0.8 × 1.15 overhead [15.2hr ÷ 223 parts] = $3.82",
 *    which actually computes to $2.94 (math that does not sum) and leans on
 *    non-fixture specifics (a 1.15 overhead, a 15.2 hr build, 223 parts). It is
 *    replaced here with a derivation grounded ONLY in fixture inputs — the SHOP
 *    rate $30/hr and util 0.80 — where the per-unit machine time back-solves to
 *    the real $3.82 (0.1019 hr × $30/hr ÷ 0.80 = $3.82). Nothing invented.
 *  - The "$7,800 acquisition consideration" is not in the fixture, so it wears an
 *    <IllustrativeTag/> (the marginal-vs-acquire distinction itself is kept —
 *    it is the thesis).
 *  - Validation stays schematic: Act 4 prints no residual number; the solid
 *    green band is explicitly the *earned* post-validation state.
 */

import * as React from "react";
import type * as THREE from "three";
import {
  SiteNav,
  SiteFooterTagline,
  PartStage,
  Eyebrow,
  DisplayHeading,
  ProvenanceChip,
  IllustrativeTag,
  measureSection,
  applyCaptionReveal,
  lerp,
  clamp01,
  smooth,
} from "@/components/site";
import type { Choreography } from "@/components/site";

export default function CostEngineeringCinematic() {
  // act sections (measured) + caption nodes (revealed) — one loop drives both.
  const sec1 = React.useRef<HTMLElement | null>(null);
  const sec2 = React.useRef<HTMLElement | null>(null);
  const sec3 = React.useRef<HTMLElement | null>(null);
  const sec4 = React.useRef<HTMLElement | null>(null);
  const ctaSec = React.useRef<HTMLElement | null>(null);
  const cap0 = React.useRef<HTMLDivElement | null>(null);
  const cap1 = React.useRef<HTMLDivElement | null>(null);
  const cap2 = React.useRef<HTMLDivElement | null>(null);
  const cap3 = React.useRef<HTMLDivElement | null>(null);
  const cap4 = React.useRef<HTMLDivElement | null>(null);
  const cap5 = React.useRef<HTMLDivElement | null>(null);

  const choreography = React.useMemo<Choreography>(() => {
    // grabbed once from the shared scene (foundation exposes no light handles).
    let keyLight: THREE.DirectionalLight | null = null;
    let rimLight: THREE.DirectionalLight | null = null;
    let rimBlue: THREE.Color | null = null;
    let rimGreen: THREE.Color | null = null;

    return (f) => {
      const { scene, part, camera, renderer, materials, ghosts, shadow, dt, elapsed } = f;

      if (!rimLight) {
        scene.traverse((o) => {
          const dl = o as THREE.DirectionalLight;
          if (dl.isDirectionalLight) {
            // key sits camera-left (x=-3); rim sits camera-right (x=4).
            if (dl.position.x < 0) keyLight = dl;
            else rimLight = dl;
          }
        });
        rimBlue = new f.THREE.Color(0xbcd2ff);
        rimGreen = new f.THREE.Color(0x55b880);
      }

      const m1 = measureSection(sec1.current); // lands
      const m2 = measureSection(sec2.current); // interrogate (x-ray)
      const m3 = measureSection(sec3.current); // the review — Σ
      const m4 = measureSection(sec4.current); // validated
      const mCta = measureSection(ctaSec.current);

      const a1 = smooth(clamp01(m1.ramp * 0.55 + m1.pin * 0.45));
      const a2 = smooth(clamp01(m2.ramp * 0.45 + m2.pin * 0.55));
      const a3 = smooth(clamp01(m3.ramp * 0.5 + m3.pin * 0.5));
      const a4 = smooth(clamp01(m4.ramp * 0.5 + m4.pin * 0.5));

      part.rotation.y += dt * 0.22;

      // camera: drift → inspect orbit → close on x-ray → far+low for Σ → medium
      const orbit = a1 * 1.2 - a4 * 0.5;
      const radius = lerp(lerp(lerp(lerp(5.4, 3.9, a1), 3.0, a2), 7.6, a3), 4.6, a4);
      camera.position.x = Math.sin(orbit) * radius + lerp(1.5, 0, Math.max(a1, a2));
      camera.position.z = Math.cos(orbit) * radius;
      camera.position.y = lerp(lerp(0.1, 0.5, a1), -0.15, a2);
      camera.lookAt(0, 0, 0);
      part.position.x = lerp(1.55, 0, Math.max(a1, a2));
      part.position.y = lerp(0, -0.5, a3 * (1 - a4)) - Math.sin(elapsed * 0.8) * 0.04;
      part.rotation.z = lerp(0.35, 0.12, a1);

      // x-ray during interrogation, resolidify for the review
      const x = a2 * (1 - a3);
      materials.alu.opacity = lerp(1, 0.12, x);
      materials.wire.opacity = lerp(0, 0.55, x);
      materials.ring.opacity = lerp(1, 0.1, x); // grooves x-ray with the body

      // Σ act: dim the world so the number carries; validated act: lift back up
      renderer.toneMappingExposure = 1.15 * Math.max(0.3, 1 - a3 * 0.7 + a4 * 0.55);

      // validated act: the light itself turns green — the earned solid
      if (rimLight && rimBlue && rimGreen) {
        rimLight.color.copy(rimBlue).lerp(rimGreen, a4);
        rimLight.intensity = 1.6 + a4 * 1.8;
      }
      if (keyLight) keyLight.intensity = 2.4 - a4 * 0.9;

      // this page is the pure shaft + x-ray: keep the shared studio's extra
      // props (metrology / scan / gearbox ghosts / contact shadow) quiet.
      materials.metro.opacity = 0;
      materials.scan.opacity = 0;
      materials.ghost.opacity = 0;
      for (const g of ghosts) g.visible = false;
      (shadow.material as THREE.MeshBasicMaterial).opacity = 0;

      // caption reveals (page-owned DOM, same loop as the design's render loop)
      applyCaptionReveal(cap1.current, m1.vis);
      applyCaptionReveal(cap2.current, m2.vis);
      applyCaptionReveal(cap3.current, m3.vis);
      applyCaptionReveal(cap4.current, m4.vis);
      applyCaptionReveal(cap5.current, smooth(mCta.ramp));
      if (cap0.current) {
        cap0.current.style.opacity = (1 - smooth(clamp01(m1.ramp / 0.55))).toFixed(3);
      }
    };
    // refs are stable across renders — the choreography is built once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      {/* fixed WebGL stage + atmosphere behind the copy */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0 }}>
        <PartStage choreography={choreography} style={{ position: "fixed", zIndex: 0 }} />
      </div>
      <div className="st-vignette" />

      <SiteNav variant="cinematic" activeHref="/teams" />

      {/* ── hero ─────────────────────────────────────────────────────────── */}
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
        <div ref={cap0} style={{ maxWidth: 700 }}>
          <Eyebrow style={{ animation: heroIn(0.5), color: "var(--st-ink-45)" }}>
            <a href="/teams" style={{ color: "inherit", textDecoration: "none" }}>
              Teams
            </a>{" "}
            / Cost engineering
          </Eyebrow>
          <DisplayHeading
            as="h1"
            size="clamp(48px, 5.8vw, 84px)"
            style={{ marginTop: 22, lineHeight: 1.02, animation: heroIn(0.75) }}
          >
            You sign the number.
            <br />
            You should be able to open it.
          </DisplayHeading>
          <p
            style={{
              margin: "24px 0 0",
              maxWidth: 520,
              fontSize: 18,
              lineHeight: 1.6,
              fontWeight: 300,
              color: "rgba(245,245,247,0.65)",
              animation: heroIn(1),
            }}
          >
            From a CAD file landing on your desk, to a number you can defend line-by-line — and
            eventually prove.
          </p>
        </div>
      </section>

      {/* ── act 1 — it lands ─────────────────────────────────────────────── */}
      <section ref={sec1 as React.RefObject<HTMLElement>} style={{ position: "relative", zIndex: 10, height: "150vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", alignItems: "center", padding: "0 48px" }}>
          <div ref={cap1} style={{ maxWidth: 460, opacity: 0 }}>
            <Eyebrow index="01">Monday, 9:04</Eyebrow>
            <DisplayHeading style={{ marginTop: 18 }} size="clamp(34px, 3.4vw, 50px)">
              A part lands.
              <br />
              Twelve seconds later — a verdict.
            </DisplayHeading>
            <p style={{ margin: "20px 0 0", fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
              Program needs the number by Thursday&apos;s review. The engine walks the part through
              envelope, materials, physics — then builds the resource-cost record, every driver
              sourced. The spreadsheet version of this week used to start with hunting for the last
              analogous part.
            </p>
            <p className="st-mono" style={{ margin: "20px 0 0", fontSize: 12, lineHeight: 1.8, color: "var(--st-ink-40)" }}>
              verdict: makeable in-house — M2 Pro (MJF) · $14.14/unit marginal ±40% · Σ ✓ · 412 ms
            </p>
          </div>
        </div>
      </section>

      {/* ── act 2 — interrogate (x-ray) ──────────────────────────────────── */}
      <section ref={sec2 as React.RefObject<HTMLElement>} style={{ position: "relative", zIndex: 10, height: "160vh" }}>
        <div
          style={{
            position: "sticky",
            top: 0,
            height: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            padding: "0 48px",
          }}
        >
          <div ref={cap2} style={{ maxWidth: 470, opacity: 0 }}>
            <Eyebrow index="02">Interrogate it</Eyebrow>
            <DisplayHeading style={{ marginTop: 18 }} size="clamp(34px, 3.4vw, 50px)">
              Open it like you built it.
            </DisplayHeading>
            <p style={{ margin: "20px 0 0", fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
              Every driver drills to its verbatim derivation. Disagree with the machine rate?
              Override it — the row re-tags USER, the report re-costs server-side, and the audit
              trail keeps both versions.
            </p>
            <div style={{ marginTop: 24, display: "flex", flexDirection: "column", gap: 8 }}>
              <div
                className="st-mono"
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  gap: 12,
                  borderBottom: "1px solid var(--st-line-12)",
                  paddingBottom: 7,
                  fontSize: 12.5,
                  color: "var(--st-ink-55)",
                }}
              >
                <span>machine_cost</span>
                <span style={{ display: "inline-flex", alignItems: "baseline", gap: 8, color: "var(--st-ink)" }}>
                  $3.82
                  <ProvenanceChip provenance="SHOP" />
                </span>
              </div>
              <p className="st-mono" style={{ margin: 0, fontSize: 11, lineHeight: 1.7, color: "var(--st-ink-35)" }}>
                &ldquo;0.1019 machine-hr/unit × $30/hr SHOP ÷ 0.80 utilization = $3.82&rdquo;
              </p>
              <p className="st-mono" style={{ margin: "4px 0 0", fontSize: 11.5, color: "var(--st-prov-user)" }}>
                override → re-tags <ProvenanceChip provenance="USER" /> · re-costs · both versions retained
              </p>
              <p
                className="st-mono"
                style={{ margin: "6px 0 0", display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--st-ink-45)" }}
              >
                ownership is explicit: M2 Pro owned → marginal · IM not owned → $7,800 acquisition
                consideration
                <IllustrativeTag />
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── act 3 — the review (climax: The Verdict, Σ = $14.14) ─────────── */}
      <section ref={sec3 as React.RefObject<HTMLElement>} style={{ position: "relative", zIndex: 10, height: "160vh" }}>
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
          <div ref={cap3} style={{ opacity: 0, maxWidth: 720, padding: "0 48px" }}>
            <Eyebrow index="03" style={{ textAlign: "center" }}>
              Thursday, the review pushes back
            </Eyebrow>
            <p className="st-readout" style={{ margin: "18px 0 0", fontSize: "clamp(64px, 9vw, 130px)", letterSpacing: "-0.04em" }}>
              Σ = $14.14
            </p>
            <p className="st-mono" style={{ margin: "18px 0 0", fontSize: 13, color: "var(--st-ink-45)" }}>
              amortized_fixed 3.89 + material 0.04 + machine 3.82 + labor 6.39 — reconciled on
              screen, in the room
            </p>
            <p style={{ margin: "24px auto 0", maxWidth: 560, fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
              &ldquo;Where does the $14.14 come from?&rdquo; You don&apos;t defend a rollup — you
              open it. The band says exactly what it is: assumption-based, n=0, and here&apos;s the
              plan to validate it. The number survives because it has nothing to hide.
            </p>
          </div>
        </div>
      </section>

      {/* ── act 4 — validated (the band earns its solid) ─────────────────── */}
      <section ref={sec4 as React.RefObject<HTMLElement>} style={{ position: "relative", zIndex: 10, height: "150vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", alignItems: "center", padding: "0 48px" }}>
          <div ref={cap4} style={{ maxWidth: 470, opacity: 0 }}>
            <Eyebrow index="04" style={{ color: "var(--st-pass)" }}>
              Quarter-end
            </Eyebrow>
            <DisplayHeading style={{ marginTop: 18 }} size="clamp(34px, 3.4vw, 50px)">
              The band goes solid.
            </DisplayHeading>
            <p style={{ margin: "20px 0 0", fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
              Invoices flow back in, and the model validates against parts it never saw. Next review,
              you&apos;re not presenting an estimate — you&apos;re presenting an instrument with a
              calibration certificate.
            </p>
            <div style={{ marginTop: 24 }}>
              <div style={{ position: "relative", height: 7, borderRadius: 4, background: "rgba(245,245,247,0.08)", overflow: "hidden" }}>
                <div style={{ position: "absolute", inset: "0 18% 0 22%", borderRadius: 4, background: "rgba(85,184,128,0.85)" }} />
                <span aria-hidden="true" style={{ position: "absolute", top: -2, bottom: -2, left: "52%", width: 2, background: "var(--st-ink)" }} />
              </div>
              <p className="st-mono" style={{ margin: "10px 0 0", fontSize: 12, color: "var(--st-pass)" }}>
                validated on n of YOUR parts · a measured residual — the only accuracy figure the
                product will ever print
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────────────────── */}
      <section
        ref={ctaSec as React.RefObject<HTMLElement>}
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
            Bring the part your last review argued about.
          </DisplayHeading>
          <div style={{ marginTop: 38, display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
            <a href="/company#pilot" className="st-pill st-pill-solid" style={{ padding: "15px 34px", fontSize: 15.5 }}>
              Request a pilot
            </a>
            <a href="/teams" className="st-pill st-pill-ghost" style={{ padding: "15px 34px", fontSize: 15.5 }}>
              All teams
            </a>
          </div>
          <p style={{ margin: "64px 0 0" }}>
            <SiteFooterTagline />
          </p>
        </div>
      </section>
    </>
  );
}

/** The staggered cinematic hero-entrance animation (foundation `st-heroIn`). */
function heroIn(delaySeconds: number): string {
  return `st-heroIn 1.4s cubic-bezier(0.16,1,0.3,1) ${delaySeconds}s both`;
}
