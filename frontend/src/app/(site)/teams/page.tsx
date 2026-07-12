import type { Metadata } from "next";
import Link from "next/link";
import type * as React from "react";
// NOTE: imported from the foundation sub-modules, NOT the "@/components/site"
// barrel. The barrel re-exports src/lib/site/scroll-acts.ts, a hooks module
// that lacks a "use client" directive; pulling the barrel into this Server
// Component therefore fails the RSC boundary check. site-shell.tsx and
// evidence.tsx are both "use client" and self-contained (no scroll-acts), so
// importing them directly keeps this page a Server Component (with metadata)
// and builds clean. See sharedChangeRequests — the fix belongs in foundation.
import { SiteShell, PILOT_HREF } from "@/components/site/site-shell";
import { Eyebrow, DisplayHeading, IllustrativeTag } from "@/components/site/evidence";

/**
 * /teams — the Teams hub ("Who it's for").
 *
 * Faithful port of handoff_cadverify_2026-07-04/site/Teams.dc.html: the
 * four-lenses-on-one-truth structure — five role lenses (operator / MRO, cost
 * engineering, sourcing, design engineering, shop owners) reading the same
 * engine record, "the answer never changes, only what's foregrounded". Copy is
 * post-pivot canonical and reproduced verbatim.
 *
 * Register: dark theater (via the (site) layout). A document page — sticky nav
 * + full footer through <SiteShell>. Each persona row links to its /teams/*
 * journey; the nav "Teams" link stays lit across the whole subtree.
 *
 * HONESTY: the fixture family (M2 Pro / PP / $14.14 marginal / $7,800 IM
 * acquisition / crossover 1,962 / Midwest rates $52·$95·$30 / margin 0.30 ·
 * util 0.80) is the one real fixture, presented as engine output across every
 * site page. The Sourcing card, alone among the five, prints fabricated
 * shop-vs-shop per-unit costs at qty 1,000 ($5.96 / $10.45 / $2.68) that are
 * NOT in the fixture family — so it carries an [illustrative] tag (the design
 * omitted it; added here per the binding honesty rules — see the branch
 * summary). No ● SHOP chip ever sits on an invented number; the calibration
 * card's ● are the real bound Midwest rates, its ○ the honest DEFAULTs.
 */

export const metadata: Metadata = {
  title: "Teams — CadVerify",
  description:
    "One record. Five people who have to defend it. The same engine output, read through different lenses — cost engineering, sourcing, design engineering, in-house manufacturing and shop owners.",
};

// ── shared row geometry ──────────────────────────────────────────────────────

const ROW: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "110px 1fr 1fr",
  gap: 40,
  padding: "52px 0",
  borderTop: "1px solid var(--st-line-09)",
};

const INDEX_NUM: React.CSSProperties = {
  fontSize: 52,
  fontWeight: 200,
  color: "rgba(245,245,247,0.14)",
  lineHeight: 1,
  fontVariantNumeric: "tabular-nums",
};

const KICKER: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--st-font-mono)",
  fontSize: 11,
  letterSpacing: "0.18em",
  color: "var(--st-ink-40)",
};

const HEADING: React.CSSProperties = {
  margin: "12px 0 0",
  fontSize: 30,
  fontWeight: 300,
  letterSpacing: "-0.02em",
  lineHeight: 1.12,
};

const BODY: React.CSSProperties = {
  margin: "14px 0 0",
  fontSize: 15,
  lineHeight: 1.65,
  fontWeight: 300,
  color: "rgba(245,245,247,0.58)",
};

const JOURNEY: React.CSSProperties = {
  display: "inline-block",
  marginTop: 18,
  fontSize: 14,
  paddingBottom: 2,
};

const CARD: React.CSSProperties = {
  border: "1px solid var(--st-line-09)",
  borderRadius: 12,
  background: "var(--st-panel-2)",
  padding: 22,
  alignSelf: "center",
  fontFamily: "var(--st-font-mono)",
  fontSize: 12,
  lineHeight: 1.9,
};

const CARD_HEAD: React.CSSProperties = {
  margin: 0,
  color: "var(--st-ink-35)",
  fontSize: 10,
  letterSpacing: "0.12em",
};

