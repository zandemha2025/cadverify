"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { safeLocalPath } from "@/lib/safe-return-path";
import { AuthField, AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";
import { SignupDataNote } from "@/components/site/signup-data-note";
import { authErrorMessage } from "@/lib/api-recovery";
import { identifyAccount, signupMetadata, track } from "@/lib/analytics";

export function SignupForm({ freeChecks }: { freeChecks?: { work: number; personal: number } }) {
  const next = safeLocalPath(useSearchParams().get("next"), "/onboarding");
  const [hydrated, setHydrated] = React.useState(false);
  const [email, setEmail] = React.useState("");
  const [name, setName] = React.useState("");
  const [phone, setPhone] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => setHydrated(true), []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password, name, phone, ...signupMetadata() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(authErrorMessage(res.status, data, "Could not create your account."));
        return;
      }
      identifyAccount(data.user.id);
      track("signup_completed", { auth_provider: "password" });
      window.location.href = next;
    } catch {
      setError("Could not connect. Please try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="Free account"
      title="Create your account"
      body={`Free to start: ${freeChecks?.work ?? 15} checks with a work email, ${freeChecks?.personal ?? 3} with a personal one. No credit card.`}
      footer={<>Already have an account? <AuthTextLink href={`/login?next=${encodeURIComponent(next)}`}>Log in</AuthTextLink><span style={{ display: "block", marginTop: 10, fontSize: 12, lineHeight: 1.5 }}><SignupDataNote /></span></>}
    >
      <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <AuthField id="name" name="name" label="Full name" type="text" autoComplete="name" required maxLength={160} placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
        <AuthField id="email" name="email" label="Email" type="email" autoComplete="email" required placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <AuthField id="phone" name="phone" label="Phone number (optional)" type="tel" autoComplete="tel" maxLength={32} placeholder="+1 555 123 4567" value={phone} onChange={(e) => setPhone(e.target.value)} />
        {/* HTML counts UTF-16 units; allow two per server-validated code point. */}
        <AuthField id="password" name="password" label="Password" type="password" autoComplete="new-password" required maxLength={256} placeholder="Create a password" value={password} error={error} hint="8–128 characters, with a letter and a digit." onChange={(e) => setPassword(e.target.value)} />
        <AuthSubmit loading={loading} disabled={!hydrated}>Create account</AuthSubmit>
      </form>
    </AuthFrame>
  );
}
