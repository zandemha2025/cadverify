import type { Metadata } from "next";
import type { CSSProperties } from "react";
import Link from "next/link";
import { backendOrigin } from "@/lib/api-base";
// Import SiteShell from its module path rather than the `@/components/site`
// barrel: the barrel re-exports `lib/site/scroll-acts` (React hooks, no
// "use client" directive), which would pull that client-only module into this
// server component's graph and fail the build. site-shell.tsx is itself
// "use client", so importing it directly keeps this page a static server
// component. See sharedChangeRequests — scroll-acts.ts should carry "use client"
// so the barrel is server-importable per the route plan.
import { SiteShell } from "@/components/site/site-shell";
import styles from "./developers.module.css";

/**
 * Public quickstart. The recorded example keeps its original values and
 * provenance, but only shows selected response fields. Cost fields belong to
 * estimates[]; routing describes the report. The deployment origin is runtime
 * configuration, and /scalar opens the actual backend OpenAPI console.
 */

export const metadata: Metadata = {
  title: "Developers — ProofShape",
  description:
    "The engine is an API. Send an STL, STEP/STP or IGES/IGS file, get back the full auditable report — routing, DFM, drivers with provenance, confidence, decision. Or self-host the whole stack with Docker Compose.",
};

// The API hostname is supplied when the container starts. Keeping this page
// dynamic prevents a staging hostname from being frozen into the promoted
// production image at build time.
export const dynamic = "force-dynamic";

// JSON syntax hues (design values; tokens where the foundation defines them).
const STR = "#9fc0a8"; // string literal green (no token in the register)
const SHOP = "var(--st-prov-shop)"; // #c9834f — bound rate provenance
const COND = "var(--st-conditional)"; // #d9a856 — validated:false
const PASS = "var(--st-pass)"; // #55b880 — 200 status / Σ check

// A pair of non-breaking spaces = one indent level (matches the design's &nbsp;).
const I1 = "  ";
const I2 = "    ";

