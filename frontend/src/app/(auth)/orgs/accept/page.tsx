"use client";

/**
 * Organization invite on the pre-v4 frame (with UI_V4 on, the v4 card).
 *
 * Opening the link changes nothing (security review R4, F2). The page reads
 * what the invite is for from the public invite summary (the org, the
 * inviter's name, the role, when it expires) and whether this browser is the
 * invited account (the read-only preview), and accepts only when the person
 * presses Accept. Accepting makes the org active, as the page says before the
 * press. An org that requires two-step sign-in ends the session at the join;
 * the page then sends the person to sign in again and set it up.
 */
import * as React from "react";
import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";
import { Spinner } from "@/components/ui/spinner";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { V4InviteAccept } from "@/components/v4/moments/invite";
import { fetchInviteSummary, roleMeans, roleWord } from "@/components/v4/moments/invite-summary";

const ACCEPT_PATH = "/api/proxy/orgs/invites/accept";
const PREVIEW_PATH = "/api/proxy/orgs/invites/preview";
const HOME = "/verify";

type Access = "invitee" | "signed_out" | "other_account" | "unknown";

type Facts = {
  org: string | null;
  role: string;
  email: string | null;
  invitedBy: string | null;
  expiresAt: string | null;
  alreadyMember: boolean;
  currentRole: string | null;
};

type State =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "unusable"; message: string }
  | { kind: "ready"; facts: Facts; access: Access; problem: string | null }
  | { kind: "joined"; org: string | null; role: string; created: boolean; switched: boolean }
  | { kind: "sign_in_again"; org: string | null; role: string }
  | { kind: "error"; message: string };

type Answer = { status: number; data: Record<string, unknown> };

function detailMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const d = data as { detail?: string | { message?: string }; message?: string };
    if (typeof d.detail === "string") return d.detail;
    return d.detail?.message ?? d.message ?? fallback;
  }
  return fallback;
}

async function post(path: string, body: Record<string, unknown>): Promise<Answer | null> {
  try {
    const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    return { status: res.status, data: ((await res.json().catch(() => ({}))) ?? {}) as Record<string, unknown> };
  } catch {
    return null;
  }
}

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

function expiry(iso: string | null): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const days = Math.ceil((t - Date.now()) / 86_400_000);
  const date = new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  if (days <= 0) return `Today (${date})`;
  return `In ${days} day${days === 1 ? "" : "s"} (${date})`;
}

