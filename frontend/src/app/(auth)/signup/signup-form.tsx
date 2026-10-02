"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { safeLocalPath } from "@/lib/safe-return-path";
import { AuthField, AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";
import { authErrorMessage } from "@/lib/api-recovery";

export function SignupForm() {
  const next = safeLocalPath(useSearchParams().get("next"), "/onboarding");
  const [hydrated, setHydrated] = React.useState(false);
  const [email, setEmail] = React.useState("");
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
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(authErrorMessage(res.status, data, "Could not create your account."));
        return;
      }
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
      body="Get 10 free lifetime single-part CAD checks. No credit card or subscription required. Request paid access for more checks or advanced tools."
      footer={<>Already have an account? <AuthTextLink href={`/login?next=${encodeURIComponent(next)}`}>Log in</AuthTextLink></>}
    >
      <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <AuthField id="email" name="email" label="Email" type="email" autoComplete="email" required placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        {/* HTML counts UTF-16 units; allow two per server-validated code point. */}
        <AuthField id="password" name="password" label="Password" type="password" autoComplete="new-password" required maxLength={256} placeholder="Create a password" value={password} error={error} hint="8–128 characters, with a letter and a digit." onChange={(e) => setPassword(e.target.value)} />
        <AuthSubmit loading={loading} disabled={!hydrated}>Create account</AuthSubmit>
      </form>
    </AuthFrame>
  );
}
