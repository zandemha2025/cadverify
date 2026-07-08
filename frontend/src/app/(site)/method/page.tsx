"use client";

/**
 * /method — "One file in. The whole model out."
 *
 * A DOCUMENT page (no WebGL) in the dark-theater register, ported faithfully
 * from handoff_cadverify_2026-07-04/site/Method.dc.html. It renders the
 * cost-truth engine's own report for the ONE real fixture — object.stl,
 * calibrated to Midwest Precision CNC. Every figure on this page is either the
 * canonical fixture output or a schematic honesty demo; nothing is invented.
 *
 * MUST-KEEP (all present):
 *  - the five-stage walk, reframed to the question hierarchy (envelope →
 *    materials → process physics → hours+mass → resource cost);
 *  - the Σ scroll-assembly (the four drivers reveal and reconcile to $14.14,
 *    ported from the design's componentDidMount rAF loop via measureSection);
 *  - the honesty rail (provenance = the fill of the dot · confidence = the
 *    texture of the band);
 *  - the ±40% objection section.
 *
 * Copy is VERBATIM from the (post-pivot, audited) design. Honesty audit:
 *  - $14.14 with drivers 6.39/3.89/3.82/0.04 sum exactly (6.39+3.89+3.82+0.04);
 *  - band $8.49–19.80 · ±40% · assumption-based · n=0 is hatched, never solid,
 *    and no measured accuracy figure is printed;
 *  - shop rates $52/$95/$30, margin 0.30, util 0.80, crossover 1,962, routing
 *    cnc_turning 0.80, DFM 423 faces / 1 sidewall <1.0°, lead 5.6–10.4d all
 *    match the canonical fixture. No fabricated figure wears a filled ● chip.
 */

import * as React from "react";
import Link from "next/link";
import {
  SiteShell,
  Eyebrow,
  ProvenanceChip,
  HonestyBand,
  measureSection,
  seg,
  smooth,
  useRafLoop,
} from "@/components/site";

export default function MethodPage() {
  return (
    <SiteShell>
      <MethodBody />
    </SiteShell>
  );
}

function MethodBody() {
  return (
    <>
      <Hero />
      <RecordAssembles />
      <Stages />
      <HonestyRail />
      <Objection />
      <MethodCta />
    </>
  );
}

/* ── hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  return (
    <section style={{ maxWidth: 880, margin: "0 auto", padding: "110px 48px 90px" }}>
      <Eyebrow>Method</Eyebrow>
      <h1
        className="st-display"
        style={{ margin: "24px 0 0", fontSize: "clamp(44px, 5.2vw, 72px)", lineHeight: 1.03 }}
      >
        One file in.
        <br />
        The whole model out.
      </h1>
      <p style={{ margin: "26px 0 0", maxWidth: 620, fontSize: 18, lineHeight: 1.65, fontWeight: 300, color: "var(--st-ink-60)" }}>
        A CAD file passes through five stages, and every one of them opens. The panels below render the cost-truth
        engine&apos;s own report for a real part — object.stl, calibrated to a real shop, with every panel tied to explicit inputs and outputs.
      </p>
      <p style={{ margin: "16px 0 0", maxWidth: 620, fontSize: 15, lineHeight: 1.65, fontWeight: 300, color: "var(--st-ink-45)" }}>
        The question it answers, in order:{" "}
        <span style={{ color: "rgba(245,245,247,0.8)" }}>
          can it be made — on your machines, in materials that survive its world — and what will it really take?
        </span>{" "}
        The dollar is the last stop, not the destination.
      </p>
      <div
        className="st-mono"
        style={{ marginTop: 22, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, fontSize: 11 }}
      >
        {QUESTION_HIERARCHY.map((label, i) => (
          <React.Fragment key={label}>
            {i > 0 ? <span style={{ color: "var(--st-ink-25)" }}>→</span> : null}
            <span
              style={{
                border: "1px solid var(--st-line-strong)",
                borderRadius: "var(--st-radius-pill)",
                padding: "5px 13px",
                color: "var(--st-ink-70)",
              }}
            >
              {label}
            </span>
          </React.Fragment>
        ))}
      </div>
    </section>
  );
}

const QUESTION_HIERARCHY = [
  "1 envelope — your machines",
  "2 materials — its world",
  "3 process physics",
  "4 hours + mass",
  "5 resource cost",
];

/* ── the record assembles — scroll-driven Σ ───────────────────────────────── */

