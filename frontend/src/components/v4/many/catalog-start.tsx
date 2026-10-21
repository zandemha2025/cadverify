"use client";

/**
 * New catalog run (board M4, for the catalog run): parts the way an ops owner
 * has them (many files at once, a whole folder, or a ZIP) plus an optional
 * parts list with quantities and materials. Many files or a folder are zipped
 * in the browser, so it's one upload. A free account sees its allowance; with
 * no machines yet it is asked to add them first, because the answer is about
 * its machines. Refusals say exactly why, with the way forward.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { R } from "../routes";
import { Chip, Sheet, cx } from "../ui";
import { registerWork, runKey } from "../work/work-bar";
import { PILOT_HREF } from "../moments/pilot-gate";
import { saveBlob } from "./common";
import { CatalogRunError, startCatalogRun, type RunCreated } from "./catalog-api";
import { fetchMachines } from "./many-api";
import {
  FREE_MAX_ZIP_BYTES,
  MATERIALS,
  allowanceText,
  fitNote,
  planFiles,
  refusalTitle,
  sizeText,
  zipEntryName,
  type CatalogAccess,
  type PickedFile,
} from "./catalog-model";
import { storedZip } from "./catalog-zip";
import { takePendingBatch } from "./pending-batch";
import "./catalog.css";

type Picked = PickedFile & { file: File };

type Phase =
  | { k: "idle" }
  | { k: "packing"; done: number; total: number }
  | { k: "uploading"; frac: number | null }
  | { k: "err"; title: string; message: string; code: string | null; batchId: string | null }
  | { k: "started"; run: RunCreated };

const TEMPLATE = "file,part_number,quantity,material\nbracket.step,BRK-100,25,6061-T6 aluminum\nhousing.stl,HSG-200,500,PETG\ncover.iges,CVR-300,40,304 stainless\n";

function picked(f: File, path?: string): Picked {
  const rel = path || (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
  return { name: f.name, path: rel, size: f.size, file: f };
}

/** Every file under a dropped folder (or the dropped files themselves). */
async function droppedFiles(dt: DataTransfer): Promise<Picked[]> {
  const items = Array.from(dt.items ?? []);
  const entries = items
    .map((i) => (typeof (i as DataTransferItem & { webkitGetAsEntry?: () => unknown }).webkitGetAsEntry === "function" ? (i as DataTransferItem & { webkitGetAsEntry: () => FileSystemEntry | null }).webkitGetAsEntry() : null))
    .filter((e): e is FileSystemEntry => !!e);
  if (!entries.length) return Array.from(dt.files ?? []).map((f) => picked(f));
  const out: Picked[] = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej));
      out.push(picked(file, `${prefix}${file.name}`));
      return;
    }
    if (!entry.isDirectory) return;
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
      if (!batch.length) break;
      for (const child of batch) await walk(child, `${prefix}${entry.name}/`);
    }
  };
  for (const e of entries) await walk(e, "");
  return out;
}

