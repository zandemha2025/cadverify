"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, Mail } from "lucide-react";
import { TurnstileWidget } from "@/components/auth/turnstile-widget";
import { authErrorMessage } from "@/lib/api-recovery";
import { emailTier } from "@/lib/site/email-tier";
import { SiteCta, useSiteSession } from "./site-shell";

export function SignupEmailForm() {
  const { user, siteKey, nonce, ssoLoginPath } = useSiteSession();
  const id = useId();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [reset, setReset] = useState(0);
  const tier = emailTier(email);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!tier || busy) return;
    if (!token) { setError("Complete the security check first."); return; }
    setBusy(true); setError(null);
    try {
      const res = await fetch("/api/auth/magic/start", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: email.trim(), turnstileToken: token }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(authErrorMessage(res.status, data, "Could not send a sign-in link."));
      setSent(true);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not send a sign-in link. Please try again."); setToken(null); setReset(value => value + 1); }
    finally { setBusy(false); }
  }
  if (user) return <div className="cv-signup-card"><SiteCta /><Link href="/history">View your saved checks</Link></div>;
  return <div className="cv-signup-card">
    {sent ? <div role="status" className="cv-signup-sent"><Mail size={44} aria-hidden="true" /><h2>Check your inbox.</h2><p>We sent a sign-in link to <strong>{email.trim()}</strong>. Click it to open ScaleCAD with {tier === "personal" ? 3 : 15} free checks. Not there? Check your spam folder or try another address.</p><button className="cv-button cv-button-secondary" type="button" onClick={() => { setSent(false); setEmail(""); setToken(null); }}>Use a different email</button></div> : <>
      <form onSubmit={submit}>
        <label htmlFor={id}>Work email</label>
        <input id={id} name="email" type="email" autoComplete="email" required maxLength={320} placeholder="you@company.com" value={email} onChange={event => setEmail(event.target.value)} aria-describedby={`${id}-tier`} />
        <p id={`${id}-tier`} className="cv-email-tier" data-tier={tier || "empty"} aria-live="polite">{tier === "personal" ? <><strong>Personal email: 3 free checks.</strong> Use your work email to start with 15.</> : tier === "work" ? <><Check size={16} aria-hidden="true" /><strong>Work email: 15 free checks.</strong></> : "Work emails get 15 free checks. Personal emails get 3."}</p>
        {siteKey ? <TurnstileWidget siteKey={siteKey} nonce={nonce} resetSignal={reset} onToken={setToken} /> : <p>Email sign-up is unavailable in this environment. <Link href="/login">Log in</Link> or <Link href="/contact">contact us</Link>.</p>}
        {error && <p role="alert">{error}</p>}
        <button className="cv-button" type="submit" disabled={!siteKey || !token || busy}>{busy ? "Sending…" : "Try ScaleCAD free"}<ArrowRight size={16} aria-hidden="true" /></button>
        <p className="cv-signup-terms">No password. No credit card. By continuing you agree to the <Link href="/terms">Terms</Link> and <Link href="/privacy">Privacy Policy</Link>.</p>
      </form>
      <div className="cv-signup-links"><span>Have an account? <Link href="/login">Log in</Link></span>{ssoLoginPath && <a href={ssoLoginPath}>Sign in with your company account</a>}</div>
    </>}
  </div>;
}
