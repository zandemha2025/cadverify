"use client";

/**
 * API and keys (board A3). Create a key with a name, its access (read only, or
 * read and write) and when it expires; the secret is shown once in a dialog.
 * Rename, rotate (confirm, then the new secret) and revoke your own keys. An
 * org admin sees every key in the organization, with its owner and their role,
 * and can revoke any of them. An example request and the developer links.
 *
 * A key whose secret never reached this page doesn't stay live: the server
 * action revokes it when no secret came back, and if the action's answer
 * itself is lost, this page finds the key it made and revokes it.
 */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { Chip, Content, KV, Loading, Panel, Sheet, Failed } from "../ui";
import { R } from "../routes";
import { AccountFrame, AccountHead, Confirm, CopyButton } from "./frame";
import * as api from "./api";
import { mintKey } from "./actions";
import type { MintOp } from "./key-mint";
import {
  dateLabel,
  keyAccessLabel,
  keyExpiryLabel,
  keyStatus,
  KEY_EXPIRY_CHOICES,
  KEY_EXPIRY_DEFAULT,
  roleName,
  scopeChoices,
  scopeName,
  type KeyExpiryDays,
  type KeyScopeName,
} from "./derive";

type Ask = { kind: "rotate" | "revoke"; id: number };
type Row = api.ApiKey & Partial<Pick<api.OrgApiKey, "owner_email" | "owner_role" | "yours">>;
type Reveal = { secret: string; lead: string; facts: string; back: HTMLElement | null };
/** What a create or rotate did: whether anything changed, and what to say. */
type Outcome = { changed: boolean; error: string | null };

