"use client";

/**
 * Single sign-on (board A6): SAML group → org role mappings (add, delete with
 * confirm; admins only) and the read-only endpoints an admin hands their
 * identity provider, with live status and Copy on each. Base SAML/OIDC/SCIM
 * enablement is per deployment, not a setting here.
 */
import * as React from "react";
import Link from "next/link";
import { createSamlMapping, deleteSamlMapping, type SsoStatus } from "@/app/(app)/settings/organization/actions";
import { Chip, Content, KV, Loading, Sheet } from "../ui";
import { R } from "../routes";
import { AccountFrame, AccountHead, AdminsOnly, Banner, Confirm, CopyButton } from "./frame";
import * as api from "./api";
import { roleName, signIn, type OrgRole } from "./derive";

type State = SsoStatus["saml"]["state"];

function chipFor(state: State): { tone: "ok" | "warn" | "unk"; label: string } {
  if (state === "reachable") return { tone: "ok", label: "Reachable" };
  if (state === "misconfigured") return { tone: "warn", label: "Enabled, check settings" };
  if (state === "not_enabled") return { tone: "unk", label: "Not enabled" };
  return { tone: "unk", label: "Unknown" };
}

export function SsoScreen({ sso, authMode, magicLink }: { sso: SsoStatus; authMode: string; magicLink: boolean }) {
  const [org, setOrg] = React.useState<{ name: string; role: OrgRole } | null>(null);
  const [orgErr, setOrgErr] = React.useState<string | null>(null);
  const [mappings, setMappings] = React.useState<api.SamlMapping[] | null>(null);
  const [mapErr, setMapErr] = React.useState<string | null>(null);
  const [attr, setAttr] = React.useState("groups");
  const [value, setValue] = React.useState("");
  const [role, setRole] = React.useState<OrgRole>("member");
  const [adding, setAdding] = React.useState(false);
  const [addErr, setAddErr] = React.useState<string | null>(null);
  const [askDel, setAskDel] = React.useState<number | null>(null);
  const [delErr, setDelErr] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState(false);

  const loadMappings = React.useCallback(async () => {
    setMapErr(null);
    try {
      setMappings(await api.getMappings());
    } catch (e) {
      setMapErr(api.errText(e, "Mappings didn’t load."));
    }
  }, []);

  const load = React.useCallback(async () => {
    setOrgErr(null);
    try {
      const o = await api.getOrgs();
      const a = o.organizations.find((x) => x.org_id === o.active_org_id) ?? null;
      setOrg(a ? { name: a.name, role: a.org_role } : null);
      if (a?.org_role === "admin") await loadMappings();
    } catch (e) {
      setOrgErr(api.errText(e, "Couldn’t load your organization."));
    }
  }, [loadMappings]);
  React.useEffect(() => {
    void load();
  }, [load]);

  const admin = org?.role === "admin";
  const si = signIn(authMode, magicLink);
  const saml = chipFor(sso.saml.state);
  const oidc = chipFor(sso.oidc.state);
  const orgName = org?.name ?? "your organization";
  const n = mappings?.length ?? null;
  const samlWord = sso.saml.state === "reachable" ? "reachable" : sso.saml.state === "not_enabled" ? "not enabled" : sso.saml.state === "misconfigured" ? "check settings" : "status unknown";

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const a = attr.trim();
    const v = value.trim();
    if (!a || !v) {
      setAddErr(!a ? "Enter the SAML attribute." : "Enter the group value.");
      return;
    }
    setAdding(true);
    setAddErr(null);
    const r = await createSamlMapping(a, v, role);
    setAdding(false);
    if (!r.ok) {
      setAddErr(/already exists|duplicate/i.test(r.error) ? "That mapping already exists." : r.error);
      return;
    }
    setValue("");
    await loadMappings();
  }

  async function del(id: number) {
    setDeleting(true);
    setDelErr(null);
    const r = await deleteSamlMapping(id);
    setDeleting(false);
    if (!r.ok) {
      setDelErr(r.error);
      return;
    }
    setAskDel(null);
    await loadMappings();
  }

  const urls: { k: string; label: string; url: string; hint?: string; group: "saml" | "oidc" | "scim" }[] = [
    { k: "acs", label: "SAML ACS", url: sso.urls.samlAcs, group: "saml" },
    { k: "meta", label: "SAML SP metadata", url: sso.urls.samlMetadata, group: "saml" },
    { k: "slog", label: "SAML login", url: sso.urls.samlLogin, group: "saml" },
    { k: "olog", label: "OIDC login", url: sso.urls.oidcLogin, group: "oidc", hint: sso.oidc.state === "reachable" ? undefined : "Works after OIDC is turned on." },
    { k: "ocb", label: "OIDC callback", url: sso.urls.oidcCallback, group: "oidc", hint: sso.oidc.state === "reachable" ? undefined : "Register it with your provider first." },
    { k: "scim", label: "SCIM base URL", url: sso.urls.scimBase, group: "scim", hint: "Needs an org-scoped admin API key, issued at deploy time." },
  ];
  const row = (u: (typeof urls)[number]) => (
    <div className="a-url" key={u.k}>
      <span>{u.label}</span>
      <code title={u.url}>{u.url}</code>
      <CopyButton value={u.url} ariaLabel={`Copy ${u.label} URL`} />
      {u.hint ? <small>{u.hint}</small> : null}
    </div>
  );
  const cols = "160px minmax(0,1fr) 120px 80px";

  return (
    <AccountFrame label="Single sign-on">
      <AccountHead
        title="Single sign-on"
        meta={[
          <span key="s">SAML <b>{saml.label}</b></span>,
          <span key="o">OIDC <b>{oidc.label}</b></span>,
          <span key="d">Directory sync <b>Admin key needed</b></span>,
          ...(admin ? [<span key="g">Group mappings <b className="num">{n ?? "—"}</b></span>] : []),
          <span key="a">Admins only</span>,
        ]}
      />
      <Content>
        {orgErr ? (
          <Banner title="Couldn’t load your organization." actions={<button className="btn sm" type="button" onClick={() => void load()}>Try again</button>}>
            {orgErr}
          </Banner>
        ) : null}
        <section className="panel" aria-label="Groups to roles">
          <div className="ph">
            <h2>Groups to roles</h2>
            <span>Applied at SAML sign-in · grants only, never lowers or removes</span>
          </div>
          {!org && !orgErr ? (
            <Loading rows={2} label="Loading mappings" />
          ) : !admin ? (
            <AdminsOnly what="Only an organization admin maps identity-provider groups to roles." role={org ? roleName(org.role) : null} />
          ) : (
            <>
              <form className="a-frow" style={{ gridTemplateColumns: "170px minmax(0,1fr) 150px auto" }} onSubmit={add}>
                <label className="field">
                  SAML attribute
                  <input type="text" value={attr} onChange={(e) => setAttr(e.target.value)} aria-describedby="a-attr-h" maxLength={200} />
                </label>
                <label className="field">
                  Group value
                  <input type="text" placeholder="acme-admins" value={value} onChange={(e) => setValue(e.target.value)} maxLength={1000} aria-invalid={addErr ? true : undefined} />
                </label>
                <label className="field">
                  Grants role
                  <select value={role} onChange={(e) => setRole(e.target.value as OrgRole)}>
                    <option value="member">Member</option>
                    <option value="viewer">Viewer</option>
                    <option value="admin">Admin</option>
                  </select>
                </label>
                <button className="btn ink" type="submit" disabled={adding} aria-busy={adding}>
                  {adding ? "Adding…" : "Add mapping"}
                </button>
              </form>
              <p className="a-fh" id="a-attr-h" style={{ margin: "-6px 16px 10px" }}>
                Attribute is usually groups or memberOf.
              </p>
              {addErr ? (
                <p className="a-err" role="alert" style={{ margin: "-4px 16px 10px" }}>
                  {addErr}
                </p>
              ) : null}
              {mapErr ? (
                <Banner title="Couldn’t load mappings." actions={<button className="btn sm" type="button" onClick={() => void loadMappings()}>Try again</button>}>
                  {mapErr}
                </Banner>
              ) : !mappings ? (
                <Loading rows={1} label="Loading mappings" />
              ) : mappings.length === 0 ? (
                <div className="empty" style={{ padding: "16px 24px", borderTop: "1px solid var(--rule)" }}>
                  <b>No mappings</b>
                  <span>Without a match, a SAML user isn’t added to {orgName}.</span>
                </div>
              ) : (
                <div role="table" aria-label="Group mappings">
                  <div className="a-tr th" role="row" style={{ gridTemplateColumns: cols }}>
                    <span role="columnheader">Attribute</span>
                    <span role="columnheader">Group value</span>
                    <span role="columnheader">Grants</span>
                    <span role="columnheader">
                      <span className="sr">Actions</span>
                    </span>
                  </div>
                  {mappings.map((m) => (
                    <React.Fragment key={m.id}>
                      <div className="a-tr" role="row" style={{ gridTemplateColumns: cols }}>
                        <span role="cell" className="a-mono a-clip" data-l="Attribute" title={m.attribute_name}>
                          {m.attribute_name}
                        </span>
                        <span role="cell" className="a-mono a-clip" data-l="Group value" title={m.group_value}>
                          {m.group_value}
                        </span>
                        <span role="cell" data-l="Grants">
                          <Chip tone="unk">{roleName(m.org_role)}</Chip>
                        </span>
                        <span role="cell" className="a-acts">
                          <button className="btn sm" type="button" aria-label={`Delete mapping ${m.attribute_name} ${m.group_value}`} disabled={askDel === m.id} onClick={() => { setAskDel(m.id); setDelErr(null); }}>
                            Delete
                          </button>
                        </span>
                      </div>
                      {askDel === m.id ? (
                        <Confirm
                          label="Delete mapping"
                          question="Delete this mapping?"
                          detail="People who already signed in keep their role."
                          confirmLabel="Delete mapping"
                          danger
                          busy={deleting}
                          error={delErr}
                          onConfirm={() => void del(m.id)}
                          onCancel={() => setAskDel(null)}
                        />
                      ) : null}
                    </React.Fragment>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
        <section className="panel" aria-label="Endpoints for your identity provider">
          <div className="ph">
            <h2>Endpoints for your identity provider</h2>
            <span>Set per deployment · read only</span>
          </div>
          <div className="a-sth">
            SAML <Chip tone={saml.tone}>{saml.label}</Chip>
            {sso.saml.httpStatus != null ? <span className="a-mono">HTTP {sso.saml.httpStatus}</span> : null}
          </div>
          {urls.filter((u) => u.group === "saml").map(row)}
          <div className="a-sth" style={{ borderTop: "1px solid var(--rule)", marginTop: 4 }}>
            OIDC <Chip tone={oidc.tone}>{oidc.label}</Chip>
            {sso.oidc.httpStatus != null ? <span className="a-mono">HTTP {sso.oidc.httpStatus}</span> : null}
          </div>
          {urls.filter((u) => u.group === "oidc").map(row)}
          <div className="a-sth" style={{ borderTop: "1px solid var(--rule)", marginTop: 4 }}>
            Directory sync (SCIM 2.0)
          </div>
          {urls.filter((u) => u.group === "scim").map(row)}
          <div style={{ height: 10 }} />
        </section>
      </Content>
      <Sheet label="SAML sign-in" style={{ bottom: 20 }}>
        <div className="top">
          <h2 className="stitle">SAML sign-in</h2>
          <p className="smeta a-wrap">
            {orgName} · {samlWord}
          </p>
          <div className="figs">
            <div className="fig">
              <span>Mappings</span>
              <b className="num">{admin ? (n ?? "—") : "—"}</b>
              <small>groups</small>
            </div>
            <div className="fig">
              <span>No match</span>
              <b className="t">Not added</b>
              <small className="a-clip" style={{ maxWidth: 140 }} title={orgName}>
                to {orgName}
              </small>
            </div>
            <div className="fig">
              <span>Sign-in now</span>
              <b className="t">{si.passwordOn ? "Password" : si.ssoOnly ? "SSO" : si.linkOn ? "Email link" : "—"}</b>
              <small>{si.passwordOn && si.linkOn ? "or email link" : si.passwordOn && si.ssoOn ? "or single sign-on" : ""}</small>
            </div>
          </div>
        </div>
        <div className="scroll">
          <div className="a-step">
            <i>1</i>
            <span>
              <b>Give your provider the URLs</b>
              <span>ACS, metadata and login.</span>
            </span>
          </div>
          <div className="a-step">
            <i>2</i>
            <span>
              <b>Turned on for your deployment</b>
              <span>Status reads Reachable.</span>
            </span>
          </div>
          <div className="a-step">
            <i>3</i>
            <span>
              <b>Map groups to roles</b>
              <span>Checked at each SAML sign-in.</span>
            </span>
          </div>
          <div className="gh" style={{ marginTop: 8 }}>
            <span>Rules</span>
            <span />
          </div>
          <KV
            rows={[
              ["Membership", "Added at first matching sign-in"],
              ["Roles", "Raised, never lowered"],
              ["Removal", "Manual, in Organization"],
              ["Several groups match", "Highest role wins"],
            ]}
          />
          <div style={{ padding: "8px 12px" }}>
            <Link className="btn sm" href={R.org}>
              Members
            </Link>
          </div>
        </div>
      </Sheet>
    </AccountFrame>
  );
}
