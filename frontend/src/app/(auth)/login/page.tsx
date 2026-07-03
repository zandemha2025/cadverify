"use client";

import * as React from "react";
import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { browserOrBackendUrl } from "@/lib/api-base";
import { STAGE_UI } from "@/lib/stage-flag";
import { PublicHeader } from "@/components/ui/public-chrome";

/**
 * Where a fresh login lands when no `next` was requested. Flag-on (D5 FE-3): the
 * three-door landing router at /cost, so the door chooser can greet a first-run
 * user. Flag-off: today's /analyze. `STAGE_UI` is a compile-time constant, so
 * this folds to "/analyze" and behaviour is byte-identical when the flag is off.
 */
const POST_LOGIN_HOME = STAGE_UI ? "/cost" : "/analyze";
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
    <Card className="w-full max-w-sm">
      <CardContent className="space-y-6">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold text-foreground">
            Log in to CadVerify
          </h1>
          <p className="text-sm text-muted-foreground">
            Welcome back. Enter your email and password.
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
          <Field label="Password" htmlFor="password" error={error}>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              placeholder="Your password"
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
            Log in
          </Button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          New here?{" "}
          <Link href="/signup" className="font-medium text-primary hover:underline">
            Create an account
          </Link>
        </p>

        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-border" />
          or
          <span className="h-px flex-1 bg-border" />
        </div>

        {/* Secondary providers — deploy-gated (need provider credentials). */}
        <Button asChild variant="secondary" className="w-full">
          <a href={browserOrBackendUrl("/auth/google/start")}>
            Continue with Google
          </a>
        </Button>
        <p className="text-center text-xs text-muted-foreground">
          Google / SSO / magic-link require server credentials.
        </p>
      </CardContent>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <PublicHeader showCta={false} />
      <main className="flex flex-1 items-center justify-center px-4 py-16">
        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>
      </main>
    </div>
  );
}
