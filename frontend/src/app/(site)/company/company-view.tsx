"use client";

import * as React from "react";

import { SiteShell, Eyebrow, DisplayHeading } from "@/components/site";
import styles from "./company.module.css";
import { PilotForm } from "./pilot-form";

/**
 * /company — the Company page body (dark-theater document register).
 *
 * Recreated faithfully from handoff_cadverify_2026-07-04/site/Company.dc.html.
 * Sections: Mission (with the animated "flip band" — hatched assumption →
 * solid validated), the Pilot program at #pilot (four-week evaluation +
 * request form), Why now, and Contact. Copy is verbatim canonical.
 *
 * This is the "use client" view. `page.tsx` is the thin Server Component that
 * owns page metadata and renders it — the foundation barrel re-exports the
 * client-only scroll-act hooks, so consuming it (as the route plan asks) means
 * the consumer must be a Client Component. It still server-renders for the
 * initial HTML.
 *
 * Honesty: nothing here is presented as engine output — the flip band is
 * schematic (the hatched→solid flip we exist for), the pilot describes the
 * measurement (rates tagged SHOP, gaps left as DEFAULT, the band flips "or it
 * doesn't"), and there are no compliance badges. No violation to correct.
 *
 * Chrome (SiteNav document variant + SiteFooter) comes from SiteShell; the
 * nav's "Request a pilot" CTA and the wordmark cross-link back here / home.
 */

const bodyDim: React.CSSProperties = {
  color: "rgba(245,245,247,0.62)",
};

