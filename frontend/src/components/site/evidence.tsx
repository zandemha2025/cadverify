"use client";

/**
 * Evidence + typography primitives for the dark-theater marketing site.
 *
 * These encode the HONESTY RULES structurally (DESIGN-DECISIONS.md):
 *  - Provenance is the FILL of the dot: MEASURED / SHOP / USER are grounded
 *    (filled ●); DEFAULT and MODEL are guesses (hollow ○). Hours are ○ MODEL,
 *    never ● MEASURED. There is no API here to put a filled dot on a MODEL/
 *    DEFAULT value — the type system won't let a page fake it.
 *  - Fabricated example figures must carry <IllustrativeTag/>; modeled
 *    what-if surfaces carry <ScenarioChip/>. Confidence bands are hatched
 *    (assumption / n=0) until real residuals turn them solid.
 *  - The one real fixture (object.stl · $14.14 · …) is the only thing a page
 *    presents as engine output; everything else is labeled.
 *
 * Presentation only (light Helvetica display + ui-monospace evidence). Colors
 * come from the scoped `--st-*` tokens, so nothing here can touch the product.
 *
 * SHARED FOUNDATION — do not edit in a page branch.
 */

import * as React from "react";

type Div = React.HTMLAttributes<HTMLDivElement>;
type Span = React.HTMLAttributes<HTMLSpanElement>;

// ── typography ───────────────────────────────────────────────────────────────

/**
 * The small-caps eyebrow / act label. Pass `index` (e.g. "01") to render the
 * numbered act form used across the cinematic acts ("01 — Routed by geometry").
 */
export function Eyebrow({
  index,
  children,
  style,
  ...rest
}: Span & { index?: string }) {
  return (
    <p className="st-eyebrow" style={style} {...rest}>
      {index ? <>{index} — </> : null}
      {children}
    </p>
  );
}

