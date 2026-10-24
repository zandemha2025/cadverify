"use client";

/** Organization › Decision sign-off: who may sign off a recorded make-or-buy decision. */
import * as React from "react";
import { API_BASE } from "@/lib/api-base";
import { Panel, cx } from "../ui";
import { forgetSignoffRule, type SignoffRule } from "../part/signoff";

const CHOICES: ["member" | "admin", string, string][] = [
  ["member", "Members and admins", "Anyone who can record an outcome can sign it off."],
  ["admin", "Admins only", "Members record outcomes; an admin signs them off."],
];

export function SignoffPanel() {
  const [rule, setRule] = React.useState<SignoffRule | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [saved, setSaved] = React.useState<string | null>(null);
  React.useEffect(() => {
    let live = true;
    fetch(`${API_BASE}/orgs/signoff`, { cache: "no-store" })
      .then(async (r) => (r.ok ? ((await r.json()) as SignoffRule) : Promise.reject(new Error(`Couldn't load the sign-off rule (${r.status}).`))))
      .then((r) => live && setRule(r), (e: Error) => live && setErr(e.message));
    return () => {
      live = false;
    };
  }, []);

  const choose = async (role: "member" | "admin") => {
    if (!rule || busy || role === rule.signoff_role) return;
    setBusy(true);
    setErr(null);
    setSaved(null);
    try {
      const r = await fetch(`${API_BASE}/orgs/signoff`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ signoff_role: role }) });
      const body = (await r.json().catch(() => null)) as (SignoffRule & { detail?: unknown }) | null;
      if (!r.ok || !body) throw new Error(typeof body?.detail === "string" ? body.detail : "The sign-off rule wasn't saved.");
      setRule(body);
      forgetSignoffRule();
      setSaved(`${body.label} sign off decisions now. Sign-offs already made stay.`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The sign-off rule wasn't saved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Decision sign-off" note={rule ? rule.label : undefined}>
      {rule ? (
        <div role="radiogroup" aria-label="Who signs off decisions" style={{ padding: "0 16px 6px" }}>
          {CHOICES.map(([k, name, sub]) => {
            const on = rule.signoff_role === k;
            return (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={on}
                aria-disabled={!rule.can_change || busy}
                className={cx("mr", on && "on")}
                onClick={() => rule.can_change && void choose(k)}
                style={{ width: "100%" }}
              >
                <span>
                  <b>{name}</b>
                  <small>{sub}</small>
                </span>
                <span />
                <span className="c">{on ? "In effect" : ""}</span>
              </button>
            );
          })}
        </div>
      ) : !err ? (
        <p className="a-fh" style={{ margin: "0 16px 12px" }}>Loading…</p>
      ) : null}
      <p className="a-fh" style={{ margin: "4px 16px 12px", color: err ? "var(--bad)" : undefined }} role={err ? "alert" : undefined} aria-live="polite">
        {err ?? saved ?? (rule && !rule.can_change ? "Only admins change who signs off." : "A sign-off keeps the signer's name, the time and a note. It goes out of date when the rates, machines, specs or calibration it used change.")}
      </p>
    </Panel>
  );
}
