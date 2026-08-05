"use client";

/**
 * /teams/shop-owners — "For Shop Owners" (Teams / Shop owners).
 *
 * A faithful production port of
 * `handoff_cadverify_2026-07-04/site/For Shop Owners.dc.html`: a cinematic
 * dark-theater page with the shared WebGL PartStage fixed behind, driven by the
 * bespoke {@link makeShopChoreography} (the 3-jaw lathe chuck grips the shaft
 * during the Friday-RFQ act). Copy is verbatim from the canonical design.
 *
 * Honesty: every figure shown is the real fixture — Midwest rates $52/$95/$30 ·
 * margin 0.30 (● SHOP, bound from the accounting export) · $14.14 marginal ·
 * lead 5.6–10.4d [queue model] · DFM 423 faces (59.6%) undercut · cnc_turning
 * issues 0.9 (the canonical 0.8–0.9 DFM band). No fabricated engine numbers, so
 * no [illustrative] tags are needed; the loop-closing act describes a measured
 * residual as a FUTURE state you earn on your own delivered jobs, never a
 * measured accuracy claimed now.
 *
 * PAGE-LOCAL builder — composes the shared chrome (SiteNav / PartStage /
 * SiteFooterTagline / scroll acts) and edits no foundation file.
 */

import * as React from "react";
import Link from "next/link";
import {
  SiteNav,
  SiteFooterTagline,
  PartStage,
  applyCaptionReveal,
  measureSection,
  clamp01,
  smooth,
  useRafLoop,
} from "@/components/site";
import { makeShopChoreography } from "./choreography";

const HERO_IN = "st-heroIn 1.4s cubic-bezier(0.16,1,0.3,1)";

