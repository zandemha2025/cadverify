"use client";

/**
 * Delete account (Account > Security). Says what goes, what blocks it (being
 * the only admin of an organization others are in), what stays (billing
 * records, the email fingerprint behind free checks), and that it can't be
 * undone. The account's email must be typed. The server ends every session
 * at once; this browser's own cookie is cleared before the receipt shows.
 */
import * as React from "react";
import Link from "next/link";
import posthog from "posthog-js";
import { Panel } from "../ui";
import { R } from "../routes";
import { forget } from "../home/data";
import { forgetLoaded } from "../records/api";
import { clearCachedMeshes } from "../part/mesh-cache";
import { accountDeletionPreview, deleteAccount } from "./api";
import { useDialogFocus } from "./delete-part";
import { accountRemovalLines, emailMatches, receiptLine, type AccountPreview, type Receipt } from "./words";
import "./data.css";

export function DeleteAccountPanel({ email }: { email: string | null }) {
  const [open, setOpen] = React.useState(false);
  const [preview, setPreview] = React.useState<AccountPreview | null>(null);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const [typed, setTyped] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [done, setDone] = React.useState<Receipt | null>(null);
  const inputId = React.useId();

  React.useEffect(() => {
    if (!open || preview) return;
    let live = true;
    accountDeletionPreview().then(
      (p) => live && setPreview(p),
      (e) => live && setLoadErr(e instanceof Error ? e.message : "What your account holds didn't load."),
    );
    return () => {
      live = false;
    };
  }, [open, preview]);

  const address = preview?.email ?? email ?? "";
  const close = () => {
    setOpen(false);
    setTyped("");
    setErr(null);
    setLoadErr(null);
  };
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await deleteAccount(typed);
      // The server already refuses this browser's cookie; clear it here too.
      await fetch("/api/auth/logout", { method: "POST" }).then((x) => x.arrayBuffer()).catch(() => undefined);
      if (posthog.__loaded) posthog.reset();
      void clearCachedMeshes();
      forget("");
      forgetLoaded();
      setDone(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Your account wasn't deleted. Nothing was changed.");
    } finally {
      setBusy(false);
    }
  };

  if (done) return <AccountDeleted receipt={done} />;

  return (
    <>
      <Panel title="Delete account">
        <div className="dc-pad">
          {!open ? (
            <>
              <p className="dc-p">
                Deletes your sign-in account for good. Organizations only you are in are deleted with it; you leave the others, and what you made there stays with them. It can&apos;t be undone.
              </p>
              <div className="dc-acts">
                <button className="btn sm" type="button" onClick={() => setOpen(true)}>
                  Delete account…
                </button>
              </div>
            </>
          ) : loadErr ? (
            <>
              <p className="dc-err" role="alert">
                {loadErr}
              </p>
              <div className="dc-acts">
                <button className="btn sm" type="button" onClick={close}>
                  Cancel
                </button>
              </div>
            </>
          ) : !preview ? (
            <p className="dc-p" role="status">
              Reading what your account holds…
            </p>
          ) : !preview.can_delete ? (
            <>
              <p className="dc-p">Your account can&apos;t be deleted yet:</p>
              {preview.blockers.map((b) => (
                <p key={b.org_id} className="dc-warn" role="alert">
                  {b.message}
                </p>
              ))}
              <div className="dc-acts">
                <Link className="btn sm ink" href={R.org}>
                  Organization
                </Link>
                <button className="btn sm" type="button" onClick={close}>
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="dc-p">Deletes now:</p>
              <ul className="dc-list">
                {accountRemovalLines(preview).map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
              <p className="dc-warn">This can&apos;t be undone. Export records and download files you need first. Signing up again with this email starts a new, empty account with the free checks this one had left.</p>
              <details className="dc-kept" open>
                <summary>What stays</summary>
                <ul>
                  {preview.kept.map((k) => (
                    <li key={k}>{k}</li>
                  ))}
                </ul>
              </details>
              <label className="field dc-name" htmlFor={inputId}>
                Type your account&apos;s email to confirm: {address}
                <input
                  id={inputId}
                  type="email"
                  autoComplete="off"
                  spellCheck={false}
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                />
              </label>
              {err ? (
                <p className="dc-err" role="alert">
                  {err}
                </p>
              ) : null}
              <div className="dc-acts">
                <button className="btn sm ink" type="button" disabled={!emailMatches(typed, address) || busy} aria-busy={busy} onClick={() => void run()}>
                  {busy ? "Deleting…" : "Delete account"}
                </button>
                <button className="btn sm" type="button" disabled={busy} onClick={close}>
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

/** Over the page (signed out now): the receipt, and Continue to the public site. */
function AccountDeleted({ receipt }: { receipt: Receipt }) {
  const id = React.useId();
  const go = () => window.location.replace(new URL("/", window.location.origin).toString());
  const { ref, onKeyDown } = useDialogFocus(go);
  return (
    <div className="dc-back">
      <div ref={ref} className="dc-dlg" role="dialog" aria-modal="true" aria-labelledby={id} onKeyDown={onKeyDown}>
        <h2 id={id}>Account deleted</h2>
        <p className={receipt.status === "done" ? "dc-ok" : "dc-p"} role="status">
          {receiptLine(receipt)}
        </p>
        <p className="dc-p">
          You&apos;re signed out on every browser. Deletion ID <span className="mono">{receipt.id}</span>.
        </p>
        <details className="dc-kept">
          <summary>What stays</summary>
          <ul>
            {receipt.kept.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </details>
        <div className="dc-acts">
          <button className="btn sm ink" type="button" onClick={go}>
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}
