import type { Metadata } from "next";
import Link from "next/link";
// Import directly from the foundation sub-modules (both are "use client") rather
// than the "@/components/site" barrel: the barrel also re-exports scroll-acts.ts,
// which uses React hooks without a "use client" directive, so pulling the barrel
// into this Server Component would fail the build. Importing the two client
// modules I need keeps this page a static Server Component (metadata + prerender).
// See sharedChangeRequests: scroll-acts.ts should carry "use client" so the
// barrel is safe to import from server components too.
import { SiteShell } from "@/components/site/site-shell";
import {
  Eyebrow,
  DisplayHeading,
  Panel,
  ScenarioChip,
  IllustrativeTag,
  HonestyBand,
} from "@/components/site/evidence";

/**
 * /platform — "The governed decision layer for everything you make."
 *
 * Faithful production port of handoff_cadverify_2026-07-04/site/Platform.dc.html
 * (dark-theater register). Document page: SiteShell (sticky nav + full footer),
 * no WebGL. Copy is verbatim from the canonical design.
 *
 * HONESTY (last-line corrections vs. the design file — see PR summary):
 *  - The copilot "ENGINE OUTPUT" figure ($8.01) is NOT the real fixture, so the
 *    number wears an [illustrative] tag. The real fixture is $14.14.
 *  - The batch card's invented counts (412 / 398 / 11 / 3) are marked
 *    ILLUSTRATIVE DATA — they were unlabeled invented figures in the design.
 *  - The moats sample numbers stay covered by the design's shared "sample figures
 *    illustrative" caption; the portfolio board already wears ILLUSTRATIVE DATA.
 * Only the real fixture ($14.14 · band ±40% n=0 · crossover 1,962 · 1 sidewall
 * <1.0°) is presented as computed engine output.
 */

export const metadata: Metadata = {
  title: "Platform — ProofShape",
  description:
    "One deterministic verification engine underneath; every surface above it renders the same auditable record. From a single part to a million-part legacy catalog, nothing on screen is generated — only computed, sourced, and reconciled.",
};

// ── shared inline style helpers (token-colored) ──────────────────────────────
const actLabel: React.CSSProperties = {
  margin: 0,
  display: "flex",
  alignItems: "center",
  gap: 10,
  fontFamily: "var(--st-font-mono)",
  fontSize: 11,
  letterSpacing: "0.18em",
  color: "var(--st-ink-40)",
};
const moatLabel: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--st-font-mono)",
  fontSize: 10.5,
  letterSpacing: "0.16em",
  color: "var(--st-ink-40)",
};
const monoEvidence: React.CSSProperties = {
  margin: "14px 0 0",
  fontFamily: "var(--st-font-mono)",
  fontSize: 11,
  lineHeight: 1.8,
  color: "var(--st-ink-45)",
};

