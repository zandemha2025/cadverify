import type { Metadata } from "next";
import Link from "next/link";
// Imported from the foundation's "use client" source modules directly rather
// than the `@/components/site` barrel: the barrel re-exports scroll-acts.ts
// (a hooks module with no "use client" directive), which breaks any Server
// Component that touches it. This page is a static Server Component (so it can
// export `metadata`), so it consumes the two client primitives it needs from
// their own modules. See sharedChangeRequests re: adding "use client" to
// scroll-acts.ts so the barrel is server-safe.
import { SiteShell } from "@/components/site/site-shell";
import { IllustrativeTag, ScenarioChip } from "@/components/site/evidence";

/**
 * /teams/in-house-manufacturing — "For In-House Manufacturing · MRO".
 *
 * Faithful production port of
 * `handoff_cadverify_2026-07-04/site/For In-House Manufacturing.dc.html`.
 * Document page (no WebGL — ROUTE-PLAN), wrapped in the shared <SiteShell>
 * (document nav lit on /teams/* + footer tagline). Copy is VERBATIM from the
 * design (post-pivot canonical). The heroIn reveal maps to the foundation's
 * `st-heroIn` keyframe.
 *
 * HONESTY FIXES vs the design file (recorded in the branch summary):
 *  - J4 triage buckets (268/97/36/11) + capability ranking (22 of 36) are
 *    FABRICATED example figures and, per the prose, imply a triage of the
 *    "ten thousand legacy parts" — yet they sum to 412 (the canonical
 *    illustrative gearbox-BOM batch, cf. Platform.dc.html / Product Triage).
 *    The design left them unlabeled. Here they carry <IllustrativeTag/>,
 *    matching the product's "[illustrative rows] / [illustrative ranking]".
 *  - Triage-at-scale carries a scenario marker (as on Platform.dc.html "THE
 *    DECISION WORKSPACE" and For Sourcing's portfolio board) so illustrative
 *    batch figures are not presented as measured customer output.
 * Everything else is the real fixture (object.stl · Ø21.16 × 21.43 ·
 * $30/$95 rates · $14.14 · 0.068 hr · lead 5.6–10.4 d) or the honesty
 * principle itself (withheld ≠ zero; hatched → solid on measured jobs).
 */

export const metadata: Metadata = {
  title: "CadVerify — For In-house manufacturing & MRO",
  description:
    'A captive shop inside an operator: ten thousand legacy parts, vanished suppliers, and a floor full of un-indexed capability. "Can WE make this — on OUR machines?" — a verdict per part, computed against your own machines.',
};

/* shared inline atoms (page-local; token vars keep it in the theater register) */
const NUMERAL: React.CSSProperties = {
  fontSize: 56,
  fontWeight: 200,
  color: "rgba(245,245,247,0.16)",
  lineHeight: 1,
  textAlign: "right",
  fontVariantNumeric: "tabular-nums",
};
const H2: React.CSSProperties = {
  margin: 0,
  fontSize: 30,
  fontWeight: 300,
  letterSpacing: "-0.02em",
};
const BODY: React.CSSProperties = {
  margin: "14px 0 0",
  fontSize: 15.5,
  lineHeight: 1.65,
  fontWeight: 300,
  color: "rgba(245,245,247,0.58)",
};
const CARD: React.CSSProperties = {
  marginTop: 20,
  border: "1px solid var(--st-line)",
  borderRadius: "var(--st-radius-inner)",
  background: "var(--st-panel-2)",
  padding: "20px 22px",
  fontFamily: "var(--st-font-mono)",
  fontSize: 12,
  lineHeight: 1.9,
};
const EM: React.CSSProperties = { fontStyle: "normal", color: "rgba(245,245,247,0.85)" };
const heroIn = (delay: string): React.CSSProperties => ({
  animation: `st-heroIn 1.2s var(--st-ease-cine) ${delay} both`,
});

function Act({
  n,
  children,
}: {
  n: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 36 }}>
      <span style={NUMERAL}>{n}</span>
      <div>{children}</div>
    </div>
  );
}

