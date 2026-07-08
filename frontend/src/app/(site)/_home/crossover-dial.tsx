"use client";

/**
 * The live crossover dial (Act 4.2 of Direction - Cinematic).
 *
 * A page-local interactive piece for the home page — NOT foundation. Ported
 * faithfully from the `renderVals()` dial logic and SVG in
 * `handoff_cadverify_2026-07-04/site/Direction - Cinematic.dc.html`.
 *
 * HONESTY: the two curves are FITTED from the engine's real costed quantities,
 * anchored to the fixture — the MJF curve passes through $14.14 at qty 10 and
 * crosses the injection-molding alternative at the real crossover of 1,962. It
 * is labeled "fitted … schematic between computed points" on the card, so the
 * dial never claims a continuous engine curve. The injection branch is always
 * qualified "if redesigned," never quoted as a current price.
 */

import * as React from "react";
import Link from "next/link";
import { PILOT_HREF } from "@/components/site";

const CROSSOVER = 1962;

/** unit = fixedAmort/qty + variablePerUnit (the engine's fitted form). */
const dialUnitAt = (f: number, v: number, q: number): number => f / q + v;

/** Build the SVG polyline for a fitted curve across log-quantity 1 → 10,000. */
function dialPath(f: number, v: number): string {
  const pts: string[] = [];
  for (let i = 0; i <= 64; i++) {
    const q = Math.pow(10, (i / 64) * 4);
    const cost = Math.min(50, dialUnitAt(f, v, q));
    const x = 40 + (Math.log10(q) / 4) * 672;
    const y = 196 - (cost / 50) * 186;
    pts.push((i === 0 ? "M" : "L") + x.toFixed(1) + " " + y.toFixed(1));
  }
  return pts.join(" ");
}

const fmt = (v: number): string =>
  "$" + v.toLocaleString("en-US", { maximumFractionDigits: v < 100 ? 2 : 0 });

