"use client";

/**
 * Delete a part: what goes (counted from the server, not guessed), that it
 * can't be undone, that shared links stop working, and what stays. The final
 * step is the v4 ConfirmButton. After it, the receipt says what was removed
 * and, while stored files are still being removed, how far that got.
 */
import * as React from "react";
import { ConfirmButton } from "../ui";
import { forget } from "../home/data";
import { forgetLoaded } from "../records/api";
import { deleteCachedMeshes } from "../part/mesh-cache";
import { deletePart, deletionStatus, partDeletionPreview } from "./api";
import { fingerprint, linksLine, partRemovalLines, receiptLine, type PartPreview, type Receipt } from "./words";
import { useReadOnly } from "../read-only";
import "./data.css";

export function DeletePartButton({
  partKey,
  fileName,
  className = "btn sm",
  label = "Delete part",
  onDeleted,
  readOnlyAs = "hidden",
}: {
  partKey: string;
  fileName: string;
  className?: string;
  label?: string;
  /** Called when the person closes the receipt. */
  onDeleted: () => void;
  /** For an org viewer, who can't delete: no button, and optionally the one line saying why. */
  readOnlyAs?: "hidden" | "line";
}) {
  const [open, setOpen] = React.useState(false);
  const readOnly = useReadOnly();
  if (readOnly) {
    return readOnlyAs === "line" ? (
      <span role="note" style={{ flexBasis: "100%", fontSize: 12.5, color: "var(--ink3)" }}>
        {readOnly}
      </span>
    ) : null;
  }
  return (
    <>
      <button className={className} type="button" onClick={() => setOpen(true)} title="Delete this part, its stored file and its results">
        {label}
      </button>
      {open ? <DeletePartDialog partKey={partKey} fileName={fileName} onClose={() => setOpen(false)} onDeleted={onDeleted} /> : null}
    </>
  );
}

export function useDialogFocus(onClose: () => void) {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button, input")?.focus();
    return () => back?.focus?.();
  }, []);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
    }
    if (e.key === "Tab" && ref.current) {
      const f = [...ref.current.querySelectorAll<HTMLElement>("a[href],button:not([disabled]),input:not([disabled]),select,summary")];
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };
  return { ref, onKeyDown };
}

/** Polls a receipt while its stored files are still being removed (every 2 s, up to a minute). */
export function useReceipt(initial: Receipt | null): Receipt | null {
  const [r, setR] = React.useState(initial);
  React.useEffect(() => setR(initial), [initial]);
  React.useEffect(() => {
    if (!r || r.status !== "removing_files") return;
    let tries = 0;
    let live = true;
    const t = window.setInterval(() => {
      tries += 1;
      if (tries > 30) return window.clearInterval(t);
      deletionStatus(r.id).then((x) => live && setR(x), () => undefined);
    }, 2000);
    return () => {
      live = false;
      window.clearInterval(t);
    };
  }, [r]);
  return r;
}

function DeletePartDialog({ partKey, fileName, onClose, onDeleted }: { partKey: string; fileName: string; onClose: () => void; onDeleted: () => void }) {
  const [keepCopies, setKeepCopies] = React.useState(false);
  const [preview, setPreview] = React.useState<PartPreview | null>(null);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [done, setDone] = React.useState<Receipt | null>(null);
  const [asking, setAsking] = React.useState(false);
  const receipt = useReceipt(done);
  const id = React.useId();
  const close = done ? onDeleted : onClose;
  const { ref, onKeyDown } = useDialogFocus(close);

  React.useEffect(() => {
    let live = true;
    setLoadErr(null);
    partDeletionPreview(partKey, keepCopies).then(
      (p) => live && setPreview(p),
      (e) => live && setLoadErr(e instanceof Error ? e.message : "What this part holds didn't load."),
    );
    return () => {
      live = false;
    };
  }, [partKey, keepCopies]);

  const confirm = async () => {
    setErr(null);
    try {
      const r = await deletePart(partKey, keepCopies);
      const gone = [partKey, ...(keepCopies ? [] : preview?.fixed_copies ?? [])];
      void deleteCachedMeshes(gone);
      forget("");
      forgetLoaded();
      setDone(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The part wasn't deleted. Nothing was changed.");
    }
  };

  const copies = preview?.fixed_copies?.length ?? 0;
  const lines = preview ? partRemovalLines(preview, keepCopies) : [];
  const links = preview ? linksLine(preview) : null;
  return (
    <div className={receipt ? "dc-back gone" : "dc-back"} onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div ref={ref} className="dc-dlg" role="dialog" aria-modal="true" aria-labelledby={id} onKeyDown={onKeyDown}>
        <h2 id={id}>{receipt ? "Part deleted" : "Delete this part"}</h2>
        <p className="dc-meta">
          {preview?.file_name || fileName} · fingerprint <span className="mono">{fingerprint(partKey)}</span>
        </p>
        {receipt ? (
          <>
            <p className={receipt.status === "done" ? "dc-ok" : "dc-p"} role="status">
              {receiptLine(receipt)}
            </p>
            <p className="dc-p">
              ScaleCAD keeps a deletion record: who deleted the file with this fingerprint, and when. Not its name or results. Deletion ID{" "}
              <span className="mono">{receipt.id}</span>.
            </p>
            <div className="dc-acts">
              <button className="btn sm ink" type="button" onClick={onDeleted}>
                Done
              </button>
            </div>
          </>
        ) : loadErr ? (
          <>
            <p className="dc-err" role="alert">
              {loadErr}
            </p>
            <div className="dc-acts">
              <button className="btn sm" type="button" onClick={onClose}>
                Close
              </button>
            </div>
          </>
        ) : !preview ? (
          <p className="dc-p" role="status">
            Counting what this part holds…
          </p>
        ) : preview.already_deleted ? (
          <>
            <p className="dc-p">This part was already deleted. {receiptLine(preview.already_deleted)}</p>
            <div className="dc-acts">
              <button className="btn sm ink" type="button" onClick={onDeleted}>
                Done
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="dc-p">
              Deletes, for everyone in your organization, now:
            </p>
            <ul className="dc-list">
              {lines.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
            {copies ? (
              <label className="dc-check">
                <input type="checkbox" checked={keepCopies} onChange={(e) => setKeepCopies(e.target.checked)} />
                <span>
                  Keep the {copies === 1 ? "copy" : `${copies} copies`} ScaleCAD fixed from it. A kept copy stays a part of its own; it no longer names this file.
                </span>
              </label>
            ) : null}
            {links ? <p className="dc-p"><b>{links}</b> Anyone who opens one sees that it isn&apos;t available.</p> : null}
            <p className="dc-warn">This can&apos;t be undone. Download anything you need first.</p>
            <details className="dc-kept">
              <summary>What stays</summary>
              <ul>
                {(preview.kept ?? []).map((k) => (
                  <li key={k}>{k}</li>
                ))}
              </ul>
            </details>
            {preview.can_delete ? null : (
              <p className="dc-err" role="alert">
                {preview.reason}
              </p>
            )}
            {err ? (
              <p className="dc-err" role="alert">
                {err}
              </p>
            ) : null}
            <div className="dc-acts">
              {preview.can_delete ? (
                <ConfirmButton className="btn sm ink" label="Delete part" question="Delete it for everyone? This can't be undone." confirmLabel="Delete" onConfirm={confirm} onAsking={setAsking} />
              ) : null}
              {/* While "Delete it for everyone?" asks, its own Cancel is the only one. */}
              {asking ? null : (
                <button className="btn sm" type="button" onClick={onClose}>
                  Cancel
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
