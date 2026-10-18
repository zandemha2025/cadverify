"use client";

/**
 * API and keys (board A3): your keys in the active organization, create with a
 * name and a reveal-once dialog, rename inline, rotate (confirm, then the new
 * secret) and revoke (confirm; revoked keys stay listed). An example request
 * and the developer links. The secret is shown once and never stored here.
 */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { Chip, Content, KV, Loading, Panel, Sheet, Failed } from "../ui";
import { R } from "../routes";
import { AccountFrame, AccountHead, Confirm, CopyButton } from "./frame";
import * as api from "./api";
import { mintKey } from "./actions";
import { dateLabel, roleName } from "./derive";

const REVEAL_PATH = R.api;

/** Read the one-time secret the mint action left for this page, and delete it. */
function takeSecret(): string | null {
  const m = document.cookie.match(/(?:^|;\s*)cv_mint_once=([^;]+)/);
  document.cookie = `cv_mint_once=; Max-Age=0; path=${REVEAL_PATH}`;
  return m ? decodeURIComponent(m[1]) : null;
}

type Ask = { kind: "rotate" | "revoke"; id: number };

export function ApiScreen({ apiOrigin }: { apiOrigin: string }) {
  const { user } = useAuth();
  const [keys, setKeys] = React.useState<api.ApiKey[] | null>(null);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const [org, setOrg] = React.useState<{ name: string; role: string } | null>(null);
  const [name, setName] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [createErr, setCreateErr] = React.useState<string | null>(null);
  const [ask, setAsk] = React.useState<Ask | null>(null);
  const [askErr, setAskErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [renaming, setRenaming] = React.useState<{ id: number; value: string; err: string | null; busy: boolean } | null>(null);
  const [reveal, setReveal] = React.useState<{ secret: string; lead: string; back: HTMLElement | null } | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoadErr(null);
    try {
      setKeys(await api.getKeys());
    } catch (e) {
      setLoadErr(api.errText(e, "Keys didn’t load."));
    }
  }, []);
  React.useEffect(() => {
    void load();
    api.getOrgs().then(
      (o) => {
        const a = o.organizations.find((x) => x.org_id === o.active_org_id);
        setOrg(a ? { name: a.name, role: a.org_role } : null);
      },
      () => setOrg(null),
    );
  }, [load]);

  React.useEffect(() => {
    if (!notice) return;
    const t = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(t);
  }, [notice]);

  async function mint(op: Parameters<typeof mintKey>[0], lead: string, back: HTMLElement | null): Promise<string | null> {
    const r = await mintKey(op);
    if (!r.ok) return r.error;
    const secret = takeSecret();
    await load();
    if (!secret) return "The key was made but its secret didn’t arrive. Revoke it and create another.";
    setReveal({ secret, lead, back });
    return null;
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setCreateErr(null);
    const back = (e.nativeEvent as SubmitEvent).submitter as HTMLElement | null;
    const err = await mint({ kind: "create", name: name.trim() }, "Copy it now.", back);
    setCreating(false);
    if (err) setCreateErr(err);
    else setName("");
  }

  async function confirmAsk() {
    if (!ask) return;
    const key = keys?.find((k) => k.id === ask.id);
    setBusy(true);
    setAskErr(null);
    try {
      if (ask.kind === "rotate") {
        const back = document.getElementById("a-key-name");
        const err = await mint({ kind: "rotate", id: ask.id }, `New key for ${key?.name ?? "this key"}. Copy it now.`, back);
        if (err) {
          setAskErr(err);
          return;
        }
        setAsk(null);
      } else {
        await api.revokeKey(ask.id);
        setAsk(null);
        setNotice(`${key?.name ?? "Key"} revoked.`);
        await load();
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
      await load();
    } catch (e) {
      setRenaming((r) => (r ? { ...r, busy: false, err: api.errText(e, "Not renamed. Try again.") } : r));
    }
  }

  const active = (keys ?? []).filter((k) => !k.revoked_at);
  const cols = "minmax(0,1fr) 170px 96px 96px 84px 156px";
  return (
    <AccountFrame label="API and keys">
      <AccountHead
        title="API and keys"
        meta={[
          <span key="k">Keys <b className="num">{keys ? keys.length : "—"}</b></span>,
          <span key="a">Active <b className="num">{keys ? active.length : "—"}</b></span>,
          <span key="u">Acts as <b>{user?.email ?? "you"}</b></span>,
          <span key="h">Header <b className="a-mono" style={{ fontWeight: 500 }}>Authorization: Bearer</b></span>,
        ]}
      />
      <Content>
        <Panel title="Keys" note="Shown once at creation">
          <form className="a-frow" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }} onSubmit={create}>
            <label className="field">
              Key name
              <input id="a-key-name" type="text" placeholder="ERP connector" maxLength={80} aria-describedby="a-kn-h" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <button className="btn ink" type="submit" disabled={creating} aria-busy={creating}>
              {creating ? "Creating…" : "Create key"}
            </button>
          </form>
          <p className="a-fh" id="a-kn-h" style={{ margin: "-6px 16px 10px" }}>
            Name it after the tool that uses it. Blank names save as Default.
          </p>
          {createErr ? (
            <p className="a-err" role="alert" style={{ margin: "-4px 16px 10px" }}>
              {createErr}
            </p>
          ) : null}
          {loadErr ? (
            <Failed title="Couldn’t load your keys." detail={loadErr} onRetry={() => void load()} />
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
                <span role="columnheader">Name</span>
                <span role="columnheader">Key</span>
                <span role="columnheader">Created</span>
                <span role="columnheader">Last used</span>
                <span role="columnheader">Status</span>
                <span role="columnheader">
                  <span className="sr">Actions</span>
                </span>
              </div>
              {keys.map((k) => {
                const revoked = !!k.revoked_at;
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
                          <span style={{ display: "flex", alignItems: "center", minWidth: 0 }}>
                            <b className="a-clip" title={k.name}>
                              {k.name}
                            </b>
                            {revoked ? null : (
                              <button className="btn sm a-mini" type="button" aria-label={`Rename ${k.name}`} onClick={() => setRenaming({ id: k.id, value: k.name, err: null, busy: false })}>
                                Rename
                              </button>
                            )}
                          </span>
                        )}
                      </span>
                      <span role="cell" className="a-mono a-clip" data-l="Key">
                        cv_live_{k.prefix}_…
                      </span>
                      <span role="cell" data-l="Created">
                        {dateLabel(k.created_at)}
                      </span>
                      <span role="cell" data-l="Last used">
                        {k.last_used_at ? dateLabel(k.last_used_at) : "Never"}
                      </span>
                      <span role="cell" data-l="Status">
                        <Chip tone={revoked ? "unk" : "ok"}>{revoked ? "Revoked" : "Active"}</Chip>
                      </span>
                      <span role="cell" className="a-acts">
                        {revoked ? (
                          <span className="a-fh">Revoked {dateLabel(k.revoked_at)}</span>
                        ) : (
                          <>
                            <button className="btn sm" type="button" aria-label={`Rotate ${k.name}`} disabled={!!asking} onClick={() => { setAsk({ kind: "rotate", id: k.id }); setAskErr(null); }}>
                              Rotate
                            </button>
                            <button className="btn sm" type="button" aria-label={`Revoke ${k.name}`} disabled={!!asking} onClick={() => { setAsk({ kind: "revoke", id: k.id }); setAskErr(null); }}>
                              Revoke
                            </button>
                          </>
                        )}
                      </span>
                    </div>
                    {asking?.kind === "rotate" ? (
                      <Confirm label="Rotate key" question={`Rotate ${k.name}?`} detail="The current key stops working now. Tools using it need the new key." confirmLabel="Rotate key" busy={busy} error={askErr} onConfirm={() => void confirmAsk()} onCancel={() => setAsk(null)} />
                    ) : null}
                    {asking?.kind === "revoke" ? (
                      <Confirm label="Revoke key" question={`Revoke ${k.name}?`} detail="It stops working now and can’t be turned back on." confirmLabel="Revoke key" danger busy={busy} error={askErr} onConfirm={() => void confirmAsk()} onCancel={() => setAsk(null)} />
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
              <a href="/scalar">Open API console</a>
            </span>
          }
        >
          <pre className="a-pre">{`curl ${apiOrigin}/api/v1/validate \\
  -H "Authorization: Bearer cv_live_…" \\
  -F file=@bracket.step`}</pre>
          <p style={{ margin: 0, padding: "0 16px 14px", color: "var(--ink2)", fontSize: 13.5 }}>
            Same results as the app. Costs: <span className="a-mono">/api/v1/validate/cost</span>.
          </p>
        </Panel>
      </Content>
      <Sheet label="How keys work" style={{ bottom: 20 }}>
        <div className="top">
          <h2 className="stitle">Key behavior</h2>
          <p className="smeta a-wrap">{org ? `Your keys in ${org.name}` : "Your keys"}</p>
        </div>
        <div className="scroll">
          <KV
            rows={[
              ["Acts as", <span key="a" className="a-wrap">{[user?.email, org ? roleName(org.role) : null].filter(Boolean).join(", ")}</span>],
              ["Header", <span key="h" className="a-mono" style={{ fontWeight: 500 }}>Authorization: Bearer</span>],
              ["Shown", "Once, after create or rotate"],
              ["Stored", "Fingerprint only"],
            ]}
          />
          <div className="note">
            <b>Metering</b>
            <span>Same as the app. A part’s analysis, cost and preview within an hour count as 1 check.</span>
          </div>
          <div className="note">
            <b>Audit log</b>
            <span>Create, rotate, revoke and rename are recorded in Activity.</span>
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

function RevealDialog({ secret, lead, onClose }: { secret: string; lead: string; onClose: () => void }) {
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
        <p id="a-rv-d">{lead} It won’t be shown again.</p>
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
