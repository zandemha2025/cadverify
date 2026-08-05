"use client";

import * as React from "react";
import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { AuthFrame } from "@/components/auth/auth-frame";
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
        setState({ kind: "error", message: "Could not reach ProofShape." });
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
    <div style={{ display: "flex", flexDirection: "column", gap: 18, textAlign: "center" }}>
        {state.kind === "loading" && (
          <div className="space-y-4">
            <Spinner className="mx-auto" />
            <h2 style={{ margin: 0, color: "#f5f5f7", fontSize: 22, fontWeight: 400 }}>
              Checking invitation
            </h2>
          </div>
        )}
        {state.kind === "missing" && (
          <>
            <h2 style={{ margin: 0, color: "#f5f5f7", fontSize: 22, fontWeight: 400 }}>
              Invite token missing.
            </h2>
            <p style={{ margin: 0, color: "rgba(245,245,247,0.58)", fontSize: 14, lineHeight: 1.7 }}>
              Open the exact link your ProofShape admin sent. Tokens are single-use and never guessed here.
            </p>
          </>
        )}
        {state.kind === "login" && (
          <>
            <h2 style={{ margin: 0, color: "#f5f5f7", fontSize: 22, fontWeight: 400 }}>
              Log in as the invited account.
            </h2>
            <p style={{ margin: 0, color: "rgba(245,245,247,0.58)", fontSize: 14, lineHeight: 1.7 }}>
              The backend binds invites to the invited account. Sign in, then this page will redeem the token.
            </p>
            <PrimaryLink href={loginNext}>Log in to accept</PrimaryLink>
          </>
        )}
        {state.kind === "accepted" && (
          <>
            <h2 style={{ margin: 0, color: "#f5f5f7", fontSize: 22, fontWeight: 400 }}>
              Invitation accepted.
            </h2>
            <p style={{ margin: 0, color: "rgba(245,245,247,0.58)", fontSize: 14, lineHeight: 1.7 }}>
              {state.created
                ? `You joined the organization as ${state.orgRole}.`
                : `You were already a member; the invite was consumed without changing your role (${state.orgRole}).`}
            </p>
            <PrimaryLink href="/verify">Open ProofShape</PrimaryLink>
          </>
        )}
        {state.kind === "error" && (
          <>
            <h2 style={{ margin: 0, color: "#f5f5f7", fontSize: 22, fontWeight: 400 }}>
              Invite not accepted.
            </h2>
            <p style={{ margin: 0, color: "rgba(245,245,247,0.58)", fontSize: 14, lineHeight: 1.7 }}>
              {state.message}
            </p>
          </>
        )}
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <AuthFrame
      eyebrow="Organization invite"
      title="Join the workspace"
      body="Invites are redeemed by the backend and bound to the invited account."
    >
      <Suspense fallback={<Spinner />}>
        <AcceptInviteInner />
      </Suspense>
    </AuthFrame>
  );
}

function PrimaryLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      style={{
        alignSelf: "center",
        borderRadius: 999,
        padding: "11px 18px",
        background: "#f5f5f7",
        color: "#050506",
        textDecoration: "none",
        fontSize: 13,
        fontWeight: 500,
      }}
    >
      {children}
    </Link>
  );
}
