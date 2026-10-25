"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, Menu, UserRound, X } from "lucide-react";
import { SITE_TAGLINE, SITE_NAV, APP_HOME_HREF, SIGNUP_HREF } from "@/lib/site/navigation";
import { authErrorMessage } from "@/lib/api-recovery";
import { ANALYTICS_PREFERENCES_EVENT } from "@/lib/analytics";
export { SITE_TAGLINE, SITE_NAV, PILOT_HREF, UPLOAD_HREF } from "@/lib/site/navigation";

export type SiteSession = { user: { email: string } | null; usage: { cap: number; remaining: number } | null; siteKey: string; nonce?: string; ssoLoginPath: string; freeChecks: { work: number; personal: number } };
const SiteSessionContext = createContext<SiteSession>({ user: null, usage: null, siteKey: "", ssoLoginPath: "", freeChecks: { work: 15, personal: 3 } });
export const SiteSessionProvider = SiteSessionContext.Provider;
export const useSiteSession = () => useContext(SiteSessionContext);

export function SiteMark() {
  return <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden="true"><rect x="10" y="2" width="8" height="5" rx="1" fill="currentColor" /><rect x="7" y="8" width="14" height="5" rx="1" fill="currentColor" /><rect x="2" y="14" width="24" height="5" rx="1" fill="#FF5B1F" /><rect x="9" y="20" width="10" height="6" rx="1" fill="currentColor" /></svg>;
}

export function SiteCta({ className = "cv-button", children }: { className?: string; children?: React.ReactNode }) {
  const { user } = useSiteSession();
  const pathname = usePathname();
  return <Link className={className} href={user ? APP_HOME_HREF : pathname === "/" ? "#start" : SIGNUP_HREF}>{user ? <>Open ScaleCAD <ArrowRight size={16} aria-hidden="true" /></> : children || <>Try ScaleCAD free <ArrowRight size={16} aria-hidden="true" /></>}</Link>;
}

export type SiteNavProps = { variant?: "cinematic" | "document"; activeHref?: string };
export function SiteNav({ activeHref }: SiteNavProps) {
  const pathname = usePathname();
  const { user, usage } = useSiteSession();
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const active = activeHref ?? pathname;
  async function logout() {
    setLogoutError(null);
    try {
      const res = await fetch("/api/auth/logout", { method: "POST" });
      if (!res.ok) throw new Error(authErrorMessage(res.status, await res.json().catch(() => ({})), "Could not log out. Please try again."));
      router.push("/");
      router.refresh();
    } catch (error) { setLogoutError(error instanceof Error ? error.message : "Could not log out. Please try again."); }
  }
  return <header className="cv-site-nav" data-signed-in={!!user} onKeyDown={event => { if (event.key === "Escape") { setOpen(false); toggle.current?.focus(); } }}>
    <a className="cv-skip" href="#main">Skip to content</a>
    <Link href="/" className="cv-brand" aria-label="ScaleCAD home"><SiteMark />ScaleCAD</Link>
    <nav id="site-navigation" className="cv-site-links" data-open={open} aria-label="Primary" onClick={() => setOpen(false)}>
      {SITE_NAV.map(item => <Link key={item.href} href={item.href} aria-current={active === item.href || active?.startsWith(item.href + "/") ? "page" : undefined}>{item.label}</Link>)}
      {!user && <Link href="/login" className="cv-mobile-login">Log in</Link>}
    </nav>
    <div className="cv-nav-actions">
      {user ? <>
        {usage && <span className="cv-checks">{usage.remaining} of {usage.cap} checks left</span>}
        <SiteCta className="cv-button cv-button-small cv-button-ink" />
        <details className="cv-account"><summary aria-label="Account"><UserRound size={18} aria-hidden="true" /></summary><div><span>{user.email}</span><Link href="/settings">Account settings</Link><button type="button" onClick={logout}>Log out</button>{logoutError && <p role="alert">{logoutError}</p>}</div></details>
      </> : <><Link href="/login" className="cv-login-link">Log in</Link><SiteCta className="cv-button cv-button-small" /></>}
      <button ref={toggle} className="cv-menu-toggle" type="button" aria-label={open ? "Close navigation" : "Open navigation"} aria-expanded={open} aria-controls="site-navigation" onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
    </div>
  </header>;
}

export function SiteFooter() {
  return <footer className="cv-site-footer"><div className="cv-footer-grid">
    <div><Link href="/" className="cv-brand"><SiteMark />ScaleCAD</Link><p>{SITE_TAGLINE}</p><SiteCta /><a className="cv-text-link" href="mailto:nazeem@scalecad.ai">Talk to our team <ArrowUpRight size={15} aria-hidden="true" /></a></div>
    <nav aria-label="Explore"><h2>Explore</h2><Link href="/sample">Sample part</Link><Link href="/teams">Your workflow</Link><Link href="/method">How it works</Link><Link href="/platform">The platform</Link><Link href="/pricing">Pricing</Link></nav>
    <nav aria-label="Teams"><h2>Teams</h2><Link href="/teams/in-house-manufacturing">In-house manufacturing</Link><Link href="/teams/design-engineering">Design engineering</Link><Link href="/teams/cost-engineering">Cost engineering</Link><Link href="/teams/sourcing">Sourcing</Link><Link href="/teams/shop-owners">Shop owners</Link></nav><nav aria-label="Resources"><h2>Resources</h2><Link href="/developers">Developers</Link><Link href="/api-reference">API reference</Link><Link href="/security">Security</Link><Link href="/pilot-report">Pilot report</Link></nav>
    <nav aria-label="Company"><h2>ScaleCAD</h2><Link href="/company">Company</Link><Link href="/contact">Contact</Link><Link href="/pilot">Plan a pilot</Link><Link href="/status">Service status</Link><Link href="/login">Log in</Link></nav>
  </div><div className="cv-footer-bottom"><span>© {new Date().getFullYear()} ScaleCAD</span><nav aria-label="Legal"><Link href="/privacy">Privacy</Link><Link href="/terms">Terms</Link><Link href="/dpa">Data processing</Link><button type="button" className="cv-footer-pref" onClick={() => window.dispatchEvent(new Event(ANALYTICS_PREFERENCES_EVENT))}>Privacy choices</button></nav><span>Built for decisions that matter.</span></div><div className="cv-footer-wordmark" aria-hidden="true">ScaleCAD</div></footer>;
}

export function SiteFooterTagline({ className }: { className?: string }) {
  return <p className={className}>ScaleCad — {SITE_TAGLINE}</p>;
}

export function SiteShell({ children }: { children: React.ReactNode }) {
  return <><SiteNav /><main id="main">{children}</main><SiteFooter /></>;
}
