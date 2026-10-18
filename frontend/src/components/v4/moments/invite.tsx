"use client";

/**
 * Organization invite (board X12: checking, confirm, declined, sign-in needed,
 * joined, already a member, can't accept, no code), behind UI_V4.
 *
 * Today's page redeems the invite as soon as it opens. Here nothing changes
 * until the invited person presses Accept: the page first reads what accepting
 * would do (POST /orgs/invites/preview, read-only, same refusals as accept),
 * then accepts with the same POST /orgs/invites/accept. The backend still binds
 * the invite to the invited account; a signed-out visitor is sent to sign in
 * and back here. If the preview isn't available on this server, the confirm
 * step still shows, without the details.
 */
import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiProblemDetail } from "@/lib/api-recovery";
import { AuthCard } from "./auth-card";
import { V4_HOME } from "./landing";
import "./moments.css";

type Preview = {
  org_name?: string | null;
  role?: string | null;
  email?: string | null;
  invited_by?: string | null;
  expires_at?: string | null;
  already_member?: boolean;
  current_role?: string | null;
};

type State =
  | { kind: "checking" }
  | { kind: "missing" }
  | { kind: "confirm"; preview: Preview | null }
  | { kind: "declined"; preview: Preview | null }
  | { kind: "login" }
  | { kind: "joined"; role: string; org: string | null; created: boolean }
  | { kind: "failed"; message: string; retry: boolean; otherAccount: boolean };

function role(r: string | null | undefined): string {
  const v = (r ?? "member").trim() || "member";
  return v[0].toUpperCase() + v.slice(1);
}

function expiresIn(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const days = Math.ceil((t - Date.now()) / 86_400_000);
  if (days <= 0) return "Expires today";
  return `Expires in ${days} day${days === 1 ? "" : "s"}`;
}

async function post(path: string, token: string): Promise<{ status: number; data: unknown } | null> {
  try {
    const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token }) });
    return { status: res.status, data: await res.json().catch(() => ({})) };
  } catch {
    return null;
  }
}

function failure(status: number, data: unknown, fallback: string): State {
  const message = apiProblemDetail(data) ?? fallback;
  if (status === 401) return { kind: "login" };
  if (status === 400) return { kind: "missing" };
  return { kind: "failed", message, retry: status >= 500 || status === 429, otherAccount: status === 403 };
}

