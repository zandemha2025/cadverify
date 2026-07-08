"use client";

import * as React from "react";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { AuthField, AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";

/**
 * Where a fresh login lands when no `next` was requested. Flag-on (D5 FE-3): the
 * A fresh login lands on the canonical light-instrument workspace. Legacy cost
 * and DFM routes remain reachable from inside the app, but they are no longer
 * the product's front door.
 */
const POST_LOGIN_HOME = "/verify";

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const d = data as { detail?: { message?: string }; message?: string };
    return d.detail?.message ?? d.message ?? fallback;
  }
  return fallback;
}

function LoginForm() {
  const params = useSearchParams();
  const next = params.get("next") || POST_LOGIN_HOME;

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(errorMessage(data, "Invalid email or password."));
        return;
      }
      // Hard navigation so the server re-evaluates the new session for the gate.
      window.location.href = next.startsWith("/") ? next : POST_LOGIN_HOME;
    } catch {
      setError("Could not reach the server. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="Secure workspace"
      title="Log in to CadVerify"
      body="Enter the workspace where part, machine, material, and decision records stay auditable."
      footer={
        <>
          New here? <AuthTextLink href="/signup">Create an account</AuthTextLink>
          <br />
          <span className="st-mono" style={{ fontSize: 11, color: "rgba(245,245,247,0.4)" }}>
            SSO appears when provider credentials are configured.
          </span>
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
          autoComplete="current-password"
          required
          placeholder="Your password"
          value={password}
          error={error}
          onChange={(e) => setPassword(e.target.value)}
        />
        <AuthSubmit loading={loading}>Log in</AuthSubmit>
      </form>
    </AuthFrame>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
