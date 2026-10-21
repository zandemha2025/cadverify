"use client";

/**
 * Delete organization (admins only; the server checks it too). Says what goes,
 * that it can't be undone, that members are signed out and what stays
 * (accounts and billing records). The name must be typed exactly.
 */
import * as React from "react";
import { Panel } from "../ui";
import { forget } from "../home/data";
import { forgetLoaded } from "../records/api";
import { clearCachedMeshes } from "../part/mesh-cache";
import { deleteOrg, orgDeletionPreview } from "./api";
import { useDialogFocus, useReceipt } from "./delete-part";
import { nameMatches, orgRemovalLines, receiptLine, type OrgPreview, type Receipt } from "./words";
import "./data.css";

export function DeleteOrgPanel({ orgName }: { orgName: string }) {
  const [open, setOpen] = React.useState(false);
  const [preview, setPreview] = React.useState<OrgPreview | null>(null);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const [typed, setTyped] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [done, setDone] = React.useState<Receipt | null>(null);
  const receipt = useReceipt(done);
  const inputId = React.useId();

  React.useEffect(() => {
    if (!open || preview) return;
    let live = true;
    orgDeletionPreview().then(
      (p) => live && setPreview(p),
      (e) => live && setLoadErr(e instanceof Error ? e.message : "What the organization holds didn't load."),
    );
    return () => {
      live = false;
    };
  }, [open, preview]);

  const name = preview?.name ?? orgName;
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await deleteOrg(typed);
      void clearCachedMeshes();
      forget("");
      forgetLoaded();
      setDone(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The organization wasn't deleted. Nothing was changed.");
    } finally {
      setBusy(false);
    }
  };

  if (receipt) return <OrgDeleted receipt={receipt} />;

  return (
    <>
    <Panel title="Delete organization">
      <div className="dc-pad">
        {!open ? (
          <>
            <p className="dc-p">
              Deletes {name} and everything in it, for every member: parts, their stored files, checks, records and settings. It can&apos;t be undone.
            </p>
            <div className="dc-acts">
              <button className="btn sm" type="button" onClick={() => setOpen(true)}>
                Delete organization…
              </button>
            </div>
          </>
        ) : loadErr ? (
          <p className="dc-err" role="alert">
            {loadErr}
          </p>
        ) : !preview ? (
          <p className="dc-p" role="status">
            Counting what {name} holds…
          </p>
        ) : (
          <>
            <p className="dc-p">Deletes now, for every member of {name}:</p>
            <ul className="dc-list">
              {orgRemovalLines(preview).map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
            <p className="dc-p">Members are signed out. Anyone left without an organization gets a new, empty one.</p>
            <p className="dc-warn">This can&apos;t be undone. Export records and download fixed copies you need first.</p>
            <details className="dc-kept" open>
              <summary>What stays</summary>
              <ul>
                {preview.kept.map((k) => (
                  <li key={k}>{k}</li>
                ))}
              </ul>
            </details>
            <label className="field dc-name" htmlFor={inputId}>
              Type the organization&apos;s name to confirm: {name}
              <input id={inputId} type="text" autoComplete="off" spellCheck={false} value={typed} onChange={(e) => setTyped(e.target.value)} />
            </label>
            {err ? (
              <p className="dc-err" role="alert">
                {err}
              </p>
            ) : null}
            <div className="dc-acts">
              <button className="btn sm ink" type="button" disabled={!nameMatches(typed, name) || busy} aria-busy={busy} onClick={() => void run()}>
                {busy ? "Deleting…" : "Delete organization"}
              </button>
              <button
                className="btn sm"
                type="button"
                disabled={busy}
                onClick={() => {
                  setOpen(false);
                  setTyped("");
                  setErr(null);
                }}
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </Panel>
    {/* Room below the last panel, so it scrolls clear of the floating corner controls. */}
    <div aria-hidden="true" style={{ height: 120, flexShrink: 0 }} />
    </>
  );
}

/** Over the page (which still shows the deleted organization until it reloads): the receipt and Continue. */
function OrgDeleted({ receipt }: { receipt: Receipt }) {
  const id = React.useId();
  const go = () => window.location.replace(new URL("/app", window.location.origin).toString());
  const { ref, onKeyDown } = useDialogFocus(go);
  return (
    <div className="dc-back">
      <div ref={ref} className="dc-dlg" role="dialog" aria-modal="true" aria-labelledby={id} onKeyDown={onKeyDown}>
        <h2 id={id}>Organization deleted</h2>
        <p className={receipt.status === "done" ? "dc-ok" : "dc-p"} role="status">
          {receiptLine(receipt)}
        </p>
        <p className="dc-p">
          Members were signed out. Your account and your other organizations are as they were; if this was your only organization you now have a new, empty one. Deletion ID{" "}
          <span className="mono">{receipt.id}</span>.
        </p>
        <div className="dc-acts">
          <button className="btn sm ink" type="button" onClick={go}>
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}
