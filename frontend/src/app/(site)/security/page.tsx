import type { Metadata } from "next";
import Link from "next/link";
// NOTE: imported from the foundation's client-module source paths rather than
// the `@/components/site` barrel. The barrel statically re-exports
// `@/lib/site/scroll-acts` (a hook module missing "use client"), which a Server
// Component cannot pull in. This page is a Server Component so it can export
// `metadata`; site-shell.tsx and evidence.tsx are already "use client", so
// importing them directly is clean and edits no foundation file. See
// sharedChangeRequests: scroll-acts.ts (or the barrel) needs "use client".
import { SiteShell } from "@/components/site/site-shell";
import { Eyebrow, DisplayHeading, Panel } from "@/components/site/evidence";
import styles from "./security.module.css";

/**
 * /security — "Your CAD is the crown jewels. We built accordingly."
 *
 * Ported faithfully from handoff_cadverify_2026-07-04/site/Security.dc.html
 * (dark-theater register, document page). Copy is post-pivot canonical and is
 * reproduced VERBATIM.
 *
 * HONESTY (audited, no violations to fix): the compliance state is stated the
 * way we state cost — SOC 2 Type II "in progress", pen test "scheduled pre-GA ·
 * shared when it's real" (NO pen-test badge), the report available under NDA the
 * day it lands. The zero-egress / geometry-never-leaves claims are real
 * (verified in the backend's local path). The one quoted source string
 * (`0.082 hr × $52/hr × region-labor ×1 [shop: Midwest Precision CNC]`) is the
 * real fixture's labor_cost driver source — the same string carried by the
 * product prototype and the Method page — not an invented figure.
 */

export const metadata: Metadata = {
  title: "Security — ProofShape",
  description:
    "Your CAD is the crown jewels. ProofShape was designed from the first commit for CAD-as-IP and export-controlled work: geometry never leaves your environment, run it where your program requires, and every answer is defensible.",
};

const INK_62 = "rgba(245,245,247,0.62)";
const MONO = "ui-monospace, 'SF Mono', monospace";

/** A posture card: mono eyebrow label + body, with optional extra content. */
function Posture({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Panel style={{ background: "#0c0d10", padding: 30 }}>
      <p
        className="st-mono"
        style={{
          margin: 0,
          fontSize: 11,
          letterSpacing: "0.18em",
          color: "var(--st-ink-40)",
        }}
      >
        {label}
      </p>
      {children}
    </Panel>
  );
}

function PostureBody({ children }: { children: React.ReactNode }) {
  return (
    <p
      style={{
        margin: "12px 0 0",
        fontSize: 15,
        lineHeight: 1.65,
        fontWeight: 300,
        color: INK_62,
      }}
    >
      {children}
    </p>
  );
}

