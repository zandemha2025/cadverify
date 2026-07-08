"use client";

import * as React from "react";
import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { PublicHeader } from "@/components/ui/public-chrome";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

type State =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "accepted"; orgRole: string; created: boolean }
  | { kind: "login"; token: string }
  | { kind: "error"; message: string };

function detailMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const d = data as { detail?: string | { message?: string }; message?: string };
    if (typeof d.detail === "string") return d.detail;
    return d.detail?.message ?? d.message ?? fallback;
  }
  return fallback;
}

function AcceptInviteInner() {
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [state, setState] = React.useState<State>({ kind: "loading" });

  React.useEffect(() => {
    let alive = true;
    if (!token) {
      setState({ kind: "missing" });
      return;
    }
    void (async () => {
      const res = await fetch("/api/proxy/orgs/invites/accept", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token }),
      }).catch(() => null);
      if (!alive) return;
      if (!res) {
        setState({ kind: "error", message: "Could not reach CadVerify." });
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (res.status === 401 || res.status === 403) {
        setState({ kind: "login", token });
        return;
      }
      if (!res.ok) {
        setState({
          kind: "error",
          message: detailMessage(data, "This invitation could not be accepted."),
        });
        return;
      }
      setState({
        kind: "accepted",
        orgRole: String(data.org_role ?? "member"),
        created: Boolean(data.created),
      });
    })();
    return () => {
      alive = false;
    };
  }, [token]);

  const loginNext = `/login?next=${encodeURIComponent(`/orgs/accept?token=${token}`)}`;

  return (
    <Card className="w-full max-w-md">
      <CardContent className="space-y-6 text-center">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Organization invite
        </p>
        {state.kind === "loading" && (
          <div className="space-y-4">
            <Spinner className="mx-auto" />
            <h1 className="text-2xl font-semibold text-foreground">
              Checking invitation
            </h1>
          </div>
        )}
        {state.kind === "missing" && (
          <>
            <h1 className="text-2xl font-semibold text-foreground">
              Invite token missing.
            </h1>
            <p className="text-sm leading-6 text-muted-foreground">
              Open the exact link your CadVerify admin sent. Tokens are single-use and never guessed here.
            </p>
          </>
        )}
        {state.kind === "login" && (
          <>
            <h1 className="text-2xl font-semibold text-foreground">
              Log in as the invited account.
            </h1>
            <p className="text-sm leading-6 text-muted-foreground">
              The backend binds invites to the invited account. Sign in, then this page will redeem the token.
            </p>
            <Button asChild>
              <Link href={loginNext}>Log in to accept</Link>
            </Button>
          </>
        )}
        {state.kind === "accepted" && (
          <>
            <h1 className="text-2xl font-semibold text-foreground">
              Invitation accepted.
            </h1>
            <p className="text-sm leading-6 text-muted-foreground">
              {state.created
                ? `You joined the organization as ${state.orgRole}.`
                : `You were already a member; the invite was consumed without changing your role (${state.orgRole}).`}
            </p>
            <Button asChild>
              <Link href="/verify">Open CadVerify</Link>
            </Button>
          </>
        )}
        {state.kind === "error" && (
          <>
            <h1 className="text-2xl font-semibold text-foreground">
              Invite not accepted.
            </h1>
            <p className="text-sm leading-6 text-muted-foreground">
              {state.message}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function AcceptInvitePage() {
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <PublicHeader showCta={false} />
      <main className="flex flex-1 items-center justify-center px-4 py-16">
        <Suspense fallback={<Spinner />}>
          <AcceptInviteInner />
        </Suspense>
      </main>
    </div>
  );
}