function RecordAssembles() {
  const sec = React.useRef<HTMLElement | null>(null);
  const rows = [
    React.useRef<HTMLDivElement | null>(null),
    React.useRef<HTMLDivElement | null>(null),
    React.useRef<HTMLDivElement | null>(null),
    React.useRef<HTMLDivElement | null>(null),
  ];
  const sumRef = React.useRef<HTMLDivElement | null>(null);
  const noteRef = React.useRef<HTMLParagraphElement | null>(null);

  // Scroll-driven assembly, ported verbatim from the design's rAF loop:
  // p is the section's sticky-pin progress (measureSection(...).pin); each
  // driver row reveals on its own window, then Σ/UNIT scales in, then the note.
  useRafLoop(() => {
    const p = measureSection(sec.current).pin;
    rows.forEach((row, i) => {
      const el = row.current;
      if (!el) return;
      const a = 0.08 + i * 0.14;
      const v = smooth(seg(p, a, a + 0.12));
      el.style.opacity = v.toFixed(3);
      el.style.transform = `translateY(${((1 - v) * 22).toFixed(1)}px)`;
    });
    if (sumRef.current) {
      const v = smooth(seg(p, 0.68, 0.82));
      sumRef.current.style.opacity = v.toFixed(3);
      sumRef.current.style.transform = `scale(${(0.96 + v * 0.04).toFixed(3)})`;
    }
    if (noteRef.current) {
      noteRef.current.style.opacity = smooth(seg(p, 0.84, 0.94)).toFixed(3);
    }
  });

  return (
    <section
      ref={sec as React.RefObject<HTMLElement>}
      style={{ position: "relative", height: "240vh", borderTop: "1px solid var(--st-line-soft)", background: "var(--st-bg-raised)" }}
    >
      <div
        style={{
          position: "sticky",
          top: 0,
          height: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 48px",
        }}
      >
        <p className="st-eyebrow" style={{ margin: "0 0 34px", color: "var(--st-ink-40)" }}>
          Watch the record assemble
        </p>
        <div className="st-mono" style={{ width: "100%", maxWidth: 560 }}>
          {ASSEMBLY_ROWS.map((r, i) => (
            <div
              key={r.label}
              ref={rows[i] as React.RefObject<HTMLDivElement>}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                padding: "13px 0",
                borderBottom: i < 3 ? "1px solid var(--st-line-09)" : undefined,
                opacity: 0,
              }}
            >
              <span style={{ fontSize: 14, color: "var(--st-ink-60)" }}>
                {r.label} <span style={{ fontSize: 11, color: "var(--st-ink-30)" }}>— {r.detail}</span>
              </span>
              <span style={{ display: "inline-flex", alignItems: "baseline", gap: 8, fontSize: 17, color: "var(--st-ink)" }}>
                {r.value} <ProvenanceChip provenance="SHOP" style={{ fontSize: 10 }} />
              </span>
            </div>
          ))}
          <div
            ref={sumRef}
            style={{
              borderTop: "1px solid var(--st-line-strong)",
              marginTop: 6,
              paddingTop: 22,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              opacity: 0,
            }}
          >
            <span style={{ fontSize: 13, letterSpacing: "0.18em", color: "var(--st-ink-45)" }}>Σ / UNIT</span>
            <span
              style={{
                fontFamily: "var(--st-font-display)",
                fontSize: "clamp(56px, 7vw, 96px)",
                fontWeight: 200,
                letterSpacing: "-0.04em",
                lineHeight: 1,
                color: "var(--st-ink)",
              }}
            >
              $14.14
            </span>
          </div>
          <p ref={noteRef} style={{ margin: "20px 0 0", textAlign: "right", fontSize: 11, color: "var(--st-ink-35)", opacity: 0 }}>
            reconciles exactly — no naked totals, ever
          </p>
        </div>
      </div>
    </section>
  );
}

const ASSEMBLY_ROWS = [
  { label: "labor", detail: "0.082 hr × $52/hr", value: "$6.39" },
  { label: "amortized fixed", detail: "setup ÷ 10 units", value: "$3.89" },
  { label: "machine", detail: "15.2 hr build ÷ 223 parts", value: "$3.82" },
  { label: "material", detail: "4.63 cm³ × $7/kg lot", value: "$0.04" },
];

