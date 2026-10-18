"use client";

/**
 * The New batch sheet (board M4): a ZIP of CAD files up to 5 GB, an optional
 * manifest CSV (with a template), an optional webhook and its signing secret,
 * and files at a time 1–12. Upload stages are the uploader's own; a failed
 * upload keeps the ZIP selected and nothing is created twice.
 */
import * as React from "react";
import Link from "next/link";
import { BatchApiError, createBatch, type BatchCreateResponse, type UploadProgress } from "@/lib/api/batch";
import { DirectUploadError } from "@/lib/api/direct-upload";
import { releaseSingleFlight, tryAcquireSingleFlight } from "@/lib/single-flight";
import { R } from "../routes";
import { Sheet } from "../ui";
import { errorText, isPaidAccessError, saveBlob } from "./common";
import { MANIFEST_TEMPLATE, parseConcurrency, retryCopy, sizeLabel, uploadStageCopy, zipProblem } from "./batch-model";

type Phase =
  | { k: "idle" }
  | { k: "up" }
  | { k: "err"; message: string; before: boolean }
  | { k: "failed"; batch: BatchCreateResponse; message: string }
  | { k: "done"; batch: BatchCreateResponse; conc: number };

export function NewBatchSheet({
  onCreated,
  onPaidAccess,
  toast,
}: {
  onCreated: (b: BatchCreateResponse) => void;
  onPaidAccess: () => void;
  toast: (t: string) => void;
}) {
  const zipInput = React.useRef<HTMLInputElement>(null);
  const manifestInput = React.useRef<HTMLInputElement>(null);
  const lock = React.useRef(false);
  const [zip, setZip] = React.useState<File | null>(null);
  const [zipErr, setZipErr] = React.useState<string | null>(null);
  const [manifest, setManifest] = React.useState<File | null>(null);
  const [hook, setHook] = React.useState("");
  const [secret, setSecret] = React.useState("");
  const [conc, setConc] = React.useState("10");
  const [over, setOver] = React.useState(false);
  const [phase, setPhase] = React.useState<Phase>({ k: "idle" });
  const [up, setUp] = React.useState<UploadProgress | null>(null);
  const zipErrId = React.useId();
  const secretHint = React.useId();
  const concHint = React.useId();

  const busy = phase.k === "up";
  const needSecret = hook.trim().length > 0;
  const secretBad = needSecret && !secret.trim();
  const concVal = parseConcurrency(conc);
  const concBad = concVal == null;
  let hookBad = false;
  if (needSecret) {
    try {
      const u = new URL(hook.trim());
      hookBad = u.protocol !== "https:" && u.protocol !== "http:";
    } catch {
      hookBad = true;
    }
  }
  const off = !zip || busy || secretBad || concBad || hookBad;

  const pick = (f: File | null | undefined) => {
    if (!f || busy) return;
    const problem = zipProblem(f);
    if (problem) {
      setZipErr(problem);
      return;
    }
    setZipErr(null);
    setZip(f);
    setUp(null);
    setPhase({ k: "idle" });
  };

  const start = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (off || !zip || concVal == null) return;
    if (!tryAcquireSingleFlight(lock)) return;
    setPhase({ k: "up" });
    setUp(null);
    try {
      const created = await createBatch(zip, {
        webhookUrl: needSecret ? hook.trim() : undefined,
        webhookSecret: needSecret ? secret : undefined,
        manifest: manifest ?? undefined,
        concurrencyLimit: concVal,
        onUploadProgress: setUp,
      });
      setPhase({ k: "done", batch: created, conc: concVal });
      // The ZIP is sent; clear it so a second click can't create a duplicate batch.
      setZip(null);
      setManifest(null);
      if (manifestInput.current) manifestInput.current.value = "";
      toast("Batch created.");
      onCreated(created);
    } catch (err) {
      if (isPaidAccessError(err)) {
        setPhase({ k: "idle" });
        onPaidAccess();
        return;
      }
      const message = errorText(err, "The batch wasn’t created.");
      if (err instanceof BatchApiError && err.acceptedBatch) setPhase({ k: "failed", batch: err.acceptedBatch, message });
      else setPhase({ k: "err", message, before: err instanceof DirectUploadError });
    } finally {
      releaseSingleFlight(lock);
    }
  };

  const goLabel = busy ? "Uploading…" : phase.k === "err" ? "Retry upload" : phase.k === "failed" ? "Retry this ZIP" : "Start batch";
  const goHint = !zip ? "Choose a ZIP first" : hookBad ? "Fix the webhook URL" : secretBad ? "Add the signing secret" : concBad ? "Fix files at a time" : phase.k === "err" ? "Sends the same ZIP" : "";
  const pct = up?.percent ?? null;

  return (
    <Sheet label="New batch">
      <div className="top">
        <h2 className="stitle">New batch</h2>
        <p className="smeta">DFM check on every file in a ZIP</p>
      </div>
      <form className="scroll" onSubmit={start} noValidate>
        <div className="frm">
          <button
            type="button"
            className={["zip", zip ? "has" : "", over ? "over" : ""].join(" ")}
            aria-label={zip ? `ZIP selected: ${zip.name}. Choose another.` : "Choose a ZIP of CAD files"}
            aria-describedby={zipErr ? zipErrId : undefined}
            aria-disabled={busy}
            onClick={() => !busy && zipInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy) setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              pick(e.dataTransfer.files?.[0]);
            }}
          >
            <b>{zip ? zip.name : "Drop a ZIP of CAD files"}</b>
            <span>{zip ? `${sizeLabel(zip.size)} · click to choose another` : "Or click to choose · up to 5 GB · .zip only"}</span>
          </button>
          <input
            ref={zipInput}
            type="file"
            accept=".zip,application/zip"
            tabIndex={-1}
            aria-hidden="true"
            style={{ display: "none" }}
            onChange={(e) => {
              pick(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          {zipErr ? (
            <span className="fe" id={zipErrId} role="alert" style={{ marginTop: -6 }}>
              {zipErr}
            </span>
          ) : null}
          <label className="field">
            Manifest CSV <span className="fh">Optional. Columns: filename, process_types, rule_pack, priority</span>
            <input
              ref={manifestInput}
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
              onChange={(e) => setManifest(e.target.files?.[0] ?? null)}
            />
          </label>
          <div style={{ marginTop: -4 }}>
            <button className="lk" type="button" onClick={() => {
              saveBlob(new Blob([MANIFEST_TEMPLATE], { type: "text/csv" }), "manifest-template.csv");
              toast("Downloaded manifest-template.csv");
            }}>
              Download manifest template
            </button>
          </div>
          <label className="field">
            Webhook URL <span className="fh">Optional. Called when the batch finishes.</span>
            <input
              type="url"
              inputMode="url"
              placeholder="https://"
              value={hook}
              disabled={busy}
              aria-invalid={hookBad}
              onChange={(e) => setHook(e.target.value)}
              autoComplete="off"
            />
            {hookBad ? <span className="fe">Enter a full URL, starting with https://</span> : null}
          </label>
          {needSecret ? (
            <label className="field">
              Signing secret
              <input
                type="password"
                autoComplete="off"
                value={secret}
                disabled={busy}
                aria-invalid={secretBad}
                aria-describedby={secretHint}
                onChange={(e) => setSecret(e.target.value)}
              />
              <span className={secretBad ? "fe" : "fh"} id={secretHint}>
                Required for callbacks. A long random secret shared with your receiver.
              </span>
            </label>
          ) : null}
          <label className="field">
            Files at a time
            <input
              type="number"
              min={1}
              max={12}
              step={1}
              inputMode="numeric"
              value={conc}
              disabled={busy}
              aria-invalid={concBad}
              aria-describedby={concHint}
              onChange={(e) => setConc(e.target.value)}
              style={{ width: 120 }}
            />
            <span className={concBad ? "fe" : "fh"} id={concHint}>
              {concBad ? "Enter a whole number from 1 to 12." : "1 to 12 files at a time."}
            </span>
          </label>
        </div>

        <div aria-live="polite">
          {busy ? (
            <div className="upl" role="status" data-upload-stage={up?.stage ?? "checking"}>
              <span>{uploadStageCopy(up ?? { stage: "checking" })}</span>
              <span className={pct == null ? "pb ind" : "pb"} aria-hidden="true">
                <i style={pct == null ? undefined : { transform: `scaleX(${Math.max(0, Math.min(100, pct)) / 100})` }} />
              </span>
              {pct != null ? <span className="num" style={{ color: "var(--ink3)", fontSize: 12 }}>{pct}%</span> : null}
              {up && retryCopy(up) ? <span className="fh">{retryCopy(up)}</span> : null}
              {up?.stage === "proxying" ? <span className="fh">A byte percentage isn’t available for this upload path.</span> : null}
            </div>
          ) : null}
          {phase.k === "err" ? (
            <div className="errc" role="alert" data-upload-error>
              <b>{phase.before ? "Upload didn’t finish" : "Batch creation isn’t confirmed"}</b>
              <span>{phase.message}</span>
              <span>
                {phase.before
                  ? "No batch was created. The ZIP is still selected."
                  : "Check Recent batches before retrying, so a lost reply doesn’t create a duplicate."}
              </span>
            </div>
          ) : null}
          {phase.k === "failed" ? (
            <div className="errc" role="alert">
              <b>Batch accepted, then failed</b>
              <span>{phase.message}</span>
              <span>The record is kept with its error. The ZIP is still selected.</span>
              <Link className="lk" href={R.batch(phase.batch.batch_id)}>
                Inspect failed batch
              </Link>
            </div>
          ) : null}
          {phase.k === "done" ? (
            <div className="okc" role="status">
              <b>Batch created</b>
              <span>
                {phase.conc} {phase.conc === 1 ? "file" : "files"} at a time · files are counted as the ZIP opens
              </span>
              <Link className="lk" href={R.batch(phase.batch.batch_id)}>
                Open batch
              </Link>
            </div>
          ) : null}
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", padding: 12, flexWrap: "wrap" }}>
          <button className="btn ink" type="submit" aria-disabled={off}>
            {goLabel}
          </button>
          {goHint ? <span className="fh">{goHint}</span> : null}
        </div>
      </form>
    </Sheet>
  );
}
