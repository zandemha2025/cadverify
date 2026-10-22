"use client";

/**
 * Changes to review (board S3): rate card and supplier-profile drafts sent for
 * review. An organization admin approves (which publishes the draft as a new
 * version) or rejects with a note. The proposer can't approve their own change
 * when there's another admin; a sole admin's own approval reads "self-approved"
 * (ce-13). Everyone else sees the request and that it's waiting for an admin.
 */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { API_BASE } from "@/lib/api-base";
import { R, TABS } from "../routes";
import { Content, Empty, Loading, PageHead, Panel, Sheet, cx } from "../ui";
import { Banner, ShopWorld, isOrgAdmin, useOrg, usePartRecords, useRateCard, useToast } from "./common";
import { approveChange, getRateVersion, listChanges, rejectChange, type Assumption, type ChangeRequestRow, type RateVersionFull, type RecordDetail } from "./shop-api";
import { longDate, shortWhen } from "./shop-derive";
import { costLines, defaultsFrom, headlineEstimate } from "./rates-derive";
import { ASSET_NAMES, approvalRule, changeRows, diffCard, initials, noteLines, personName, pipeline } from "./changes-derive";

type V0 = { defaults: Assumption[]; laborRec: RecordDetail | null };

const money = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function useMembers(): Map<number, string> {
  const [m, setM] = React.useState<Map<number, string>>(new Map());
  React.useEffect(() => {
    let live = true;
    fetch(`${API_BASE}/orgs/members`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((b: { members?: { user_id: number; email: string }[] } | null) => {
        if (live && b?.members) setM(new Map(b.members.map((x) => [x.user_id, x.email])));
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return m;
}

export function ChangesScreen() {
  const { user } = useAuth();
  const me = user?.id ?? null;
  const org = useOrg();
  const admin = isOrgAdmin(org);
  const rc = useRateCard();
  // One request per load: the newest record of your 6 newest parts, with details.
  const recs = usePartRecords(6);
  const emails = useMembers();
  const [reqs, setReqs] = React.useState<ChangeRequestRow[] | null>(null);
  const [admins, setAdmins] = React.useState<number | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [versions, setVersions] = React.useState<Map<number, RateVersionFull | "missing">>(new Map());
  const [v0, setV0] = React.useState<V0 | null>(null);
  const [toast, showToast] = useToast();

  const load = React.useCallback(async () => {
    setError(null);
    try {
      const b = await listChanges();
      setReqs(b.change_requests ?? []);
      setAdmins(typeof b.admins === "number" ? b.admins : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load changes.");
    }
  }, []);
  React.useEffect(() => {
    void load();
  }, [load]);

  // The draft behind each rate card request (its version number and table).
  React.useEffect(() => {
    if (!reqs) return;
    let live = true;
    // A rejected draft may since have been discarded, so only open and approved requests are read.
    const ids = Array.from(new Set(reqs.filter((r) => r.asset_type === "rate_card" && r.status !== "rejected").map((r) => r.target_version_id))).filter((id) => !versions.has(id));
    if (!ids.length) return;
    Promise.allSettled(ids.map((id) => getRateVersion(id))).then((res) => {
      if (!live) return;
      setVersions((cur) => {
        const next = new Map(cur);
        res.forEach((r, i) => next.set(ids[i], r.status === "fulfilled" ? r.value : "missing"));
        return next;
      });
    });
    return () => {
      live = false;
    };
  }, [reqs, versions]);

  // Your newest checks: the default v0 values they recorded, and one part's labor today at v0.
  React.useEffect(() => {
    const ds: RecordDetail[] = recs.data?.details ?? [];
    if (!ds.length) return;
    const defaults = defaultsFrom(ds.map((d) => d.result?.assumptions));
    const laborRec = ds.find((d) => d.result?.assumptions?.some((a) => a.name === "labor_rate" && a.provenance === "DEFAULT") && headlineEstimate(d)) ?? null;
    setV0({ defaults, laborRec });
  }, [recs.data]);

  const waiting = (reqs ?? []).filter((r) => r.status === "proposed");
  const decided = (reqs ?? []).filter((r) => r.status !== "proposed");
  const governed = rc.view?.governed === true;
  const inUse = governed ? (rc.view?.inEffect?.version != null ? `v${rc.view.inEffect.version}` : "the published card") : "v0";

  return (
    <ShopWorld label="Changes to review">
      <PageHead
        title="Changes to review"
        meta={[
          <>
            Waiting <b className="num">{reqs ? waiting.length : "…"}</b>
          </>,
          <>
            Reviewed <b className="num">{reqs ? decided.length : "…"}</b>
          </>,
          <>
            Approver <b>{admins != null && admins > 1 ? "Another admin" : "Admins"}</b>
          </>,
          <>
            Covers <b>Rate card, supplier rate profiles</b>
          </>,
        ]}
        tabs={TABS.shop.map((t) => (t.href === R.changes && reqs && waiting.length ? { ...t, count: waiting.length } : t))}
        tabsLabel="Your shop"
      />
      <Content>
        {error ? (
          <Banner
            tone="bad"
            alert
            actions={
              <button className="btn sm" type="button" onClick={() => void load()}>
                Retry
              </button>
            }
          >
            <b>Couldn&apos;t load changes.</b> {error}
          </Banner>
        ) : null}
        <Panel title={waiting.length ? "Waiting for review" : undefined} note={waiting.length ? "Newest first" : undefined}>
          {!reqs && !error ? (
            <Loading rows={2} label="Loading changes" />
          ) : waiting.length === 0 ? (
            <Empty
              title="No changes to review"
              actions={
                <Link className="btn sm" href={R.rates}>
                  Draft rates
                </Link>
              }
            >
              Drafts from Rates appear here. Admins are notified.
            </Empty>
          ) : (
            waiting.map((r) => (
              <Request
                key={r.id}
                r={r}
                me={me}
                admin={admin}
                admins={admins}
                orgKnown={org != null}
                emails={emails}
                version={r.asset_type === "rate_card" ? versions.get(r.target_version_id) : undefined}
                basePayload={governed ? rc.eff?.payload ?? null : null}
                v0={v0}
                inUse={inUse}
                onDecided={async (text) => {
                  await load();
                  rc.reload();
                  showToast(text);
                }}
              />
            ))
          )}
        </Panel>
        <Panel title="History" note="All requests, newest first">
          {!reqs ? (
            error ? null : <Loading rows={1} label="Loading history" />
          ) : decided.length === 0 ? (
            <div className="empty" style={{ padding: "22px 24px" }}>
              <b>No reviewed changes</b>
            </div>
          ) : (
            decided.map((r) => {
              const v = r.asset_type === "rate_card" ? versions.get(r.target_version_id) : undefined;
              const vn = v && v !== "missing" ? v.version : null;
              const lines = noteLines(r.note);
              return (
                <div className="hrow2" key={r.id}>
                  <span style={{ minWidth: 0 }}>
                    <b style={{ fontWeight: 600 }}>{r.title || `${ASSET_NAMES[r.asset_type] ?? r.asset_type}${vn != null ? ` v${vn}` : ""}`}</b>
                    <small>
                      Proposed by {personName(r.proposed_by, me, emails)}
                      {r.created_at ? ` · ${longDate(r.created_at)}` : ""} · {r.status === "approved" ? "approved" : "rejected"} by {personName(r.reviewed_by, me, emails)}
                      {r.decided_at ? ` · ${shortWhen(r.decided_at)}` : ""}
                    </small>
                    {lines.map((l, i) => (
                      <small key={i} style={{ color: "var(--ink2)" }}>
                        {l}
                      </small>
                    ))}
                  </span>
                  <span className={cx("chip", r.status === "approved" ? (r.self_approved ? "c-warn" : "c-ok") : "c-bad")}>
                    <i aria-hidden="true" />
                    {r.status === "approved" ? `Published${vn != null ? ` v${vn}` : ""}${r.self_approved ? " · self-approved" : ""}` : "Rejected"}
                  </span>
                </div>
              );
            })
          )}
        </Panel>
      </Content>
      <Sheet label="How review works" style={{ bottom: 20 }}>
        <div className="top">
          <h2 className="stitle">Review rules</h2>
          <p className="smeta">Rate card · supplier rate profiles</p>
        </div>
        <div className="scroll">
          <div className="step">
            <i>1</i>
            <span>
              <b>Propose</b>
              <span>Member or admin, from Rates. No effect on costs.</span>
            </span>
          </div>
          <div className="step">
            <i>2</i>
            <span>
              <b>Review</b>
              <span>Admin approves and publishes, or rejects with a note.</span>
            </span>
          </div>
          <div className="step">
            <i>3</i>
            <span>
              <b>Publish</b>
              <span>New version used for new checks. Never edited in place. Older decisions are marked for re-costing.</span>
            </span>
          </div>
          <div className="gh" style={{ marginTop: 8 }}>
            <span>Roles</span>
            <span />
          </div>
          <div className="kv">
            <span>Viewers</span>
            <b>See requests</b>
            <span>Members</span>
            <b>Propose</b>
            <span>Admins</span>
            <b>{admins != null && admins > 1 ? "Approve others’ changes, reject" : "Approve, reject"}</b>
            <span>You</span>
            <b>{org == null ? "…" : org === "none" ? "No organization" : org.role[0].toUpperCase() + org.role.slice(1)}</b>
          </div>
          <div className="gh" style={{ marginTop: 8 }}>
            <span>Versions</span>
            <span />
          </div>
          <div className="kv">
            <span>In use</span>
            <b>{rc.view ? (governed ? `Rate card ${inUse}` : "Default v0") : "…"}</b>
            <span>Published</span>
            <b className="num">{rc.view ? rc.view.published : "…"}</b>
            <span>Each verdict</span>
            <b>Pins its version</b>
          </div>
          <div className="note">
            <b>Known gaps</b>
            <span>
              {admins != null && admins > 1
                ? "A proposer can’t approve their own change: another admin does."
                : "With one admin, their own changes are approved by them and marked self-approved. Add a second admin to separate proposing from approving."}{" "}
              Material catalogs aren&apos;t reviewed, and an admin can still publish a rate card directly through the API.
            </span>
          </div>
        </div>
      </Sheet>
      {toast}
    </ShopWorld>
  );
}

function Request({
  r,
  me,
  admin,
  admins,
  orgKnown,
  emails,
  version,
  basePayload,
  v0,
  inUse,
  onDecided,
}: {
  r: ChangeRequestRow;
  me: number | null;
  admin: boolean;
  admins: number | null;
  orgKnown: boolean;
  emails: Map<number, string>;
  version: RateVersionFull | "missing" | undefined;
  basePayload: unknown;
  v0: V0 | null;
  inUse: string;
  onDecided: (text: string) => Promise<void>;
}) {
  const [ask, setAsk] = React.useState<"approve" | "reject" | null>(null);
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const firstRef = React.useRef<HTMLButtonElement>(null);
  const noteRef = React.useRef<HTMLTextAreaElement>(null);
  const approveBtn = React.useRef<HTMLButtonElement>(null);
  const tid = React.useId();
  React.useEffect(() => {
    if (ask === "approve") firstRef.current?.focus();
    if (ask === "reject") noteRef.current?.focus();
  }, [ask]);

  const who = personName(r.proposed_by, me, emails);
  const mine = me != null && r.proposed_by === me;
  const asset = ASSET_NAMES[r.asset_type] ?? r.asset_type;
  const ver = version && version !== "missing" ? version : null;
  const vn = ver?.version ?? null;
  const name = `${asset.toLowerCase()}${vn != null ? ` v${vn}` : ""}`;
  // Every value the draft changes, from the server (labor, overhead, margin, machine rates, material prices); older reads fall back to the labor-and-global diff.
  const diff = ver ? (ver.changes ? changeRows(ver.changes) : diffCard(ver.payload ?? null, { payload: basePayload, assumptions: basePayload ? null : v0?.defaults })) : [];
  const rule = approvalRule({ mine, admin, admins });
  const stages = pipeline(r.status, vn);
  const lines = noteLines(r.note);
  // The proposer's note, less any line that only restates a row of the diff.
  const extra = lines.filter((l) => !diff.some((d) => l === `${d.name} ${d.from} → ${d.to}`));

  // Labor today on your newest check (the lines the labor rate pays for).
  const lr = basePayload ? null : v0?.laborRec ?? null;
  const est = lr ? headlineEstimate(lr) : null;
  const laborBase = lr?.result?.assumptions?.find((a) => a.name === "labor_rate")?.value ?? null;
  const laborToday = est && laborBase != null ? costLines(est, laborBase).filter((l) => l.scales).reduce((s, l) => s + l.value, 0) : null;
  const laborChanges = diff.some((d) => d.key === "labor_rate");

  const decide = async (kind: "approve" | "reject") => {
    setBusy(true);
    setErr(null);
    try {
      if (kind === "approve") {
        const res = await approveChange(r.id);
        const pv = res.published_version?.version ?? vn;
        await onDecided(`Published ${asset.toLowerCase()}${pv != null ? ` v${pv}` : ""}. Older decisions are marked for re-costing.`);
      } else {
        await rejectChange(r.id, note.trim());
        await onDecided(`Rejected. ${inUse} stays in use.`);
      }
      setBusy(false);
      setAsk(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't save the decision.");
      setBusy(false);
    }
  };

  return (
    <div className="req" aria-labelledby={tid} role="group">
      <div className="ph" style={{ padding: "12px 0 0" }}>
        <h2 id={tid} style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>
          {r.title || `${asset}${vn != null ? ` v${vn}` : ""}`}
        </h2>
        <span>
          {asset}
          {r.asset_type === "rate_card" ? ` · replaces ${inUse}` : ""}
        </span>
      </div>
      <div className="who">
        <i aria-hidden="true">{initials(who)}</i>
        <span>
          {mine ? <b style={{ color: "var(--ink)", fontWeight: 600 }}>Proposed by you</b> : <>Proposed by {who}</>}
          {r.created_at ? ` · ${shortWhen(r.created_at)}` : ""}
        </span>
      </div>
      {diff.length ? (
        diff.map((d) => (
          <div className="diff" key={d.key}>
            <span>{d.name}</span>
            <s className="num">{d.from}</s>
            <span aria-hidden="true">→</span>
            <b className="num">
              <span className="sr">changes to </span>
              {d.to}
            </b>
          </div>
        ))
      ) : version === undefined && r.asset_type === "rate_card" ? (
        <p className="fh" style={{ margin: 0 }} role="status">
          Reading the draft…
        </p>
      ) : (
        lines.map((l, i) => (
          <div className="diff" key={i} style={{ gridTemplateColumns: "minmax(0,1fr)" }}>
            <span>{l}</span>
          </div>
        ))
      )}
      {diff.length && extra.length ? (
        <p className="fh" style={{ margin: 0 }}>
          {extra.join(" · ")}
        </p>
      ) : null}
      <div className="kv" style={{ padding: 0 }}>
        <span>Affects</span>
        <b>New checks, all parts</b>
        <span>Earlier verdicts</span>
        <b>Keep the version they used; marked for re-costing</b>
        {laborChanges && laborToday != null && est && lr ? (
          <>
            <span>{lr.label || lr.filename} labor today</span>
            <b className="num">
              {money(laborToday)} of {money(est.unit_cost_usd)}
            </b>
          </>
        ) : null}
      </div>
      <div className="pipe" aria-label={`Status: ${stages.find((s) => s.state === "cur" || s.state === "bad")?.label ?? stages[stages.length - 1].label}`}>
        {stages.map((s, i) => (
          <React.Fragment key={s.label}>
            {i ? <em aria-hidden="true">→</em> : null}
            <span className={cx(s.state === "done" && "done", s.state === "cur" && "cur", s.state === "bad" && "bad")}>{s.label}</span>
          </React.Fragment>
        ))}
      </div>
      {!orgKnown ? null : rule === "not-admin" ? (
        <p className="fh" style={{ margin: 0 }}>
          Waiting for an admin.
        </p>
      ) : ask === null ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {rule === "other-admin" ? null : (
            <button className="btn ink sm" type="button" ref={approveBtn} onClick={() => setAsk("approve")}>
              {rule === "self" ? "Approve as the only admin" : "Approve and publish"}
            </button>
          )}
          <button className="btn sm" type="button" onClick={() => setAsk("reject")}>
            {mine ? "Withdraw" : "Reject"}
          </button>
          <span className="fh">
            {rule === "other-admin"
              ? "You proposed this, so another admin approves it."
              : rule === "self"
                ? "You’re the only admin, so it will be recorded as self-approved."
                : "Admins only."}
          </span>
        </div>
      ) : ask === "approve" ? (
        <div className="confirm" role="alertdialog" aria-label="Approve and publish" style={{ margin: 0 }}>
          <b>Publish {name}?</b>
          <span>
            New checks cost against {vn != null ? `v${vn}` : "it"}. Earlier verdicts keep {inUse} and are marked for re-costing.
            {mine ? " You proposed this change; it will read self-approved." : ""}
          </span>
          {err ? (
            <span className="err" role="alert">
              {err}
            </span>
          ) : null}
          <span className="bx">
            <button className="btn ink sm" type="button" ref={firstRef} onClick={() => void decide("approve")} disabled={busy}>
              {busy ? "Publishing…" : "Approve and publish"}
            </button>
            <button
              className="btn sm"
              type="button"
              onClick={() => {
                setAsk(null);
                setErr(null);
                requestAnimationFrame(() => approveBtn.current?.focus());
              }}
              disabled={busy}
            >
              Cancel
            </button>
          </span>
        </div>
      ) : (
        <div className="confirm" role="alertdialog" aria-label="Reject change" style={{ margin: 0 }}>
          <b>Reject {name}?</b>
          <label className="field">
            Note to proposer
            <textarea ref={noteRef} rows={2} aria-label="Note to proposer" placeholder="Optional. Shown on the request." value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          {err ? (
            <span className="err" role="alert">
              {err}
            </span>
          ) : null}
          <span className="bx">
            <button className="btn danger sm" type="button" onClick={() => void decide("reject")} disabled={busy}>
              {busy ? "Rejecting…" : "Reject change"}
            </button>
            <button
              className="btn sm"
              type="button"
              onClick={() => {
                setAsk(null);
                setErr(null);
                requestAnimationFrame(() => approveBtn.current?.focus());
              }}
              disabled={busy}
            >
              Cancel
            </button>
          </span>
        </div>
      )}
    </div>
  );
}