function AcceptInviteInner() {
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [state, setState] = React.useState<State>({ kind: "loading" });
  const [busy, setBusy] = React.useState(false);

  // Read-only on load: what the invite is for, and who this browser is. Nothing is accepted here.
  React.useEffect(() => {
    let alive = true;
    if (!token) {
      setState({ kind: "missing" });
      return;
    }
    void (async () => {
      const [summary, preview] = await Promise.all([fetchInviteSummary(token), post(PREVIEW_PATH, { token })]);
      if (!alive) return;
      const p = preview && preview.status >= 200 && preview.status < 300 ? preview.data : null;
      const access: Access = p ? "invitee" : preview?.status === 401 ? "signed_out" : preview?.status === 403 ? "other_account" : "unknown";
      const otherAccount = access === "other_account" ? detailMessage(preview?.data, "This invite was issued to a different email address.") : null;
      if (summary.ok) {
        const s = summary.summary;
        setState({
          kind: "ready",
          access,
          problem: otherAccount,
          facts: {
            org: s.org_name,
            role: s.role,
            email: s.email,
            invitedBy: s.invited_by_name,
            expiresAt: s.expires_at,
            alreadyMember: p?.already_member === true,
            currentRole: str(p?.current_role),
          },
        });
        return;
      }
      if (summary.status === 400) return setState({ kind: "missing" });
      if (summary.status === 404 || summary.status === 409) return setState({ kind: "unusable", message: summary.message });
      if (p) {
        // The summary is unavailable but the invited account's own preview answered.
        setState({
          kind: "ready",
          access,
          problem: null,
          facts: {
            org: str(p.org_name),
            role: str(p.role) ?? "member",
            email: str(p.email),
            invitedBy: str(p.invited_by),
            expiresAt: str(p.expires_at),
            alreadyMember: p.already_member === true,
            currentRole: str(p.current_role),
          },
        });
        return;
      }
      setState({ kind: "error", message: summary.message });
    })();
    return () => {
      alive = false;
    };
  }, [token]);

  async function accept() {
    if (busy || state.kind !== "ready") return;
    const ready = state;
    setBusy(true);
    // The press is the choice: join, and make the org active (the page says so above).
    const res = await post(ACCEPT_PATH, { token, switch: true });
    setBusy(false);
    if (!res) return setState({ ...ready, problem: "Could not reach ScaleCAD. Try again in a moment." });
    if (res.status >= 200 && res.status < 300) {
      const role = str(res.data.org_role) ?? ready.facts.role;
      if (res.data.signed_out === true) return setState({ kind: "sign_in_again", org: ready.facts.org, role });
      return setState({ kind: "joined", org: ready.facts.org, role, created: res.data.created === true, switched: res.data.switched === true });
    }
    if (res.status === 401) return setState({ ...ready, access: "signed_out", problem: null });
    if (res.status === 403) return setState({ ...ready, access: "other_account", problem: detailMessage(res.data, "Only the invited account can accept.") });
    if (res.status === 404 || res.status === 409) return setState({ kind: "unusable", message: detailMessage(res.data, "This invite can’t be used.") });
    setState({ ...ready, problem: detailMessage(res.data, "This invitation could not be accepted.") });
  }

  const here = `/orgs/accept?token=${encodeURIComponent(token)}`;
  const loginNext = `/login?next=${encodeURIComponent(here)}`;

  switch (state.kind) {
    case "loading":
      return (
        <AuthFrame eyebrow="Organization invite" title="Invite" body="Checking the invite…">
          <Spinner className="mx-auto" />
        </AuthFrame>
      );
    case "missing":
      return (
        <AuthFrame eyebrow="Organization invite" title="No invite in this link" body="The link is missing its code. Open the link in the invite email again.">
          <PrimaryLink href={HOME}>Open ScaleCAD</PrimaryLink>
        </AuthFrame>
      );
    case "unusable":
      return (
        <AuthFrame eyebrow="Organization invite" title="This invite can’t be used" body={`${state.message} Ask your admin for a new invite.`}>
          <PrimaryLink href={HOME}>Open ScaleCAD</PrimaryLink>
        </AuthFrame>
      );
    case "error":
      return (
        <AuthFrame eyebrow="Organization invite" title="Invite not checked" body={state.message}>
          <AuthSubmit type="button" onClick={() => window.location.reload()}>
            Try again
          </AuthSubmit>
        </AuthFrame>
      );
    case "joined": {
      const org = state.org ?? "the organization";
      return state.created ? (
        <AuthFrame
          eyebrow="Organization invite"
          title={`You joined ${org}`}
          body={`Role: ${roleWord(state.role)}. ${state.switched ? `${org} is now your active organization.` : `Switch to ${org} in Settings › Organization to use its machines and rates.`}`}
        >
          <PrimaryLink href={HOME}>Open ScaleCAD</PrimaryLink>
        </AuthFrame>
      ) : (
        <AuthFrame eyebrow="Organization invite" title="Already a member" body={`The invite is used up. Your role is unchanged: ${roleWord(state.role)}.`}>
          <PrimaryLink href={HOME}>Open ScaleCAD</PrimaryLink>
        </AuthFrame>
      );
    }
    case "sign_in_again": {
      const org = state.org ?? "the organization";
      return (
        <AuthFrame
          eyebrow="Organization invite"
          title={`You joined ${org}`}
          body={`Role: ${roleWord(state.role)}. ${org} requires two-step sign-in for every member, so you were signed out. Log in again and set it up with an authenticator app; then ${org} opens.`}
        >
          <PrimaryLink href={`/login?next=${encodeURIComponent(HOME)}`}>Log in</PrimaryLink>
        </AuthFrame>
      );
    }
    case "ready": {
      const f = state.facts;
      const org = f.org ?? "the organization";
      const rows: [string, string][] = [
        ...(f.invitedBy ? ([["Invited by", f.invitedBy]] as [string, string][]) : []),
        ["Role", roleWord(f.role)],
        ...(f.email ? ([["For", f.email]] as [string, string][]) : []),
        ...(expiry(f.expiresAt) ? ([["Expires", expiry(f.expiresAt) as string]] as [string, string][]) : []),
        ...(f.alreadyMember ? ([["Now", `Member already · ${roleWord(f.currentRole)}`]] as [string, string][]) : []),
      ];
      const only = f.email ? `Only ${f.email} can accept.` : "Only the invited account can accept.";
      return (
        <AuthFrame
          eyebrow="Organization invite"
          title={`Join ${org}`}
          body={roleMeans(f.role, org)}
          footer={
            state.access === "signed_out" ? (
              <>
                New here? <AuthTextLink href={`/signup?next=${encodeURIComponent(here)}`}>Create an account</AuthTextLink>
              </>
            ) : state.access === "other_account" ? null : (
              <AuthTextLink href={HOME}>Not now</AuthTextLink>
            )
          }
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <FactList rows={rows} />
            {state.problem ? (
              <p role="alert" style={{ margin: 0, color: "#b42318", fontSize: 13, lineHeight: 1.5 }}>
                {state.problem}
              </p>
            ) : null}
            {state.access === "signed_out" ? (
              <>
                <p style={noteStyle}>{only} Log in with that address, or create an account with it.</p>
                <PrimaryLink href={loginNext}>Log in to accept</PrimaryLink>
              </>
            ) : state.access === "other_account" ? (
              <>
                <p style={noteStyle}>{only} You’re signed in as another account.</p>
                <PrimaryLink href={loginNext}>Log in as the invited account</PrimaryLink>
              </>
            ) : (
              <>
                <p style={noteStyle}>
                  {f.alreadyMember
                    ? "Accepting uses up the invite and doesn’t change your role."
                    : `Nothing changes until you accept. Accepting makes ${org} your active organization.`}
                </p>
                <AuthSubmit type="button" loading={busy} onClick={() => void accept()} aria-busy={busy}>
                  Accept invite
                </AuthSubmit>
              </>
            )}
          </div>
        </AuthFrame>
      );
    }
  }
}