export function ApiScreen({ apiOrigin, docsEnabled }: { apiOrigin: string | null; docsEnabled: boolean }) {
  const { user } = useAuth();
  const [org, setOrg] = React.useState<{ name: string; role: api.OrgSummary["org_role"] } | null>(null);
  const [orgLoaded, setOrgLoaded] = React.useState(false);
  const [keys, setKeys] = React.useState<Row[] | null>(null);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const [name, setName] = React.useState("");
  const [scope, setScope] = React.useState<KeyScopeName>("read");
  const [expiry, setExpiry] = React.useState<KeyExpiryDays>(KEY_EXPIRY_DEFAULT);
  const [creating, setCreating] = React.useState(false);
  const [pageErr, setPageErr] = React.useState<string | null>(null);
  const [ask, setAsk] = React.useState<Ask | null>(null);
  const [askErr, setAskErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [renaming, setRenaming] = React.useState<{ id: number; value: string; err: string | null; busy: boolean } | null>(null);
  const [reveal, setReveal] = React.useState<Reveal | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const isAdmin = org?.role === "admin";
  const keysRef = React.useRef<Row[] | null>(null);
  keysRef.current = keys;

  const load = React.useCallback(async (admin: boolean): Promise<Row[] | null> => {
    setLoadErr(null);
    try {
      const rows: Row[] = admin ? (await api.getOrgKeys()).keys : await api.getKeys();
      setKeys(rows);
      return rows;
    } catch (e) {
      setLoadErr(api.errText(e, "Keys didn’t load."));
      return null;
    }
  }, []);

  React.useEffect(() => {
    api.getOrgs().then(
      (o) => {
        const a = o.organizations.find((x) => x.org_id === o.active_org_id);
        setOrg(a ? { name: a.name, role: a.org_role } : null);
        setOrgLoaded(true);
        void load(a?.org_role === "admin");
      },
      () => {
        setOrgLoaded(true);
        void load(false);
      },
    );
  }, [load]);

  React.useEffect(() => {
    // A viewer's keys are read only: never leave "Read and write" picked.
    if (org?.role === "viewer") setScope("read");
  }, [org?.role]);

  React.useEffect(() => {
    if (!notice) return;
    const t = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(t);
  }, [notice]);

  const reload = React.useCallback(() => load(isAdmin), [load, isAdmin]);

  /**
   * The action's answer never came back. If the request reached ScaleCAD it
   * may have made a key nobody received: find it (a key of mine that wasn't
   * listed before, with this name) and revoke it, then say what happened.
   */
  async function recoverLost(before: Set<number>, keyName: string, rotatedId: number | null): Promise<Outcome> {
    let mine: api.ApiKey[] = [];
    try {
      mine = await api.getKeys();
    } catch {
      return { changed: false, error: "Couldn’t reach ScaleCAD to check whether a key was made. Reload this page and revoke any key you didn’t receive." };
    }
    const unseen = mine.filter((k) => !before.has(k.id) && !k.revoked_at && k.name === keyName);
    const failed: string[] = [];
    for (const k of unseen) {
      try {
        await api.revokeKey(k.id);
      } catch {
        failed.push(`cv_live_${k.prefix}_…`);
      }
    }
    const oldGone = rotatedId !== null && mine.some((k) => k.id === rotatedId && !!k.revoked_at);
    await reload();
    if (failed.length) return { changed: true, error: `The connection dropped before the new key arrived, and revoking it failed. Revoke ${failed.join(", ")} below.` };
    if (unseen.length) {
      return {
        changed: true,
        error: rotatedId !== null
          ? "The connection dropped before the new key arrived, so ScaleCAD revoked it. The old key was already revoked: create a new key."
          : "The connection dropped before the key arrived, so ScaleCAD revoked it. Create another.",
      };
    }
    if (oldGone) return { changed: true, error: "The connection dropped. The old key is revoked and no new key is live: create a new key." };
    return { changed: false, error: "Couldn’t reach ScaleCAD. Nothing changed." };
  }

  async function mint(op: MintOp, keyName: string, lead: string, back: HTMLElement | null): Promise<Outcome> {
    const before = new Set((keysRef.current ?? []).map((k) => k.id));
    let r: Awaited<ReturnType<typeof mintKey>>;
    try {
      r = await mintKey(op);
    } catch {
      return recoverLost(before, keyName, op.kind === "rotate" ? op.id : null);
    }
    if (!r.ok) {
      if (r.status === 503 && !r.made) return recoverLost(before, keyName, op.kind === "rotate" ? op.id : null);
      if (r.made) await reload();
      return { changed: !!r.made, error: r.error };
    }
    await reload();
    const k = r.key;
    const facts = [k.effectiveScope === "read" ? "Read only" : "Read and write", k.expiresAt ? `expires ${dateLabel(k.expiresAt)}` : "never expires"].join(", ");
    setReveal({ secret: k.secret, lead, facts, back });
    return { changed: true, error: null };
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (creating) return;
    setCreating(true);
    setPageErr(null);
    const back = (e.nativeEvent as SubmitEvent).submitter as HTMLElement | null;
    const keyName = name.trim().slice(0, 80) || "Default";
    const out = await mint({ kind: "create", name: keyName, scope, expiresInDays: expiry }, keyName, "Copy it now.", back);
    setCreating(false);
    if (out.error) setPageErr(out.error);
    else setName("");
  }

  async function confirmAsk() {
    if (!ask || busy) return;
    const key = keys?.find((k) => k.id === ask.id);
    setBusy(true);
    setAskErr(null);
    setPageErr(null);
    try {
      if (ask.kind === "rotate") {
        const back = document.getElementById("a-key-name");
        const out = await mint({ kind: "rotate", id: ask.id }, key?.name ?? "Default", `New key for ${key?.name ?? "this key"}. Copy it now.`, back);
        if (out.changed) {
          // The old key is revoked now: this confirm no longer has a key to act on.
          setAsk(null);
          if (out.error) setPageErr(out.error);
        } else if (out.error) {
          setAskErr(out.error);
        }
      } else {
        await api.revokeKey(ask.id);
        setAsk(null);
        const owner = key && !key.yours && key.owner_email ? ` (${key.owner_email})` : "";
        setNotice(`${key?.name ?? "Key"}${owner} revoked.`);
        await reload();
      }
    } catch (e) {
      setAskErr(api.errText(e, "Nothing changed. Try again."));
    } finally {
      setBusy(false);
    }
  }

  async function saveName() {
    if (!renaming) return;
    const value = renaming.value.trim().slice(0, 80) || "Default";
    setRenaming({ ...renaming, busy: true, err: null });
    try {
      await api.renameKey(renaming.id, value);
      setRenaming(null);
      setNotice(`Renamed to ${value}.`);
      await reload();
    } catch (e) {
      setRenaming((r) => (r ? { ...r, busy: false, err: api.errText(e, "Not renamed. Try again.") } : r));
    }
  }

  const active = (keys ?? []).filter((k) => keyStatus(k).label === "Active");
  const choices = scopeChoices(org?.role);
  const viewer = org?.role === "viewer";
  const cols = "minmax(0,1fr) 148px 108px 108px 88px 84px 150px";
  const orgName = org?.name ?? "this organization";
  return (
    <AccountFrame label="API and keys">
      <AccountHead
        title="API and keys"
        meta={[
          <span key="k">{isAdmin ? "Keys in org" : "Keys"} <b className="num">{keys ? keys.length : "—"}</b></span>,
          <span key="a">Active <b className="num">{keys ? active.length : "—"}</b></span>,
          <span key="u">Acts as <b>{user?.email ?? "you"}</b></span>,
          <span key="h">Header <b className="a-mono" style={{ fontWeight: 500 }}>Authorization: Bearer</b></span>,
        ]}
      />
      <Content>
        <Panel title={isAdmin ? `Keys in ${orgName}` : "Your keys"} note={isAdmin ? "Every key in the organization" : "Shown once at creation"}>
          <form className="a-frow" style={{ gridTemplateColumns: "minmax(0,1fr) 150px 140px auto" }} onSubmit={create} aria-describedby="a-kn-h">
            <label className="field">
              Key name
              <input id="a-key-name" type="text" placeholder="ERP connector" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              Access
              <select value={scope} onChange={(e) => setScope(e.target.value === "read_write" ? "read_write" : "read")} aria-describedby="a-ks-h">
                {choices.map((c) => (
                  <option key={c.value} value={c.value} disabled={c.disabled}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Expires
              <select value={expiry === null ? "never" : String(expiry)} onChange={(e) => setExpiry(e.target.value === "never" ? null : (Number(e.target.value) as KeyExpiryDays))}>
                {KEY_EXPIRY_CHOICES.map((c) => (
                  <option key={c.label} value={c.value === null ? "never" : String(c.value)}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn ink" type="submit" disabled={creating || !orgLoaded} aria-busy={creating}>
              {creating ? "Creating…" : "Create key"}
            </button>
          </form>
          <p className="a-fh" id="a-kn-h" style={{ margin: "-6px 16px 4px" }}>
            Name it after the tool that uses it. Blank names save as Default.
          </p>
          <p className="a-fh" id="a-ks-h" style={{ margin: "0 16px 10px" }}>
            {viewer
              ? "Viewers’ keys are read only: they open parts and records but can’t change them or check new parts."
              : "Read only: opens parts and records. Read and write: also checks and changes parts, as you can in the app."}
          </p>
          {pageErr ? (
            <p className="a-err" role="alert" style={{ margin: "-4px 16px 10px" }}>
              {pageErr}
            </p>
          ) : null}
          {loadErr ? (
            <Failed title="Couldn’t load the keys." detail={loadErr} onRetry={() => void reload()} />
          ) : !keys ? (
            <Loading rows={2} label="Loading keys" />
          ) : keys.length === 0 ? (
            <div className="empty" style={{ padding: "18px 24px", borderTop: "1px solid var(--rule)" }}>
              <b>No API keys</b>
              <span>One key per tool makes rotating easy.</span>
            </div>
          ) : (
            <div role="table" aria-label="Keys">
              <div className="a-tr th" role="row" style={{ gridTemplateColumns: cols }}>
                <span role="columnheader">{isAdmin ? "Name and owner" : "Name"}</span>
                <span role="columnheader">Key</span>
                <span role="columnheader">Access</span>
                <span role="columnheader">Expires</span>
                <span role="columnheader">Last used</span>
                <span role="columnheader">Status</span>
                <span role="columnheader">
                  <span className="sr">Actions</span>
                </span>
              </div>
              {keys.map((k) => {
                const status = keyStatus(k);
                const revoked = !!k.revoked_at;
                const own = !isAdmin || !!k.yours;
                const editing = renaming?.id === k.id ? renaming : null;
                const asking = ask?.id === k.id ? ask : null;
                return (
                  <React.Fragment key={k.id}>
                    <div className="a-tr" role="row" style={{ gridTemplateColumns: cols }} data-key-row={k.id}>
                      <span role="cell">
                        {editing ? (
                          <span style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                            <label style={{ flex: "1 1 120px", minWidth: 0 }}>
                              <span className="sr">Key name</span>
                              <input
                                type="text"
                                autoFocus
                                maxLength={80}
                                value={editing.value}
                                style={{ width: "100%" }}
                                onChange={(e) => setRenaming({ ...editing, value: e.target.value })}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") {
                                    e.preventDefault();
                                    void saveName();
                                  }
                                  if (e.key === "Escape") setRenaming(null);
                                }}
                              />
                            </label>
                            <button className="btn ink sm" type="button" onClick={() => void saveName()} disabled={editing.busy}>
                              {editing.busy ? "Saving…" : "Save"}
                            </button>
                            <button className="btn sm" type="button" onClick={() => setRenaming(null)} disabled={editing.busy}>
                              Cancel
                            </button>
                            {editing.err ? (
                              <span className="a-err" role="alert" style={{ flexBasis: "100%" }}>
                                {editing.err}
                              </span>
                            ) : null}
                          </span>
                        ) : (
                          <span style={{ display: "block", minWidth: 0 }}>
                            <b className="a-clip" title={k.name} style={{ display: "block" }}>
                              {k.name}
                            </b>
                            {isAdmin ? (
                              <small className="a-clip" title={k.owner_email ?? undefined}>
                                {k.yours ? "You" : k.owner_email ?? "Unknown account"} · {k.owner_role ? roleName(k.owner_role) : "Left the organization"}
                              </small>
                            ) : null}
                            <small>Created {dateLabel(k.created_at)}</small>
                            {revoked || !own ? null : (
                              <button className="a-link" type="button" aria-label={`Rename ${k.name}`} onClick={() => setRenaming({ id: k.id, value: k.name, err: null, busy: false })}>
                                Rename
                              </button>
                            )}
                          </span>
                        )}
                      </span>
                      <span role="cell" className="a-mono a-clip" data-l="Key">
                        cv_live_{k.prefix}_…
                      </span>
                      <span role="cell" data-l="Access">
                        {keyAccessLabel(k)}
                      </span>
                      <span role="cell" data-l="Expires">
                        {keyExpiryLabel(k)}
                      </span>
                      <span role="cell" data-l="Last used">
                        {k.last_used_at ? dateLabel(k.last_used_at) : "Never"}
                      </span>
                      <span role="cell" data-l="Status">
                        <Chip tone={status.tone}>{status.label}</Chip>
                      </span>
                      <span role="cell" className="a-acts">
                        {revoked ? (
                          <span className="a-fh">Revoked {dateLabel(k.revoked_at)}</span>
                        ) : (
                          <>
                            {own ? (
                              <button className="btn sm" type="button" aria-label={`Rotate ${k.name}`} disabled={!!asking || busy} onClick={() => { setAsk({ kind: "rotate", id: k.id }); setAskErr(null); }}>
                                Rotate
                              </button>
                            ) : null}
                            <button className="btn sm" type="button" aria-label={`Revoke ${k.name}`} disabled={!!asking || busy} onClick={() => { setAsk({ kind: "revoke", id: k.id }); setAskErr(null); }}>
                              Revoke
                            </button>
                          </>
                        )}
                      </span>
                    </div>
                    {asking?.kind === "rotate" && !revoked ? (
                      <Confirm label="Rotate key" question={`Rotate ${k.name}?`} detail="The current key stops working now. Tools using it need the new key." confirmLabel="Rotate key" busy={busy} error={askErr} onConfirm={() => void confirmAsk()} onCancel={() => setAsk(null)} />
                    ) : null}
                    {asking?.kind === "revoke" && !revoked ? (
                      <Confirm
                        label="Revoke key"
                        question={own ? `Revoke ${k.name}?` : `Revoke ${k.owner_email ?? "this person"}’s key ${k.name}?`}
                        detail={own ? "It stops working now and can’t be turned back on." : "It stops working now and can’t be turned back on. They can make a new key; the revoke is recorded in Activity."}
                        confirmLabel="Revoke key"
                        danger
                        busy={busy}
                        error={askErr}
                        onConfirm={() => void confirmAsk()}
                        onCancel={() => setAsk(null)}
                      />
                    ) : null}
                  </React.Fragment>
                );
              })}
              {keys.some((k) => k.revoked_at) ? (
                <p className="a-fh" style={{ margin: "6px 16px 0" }}>
                  Revoked keys stay listed.
                </p>
              ) : null}
            </div>
          )}
          <div aria-live="polite">
            {notice ? (
              <div className="toast swap a-toast" role="status" style={{ marginTop: 10 }}>
                <span>{notice}</span>
              </div>
            ) : null}
          </div>
          <div style={{ height: 6 }} />
        </Panel>
        <Panel
          title="Example request"
          actions={
            <span style={{ display: "flex", gap: 12 }}>
              <Link href="/api-reference">API reference</Link>
              {docsEnabled ? <a href="/scalar">Open API console</a> : null}
            </span>
          }
        >
          <pre className="a-pre">{`curl ${apiOrigin ?? "https://<your ScaleCAD API address>"}/api/v1/validate \\
  -H "Authorization: Bearer cv_live_…" \\
  -F file=@bracket.step`}</pre>
          <p style={{ margin: 0, padding: "0 16px 14px", color: "var(--ink2)", fontSize: 13.5 }}>
            {apiOrigin ? "Same results as the app. " : "This deployment hasn’t published a public API address; ask your ScaleCAD contact for it. "}
            Costs: <span className="a-mono">/api/v1/validate/cost</span>. A check needs a read-and-write key.
          </p>
        </Panel>
      </Content>
      <Sheet label="How keys work" style={{ bottom: 20 }}>
        <div className="top">
          <h2 className="stitle">Key behavior</h2>
          <p className="smeta a-wrap">{org ? (isAdmin ? `Every key in ${org.name}` : `Your keys in ${org.name}`) : "Your keys"}</p>
        </div>
        <div className="scroll">
          <KV
            rows={[
              ["Acts as", <span key="a" className="a-wrap">{[user?.email, org ? roleName(org.role) : null].filter(Boolean).join(", ")}</span>],
              ["Access", viewer ? scopeName("read") : "Read only or read and write, per key"],
              ["Expires", "In 30, 90 or 365 days, or never"],
              ["Shown", "Once, after create or rotate"],
              ["Stored", "Fingerprint only"],
            ]}
          />
          <div className="note">
            <b>What a key can do</b>
            <span>
              What you can do in {orgName}, and no more. A read-only key makes GET requests only; anything else gets 403. A viewer’s key is always read only. An expired key gets 401.
            </span>
          </div>
          <div className="note">
            <b>Who governs keys</b>
            <span>
              {isAdmin
                ? `You see every key in ${orgName} and can revoke any of them. Only a key’s owner can rotate or rename it.`
                : `Org admins in ${orgName} see every key and can revoke yours. A key stops working when its owner leaves the organization.`}
            </span>
          </div>
          <div className="note">
            <b>Metering</b>
            <span>Same as the app. A part’s analysis, cost and preview count as 1 check, and re-running them on the same file never counts again.</span>
          </div>
          <div className="note">
            <b>Audit log</b>
            <span>Create, rotate, revoke, rename and refused writes are recorded in Activity.</span>
          </div>
          <div style={{ padding: "8px 12px" }}>
            <Link className="btn sm" href={R.activity}>
              Activity
            </Link>
          </div>
        </div>
      </Sheet>
      {reveal ? (
        <RevealDialog
          secret={reveal.secret}
          lead={reveal.lead}
          facts={reveal.facts}
          onClose={() => {
            const back = reveal.back;
            setReveal(null);
            window.setTimeout(() => back?.focus(), 0);
          }}
        />
      ) : null}
    </AccountFrame>
  );
}

function RevealDialog({ secret, lead, facts, onClose }: { secret: string; lead: string; facts: string; onClose: () => void }) {
  const [ticked, setTicked] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, []);
  return (
    <>
      <button className="a-scrim" type="button" tabIndex={-1} aria-label="Close dialog" onClick={() => (ticked ? onClose() : undefined)} />
      <div
        ref={ref}
        className="a-dlg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="a-rv-t"
        aria-describedby="a-rv-d"
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            if (ticked) onClose();
          }
          if (e.key === "Tab") {
            // Keep focus inside the dialog.
            const els = Array.from(ref.current?.querySelectorAll<HTMLElement>("button:not([disabled]),input") ?? []);
            if (!els.length) return;
            const first = els[0];
            const last = els[els.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first.focus();
            }
          }
        }}
      >
        <h2 id="a-rv-t">Save your API key</h2>
        <p id="a-rv-d">
          {lead} It won’t be shown again. {facts}.
        </p>
        <code>{secret}</code>
        <span className="a-bx">
          <CopyButton value={secret} ariaLabel="Copy API key" />
          <span className="a-fh">Only a fingerprint is stored.</span>
        </span>
        <label className="a-chk">
          <input type="checkbox" checked={ticked} onChange={(e) => setTicked(e.target.checked)} aria-describedby="a-rv-h" />
          I’ve saved it somewhere safe
        </label>
        <span className="a-bx">
          <button className="btn ink" type="button" aria-disabled={!ticked} style={!ticked ? { opacity: 0.45, cursor: "default" } : undefined} onClick={() => (ticked ? onClose() : undefined)}>
            Done
          </button>
          <span className="a-fh" id="a-rv-h">
            {ticked ? "Esc also closes." : "Tick the box to close."}
          </span>
        </span>
      </div>
    </>
  );
}
