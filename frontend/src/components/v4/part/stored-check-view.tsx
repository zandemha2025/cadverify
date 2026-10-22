"use client";

/**
 * A big file's check on the check page: the upload (with what's sent, and that
 * it resumes), then the worker's stages, from the real state (stored-check.ts).
 * Hands over to the part's page when it's done. Leaving keeps it going: the
 * work bar shows it on every page.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CAD_UPLOAD_ACCEPT } from "@/lib/cad-file";
import { sizeText } from "@/lib/upload-limit";
import { R } from "../routes";
import { cx } from "../ui";
import { MATERIALS } from "../onboard/first-run";
import { markStoredOpened, retryStoredCheck, setStoredMaterial, stageWord, useStoredCheck } from "./stored-check";
import { overallFraction, storedSteps } from "./stored-check-model";
import "../onboard/onboard.css";
import "./stored-check.css";

const MATERIAL: Record<string, string> = Object.fromEntries(MATERIALS);

/** "What will it be made of?" while the file uploads: the check prices in the answer. */
function StoredMaterial({ id, current, open }: { id: number; current: string; open: boolean }) {
  return (
    <div className="nb-ask set" role="group" aria-labelledby={`sc-mat-${id}`}>
      <div className="q">
        <b id={`sc-mat-${id}`}>What will it be made of?</b>
        <span aria-live="polite">{open ? `Prices in ${(MATERIAL[current] ?? current).toLowerCase()}` : `Priced in ${(MATERIAL[current] ?? current).toLowerCase()}`}</span>
      </div>
      <span className="seg" role="radiogroup" aria-label="Material class">
        {MATERIALS.map(([k, label]) => (
          <button key={k} type="button" role="radio" className={cx(current === k && "on")} aria-checked={current === k} disabled={!open} onClick={() => setStoredMaterial(id, k)}>
            {label}
          </button>
        ))}
      </span>
      <p>{open ? "The shape checks don’t depend on it; the prices do. You can change it until the upload finishes." : "Another material later: re-check it from the part’s page."}</p>
    </div>
  );
}

