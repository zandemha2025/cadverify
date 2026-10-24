"use client";

/**
 * Share links (Account): every public link you made (to a check, a part for a
 * supplier, or an RFQ package), whether it still works, when it ends, what it
 * shows, and Switch off. Admins also see everyone's links in the organization
 * and can switch any of them off. A part's link shows your cost and the CAD
 * file only when its maker included them (backend supplier_links.py).
 */
import * as React from "react";
import Link from "next/link";
import { Chip, ConfirmButton, Content, Loading, Panel } from "../ui";
import { R } from "../routes";
import { AccountFrame, AccountHead, Banner } from "../account/frame";
import { listLinks, switchOffLink, type ShareLinkList, type ShareLinkRow } from "./api";
import { day, endDateAddedNote, linkEndText, statusLabel } from "./words";
import "./data.css";

function absolute(url: string): string {
  return typeof window !== "undefined" && url.startsWith("/") ? window.location.origin + url : url;
}

export function LinksScreen() {
  const [scope, setScope] = React.useState<"mine" | "org">("mine");
  const [data, setData] = React.useState<ShareLinkList | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [rowErr, setRowErr] = React.useState<string | null>(null);
  const [toast, setToast] = React.useState<string | null>(null);

  const load = React.useCallback((s: "mine" | "org") => {
    setErr(null);
    listLinks(s).then(setData, (e) => setErr(e instanceof Error ? e.message : "Your links didn't load."));
  }, []);
  React.useEffect(() => load(scope), [scope, load]);

  const on = data?.links.filter((l) => l.status === "active").length ?? 0;
  const off = async (l: ShareLinkRow) => {
    setRowErr(null);
    try {
      await switchOffLink(l.kind, l.id);
      setToast(`Switched off. Anyone who opens the link sees that it was switched off.`);
      load(scope);
    } catch (e) {
      setRowErr(e instanceof Error ? e.message : "The link is still on.");
    }
  };
  const copy = async (l: ShareLinkRow) => {
    try {
      await navigator.clipboard.writeText(absolute(l.url));
      setToast("Link copied");
    } catch {
      setToast("Copy didn't work. Open the link and copy it from the address bar.");
    }
  };
  const legacy = data?.links.find((l) => l.end_date_added && l.status === "active") ?? null;

  return (
    <AccountFrame label="Share links">
      <AccountHead
        title="Share links"
        meta={[
          <span key="n">
            Working <b className="num">{data ? on : "—"}</b>
          </span>,
          <span key="d">
            New links end after <b>{data?.default_days ?? 7} days</b> unless you pick another length
          </span>,
        ]}
      />
      <Content>
        {legacy ? (
          <Banner tone="plain" title="Links made before end dates were added now end." alert={false}>
            They used to have no end date. Each was given one 30 days after the change; the date is on each link below. Make a new link if you need one for longer.
          </Banner>
        ) : null}
        <Panel
          title={scope === "mine" ? "Links you made" : "Everyone's links"}
          note={data ? String(data.links.length) : undefined}
          actions={
            data?.is_admin ? (
              <span className="dc-seg" role="group" aria-label="Whose links">
                <button type="button" aria-pressed={scope === "mine"} onClick={() => setScope("mine")}>
                  Mine
                </button>
                <button type="button" aria-pressed={scope === "org"} onClick={() => setScope("org")}>
                  Everyone&apos;s
                </button>
              </span>
            ) : null
          }
        >
          {err ? (
            <div className="dc-pad">
              <p className="dc-err" role="alert">
                {err}
              </p>
              <button className="btn sm" type="button" onClick={() => load(scope)}>
                Try again
              </button>
            </div>
          ) : !data ? (
            <Loading rows={3} label="Loading links" />
          ) : data.links.length === 0 ? (
            <div className="empty" style={{ padding: "18px 24px" }}>
              <b>No share links</b>
              <span>Make one from a part, a record or an RFQ package: Share, then pick what the supplier sees and how long it lasts.</span>
            </div>
          ) : (
            <div className="dc-links" role="table" aria-label="Share links">
              <div className="dc-row th" role="row">
                <span role="columnheader">Shared</span>
                <span role="columnheader">Status</span>
                <span role="columnheader">Ends</span>
                <span role="columnheader">
                  <span className="sr">Actions</span>
                </span>
              </div>
              {data.links.map((l) => (
                <div className="dc-row" role="row" key={`${l.kind}-${l.id}`}>
                  <span role="cell" style={{ minWidth: 0 }}>
                    <b title={l.name}>
                      <Link href={l.kind === "package" ? R.pkg(l.id) : l.part_key ? R.part(l.part_key) : R.record(l.id)} style={{ color: "inherit", textDecoration: "none" }}>
                        {l.name}
                      </Link>
                    </b>
                    <small>
                      {l.kind === "check" ? "Check" : l.kind === "package" ? "RFQ package" : "Part, for a supplier"}
                      {l.kind === "record" ? (l.shows?.include_cost ? " · with your cost" : " · no cost") : ""}
                      {l.kind === "record" && l.shows?.include_cad ? " · CAD" : ""}
                      {l.created_at ? ` · made ${day(l.created_at)}` : ""}
                      {scope === "org" && l.made_by ? ` · by ${l.made_by}` : ""}
                    </small>
                  </span>
                  <span role="cell">
                    <Chip tone={l.status === "active" ? "ok" : "unk"}>{statusLabel(l.status)}</Chip>
                  </span>
                  <span role="cell" className="num">
                    {linkEndText(l.status, l.expires_at, l.ended_at)}
                    {l.end_date_added && l.status === "active" ? <small>{endDateAddedNote(l.expires_at)}</small> : null}
                  </span>
                  <span role="cell" className="acts">
                    {l.status === "active" ? (
                      <>
                        <button className="btn sm" type="button" onClick={() => void copy(l)}>
                          Copy
                        </button>
                        <a className="btn sm" href={l.url} target="_blank" rel="noopener noreferrer">
                          Open
                        </a>
                        {l.can_switch_off ? (
                          <ConfirmButton label="Switch off" question="Switch off this link now?" confirmLabel="Switch off" onConfirm={() => off(l)} />
                        ) : null}
                      </>
                    ) : null}
                  </span>
                </div>
              ))}
            </div>
          )}
          {rowErr ? (
            <p className="dc-err" role="alert" style={{ margin: "4px 16px 12px" }}>
              {rowErr}
            </p>
          ) : null}
          <p className="a-fh" style={{ margin: "8px 16px 12px" }}>
            Anyone with a working link sees the file name, verdicts, findings and geometry figures (a cost record link also shows its prices). Never the file, the 3D model, who uploaded it or the file&apos;s fingerprint.
            {data?.is_admin ? " As an admin you can switch off anyone's link." : " The person who made a link, or an admin, can switch it off."}
          </p>
        </Panel>
        <div aria-live="polite">
          {toast ? (
            <div className="toast swap a-toast" role="status">
              <span>{toast}</span>
            </div>
          ) : null}
        </div>
      </Content>
    </AccountFrame>
  );
}