const L65 = "rgba(245,245,247,0.65)"; // card body ink (no exact token)
const INK = "var(--st-ink)";
const SHOP = "var(--st-prov-shop)"; // #c9834f — bound-rate / negotiation-lever hue
const GOLD = "var(--st-conditional)"; // #d9a856 — acquisition consideration / DFM flag

function PersonaRow({
  index,
  kicker,
  heading,
  body,
  href,
  card,
  last,
}: {
  index: string;
  kicker: string;
  heading: string;
  body: string;
  href: string;
  card: React.ReactNode;
  last?: boolean;
}) {
  return (
    <div style={last ? { ...ROW, borderBottom: "1px solid var(--st-line-09)" } : ROW}>
      <span style={INDEX_NUM}>{index}</span>
      <div>
        <p className="st-mono" style={KICKER}>
          {kicker}
        </p>
        <h2 style={HEADING}>{heading}</h2>
        <p style={BODY}>{body}</p>
        <Link href={href} className="st-underline" style={JOURNEY}>
          The full journey →
        </Link>
      </div>
      {card}
    </div>
  );
}

export default function TeamsPage() {
  return (
    <SiteShell>
      {/* hero */}
      <section style={{ maxWidth: 1100, margin: "0 auto", padding: "110px 48px 70px" }}>
        <Eyebrow>{"Who it's for"}</Eyebrow>
        <DisplayHeading as="h1" size="clamp(44px, 5.2vw, 72px)" style={{ marginTop: 24, maxWidth: 800 }}>
          One record.
          <br />
          Five people who have to defend it.
        </DisplayHeading>
        <p style={{ margin: "26px 0 0", maxWidth: 640, fontSize: 18, lineHeight: 1.65, fontWeight: 300, color: "rgba(245,245,247,0.62)" }}>
          {"The same engine output, read through different lenses — because a cost engineer, a buyer, a design engineer, an in-house manufacturing lead and a shop owner ask different questions of the same number. Role lenses read the same record; the answer never changes, only what's foregrounded."}
        </p>
      </section>

      {/* personas */}
      <section style={{ maxWidth: 1100, margin: "0 auto", padding: "0 48px 60px", display: "flex", flexDirection: "column" }}>
        <PersonaRow
          index="00"
          kicker="IN-HOUSE MANUFACTURING · OPERATOR / MRO"
          heading={'"Can WE make this — on OUR machines?"'}
          body={"The captive shop's question at an operator: a legacy part, an obsolete supplier, a floor full of capability nobody has indexed. Declare the floor once — every verdict after that answers with a machine name: owned → marginal cost, missing → the acquisition it implies."}
          href="/teams/in-house-manufacturing"
          card={
            <div style={CARD}>
              <p style={CARD_HEAD}>THE VERDICT · ON YOUR FLOOR</p>
              <p style={{ margin: "8px 0 0", color: L65 }}>
                → fits <span style={{ color: INK }}>your M2 Pro</span> (380×284×380) ✓
              </p>
              <p style={{ margin: 0, color: L65 }}>→ PP survives the declared world ✓</p>
              <p style={{ margin: 0, color: L65 }}>
                → 0.068 machine-hr · 4.2 g · <span style={{ color: INK }}>$14.14 marginal</span>
              </p>
              <p style={{ margin: "8px 0 0", color: GOLD }}>not owned: IM → $7,800 acquisition consideration</p>
            </div>
          }
        />

        <PersonaRow
          index="01"
          kicker="COST ENGINEERING · OEM"
          heading="Defend the number in the review."
          body={"You're the one who signs the should-cost. Every driver carries its source, line items reconcile to the unit cost on screen, and the confidence band states its basis — so when the program review pushes back, you trace the answer to its inputs instead of defending a black box."}
          href="/teams/cost-engineering"
          card={
            <div style={CARD}>
              <p style={CARD_HEAD}>WHAT THE LENS FOREGROUNDS</p>
              <p style={{ margin: "8px 0 0", color: L65 }}>→ driver stack, verbatim sources</p>
              <p style={{ margin: 0, color: L65 }}>→ Σ reconciliation, error bands per driver</p>
              <p style={{ margin: 0, color: L65 }}>{"→ what's DEFAULT vs SHOP vs MEASURED"}</p>
            </div>
          }
        />

        <PersonaRow
          index="02"
          kicker="SOURCING & PROCUREMENT"
          heading="Negotiate from the driver, not the total."
          body={'Cost the same part against two shop calibrations and the board shows you which driver diverges — labor rate, machine rate, material lot. "Your labor line is 3.7× the Shenzhen calibration" is a negotiation; "your price feels high" is a feeling.'}
          href="/teams/sourcing"
          card={
            <div style={CARD}>
              <p style={{ ...CARD_HEAD, display: "flex", alignItems: "center", gap: 8 }}>
                <span>SHOP VS SHOP · QTY 1,000</span>
                <IllustrativeTag />
              </p>
              <p style={{ margin: "8px 0 0", color: L65 }}>
                CNC turning&nbsp;&nbsp;$26.92 vs $5.96&nbsp;&nbsp;<span style={{ color: SHOP }}>−78%</span>
              </p>
              <p style={{ margin: 0, color: L65 }}>
                MJF&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;$10.45 vs $2.68&nbsp;&nbsp;<span style={{ color: SHOP }}>−74%</span>
              </p>
              <p style={{ margin: "8px 0 0", color: SHOP }}>lever: labor_rate $52/hr vs $14/hr</p>
            </div>
          }
        />

        <PersonaRow
          index="03"
          kicker="DESIGN ENGINEERING"
          heading="Know the cost of a fillet before the gate review."
          body={"DFM feedback that names the fix: the failing threshold, the measured value, and the exact faces — highlighted on the part. Change the draft angle, re-run, and watch the injection-molding route unlock at the crossover quantity. Cost becomes a design variable, not a surprise."}
          href="/teams/design-engineering"
          card={
            <div style={CARD}>
              <p style={CARD_HEAD}>DFM · NAMED AND ACTIONABLE</p>
              <p style={{ margin: "8px 0 0", color: GOLD }}>▲ draft 0.4° measured · ≥1.0° required</p>
              <p style={{ margin: 0, color: L65 }}>→ faces highlighted in 3D</p>
              <p style={{ margin: 0, color: L65 }}>→ fix unlocks IM route at qty ≥ 1,962</p>
            </div>
          }
        />

        <PersonaRow
          index="04"
          kicker="SHOP OWNERS · QUOTING"
          heading="Quote in minutes, at your real rates."
          body={"Bind your loaded labor, machine rates and material lots once, and every incoming RFQ costs itself against your shop's reality — with your margin as an explicit, visible line. Win the jobs that fit your machines; skip the ones that don't, and know why."}
          href="/teams/shop-owners"
          last
          card={
            <div style={CARD}>
              <p style={CARD_HEAD}>YOUR CALIBRATION</p>
              <p style={{ margin: "8px 0 0", color: SHOP }}>● labor $52/hr · CNC-3ax $95/hr · MJF $30/hr</p>
              <p style={{ margin: 0, color: SHOP }}>● margin 0.30 · utilization 0.80</p>
              <p style={{ margin: 0, color: "var(--st-ink-45)" }}>○ 3 rates still DEFAULT — shown, not hidden</p>
            </div>
          }
        />
      </section>

      {/* CTA */}
      <section style={{ padding: "90px 48px 110px", textAlign: "center" }}>
        <DisplayHeading as="h2" size="clamp(32px, 3.8vw, 52px)" style={{ lineHeight: 1.06, letterSpacing: "-0.028em" }}>
          Same number. Every lens. No versions of the truth.
        </DisplayHeading>
        <div style={{ marginTop: 36, display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
          <Link href={PILOT_HREF} className="st-pill st-pill-solid" style={{ padding: "14px 32px", fontSize: 15 }}>
            Request a pilot
          </Link>
          <Link href="/platform" className="st-pill st-pill-ghost" style={{ padding: "14px 32px", fontSize: 15 }}>
            Explore the platform
          </Link>
        </div>
      </section>
    </SiteShell>
  );
}