export function V4InviteAccept() {
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [state, setState] = React.useState<State>(token ? { kind: "checking" } : { kind: "missing" });
  const [attempt, setAttempt] = React.useState(0);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!token) return;
    let live = true;
    setState({ kind: "checking" });
    void post("/api/proxy/orgs/invites/preview", token).then((res) => {
      if (!live) return;
      if (!res) return setState({ kind: "failed", message: "Could not reach ScaleCAD.", retry: true, otherAccount: false });
      if (res.status >= 200 && res.status < 300) return setState({ kind: "confirm", preview: res.data as Preview });
      const msg = apiProblemDetail(res.data);
      // An older server without the preview: still confirm before accepting.
      if ((res.status === 404 || res.status === 405) && (msg === "Not Found" || msg === "Method Not Allowed")) return setState({ kind: "confirm", preview: null });
      setState(failure(res.status, res.data, "This invitation could not be checked."));
    });
    return () => {
      live = false;
    };
  }, [token, attempt]);

  async function accept() {
    if (busy) return;
    setBusy(true);
    const preview = state.kind === "confirm" ? state.preview : null;
    const res = await post("/api/proxy/orgs/invites/accept", token);
    setBusy(false);
    if (!res) return setState({ kind: "failed", message: "Could not reach ScaleCAD.", retry: true, otherAccount: false });
    if (res.status >= 200 && res.status < 300) {
      const d = res.data as { org_role?: unknown; created?: unknown };
      return setState({ kind: "joined", role: String(d.org_role ?? "member"), org: preview?.org_name ?? null, created: Boolean(d.created) });
    }
    setState(failure(res.status, res.data, "This invitation could not be accepted."));
  }

  const here = `/orgs/accept?token=${token}`;
  const loginHref = `/login?next=${encodeURIComponent(here)}`;
  const signupHref = `/signup?next=${encodeURIComponent(here)}`;

  switch (state.kind) {
    case "checking":
      return (
        <AuthCard
          label="Invite"
          icon={{ tone: "wait" }}
          title="Invite"
          meta={["Checking invite…"]}
          busy
          actions={
            <button className="btn ink" type="button" disabled>
              Accept invite
            </button>
          }
        />
      );
    case "missing":
      return (
        <AuthCard
          label="No invite in this link"
          icon={{ tone: "bad", mark: "!" }}
          title="No invite in this link"
          meta={["The link is missing its code"]}
          info={[["Next", "Open the link in the invite email again"]]}
          actions={
            <Link className="btn" href={V4_HOME}>
              Open ScaleCAD
            </Link>
          }
          links={<Link href="/login">Sign in</Link>}
        />
      );
    case "login":
      return (
        <AuthCard
          label="Sign in to accept"
          title="Sign in to accept"
          meta={["Only the invited account can accept"]}
          actions={
            <Link className="btn ink" href={loginHref}>
              Sign in
            </Link>
          }
          links={<Link href={signupHref}>Create an account</Link>}
        />
      );
    case "confirm": {
      const p = state.preview;
      const org = p?.org_name || "the organization";
      const facts = [p?.invited_by ? `Invited by ${p.invited_by}` : null, expiresIn(p?.expires_at)].filter((x): x is string => Boolean(x));
      const info: [string, string][] = p
        ? [
            ["Role", role(p.role)],
            ...(p.email ? ([["For", p.email]] as [string, string][]) : []),
            ...(p.already_member ? ([["Now", `Member already · ${role(p.current_role)}`]] as [string, string][]) : []),
            ["You’ll see", "Parts, machines, records"],
          ]
        : [["You’ll see", "Parts, machines, records"]];
      return (
        <AuthCard
          label={`Join ${org}`}
          title={`Join ${org}`}
          meta={facts.length ? facts : ["Organization invite"]}
          info={info}
          busy={busy}
          actions={
            <button className="btn ink" type="button" onClick={() => void accept()} disabled={busy} aria-busy={busy}>
              {busy ? "Accepting…" : "Accept invite"}
            </button>
          }
          links={
            <button type="button" onClick={() => setState({ kind: "declined", preview: p })} disabled={busy}>
              Decline
            </button>
          }
          note={
            p?.already_member
              ? "Accepting uses up the invite and doesn’t change your role."
              : `${p?.email ? `Only ${p.email} can accept.` : "Only the invited account can accept."} Nothing changes until you accept.`
          }
        />
      );
    }
    case "declined": {
      const p = state.preview;
      const until = p?.expires_at && !Number.isNaN(new Date(p.expires_at).getTime()) ? new Date(p.expires_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : null;
      return (
        <AuthCard
          label="Invite not accepted"
          title="Invite not accepted"
          meta={[p?.org_name ?? "Organization invite", until ? `The invite stays valid until ${until}` : "The invite stays valid until it expires"]}
          actions={
            <Link className="btn" href={V4_HOME}>
              Open ScaleCAD
            </Link>
          }
          links={
            <button type="button" onClick={() => setState({ kind: "confirm", preview: p })}>
              Back to the invite
            </button>
          }
        />
      );
    }
    case "joined":
      return state.created ? (
        <AuthCard
          label="Joined"
          icon={{ tone: "ok", mark: "✓" }}
          title={`You joined ${state.org ?? "the organization"}`}
          meta={[`Role: ${role(state.role)}`]}
          actions={
            <Link className="btn ink" href={V4_HOME}>
              Open ScaleCAD
            </Link>
          }
        />
      ) : (
        <AuthCard
          label="Already a member"
          icon={{ tone: "ok", mark: "✓" }}
          title="Already a member"
          meta={[...(state.org ? [state.org] : []), `Role unchanged: ${role(state.role)}`]}
          actions={
            <Link className="btn ink" href={V4_HOME}>
              Open ScaleCAD
            </Link>
          }
        />
      );
    case "failed":
      return (
        <AuthCard
          label="Can’t accept this invite"
          icon={{ tone: "bad", mark: "!" }}
          title="Can’t accept this invite"
          meta={[state.message]}
          info={[["Next", state.otherAccount ? "Sign in as the invited account" : state.retry ? "Try again in a moment" : "Ask your admin for a new invite"]]}
          actions={
            <>
              {state.retry ? (
                <button className="btn ink" type="button" onClick={() => setAttempt((n) => n + 1)}>
                  Retry
                </button>
              ) : null}
              <Link className="btn" href={V4_HOME}>
                Open ScaleCAD
              </Link>
            </>
          }
          links={<Link href={loginHref}>Sign in with another account</Link>}
        />
      );
  }
}
