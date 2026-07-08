"use client";

import * as React from "react";
import { AuthField, AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const d = data as { detail?: { message?: string }; message?: string };
    return d.detail?.message ?? d.message ?? fallback;
  }
  return fallback;
}

/** Mirror of the server-side policy (the server is the source of truth). */
function passwordProblem(pw: string): string | null {
  if (pw.length < 8) return "Password must be at least 8 characters.";
  if (!/[a-zA-Z]/.test(pw)) return "Password must contain at least one letter.";
  if (!/[0-9]/.test(pw)) return "Password must contain at least one digit.";
  return null;
}

export default function SignupPage() {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const policy = passwordProblem(password);
    if (policy) {
      setError(policy);
      return;
    }
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
        setError(errorMessage(data, "Could not create your account."));
        return;
      }
      // Signed up + auto-logged-in; land on the canonical product workspace.
      window.location.href = "/verify";
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
      body="Email and password works immediately. Enterprise SSO is enabled when a provider is connected."
      footer={
        <>
          Already have an account? <AuthTextLink href="/login">Log in</AuthTextLink>
        </>
      }
    >
      <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <AuthField
          id="email"
          name="email"
          label="Email"
          type="email"
          autoComplete="email"
          required
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <AuthField
          id="password"
          name="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          placeholder="Create a password"
          value={password}
          error={error}
          hint="At least 8 characters, with a letter and a digit."
          onChange={(e) => setPassword(e.target.value)}
        />
        <AuthSubmit loading={loading}>Create account</AuthSubmit>
      </form>
    </AuthFrame>
  );
}
