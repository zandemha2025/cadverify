"use client";

import * as React from "react";
import { AuthField, AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";
import { authErrorMessage } from "@/lib/api-recovery";

export function SignupForm() {
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
      window.location.href = "/onboarding";
    } catch {
      setError("Could not reach the server. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="Pilot access"
      title="Create your account"
      body="Password signup is live on this deployment. Trial accounts include 20 part checks per account. Email-link sign-in follows when the hosted mail service is connected."
      footer={<>Already have an account? <AuthTextLink href="/login">Log in</AuthTextLink></>}
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
