"use client";

import * as React from "react";
import Link from "next/link";
import Script from "next/script";
import { browserOrBackendUrl } from "@/lib/api-base";
import { startMagic } from "./actions";
import { PublicHeader } from "@/components/ui/public-chrome";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/field";
import { Card, CardContent } from "@/components/ui/card";

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
  const sitekey =
    process.env.NEXT_PUBLIC_TURNSTILE_SITEKEY?.replace(/\\[rn]/g, "").trim() ||
    "";

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
      // Signed up + auto-logged-in; land on the platform.
      window.location.href = "/analyze";
    } catch {
      setError("Could not reach the server. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <PublicHeader showCta={false} />
      <main className="flex flex-1 items-center justify-center px-4 py-16">
        <Card className="w-full max-w-sm">
          <CardContent className="space-y-6">
            <div className="space-y-1">
              <h1 className="text-xl font-semibold text-foreground">
                Create your account
              </h1>
              <p className="text-sm text-muted-foreground">
                Email + password — works immediately, no external setup.
              </p>
            </div>

            <form onSubmit={onSubmit} className="space-y-4">
              <Field label="Email" htmlFor="email">
                <Input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
              <Field
                label="Password"
                htmlFor="password"
                error={error}
                hint="At least 8 characters, with a letter and a digit."
              >
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  required
                  placeholder="Create a password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
              <Button
                type="submit"
                variant="primary"
                className="w-full"
                loading={loading}
              >
                Create account
              </Button>
            </form>

            <p className="text-center text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link href="/login" className="font-medium text-primary hover:underline">
                Log in
              </Link>
            </p>

            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="h-px flex-1 bg-border" />
              or
              <span className="h-px flex-1 bg-border" />
            </div>

            {/* Secondary / enterprise options — deploy-gated (need credentials). */}
            <Button asChild variant="secondary" className="w-full">
              <a href={browserOrBackendUrl("/auth/google/start")}>
                Continue with Google
              </a>
            </Button>

            <form action={startMagic} className="space-y-3">
              <Input
                name="email"
                type="email"
                required
                placeholder="you@company.com"
              />
              <Script
                src="https://challenges.cloudflare.com/turnstile/v0/api.js"
                async
                defer
              />
              <div className="cf-turnstile" data-sitekey={sitekey} />
              <Button type="submit" variant="ghost" className="w-full">
                Email me a magic link
              </Button>
            </form>
            <p className="text-center text-xs text-muted-foreground">
              Google / SSO / magic-link require server credentials.
            </p>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
