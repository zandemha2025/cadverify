"use client";

/**
 * The sample's result (board X9 states result / full / stopped), for the page
 * where the sample runs. Mount <SampleFlow> with the check session's status and
 * result: when the sample finishes it opens "Sample result" (Esc, ×, the scrim
 * or "Show full result" close it to the full result), then leaves the sample
 * bar; a stopped sample shows "Sample stopped" with Retry. "Back to start"
 * reopens Get started on Home; "Check my CAD" opens the file picker.
 */
import * as React from "react";
import { useRouter } from "next/navigation";
import type { VerifyResult } from "@/lib/verify/run";
import { R } from "../routes";
import { useShell } from "../shell";
import { Chip, Fig, Figs, Src } from "../ui";
import { Modal } from "./welcome";
import { sampleBarLine, sampleSummary, type SampleRunLite, type SampleSummary } from "./sample-derive";
import "./home.css";

export function SampleResultDialog({ s, onClose, onBack, onCheckMine }: { s: SampleSummary; onClose: () => void; onBack: () => void; onCheckMine: () => void }) {
  return (
    <Modal labelledBy="sr-title" onClose={onClose}>
      <div className="h-hd">
        <div style={{ minWidth: 0 }}>
          <h1 className="ptitle" id="sr-title">
            Sample result
          </h1>
          <p className="pmeta" style={{ marginTop: 6 }}>
            <span>{s.file}</span>
            {s.saved ? <span>Saved to Records</span> : null}
            <span>No check used</span>
          </p>
          <Figs>
            {s.figs.map((f) => (
              <Fig key={f.k} k={f.k} v={f.v} sub={f.s} tone={f.c} />
            ))}
          </Figs>
        </div>
        <button className="btn h-x" type="button" onClick={onClose} aria-label="Close and show the full result" data-autofocus>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      <div className="h-rbody">
        {s.firstIssue ? (
          <div className="h-box">
            <div className="h-h">
              <b>First issue · {s.firstIssue.way}</b>
              <Chip tone={s.firstIssue.tone}>{s.firstIssue.chip}</Chip>
            </div>
            <p>{s.firstIssue.text}</p>
          </div>
        ) : null}
        {s.cantText ? (
          <div className="h-box">
            <div className="h-h">
              <b>Can&apos;t make as drawn</b>
              <Chip tone="bad">{String(s.cant)}</Chip>
            </div>
            <p>{s.cantText}</p>
          </div>
        ) : null}
        {s.measured.length ? (
          <div className="h-box">
            <div className="h-h">
              <b>Measured</b>
              <Src kind="file">From the file</Src>
            </div>
            <div className="kv">
              {s.measured.map(([k, v]) => (
                <React.Fragment key={k}>
                  <span>{k}</span>
                  <b className="num">{v}</b>
                </React.Fragment>
              ))}
            </div>
          </div>
        ) : null}
        <p className="h-fine">{s.ratesNote}</p>
      </div>
      <div className="h-dfoot">
        <span className="h-r l">
          <button className="btn ghost sm" type="button" onClick={onBack}>
            Back to start
          </button>
        </span>
        <span className="h-r">
          <button className="btn sm" type="button" onClick={onCheckMine}>
            Check my CAD
          </button>
          <button className="btn ink sm" type="button" onClick={onClose}>
            Show full result
          </button>
        </span>
      </div>
    </Modal>
  );
}

/** The bar over the stage after the dialog closes ("full") or when the sample stopped. */
export function SampleBar({ kind, line, onRetry, onBack, onCheckMine }: { kind: "full" | "stopped"; line?: string; onRetry: () => void; onBack: () => void; onCheckMine: () => void }) {
  return (
    <div className="h-gbar swap" role="status">
      <span className={kind === "stopped" ? "h-gic warn" : "h-gic"} aria-hidden="true">
        {kind === "stopped" ? "!" : "✓"}
      </span>
      <span className="h-gtx">
        <b>{kind === "stopped" ? "Sample stopped" : "Sample"}</b>
        <span>{kind === "stopped" ? "No result saved · no check used" : line}</span>
      </span>
      <span className="h-gacts">
        {kind === "full" ? (
          <button className="btn ink sm" type="button" onClick={onCheckMine}>
            Check my CAD
          </button>
        ) : (
          <button className="btn ink sm" type="button" onClick={onRetry}>
            Retry sample
          </button>
        )}
        <button className="btn ghost sm" type="button" onClick={onBack}>
          Back to start
        </button>
      </span>
    </div>
  );
}

/** The sheet for a stopped sample: nothing was saved or charged. */
export function SampleStoppedSheet({ onRetry }: { onRetry: () => void }) {
  return (
    <aside className="sheet swap" aria-label="Sample stopped" style={{ bottom: "auto" }}>
      <div className="top">
        <h1 className="stitle">Sample stopped</h1>
        <p className="smeta">No result saved · no check used</p>
      </div>
      <div className="empty">
        <b>No result</b>
        <span>The check was interrupted before it finished.</span>
        <button className="btn ink sm" type="button" onClick={onRetry}>
          Retry sample
        </button>
      </div>
    </aside>
  );
}

/**
 * Drop-in for the page running the sample. `status` and `result` come from the
 * check session; `onRetry` restarts the sample run.
 */
export function SampleFlow({ status, result, onRetry }: { status: "running" | "done" | "failed" | "stopped" | string; result: VerifyResult | null; onRetry: () => void }) {
  const router = useRouter();
  const { pickFile } = useShell();
  const [open, setOpen] = React.useState(true);
  const summary = React.useMemo(() => (result ? sampleSummary(result as unknown as SampleRunLite) : null), [result]);
  const back = () => router.push(`${R.home}?welcome=1`);
  if (status === "stopped" || (status === "failed" && !result)) return <SampleBar kind="stopped" onRetry={onRetry} onBack={back} onCheckMine={pickFile} />;
  if (status !== "done" || !summary) return null;
  return open ? (
    <SampleResultDialog s={summary} onClose={() => setOpen(false)} onBack={back} onCheckMine={pickFile} />
  ) : (
    <SampleBar kind="full" line={sampleBarLine(summary)} onRetry={onRetry} onBack={back} onCheckMine={pickFile} />
  );
}