/* ── stages ────────────────────────────────────────────────────────────── */

function StageShell({ index, title, lede, children }: { index: string; title: string; lede: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 36 }}>
      <span
        style={{
          fontSize: 56,
          fontWeight: 200,
          color: "rgba(245,245,247,0.16)",
          lineHeight: 1,
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {index}
      </span>
      <div>
        <h2 className="st-display-2" style={{ fontSize: 30 }}>
          {title}
        </h2>
        <p style={{ margin: "14px 0 0", fontSize: 15.5, lineHeight: 1.65, fontWeight: 300, color: "var(--st-ink-55)" }}>{lede}</p>
        {children}
      </div>
    </div>
  );
}

function Stages() {
  return (
    <section style={{ maxWidth: 880, margin: "0 auto", padding: "80px 48px 40px", display: "flex", flexDirection: "column", gap: 88 }}>
      {/* 01 — measure the geometry */}
      <StageShell
        index="01"
        title="Measure the geometry."
        lede="The engine reads the part itself — volume, bounding box, wall thickness, watertightness. These are MEASURED facts taken directly from your CAD, the ground everything else stands on. The mesh is parsed in-process and discarded."
      >
        <div className="st-card" style={{ marginTop: 22, padding: 22 }}>
          <div className="st-mono" style={{ display: "flex", flexWrap: "wrap", gap: 8, fontSize: 12 }}>
            {MEASURED_FACTS.map((f) => (
              <span
                key={f.label}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 7,
                  border: "1px solid rgba(106,165,216,0.3)",
                  borderRadius: 6,
                  padding: "5px 10px",
                }}
              >
                <span aria-hidden style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--st-prov-measured)" }} />
                <span style={{ color: "rgba(245,245,247,0.65)" }}>{f.label}</span>
                <span style={{ color: "var(--st-prov-measured)" }}>{f.value}</span>
              </span>
            ))}
          </div>
          <p className="st-mono" style={{ margin: "14px 0 0", fontSize: 11, color: "var(--st-ink-40)" }}>
            tagged ● MEASURED — read directly from the geometry you uploaded
          </p>
        </div>
      </StageShell>

      {/* 02 — route it, and say why */}
      <StageShell
        index="02"
        title="Route it — and say why."
        lede="Before anything downstream is computed, the engine decides whether — and how — the part can be made, from its shape — and shows the reasoning, not just a verdict. Every DFM blocker states the measured value against the threshold and points at the offending faces."
      >
        <div className="st-card" style={{ marginTop: 22, overflow: "hidden" }}>
          <div style={{ padding: "20px 22px", borderBottom: "1px solid var(--st-line-soft)" }}>
            <p className="st-mono" style={{ margin: 0, fontSize: 10.5, letterSpacing: "0.16em", color: "var(--st-ink-40)" }}>
              GEOMETRIC ROUTING · CONFIDENCE 0.80 · ARCHETYPE ROTATIONAL
            </p>
            <p style={{ margin: "10px 0 0", fontSize: 21, fontWeight: 400 }}>→ CNC turning</p>
            <p
              style={{
                margin: "10px 0 0",
                fontSize: 14,
                lineHeight: 1.6,
                fontWeight: 300,
                color: "var(--st-ink-60)",
                borderLeft: "2px solid rgba(106,165,216,0.4)",
                paddingLeft: 14,
              }}
            >
              &ldquo;Axisymmetric cross-section (round, turnable): axis 21mm × Ø21mm → CNC turning / mill-turn. A round metal
              part is rarely powder-bed printed at production volume.&rdquo;
            </p>
          </div>
          <div className="st-mono" style={{ padding: "16px 22px", display: "flex", flexDirection: "column", gap: 8, fontSize: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--st-ink-55)" }}>cnc_turning · mjf · cnc_5axis</span>
              <span style={{ color: "var(--st-conditional)" }}>issues 0.8–0.9</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--st-ink-55)" }}>cnc_3axis — 423 faces (59.6%) undercut</span>
              <span style={{ color: "var(--st-fail)" }}>fail</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--st-ink-55)" }}>injection_molding — 1 sidewall &lt; 1.0° draft</span>
              <span style={{ color: "var(--st-fail)" }}>fail</span>
            </div>
          </div>
        </div>
      </StageShell>

      {/* 03 — open the cost */}
      <StageShell
        index="03"
        title="Open the cost."
        lede="Every driver on the table, provenance-tagged and sourced, with line items summing visibly to the unit cost — no naked totals. Anything generic is flagged DEFAULT, so you see exactly where the model is guessing before you ask."
      >
        <div className="st-card" style={{ marginTop: 22, padding: 22 }}>
          <div className="st-mono" style={{ display: "flex", flexDirection: "column", gap: 9, fontSize: 12.5 }}>
            {COST_DRIVERS.map((d) => (
              <div key={d.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                <span style={{ color: "var(--st-ink-60)" }}>{d.label}</span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                  <span>{d.value}</span>
                  {d.provenance === "SHOP" ? (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--st-prov-shop)" }}>
                      <ProvenanceChip provenance="SHOP" />
                      <span>{d.tol}</span>
                    </span>
                  ) : (
                    <ProvenanceChip provenance="DEFAULT" />
                  )}
                </span>
              </div>
            ))}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                borderTop: "1px solid var(--st-line)",
                paddingTop: 10,
                marginTop: 2,
              }}
            >
              <span style={{ color: "rgba(245,245,247,0.75)" }}>Σ line items = unit cost</span>
              <span style={{ color: "var(--st-pass)" }}>$14.14 ✓</span>
            </div>
          </div>
        </div>
      </StageShell>

      {/* 04 — calibrate to your shop */}
      <StageShell
        index="04"
        title="Calibrate it to your shop."
        lede="Bind a shop's real labor, machine and material rates and the whole model re-costs to their reality. Each bound rate is tagged SHOP and carries its source. Every rate that isn't bound stays a visible DEFAULT — your numbers become yours, and the gaps stay honest."
      >
        <div className="st-card" style={{ marginTop: 22, padding: 22 }}>
          <p className="st-mono" style={{ margin: 0, fontSize: 10.5, letterSpacing: "0.16em", color: "var(--st-prov-shop)" }}>
            ● CALIBRATED TO MIDWEST PRECISION CNC — 19 RATES BOUND
          </p>
          <p className="st-mono" style={{ margin: "8px 0 0", fontSize: 11, color: "var(--st-ink-40)" }}>
            source: shop accounting export 2026-Q2 (loaded rates + negotiated resin lots)
          </p>
          <div className="st-mono" style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 8, fontSize: 11.5 }}>
            {BOUND_RATES.map((r) => (
              <span
                key={r.label}
                style={{
                  border: "1px solid rgba(201,131,79,0.3)",
                  borderRadius: 6,
                  padding: "4px 10px",
                  color: "rgba(245,245,247,0.75)",
                  whiteSpace: "nowrap",
                }}
              >
                {r.label} <span style={{ color: "var(--st-prov-shop)" }}>{r.value}</span>
              </span>
            ))}
            {DEFAULT_RATES.map((label) => (
              <span
                key={label}
                style={{
                  border: "1px dashed var(--st-line-strong)",
                  borderRadius: 6,
                  padding: "4px 10px",
                  color: "var(--st-ink-45)",
                }}
              >
                {label} ○ DEFAULT
              </span>
            ))}
          </div>
        </div>
      </StageShell>

      {/* 05 — make the decision */}
      <StageShell
        index="05"
        title="Make the decision."
        lede="The output is a choice, not a price: make by which process, and the quantity where you should tool up instead — carried with confidence bands, never a fake-exact figure."
      >
        <div
          className="st-card"
          style={{ marginTop: 22, padding: 26, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 26 }}
        >
          <div>
            <p className="st-mono" style={{ margin: 0, fontSize: 10.5, letterSpacing: "0.16em", color: "var(--st-ink-40)" }}>
              RESOURCE COST · MAKE NOW · MJF (PP) · QTY 10
            </p>
            <p
              className="st-readout"
              style={{ margin: "12px 0 0", fontSize: 52, fontWeight: 200, letterSpacing: "-0.035em", lineHeight: 1 }}
            >
              $14.14
            </p>
            <div style={{ marginTop: 16, position: "relative" }}>
              <HonestyBand state="assumption" style={{ height: 6, borderRadius: 3 }} />
              <span
                aria-hidden
                style={{ position: "absolute", top: -2, bottom: -2, left: "50%", width: 2, background: "var(--st-ink)" }}
              />
            </div>
            <p className="st-mono" style={{ margin: "9px 0 0", fontSize: 11, color: "var(--st-ink-40)" }}>
              $8.49 — ±40% · assumption-based · n=0 — $19.80
            </p>
          </div>
          <div
            style={{
              borderLeft: "1px solid var(--st-line-soft)",
              paddingLeft: 26,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              gap: 14,
            }}
          >
            <div>
              <p className="st-mono" style={{ margin: 0, fontSize: 10.5, letterSpacing: "0.14em", color: "var(--st-ink-40)" }}>
                LEAD TIME
              </p>
              <p style={{ margin: "5px 0 0", fontSize: 19, fontWeight: 300 }}>5.6 – 10.4 days</p>
            </div>
            <div>
              <p className="st-mono" style={{ margin: 0, fontSize: 10.5, letterSpacing: "0.14em", color: "var(--st-ink-40)" }}>
                CROSSOVER
              </p>
              <p style={{ margin: "5px 0 0", fontSize: 19, fontWeight: 300 }}>MJF wins ≤ 1,962 units</p>
              <p style={{ margin: "4px 0 0", fontSize: 12.5, fontWeight: 300, color: "var(--st-conditional)" }}>
                injection molding above — if redesigned, never a current quote
              </p>
            </div>
          </div>
        </div>
      </StageShell>
    </section>
  );
}