export default function CompanyView() {
  return (
    <SiteShell>
      {/* ── Mission ─────────────────────────────────────────────────────── */}
      <section style={{ maxWidth: 880, margin: "0 auto", padding: "110px 48px 80px" }}>
        <Eyebrow>Company</Eyebrow>
        <DisplayHeading as="h1" size="clamp(44px, 5.2vw, 72px)" style={{ marginTop: 24 }}>
          Manufacturing runs on numbers nobody can check.
        </DisplayHeading>
        <p style={{ margin: "26px 0 0", maxWidth: 640, fontSize: 18, lineHeight: 1.65, fontWeight: 300, ...bodyDim }}>
          Trillions of dollars of hardware are sourced every year against quotes and estimates that
          arrive as bare totals — from marketplaces selling their own capacity, or suites that bury the
          math where only a specialist can read it. We think the cost of a part should be as inspectable
          as its geometry.
        </p>
        <p style={{ margin: "18px 0 0", maxWidth: 640, fontSize: 18, lineHeight: 1.65, fontWeight: 300, ...bodyDim }}>
          So we built the glass box: a cost-truth engine where every number carries its provenance,
          every total reconciles on screen, and accuracy is a measured property — earned per customer,
          on their parts, against their invoices. Never asserted.
        </p>

        {/* the light: the flip we exist for (hatched assumption → solid validated) */}
        <div className={styles.flipWrap}>
          <div className={styles.flipTrack}>
            <div aria-hidden="true" className={styles.flipHatch} />
            <div aria-hidden="true" className={styles.flipSolid} />
            <span aria-hidden="true" className={styles.flipMarker} />
          </div>
          <div className={styles.flipLabels} aria-hidden="true">
            <p className={`${styles.flipLabel} ${styles.flipLabel1}`}>
              assumption-based · n=0 — how every estimate begins
            </p>
            <p className={`${styles.flipLabel} ${styles.flipLabel2}`}>
              validated on your parts, against your invoices — the flip we exist for
            </p>
          </div>
        </div>

        <div className={styles.statsRow}>
          <span>
            <span className={styles.statNum}>21</span>process families routed &amp; costed
          </span>
          <span>
            <span className={styles.statNum}>4</span>provenance marks on every driver
          </span>
          <span>
            <span className={styles.statNum}>0</span>accuracy claims we haven&apos;t measured
          </span>
        </div>
      </section>

      {/* ── Pilot ───────────────────────────────────────────────────────── */}
      <section
        id="pilot"
        style={{
          borderTop: "1px solid var(--st-line-soft)",
          background: "var(--st-bg-raised)",
          padding: "90px 48px",
          scrollMarginTop: 84,
        }}
      >
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          <Eyebrow>The evaluation</Eyebrow>
          <DisplayHeading
            as="h2"
            size="clamp(32px, 3.8vw, 52px)"
            style={{ marginTop: 20, lineHeight: 1.06, letterSpacing: "-0.028em", maxWidth: 760 }}
          >
            Don&apos;t take our word for it.
            <br />
            That&apos;s the entire point.
          </DisplayHeading>
          <p style={{ margin: "22px 0 0", maxWidth: 620, fontSize: 16.5, lineHeight: 1.65, fontWeight: 300, color: "rgba(245,245,247,0.6)" }}>
            A CadVerify pilot is a measurement, not a demo. You bring real parts and real paid prices;
            we come back with a validated-on-your-parts report — including the parts we got wrong. Runs
            in your environment if your programs require it.
          </p>

          <div className={styles.weekGrid}>
            <WeekCell
              week="WEEK 1"
              title="Bring 10–50 parts"
              body="STL, STEP or IGES, plus your machine list — the floor is the denominator of every verdict — and 12 months of paid prices where you have them. Deployed in our cloud, your VPC, or air-gapped."
            />
            <WeekCell
              week="WEEK 2"
              title="We calibrate"
              body="Your shops' rates bound and tagged SHOP; every gap left visible as a DEFAULT. Every part costed with full driver stacks."
            />
            <WeekCell
              week="WEEK 3"
              title="Held-out validation"
              body="We validate hours and cost against actuals the model never saw — machine time is the number this thesis lives or dies on. The band flips hatched → solid, or it doesn't, and the report says so."
            />
            <WeekCell
              week="WEEK 4"
              title="The decision brief"
              body="Measured residuals per process family, the cost-down ranking for the portfolio you shared, and where the model still guesses."
            />
          </div>

          <PilotForm />
        </div>
      </section>

      {/* ── Why now ─────────────────────────────────────────────────────── */}
      <section style={{ maxWidth: 880, margin: "0 auto", padding: "90px 48px" }}>
        <Eyebrow>Why now</Eyebrow>
        <div
          style={{
            marginTop: 28,
            display: "flex",
            flexDirection: "column",
            gap: 22,
            fontSize: 17,
            lineHeight: 1.7,
            fontWeight: 300,
            color: "rgba(245,245,247,0.65)",
            maxWidth: 680,
          }}
        >
          <p style={{ margin: 0 }}>
            Supply chains regionalized, and with them every make-vs-buy assumption of the last twenty
            years went stale. Reshoring programs are re-costing entire portfolios at once — with cost
            engineering teams that haven&apos;t grown since 2015.
          </p>
          <p style={{ margin: 0 }}>
            At the same moment, language models made it trivial to generate a confident-sounding number.
            The scarce thing is no longer an estimate — it&apos;s an estimate you can audit. We built the
            engine that computes, and drew a hard architectural line so the model that talks can never be
            the one that counts.
          </p>
        </div>
      </section>

      {/* ── Contact ─────────────────────────────────────────────────────── */}
      <section
        style={{
          borderTop: "1px solid var(--st-line-soft)",
          padding: "80px 48px 110px",
          textAlign: "center",
        }}
      >
        <DisplayHeading
          as="h2"
          size="clamp(30px, 3.4vw, 46px)"
          style={{ lineHeight: 1.06, letterSpacing: "-0.026em" }}
        >
          Talk to a human.
        </DisplayHeading>
        <p style={{ margin: "18px auto 0", maxWidth: 440, fontSize: 16, lineHeight: 1.6, fontWeight: 300, color: "rgba(245,245,247,0.55)" }}>
          Founders answer the pilot inbox. Procurement, security, and export-control questions welcome.
        </p>
        <p className="st-mono" style={{ margin: "26px 0 0", fontSize: 14, color: "rgba(245,245,247,0.7)" }}>
          <a href="mailto:pilots@cadverify.com" style={{ color: "inherit", textDecoration: "none" }}>
            pilots@cadverify.com
          </a>
        </p>
      </section>
    </SiteShell>
  );
}

/** One column of the four-week pilot evaluation grid. */
function WeekCell({ week, title, body }: { week: string; title: string; body: string }) {
  return (
    <div className={styles.weekCell}>
      <p
        className="st-mono"
        style={{ margin: 0, fontSize: 11, letterSpacing: "0.14em", color: "rgba(245,245,247,0.4)" }}
      >
        {week}
      </p>
      <h3 style={{ margin: "12px 0 0", fontSize: 19, fontWeight: 400, letterSpacing: "-0.01em" }}>
        {title}
      </h3>
      <p style={{ margin: "10px 0 0", fontSize: 13.5, lineHeight: 1.6, fontWeight: 300, color: "rgba(245,245,247,0.55)" }}>
        {body}
      </p>
    </div>
  );
}