export default function SecurityPage() {
  return (
    <SiteShell>
      {/* hero */}
      <section style={{ maxWidth: 880, margin: "0 auto", padding: "110px 48px 80px" }}>
        <Eyebrow>Security &amp; trust</Eyebrow>
        <DisplayHeading
          as="h1"
          size="clamp(44px, 5.2vw, 72px)"
          style={{ margin: "24px 0 0" }}
        >
          Your CAD is the crown jewels.
          <br />
          We built accordingly.
        </DisplayHeading>
        <p
          style={{
            margin: "26px 0 0",
            maxWidth: 620,
            fontSize: 18,
            lineHeight: 1.65,
            fontWeight: 300,
            color: INK_62,
          }}
        >
          For an aerospace, automotive or defense program, where the model runs and
          what leaves your network matter as much as the answer. ProofShape was
          designed from the first commit for CAD-as-IP and export-controlled work.
        </p>

        {/* the light: where your data travels, and stops */}
        <div style={{ marginTop: 56, position: "relative", padding: "34px 0 10px" }}>
          <div
            style={{
              position: "relative",
              height: 2,
              background: "rgba(245,245,247,0.1)",
              borderRadius: 1,
            }}
          >
            <span aria-hidden="true" className={styles.beam} />
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              marginTop: 26,
              fontFamily: MONO,
              fontSize: 11,
              lineHeight: 1.7,
            }}
          >
            <div className={styles.node} style={{ maxWidth: 200 }}>
              <p style={{ margin: 0, color: "#6aa5d8", letterSpacing: "0.12em" }}>YOUR CAD</p>
              <p style={{ margin: "5px 0 0", color: "rgba(245,245,247,0.4)" }}>
                parsed in-process, measured — then discarded. the beam ends here for
                geometry.
              </p>
            </div>
            <div style={{ maxWidth: 200, textAlign: "center" }}>
              <p style={{ margin: 0, color: "rgba(245,245,247,0.65)", letterSpacing: "0.12em" }}>
                DERIVED RECORD
              </p>
              <p style={{ margin: "5px 0 0", color: "rgba(245,245,247,0.4)" }}>
                measurements, routing, drivers, bands — stored for history &amp;
                validation.
              </p>
            </div>
            <div style={{ maxWidth: 200, textAlign: "right" }}>
              <p style={{ margin: 0, color: "#c9834f", letterSpacing: "0.12em" }}>
                YOUR CALIBRATIONS
              </p>
              <p style={{ margin: "5px 0 0", color: "rgba(245,245,247,0.4)" }}>
                tenant-scoped, never pooled. your ground truth stays yours.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* posture */}
      <section
        style={{
          maxWidth: 880,
          margin: "0 auto",
          padding: "0 48px 60px",
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        <Posture label="GEOMETRY NEVER LEAVES YOUR ENVIRONMENT">
          <PostureBody>
            On the local path, CAD is parsed in-process and discarded — no upload to
            a marketplace, no part library trained on your designs, zero network
            egress for the geometry. The mesh exists in memory for the duration of
            the analysis and no longer.
          </PostureBody>
        </Posture>

        <Posture label="RUN IT WHERE YOUR PROGRAM REQUIRES">
          <PostureBody>
            The full stack — engine, API, frontend, Postgres — ships as a Docker
            Compose deployment you can stand up in your own VPC or on an air-gapped
            network. Designed for the ITAR / AS9100 path: an export-controlled
            program can cost parts without technical data ever crossing a boundary.
          </PostureBody>
          <div
            style={{
              marginTop: 18,
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 12,
              fontFamily: MONO,
              fontSize: 11.5,
            }}
          >
            {[
              { title: "CLOUD", body: "managed, fastest start · session auth + API keys" },
              { title: "SELF-HOSTED", body: "your VPC · docker compose up · your storage, your keys" },
              { title: "AIR-GAPPED", body: "controlled environment · zero egress · export-controlled programs" },
            ].map((c) => (
              <div
                key={c.title}
                style={{
                  border: "1px solid rgba(245,245,247,0.09)",
                  borderRadius: 8,
                  padding: "14px 16px",
                }}
              >
                <p style={{ margin: 0, color: "rgba(245,245,247,0.75)" }}>{c.title}</p>
                <p style={{ margin: "6px 0 0", color: "rgba(245,245,247,0.4)", lineHeight: 1.6 }}>
                  {c.body}
                </p>
              </div>
            ))}
          </div>
        </Posture>

        <Posture label="ENTERPRISE IDENTITY">
          <PostureBody>
            SAML SSO for enterprise deployments, alongside Google sign-in and
            magic-link email. Sessions are server-verified on every authed surface;
            API access uses scoped bearer keys shown once at creation, with per-key
            rate limits you can read from the response headers.
          </PostureBody>
        </Posture>

        <Posture label="EVERY ANSWER IS DEFENSIBLE">
          <PostureBody>
            Provenance tags and verbatim source strings on every driver mean a cost
            or quality engineer can reconstruct the number in a review — from CAD
            measurement to shop rate to line item to Σ. Auditability isn&apos;t a
            report we export; it&apos;s the shape of the data.
          </PostureBody>
          <p
            className="st-mono"
            style={{ margin: "14px 0 0", fontSize: 11.5, color: "var(--st-ink-45)" }}
          >
            &ldquo;0.082 hr × $52/hr × region-labor ×1 [shop: Midwest Precision CNC]&rdquo;
            — a real source string, attached to a real driver
          </p>
        </Posture>

        {/* where your data goes — and stops */}
        <Posture label="WHERE YOUR DATA GOES — AND STOPS">
          <div
            style={{
              marginTop: 22,
              display: "grid",
              gridTemplateColumns: "1fr 24px 1fr 24px 1fr",
              gap: 8,
              alignItems: "stretch",
            }}
          >
            <div style={{ border: "1px solid rgba(106,165,216,0.3)", borderRadius: 10, padding: "16px 18px" }}>
              <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.12em", color: "#6aa5d8" }}>
                CAD FILE
              </p>
              <p style={{ margin: "8px 0 0", fontSize: 12.5, lineHeight: 1.55, fontWeight: 300, color: "rgba(245,245,247,0.6)" }}>
                Parsed in-process, measured, then{" "}
                <span style={{ color: "#f5f5f7" }}>discarded</span>. Never persisted,
                never trained on.
              </p>
            </div>
            <span style={{ alignSelf: "center", textAlign: "center", color: "rgba(245,245,247,0.3)" }}>→</span>
            <div style={{ border: "1px solid rgba(245,245,247,0.14)", borderRadius: 10, padding: "16px 18px" }}>
              <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.12em", color: "rgba(245,245,247,0.55)" }}>
                DERIVED REPORT
              </p>
              <p style={{ margin: "8px 0 0", fontSize: 12.5, lineHeight: 1.55, fontWeight: 300, color: "rgba(245,245,247,0.6)" }}>
                Measurements, routing, drivers, bands — stored so your history and
                validations work.
              </p>
            </div>
            <span style={{ alignSelf: "center", textAlign: "center", color: "rgba(245,245,247,0.3)" }}>→</span>
            <div style={{ border: "1px solid rgba(201,131,79,0.3)", borderRadius: 10, padding: "16px 18px" }}>
              <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.12em", color: "#c9834f" }}>
                YOUR CALIBRATIONS
              </p>
              <p style={{ margin: "8px 0 0", fontSize: 12.5, lineHeight: 1.55, fontWeight: 300, color: "rgba(245,245,247,0.6)" }}>
                Shop rates and invoice ground truth stay tenant-scoped — never pooled
                across customers.
              </p>
            </div>
          </div>
        </Posture>

        {/* compliance — stated the way we state cost */}
        <Posture label="COMPLIANCE — STATED THE WAY WE STATE COST">
          <PostureBody>
            We tell you our audit state the same way we label an unvalidated band:
            plainly. SOC 2 Type II is in progress — the report is available under NDA
            the day it lands, and we won&apos;t print the badge a day earlier. DPAs
            and security questionnaires answered as part of every pilot; self-hosted
            deployments inherit your controls.
          </PostureBody>
          <div
            style={{
              marginTop: 16,
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
              fontFamily: MONO,
              fontSize: 11.5,
            }}
          >
            {[
              "SOC 2 Type II — in progress",
              "DPA — available",
              "Pen test — scheduled pre-GA · shared when it's real",
              "Self-host — your controls apply",
            ].map((chip) => (
              <span
                key={chip}
                style={{
                  border: "1px solid rgba(245,245,247,0.15)",
                  borderRadius: 6,
                  padding: "5px 10px",
                  color: "rgba(245,245,247,0.6)",
                }}
              >
                {chip}
              </span>
            ))}
          </div>
        </Posture>

        <Posture label="WHAT WE DON'T DO">
          <div
            style={{
              marginTop: 14,
              display: "flex",
              flexDirection: "column",
              gap: 10,
              fontSize: 15,
              fontWeight: 300,
              lineHeight: 1.6,
              color: INK_62,
            }}
          >
            <p style={{ margin: 0 }}>— We don&apos;t train models on your geometry.</p>
            <p style={{ margin: 0 }}>— We don&apos;t broker your parts to suppliers or resell demand.</p>
            <p style={{ margin: 0 }}>— We don&apos;t print accuracy figures we haven&apos;t measured on your parts.</p>
          </div>
        </Posture>
      </section>

      {/* CTA */}
      <section style={{ padding: "90px 48px 110px", textAlign: "center" }}>
        <DisplayHeading
          as="h2"
          size="clamp(32px, 3.8vw, 52px)"
          style={{ letterSpacing: "-0.028em", lineHeight: 1.06 }}
        >
          Bring your security team.
          <br />
          We like the hard questions.
        </DisplayHeading>
        <div style={{ marginTop: 36, display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
          <Link href="/company#pilot" className="st-pill st-pill-solid" style={{ padding: "14px 32px", fontSize: 15 }}>
            Talk to us
          </Link>
          <Link href="/developers" className="st-pill st-pill-ghost" style={{ padding: "14px 32px", fontSize: 15 }}>
            Self-host it today
          </Link>
        </div>
      </section>
    </SiteShell>
  );
}
