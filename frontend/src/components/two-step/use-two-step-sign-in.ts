"use client";

/**
 * The second step of a sign-in: the page reads what the challenge asks for
 * (a code, or setting two-step up because an organization requires it) and
 * posts the code through /api/auth/two-step/*, which holds the challenge in an
 * httpOnly cookie and sets the session cookie itself when the code is right.
 */
import * as React from "react";
import { errorCode, twoStepError } from "./parts";

export type ChallengeState = {
  purpose: "verify" | "setup";
  method: "password" | "email_link" | "google";
  email: string;
  required_by: string[];
  recovery_codes_left: number;
  expires_in_seconds: number;
};

export type Enrolment = { manual_key: string; otpauth_uri: string; qr: string[]; account: string };

type Phase =
  | { kind: "loading" }
  | { kind: "expired"; message: string }
  | { kind: "verify" }
  | { kind: "setup"; enrolment: Enrolment | null }
  | { kind: "codes"; codes: string[] };

async function post(action: string, body?: unknown): Promise<{ res: Response; data: unknown }> {
  const res = await fetch(`/api/auth/two-step/${action}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return { res, data: await res.json().catch(() => ({})) };
}

export function useTwoStepSignIn({ onDone }: { onDone: (used: "code" | "recovery" | "setup") => void }) {
  const [state, setState] = React.useState<ChallengeState | null>(null);
  const [phase, setPhase] = React.useState<Phase>({ kind: "loading" });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const { res, data } = await post("state");
        if (!live) return;
        if (!res.ok) {
          setPhase({ kind: "expired", message: twoStepError(res.status, data, "This sign-in expired. Sign in again.") });
          return;
        }
        const s = data as ChallengeState;
        setState(s);
        if (s.purpose === "verify") {
          setPhase({ kind: "verify" });
          return;
        }
        setPhase({ kind: "setup", enrolment: null });
        const started = await post("setup");
        if (!live) return;
        if (!started.res.ok) {
          setError(twoStepError(started.res.status, started.data, "Couldn't start the setup. Reload the page."));
          return;
        }
        setPhase({ kind: "setup", enrolment: started.data as Enrolment });
      } catch {
        if (live) setPhase({ kind: "expired", message: "Couldn't reach the sign-in service. Sign in again." });
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  async function submit(action: "verify" | "setup-confirm", body: Record<string, string>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { res, data } = await post(action, body);
      if (!res.ok) {
        const code = errorCode(data);
        if (code === "two_step_challenge_invalid" || code === "account_deactivated") {
          setPhase({ kind: "expired", message: twoStepError(res.status, data, "This sign-in expired. Sign in again.") });
        } else {
          setError(twoStepError(res.status, data, "That code didn't work. Try the newest code."));
        }
        return;
      }
      if (action === "setup-confirm") {
        const codes = (data as { recovery_codes?: unknown }).recovery_codes;
        setPhase({ kind: "codes", codes: Array.isArray(codes) ? codes.filter((c): c is string => typeof c === "string") : [] });
        return;
      }
      onDone((data as { used?: string }).used === "recovery" ? "recovery" : "code");
    } catch {
      setError("Couldn't reach the sign-in service. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return {
    state,
    phase,
    busy,
    error,
    setError,
    verify: (body: { code?: string; recovery_code?: string }) => submit("verify", body as Record<string, string>),
    confirmSetup: (code: string) => submit("setup-confirm", { code }),
    finishSetup: () => onDone("setup"),
  };
}
