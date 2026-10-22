"use client";

/**
 * Activity (board A7): usage over the last 30 days, the batch webhook
 * delivery log, the audit log (newest first, Show older pages back with the
 * cursor, CSV export for the chosen range) and service health from
 * /health/deep. Usage, deliveries and the audit log are org-admin reads; the
 * health readout is the deployment's own and is shown to everyone.
 */
import * as React from "react";
import Link from "next/link";
import { getHealthDeep, type HealthDeep } from "@/app/(app)/settings/organization/actions";
import { Chip, Content, Loading, Panel, Sheet } from "../ui";
import { R } from "../routes";
import { AccountFrame, AccountHead, AdminsOnly, Banner } from "./frame";
import * as api from "./api";
import { auditTitle, auditWhat, auditWho, dateLabel, healthRows, roleName, timeLabel, usageEventsLine, whenLabel, workerFig, type HealthChecks, type OrgRole } from "./derive";

const RANGES = [7, 30, 90] as const;
type Range = (typeof RANGES)[number];
const PAGE = 50;

export function ActivityScreen({ health: first }: { health: HealthDeep & { checkedAt: string } }) {
  const [role, setRole] = React.useState<OrgRole | null>(null);
  const [orgName, setOrgName] = React.useState<string | null>(null);
  const [orgErr, setOrgErr] = React.useState<string | null>(null);
  const [health, setHealth] = React.useState(first);
  const [checking, setChecking] = React.useState(false);

  React.useEffect(() => {
    api.getOrgs().then(
      (o) => {
        const a = o.organizations.find((x) => x.org_id === o.active_org_id) ?? null;
        setRole(a?.org_role ?? null);
        setOrgName(a?.name ?? null);
      },
      (e) => setOrgErr(api.errText(e, "Couldn’t load your organization.")),
    );
  }, []);

  const admin = role === "admin";
  const usage = useLoad(admin, () => api.getUsage(30));
  const deliveries = useLoad(admin, () => api.getDeliveries(12));
  const c = (health.checks ?? {}) as HealthChecks;
  const overall = !health.reachable ? "Unreachable" : health.status === "ok" ? "Healthy" : "Degraded";
  const counts = usage.data?.counts;
  const wf = workerFig(c);

  return (
    <AccountFrame label="Activity">
      <AccountHead
        title="Activity"
        meta={[
          <span key="d">Last <b>30 days</b></span>,
          ...(admin
            ? [
                <span key="c">Part checks <b className="num">{counts ? counts.analyses : "—"}</b></span>,
                <span key="s">Cost records <b className="num">{counts ? counts.cost_decisions : "—"}</b></span>,
                <span key="w">Webhook deliveries <b className="num">{counts ? counts.webhook_deliveries : "—"}</b></span>,
              ]
            : []),
          <span key="h">Service <b>{overall}</b></span>,
        ]}
      />
      <Content>
        {orgErr ? (
          <Banner title="Couldn’t load your organization." actions={<button className="btn sm" type="button" onClick={() => window.location.reload()}>Try again</button>}>
            {orgErr}
          </Banner>
        ) : null}
        <Panel title="Usage" note={orgName ? `${orgName} · last 30 days` : "Last 30 days"}>
          {role == null && !orgErr ? (
            <Loading rows={1} label="Loading usage" />
          ) : !admin ? (
            <AdminsOnly what="Usage counts are for organization admins." role={role ? roleName(role) : null} />
          ) : usage.err ? (
            <Banner title="Couldn’t load usage." actions={<button className="btn sm" type="button" onClick={usage.reload}>Try again</button>}>
              {usage.err}
            </Banner>
          ) : (
            <>
              <div className="a-figs4">
                {(
                  [
                    ["Part checks", counts?.analyses],
                    ["Cost records", counts?.cost_decisions],
                    ["Usage events", counts?.usage_events],
                    ["Webhook deliveries", counts?.webhook_deliveries],
                  ] as [string, number | undefined][]
                ).map(([k, v]) => (
                  <div key={k}>
                    <span>{k}</span>
                    <b className="num">{v ?? "—"}</b>
                  </div>
                ))}
              </div>
              {usageEventsLine(usage.data?.event_counts) ? (
                <p className="a-fh" style={{ margin: "-2px 16px 12px" }}>
                  {usageEventsLine(usage.data?.event_counts)}
                </p>
              ) : null}
            </>
          )}
        </Panel>
        <Panel title="Webhook deliveries" note="Latest 12 · batch.completed, batch_item.completed">
          {role == null && !orgErr ? (
            <Loading rows={1} label="Loading deliveries" />
          ) : !admin ? (
            <AdminsOnly what="The delivery log is for organization admins." role={role ? roleName(role) : null} />
          ) : deliveries.err ? (
            <Banner title="Couldn’t load deliveries." actions={<button className="btn sm" type="button" onClick={deliveries.reload}>Try again</button>}>
              {deliveries.err}
            </Banner>
          ) : !deliveries.data ? (
            <Loading rows={1} label="Loading deliveries" />
          ) : deliveries.data.length === 0 ? (
            <div className="empty" style={{ padding: "16px 24px" }}>
              <b>No deliveries</b>
              <span>Set a webhook URL when starting a batch.</span>
              <Link className="btn sm" href={R.many}>
                Many parts
              </Link>
            </div>
          ) : (
            <div role="table" aria-label="Webhook deliveries">
              <div className="a-tr th" role="row" style={{ gridTemplateColumns: "minmax(0,1fr) 110px 110px 120px" }}>
                <span role="columnheader">Event</span>
                <span role="columnheader">Status</span>
                <span role="columnheader">Response</span>
                <span role="columnheader">Last try</span>
              </div>
              {deliveries.data.map((d) => (
                <div key={d.id} className="a-tr" role="row" style={{ gridTemplateColumns: "minmax(0,1fr) 110px 110px 120px" }}>
                  <span role="cell" className="a-clip">
                    <b className="a-mono" style={{ fontWeight: 500 }}>{d.event_type}</b>
                    <small className="a-mono">batch {d.batch_ulid.slice(0, 10)}</small>
                  </span>
                  <span role="cell" data-l="Status">
                    <Chip tone={d.status === "delivered" ? "ok" : d.status === "failed" ? "bad" : "warn"}>{roleName(d.status)}</Chip>
                  </span>
                  <span role="cell" className="num" data-l="Response">
                    {d.response_code ?? "—"} · {d.attempts}×
                  </span>
                  <span role="cell" className="num" data-l="Last try">
                    {whenLabel(d.last_attempt_at ?? d.created_at)} UTC
                  </span>
                </div>
              ))}
            </div>
          )}
        </Panel>
        <AuditPanel admin={admin} role={role} loading={role == null && !orgErr} />
      </Content>
      <Sheet label="Service health" style={{ bottom: 20 }}>
        <div className="top">
          <h2 className="stitle">Service health</h2>
          <p className="smeta">
            ScaleCAD API · checked {timeLabel(health.checkedAt)} UTC{health.version ? ` · release ${health.version}` : ""}
          </p>
          <div className="figs" aria-live="polite">
            <div className="fig">
              <span>Overall</span>
              <b className={`t${health.reachable && health.status === "ok" ? " ok" : " warn"}`}>{overall}</b>
              <small>{health.httpStatus != null ? `HTTP ${health.httpStatus}` : "no answer"}</small>
            </div>
            <div className="fig">
              <span>Queue</span>
              <b className="num">{c.queue?.depth != null ? String(c.queue.depth) : "—"}</b>
              <small>jobs waiting</small>
            </div>
            <div className="fig">
              <span>Worker</span>
              <b className="t">{wf.v}</b>
              <small>{wf.sub}</small>
            </div>
          </div>
        </div>
        <div className="scroll">
          {!health.reachable ? (
            <div className="note">
              <b>Health check unreachable</b>
              <span>/health/deep didn’t answer{health.httpStatus ? ` (HTTP ${health.httpStatus})` : ""}. Nothing below is guessed.</span>
            </div>
          ) : (
            healthRows(c).map((r) => (
              <div className="a-hl" key={r.name}>
                <b>{r.name}</b>
                {r.chip ? <Chip tone={r.chip.tone}>{r.chip.label}</Chip> : <span className="num" style={{ fontWeight: 600 }}>{r.value}</span>}
                <small>{r.note}</small>
              </div>
            ))
          )}
          <div style={{ padding: "10px 12px" }}>
            <button
              className="btn sm"
              type="button"
              disabled={checking}
              aria-busy={checking}
              onClick={async () => {
                setChecking(true);
                try {
                  const h = await getHealthDeep();
                  setHealth({ ...h, checkedAt: new Date().toISOString() });
                } finally {
                  setChecking(false);
                }
              }}
            >
              {checking ? "Checking…" : "Check again"}
            </button>
          </div>
          <div className="note">
            <b>Records stay</b>
            <span>The audit log can’t be edited or deleted.</span>
          </div>
        </div>
      </Sheet>
    </AccountFrame>
  );
}

