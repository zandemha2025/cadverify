"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { ArrowUpRight, Box, Menu, X } from "lucide-react";
import { SITE_TAGLINE, SITE_NAV } from "@/lib/site/navigation";
export { SITE_TAGLINE, SITE_NAV, PILOT_HREF, UPLOAD_HREF } from "@/lib/site/navigation";

export type SiteNavProps = { variant?: "cinematic" | "document"; activeHref?: string };
export function SiteNav({ activeHref }: SiteNavProps) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const active = activeHref ?? pathname;
  return (
    <header className="cv-site-nav">
      <a className="cv-skip" href="#main">Skip to content</a>
      <Link href="/" className="cv-brand" aria-label="CadVerify home"><Box size={27} strokeWidth={1.7} aria-hidden="true" />CadVerify<span className="cv-brand-dot">.</span></Link>
      <button className="cv-menu-toggle" type="button" aria-label={open ? "Close navigation" : "Open navigation"} aria-expanded={open} aria-controls="site-navigation" onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
      <nav id="site-navigation" className="cv-site-links" data-open={open} aria-label="Primary" onClick={() => setOpen(false)} onKeyDown={e => { if (e.key === "Escape") { setOpen(false); document.querySelector<HTMLButtonElement>(".cv-menu-toggle")?.focus(); } }}>
        {SITE_NAV.map(item => <Link key={item.href} href={item.href} aria-current={active === item.href || active?.startsWith(item.href + "/") ? "page" : undefined}>{item.label}</Link>)}
        <Link href="/login" className="cv-login-link">Log in</Link>
        <Link href="/sample" className="cv-button cv-button-small">Try a sample <ArrowUpRight size={16} aria-hidden="true" /></Link>
      </nav>
    </header>
  );
}

export function SiteFooter() {
  return <footer className="cv-site-footer"><div className="cv-footer-grid">
    <div><Link href="/" className="cv-brand"><Box size={25} strokeWidth={1.7} aria-hidden="true" />CadVerify.</Link><p>{SITE_TAGLINE}</p><a className="cv-text-link" href="mailto:nazeemahmed2023@gmail.com">Talk to our team <ArrowUpRight size={15} aria-hidden="true" /></a></div>
    <nav aria-label="Explore"><h2>Explore</h2><Link href="/sample">Sample part</Link><Link href="/teams">Your workflow</Link><Link href="/method">How it works</Link><Link href="/platform">The platform</Link></nav>
    <nav aria-label="Resources"><h2>Resources</h2><Link href="/developers">Developers</Link><Link href="/api-reference">API reference</Link><Link href="/security">Security</Link><Link href="/pilot-report">Pilot report</Link></nav>
    <nav aria-label="Company"><h2>CadVerify</h2><Link href="/company">Company & contact</Link><Link href="/company#pilot">Plan a pilot</Link><Link href="/status">Service status</Link><Link href="/login">Log in</Link></nav>
  </div><div className="cv-footer-bottom"><span>© {new Date().getFullYear()} CadVerify, Inc.</span><nav aria-label="Legal"><Link href="/privacy">Privacy</Link><Link href="/terms">Terms</Link><Link href="/dpa">Data processing</Link></nav><span>Built for decisions that matter.</span></div></footer>;
}

export function SiteFooterTagline({ className }: { className?: string }) {
  return <p className={className}>CadVerify — {SITE_TAGLINE}</p>;
}

export function SiteShell({ children }: { children: React.ReactNode }) {
  return <><SiteNav /><main id="main">{children}</main><SiteFooter /></>;
}
