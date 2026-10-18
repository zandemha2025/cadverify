"use client";

/**
 * Security (board A2): change or set the password (which variant depends on
 * AUTH_MODE and whether the account has one), the ways this deployment signs
 * people in, and Sign out — which signs out every browser at once, because
 * logout revokes the account's sessions (there is no per-device list).
 */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { authErrorMessage } from "@/lib/api-recovery";
import { Chip, Content, KV, Panel, Sheet } from "../ui";
import { R } from "../routes";
import { AccountFrame, AccountHead, Confirm } from "./frame";
import * as api from "./api";
import { passwordProblem, signIn } from "./derive";

export function SecurityScreen({ authMode, magicLink, hasPassword }: { authMode: string; magicLink: boolean; hasPassword: boolean }) {
  const { user, signOut } = useAuth();
  const si = signIn(authMode, magicLink);
  const [has, setHas] = React.useState(hasPassword);
  const [orgName, setOrgName] = React.useState<string | null>(null);
  const [askOut, setAskOut] = React.useState(false);
  const [leaving, setLeaving] = React.useState(false);

  React.useEffect(() => {
    api.getOrgs().then(
      (o) => setOrgName(o.organizations.find((x) => x.org_id === o.active_org_id)?.name ?? null),
      () => setOrgName(null),
    );
  }, []);

  const pwState = si.ssoOnly ? "Managed" : has ? "Set" : "Not set";
  return (
    <AccountFrame label="Security and sign-in">
      <AccountHead
        title="Security"
        meta={[
          <span key="m">Sign-in <b>{si.mode}</b></span>,
          <span key="p">Password <b>{pwState}</b></span>,
          <span key="o">Sign out <b>All browsers</b></span>,
        ]}
      />
      <Content>
        {si.ssoOnly ? (
          <section className="panel" aria-label="Managed sign-in">
            <div className="empty">
              <b>Sign-in managed by your organization</b>
              <span>Password and sign-in rules are set in your identity provider.</span>
              <Link className="btn sm" href={R.sso}>
                Single sign-on
              </Link>
            </div>
          </section>
        ) : (
          <PasswordPanel hasPassword={has} onSet={() => setHas(true)} linkOn={si.linkOn} />
        )}
        <Panel title="Ways to sign in">
          <div className="a-row2">
            <span>
              <b>Password</b>
              <small>{si.ssoOnly ? "Set by your identity provider." : !si.passwordOn ? "Not used on this deployment." : has ? "Set." : "Not set yet."}</small>
            </span>
            <Chip tone={!si.ssoOnly && si.passwordOn && has ? "ok" : "unk"}>{si.passwordOn || si.ssoOnly ? pwState : "Off"}</Chip>
          </div>
          <div className="a-row2">
            <span>
              <b>Email sign-in link</b>
              <small>One-time link to your work email.</small>
            </span>
            <Chip tone={si.linkOn ? "ok" : "unk"}>{si.linkOn ? "On" : "Off"}</Chip>
          </div>
          <div className="a-row2">
            <span>
              <b>Single sign-on</b>
              <small>Through your organization’s identity provider.</small>
            </span>
            <Chip tone={si.ssoOn ? "ok" : "unk"}>{si.ssoOn ? "On" : "Not enabled"}</Chip>
          </div>
        </Panel>
        <Panel title="Sign out">
          <div className="a-row2">
            <span>
              <b>Every browser signed in to this account</b>
              <small>Includes this one. No per-device list.</small>
            </span>
            <button className="btn sm" type="button" onClick={() => setAskOut(true)} disabled={askOut}>
              Sign out
            </button>
          </div>
          {askOut ? (
            <Confirm
              label="Sign out"
              question="Sign out of every browser?"
              detail="Unsaved what-ifs on open parts are lost."
              confirmLabel="Sign out"
              busy={leaving}
              onConfirm={() => {
                setLeaving(true);
                void signOut();
              }}
              onCancel={() => setAskOut(false)}
            />
          ) : null}
        </Panel>
      </Content>
      <Sheet label="Sign-in rules" style={{ bottom: 20 }}>
        <div className="top">
          <h2 className="stitle">Sign-in rules</h2>
          <p className="smeta a-wrap">{[user?.email, orgName].filter(Boolean).join(" · ")}</p>
        </div>
        <div className="scroll">
          <KV
            rows={[
              ["Password length", si.ssoOnly ? "Set by your provider" : "8 to 128 characters"],
              ["After a change", "Other browsers signed out"],
              ["Sign out", "Every browser, at once"],
              ["Email link", si.linkOn ? "Single use" : "Off"],
              ["Two-step codes", "Not available"],
              ["Device list", "Not available"],
            ]}
          />
          <div className="note">
            <b>Lost access</b>
            <span>{si.ssoOnly ? "Ask your organization’s identity provider admin." : "Reset from the sign-in page with your work email."}</span>
          </div>
          {si.ssoOnly ? null : (
            <div style={{ padding: "8px 12px" }}>
              <a className="btn sm" href="/forgot-password">
                Sign-in page
              </a>
            </div>
          )}
        </div>
      </Sheet>
    </AccountFrame>
  );
}

