"use client";

/**
 * N6: a teammate's first run. Joining an organization makes it the active one
 * (the person accepted the invite to work in it), and what the team already set
 * up is listed from the organization's own data: its machines, its rate card,
 * its parts and records. Every check the teammate runs uses those machines and
 * rates, so there is no shop setup; their first part shows the three tips once,
 * with Shop as "your team's machines".
 */
import * as React from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api-base";
import { apiProblemDetail } from "@/lib/api-recovery";
import { R } from "../routes";
import * as api from "../home/data";
import { rateCardName, yoursOf } from "../home/home-derive";
import { PartThumb } from "../home/thumb";
import "./onboard.css";

/** Make the joined organization the active one. */
export async function switchTo(orgId: string): Promise<{ ok: true; name: string | null } | { ok: false; message: string }> {
  try {
    const res = await fetch(`${API_BASE}/orgs/switch`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ org_id: orgId }) });
    const body = await res.json().catch(() => null);
    if (!res.ok) return { ok: false, message: apiProblemDetail(body) ?? `The server answered ${res.status}` };
    return { ok: true, name: (body as { name?: string | null } | null)?.name ?? null };
  } catch {
    return { ok: false, message: "Could not reach ScaleCAD." };
  }
}

export const ROLE_CAN: Record<string, string> = {
  viewer: "See parts, machines and records",
  member: "Check parts and record decisions",
  admin: "Check parts, change the shop and rates, invite people",
};

export interface TeamSetup {
  machines: { names: string[]; n: number } | null;
  rates: string | null;
  parts: number | null;
  records: string | null;
}

/** What the team already set up, read from the (now active) organization. */
export function useTeamSetup(enabled: boolean): TeamSetup {
  const [s, setS] = React.useState<TeamSetup>({ machines: null, rates: null, parts: null, records: null });
  React.useEffect(() => {
    if (!enabled) return;
    let live = true;
    const patch = (p: Partial<TeamSetup>) => live && setS((c) => ({ ...c, ...p }));
    api.machines(true).then((m) => patch({ machines: { names: m.map((x) => x.name).filter(Boolean), n: m.reduce((n, x) => n + (x.count ?? 1), 0) } }), () => undefined);
    Promise.all([api.rateSource(true), api.portfolio(true).catch(() => null)]).then(([r, p]) => {
      const y = yoursOf(p?.summary.posture ?? null);
      patch({ rates: `${rateCardName(r)}${y ? ` · ${y.yours} of ${y.total} cost inputs yours` : ""}` });
    }, () => undefined);
    api.catalogPage(1, true).then((c) => patch({ parts: api.catalogTotal(c.facets) }), () => undefined);
    api.records(true).then((b) => patch({ records: `${b.cost_decisions.length}${b.has_more ? "+" : ""}` }), () => undefined);
    return () => {
      live = false;
    };
  }, [enabled]);
  return s;
}

export function teamInfo(s: TeamSetup, role: string): [string, string][] {
  const rows: [string, string][] = [];
  rows.push(["Machines", s.machines ? (s.machines.n ? `${s.machines.n} · ${s.machines.names.slice(0, 3).join(", ")}${s.machines.names.length > 3 ? ` and ${s.machines.names.length - 3} more` : ""}` : "None yet · answers use typical machines") : "…"]);
  rows.push(["Rates", s.rates ?? "…"]);
  rows.push(["Parts", s.parts != null ? `${s.parts} ${s.parts === 1 ? "part" : "parts"}${s.records ? ` · ${s.records} records` : ""}` : "…"]);
  rows.push(["You can", ROLE_CAN[role] ?? "Use the organization’s parts and machines"]);
  return rows;
}

/** Parts, right after joining (`?joined=1`): who set up what, and the first check. */
export function JoinedWelcome() {
  const [on, setOn] = React.useState(false);
  const [org, setOrg] = React.useState<string | null>(null);
  const [machines, setMachines] = React.useState<string[] | null>(null);
  const [newest, setNewest] = React.useState<{ key: string; file: string; checks: number } | null>(null);
  React.useEffect(() => {
    setOn(new URLSearchParams(window.location.search).get("joined") === "1");
  }, []);
  React.useEffect(() => {
    if (!on) return;
    let live = true;
    api.org().then((o) => live && setOrg(o.name), () => undefined);
    api.machines().then((m) => live && setMachines(m.map((x) => x.name).filter(Boolean)), () => live && setMachines(null));
    api.records().then((b) => {
      const r = b.cost_decisions[0];
      if (!live || !r?.mesh_hash) return;
      setNewest({ key: r.mesh_hash, file: r.label || r.filename, checks: b.cost_decisions.filter((x) => x.mesh_hash === r.mesh_hash).length });
    }, () => undefined);
    return () => {
      live = false;
    };
  }, [on]);
  if (!on) return null;
  const dismiss = () => {
    setOn(false);
    try {
      const u = new URL(window.location.href);
      u.searchParams.delete("joined");
      window.history.replaceState(window.history.state, "", `${u.pathname}${u.search}`);
    } catch {
      /* it stays in the address; nothing else changes */
    }
  };
  const list = machines && machines.length ? machines.length <= 3 ? machines.join(", ") : `${machines.slice(0, 3).join(", ")} and ${machines.length - 3} more` : null;
  return (
    <section className="panel nb-welcome swap" aria-labelledby="nb-wel-t">
      <div className="hd">
        <b id="nb-wel-t">You joined {org ?? "the organization"}</b>
        <span>
          {list
            ? `Your team set up the shop: ${list}, and their rates. Every check you run uses them, so there’s nothing to set up.`
            : machines
              ? "Your team hasn’t added machines yet, so answers use typical machines and rates and say so."
              : "Every check you run uses your team’s machines and rates."}
        </span>
        <span className="acts">
          <Link className="btn sm" href={R.shop}>
            See machines
          </Link>
          <button className="btn ghost sm" type="button" onClick={dismiss}>
            Dismiss
          </button>
        </span>
      </div>
      <div className="nb-firsts">
        {newest ? (
          <Link className="lrow" href={R.part(newest.key)}>
            <PartThumb size={44} />
            <span>
              <b>Open {newest.file}</b>
              <small>
                Saved results · checked {newest.checks} {newest.checks === 1 ? "time" : "times"}
              </small>
            </span>
            <span aria-hidden="true">→</span>
          </Link>
        ) : null}
        <Link className="lrow" href={R.check}>
          <span className="h-th" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
              <path d="M10 13V3m0 0L6 7m4-4 4 4M4 13v4h12v-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span>
            <b>Check your own part</b>
            <small>Uses 1 check · on your team’s machines</small>
          </span>
          <span aria-hidden="true">→</span>
        </Link>
        <p className="nb-fine" style={{ margin: "2px 2px 0" }}>
          Three short tips show on the first part you open, once.
        </p>
      </div>
    </section>
  );
}