export default function PlatformPage() {
  return (
    <SiteShell>
      {/* ── hero ─────────────────────────────────────────────────────────── */}
      <section
        data-screen-label="Platform hero"
        className="st-platform-wrap st-platform-hero"
      >
        <Eyebrow>Platform</Eyebrow>
        <DisplayHeading
          as="h1"
          size="clamp(44px, 5.2vw, 72px)"
          style={{ marginTop: 24, maxWidth: 820 }}
        >
          {"The governed decision layer for everything you make."}
        </DisplayHeading>
        <p
          style={{
            margin: "26px 0 0",
            maxWidth: 640,
            fontSize: 18,
            lineHeight: 1.65,
            fontWeight: 300,
            color: "var(--st-ink-60)",
          }}
        >
          {
            "One deterministic verification engine underneath; every surface above it renders the same auditable record. From a single part to a million-part legacy catalog, nothing on screen is generated — only computed, sourced, and reconciled."
          }
        </p>
      </section>

      {/* ── the moats (MUST-KEEP) ────────────────────────────────────────── */}
      <section
        data-screen-label="The moats"
        className="st-platform-wrap st-platform-section"
      >
        <Eyebrow>What nobody else answers</Eyebrow>
        <div className="st-platform-moat-grid">
          {/* moat 1 — your machines */}
          <Panel className="st-platform-panel-moat">
            <p style={moatLabel}>YOUR MACHINES, BY NAME</p>
            <DisplayHeading
              as="h3"
              size="22px"
              style={{ marginTop: 12, lineHeight: 1.2, letterSpacing: "-0.018em" }}
            >
              {'"Yes — on your M2 Pro."'}
            </DisplayHeading>
            <p style={moatBody}>
              {
                "Verdicts are computed against your declared shop floor — envelope, materials, rate, throughput per machine. Owned means marginal cost; missing means an acquisition consideration, stated as one."
              }
            </p>
            <p style={monoEvidence}>
              {"✓ fits M2 Pro · 380×284×380"}
              <br />
              <span style={{ color: "var(--st-conditional)" }}>
                {"✗ IM not owned → $7,800 consideration"}
              </span>
            </p>
          </Panel>

          {/* moat 2 — the environment gate */}
          <Panel className="st-platform-panel-moat">
            <p style={moatLabel}>THE ENVIRONMENT GATE</p>
            <DisplayHeading
              as="h3"
              size="22px"
              style={{ marginTop: 12, lineHeight: 1.2, letterSpacing: "-0.018em" }}
            >
              {"Materials that can't survive are struck, with reasons."}
            </DisplayHeading>
            <p style={moatBody}>
              {
                "Declare the part's world — pressure, temperature, sour service — and the material set filters visibly, never silently."
              }
            </p>
            <p style={monoEvidence}>
              <span style={{ textDecoration: "line-through", color: "var(--st-ink-30)" }}>
                {"Al 6061-T6"}
              </span>{" "}
              <span style={{ color: "var(--st-fail)" }}>{"fails NACE MR0175"}</span>
              <br />
              <span style={{ textDecoration: "line-through", color: "var(--st-ink-30)" }}>
                {"PP"}
              </span>{" "}
              <span style={{ color: "var(--st-fail)" }}>{"HDT < 120 °C"}</span>
              {" · "}
              <span style={{ color: "var(--st-pass)" }}>{"316L · 17-4PH pass"}</span>
            </p>
          </Panel>

          {/* moat 3 — triage at scale */}
          <Panel className="st-platform-panel-moat">
            <p style={moatLabel}>TRIAGE AT SCALE</p>
            <DisplayHeading
              as="h3"
              size="22px"
              style={{ marginTop: 12, lineHeight: 1.2, letterSpacing: "-0.018em" }}
            >
              {"A legacy catalog collapses into honest buckets."}
            </DisplayHeading>
            <p style={moatBody}>
              {
                "Thousands to millions of parts, each walked through the same verification: makeable in-house · outside · needs new capability · not makeable — every count openable to its verdicts."
              }
            </p>
            <p style={monoEvidence}>
              {"268 in-house · 97 outside · "}
              <span style={{ color: "var(--st-conditional)" }}>{"36 capability"}</span>
              {" · "}
              <span style={{ color: "var(--st-fail)" }}>{"11 not makeable"}</span>
            </p>
          </Panel>
        </div>
        <p
          style={{
            margin: "16px 0 0",
            textAlign: "center",
            fontFamily: "var(--st-font-mono)",
            fontSize: 10.5,
            color: "var(--st-ink-35)",
          }}
        >
          {
            "sample figures illustrative — the mechanics are the product · the surfaces below render these three gates"
          }
        </p>
      </section>

      {/* ── capabilities ─────────────────────────────────────────────────── */}
      <section
        className="st-platform-wrap st-platform-section st-platform-capabilities"
      >
        {/* 01 — decision workspace scenario */}
        <Panel
          data-screen-label="Copilot"
          className="st-platform-panel-lg st-platform-split"
          style={{
            borderRadius: 18,
            alignItems: "center",
          }}
        >
          <div>
            <p className="st-platform-act-label" style={actLabel}>
              {"01 · THE DECISION WORKSPACE"} <ScenarioChip />
            </p>
            <DisplayHeading
              as="h2"
              size="clamp(26px, 2.7vw, 36px)"
              style={{ marginTop: 14, lineHeight: 1.12, letterSpacing: "-0.022em" }}
            >
              {"A copilot that cannot hallucinate a number."}
            </DisplayHeading>
            <p style={cardBody}>
              {
                'Ask in plain language — "should we tool up for 5,000 units?" — and the answer arrives as a decision artifact: should-cost with its band, the crossover chart, DFM findings, and a provenance chip on every driver. The language model writes the sentences. The engine writes the numbers. That boundary is architectural, not a policy.'
              }
            </p>
            <p
              style={{
                margin: "16px 0 0",
                fontFamily: "var(--st-font-mono)",
                fontSize: 11.5,
                color: "var(--st-ink-40)",
              }}
            >
              {"every artifact carries its engine run id, shop binding, and timestamp"}
            </p>
          </div>
          <Panel well className="st-platform-panel-inset">
            <p
              style={{
                margin: 0,
                fontSize: 13.5,
                fontWeight: 300,
                color: "var(--st-ink-70)",
                borderBottom: "1px solid var(--st-line-soft)",
                paddingBottom: 12,
              }}
            >
              {'"Procurement wants 5,000 units next year. Keep printing, or tool up?"'}
            </p>
            <p
              style={{
                margin: "14px 0 0",
                fontFamily: "var(--st-font-mono)",
                fontSize: 10.5,
                letterSpacing: "0.12em",
                color: "var(--st-ink-40)",
              }}
            >
              {"ENGINE OUTPUT — COMPUTED, NOT GENERATED"}
            </p>
            <div style={{ marginTop: 12, display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
              <span
                className="st-readout"
                style={{ fontSize: 32, fontWeight: 200, letterSpacing: "-0.03em" }}
              >
                $8.01
              </span>
              {/* honesty: fabricated scenario figure — not the real fixture */}
              <IllustrativeTag />
              <span
                style={{
                  fontFamily: "var(--st-font-mono)",
                  fontSize: 11,
                  color: "var(--st-conditional)",
                }}
              >
                {"CONDITIONAL — 1 sidewall < 1.0° draft"}
              </span>
            </div>
            {/* gold (conditional) hatch — echoes the verdict, illustrative */}
            <div
              style={{
                marginTop: 12,
                position: "relative",
                height: 5,
                borderRadius: 3,
                background: "rgba(245,245,247,0.08)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  backgroundImage:
                    "repeating-linear-gradient(135deg, rgba(217,168,86,0.5) 0 2px, transparent 2px 6px)",
                }}
              />
            </div>
            <p
              style={{
                margin: "9px 0 0",
                fontFamily: "var(--st-font-mono)",
                fontSize: 10.5,
                color: "var(--st-ink-40)",
              }}
            >
              {"±60% · assumption-based · n=0 · crossover 1,962 units"}
            </p>
          </Panel>
        </Panel>

        {/* 02 + 03 — part hero + context */}
        <div className="st-platform-pair-grid">
          <Panel data-screen-label="Part stage" className="st-platform-panel-md" style={{ borderRadius: 18 }}>
            <p className="st-platform-act-label" style={{ ...actLabel, display: "block" }}>{"02 · THE PART, AS HERO OBJECT"}</p>
            <DisplayHeading
              as="h2"
              size="26px"
              style={{ marginTop: 14, lineHeight: 1.15, letterSpacing: "-0.02em" }}
            >
              {"Geometry is the interface."}
            </DisplayHeading>
            <p style={cardBodySm}>
              {
                "Every part lives on a lit 3D stage — X-ray into the driver stack, highlight the exact faces a DFM blocker points at, section it. Every list in the product carries real rendered thumbnails, because a cost without its geometry is just a rumor."
              }
            </p>
            {/* geometry is the ONE measured tier — filled ● MEASURED is honest here */}
            <p
              style={{
                margin: "18px 0 0",
                fontFamily: "var(--st-font-mono)",
                fontSize: 11.5,
                color: "var(--st-prov-measured)",
              }}
            >
              {"● MEASURED — 423 faces · watertight · Ø21 × 21.5 mm"}
            </p>
          </Panel>

          <Panel data-screen-label="Context" className="st-platform-panel-md" style={{ borderRadius: 18 }}>
            <p className="st-platform-act-label" style={{ ...actLabel, display: "block" }}>{"03 · CONTEXT, EARNED"}</p>
            <DisplayHeading
              as="h2"
              size="26px"
              style={{ marginTop: 14, lineHeight: 1.15, letterSpacing: "-0.02em" }}
            >
              {"Every part knows where it lives."}
            </DisplayHeading>
            <p style={cardBodySm}>
              {
                "With assembly data, the camera pulls back and the part seats into its housing — one unit cost becomes program exposure. Context you declared yourself is shown as exactly that, tagged USER. And a part with no home says so, honestly."
              }
            </p>
            <p
              style={{
                margin: "18px 0 0",
                fontFamily: "var(--st-font-mono)",
                fontSize: 11.5,
                color: "var(--st-ink-45)",
              }}
            >
              {"program → assembly → part · "}
              <span style={{ color: "var(--st-ink)" }}>
                {"exposure = unit cost × your volume, computed"}
              </span>
            </p>
          </Panel>
        </div>

        {/* 04 — portfolio cost-down board scenario */}
        <Panel data-screen-label="Portfolio" className="st-platform-panel-lg" style={{ borderRadius: 18 }}>
          <div
            className="st-platform-split-wide"
            style={{
              alignItems: "center",
            }}
          >
            <div>
              <p className="st-platform-act-label" style={actLabel}>
                {"04 · THE PORTFOLIO COST-DOWN BOARD"} <ScenarioChip />
              </p>
              <DisplayHeading
                as="h2"
                size="clamp(26px, 2.7vw, 36px)"
                style={{ marginTop: 14, lineHeight: 1.12, letterSpacing: "-0.022em" }}
              >
                {"Where the money is, ranked by the engine."}
              </DisplayHeading>
              <p style={cardBody}>
                {
                  "Every costed part in the org, clustered by program and ranked by engine-computed savings against what you're paying today. Validated savings read solid; assumption-based stay hatched; and where there's no paid price on file, the number is withheld — never extrapolated to look complete."
                }
              </p>
            </div>
            <div
              className="st-platform-portfolio-table"
              style={{
                border: "1px solid var(--st-line-09)",
                borderRadius: 12,
                background: "var(--st-panel-inset)",
                overflow: "hidden",
                fontFamily: "var(--st-font-mono)",
                fontSize: 12,
              }}
            >
              <div className="st-platform-portfolio-row st-platform-portfolio-head" style={{ borderBottom: "1px solid var(--st-line-soft)", color: "var(--st-ink-35)", fontSize: 10, letterSpacing: "0.1em" }}>
                <span>ILLUSTRATIVE DATA</span>
                <span>PAYING</span>
                <span>SHOULD</span>
                <span style={{ textAlign: "right" }}>SAVINGS</span>
              </div>
              <div className="st-platform-portfolio-row" style={{ borderBottom: "1px solid rgba(245,245,247,0.05)" }}>
                <span style={{ color: "var(--st-ink-70)" }}>Bearing flange</span>
                <span data-label="Paying" style={{ color: "var(--st-ink-55)" }}>$41.80</span>
                <span data-label="Should" style={{ color: "var(--st-ink-55)" }}>$22.60</span>
                <span data-label="Savings" style={{ textAlign: "right", color: "var(--st-ink)" }}>$1.27M</span>
              </div>
              <div className="st-platform-portfolio-row" style={{ borderBottom: "1px solid rgba(245,245,247,0.05)", background: "rgba(85,184,128,0.04)" }}>
                <span style={{ color: "var(--st-ink-70)" }}>Guide bushing</span>
                <span data-label="Paying" style={{ color: "var(--st-ink-55)" }}>$11.02</span>
                <span data-label="Should" style={{ color: "var(--st-ink-55)" }}>$6.31</span>
                <span data-label="Savings" style={{ textAlign: "right", color: "var(--st-pass)" }}>$620K ✓</span>
              </div>
              <div className="st-platform-portfolio-row">
                <span style={{ color: "var(--st-ink-70)" }}>Output shaft</span>
                <span data-label="Paying" style={{ color: "var(--st-ink-30)" }}>— none on file</span>
                <span data-label="Should" style={{ color: "var(--st-ink-55)" }}>$14.14</span>
                <span data-label="Savings" style={{ textAlign: "right", color: "var(--st-ink-30)" }}>withheld</span>
              </div>
            </div>
          </div>
        </Panel>

        {/* 05 + 06 — flywheel + honest states */}
        <div className="st-platform-pair-grid">
          <Panel data-screen-label="Flywheel" className="st-platform-panel-md" style={{ borderRadius: 18 }}>
            <p className="st-platform-act-label" style={{ ...actLabel, display: "block" }}>{"05 · THE GROUND-TRUTH FLYWHEEL"}</p>
            <DisplayHeading
              as="h2"
              size="26px"
              style={{ marginTop: 14, lineHeight: 1.15, letterSpacing: "-0.02em" }}
            >
              {"Accuracy is earned, per customer."}
            </DisplayHeading>
            <p style={cardBodySm}>
              {
                "Send back real invoice costs and the model validates against your held-out parts. The band flips from hatched to solid and states its measured residual — the only accuracy claim the product will ever make, and it's yours, not ours."
              }
            </p>
            <div style={{ marginTop: 22, display: "flex", flexDirection: "column", gap: 10 }}>
              <HonestyBand state="assumption" style={{ height: 6, borderRadius: 3 }} />
              <HonestyBand state="validated" style={{ height: 6, borderRadius: 3 }} />
              <p
                style={{
                  margin: "4px 0 0",
                  fontFamily: "var(--st-font-mono)",
                  fontSize: 10.5,
                  color: "var(--st-ink-40)",
                }}
              >
                {"±40% n=0 → "}
                <span style={{ color: "var(--st-pass)" }}>
                  {"a measured residual on your held-out parts"}
                </span>
              </p>
            </div>
          </Panel>

          <Panel data-screen-label="Honest states" className="st-platform-panel-md" style={{ borderRadius: 18 }}>
            <p className="st-platform-act-label" style={{ ...actLabel, display: "block" }}>{"06 · HONESTY AS A DESIGN SYSTEM"}</p>
            <DisplayHeading
              as="h2"
              size="26px"
              style={{ marginTop: 14, lineHeight: 1.15, letterSpacing: "-0.02em" }}
            >
              {"The states we refuse to fake."}
            </DisplayHeading>
            <p style={cardBodySm}>
              {
                "Unvalidated bands render hatched. Missing baselines render withheld, with the reason. Generic assumptions are framed, not buried. In a procurement review, the absence of false precision is the feature."
              }
            </p>
            <div
              style={{
                marginTop: 22,
                display: "flex",
                flexWrap: "wrap",
                gap: 8,
                fontFamily: "var(--st-font-mono)",
                fontSize: 11,
              }}
            >
              <span style={{ ...stateChip, border: "1px solid rgba(245,245,247,0.15)", color: "var(--st-ink-60)" }}>
                hatched band
              </span>
              <span style={{ ...stateChip, border: "1px solid rgba(85,184,128,0.3)", color: "var(--st-pass)" }}>
                earned solid
              </span>
              <span style={{ ...stateChip, border: "1px dashed rgba(245,245,247,0.2)", color: "var(--st-ink-45)" }}>
                withheld number
              </span>
              <span style={{ ...stateChip, border: "1px solid rgba(217,168,86,0.3)", color: "var(--st-conditional)" }}>
                visible DEFAULT
              </span>
            </div>
          </Panel>
        </div>
      </section>

      {/* ── scale ────────────────────────────────────────────────────────── */}
      <section
        data-screen-label="Scale"
        className="st-platform-wrap st-platform-scale"
      >
        <Panel
          className="st-platform-panel-lg st-platform-split"
          style={{
            borderRadius: 18,
            alignItems: "center",
          }}
        >
          <div>
            <p className="st-platform-act-label" style={{ ...actLabel, display: "block" }}>{"07 · BUILT FOR PORTFOLIO SCALE"}</p>
            <DisplayHeading
              as="h2"
              size="clamp(26px, 2.7vw, 36px)"
              style={{ marginTop: 14, lineHeight: 1.12, letterSpacing: "-0.022em" }}
            >
              {"One part is a demo."}
              <br />
              {"Ten thousand is a program."}
            </DisplayHeading>
            <p style={cardBody}>
              {
                "Batch upload an entire BOM, or drive the API from your PLM export — every part routed, costed and DFM-checked with the same full report, then ranked on the cost-down board. Onboarding a reshoring program's portfolio is a batch job, not a quarter."
              }
            </p>
          </div>
          <Panel
            well
            className="st-platform-panel-inset"
            style={{
              fontFamily: "var(--st-font-mono)",
              fontSize: 12,
              lineHeight: 2,
            }}
          >
            <p style={{ margin: 0, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", color: "var(--st-ink-35)", fontSize: 10, letterSpacing: "0.12em" }}>
              <span>BATCH · GEARBOX BOM · 412 PARTS</span>
              {/* honesty: invented batch counts — mark them illustrative */}
              <IllustrativeTag block />
            </p>
            <p style={{ margin: "10px 0 0", color: "var(--st-ink-60)" }}>
              {"▸ 398 costed with full driver stacks"}
            </p>
            <p style={{ margin: 0, color: "var(--st-ink-60)" }}>
              {"▸ 11 routed feasibility-only "}
              <span style={{ color: "var(--st-ink-35)" }}>{"(no calibrated process)"}</span>
            </p>
            <p style={{ margin: 0, color: "var(--st-conditional)" }}>
              {"▸ 3 geometry invalid — repair suggested, not silently skipped"}
            </p>
            <p
              style={{
                margin: "10px 0 0",
                color: "var(--st-ink-45)",
                borderTop: "1px solid var(--st-line-soft)",
                paddingTop: 10,
              }}
            >
              {"every row opens into the same glass box"}
            </p>
          </Panel>
        </Panel>
      </section>

      {/* ── positioning ──────────────────────────────────────────────────── */}
      <section
        data-screen-label="Positioning"
        className="st-platform-positioning"
        style={{
          borderTop: "1px solid var(--st-line-soft)",
          background: "var(--st-bg-raised)",
        }}
      >
        <div className="st-platform-wrap">
          <Eyebrow style={{ textAlign: "center" }}>The category</Eyebrow>
          <DisplayHeading
            as="h2"
            size="clamp(30px, 3.6vw, 48px)"
            style={{
              margin: "20px auto 0",
              maxWidth: 720,
              textAlign: "center",
              lineHeight: 1.07,
              letterSpacing: "-0.026em",
            }}
          >
            {"Both incumbents hide the model."}
            <br />
            {"For opposite reasons."}
          </DisplayHeading>
          <div
            className="st-platform-positioning-grid"
          >
            <div className="st-platform-position-card" style={posCard}>
              <p style={posLabel}>INSTANT-QUOTE MARKETPLACE</p>
              <p style={posBody}>
                {
                  "A price with nothing behind it — because the marketplace is selling its own capacity. The number is a sales position, unauditable by design, and your CAD trains their library."
                }
              </p>
            </div>
            <div className="st-platform-position-card" style={posCard}>
              <p style={posLabel}>COST-ENGINEERING SUITE</p>
              <p style={posBody}>
                {
                  "Physics-based and serious — then buried in a bill-of-process only a trained specialist can read, gated behind seats, roles, and a six-month deployment."
                }
              </p>
            </div>
            <div
              className="st-platform-position-card"
              style={{
                border: "1px solid var(--st-line-strong)",
                borderRadius: 16,
                background: "rgba(245,245,247,0.045)",
              }}
            >
              <p style={{ ...posLabel, color: "var(--st-ink)" }}>PROOFSHAPE — THE GLASS BOX</p>
              <p style={{ ...posBody, color: "var(--st-ink-70)" }}>
                {
                  "Every driver visible, sourced, and summing to the unit cost. The hero output is the decision — make-vs-buy and the crossover — and trust is demonstrated on your parts, never asserted on a slide."
                }
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────────────────── */}
      <section
        data-screen-label="Platform CTA"
        className="st-platform-cta"
        style={{ textAlign: "center" }}
      >
        <DisplayHeading
          as="h2"
          size="clamp(32px, 3.8vw, 52px)"
          style={{ lineHeight: 1.06, letterSpacing: "-0.028em" }}
        >
          {"One engine. Every decision surface."}
        </DisplayHeading>
        <div style={{ marginTop: 36, display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
          <Link href="/signup" className="st-pill st-pill-solid" style={{ padding: "14px 32px", fontSize: 15 }}>
            Cost a part
          </Link>
          <Link href="/method" className="st-pill st-pill-ghost" style={{ padding: "14px 32px", fontSize: 15 }}>
            How the number is built
          </Link>
        </div>
      </section>
    </SiteShell>
  );
}

// ── local style tokens ───────────────────────────────────────────────────────
const moatBody: React.CSSProperties = {
  margin: "12px 0 0",
  fontSize: 14,
  lineHeight: 1.65,
  fontWeight: 300,
  color: "var(--st-ink-55)",
};
const cardBody: React.CSSProperties = {
  margin: "16px 0 0",
  fontSize: 15,
  lineHeight: 1.65,
  fontWeight: 300,
  color: "var(--st-ink-55)",
};
const cardBodySm: React.CSSProperties = {
  margin: "14px 0 0",
  fontSize: 14.5,
  lineHeight: 1.65,
  fontWeight: 300,
  color: "var(--st-ink-55)",
};
const stateChip: React.CSSProperties = {
  borderRadius: 6,
  padding: "5px 10px",
};
const posCard: React.CSSProperties = {
  border: "1px solid var(--st-line-soft)",
  borderRadius: 16,
  background: "rgba(245,245,247,0.02)",
};
const posLabel: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--st-font-mono)",
  fontSize: 10.5,
  letterSpacing: "0.16em",
  color: "var(--st-ink-35)",
};
const posBody: React.CSSProperties = {
  margin: "14px 0 0",
  fontSize: 15,
  lineHeight: 1.65,
  fontWeight: 300,
  color: "var(--st-ink-55)",
};
