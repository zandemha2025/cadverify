"use client";

/**
 * Organization (board A1): the active organization and switcher, members with
 * org role (confirm, self-demotion warning) and workspace role, leave/remove
 * with confirm, invites with a shown-once link, and the invitation list with
 * revoke confirm. The sheet shows one member and how the team signs in.
 *
 * Admin-only parts (invite, invitations, other people's roles, removing
 * members) are hidden for non-admins; the backend enforces the same rules.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/ui/auth-provider";
import {
  createInvite,
  removeMember,
  revokeInvite,
  switchOrganization,
  getSsoStatus,
  type SsoStatus,
} from "@/app/(app)/settings/organization/actions";
import { Chip, Content, Failed, KV, Loading, Panel, Sheet, cx } from "../ui";
import { R } from "../routes";
import { useShell } from "../shell";
import { DeleteOrgPanel } from "../datacontrol/delete-org";
import { SignoffPanel } from "./signoff-panel";
import { TwoStepRulePanel } from "./two-step-org";
import { AccountFrame, AccountHead, Banner, Confirm, CopyButton } from "./frame";
import * as api from "./api";
import {
  ORG_ROLES,
  ORG_ROLE_DOES,
  WORKSPACE_ROLES,
  dateLabel,
  dayLabel,
  domainOf,
  initials,
  inviteChip,
  orgRoleChange,
  orgRoleLocked,
  planName,
  orgRoleNote,
  roleName,
  signIn,
  workspaceRoleChange,
  type OrgRole,
} from "./derive";

type Ask =
  | { kind: "org"; userId: number; next: OrgRole }
  | { kind: "ws"; userId: number; next: string }
  | { kind: "remove"; userId: number }
  | { kind: "revoke"; inviteId: number };

const PROVIDER: Record<string, string> = {
  password: "Password",
  magic_link: "Email link",
  google: "Google",
  saml: "Single sign-on (SAML)",
  oidc: "Single sign-on (OIDC)",
};

export function OrgScreen({ authMode, magicLink }: { authMode: string; magicLink: boolean }) {
  const router = useRouter();
  const { user } = useAuth();
  const { usage } = useShell();
  const me = user?.id ?? null;

  const [orgs, setOrgs] = React.useState<api.OrgList | null>(null);
  const [orgsErr, setOrgsErr] = React.useState<string | null>(null);
  const [members, setMembers] = React.useState<api.OrgMember[] | null>(null);
  const [invites, setInvites] = React.useState<api.OrgInvite[] | null>(null);
  const [platform, setPlatform] = React.useState<Map<number, api.PlatformUser> | null>(null);
  const [mappings, setMappings] = React.useState<number | null>(null);
  const [sso, setSso] = React.useState<SsoStatus | null>(null);
  const [accessErr, setAccessErr] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<number | null>(null);
  const [ask, setAsk] = React.useState<Ask | null>(null);
  const [askErr, setAskErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState<string | null>(null);

  const active = orgs?.organizations.find((o) => o.org_id === orgs.active_org_id) ?? orgs?.organizations.find((o) => o.is_active) ?? null;
  const isAdmin = active?.org_role === "admin";
  const superadmin = user?.role === "superadmin";

  const load = React.useCallback(async () => {
    setOrgsErr(null);
    setAccessErr(null);
    let list: api.OrgList;
    try {
      list = await api.getOrgs();
      setOrgs(list);
    } catch (e) {
      setOrgsErr(api.errText(e, "Couldn’t load your organizations."));
      return;
    }
    const act = list.organizations.find((o) => o.org_id === list.active_org_id) ?? list.organizations.find((o) => o.is_active);
    if (!act) {
      setMembers([]);
      return;
    }
    const admin = act.org_role === "admin";
    const problems: string[] = [];
    await Promise.all([
      api.getMembers().then(setMembers, (e) => {
        setMembers(null);
        problems.push(api.errText(e, "Members didn’t load."));
      }),
      admin
        ? api.getInvites().then(setInvites, (e) => {
            setInvites(null);
            problems.push(api.errText(e, "Invitations didn’t load."));
          })
        : Promise.resolve(setInvites(null)),
      admin
        ? api.getPlatformUsers().then(
            (us) => setPlatform(new Map(us.map((u) => [u.id, u]))),
            () => setPlatform(null),
          )
        : Promise.resolve(setPlatform(null)),
      admin ? api.getMappings().then((m) => setMappings(m.length), () => setMappings(null)) : Promise.resolve(setMappings(null)),
    ]);
    if (problems.length) setAccessErr(problems.join(" "));
  }, []);

  React.useEffect(() => {
    void load();
    getSsoStatus().then(setSso, () => setSso(null));
  }, [load]);

  React.useEffect(() => {
    if (!done) return;
    const t = window.setTimeout(() => setDone(null), 4000);
    return () => window.clearTimeout(t);
  }, [done]);

  const adminCount = (members ?? []).filter((m) => m.org_role === "admin").length;
  const pending = (invites ?? []).filter((i) => i.status === "pending").length;
  const plan = planName(usage);
  const orgName = active?.name ?? "this organization";
  const sel = (members ?? []).find((m) => m.user_id === (selected ?? me)) ?? (members ?? [])[0] ?? null;

  const cancel = () => {
    setAsk(null);
    setAskErr(null);
  };

  async function confirmAsk() {
    if (!ask) return;
    setBusy(true);
    setAskErr(null);
    try {
      if (ask.kind === "org") {
        const target = members?.find((m) => m.user_id === ask.userId);
        await api.setOrgRole(ask.userId, ask.next);
        setDone(`${target && target.user_id === me ? "Your org role" : "Org role"} changed to ${roleName(ask.next)}.`);
        setAsk(null);
        await load();
        router.refresh();
      } else if (ask.kind === "ws") {
        await api.setWorkspaceRole(ask.userId, ask.next);
        setDone(`Account tier changed to ${roleName(ask.next)}.`);
        setAsk(null);
        await load();
      } else if (ask.kind === "remove") {
        const self = ask.userId === me;
        const r = await removeMember(ask.userId);
        if (!r.ok) {
          setAskErr(/last admin/i.test(r.error) ? "You’re the only admin. Make another member admin first." : r.error);
          return;
        }
        setAsk(null);
        if (self) {
          router.push(R.home);
          router.refresh();
          return;
        }
        setDone("Member removed.");
        await load();
      } else if (ask.kind === "revoke") {
        const r = await revokeInvite(ask.inviteId);
        if (!r.ok) {
          setAskErr(r.error);
          return;
        }
        setAsk(null);
        setDone("Invite revoked.");
        await load();
      }
    } catch (e) {
      setAskErr(api.errText(e, "Nothing changed. Try again."));
    } finally {
      setBusy(false);
    }
  }

  const meta: React.ReactNode[] = [];
  if (active) meta.push(<b key="o" className="a-clip" style={{ display: "inline-block", maxWidth: 320, verticalAlign: "bottom" }} title={active.name}>{active.name}</b>);
  meta.push(<span key="m">Members <b className="num">{members ? members.length : "—"}</b></span>);
  if (isAdmin) meta.push(<span key="p">Pending invites <b className="num">{invites ? pending : "—"}</b></span>);
  if (active) meta.push(<span key="r">Your role <b>{roleName(active.org_role)}</b></span>);
  if (plan) meta.push(<span key="pl">Plan <b>{plan}</b></span>);

  return (
    <AccountFrame label="Organization">
      <AccountHead title="Organization" meta={meta} />
      <Content>
        {orgsErr ? (
          <Failed title="Couldn’t load your organizations." detail={orgsErr} onRetry={() => void load()} />
        ) : !orgs ? (
          <div className="panel">
            <Loading rows={3} label="Loading organization" />
          </div>
        ) : !active ? (
          <div className="panel">
            <div className="empty">
              <b>No organization yet</b>
              <span>Open the invite link an admin sent you to join one.</span>
            </div>
          </div>
        ) : (
          <>
            {accessErr ? (
              <Banner title="Couldn’t load members or invites." actions={<button className="btn sm" type="button" onClick={() => void load()}>Try again</button>}>
                {accessErr}
              </Banner>
            ) : null}
            {isAdmin ? (
              <NamePanel
                key={active.org_id}
                name={active.name}
                onRenamed={async () => {
                  await load();
                  router.refresh();
                }}
              />
            ) : null}
            <SwitchPanel orgs={orgs} activeId={active.org_id} onSwitched={async () => {
              setSelected(null);
              setAsk(null);
              await load();
              router.refresh();
            }} />
            <Panel title="Members" note={members ? String(members.length) : undefined}>
              {!members ? (
                accessErr ? null : <Loading rows={2} label="Loading members" />
              ) : (
                <MembersTable
                  members={members}
                  me={me}
                  isAdmin={isAdmin}
                  superadmin={superadmin}
                  platform={platform}
                  myPlatformRole={user?.role ?? null}
                  adminCount={adminCount}
                  orgName={orgName}
                  selected={sel?.user_id ?? null}
                  onSelect={setSelected}
                  ask={ask}
                  askErr={askErr}
                  busy={busy}
                  onAsk={(a) => {
                    setAsk(a);
                    setAskErr(null);
                    setDone(null);
                  }}
                  onConfirm={() => void confirmAsk()}
                  onCancel={cancel}
                />
              )}
              <div aria-live="polite">
                {done && ask == null ? (
                  <div className="toast swap a-toast" role="status">
                    <span>{done}</span>
                  </div>
                ) : null}
              </div>
              <p className="a-fh" style={{ margin: "4px 16px 12px" }}>
                {orgRoleNote(orgName, superadmin)}
              </p>
            </Panel>
            <SignoffPanel />
            <TwoStepRulePanel me={me} />
            {isAdmin ? (
              <>
                <InvitePanel onInvited={() => void load()} domain={user?.email ? domainOf(user.email) : ""} />
                <Panel title="Invitations" note={invites ? String(invites.length) : undefined}>
                  {!invites ? (
                    accessErr ? null : <Loading rows={1} label="Loading invitations" />
                  ) : invites.length === 0 ? (
                    <div className="empty" style={{ padding: "18px 24px" }}>
                      <b>No invitations</b>
                    </div>
                  ) : (
                    <div role="table" aria-label="Invitations">
                      <div className="a-tr th" role="row" style={{ gridTemplateColumns: "minmax(0,1.6fr) 90px 100px 120px 90px" }}>
                        <span role="columnheader">Email</span>
                        <span role="columnheader">Role</span>
                        <span role="columnheader">Status</span>
                        <span role="columnheader">Expires</span>
                        <span role="columnheader">
                          <span className="sr">Actions</span>
                        </span>
                      </div>
                      {invites.map((inv) => {
                        const chip = inviteChip(inv.status);
                        const asking = ask?.kind === "revoke" && ask.inviteId === inv.id;
                        return (
                          <React.Fragment key={inv.id}>
                            <div className="a-tr" role="row" style={{ gridTemplateColumns: "minmax(0,1.6fr) 90px 100px 120px 90px" }}>
                              <span role="cell" className="a-clip" title={inv.email}>
                                {inv.email}
                              </span>
                              <span role="cell" data-l="Role">{roleName(inv.role)}</span>
                              <span role="cell" data-l="Status">
                                <Chip tone={chip.tone}>{chip.label}</Chip>
                              </span>
                              <span role="cell" className="num" data-l={inv.status === "accepted" ? undefined : "Expires"}>
                                {inv.status === "accepted" ? `Joined ${dayLabel(inv.accepted_at)}` : dateLabel(inv.expires_at)}
                              </span>
                              <span role="cell" className="a-acts">
                                {inv.status === "pending" ? (
                                  <button className="btn sm" type="button" aria-label={`Revoke invite for ${inv.email}`} onClick={() => { setAsk({ kind: "revoke", inviteId: inv.id }); setAskErr(null); }} disabled={asking}>
                                    Revoke
                                  </button>
                                ) : (
                                  <span className="a-fh">—</span>
                                )}
                              </span>
                            </div>
                            {asking ? (
                              <Confirm
                                label="Revoke invite"
                                question="Revoke this invite?"
                                detail={`The one-time link for ${inv.email} stops working now.`}
                                confirmLabel="Revoke invite"
                                danger
                                busy={busy}
                                error={askErr}
                                onConfirm={() => void confirmAsk()}
                                onCancel={cancel}
                              />
                            ) : null}
                          </React.Fragment>
                        );
                      })}
                    </div>
                  )}
                </Panel>
                <DeleteOrgPanel orgName={active.name} />
              </>
            ) : null}
          </>
        )}
      </Content>
      <Sheet label="Member" style={{ bottom: 20 }}>
        {sel && active ? (
          <MemberSheet
            m={sel}
            self={sel.user_id === me}
            orgName={active.name}
            orgId={active.org_id}
            platform={platform?.get(sel.user_id) ?? null}
            myProvider={user?.auth_provider ?? null}
            myPlatformRole={user?.role ?? null}
            tier={usage?.tier ?? null}
            adminCount={members ? adminCount : null}
            mappings={mappings}
            sso={sso}
            authMode={authMode}
            magicLink={magicLink}
            isAdmin={isAdmin}
            staff={superadmin}
          />
        ) : (
          <div className="top">
            <h2 className="stitle">Member</h2>
            <p className="smeta">{orgs && !active ? "No organization" : orgsErr || (orgs && !members && accessErr) ? "Members didn’t load" : "Loading…"}</p>
          </div>
        )}
      </Sheet>
    </AccountFrame>
  );
}

function SwitchPanel({ orgs, activeId, onSwitched }: { orgs: api.OrgList; activeId: string; onSwitched: () => Promise<void> }) {
  const [pick, setPick] = React.useState(activeId);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  React.useEffect(() => setPick(activeId), [activeId]);
  const n = orgs.organizations.length;
  return (
    <Panel title="Active organization" note="Lists, records, downloads, jobs and keys follow it">
      <div className="a-frow" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
        <label className="field">
          Organization
          <select aria-describedby="a-org-h" value={pick} disabled={n < 2 || busy} onChange={(e) => setPick(e.target.value)}>
            {orgs.organizations.map((o) => (
              <option key={o.org_id} value={o.org_id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn sm"
          type="button"
          disabled={pick === activeId || busy}
          aria-busy={busy}
          onClick={async () => {
            setBusy(true);
            setErr(null);
            const r = await switchOrganization(pick);
            if (!r.ok) setErr(r.error);
            else await onSwitched();
            setBusy(false);
          }}
        >
          {busy ? "Switching…" : "Switch"}
        </button>
      </div>
      {err ? (
        <p className="a-err" role="alert" style={{ margin: "-4px 16px 8px" }}>
          {err}
        </p>
      ) : null}
      <p className="a-fh" id="a-org-h" style={{ margin: "-4px 16px 12px" }}>
        You belong to {n === 1 ? "1 organization" : `${n} organizations`}. Every member sees this.
      </p>
    </Panel>
  );
}

function MembersTable(props: {
  members: api.OrgMember[];
  me: number | null;
  isAdmin: boolean;
  superadmin: boolean;
  platform: Map<number, api.PlatformUser> | null;
  myPlatformRole: string | null;
  adminCount: number;
  orgName: string;
  selected: number | null;
  onSelect: (id: number) => void;
  ask: Ask | null;
  askErr: string | null;
  busy: boolean;
  onAsk: (a: Ask) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { members, me, isAdmin, superadmin, platform, adminCount, orgName, ask } = props;
  // One role per person: the org role. The account tier ("workspace role",
  // set by ScaleCAD staff) is shown only to staff, and to everyone only when
  // it narrows a person to view-only.
  const cols = superadmin ? "minmax(0,1.6fr) 120px 150px 110px 90px" : "minmax(0,1.6fr) 120px 110px 90px";
  return (
    <div role="table" aria-label="Members">
      <div className="a-tr th" role="row" style={{ gridTemplateColumns: cols }}>
        <span role="columnheader">Member</span>
        <span role="columnheader">Org role</span>
        {superadmin ? <span role="columnheader">Account tier (staff)</span> : null}
        <span role="columnheader">Joined</span>
        <span role="columnheader">
          <span className="sr">Actions</span>
        </span>
      </div>
      {members.map((m) => {
        const self = m.user_id === me;
        const wsRole = platform?.get(m.user_id)?.role ?? (self ? props.myPlatformRole : null);
        const locked = orgRoleLocked({ role: m.org_role }, adminCount);
        const orgAsk = ask?.kind === "org" && ask.userId === m.user_id ? ask : null;
        const wsAsk = ask?.kind === "ws" && ask.userId === m.user_id ? ask : null;
        const removeAsk = ask?.kind === "remove" && ask.userId === m.user_id;
        const canRemove = self || isAdmin;
        const change = orgAsk ? orgRoleChange({ email: m.email, role: m.org_role, self }, orgAsk.next, orgName) : null;
        return (
          <React.Fragment key={m.user_id}>
            <div className="a-tr" role="row" style={{ gridTemplateColumns: cols }}>
              <span role="cell">
                <button type="button" className={cx("a-cellbtn", members.length > 1 && props.selected === m.user_id && "on")} aria-pressed={props.selected === m.user_id} onClick={() => props.onSelect(m.user_id)} aria-label={`Show ${m.email}${self ? " (you)" : ""}`}>
                  <span className="a-av" aria-hidden="true">
                    {initials(m.email)}
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <b className="a-clip" style={{ display: "block" }} title={m.email}>
                      {m.email}
                    </b>
                    <small>
                      {[domainOf(m.email), self ? "You" : null, m.is_active ? null : "Deactivated", !superadmin && wsRole === "viewer" ? "View-only account (set by ScaleCAD)" : null].filter(Boolean).join(" · ")}
                    </small>
                  </span>
                </button>
              </span>
              <span role="cell" data-l="Org role">
                {isAdmin && !locked ? (
                  <label>
                    <span className="sr">Org role for {m.email}</span>
                    <select value={orgAsk ? orgAsk.next : m.org_role} disabled={props.busy} onChange={(e) => {
                      const next = e.target.value as OrgRole;
                      if (next === m.org_role) props.onCancel();
                      else props.onAsk({ kind: "org", userId: m.user_id, next });
                    }}>
                      {ORG_ROLES.map((r) => (
                        <option key={r} value={r}>
                          {roleName(r)}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <Chip tone="unk" title={isAdmin && locked ? "The only admin. Make another member admin to change this." : undefined}>
                    {roleName(m.org_role)}
                  </Chip>
                )}
              </span>
              {superadmin ? (
              <span role="cell" data-l="Account tier (staff)">
                {!self ? (
                  <label>
                    <span className="sr">Account tier for {m.email}</span>
                    <select value={wsAsk ? wsAsk.next : wsRole ?? ""} disabled={props.busy || !wsRole} onChange={(e) => {
                      const next = e.target.value;
                      if (next === wsRole) props.onCancel();
                      else props.onAsk({ kind: "ws", userId: m.user_id, next });
                    }}>
                      {!wsRole ? <option value="">Unknown</option> : null}
                      {WORKSPACE_ROLES.map((r) => (
                        <option key={r} value={r}>
                          {roleName(r)}
                        </option>
                      ))}
                      {wsRole && !(WORKSPACE_ROLES as readonly string[]).includes(wsRole) ? (
                        <option value={wsRole} disabled>
                          {roleName(wsRole)}
                        </option>
                      ) : null}
                    </select>
                  </label>
                ) : (
                  <span title="Account tiers are set by ScaleCAD staff." aria-label={`Account tier for ${m.email}: ${roleName(wsRole)}`}>
                    {roleName(wsRole)}
                  </span>
                )}
              </span>
              ) : null}
              <span role="cell" className="num" data-l="Joined">
                {dateLabel(m.joined_at)}
              </span>
              <span role="cell" className="a-acts">
                {canRemove ? (
                  <button className="btn sm" type="button" disabled={removeAsk} aria-label={self ? `Leave ${orgName}` : `Remove ${m.email}`} onClick={() => props.onAsk({ kind: "remove", userId: m.user_id })}>
                    {self ? "Leave" : "Remove"}
                  </button>
                ) : null}
              </span>
            </div>
            {orgAsk && change ? (
              <Confirm label="Change role" question={change.question} detail={change.detail} confirmLabel="Change role" busy={props.busy} error={props.askErr} onConfirm={props.onConfirm} onCancel={props.onCancel} />
            ) : null}
            {wsAsk ? (
              <Confirm label="Change workspace role" {...workspaceRoleChange({ email: m.email }, wsAsk.next)} confirmLabel="Change role" busy={props.busy} error={props.askErr} onConfirm={props.onConfirm} onCancel={props.onCancel} />
            ) : null}
            {removeAsk ? (
              self ? (
                <Confirm
                  label="Leave organization"
                  question={`Leave ${orgName}?`}
                  detail="You lose its parts, records and keys."
                  confirmLabel="Leave organization"
                  danger
                  busy={props.busy}
                  blocked={m.org_role === "admin" && adminCount <= 1}
                  error={m.org_role === "admin" && adminCount <= 1 ? "You’re the only admin. Make another member admin first." : props.askErr}
                  onConfirm={props.onConfirm}
                  onCancel={props.onCancel}
                />
              ) : (
                <Confirm label="Remove member" question={`Remove ${m.email}?`} detail={`They lose access to ${orgName} now, and their API keys for it stop working.`} confirmLabel="Remove member" danger busy={props.busy} error={props.askErr} onConfirm={props.onConfirm} onCancel={props.onCancel} />
              )
            ) : null}
          </React.Fragment>
        );
      })}
    </div>
  );
}

/** The organization's name (admins): what the header, invites and members see. */
function NamePanel({ name, onRenamed }: { name: string; onRenamed: () => Promise<void> }) {
  const [value, setValue] = React.useState(name);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);
  const clean = value.split(/\s+/).filter(Boolean).join(" ");
  const changed = clean !== name;
  return (
    <Panel title="Name" note="Admins only · the header, invitations and members see it">
      <form
        className="a-frow"
        style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}
        onSubmit={async (e) => {
          e.preventDefault();
          if (!clean || !changed || busy) return;
          setBusy(true);
          setErr(null);
          setSaved(false);
          try {
            await api.renameOrg(clean);
            setSaved(true);
            await onRenamed();
          } catch (e2) {
            setErr(api.errText(e2, "The name wasn’t changed. Try again."));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="field">
          Organization name
          <input
            type="text"
            required
            maxLength={80}
            autoComplete="organization"
            value={value}
            aria-invalid={err ? true : undefined}
            onChange={(e) => {
              setValue(e.target.value);
              setSaved(false);
            }}
          />
        </label>
        <button className="btn ink" type="submit" disabled={busy || !clean || !changed} aria-busy={busy}>
          {busy ? "Saving…" : "Rename"}
        </button>
      </form>
      <div aria-live="polite">
        {err ? (
          <p className="a-err" role="alert" style={{ margin: "-4px 16px 10px" }}>
            {err}
          </p>
        ) : saved ? (
          <p className="smeta" role="status" style={{ margin: "-4px 16px 12px" }}>
            Renamed. Members see the new name next time a page loads.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}

function InvitePanel({ onInvited, domain }: { onInvited: () => void; domain: string }) {
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<OrgRole>("member");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [link, setLink] = React.useState<{ url: string; emailed: boolean; to: string } | null>(null);
  return (
    <Panel title="Invite" note="Admins only · emailed when email is set up">
      <form
        className="a-frow"
        style={{ gridTemplateColumns: "minmax(0,1fr) 160px auto" }}
        onSubmit={async (e) => {
          e.preventDefault();
          const to = email.trim();
          if (!to) return;
          setBusy(true);
          setErr(null);
          setLink(null);
          const r = await createInvite(to, role);
          setBusy(false);
          if (!r.ok) {
            setErr(r.error);
            return;
          }
          setLink({ url: r.data?.accept_link ?? "", emailed: !!r.data?.emailed, to });
          setEmail("");
          onInvited();
        }}
      >
        <label className="field">
          Email
          <input type="email" required autoComplete="off" placeholder={domain ? `teammate@${domain}` : "teammate@company.com"} value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={err ? true : undefined} />
        </label>
        <label className="field">
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as OrgRole)}>
            <option value="member">Member</option>
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        <button className="btn ink" type="submit" disabled={busy} aria-busy={busy}>
          {busy ? "Sending…" : "Send invite"}
        </button>
      </form>
      {err ? (
        <p className="a-err" role="alert" style={{ margin: "-4px 16px 10px" }}>
          {err}
        </p>
      ) : null}
      <div aria-live="polite">
        {link && link.url ? (
          <div className="a-link1 swap" role="status">
            <code title={link.url}>{link.url}</code>
            <CopyButton value={link.url} ariaLabel="Copy invite link" />
            <small>
              {link.emailed ? `Emailed to ${link.to}. ` : ""}Shown once. Gone when you leave this page. Single use.
            </small>
          </div>
        ) : null}
      </div>
      <div className="a-roles">
        {(["viewer", "member", "admin"] as const).map((r) => (
          <div key={r}>
            <b>{roleName(r)}</b>
            {ORG_ROLE_DOES[r]}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function MemberSheet(p: {
  m: api.OrgMember;
  self: boolean;
  orgName: string;
  orgId: string;
  platform: api.PlatformUser | null;
  myProvider: string | null;
  myPlatformRole: string | null;
  tier: string | null;
  adminCount: number | null;
  mappings: number | null;
  sso: SsoStatus | null;
  authMode: string;
  magicLink: boolean;
  isAdmin: boolean;
  /** ScaleCAD staff (superadmin): sees each account's tier. */
  staff: boolean;
}) {
  const ws = p.platform?.role ?? (p.self ? p.myPlatformRole : null);
  const provider = p.platform?.auth_provider ?? (p.self ? p.myProvider : null);
  const si = signIn(p.authMode, p.magicLink);
  const samlOn = p.sso?.saml.state === "reachable";
  const oidcOn = p.sso?.oidc.state === "reachable";
  const ssoLine = !p.sso ? "Checking…" : samlOn && oidcOn ? "SAML and OIDC on" : samlOn ? "SAML on" : oidcOn ? "OIDC on" : "Not enabled";
  const kind = p.self && p.tier === "work" ? "Work email" : p.self && p.tier === "personal" ? "Personal email" : null;
  return (
    <>
      <div className="top">
        <h2 className="stitle a-wrap">{p.m.email}</h2>
        <p className="smeta">{[kind ? `${kind} at ${domainOf(p.m.email)}` : domainOf(p.m.email), p.self ? "You" : null].filter(Boolean).join(" · ")}</p>
        <div className="figs">
          <div className="fig">
            <span>Org role</span>
            <b className="t">{roleName(p.m.org_role)}</b>
            <small className="a-clip" style={{ maxWidth: 140 }} title={p.orgName}>
              {p.orgName}
            </small>
          </div>
          {p.staff || ws === "viewer" ? (
            <div className="fig">
              <span>Account</span>
              <b className="t">{ws === "viewer" ? "View-only" : roleName(ws)}</b>
              <small>{p.staff ? "tier (staff)" : "set by ScaleCAD"}</small>
            </div>
          ) : null}
          <div className="fig">
            <span>Joined</span>
            <b className="num">{dayLabel(p.m.joined_at)}</b>
            <small>{p.m.joined_at ? new Date(p.m.joined_at).getUTCFullYear() : ""}</small>
          </div>
        </div>
      </div>
      <div className="scroll">
        <KV
          rows={[
            ["Sign-in", provider ? PROVIDER[provider] ?? roleName(provider) : "—"],
            ["Admins in org", p.adminCount == null ? "—" : String(p.adminCount)],
            ["Organization ID", <span key="id" className="a-mono" style={{ fontWeight: 500, overflowWrap: "anywhere" }}>{p.orgId}</span>],
          ]}
        />
        <div className="gh" style={{ marginTop: 8 }}>
          <span>Sign-in for the team</span>
          <span />
        </div>
        <KV
          rows={[
            ["Password or email link", si.passwordOn || si.linkOn ? "On" : "Off"],
            ["Single sign-on", ssoLine],
            ["Directory sync (SCIM)", "Set up with ScaleCAD support"],
            ["Groups to roles", p.isAdmin ? (p.mappings == null ? "—" : String(p.mappings)) : "Admins see these"],
          ]}
        />
        <div style={{ padding: "8px 12px", display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Link className="btn sm" href={R.sso}>
            Single sign-on
          </Link>
          <Link className="btn sm" href={R.security}>
            Security
          </Link>
        </div>
        <div className="note">
          <b>Removing people</b>
          <span>Removing a member or leaving asks first. The last admin can’t leave.</span>
        </div>
      </div>
    </>
  );
}
