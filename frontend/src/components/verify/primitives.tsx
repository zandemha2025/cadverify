"use client";

/**
 * Light-instrument primitives for the Verify surface. Explicit-hex, theme-
 * independent (the app is dark-first; this register is the founder-approved light
 * instrument). These are the honesty atoms: a provenance dot/chip, the hatched
 * (assumption) vs solid (validated) band, cards, kicker, and empty states.
 */
import * as React from "react";
import { C, MONO, PROV, type Prov } from "@/lib/verify/tokens";

export function ProvDot({ p, size = 8 }: { p: Prov; size?: number }) {
  const m = PROV[p];
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        flexShrink: 0,
        background: m.filled ? m.color : "transparent",
        border: m.filled ? "none" : `1.5px solid ${m.color}`,
      }}
    />
  );
}

/** The provenance tag on a number (● grounded / ○ MODEL·DEFAULT). */
export function ProvChip({ p, className }: { p: Prov; className?: string }) {
  const m = PROV[p];
  return (
    <span
      className={className}
      title={`${m.label} — ${m.description}`}
      style={{
        fontFamily: MONO,
        fontSize: 10,
        color: m.color,
        whiteSpace: "nowrap",
      }}
    >
      {m.glyph} {m.label}
    </span>
  );
}

export function Illustrative({ label = "ILLUSTRATIVE DATA" }: { label?: string }) {
  return (
    <span
      style={{
        fontFamily: MONO,
        fontSize: 9.5,
        letterSpacing: "0.1em",
        border: `1px solid ${C.hair}`,
        color: C.ink45,
        borderRadius: 4,
        padding: "2px 7px",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

export function Kicker({ children, color = C.ink45 }: { children: React.ReactNode; color?: string }) {
  return (
    <p
      style={{
        margin: 0,
        fontFamily: MONO,
        fontSize: 10.5,
        letterSpacing: "0.14em",
        color,
      }}
    >
      {children}
    </p>
  );
}

export function Card({
  children,
  style,
  radius = 16,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
  radius?: number;
}) {
  return (
    <div
      style={{
        border: `1px solid ${C.hair}`,
        borderRadius: radius,
        background: C.panel,
        padding: "18px 20px",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/** The measurement band: HATCHED = assumption awaiting validation; SOLID =
 *  measured/validated. `validated` and `label` are rendered VERBATIM from the
 *  engine's confidence object — never a fabricated ±X%. Withheld ≠ zero. */
export function ConfidenceBand({
  validated,
  pointFraction = 0.5,
}: {
  validated: boolean;
  pointFraction?: number;
}) {
  return (
    <div
      style={{
        position: "relative",
        height: 5,
        borderRadius: 3,
        background: "#ececef",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          ...(validated
            ? { background: "rgba(31,138,91,0.5)" }
            : {
                backgroundImage:
                  "repeating-linear-gradient(135deg, rgba(23,24,26,0.35) 0 2px, transparent 2px 7px)",
              }),
        }}
      />
      <span
        aria-hidden
        style={{
          position: "absolute",
          top: -2,
          bottom: -2,
          left: `${Math.min(100, Math.max(0, pointFraction * 100))}%`,
          width: 2,
          background: C.ink,
          transform: "translateX(-1px)",
        }}
      />
    </div>
  );
}

/** A neutral pill button in the light register. */
export function GhostButton({
  children,
  onClick,
  primary,
  disabled,
  title,
  style,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  primary?: boolean;
  disabled?: boolean;
  title?: string;
  style?: React.CSSProperties;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        fontFamily: "inherit",
        fontSize: 12.5,
        fontWeight: primary ? 500 : 400,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        borderRadius: 999,
        padding: "8px 18px",
        border: primary ? "none" : `1px solid #d8d8dc`,
        background: primary ? C.ink : "transparent",
        color: primary ? "#ffffff" : C.ink,
        ...style,
      }}
    >
      {children}
    </button>
  );
}

/** The dashed empty-state frame the design uses for honest absences. */
export function EmptyState({
  title,
  body,
  children,
}: {
  title: string;
  body?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div
      style={{
        border: `1.5px dashed #c9cbd0`,
        borderRadius: 16,
        background: C.panel,
        padding: "34px 30px",
        textAlign: "center",
      }}
    >
      <p style={{ margin: 0, fontSize: 16, fontWeight: 500 }}>{title}</p>
      {body && (
        <p
          style={{
            margin: "8px 0 0",
            fontSize: 12.5,
            lineHeight: 1.6,
            color: C.ink50,
            maxWidth: 460,
            marginInline: "auto",
          }}
        >
          {body}
        </p>
      )}
      {children && <div style={{ marginTop: 14 }}>{children}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
      <span
        aria-hidden
        style={{
          width: 12,
          height: 12,
          borderRadius: "50%",
          border: `2px solid ${C.hair}`,
          borderTopColor: C.ink,
          animation: "vspin 700ms linear infinite",
          display: "inline-block",
        }}
      />
      {label}
    </span>
  );
}