export function StoredCheckView({ id, onPick, onRetried }: { id: number; onPick: (f: File) => void; onRetried: (id: number) => void }) {
  const router = useRouter();
  const c = useStoredCheck(id);
  const input = React.useRef<HTMLInputElement>(null);

  // Done on a closed solid: the part's own page, from its saved records.
  React.useEffect(() => {
    if (c?.phase === "done" && c.key && !c.geometryInvalid) {
      markStoredOpened(id);
      router.replace(R.part(c.key));
    }
  }, [c?.phase, c?.key, c?.geometryInvalid, id, router]);

  // Closing the tab mid-upload loses the browser's half: ask first.
  const uploading = c?.phase === "hashing" || c?.phase === "uploading" || c?.phase === "finishing";
  React.useEffect(() => {
    if (!uploading) return;
    const onBefore = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBefore);
    return () => window.removeEventListener("beforeunload", onBefore);
  }, [uploading]);

  if (!c) return null;
  const steps = storedSteps(c);
  const frac = overallFraction(c);
  const failed = c.phase === "failed";
  const name = c.partName ?? c.name;
  const title = failed ? "Not checked" : c.phase === "done" ? "Checked" : uploading ? `Uploading ${name}` : `Checking ${name}`;
  const manyParts = c.failure?.code === "ARCHIVE_MANY_PARTS";

  return (
    <main className="world pv" aria-label={title}>
      <section className="stage sc-stage" aria-label={title}>
        <div className="floor" />
        <div className="pagehead">
          <h1 className="ptitle" style={{ overflowWrap: "anywhere" }}>
            {title}
          </h1>
          <p className="pmeta">
            <span style={{ overflowWrap: "anywhere" }}>{c.name}</span>
            {c.size ? <span>{sizeText(c.size)}</span> : null}
            <span>{MATERIAL[c.materialClass] ?? c.materialClass}</span>
            <span>Checked on the worker</span>
          </p>
        </div>

        <div className={cx("sc-card", failed && "bad")} role="group" aria-label="Upload and check">
          <span className="sc-file" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 20 20" fill="none">
              <path d="M5 2.5h6.5L15 6v11.5H5z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
              <path d="M11.5 2.5V6H15" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
            </svg>
          </span>
          <b className="sc-name">{name}</b>
          {failed ? (
            <div className="sc-fail" role="alert">
              <b>{c.failure?.title ?? "The check didn’t finish"}</b>
              <span>{c.failure?.detail}</span>
            </div>
          ) : (
            <>
              <div className="sc-bar" role="progressbar" aria-label={title} aria-valuemin={0} aria-valuemax={100} aria-valuenow={frac == null ? undefined : Math.round(frac * 100)}>
                <i style={{ transform: `scaleX(${Math.max(0.02, frac ?? 0.02)})` }} />
              </div>
              <span className="sc-line num">
                {uploading ? `${sizeText(c.sent)} of ${sizeText(c.size)}` : stageWord(c.phase)}
                {c.phase === "done" && c.geometryInvalid ? " · not a closed solid" : null}
              </span>
              <span className="sc-note">
                {uploading
                  ? "Keep this tab open while it uploads. If the connection drops, it carries on; if the tab closes, pick the same file again and only the missing parts are sent."
                  : "You can leave this page. The check runs on the server; the bar at the foot of every page shows it, and opens the part when it’s ready."}
              </span>
            </>
          )}
          <span className="sc-acts">
            {failed && c.failure?.retry && c.file ? (
              <button className="btn ink sm" type="button" onClick={() => {
                const next = retryStoredCheck(id);
                if (next != null) onRetried(next);
              }}>
                Try again
              </button>
            ) : null}
            {manyParts ? (
              <Link className="btn ink sm" href={`${R.many}?new=1`}>
                Check them as a catalog run
              </Link>
            ) : null}
            {c.phase === "done" && c.key ? (
              <Link className="btn ink sm" href={R.part(c.key)} onClick={() => markStoredOpened(id)}>
                Open the part
              </Link>
            ) : null}
            {failed || c.phase === "done" ? (
              <button className="btn sm" type="button" onClick={() => input.current?.click()}>
                Choose another file
              </button>
            ) : null}
          </span>
          <input
            ref={input}
            type="file"
            accept={CAD_UPLOAD_ACCEPT}
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onPick(f);
            }}
          />
        </div>

        <section className="prog sc-prog" role="status" aria-live="polite" aria-labelledby="sc-title">
          <div className="hd">
            <div style={{ minWidth: 0 }}>
              <h2 className="stitle" id="sc-title">
                {failed ? "Stopped" : c.phase === "done" ? "Checked" : "Checking"}
              </h2>
              <p className="pmeta" style={{ marginTop: 4 }}>
                <span style={{ overflowWrap: "anywhere" }}>{name}</span>
                {c.partBytes && c.partBytes !== c.size ? <span>{sizeText(c.partBytes)} unpacked</span> : null}
              </p>
            </div>
          </div>
          <ol className="steps">
            {steps.map((s) => (
              <li key={s.key} className={`st ${s.state}`}>
                <span className="m" aria-hidden="true">
                  {s.state === "done" ? "✓" : s.state === "bad" ? "✕" : ""}
                </span>
                <span>
                  <b>{s.t}</b>
                  <span>
                    <span className="sr">{s.state === "done" ? "Done: " : s.state === "now" ? "In progress: " : s.state === "bad" ? "Failed: " : s.state === "skip" ? "Skipped: " : "Waiting: "}</span>
                    {s.d}
                  </span>
                </span>
              </li>
            ))}
          </ol>
          {failed ? null : <StoredMaterial id={id} current={c.materialClass} open={!c.checkId} />}
          <div className="ft">
            <span>{failed ? (c.failure?.code === "CHECK_TOO_LARGE" || !c.checkId ? "Nothing was charged." : "Nothing after this step ran.") : "The same file always gets the same result."}</span>
          </div>
        </section>
      </section>
    </main>
  );
}
