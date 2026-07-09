"use client";

import Link from "next/link";
import type { CSSProperties, InputHTMLAttributes, ReactNode } from "react";

const panel = {
  width: "min(430px, calc(100vw - 32px))",
  border: "1px solid rgba(245,245,247,0.12)",
  borderRadius: 18,
  background: "#0b0c0f",
  padding: 32,
  boxShadow: "0 30px 90px -44px rgba(0,0,0,0.9)",
} satisfies CSSProperties;

const label = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  fontFamily: "var(--st-font-mono)",
  fontSize: 10,
  letterSpacing: "0.1em",
  textTransform: "uppercase",
  color: "rgba(245,245,247,0.48)",
} satisfies CSSProperties;

const input = {
  width: "100%",
  border: "1px solid rgba(245,245,247,0.16)",
  borderRadius: 8,
  background: "#07080a",
  color: "#f5f5f7",
  padding: "13px 14px",
  fontFamily: "var(--st-font-sans)",
  fontSize: 14,
  // NOTE: focus styling lives in the `.auth-input` rule in globals.css — a
  // `:focus-visible` ring can't be expressed inline, and an inline `outline:none`
  // here would win over any stylesheet rule and re-suppress it (WCAG 2.4.7 / F3).
} satisfies CSSProperties;

export function AuthFrame({
  eyebrow,
  title,
  body,
  children,
  footer,
}: {
  eyebrow: string;
  title: string;
  body: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "#050506" }}>
      <header style={{ borderBottom: "1px solid rgba(245,245,247,0.08)" }}>
        <div style={{ maxWidth: 1180, margin: "0 auto", height: 62, padding: "0 24px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 18 }}>
          <Link href="/" style={{ color: "#f5f5f7", textDecoration: "none", fontSize: 17, letterSpacing: "-0.01em" }}>
            CadVerify
          </Link>
          <Link href="/company" className="st-mono" style={{ color: "rgba(245,245,247,0.56)", textDecoration: "none", fontSize: 11 }}>
            PILOT ACCESS
          </Link>
        </div>
      </header>
      <main style={{ flex: 1, display: "grid", placeItems: "center", padding: "54px 16px" }}>
        <section style={panel}>
          <p className="st-eyebrow" style={{ margin: 0 }}>{eyebrow}</p>
          <h1 className="st-display" style={{ margin: "16px 0 0", fontSize: 32, lineHeight: 1.1 }}>
            {title}
          </h1>
          <p style={{ margin: "12px 0 0", color: "rgba(245,245,247,0.58)", fontSize: 14, lineHeight: 1.7 }}>
            {body}
          </p>
          <div style={{ marginTop: 26 }}>{children}</div>
          {footer && (
            <div style={{ marginTop: 22, textAlign: "center", color: "rgba(245,245,247,0.48)", fontSize: 13, lineHeight: 1.6 }}>
              {footer}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export function AuthField({
  label: labelText,
  error,
  hint,
  ...props
}: {
  label: string;
  error?: string | null;
  hint?: string;
} & InputHTMLAttributes<HTMLInputElement>) {
  const helpId = props.id ? `${props.id}-help` : undefined;
  return (
    <label style={label}>
      <span>{labelText}</span>
      <input
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={helpId}
        className="auth-input"
        style={input}
      />
      {(error || hint) && (
        <span id={helpId} style={{ letterSpacing: 0, textTransform: "none", color: error ? "#f08f86" : "rgba(245,245,247,0.42)", lineHeight: 1.5 }}>
          {error || hint}
        </span>
      )}
    </label>
  );
}

export function AuthSubmit({
  children,
  loading,
}: {
  children: ReactNode;
  loading?: boolean;
}) {
  return (
    <button
      type="submit"
      disabled={loading}
      style={{
        width: "100%",
        minHeight: 44,
        border: "none",
        borderRadius: 999,
        background: loading ? "rgba(245,245,247,0.56)" : "#f5f5f7",
        color: "#050506",
        fontFamily: "var(--st-font-sans)",
        fontSize: 14,
        fontWeight: 500,
        cursor: loading ? "wait" : "pointer",
      }}
    >
      {loading ? "Working..." : children}
    </button>
  );
}

export function AuthTextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} style={{ color: "#f5f5f7", textDecoration: "none", borderBottom: "1px solid rgba(245,245,247,0.28)" }}>
      {children}
    </Link>
  );
}
