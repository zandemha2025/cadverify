"use client";

import * as React from "react";
import { LockKeyhole } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function errorMessage(data: unknown): string {
  if (data && typeof data === "object") {
    const d = data as { detail?: { message?: string }; message?: string };
    return d.detail?.message ?? d.message ?? "Could not configure the password.";
  }
  return "Could not configure the password.";
}

function passwordProblem(password: string): string | null {
  if (password.length < 8) return "Password must be at least 8 characters.";
  if (password.length > 128) return "Password must be at most 128 characters.";
  if (!/[A-Za-z]/.test(password)) return "Password must contain a letter.";
  if (!/[0-9]/.test(password)) return "Password must contain a digit.";
  return null;
}

export function SecuritySettingsClient({ hasPassword }: { hasPassword: boolean }) {
  const [currentPassword, setCurrentPassword] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirmation, setConfirmation] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const problem = passwordProblem(password);
    if (problem) {
      setError(problem);
      return;
    }
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/password/initialize", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ password, ...(hasPassword ? { current_password: currentPassword } : {}) }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(errorMessage(data));
        return;
      }
      setPassword("");
      setConfirmation("");
      setCurrentPassword("");
      setSaved(true);
    } catch {
      setError("Could not configure the password. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security"
        subtitle="Set or change the password for this account."
      />
      <Card className="max-w-2xl">
        <CardHeader>
          <div className="flex items-center gap-2">
            <LockKeyhole className="size-4 text-primary" />
            <CardTitle>{hasPassword ? "Change password" : "Initial password"}</CardTitle>
          </div>
          <CardDescription>
            {hasPassword
              ? "Enter your current password to choose a new one. Other dashboard sessions will be signed out."
              : "Set a password for this verified account. Other dashboard sessions will be signed out."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {saved ? (
            <p role="status" className="text-sm text-pass">
              {hasPassword ? "Password changed." : "Password configured."} Older dashboard sessions were revoked.
            </p>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              {hasPassword && (
                <label className="block space-y-1.5 text-sm font-medium">
                  Current password
                  <Input
                    type="password"
                    autoComplete="current-password"
                    maxLength={128}
                    required
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                  />
                </label>
              )}
              <label className="block space-y-1.5 text-sm font-medium">
                New password
                <Input
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  maxLength={128}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <label className="block space-y-1.5 text-sm font-medium">
                Confirm password
                <Input
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  maxLength={128}
                  required
                  value={confirmation}
                  onChange={(e) => setConfirmation(e.target.value)}
                />
              </label>
              {error && <p role="alert" className="text-sm text-fail">{error}</p>}
              <Button type="submit" disabled={loading}>
                {loading ? "Securing account…" : hasPassword ? "Change password" : "Set password"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