const MEASURED_FACTS = [
  { label: "volume", value: "4.63 cm³" },
  { label: "bbox", value: "21.2 × 21.4 × 21.5 mm" },
  { label: "nominal wall", value: "6.17 mm" },
  { label: "watertight", value: "yes" },
];

const COST_DRIVERS: { label: string; value: string; provenance: "SHOP" | "DEFAULT"; tol?: string }[] = [
  { label: "labor — 0.082 hr × $52/hr", value: "$6.39", provenance: "SHOP", tol: "±20%" },
  { label: "setup — 0.5 hr ÷ 10 units", value: "$3.89", provenance: "SHOP", tol: "±20%" },
  { label: "machine — 15.2 hr build ÷ 223 parts", value: "$3.82", provenance: "SHOP", tol: "±40%" },
  { label: "material — 4.63 cm³ × $7/kg shop lot", value: "$0.04", provenance: "SHOP", tol: "±5%" },
  { label: "nesting — 223 parts/build packing model", value: "223", provenance: "DEFAULT" },
];

const BOUND_RATES = [
  { label: "labor", value: "$52/hr" },
  { label: "CNC-3ax", value: "$95/hr" },
  { label: "MJF", value: "$30/hr" },
  { label: "margin", value: "0.30" },
  { label: "utilization", value: "0.80" },
];

