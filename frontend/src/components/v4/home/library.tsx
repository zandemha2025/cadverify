"use client";

/**
 * Parts library onboarding (board O8 sheet): add many CAD files and an optional
 * identity mapping to the organization's parts library, so later uploads are
 * recognised by name. Picking files again adds to the list; each file and the
 * mapping can be removed before adding. The readout is the server's own counts.
 */
import * as React from "react";
import { onboardLibrary } from "@/lib/verify/library-api";
import type { OnboardSummary } from "@/lib/verify/library";
import { cx } from "../ui";
import { ReadOnlyLine, useReadOnly } from "../read-only";
import * as api from "./data";

const CAD = ".stl,.step,.stp,.iges,.igs";

export function LibraryPanel({ onAdded }: { onAdded: () => void }) {
  const [size, setSize] = React.useState<number | null>(null);
  const [files, setFiles] = React.useState<File[]>([]);
  const [mapping, setMapping] = React.useState<File | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [res, setRes] = React.useState<OnboardSummary | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  // A viewer opens the library but can't add to it: the pickers are off, with the reason.
  const readOnly = useReadOnly("add parts to the library");

  React.useEffect(() => {
    api.librarySize().then(setSize, () => setSize(null));
  }, []);

  const add = async () => {
    if (!files.length || busy) return;
    setBusy(true);
    setErr(null);
    setRes(null);
    const r = await onboardLibrary(files, mapping);
    setBusy(false);
    if (!r.ok) {
      setErr(r.error);
      return;
    }
    setRes(r.summary);
    setSize(r.summary.library_size);
    setFiles([]);
    setMapping(null);
    api.forget("/identity/library");
    onAdded();
  };

  return (
    <>
      <div className="gh">
        <span>Parts library</span>
        <span className="num">{size == null ? "" : `${size.toLocaleString("en-US")} ${size === 1 ? "part" : "parts"}`}</span>
      </div>
      <div className="h-lib">
        <span className="h-pk">
          <label className={cx("btn sm h-file", readOnly && "off")} aria-disabled={readOnly ? true : undefined} title={readOnly ?? undefined}>
            Choose CAD files
            <input
              type="file"
              multiple
              accept={CAD}
              aria-label="Choose CAD files for the parts library"
              disabled={busy || !!readOnly}
              onChange={(e) => {
                const picked = Array.from(e.target.files ?? []);
                e.target.value = "";
                setRes(null);
                setFiles((cur) => [...cur, ...picked.filter((p) => !cur.some((c) => c.name === p.name && c.size === p.size))]);
              }}
            />
          </label>
          <label className={cx("btn sm h-file", readOnly && "off")} aria-disabled={readOnly ? true : undefined} title={readOnly ?? undefined}>
            <span style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>{mapping ? mapping.name : "Choose mapping"}</span>
            <input
              type="file"
              accept=".csv,.json,text/csv,application/json"
              aria-label="Choose a mapping file, CSV or JSON"
              disabled={busy || !!readOnly}
              onChange={(e) => {
                const m = e.target.files?.[0] ?? null;
                e.target.value = "";
                if (m) {
                  setMapping(m);
                  setRes(null);
                }
              }}
            />
          </label>
          {mapping ? (
            <button type="button" className="btn sm ghost" onClick={() => setMapping(null)} disabled={busy}>
              Remove mapping
            </button>
          ) : null}
        </span>
        <small>Mapping columns: filename, part_id, name, program, material_class. Optional.</small>
        <ReadOnlyLine line={readOnly} />
        {files.length ? (
          <div className="h-files" role="list" aria-label="Files to add">
            {files.map((f, i) => (
              <div className="h-fl" role="listitem" key={`${f.name}-${i}`}>
                <span title={f.name}>{f.name}</span>
                <button type="button" className="h-link" aria-label={`Remove ${f.name}`} onClick={() => setFiles((cur) => cur.filter((x) => x !== f))} disabled={busy}>
                  Remove
                </button>
              </div>
            ))}
          </div>
        ) : null}
        <span className="h-pk">
          <button
            type="button"
            className={cx("btn sm", files.length ? "ink" : "off")}
            aria-disabled={!files.length || busy}
            onClick={() => void add()}
          >
            {busy ? "Adding…" : files.length ? `Add ${files.length} ${files.length === 1 ? "file" : "files"}` : "Add to library"}
          </button>
          <small>{files.length ? (mapping ? `With ${mapping.name}` : "No mapping: files are added by shape only") : "STEP, STL or IGES"}</small>
        </span>
        {err ? (
          <div className="h-res" role="alert">
            <b>Not added</b>
            <span className="h-skip">{err}</span>
          </div>
        ) : null}
        {res ? (
          <div className="h-res" role="status">
            <b>
              Added {res.onboarded} · library now {res.library_size}
            </b>
            {res.unnamed > 0 ? <span>{res.unnamed} without a name: added by shape only</span> : null}
            {res.manifest_registered > 0 ? <span>{res.manifest_registered} registered in the parts master</span> : null}
            {res.skipped.map((s) => (
              <span className="h-skip" key={s.filename}>
                Skipped {s.filename}: {s.reason}
              </span>
            ))}
            {res.mapping_errors.map((m, i) => (
              <span className="h-skip" key={`m${i}`}>
                Mapping{m.line ? ` row ${m.line}` : ""}: {m.reason}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </>
  );
}
