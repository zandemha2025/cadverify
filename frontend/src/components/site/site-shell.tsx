"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { ArrowUpRight, Box, Menu, X } from "lucide-react";
import { SITE_TAGLINE, SITE_NAV, APP_HOME_HREF, SIGNUP_HREF } from "@/lib/site/navigation";
import { useSignedIn } from "./signed-in";
import { ANALYTICS_PREFERENCES_EVENT } from "@/lib/analytics";
export { SITE_TAGLINE, SITE_NAV, PILOT_HREF, UPLOAD_HREF } from "@/lib/site/navigation";

export type SiteNavProps = { variant?: "cinematic" | "document"; activeHref?: string };
export function SiteNav({ activeHref }: SiteNavProps) {
  const pathname = usePathname();
  const signedIn = useSignedIn();
  const [open, setOpen] = useState(false);
  const active = activeHref ?? pathname;
  return (
    <header className="cv-site-nav">
      <a className="cv-skip" href="#main">Skip to content</a>
      <Link href="/" className="cv-brand" aria-label="ScaleCAD home"><Box size={27} strokeWidth={1.7} aria-hidden="true" />ScaleCAD<span className="cv-brand-dot">.</span></Link>
      <Link href={signedIn ? APP_HOME_HREF : SIGNUP_HREF} className="cv-button cv-button-small cv-nav-cta-mobile">{signedIn ? "Open ScaleCAD" : "Try free"}</Link>
      <button className="cv-menu-toggle" type="button" aria-label={open ? "Close navigation" : "Open navigation"} aria-expanded={open} aria-controls="site-navigation" onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
      <nav id="site-navigation" className="cv-site-links" data-open={open} aria-label="Primary" onClick={() => setOpen(false)} onKeyDown={e => { if (e.key === "Escape") { setOpen(false); document.querySelector<HTMLButtonElement>(".cv-menu-toggle")?.focus(); } }}>
        {SITE_NAV.map(item => <Link key={item.href} href={item.href} aria-current={active === item.href || active?.startsWith(item.href + "/") ? "page" : undefined}>{item.label}</Link>)}
        {signedIn ? (
          <Link href={APP_HOME_HREF} className="cv-button cv-button-small cv-button-secondary">Open ScaleCAD <ArrowUpRight size={16} aria-hidden="true" /></Link>
        ) : <>
          <Link href="/login" className="cv-login-link">Log in</Link>
          <Link href={SIGNUP_HREF} className="cv-button cv-button-small cv-button-cta">Try ScaleCAD free <ArrowUpRight size={16} aria-hidden="true" /></Link>
        </>}
      </nav>
    </header>
  );
}

export function SiteFooter() {
  return <footer className="cv-site-footer"><div className="cv-footer-grid">
    <div><Link href="/" className="cv-brand"><Box size={25} strokeWidth={1.7} aria-hidden="true" />ScaleCAD.</Link><p>{SITE_TAGLINE}</p><a className="cv-text-link" href="mailto:nazeem@scalecad.ai">Talk to our team <ArrowUpRight size={15} aria-hidden="true" /></a></div>
    <nav aria-label="Explore"><h2>Explore</h2><Link href="/sample">Sample part</Link><Link href="/teams">Your workflow</Link><Link href="/method">How it works</Link><Link href="/platform">The platform</Link><Link href="/pricing">Pricing</Link></nav>
    <nav aria-label="Resources"><h2>Resources</h2><Link href="/developers">Developers</Link><Link href="/api-reference">API reference</Link><Link href="/security">Security</Link><Link href="/pilot-report">Pilot report</Link></nav>
    <nav aria-label="Company"><h2>ScaleCAD</h2><Link href="/company">Company</Link><Link href="/contact">Contact</Link><Link href="/pilot">Plan a pilot</Link><Link href="/status">Service status</Link><Link href="/login">Log in</Link></nav>
  </div><div className="cv-footer-bottom"><span>© {new Date().getFullYear()} ScaleCAD</span><nav aria-label="Legal"><Link href="/privacy">Privacy</Link><Link href="/terms">Terms</Link><Link href="/dpa">Data processing</Link><button type="button" className="cv-footer-pref" onClick={() => window.dispatchEvent(new Event(ANALYTICS_PREFERENCES_EVENT))}>Analytics preferences</button></nav><span>Built for decisions that matter.</span></div></footer>;
}

export function SiteFooterTagline({ className }: { className?: string }) {
  return <p className={className}>ScaleCAD — {SITE_TAGLINE}</p>;
}

export function SiteShell({ children }: { children: React.ReactNode }) {
  return <><SiteNav /><main id="main">{children}</main><SiteFooter /></>;
}