/** A light display heading. `as` picks the tag; `size` is a CSS font-size. */
export function DisplayHeading({
  as = "h2",
  size = "clamp(36px, 3.6vw, 54px)",
  children,
  className,
  style,
  ...rest
}: React.HTMLAttributes<HTMLHeadingElement> & {
  as?: "h1" | "h2" | "h3";
  size?: string;
}) {
  const Tag = as;
  return (
    <Tag
      className={`${as === "h1" ? "st-display" : "st-display-2"} ${className ?? ""}`}
      style={{ fontSize: size, ...style }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/** Inline mono evidence — a cost, dim, qty, rate, id, or source string. */
export function Mono({ children, style, ...rest }: Span) {
  return (
    <span className="st-mono" style={style} {...rest}>
      {children}
    </span>
  );
}

/**
 * A label → value evidence row (mono), as used in the driver stacks. `chip`
 * renders to the right of the value (typically a ProvenanceChip).
 */
export function MonoRow({
  label,
  value,
  sub,
  chip,
  style,
  ...rest
}: Div & {
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  chip?: React.ReactNode;
}) {
  return (
    <div
      className="st-mono"
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 12,
        padding: "13px 0",
        borderBottom: "1px solid var(--st-line-09)",
        fontSize: 14,
        ...style,
      }}
      {...rest}
    >
      <span style={{ color: "var(--st-ink-60)" }}>
        {label}
        {sub ? <span style={{ fontSize: 11, color: "var(--st-ink-30)" }}> — {sub}</span> : null}
      </span>
      <span style={{ display: "inline-flex", alignItems: "baseline", gap: 8, color: "var(--st-ink)", fontSize: 17 }}>
        {value}
        {chip}
      </span>
    </div>
  );
}

// ── provenance (the honesty core) ────────────────────────────────────────────

/** Grounded tiers are filled; guesses are hollow. Hours are always MODEL. */
export type Provenance = "MEASURED" | "SHOP" | "USER" | "DEFAULT" | "MODEL";

const PROV: Record<Provenance, { hue: string; filled: boolean; glyph: string }> = {
  MEASURED: { hue: "var(--st-prov-measured)", filled: true, glyph: "●" },
  SHOP: { hue: "var(--st-prov-shop)", filled: true, glyph: "●" },
  USER: { hue: "var(--st-prov-user)", filled: true, glyph: "●" },
  DEFAULT: { hue: "var(--st-prov-default)", filled: false, glyph: "○" },
  MODEL: { hue: "var(--st-prov-default)", filled: false, glyph: "○" },
};

/**
 * A provenance chip: filled dot (grounded — MEASURED/SHOP/USER) or hollow ring
 * (guess — DEFAULT/MODEL), tinted by tier, with the tier label. `label={false}`
 * renders just the dot. This is the ONLY sanctioned way to mark a figure's
 * provenance — there is no path to a filled dot on a MODEL/DEFAULT value.
 */
export function ProvenanceChip({
  provenance,
  label = true,
  style,
  ...rest
}: Span & { provenance: Provenance; label?: boolean }) {
  const p = PROV[provenance];
  return (
    <span className="st-chip" style={{ color: p.hue, ...style }} {...rest}>
      <span className={p.filled ? "st-dot" : "st-dot-hollow"} style={{ background: p.filled ? p.hue : undefined }} aria-hidden />
      {label ? <span>{provenance}</span> : null}
    </span>
  );
}

// ── honesty tags (fabricated / unshipped / unvalidated) ──────────────────────

/**
 * Marks a fabricated example figure. Fabricated figures may NEVER wear a filled
 * ● SHOP chip — they wear this. Renders "[illustrative]" (mono) or, with
 * `block`, an "ILLUSTRATIVE DATA" banner tag.
 */
export function IllustrativeTag({ block = false, style, ...rest }: Span & { block?: boolean }) {
  return (
    <span
      className="st-mono"
      style={{
        fontSize: block ? 9.5 : 11,
        letterSpacing: block ? "0.16em" : "0.04em",
        color: "var(--st-ink-40)",
        border: "1px solid var(--st-line-strong)",
        borderRadius: "var(--st-radius-chip)",
        padding: block ? "2px 7px" : "1px 5px",
        whiteSpace: "nowrap",
        ...style,
      }}
      {...rest}
    >
      {block ? "ILLUSTRATIVE DATA" : "[illustrative]"}
    </span>
  );
}

/** Marks a modeled what-if surface without presenting it as measured output. */
export function ScenarioChip({ style, ...rest }: Span) {
  return (
    <span
      className="st-mono"
      style={{
        fontSize: 9.5,
        letterSpacing: "0.1em",
        color: "var(--st-conditional)",
        border: "1px solid rgba(217,168,86,0.35)",
        borderRadius: "4px",
        padding: "2px 7px",
        whiteSpace: "nowrap",
        ...style,
      }}
      {...rest}
    >
      SCENARIO
    </span>
  );
}

/**
 * The confidence band texture: `state="assumption"` is hatched (assumption-
 * based, n=0 — the default until real residuals exist); `state="validated"` is
 * solid (measured on the user's held-out parts). Never render solid on
 * assumption-based data.
 */
export function HonestyBand({
  state,
  style,
  ...rest
}: Div & { state: "assumption" | "validated" }) {
  return (
    <div
      className={`st-band ${state === "assumption" ? "st-band-hatch" : "st-band-solid"}`}
      role="img"
      aria-label={state === "assumption" ? "assumption-based band, not yet validated" : "validated band"}
      style={style}
      {...rest}
    />
  );
}

/** The animated scroll-hint chevron used at the foot of cinematic heroes. */
export function ScrollHint({ style, ...rest }: Div) {
  return (
    <div
      aria-hidden="true"
      style={{
        position: "absolute",
        bottom: 28,
        left: "50%",
        transform: "translateX(-50%)",
        animation: "st-scrollHint 2.2s ease-in-out infinite",
        ...style,
      }}
      {...rest}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--st-ink-70)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </div>
  );
}

/** A theater card (bordered panel in the near-black register). */
export function Panel({ well = false, className, children, ...rest }: Div & { well?: boolean }) {
  return (
    <div className={`${well ? "st-card-well" : "st-card"} ${className ?? ""}`} {...rest}>
      {children}
    </div>
  );
}