const DEFAULT_RATES = ["stock_allowance 1.10×", "n_cavities 1"];

/* ── honesty rail ──────────────────────────────────────────────────────── */

function HonestyRail() {
  return (
    <section
      style={{
        borderTop: "1px solid var(--st-line-soft)",
        borderBottom: "1px solid var(--st-line-soft)",
        background: "var(--st-bg-raised)",
        padding: "90px 48px",
      }}
    >
      <div style={{ maxWidth: 880, margin: "0 auto" }}>
        <Eyebrow>Reading the receipts</Eyebrow>
        <h2
          className="st-display-2"
          style={{ margin: "20px 0 0", fontSize: "clamp(30px, 3.4vw, 44px)", lineHeight: 1.1, maxWidth: 700 }}
        >
          Two marks tell you everything: where a number came from, and whether we&apos;ve earned it.
        </h2>
        <div style={{ marginTop: 40, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          <div className="st-card" style={{ padding: 26 }}>
            <p className="st-mono" style={{ margin: 0, fontSize: 11, letterSpacing: "0.18em", color: "var(--st-ink-40)" }}>
              PROVENANCE — THE FILL OF THE DOT
            </p>
            <p style={{ margin: "14px 0 0", fontSize: 14.5, lineHeight: 1.65, fontWeight: 300, color: "var(--st-ink-60)" }}>
              Filled means grounded — measured off your geometry, bound to your shop, or overridden by you. A hollow ring
              means a generic DEFAULT: we&apos;re guessing, and we&apos;re telling you so.
            </p>
            <div style={{ marginTop: 20, display: "flex", flexWrap: "wrap", gap: 16 }}>
              <ProvenanceChip provenance="MEASURED" style={{ fontSize: 11.5 }} />
              <ProvenanceChip provenance="SHOP" style={{ fontSize: 11.5 }} />
              <ProvenanceChip provenance="USER" style={{ fontSize: 11.5 }} />
              <ProvenanceChip provenance="DEFAULT" style={{ fontSize: 11.5 }} />
            </div>
          </div>
          <div className="st-card" style={{ padding: 26 }}>
            <p className="st-mono" style={{ margin: 0, fontSize: 11, letterSpacing: "0.18em", color: "var(--st-ink-40)" }}>
              CONFIDENCE — THE TEXTURE OF THE BAND
            </p>
            <p style={{ margin: "14px 0 0", fontSize: 14.5, lineHeight: 1.65, fontWeight: 300, color: "var(--st-ink-60)" }}>
              Hatched means assumption-based, not yet validated. It goes solid — and reads &ldquo;validated on N of your
              parts&rdquo; — only after real costs on your held-out parts back it. We never print an accuracy figure we
              haven&apos;t measured.
            </p>
            <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 12 }}>
              <HonestyBand state="assumption" style={{ height: 6, borderRadius: 3 }} />
              <HonestyBand state="validated" style={{ height: 6, borderRadius: 3 }} />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── the objection ─────────────────────────────────────────────────────── */

function Objection() {
  return (
    <section style={{ maxWidth: 880, margin: "0 auto", padding: "90px 48px 20px" }}>
      <Eyebrow>The question everyone asks</Eyebrow>
      <h2 className="st-display-2" style={{ margin: "20px 0 0", fontSize: "clamp(30px, 3.4vw, 44px)", lineHeight: 1.1 }}>
        &ldquo;±40%? Why would I trust that?&rdquo;
      </h2>
      <div
        style={{
          marginTop: 26,
          maxWidth: 680,
          display: "flex",
          flexDirection: "column",
          gap: 18,
          fontSize: 16.5,
          lineHeight: 1.7,
          fontWeight: 300,
          color: "rgba(245,245,247,0.65)",
        }}
      >
        <p style={{ margin: 0 }}>
          Because it&apos;s true. ±40% is what an uncalibrated should-cost honestly knows before it has seen your shops and
          your invoices — the stated assumption band of the defaults it leaned on, not a measured accuracy dressed up as one.
        </p>
        <p style={{ margin: 0 }}>
          The vendors printing &ldquo;±5% accurate&rdquo; on slide four can&apos;t tell you what it was measured on, because
          it wasn&apos;t. We&apos;d rather hand you a wide band you can narrow — bind your rates, send back real costs, watch
          it validate to a measured residual on your held-out parts — than a narrow number you can&apos;t check.
        </p>
        <p style={{ margin: 0, color: "rgba(245,245,247,0.85)" }}>
          The wide band isn&apos;t the method&apos;s weakness. It&apos;s the proof the method doesn&apos;t lie.
        </p>
      </div>
    </section>
  );
}

/* ── CTA ───────────────────────────────────────────────────────────────── */

function MethodCta() {
  return (
    <section style={{ padding: "110px 48px", textAlign: "center" }}>
      <h2 className="st-display-2" style={{ fontSize: "clamp(32px, 3.8vw, 52px)", lineHeight: 1.06, letterSpacing: "-0.028em" }}>
        See it on a part you choose.
      </h2>
      <p style={{ margin: "20px auto 0", maxWidth: 480, fontSize: 16.5, lineHeight: 1.6, fontWeight: 300, color: "var(--st-ink-60)" }}>
        Run your own part, or bring a real one and calibrate it to your shop.
      </p>
      <div style={{ marginTop: 36, display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
        <Link href="/signup" className="st-pill st-pill-solid" style={{ padding: "14px 32px", fontSize: 15 }}>
          Cost a part
        </Link>
        <Link href="/platform" className="st-pill st-pill-ghost" style={{ padding: "14px 32px", fontSize: 15 }}>
          Explore the platform
        </Link>
      </div>
    </section>
  );
}