export default function InHouseManufacturingPage() {
  return (
    <SiteShell>
      {/* hero */}
      <section style={{ maxWidth: 880, margin: "0 auto", padding: "110px 48px 80px" }}>
        <p style={{ margin: 0, ...heroIn("0.2s") }}>
          <Link
            href="/teams"
            style={{
              fontSize: 13,
              letterSpacing: "0.32em",
              textTransform: "uppercase",
              color: "var(--st-ink-45)",
              textDecoration: "none",
            }}
          >
            Teams / In-house manufacturing · MRO
          </Link>
        </p>
        <h1
          className="st-display"
          style={{
            margin: "24px 0 0",
            fontSize: "clamp(44px, 5.2vw, 72px)",
            lineHeight: 1.03,
            fontWeight: 300,
            letterSpacing: "-0.03em",
            ...heroIn("0.4s"),
          }}
        >
          &ldquo;Can WE make this &mdash;
          <br />
          on OUR machines?&rdquo;
        </h1>
        <p
          style={{
            margin: "26px 0 0",
            maxWidth: 620,
            fontSize: 18,
            lineHeight: 1.65,
            fontWeight: 300,
            color: "rgba(245,245,247,0.62)",
            ...heroIn("0.6s"),
          }}
        >
          You run a captive shop inside an operator. Ten thousand legacy parts, suppliers that
          vanish, lead times that stop production &mdash; and a floor full of capability nobody has
          indexed. This is the journey from that backlog to a verdict per part, computed against your
          own machines.
        </p>
      </section>

      {/* journey */}
      <section
        style={{
          maxWidth: 880,
          margin: "0 auto",
          padding: "0 48px 40px",
          display: "flex",
          flexDirection: "column",
          gap: 84,
        }}
      >
        {/* 01 */}
        <Act n="01">
          <h2 style={H2}>A supplier goes dark. Production doesn&rsquo;t wait.</h2>
          <p style={BODY}>
            The obsolete-parts problem: a pump shaft last bought in 2019, the vendor gone, the drawing
            in a PLM export. Today the question &ldquo;could our own shop make it?&rdquo; takes a week
            of walking the floor and asking. It should take twelve seconds.
          </p>
          <div style={CARD}>
            <p style={{ margin: 0, color: "var(--st-ink-35)", fontSize: 10, letterSpacing: "0.12em" }}>
              OBJECT.STL · DROPPED AT 09:41
            </p>
            <p style={{ margin: "8px 0 0", color: "rgba(245,245,247,0.65)" }}>
              measured Ø21.16 × 21.43 · watertight ✓ · routed rotational → cnc_turning · 412 ms
            </p>
          </div>
        </Act>

        {/* 02 */}
        <Act n="02">
          <h2 style={H2}>Declare the floor once. It becomes the denominator.</h2>
          <p style={BODY}>
            Every machine you own &mdash; type, build envelope, materials, loaded rate, throughput
            &mdash; declared in an afternoon or imported as CSV. From then on, every verdict in the
            org is computed against <em style={EM}>your</em> capability, not a generic shop&rsquo;s.
          </p>
          <div style={CARD}>
            <p style={{ margin: 0, color: "var(--st-prov-shop)" }}>
              ● M2 Pro (MJF) $30/hr · ST-20 mill-turn $95/hr · VF-2 · UMC-500 — OWNED → MARGINAL
            </p>
            <p style={{ margin: 0, color: "var(--st-ink-45)" }}>
              ○ gaps stay visible defaults — never silently filled
            </p>
          </div>
        </Act>

        {/* 03 */}
        <Act n="03">
          <h2 style={H2}>The verdict answers with a machine name.</h2>
          <p style={BODY}>
            Not &ldquo;makeable&rdquo; &mdash;{" "}
            <em style={EM}>
              &ldquo;yes, on your M2 Pro, in PP, 0.068 machine-hours and 4.2 grams per part, $14.14
              marginal at your rates.&rdquo;
            </em>{" "}
            And when the answer is no, it says why: exceeds every envelope you own, or the declared
            world (sour service, 120 °C) strikes the material &mdash; with the NACE or HDT reason
            named.
          </p>
          <div style={CARD}>
            <p style={{ margin: 0, color: "var(--st-pass)" }}>
              ✓ MAKEABLE IN-HOUSE — M2 Pro · $14.14/unit marginal · lead 5.6–10.4 days
            </p>
            <p style={{ margin: "6px 0 0", color: "var(--st-ink-45)" }}>
              vs last paid price on file: none —{" "}
              <span style={{ color: "rgba(245,245,247,0.65)" }}>withheld, not invented</span>
            </p>
          </div>
        </Act>

        {/* 04 — triage at scale scenario; illustrative figures */}
        <Act n="04">
          <h2 style={{ ...H2, display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
            Then run the whole legacy catalog.
            <ScenarioChip style={{ transform: "translateY(-2px)" }} />
          </h2>
          <p style={BODY}>
            Triage at scale: the ten-thousand-part backlog collapses into honest buckets &mdash;
            makeable in-house, makeable outside, needs new capability, not makeable as drawn. The
            capability bucket ranks the acquisition that unlocks the most parts, so the capex case
            writes itself from the geometry up.
          </p>
          <div style={CARD}>
            <p
              style={{
                margin: 0,
                display: "flex",
                alignItems: "baseline",
                gap: 10,
                flexWrap: "wrap",
                color: "rgba(245,245,247,0.65)",
              }}
            >
              <span>
                268 in-house · 97 outside · <span style={{ color: "var(--st-conditional)" }}>36 need capability</span> ·{" "}
                <span style={{ color: "var(--st-fail)" }}>11 not makeable</span>
              </span>
              <IllustrativeTag />
            </p>
            <p
              style={{
                margin: "6px 0 0",
                display: "flex",
                alignItems: "baseline",
                gap: 10,
                flexWrap: "wrap",
                color: "var(--st-conditional)",
              }}
            >
              <span>one IM cell unlocks 22 of 36 — the ranked consideration, not a hunch</span>
              <IllustrativeTag />
            </p>
          </div>
        </Act>

        {/* 05 */}
        <Act n="05">
          <h2 style={H2}>Your floor sends reality back.</h2>
          <p style={BODY}>
            You own the machines, so you own the ground truth: real machine-hours flow back from the
            jobs you run, and the engine&rsquo;s bands flip from hatched assumption to measured
            residual &mdash; on your parts, your floor. A captive shop is the flywheel&rsquo;s best
            customer.
          </p>
          <div
            style={{
              ...CARD,
              border: "1px solid rgba(85,184,128,0.25)",
              background: "rgba(85,184,128,0.04)",
            }}
          >
            <p style={{ margin: 0, color: "var(--st-pass)" }}>
              actual hours returned → bands flip hatched → solid (measured)
            </p>
            <p style={{ margin: 0, color: "var(--st-ink-45)" }}>
              &ldquo;validated&rdquo; will only ever mean measured on your jobs
            </p>
          </div>
        </Act>
      </section>

      {/* CTA */}
      <section style={{ padding: "100px 48px 110px", textAlign: "center" }}>
        <h2
          className="st-display-2"
          style={{
            margin: 0,
            fontSize: "clamp(32px, 3.8vw, 52px)",
            lineHeight: 1.06,
            fontWeight: 300,
            letterSpacing: "-0.028em",
          }}
        >
          Bring the part your supplier abandoned.
          <br />
          And your machine list.
        </h2>
        <div style={{ marginTop: 36, display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
          <Link href="/company#pilot" className="st-pill st-pill-solid" style={{ padding: "14px 32px", fontSize: 15 }}>
            Request a pilot
          </Link>
          <Link href="/teams" className="st-pill st-pill-ghost" style={{ padding: "14px 32px", fontSize: 15 }}>
            All teams
          </Link>
        </div>
      </section>
    </SiteShell>
  );
}