function PasswordPanel({ hasPassword, onSet, linkOn }: { hasPassword: boolean; onSet: () => void; linkOn: boolean }) {
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [mismatch, setMismatch] = React.useState(false);
  const [done, setDone] = React.useState<"changed" | "set" | null>(null);
  const change = hasPassword && done !== "set";

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (hasPassword && !current) {
      setErr("Enter your current password.");
      return;
    }
    const problem = passwordProblem(next, confirm);
    setMismatch(problem === "Passwords don’t match.");
    if (problem) {
      setErr(problem === "Passwords don’t match." ? null : problem);
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch("/api/auth/password/initialize", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ password: next, ...(hasPassword ? { current_password: current } : {}) }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(authErrorMessage(res.status, data, "Could not configure the password."));
        return;
      }
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(hasPassword ? "changed" : "set");
      if (!hasPassword) onSet();
    } catch {
      setErr("Could not configure the password. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const title = change ? "Change password" : "Set a password";
  return (
    <Panel title={title} note={change ? "8 to 128 characters" : linkOn ? "You sign in with an email link today" : "8 to 128 characters"}>
      <div aria-live="polite">
        {done ? (
          <div className="a-pf">
            <div className="toast swap" role="status" style={{ position: "static", alignSelf: "flex-start" }}>
              <span>{done === "changed" ? "Password changed." : "Password set."} Other browsers were signed out.</span>
            </div>
            {done === "changed" || hasPassword ? (
              <span>
                <button className="btn sm" type="button" onClick={() => setDone(null)}>
                  Change again
                </button>
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
      {done ? null : (
        <form className="a-pf" onSubmit={save} noValidate>
          {hasPassword ? (
            <label className="field">
              Current password
              <input type="password" autoComplete="current-password" maxLength={256} required value={current} onChange={(e) => setCurrent(e.target.value)} />
            </label>
          ) : null}
          <label className="field">
            New password
            <input type="password" autoComplete="new-password" maxLength={256} required aria-describedby="a-pw-h" value={next} onChange={(e) => setNext(e.target.value)} />
            <span className="a-fh" id="a-pw-h">
              8 to 128 characters.
            </span>
          </label>
          <label className="field">
            {hasPassword ? "Confirm new password" : "Confirm password"}
            <input
              type="password"
              autoComplete="new-password"
              maxLength={256}
              required
              aria-invalid={mismatch ? true : undefined}
              aria-describedby={mismatch ? "a-pw-mm" : undefined}
              value={confirm}
              onChange={(e) => {
                setConfirm(e.target.value);
                if (mismatch) setMismatch(false);
              }}
            />
            {mismatch ? (
              <span className="a-err" id="a-pw-mm" role="alert">
                Passwords don’t match.
              </span>
            ) : null}
          </label>
          {err ? (
            <span className="a-err" role="alert">
              {err}
            </span>
          ) : null}
          <span style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn ink sm" type="submit" disabled={busy} aria-busy={busy}>
              {busy ? "Securing account…" : hasPassword ? "Change password" : "Set password"}
            </button>
            <span className="a-fh">Signs out your other browsers.</span>
          </span>
        </form>
      )}
    </Panel>
  );
}