const noteStyle: React.CSSProperties = { margin: 0, color: "#53635a", fontSize: 13, lineHeight: 1.6 };

function FactList({ rows }: { rows: [string, string][] }) {
  return (
    <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "max-content minmax(0, 1fr)", gap: "8px 16px", fontSize: 14, lineHeight: 1.5 }}>
      {rows.map(([k, v]) => (
        <React.Fragment key={k}>
          <dt style={{ color: "#53635a" }}>{k}</dt>
          <dd style={{ margin: 0, color: "#183d32", overflowWrap: "anywhere" }}>{v}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

export default function AcceptInvitePage() {
  if (UI_V4) {
    return (
      <Suspense fallback={null}>
        <V4InviteAccept />
      </Suspense>
    );
  }
  return (
    <Suspense
      fallback={
        <AuthFrame eyebrow="Organization invite" title="Invite" body="Checking the invite…">
          <Spinner className="mx-auto" />
        </AuthFrame>
      }
    >
      <AcceptInviteInner />
    </Suspense>
  );
}

function PrimaryLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: "100%",
        minHeight: 44,
        borderRadius: 5,
        background: "#183d32",
        color: "#ffffff",
        textDecoration: "none",
        fontSize: 14,
        fontWeight: 500,
      }}
    >
      {children}
    </Link>
  );
}