export default function DevelopersPage() {
  const apiOrigin = backendOrigin();
  return (
    <SiteShell>
      {/* ── hero ─────────────────────────────────────────────────────────── */}
      <section style={{ maxWidth: 880, margin: "0 auto", padding: "110px 48px 70px" }}>
        <p className="st-eyebrow">Developers</p>
        <h1
          className="st-display"
          style={{ margin: "24px 0 0", fontSize: "clamp(44px, 5.2vw, 72px)" }}
        >
          The engine is an API.
          <br />
          One request, the whole report.
        </h1>
        <p
          style={{
            margin: "26px 0 0",
            maxWidth: 620,
            fontSize: 18,
            lineHeight: 1.65,
            fontWeight: 300,
            color: "rgba(245,245,247,0.62)",
          }}
        >
          Send an STL, STEP/STP or IGES/IGS file, get back the full auditable report — routing, DFM, drivers with
          provenance, confidence, decision. Or self-host the entire stack with Docker Compose.
        </p>

        {/* the record, arriving */}
        <div
          style={{
            marginTop: 52,
            border: "1px solid rgba(245,245,247,0.12)",
            borderRadius: 14,
            background: "#08090b",
            overflow: "hidden",
            boxShadow: "0 30px 80px -30px rgba(0,0,0,0.8)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 16,
              padding: "12px 22px",
              borderBottom: "1px solid rgba(245,245,247,0.07)",
            }}
          >
            <span
              className="st-mono"
              style={{ fontSize: 11, letterSpacing: "0.14em", color: "var(--st-ink-40)" }}
            >
              POST /api/v1/validate/cost · selected response fields
            </span>
            <span className="st-mono" style={{ fontSize: 11, color: PASS, whiteSpace: "nowrap" }}>
              Example · 200
            </span>
          </div>
          <div
            className="st-mono"
            style={{ padding: "22px 24px", fontSize: 13, lineHeight: 1.85 }}
          >
            <p className={styles.jsonLine} style={{ color: "rgba(245,245,247,0.6)", animationDelay: "300ms" }}>
              {"{"}
            </p>
            <p className={styles.jsonLine} style={{ color: "rgba(245,245,247,0.6)", animationDelay: "550ms" }}>
              {I1}&quot;routing&quot;: {"{"} &quot;recommended_process&quot;: <span style={{ color: STR }}>&quot;mjf&quot;</span>, &quot;confidence&quot;: 0.4 {"}"},
            </p>
            <p className={styles.jsonLine} style={{ color: "rgba(245,245,247,0.6)", animationDelay: "800ms" }}>
              {I1}&quot;estimates&quot;: [{"{"}
            </p>
            <p className={styles.jsonLine} style={{ color: "rgba(245,245,247,0.6)", animationDelay: "900ms" }}>
              {I2}&quot;unit_cost_usd&quot;: <span style={{ color: "#f5f5f7", fontWeight: 600 }}>14.14</span>,
            </p>
            <p className={styles.jsonLine} style={{ color: "rgba(245,245,247,0.6)", animationDelay: "1050ms" }}>
              {I2}&quot;drivers&quot;: [ {"{"} &quot;name&quot;: <span style={{ color: STR }}>&quot;labor_cost&quot;</span>, &quot;value&quot;: 6.39, &quot;provenance&quot;: <span style={{ color: SHOP }}>&quot;SHOP&quot;</span>, &quot;source&quot;: <span style={{ color: STR }}>&quot;(0.08 + 0.5/223) hr × $52/hr × 1.3 markup × 1.15 overhead&quot;</span> {"}"}, <span style={{ color: "rgba(245,245,247,0.35)" }}>…4 more</span> ],
            </p>
            <p className={styles.jsonLine} style={{ color: "rgba(245,245,247,0.6)", animationDelay: "1300ms" }}>
              {I2}&quot;confidence&quot;: {"{"} &quot;low_usd&quot;: 8.49, &quot;high_usd&quot;: 19.8, &quot;validated&quot;: <span style={{ color: COND }}>false</span>, &quot;n_samples&quot;: 0 {"}"},
            </p>
            <p className={styles.jsonLine} style={{ color: "rgba(245,245,247,0.6)", animationDelay: "1550ms" }}>
              {I2}&quot;line_items&quot;: {"{"} &quot;labor&quot;: 6.39, &quot;amortized_fixed&quot;: 3.89, &quot;machine&quot;: 3.82, &quot;material&quot;: 0.04 {"}"}{I1}
              <span style={{ color: PASS }}>{"// Σ = 14.14 ✓"}</span>
            </p>
            <p className={styles.jsonLine} style={{ color: "rgba(245,245,247,0.6)", animationDelay: "1800ms" }}>
              {I1}{"}"}]
            </p>
            <p className={styles.jsonLine} style={{ color: "rgba(245,245,247,0.6)", animationDelay: "1800ms" }}>
              {"}"}
              <span aria-hidden="true" className={styles.caret}>
                ▌
              </span>
            </p>
          </div>
        </div>
        <p
          className="st-mono"
          style={{ margin: "14px 0 0", fontSize: 11, color: "rgba(245,245,247,0.35)", textAlign: "right" }}
        >
          Selected fields from a recorded example. Prices depend on the part, quantity and rates.
        </p>
      </section>

      {/* ── quickstart ───────────────────────────────────────────────────── */}
      <section
        style={{
          maxWidth: 880,
          margin: "0 auto",
          padding: "0 48px 60px",
          display: "flex",
          flexDirection: "column",
          gap: 44,
        }}
      >
        {/* 1 — curl */}
        <div>
          <h2 style={sectionH2}>1 — Validate a part with curl</h2>
          <div style={codeBlock}>
            <p style={{ margin: 0, color: "rgba(245,245,247,0.35)" }}># should-cost with routing and DFM evidence for each estimate</p>
            <p style={codeLine}>curl -X POST {apiOrigin}/api/v1/validate/cost \</p>
            <p style={codeLine}>
              {I1}-H <span style={{ color: STR }}>&quot;Authorization: Bearer cv_live_YOUR_KEY&quot;</span> \
            </p>
            <p style={codeLine}>
              {I1}-F <span style={{ color: STR }}>&quot;file=@part.stl&quot;</span> \
            </p>
            <p style={codeLine}>
              {I1}-F <span style={{ color: STR }}>&quot;qty=50,5000&quot;</span>
            </p>
          </div>
          <div style={responseBlock}>
            <p style={{ margin: 0, color: "rgba(245,245,247,0.35)" }}>
              {"// Selected fields from an example response. Read estimates[] by process, material and quantity. Use /validate separately for the full DFM report."}
            </p>
            <p style={respLine}>{"{"}</p>
            <p style={respLine}>
              {I1}&quot;routing&quot;: {"{"} &quot;recommended_process&quot;: <span style={{ color: STR }}>&quot;mjf&quot;</span>, &quot;confidence&quot;: 0.4 {"}"},
            </p>
            <p style={respLine}>{I1}&quot;estimates&quot;: [{"{"}</p>
            <p style={respLine}>
              {I2}&quot;unit_cost_usd&quot;: <span style={{ color: "#f5f5f7" }}>14.14</span>,
            </p>
            <p style={respLine}>
              {I2}&quot;confidence&quot;: {"{"} &quot;low_usd&quot;: 8.49, &quot;high_usd&quot;: 19.8, &quot;validated&quot;: <span style={{ color: COND }}>false</span>, &quot;n_samples&quot;: 0,
            </p>
            <p style={respLine}>
              {I2}&quot;label&quot;: <span style={{ color: STR }}>&quot;assumption-based, not yet validated&quot;</span> {"}"},
            </p>
            <p style={respLine}>
              {I2}&quot;drivers&quot;: [ {"{"} &quot;name&quot;: <span style={{ color: STR }}>&quot;labor_cost&quot;</span>, &quot;value&quot;: 6.39, &quot;provenance&quot;: <span style={{ color: SHOP }}>&quot;SHOP&quot;</span>, &quot;source&quot;: <span style={{ color: STR }}>&quot;(0.08 + 0.5/223) hr × $52/hr × 1.3 markup × 1.15 overhead&quot;</span> {"}"}, … ],
            </p>
            <p style={respLine}>
              {I2}&quot;line_items&quot;: {"{"} &quot;material&quot;: 0.04, &quot;machine&quot;: 3.82, &quot;labor&quot;: 6.39, &quot;amortized_fixed&quot;: 3.89 {"}"}
            </p>
            <p style={respLine}>{I1}{"}"}]</p>
            <p style={respLine}>{"}"}</p>
          </div>
        </div>

        {/* 2 — self-host */}
        <div>
          <h2 style={sectionH2}>2 — Self-host with Docker Compose</h2>
          <p
            style={{
              margin: "12px 0 0",
              fontSize: 15,
              fontWeight: 300,
              lineHeight: 1.6,
              color: "rgba(245,245,247,0.58)",
            }}
          >
            The stack — backend API, frontend, Postgres, Redis — runs on your own infrastructure. This is the same path
            used for air-gapped and export-controlled deployments.
          </p>
          <div style={codeBlock}>
            <p style={codeLine}>git clone &quot;$PROOFSHAPE_DEPLOYMENT_REPOSITORY&quot; proofshape</p>
            <p style={codeLine}>cd proofshape</p>
            <p style={codeLine}>
              cp .env.example .env{I1}<span style={{ color: "rgba(245,245,247,0.35)" }}># set secrets, storage, origins</span>
            </p>
            <p style={codeLine}>docker compose up -d</p>
            <p style={codeLine}>open http://localhost:3000</p>
          </div>
        </div>

        {/* 3 — keys, limits */}
        <div>
          <h2 style={sectionH2}>3 — Keys, limits, and good behavior</h2>
          <div
            style={{
              marginTop: 16,
              display: "grid",
              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
              gap: 16,
            }}
          >
            <div style={infoCard}>
              <p style={infoLabel}>API KEYS</p>
              <p
                style={{
                  margin: "12px 0 0",
                  fontSize: 14,
                  fontWeight: 300,
                  lineHeight: 1.65,
                  color: "var(--st-ink-60)",
                }}
              >
                Scoped bearer keys (
                <span className="st-mono" style={{ fontSize: 12.5 }}>
                  cv_live_…
                </span>
                ), shown once at creation. Manage keys and usage from the developer settings; revoke instantly.
              </p>
            </div>
            <div style={infoCard}>
              <p style={infoLabel}>RATE LIMITS</p>
              <p
                className="st-mono"
                style={{ margin: "12px 0 0", fontSize: 12, lineHeight: 1.9, color: "var(--st-ink-60)" }}
              >
                X-RateLimit-Limit: 100
                <br />
                X-RateLimit-Remaining: 97
                <br />
                X-RateLimit-Reset: 1700000000
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────────────────── */}
      <section style={{ padding: "80px 48px 110px", textAlign: "center" }}>
        <h2
          className="st-display"
          style={{ fontSize: "clamp(32px, 3.8vw, 52px)", lineHeight: 1.06, letterSpacing: "-0.028em" }}
        >
          Ship the number with its receipts.
        </h2>
        <div style={{ marginTop: 36, display: "flex", justifyContent: "center", flexWrap: "wrap", gap: 16 }}>
          <Link href="/signup" className="st-pill st-pill-solid" style={{ padding: "14px 32px", fontSize: 15 }}>
            Get an API key
          </Link>
          <a href="/scalar" className="st-pill st-pill-ghost" style={{ padding: "14px 32px", fontSize: 15 }}>
            Full API reference
          </a>
        </div>
      </section>
    </SiteShell>
  );
}