export default function ShopOwnersClient() {
  const sec1 = React.useRef<HTMLElement | null>(null);
  const sec2 = React.useRef<HTMLElement | null>(null);
  const sec3 = React.useRef<HTMLElement | null>(null);
  const sec4 = React.useRef<HTMLElement | null>(null);
  const cta = React.useRef<HTMLElement | null>(null);
  const cap0 = React.useRef<HTMLDivElement | null>(null);
  const cap1 = React.useRef<HTMLDivElement | null>(null);
  const cap2 = React.useRef<HTMLDivElement | null>(null);
  const cap3 = React.useRef<HTMLDivElement | null>(null);
  const cap4 = React.useRef<HTMLDivElement | null>(null);
  const cap5 = React.useRef<HTMLDivElement | null>(null);

  const choreography = React.useMemo(
    () => {
      // The factory stores these refs; it reads `.current` only in animation frames.
      // eslint-disable-next-line react-hooks/refs
      return makeShopChoreography({ sec1, sec2, sec3, sec4 });
    },
    // refs are stable — the choreography is built once.
    [],
  );

  // caption reveals are page-owned (robust even if WebGL is unavailable):
  // measure each act from its live rect and fade + settle the copy, exactly as
  // the design's setOp does.
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
    <div style={{ color: "var(--st-ink)" }}>
      {/* fixed WebGL stage + atmosphere behind everything */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0 }}>
        <PartStage choreography={choreography} style={{ position: "fixed", zIndex: 0 }} />
      </div>
      <div className="st-vignette" />

      <SiteNav variant="cinematic" />

      {/* ── hero ─────────────────────────────────────────────────────────── */}
      <section
        data-screen-label="Hero"
        style={{
          position: "relative", zIndex: 10, minHeight: "100vh",
          display: "flex", flexDirection: "column", justifyContent: "flex-end",
          padding: "0 48px 9vh",
        }}
      >
        <div ref={cap0} style={{ maxWidth: 700 }}>
          <p
            className="st-eyebrow"
            style={{ color: "rgba(245,245,247,0.5)", animation: `${HERO_IN} 0.5s both` }}
          >
            <Link href="/teams" style={{ color: "inherit", textDecoration: "none" }}>
              Teams
            </Link>{" "}
            / Shop owners
          </p>
          <h1
            className="st-display"
            style={{
              margin: "22px 0 0", fontSize: "clamp(48px, 5.8vw, 84px)", lineHeight: 1.02,
              animation: `${HERO_IN} 0.75s both`,
            }}
          >
            Your floor,
            <br />
            fully indexed.
          </h1>
          <p
            style={{
              margin: "24px 0 0", maxWidth: 520, fontSize: 18, lineHeight: 1.6, fontWeight: 300,
              color: "rgba(245,245,247,0.65)", animation: `${HERO_IN} 1s both`,
            }}
          >
            Your machines ARE the inventory. Declare them once, and every part that hits your inbox
            gets a verdict — fits which machine, in what material, at what marginal cost.
          </p>
        </div>
      </section>

      {/* ── act 1: calibrate ─────────────────────────────────────────────── */}
      <section ref={sec1} data-screen-label="Calibrate" style={{ position: "relative", zIndex: 10, height: "150vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", alignItems: "center", padding: "0 48px" }}>
          <div ref={cap1} style={{ maxWidth: 460, opacity: 0 }}>
            <p className="st-eyebrow" style={{ color: "var(--st-prov-shop)" }}>01 — Calibrate once</p>
            <h2 className="st-display-2" style={{ margin: "18px 0 0", fontSize: "clamp(34px, 3.4vw, 50px)" }}>
              It&rsquo;s an afternoon, not an implementation.
            </h2>
            <p style={{ margin: "20px 0 0", fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "rgba(245,245,247,0.6)" }}>
              Bind your loaded labor rate, machine rates, utilization, margin, and material lots —
              straight from your accounting export. Everything bound is tagged SHOP; everything
              skipped stays a visible default.
            </p>
            <p className="st-mono" style={{ margin: "20px 0 0", fontSize: 12, lineHeight: 1.9, color: "var(--st-prov-shop)" }}>
              ● labor $52/hr · CNC-3ax $95/hr · MJF $30/hr · margin 0.30
              <br />
              <span style={{ color: "rgba(245,245,247,0.4)" }}>○ 3 rates still DEFAULT — shown, not hidden</span>
            </p>
          </div>
        </div>
      </section>

      {/* ── act 2: the friday rfq ────────────────────────────────────────── */}
      <section ref={sec2} data-screen-label="The RFQ" style={{ position: "relative", zIndex: 10, height: "160vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", alignItems: "center", justifyContent: "flex-end", padding: "0 48px" }}>
          <div ref={cap2} style={{ maxWidth: 470, opacity: 0 }}>
            <p className="st-eyebrow" style={{ color: "rgba(245,245,247,0.45)" }}>02 — Friday, 4:50 PM</p>
            <h2 className="st-display-2" style={{ margin: "18px 0 0", fontSize: "clamp(34px, 3.4vw, 50px)" }}>
              A part lands.
              <br />
              It gets a verdict.
            </h2>
            <p style={{ margin: "20px 0 0", fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "rgba(245,245,247,0.6)" }}>
              The customer&rsquo;s STEP file is verified against your reality — envelope-fit per
              machine, materials, physics, marginal cost at your rates. Price is the last line, and
              it&rsquo;s your call; the verdict underneath it is computed. Monday morning&rsquo;s first
              two hours, done before you lock up.
            </p>
            <p className="st-mono" style={{ margin: "20px 0 0", fontSize: 12, lineHeight: 1.9, color: "rgba(245,245,247,0.45)" }}>
              verdict: fits ST-20 &amp; M2 Pro ✓ · $14.14 marginal at your rates
              <br />
              your margin, your call · lead 5.6–10.4 days{" "}
              <span style={{ color: "rgba(245,245,247,0.35)" }}>[queue model]</span>
            </p>
          </div>
        </div>
      </section>

      {/* ── act 3: skip the bad jobs ─────────────────────────────────────── */}
      <section ref={sec3} data-screen-label="Skip bad jobs" style={{ position: "relative", zIndex: 10, height: "160vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", alignItems: "center", padding: "0 48px" }}>
          <div ref={cap3} style={{ maxWidth: 460, opacity: 0 }}>
            <p className="st-eyebrow" style={{ color: "var(--st-conditional)" }}>03 — Know which jobs don&rsquo;t fit</p>
            <h2 className="st-display-2" style={{ margin: "18px 0 0", fontSize: "clamp(34px, 3.4vw, 50px)" }}>
              Decline in five minutes, with a reason.
            </h2>
            <p style={{ margin: "20px 0 0", fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "rgba(245,245,247,0.6)" }}>
              The DFM matrix runs against the processes on your floor. A part that&rsquo;s 60% undercut
              for your 3-axis cells isn&rsquo;t a job — it&rsquo;s a re-fixturing money pit. Skip it, or
              quote the mill-turn cell it really needs.
            </p>
            <p className="st-mono" style={{ margin: "20px 0 0", fontSize: 12, lineHeight: 1.9, color: "rgba(245,245,247,0.45)" }}>
              cnc_3axis <span style={{ color: "var(--st-fail)" }}>fail</span> — 423 faces (59.6%) undercut
              <br />
              cnc_turning <span style={{ color: "var(--st-pass)" }}>issues 0.9</span> — quote from the mill-turn cell
            </p>
          </div>
        </div>
      </section>

      {/* ── act 4: close the loop ────────────────────────────────────────── */}
      <section ref={sec4} data-screen-label="Close the loop" style={{ position: "relative", zIndex: 10, height: "150vh" }}>
        <div style={{ position: "sticky", top: 0, height: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
          <div ref={cap4} style={{ opacity: 0, maxWidth: 720, padding: "0 48px" }}>
            <p className="st-eyebrow" style={{ color: "var(--st-pass)" }}>04 — Close the loop</p>
            <p className="st-display" style={{ margin: "18px 0 0", fontSize: "clamp(40px, 5.4vw, 78px)", lineHeight: 1.03, fontWeight: 200, letterSpacing: "-0.035em" }}>
              Quote down to the real floor,
              <br />
              <span style={{ color: "rgba(245,245,247,0.55)" }}>not the guessed one.</span>
            </p>
            <p style={{ margin: "24px auto 0", maxWidth: 540, fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "rgba(245,245,247,0.6)" }}>
              Feed job actuals back after delivery and your quotes tighten from ±40% assumption bands
              to a measured residual — shave margin on the work you want, and win it.
            </p>
            <p className="st-mono" style={{ margin: "18px 0 0", fontSize: 12.5, color: "var(--st-pass)" }}>
              validated on your delivered jobs · a measured residual, not a promise
            </p>
          </div>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────────────────── */}
      <section
        ref={cta}
        data-screen-label="CTA"
        style={{
          position: "relative", zIndex: 10, minHeight: "100vh",
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          textAlign: "center", padding: "0 48px",
        }}
      >
        <div ref={cap5} style={{ opacity: 0 }}>
          <h2 className="st-display-2" style={{ margin: 0, fontSize: "clamp(38px, 4.4vw, 64px)", lineHeight: 1.05, letterSpacing: "-0.03em" }}>
            Bring Monday&rsquo;s part list.
            <br />
            Race your estimator.
          </h2>
          <div style={{ marginTop: 38, display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
            <Link href="/company#pilot" className="st-pill st-pill-solid">
              Request a pilot
            </Link>
            <Link href="/teams" className="st-pill st-pill-ghost">
              All teams
            </Link>
          </div>
          <div style={{ margin: "64px 0 40px", fontSize: 12.5, color: "rgba(245,245,247,0.35)" }}>
            <SiteFooterTagline />
          </div>
        </div>
      </section>
    </div>
  );
}
