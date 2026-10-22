"use client";

/**
 * Organization › Two-step sign-in: the admin's rule that every member signs in
 * with an authenticator code, and (admins) who has it on. Turning the rule on
 * needs the admin's own two-step first; members without it are signed out at
 * once and set it up at their next sign-in, before they reach anything.
 */
import * as React from "react";
import Link from "next/link";
import { twoStepError } from "@/components/two-step/parts";
import { personLabel } from "@/lib/person-label";
import { Chip, Panel } from "../ui";
import { R } from "../routes";
import { Confirm } from "./frame";

type Member = { user_id: number; email: string; org_role: string; two_step_on: boolean; single_sign_on: boolean };
type Rule = {
  org_id: string;
  org_name: string | null;
  is_personal: boolean;
  required: boolean;
  can_change: boolean;
  members?: Member[];
  members_signed_out?: number;
};

async function call(method: "GET" | "PUT", body?: unknown) {
  const res = await fetch("/api/auth/two-step/org", {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  return { res, data: (await res.json().catch(() => ({}))) as Record<string, unknown> };
}

export function TwoStepRulePanel({ me }: { me: number | null }) {
  const [rule, setRule] = React.useState<Rule | null>(null);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const [ask, setAsk] = React.useState<boolean | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [done, setDone] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const { res, data } = await call("GET");
      if (!res.ok) throw new Error(twoStepError(res.status, data, "Couldn’t read the two-step rule."));
      setRule(data as unknown as Rule);
      setLoadErr(null);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Couldn’t read the two-step rule.");
    }
  }, []);
  React.useEffect(() => {
    void load();
  }, [load]);

  async function apply(required: boolean) {
    setBusy(true);
    setErr(null);
    try {
      const { res, data } = await call("PUT", { required });
      if (!res.ok) {
        setErr(twoStepError(res.status, data, "Couldn’t change the rule."));
        return;
      }
      const next = data as unknown as Rule;
      setRule(next);
      setAsk(null);
      const out = next.members_signed_out ?? 0;
      setDone(
        required
          ? `Two-step sign-in is required. ${out === 0 ? "Nobody needed signing out." : `${out} ${out === 1 ? "member was" : "members were"} signed out and set it up at their next sign-in.`}`
          : "Two-step sign-in is no longer required. Members who have it keep it.",
      );
    } catch {
      setErr("Couldn’t reach the sign-in service. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (loadErr)
    return (
      <Panel title="Two-step sign-in">
        <div className="a-row2">
          <span className="a-err">{loadErr}</span>
          <button className="btn sm" type="button" onClick={() => void load()}>
            Try again
          </button>
        </div>
      </Panel>
    );
  if (!rule) return null;

  const members = rule.members ?? [];
  const without = members.filter((m) => !m.two_step_on && m.user_id !== me);
  const meOn = members.find((m) => m.user_id === me)?.two_step_on ?? null;
  const onCount = members.filter((m) => m.two_step_on).length;
  const name = rule.org_name ?? "this organization";

  return (
    <Panel
      title="Two-step sign-in"
      note={rule.members ? `${onCount} of ${members.length} on` : "Set by admins"}
      actions={<Chip tone={rule.required ? "ok" : "unk"}>{rule.required ? "Required" : "Not required"}</Chip>}
    >
      <div className="a-row2">
        <span>
          <b>Require for every member</b>
          <small>
            A code from an authenticator app after a password, email-link or Google sign-in. Single sign-on through your identity
            provider isn&rsquo;t asked. API keys aren&rsquo;t affected; revoke them on the API page.
          </small>
        </span>
        {rule.can_change ? (
          <button
            className={rule.required ? "btn sm" : "btn ink sm"}
            type="button"
            disabled={busy || ask !== null}
            onClick={() => {
              setAsk(!rule.required);
              setErr(null);
              setDone(null);
            }}
          >
            {rule.required ? "Stop requiring" : "Require"}
          </button>
        ) : null}
      </div>
      {ask !== null ? (
        <Confirm
          label={ask ? "Require two-step sign-in" : "Stop requiring two-step sign-in"}
          question={ask ? `Require two-step sign-in in ${name}?` : `Stop requiring two-step sign-in in ${name}?`}
          detail={
            ask
              ? meOn === false
                ? "Turn it on for your own account first, in Security."
                : without.length === 0
                  ? "Every member already has it on. Nobody is signed out."
                  : `${without.length} ${without.length === 1 ? "member doesn’t" : "members don’t"} have it yet: signed out now, and asked to set it up at their next sign-in before they reach anything.`
              : "Members who turned it on keep it. Others sign in with a password or email link alone."
          }
          confirmLabel={ask ? "Require" : "Stop requiring"}
          busy={busy}
          blocked={ask && meOn === false}
          error={err}
          onConfirm={() => void apply(ask)}
          onCancel={() => {
            setAsk(null);
            setErr(null);
          }}
        />
      ) : null}
      {err && ask === null ? (
        <div className="a-row2">
          <span className="a-err" role="alert">
            {err} {/own account/.test(err) ? <Link href={R.security}>Security</Link> : null}
          </span>
        </div>
      ) : null}
      <div aria-live="polite">
        {done ? (
          <div className="a-row2" role="status">
            <span>{done}</span>
          </div>
        ) : null}
      </div>
      {rule.members ? (
        <div role="table" aria-label="Two-step sign-in by member">
          {members.map((m) => (
            <div key={m.user_id} className="a-row2" role="row">
              <span role="cell" className="a-wrap">
                <b>
                  {personLabel(m.email) ?? m.email}
                  {m.user_id === me ? " (you)" : ""}
                </b>
                <small>{m.single_sign_on ? "Signs in through single sign-on" : m.two_step_on ? "Authenticator app" : rule.required ? "Sets it up at next sign-in" : "Password or email link only"}</small>
              </span>
              <span role="cell">
                <Chip tone={m.two_step_on ? "ok" : "unk"}>{m.two_step_on ? "On" : "Off"}</Chip>
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}