export function CrossoverDial({
  sectionRef,
}: {
  /** The page attaches this so the progress rail's "PROOF" stop can measure it. */
  sectionRef?: React.RefObject<HTMLElement | null>;
}) {
  const [qty, setQty] = React.useState(500);

  const below = qty <= CROSSOVER;
  const makeUnit = dialUnitAt(37.27, 10.41, qty);
  const toolUnit = dialUnitAt(7800, 6.45, qty);
  const recUnit = below ? makeUnit : toolUnit;
  const pos = Math.round((Math.log10(Math.max(1, qty)) / 4) * 1000);

  // curves are constant across renders — fit once
  const pathMjf = React.useMemo(() => dialPath(37.27, 10.41), []);
  const pathIm = React.useMemo(() => dialPath(7800, 6.45), []);

  const mjfStroke = below ? "#f5f5f7" : "rgba(245,245,247,0.3)";
  const imStroke = below ? "rgba(245,245,247,0.3)" : "#d9a856";
  const mjfW = below ? 2.5 : 1.5;
  const imW = below ? 1.5 : 2.5;
  const qtyX = (40 + (Math.log10(qty) / 4) * 672).toFixed(1);
  const crossX = (40 + (Math.log10(CROSSOVER) / 4) * 672).toFixed(1);
  const dotY = (196 - (Math.min(50, recUnit) / 50) * 186).toFixed(1);

  // typed for both onInput and onChange (range drags fire onInput on Firefox)
  const onDial = (e: React.SyntheticEvent<HTMLInputElement>) => {
    const p = parseFloat(e.currentTarget.value);
    setQty(Math.max(1, Math.round(Math.pow(10, (p / 1000) * 4))));
  };

  const legend: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
  };

  return (
    <section
      data-screen-label="Live crossover dial"
      ref={sectionRef}
      style={{
        position: "relative",
        zIndex: 10,
        background:
          "linear-gradient(180deg, rgba(5,5,6,0) 0%, rgba(7,7,9,0.9) 15%, rgba(7,7,9,0.9) 85%, rgba(5,5,6,0) 100%)",
        padding: "16vh 48px",
      }}
    >
      <div style={{ maxWidth: 760, margin: "0 auto" }}>
        <p
          className="st-eyebrow"
          style={{ textAlign: "center", fontSize: 13 }}
        >
          Don&rsquo;t trust the copy — drag this
        </p>
        <h2
          className="st-display-2"
          style={{
            margin: "18px 0 0",
            textAlign: "center",
            fontSize: "clamp(30px, 3.4vw, 46px)",
            letterSpacing: "-0.026em",
          }}
        >
          The decision, live.
          <br />
          Fitted from the engine&rsquo;s costed quantities.
        </h2>

        <div
          style={{
            marginTop: 44,
            border: "1px solid var(--st-line-12)",
            borderRadius: 16,
            background: "var(--st-panel)",
            padding: "30px 34px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            <p style={{ margin: 0, fontSize: 22, fontWeight: 300, letterSpacing: "-0.015em" }}>
              {below ? "Make by MJF (PP)" : "Tool up: injection molding"}
            </p>
            <p className="st-mono" style={{ margin: 0, fontSize: 13, color: "var(--st-ink-55)" }}>
              {fmt(recUnit)} <span style={{ color: "var(--st-ink-35)" }}>/unit</span>
            </p>
          </div>

          {!below ? (
            <p className="st-mono" style={{ margin: "8px 0 0", fontSize: 11.5, color: "var(--st-conditional)" }}>
              conditional — the part fails draft today · &ldquo;if redesigned,&rdquo; never a current quote
            </p>
          ) : null}

          <div style={{ marginTop: 26 }}>
            <div
              className="st-mono"
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: 10,
                fontSize: 11.5,
                color: "var(--st-ink-45)",
              }}
            >
              <span>QUANTITY</span>
              <span style={{ color: "var(--st-ink)" }}>{qty.toLocaleString()} units</span>
            </div>
            <input
              className="st-dial"
              type="range"
              min={0}
              max={1000}
              step={1}
              value={pos}
              onInput={onDial}
              onChange={onDial}
              aria-label="Quantity"
            />
            <div
              className="st-mono"
              style={{
                marginTop: 8,
                display: "flex",
                justifyContent: "space-between",
                fontSize: 10.5,
                color: "var(--st-ink-35)",
              }}
            >
              <span>1</span>
              <span>crossover &asymp; 1,962</span>
              <span>10,000</span>
            </div>
          </div>

          <svg viewBox="0 0 720 230" style={{ width: "100%", display: "block", marginTop: 26 }}>
            <line x1="40" y1="10" x2="40" y2="196" stroke="rgba(245,245,247,0.14)" strokeWidth="1" />
            <line x1="40" y1="196" x2="712" y2="196" stroke="rgba(245,245,247,0.14)" strokeWidth="1" />
            <g fontFamily="ui-monospace, monospace" fontSize="10.5" fill="rgba(245,245,247,0.35)">
              <text x="34" y="200" textAnchor="end">$0</text>
              <text x="34" y="106" textAnchor="end">$25</text>
              <text x="34" y="16" textAnchor="end">$50</text>
            </g>
            <line x1={crossX} y1="10" x2={crossX} y2="196" stroke="rgba(245,245,247,0.25)" strokeWidth="1" strokeDasharray="3 4" />
            <path d={pathIm} fill="none" stroke={imStroke} strokeWidth={imW} strokeDasharray="6 4" />
            <path d={pathMjf} fill="none" stroke={mjfStroke} strokeWidth={mjfW} />
            <line x1={qtyX} y1="10" x2={qtyX} y2="196" stroke="#f5f5f7" strokeWidth="1.5" />
            <circle cx={qtyX} cy={dotY} r="4.5" fill="#f5f5f7" stroke="#0b0c0f" strokeWidth="2" />
          </svg>

          <div
            className="st-mono"
            style={{
              marginTop: 14,
              display: "flex",
              justifyContent: "center",
              gap: 26,
              fontSize: 11,
              color: "var(--st-ink-45)",
              flexWrap: "wrap",
            }}
          >
            <span style={legend}>
              <span aria-hidden="true" style={{ width: 14, height: 2, background: mjfStroke }} />
              MJF (PP) — make now
            </span>
            <span style={legend}>
              <span aria-hidden="true" style={{ width: 14, height: 2, background: imStroke }} />
              Injection molding — tooled, if redesigned
            </span>
          </div>

          <p
            className="st-mono"
            style={{ margin: "20px 0 0", textAlign: "center", fontSize: 10.5, color: "var(--st-ink-30)" }}
          >
            fitted from the engine&rsquo;s costed quantities · schematic between computed points · object.stl · Midwest Precision CNC
          </p>
        </div>

        <p
          style={{
            margin: "26px 0 0",
            textAlign: "center",
            fontSize: 15,
            fontWeight: 300,
            color: "var(--st-ink-55)",
          }}
        >
          This is one part. A pilot does this for fifty of yours — against your rates.&nbsp;&nbsp;
          <Link href={PILOT_HREF} className="st-underline">
            Request a pilot &rarr;
          </Link>
        </p>
      </div>
    </section>
  );
}
