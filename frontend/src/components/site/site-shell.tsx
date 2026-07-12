"use client";

/**
 * SiteShell — the shared nav + footer chrome for the dark-theater marketing
 * site. Every page cross-links through these; the footer tagline everywhere is
 * "verification, made of glass" (DESIGN-DECISIONS.md / README.md).
 *
 * Ported from the shared header/footer across
 * `handoff_cadverify_2026-07-04/site/*.dc.html`. Two nav variants:
 *  - `cinematic` — fixed, transparent, fades in over the WebGL stage (home +
 *    the five persona journeys).
 *  - `document` — sticky, blurred bar (Method / Platform / Teams / Security /
 *    Developers / Company).
 *
 * `SiteShell` is the convenience wrapper for document pages (nav + main +
 * footer). Cinematic pages compose `<SiteNav variant="cinematic" />` themselves
 * so the fixed WebGL stage can sit behind the content, then close with
 * `<SiteFooter />` or an inline `<SiteFooterTagline />`.
 *
 * SHARED FOUNDATION — do not edit in a page branch.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

/** The footer tagline, verbatim, everywhere. */
export const SITE_TAGLINE = "verification, made of glass";

/** Where the primary CTA points (the pilot form anchor on Company). */
export const PILOT_HREF = "/company#pilot";

/** The canonical top-nav, in order. Personas live under /teams/* (see Teams). */
export const SITE_NAV: { href: string; label: string }[] = [
  { href: "/method", label: "Method" },
  { href: "/platform", label: "Platform" },
  { href: "/teams", label: "Teams" },
  { href: "/security", label: "Security" },
  { href: "/developers", label: "Developers" },
  { href: "/company", label: "Company" },
];

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === "/") return pathname === "/";
  // /teams stays lit for the persona journeys nested under it.
  return pathname === href || pathname.startsWith(href + "/");
}

export type SiteNavProps = {
  variant?: "cinematic" | "document";
  /** Override the active link (defaults to the current pathname). */
  activeHref?: string;
};

/** The shared top nav. Wordmark → home; links + "Request a pilot" CTA. */
export function SiteNav({ variant = "document", activeHref }: SiteNavProps) {
  const pathname = usePathname();
  const active = activeHref ?? pathname;
  const closeMobileNav = (event: React.MouseEvent<HTMLAnchorElement>) => {
    const details = event.currentTarget.closest("details");
    if (details instanceof HTMLDetailsElement) details.open = false;
  };
  return (
    <header className={`st-nav ${variant === "cinematic" ? "st-nav-cinematic" : "st-nav-document"}`}>
      <Link href="/" className="st-wordmark">
        CadVerify
      </Link>
      <nav className="st-navrow" aria-label="Primary">
        {SITE_NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="st-navlink"
            data-active={isActive(active, item.href)}
          >
            {item.label}
          </Link>
        ))}
        <Link href="/login" className="st-navlink st-navlogin">
          Log in
        </Link>
        <Link href={PILOT_HREF} className="st-navcta">
          Request a pilot
        </Link>
      </nav>
      <details
        className="st-mobile-nav"
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.currentTarget.open = false;
          event.currentTarget.querySelector("summary")?.focus();
        }}
      >
        <summary className="st-nav-toggle" aria-label="Open site navigation">
          <span>Menu</span>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
            <path d="M5 8h14M5 16h14" />
          </svg>
        </summary>
        <nav className="st-mobile-panel" aria-label="Mobile primary">
          {SITE_NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="st-mobile-link"
              data-active={isActive(active, item.href)}
              onClick={closeMobileNav}
            >
              {item.label}
            </Link>
          ))}
          <Link href="/login" className="st-mobile-link" onClick={closeMobileNav}>
            Log in
          </Link>
          <Link href={PILOT_HREF} className="st-mobile-cta" onClick={closeMobileNav}>
            Request a pilot
          </Link>
        </nav>
      </details>
    </header>
  );
}

/** The one full footer: tagline + cross-links + legal row. */
export function SiteFooter() {
  return (
    <footer className="st-footer">
      <div className="st-footer-row">
        <span className="st-footer-tagline">CadVerify — {SITE_TAGLINE}</span>
        <span className="st-footer-links">
          <Link href="/">Home</Link>
          {SITE_NAV.map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
          <Link href="/login">Log in</Link>
        </span>
      </div>
      <div className="st-footer-legal">
        <span>© {new Date().getFullYear()} CadVerify, Inc.</span>
        <span className="st-footer-links">
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/dpa">DPA</Link>
          <Link href="/status">Status</Link>
        </span>
      </div>
    </footer>
  );
}

/**
 * The minimal inline tagline line the cinematic pages close with (home + the
 * personas), e.g. "CadVerify — verification, made of glass · Method · …".
 */
export function SiteFooterTagline({ className }: { className?: string }) {
  return (
    <p className={`st-footer-tagline ${className ?? ""}`} style={{ margin: 0 }}>
      CadVerify — {SITE_TAGLINE}
      {SITE_NAV.filter((n) => ["/method", "/platform", "/security", "/developers"].includes(n.href)).map((n) => (
        <React.Fragment key={n.href}>
          {" · "}
          <Link href={n.href} style={{ color: "inherit", textDecoration: "none" }}>
            {n.label}
          </Link>
        </React.Fragment>
      ))}
    </p>
  );
}

/** Document-page convenience wrapper: sticky nav + main + full footer. */
export function SiteShell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <SiteNav variant="document" />
      <main style={{ flex: 1 }}>{children}</main>
      <SiteFooter />
    </div>
  );
}