/** Load once when `enabled` turns true; `reload` re-runs it. */
function useLoad<T>(enabled: boolean, fn: () => Promise<T>): { data: T | null; err: string | null; reload: () => void } {
  const [data, setData] = React.useState<T | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [n, setN] = React.useState(0);
  const ref = React.useRef(fn);
  React.useEffect(() => {
    ref.current = fn;
  });
  React.useEffect(() => {
    if (!enabled) return;
    let live = true;
    setErr(null);
    ref.current().then(
      (d) => live && setData(d),
      (e) => live && setErr(api.errText(e, "Didn’t load.")),
    );
    return () => {
      live = false;
    };
  }, [enabled, n]);
  return { data, err, reload: () => setN((x) => x + 1) };
}

function AuditPanel({ admin, role, loading }: { admin: boolean; role: OrgRole | null; loading: boolean }) {
  const [days, setDays] = React.useState<Range>(30);
  const [range, setRange] = React.useState(() => api.auditRange(30));
  const [entries, setEntries] = React.useState<api.AuditEntry[] | null>(null);
  const [cursor, setCursor] = React.useState<string | null>(null);
  const [more, setMore] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [exported, setExported] = React.useState<string | null>(null);
  const [exportErr, setExportErr] = React.useState<string | null>(null);
  const [exporting, setExporting] = React.useState(false);

  // A range change starts a new list; a page that arrives for an older one is dropped.
  const gen = React.useRef(0);
  const first = React.useCallback(async (r: { start: string; end: string }) => {
    const mine = ++gen.current;
    setBusy(true);
    setErr(null);
    setEntries(null);
    try {
      const p = await api.getAuditPage(r, null, PAGE);
      if (mine !== gen.current) return;
      setEntries(p.entries);
      setCursor(p.next_cursor);
      setMore(p.has_more && !!p.next_cursor);
    } catch (e) {
      if (mine === gen.current) setErr(api.errText(e, "The audit log didn’t load."));
    } finally {
      if (mine === gen.current) setBusy(false);
    }
  }, []);

  React.useEffect(() => {
    if (admin) void first(range);
  }, [admin, range, first]);

  React.useEffect(() => {
    if (!exported) return;
    const t = window.setTimeout(() => setExported(null), 5000);
    return () => window.clearTimeout(t);
  }, [exported]);

  async function older() {
    if (!cursor) return;
    const mine = gen.current;
    setBusy(true);
    setErr(null);
    try {
      const p = await api.getAuditPage(range, cursor, PAGE);
      if (mine !== gen.current) return;
      setEntries((rows) => {
        const seen = new Set((rows ?? []).map((r) => r.id));
        return [...(rows ?? []), ...p.entries.filter((e) => !seen.has(e.id))];
      });
      setCursor(p.next_cursor);
      setMore(p.has_more && !!p.next_cursor);
    } catch (e) {
      if (mine === gen.current) setErr(api.errText(e, "Older entries didn’t load."));
    } finally {
      if (mine === gen.current) setBusy(false);
    }
  }

  async function exportCsv() {
    setExporting(true);
    setExportErr(null);
    setExported(null);
    try {
      const blob = await api.downloadAuditCsv(api.auditRange(days));
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "audit-log.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setExported(`audit-log.csv downloaded. Last ${days} days.`);
    } catch (e) {
      setExportErr(api.errText(e, "Export failed. Try again."));
    } finally {
      setExporting(false);
    }
  }

  const now = new Date();
  const cols = "90px 170px minmax(0,1fr) 190px";
  return (
    <section className="panel" aria-label="Audit log">
      <div className="ph" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <h2>Audit log</h2>
        {admin ? (
          <span style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <label className="field a-range">
              Range
              <select
                value={days}
                onChange={(e) => {
                  const d = Number(e.target.value) as Range;
                  setDays(d);
                  setRange(api.auditRange(d));
                }}
              >
                {RANGES.map((d) => (
                  <option key={d} value={d}>
                    Last {d} days
                  </option>
                ))}
              </select>
            </label>
            <button className="btn sm" type="button" onClick={() => void exportCsv()} disabled={exporting} aria-busy={exporting}>
              {exporting ? "Exporting…" : "Export CSV"}
            </button>
          </span>
        ) : null}
      </div>
      {loading ? (
        <Loading rows={3} label="Loading audit log" />
      ) : !admin ? (
        <AdminsOnly what="The audit log is for organization admins." role={role ? roleName(role) : null} />
      ) : (
        <>
          <div aria-live="polite">
            {exported ? (
              <div className="toast swap a-toast" role="status" style={{ margin: "0 16px 8px" }}>
                <span>{exported}</span>
              </div>
            ) : null}
          </div>
          {exportErr ? (
            <p className="a-err" role="alert" style={{ margin: "0 16px 8px" }}>
              {exportErr}
            </p>
          ) : null}
          {err ? (
            <Banner title="Couldn’t load the audit log." actions={<button className="btn sm" type="button" onClick={() => (entries ? void older() : void first(range))}>Try again</button>}>
              {err}
            </Banner>
          ) : null}
          {!entries ? (
            err ? null : <Loading rows={4} label="Loading audit log" />
          ) : entries.length === 0 ? (
            <div className="empty" style={{ padding: "16px 24px" }}>
              <b>No audit entries</b>
              <span>Nothing was recorded in the last {days} days.</span>
            </div>
          ) : (
            <div role="table" aria-label="Audit log entries">
              <div className="a-tr th" role="row" style={{ gridTemplateColumns: cols }}>
                <span role="columnheader">Time</span>
                <span role="columnheader">Event</span>
                <span role="columnheader">What</span>
                <span role="columnheader">Who</span>
              </div>
              {entries.map((e) => (
                <div className="a-tr a-audit" role="row" key={e.id} style={{ gridTemplateColumns: cols }}>
                  <span role="cell" className="num" title={e.timestamp ?? undefined}>
                    {whenLabel(e.timestamp, now)}
                  </span>
                  <span role="cell">
                    <b>{auditTitle(e)}</b>
                    <small className="a-mono a-clip" title={e.action}>
                      {e.action}
                    </small>
                  </span>
                  <span role="cell" className="a-clip" title={auditWhat(e)}>
                    {auditWhat(e)}
                  </span>
                  <span role="cell" className="a-clip" title={auditWho(e)}>
                    {auditWho(e)}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="a-pact" style={{ paddingTop: 10, borderTop: "1px solid var(--rule)" }}>
            {more ? (
              <button className="btn sm" type="button" onClick={() => void older()} disabled={busy} aria-busy={busy}>
                {busy ? "Loading…" : "Show older"}
              </button>
            ) : entries && entries.length ? (
              <span className="a-fh">That’s everything in the last {days} days.</span>
            ) : null}
            <span className="a-fh">
              Newest first · {dateLabel(range.start)} to {dateLabel(range.end)} · UTC · admins only
            </span>
          </div>
        </>
      )}
    </section>
  );
}
