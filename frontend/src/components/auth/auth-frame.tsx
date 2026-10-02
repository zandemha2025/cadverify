"use client";

import Link from "next/link";
import { SiteNav } from "@/components/site/site-shell";
import type { ButtonHTMLAttributes, CSSProperties, InputHTMLAttributes, ReactNode } from "react";

const panel = {
  width: "min(430px, calc(100vw - 32px))",
  border: "1px solid #dbe1da",
  borderRadius: 8,
  background: "#ffffff",
  padding: 32,
} satisfies CSSProperties;

const label = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  fontFamily: "var(--font-geist-sans), sans-serif",
  fontSize: 13,
  letterSpacing: 0,
  color: "#53635a",
} satisfies CSSProperties;

const input = {
  width: "100%",
  border: "1px solid #aab8a8",
  borderRadius: 8,
  background: "#ffffff",
  color: "#183d32",
  padding: "13px 14px",
  fontFamily: "var(--font-geist-sans), sans-serif",
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
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "#fbfcfa", color: "#183d32", fontFamily: "var(--font-geist-sans), sans-serif" }}>
      <SiteNav />
      <main id="main" style={{ flex: 1, display: "grid", placeItems: "center", padding: "54px 16px" }}>
        <section style={panel}>
          <p style={{ margin: 0, color: "#53635a", fontSize: 13 }}>{eyebrow}</p>
          <h1 style={{ margin: "16px 0 0", fontFamily: "var(--font-archivo), sans-serif", fontSize: 32, lineHeight: 1.1 }}>
            {title}
          </h1>
          <p style={{ margin: "12px 0 0", color: "#53635a", fontSize: 14, lineHeight: 1.7 }}>
            {body}
          </p>
          <div style={{ marginTop: 26 }}>{children}</div>
          {footer && (
            <div style={{ marginTop: 22, textAlign: "center", color: "#53635a", fontSize: 13, lineHeight: 1.6 }}>
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
  id: string;
  label: string;
  error?: string | null;
  hint?: string;
} & InputHTMLAttributes<HTMLInputElement>) {
  const helpId = props.id ? `${props.id}-help` : undefined;
  return (
    <div style={label}>
      <label htmlFor={props.id}>{labelText}</label>
      <input
        {...props}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? helpId : undefined}
        className="auth-input"
        style={input}
      />
      {(error || hint) && (
        <span id={helpId} style={{ letterSpacing: 0, textTransform: "none", color: error ? "#b42318" : "#53635a", lineHeight: 1.5 }}>
          {error || hint}
        </span>
      )}
    </div>
  );
}

export function AuthSubmit({
  children,
  loading,
  ...props
}: {
  children: ReactNode;
  loading?: boolean;
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children">) {
  const disabled = Boolean(loading || props.disabled);
  return (
    <button
      {...props}
      type={props.type ?? "submit"}
      disabled={disabled}
      style={{
        width: "100%",
        minHeight: 44,
        border: "none",
        borderRadius: 5,
        background: disabled ? "#697f70" : "#183d32",
        color: "#ffffff",
        fontFamily: "var(--font-geist-sans), sans-serif",
        fontSize: 14,
        fontWeight: 500,
        cursor: loading ? "wait" : disabled ? "not-allowed" : "pointer",
        ...props.style,
      }}
    >
      {loading ? "Working..." : children}
    </button>
  );
}

export function AuthTextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} style={{ color: "#183d32", textDecoration: "none", borderBottom: "1px solid #183d32" }}>
      {children}
    </Link>
  );
}