// ── shared inline styles for the repeated code / card treatments ─────────────

const sectionH2: CSSProperties = {
  margin: 0,
  fontSize: 24,
  fontWeight: 300,
  letterSpacing: "-0.018em",
};

const codeBlock: CSSProperties = {
  marginTop: 16,
  border: "1px solid rgba(245,245,247,0.1)",
  borderRadius: 12,
  background: "#0a0b0d",
  padding: "22px 24px",
  fontFamily: "var(--st-font-mono)",
  fontSize: 13,
  lineHeight: 1.8,
  overflowX: "auto",
};

const codeLine: CSSProperties = { margin: 0, color: "rgba(245,245,247,0.85)" };

const responseBlock: CSSProperties = {
  marginTop: 14,
  border: "1px solid rgba(245,245,247,0.08)",
  borderRadius: 12,
  background: "#08090b",
  padding: "22px 24px",
  fontFamily: "var(--st-font-mono)",
  fontSize: 12.5,
  lineHeight: 1.75,
  overflowX: "auto",
};

const respLine: CSSProperties = { margin: 0, color: "rgba(245,245,247,0.7)" };

const infoCard: CSSProperties = {
  border: "1px solid rgba(245,245,247,0.1)",
  borderRadius: 12,
  background: "#0c0d10",
  padding: 22,
};

const infoLabel: CSSProperties = {
  margin: 0,
  fontFamily: "var(--st-font-mono)",
  fontSize: 11,
  letterSpacing: "0.16em",
  color: "var(--st-ink-40)",
};