export function CatalogStartSheet({ access, onStarted }: { access: CatalogAccess; onStarted?: (run: RunCreated) => void }) {
  const router = useRouter();
  const filesRef = React.useRef<HTMLInputElement>(null);
  const folderRef = React.useRef<HTMLInputElement>(null);
  const listRef = React.useRef<HTMLInputElement>(null);
  const [files, setFiles] = React.useState<Picked[]>([]);
  const [listFile, setListFile] = React.useState<File | null>(null);
  const [material, setMaterial] = React.useState("");
  const [qty, setQty] = React.useState("100");
  const [over, setOver] = React.useState(false);
  const [phase, setPhase] = React.useState<Phase>({ k: "idle" });
  const [machines, setMachines] = React.useState<number | null>(null);
  const [goAhead, setGoAhead] = React.useState(false);
  const qtyHint = React.useId();
  const busy = phase.k === "packing" || phase.k === "uploading";

  React.useEffect(() => {
    folderRef.current?.setAttribute("webkitdirectory", "");
    folderRef.current?.setAttribute("directory", "");
    const handed = takePendingBatch();
    if (handed?.length) setFiles(handed.map((f) => picked(f)));
    fetchMachines().then((m) => setMachines(m.length), () => setMachines(null));
  }, []);

  const free = access.kind === "free";
  const plan = planFiles(files, { maxZipBytes: free ? FREE_MAX_ZIP_BYTES : undefined });
  const list = listFile ?? plan.list?.file ?? null;
  const parts = plan.zip ? null : plan.cad.length;
  const qtyVal = /^\d+$/.test(qty.trim()) && Number(qty) >= 1 && Number(qty) <= 10_000_000 ? Number(qty) : null;
  const noneLeft = free && access.usage.remaining === 0;
  const needShop = machines === 0 && !goAhead;
  const off = busy || !!plan.problem || (!plan.zip && !plan.cad.length) || qtyVal == null || noneLeft || needShop;
  const note = parts != null ? fitNote(parts, access) : null;

  const add = (more: Picked[]) => {
    if (busy) return;
    setPhase({ k: "idle" });
    setFiles((cur) => {
      // A ZIP replaces loose files and the other way round; a CSV joins either.
      const zipIn = more.some((f) => /\.zip$/i.test(f.name));
      const keep = zipIn ? cur.filter((f) => /\.(csv|tsv|txt)$/i.test(f.name)) : cur.filter((f) => !/\.zip$/i.test(f.name));
      const seen = new Set(keep.map((f) => f.path));
      return [...keep, ...more.filter((f) => !seen.has(f.path))];
    });
  };

  const start = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (off || qtyVal == null) return;
    try {
      let zip: Blob;
      let zipName: string;
      if (plan.zip) {
        zip = plan.zip.file;
        zipName = plan.zip.name;
      } else {
        setPhase({ k: "packing", done: 0, total: plan.cad.length });
        let n = 0;
        zip = await storedZip(
          plan.cad.map((f) => ({ name: zipEntryName(f), data: f.file })),
          () => {
            n += 1;
            setPhase({ k: "packing", done: Math.min(n, plan.cad.length), total: plan.cad.length });
          },
        );
        const folder = plan.cad[0]?.path.includes("/") ? plan.cad[0].path.split("/")[0] : "catalog";
        zipName = `${folder}.zip`;
      }
      setPhase({ k: "uploading", frac: 0 });
      const run = await startCatalogRun({ zip, zipName, list, materialClass: material || undefined, quantity: qtyVal }, (frac) => setPhase({ k: "uploading", frac }));
      setPhase({ k: "started", run });
      registerWork({ key: runKey(run.batch_id), href: R.batch(run.batch_id), persist: true, state: "running", label: `Checking ${run.parts} ${run.parts === 1 ? "part" : "parts"}`, detail: `0 of ${run.parts}`, progress: 0 });
      window.dispatchEvent(new Event("proofshape:usage-changed"));
      setFiles([]);
      setListFile(null);
      onStarted?.(run);
      router.push(R.batch(run.batch_id));
    } catch (err) {
      const e2 = err instanceof CatalogRunError ? err : new CatalogRunError(err instanceof Error ? err.message : "The run didn’t start.", 0, null, null);
      setPhase({ k: "err", title: refusalTitle(e2), message: e2.message, code: e2.code, batchId: e2.batchId });
    }
  };

  const shown = plan.zip ? [plan.zip] : plan.cad;
  const pct = phase.k === "uploading" && phase.frac != null ? Math.round(phase.frac * 100) : null;

  return (
    <Sheet label="New catalog run">
      <div className="top">
        <h2 className="stitle">New catalog run</h2>
        <p className="smeta">Every part checked against your machines, then sorted</p>
        <div className="cs-allow">
          {access.kind === "pilot" ? <Chip tone="ok">Pilot plan · no part limit</Chip> : null}
          {free ? <Chip tone={noneLeft ? "warn" : "ok"}>{allowanceText(access)}</Chip> : null}
          {free ? <span className="fh">Separate from your single-part checks</span> : null}
        </div>
      </div>
      <form className="scroll" onSubmit={start} noValidate>
        {machines === 0 ? (
          <div className="cs-shop" role="note">
            <b>Add your machines first</b>
            <span>The run sorts each part by the machines in Your shop. A machine from the catalog (Haas VF-2, Bambu Lab X1C, and more), added as it is, can already say yes.</span>
            <span className="acts">
              <Link className="btn sm ink" href={`${R.shop}?add=1`}>
                Add machines
              </Link>
              {!goAhead ? (
                <button className="btn sm" type="button" onClick={() => setGoAhead(true)}>
                  Run without machines
                </button>
              ) : (
                <span className="fh">Parts will land in Not sorted.</span>
              )}
            </span>
          </div>
        ) : null}
        <div className="frm">
          <div
            className={cx("cs-drop", over && "over", shown.length > 0 && "has")}
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              void droppedFiles(e.dataTransfer).then(add);
            }}
          >
            <b>{shown.length ? (plan.zip ? plan.zip.name : `${plan.cad.length} ${plan.cad.length === 1 ? "part" : "parts"} · ${sizeText(plan.bytes)}`) : "Drop parts, a folder or a ZIP"}</b>
            <span>{shown.length ? "Drop more to add them" : "STEP, STL or IGES · a parts list CSV can come along"}</span>
            <span className="cs-pick">
              <button className="btn sm" type="button" onClick={() => filesRef.current?.click()} disabled={busy}>
                Choose files
              </button>
              <button className="btn sm" type="button" onClick={() => folderRef.current?.click()} disabled={busy}>
                Choose a folder
              </button>
              {shown.length ? (
                <button className="btn sm ghost" type="button" onClick={() => setFiles([])} disabled={busy}>
                  Clear
                </button>
              ) : null}
            </span>
            {shown.length ? (
              <span className="cs-files" aria-label="Parts in this run">
                {shown.slice(0, 5).map((f) => (
                  <span key={f.path} title={f.path}>
                    {f.path}
                  </span>
                ))}
                {shown.length > 5 ? <span>and {shown.length - 5} more</span> : null}
              </span>
            ) : null}
          </div>
          <input
            ref={filesRef}
            type="file"
            multiple
            accept=".step,.stp,.stl,.iges,.igs,.zip,.csv"
            aria-label="Choose part files, a ZIP or a parts list"
            tabIndex={-1}
            hidden
            onChange={(e) => {
              add(Array.from(e.target.files ?? []).map((f) => picked(f)));
              e.target.value = "";
            }}
          />
          <input
            ref={folderRef}
            type="file"
            multiple
            aria-label="Choose a folder of parts"
            tabIndex={-1}
            hidden
            onChange={(e) => {
              add(Array.from(e.target.files ?? []).map((f) => picked(f)));
              e.target.value = "";
            }}
          />
          {plan.problem ? (
            <span className="fe" role="alert">
              {plan.problem}
            </span>
          ) : null}
          {plan.skipped.length ? (
            <details className="cs-skip">
              <summary>
                {plan.skipped.length} {plan.skipped.length === 1 ? "file" : "files"} left out
              </summary>
              <ul>
                {plan.skipped.slice(0, 30).map((s, i) => (
                  <li key={i}>
                    {s.name}: {s.why}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          <label className="field">
            Parts list <span className="fh">Optional. CSV or a BOM export: file or part number, quantity, material.</span>
            <input
              ref={listRef}
              type="file"
              accept=".csv,.tsv,.txt,text/csv"
              disabled={busy}
              onChange={(e) => {
                setListFile(e.target.files?.[0] ?? null);
                setPhase({ k: "idle" });
              }}
            />
            {list && !listFile ? <span className="fh">Using {list.name} from the files you added.</span> : null}
          </label>
          <div style={{ marginTop: -4 }}>
            <button
              className="lk"
              type="button"
              onClick={() => saveBlob(new Blob([TEMPLATE], { type: "text/csv" }), "parts-list-template.csv")}
            >
              Download a parts list template
            </button>
          </div>
          <div className="cs-row">
            <label className="field">
              Material <span className="fh">For parts the list doesn’t name</span>
              <select value={material} onChange={(e) => setMaterial(e.target.value)} disabled={busy}>
                {MATERIALS.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Quantity <span className="fh">Each, unless listed</span>
              <input
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                value={qty}
                disabled={busy}
                aria-invalid={qtyVal == null}
                aria-describedby={qtyHint}
                onChange={(e) => setQty(e.target.value)}
              />
            </label>
          </div>
          <span className={qtyVal == null ? "fe" : "fh"} id={qtyHint} style={{ marginTop: -6 }}>
            {qtyVal == null ? "Enter a whole number of parts, 1 or more." : "Prices and machine time are shown at this quantity."}
          </span>
        </div>

        <div aria-live="polite">
          {note ? <div className="cs-ok">{note}</div> : null}
          {noneLeft ? (
            <div className="errc" role="status">
              <b>Your free catalog parts are used</b>
              <span>Parts you already ran stay open. The pilot plan has no part limit.</span>
              <Link className="lk" href={PILOT_HREF.request}>
                Talk to us about a pilot
              </Link>
            </div>
          ) : null}
          {phase.k === "packing" ? (
            <div className="upl" role="status">
              <span>
                Packing {phase.done} of {phase.total} files into one upload…
              </span>
              <span className="pb" aria-hidden="true">
                <i style={{ transform: `scaleX(${phase.total ? phase.done / phase.total : 0})` }} />
              </span>
            </div>
          ) : null}
          {phase.k === "uploading" ? (
            <div className="upl" role="status">
              <span>{pct != null && pct >= 100 ? "Upload complete · starting the run…" : "Uploading…"}</span>
              <span className={pct == null ? "pb ind" : "pb"} aria-hidden="true">
                <i style={pct == null ? undefined : { transform: `scaleX(${pct / 100})` }} />
              </span>
              {pct != null ? <span className="num" style={{ color: "var(--ink3)", fontSize: 12 }}>{pct}%</span> : null}
            </div>
          ) : null}
          {phase.k === "err" ? (
            <div className="errc" role="alert">
              <b>{phase.title}</b>
              <span>{phase.message}</span>
              {phase.code === "catalog_run_active" && phase.batchId ? (
                <Link className="lk" href={R.batch(phase.batchId)}>
                  Open the run
                </Link>
              ) : phase.code === "phone_verification_required" ? (
                <Link className="lk" href={R.phone}>
                  Verify your phone
                </Link>
              ) : phase.code === "catalog_allowance_exceeded" || phase.code === "catalog_run_work_email" ? (
                <Link className="lk" href={PILOT_HREF.request}>
                  Talk to us about a pilot
                </Link>
              ) : (
                <span>Nothing was started. Your files are still selected.</span>
              )}
            </div>
          ) : null}
          {phase.k === "started" ? (
            <div className="okc" role="status">
              <b>Run started</b>
              <span>
                {phase.run.parts} {phase.run.parts === 1 ? "part" : "parts"}
                {phase.run.catalog.free ? ` · ${phase.run.catalog.new} new, ${phase.run.catalog.reruns} run before · ${phase.run.catalog.remaining} free left` : ""}
              </span>
              <Link className="lk" href={R.batch(phase.run.batch_id)}>
                Open the run
              </Link>
            </div>
          ) : null}
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", padding: 12, flexWrap: "wrap" }}>
          <button className="btn ink" type="submit" aria-disabled={off}>
            {busy ? "Starting…" : parts ? `Check ${parts} ${parts === 1 ? "part" : "parts"}` : plan.zip ? "Check the ZIP" : "Check parts"}
          </button>
          <span className="fh">
            {needShop ? "Add machines, or choose to run without them" : free ? "A run keeps going if you leave this page" : "Pilot runs take up to 12 parts at a time"}
          </span>
        </div>
        {free ? (
          <p style={{ margin: "0 12px 16px", color: "var(--ink3)", fontSize: 12.5 }}>
            Free runs: up to 1 GB, 4 parts at a time, one run at a time. A part you’ve run or checked before is free again.
          </p>
        ) : null}
      </form>
    </Sheet>
  );
}
