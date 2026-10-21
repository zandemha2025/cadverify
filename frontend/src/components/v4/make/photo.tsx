"use client";

/**
 * Photo to 3D (board F4). The server says first whether image-to-3D runs here
 * (GET /reconstruct/capability): off, inside this deployment, or through an
 * approved third-party provider that needs the user's consent per transfer.
 * When on: add 1 to 4 photos, Reconstruct, the job is polled (leaving the page
 * doesn't stop it), then the mesh is shown with its confidence and handed on:
 * its DFM analysis, or a check of the mesh itself. With it off nothing can be
 * uploaded and the controls say why.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/ui/auth-provider";
import { canMutateWorkspace } from "@/lib/role-capabilities";
import {
  getJobResult,
  getJobStatus,
  getReconstructionCapability,
  getReconstructionMeshUrl,
  submitReconstruction,
  type ReconstructionCapability,
  type ReconstructionJobResult,
} from "@/lib/api";
import { createReconstructionSubmissionId } from "@/lib/reconstruction-id";
import { reconstructionAttempt, type ReconstructionAttempt } from "@/app/(app)/reconstruct/reconstruction-attempt";
import { startReconstructionPolling } from "@/app/(app)/reconstruct/reconstruction-poller";
import { reconstructionViewModel } from "@/app/(app)/reconstruct/reconstruction-result";
import { R } from "../routes";
import { setPendingFile } from "../pending-file";
import { Chip, Content, Sheet, cx } from "../ui";
import { MakeHead, MakeWorld, PilotPlanCard, errorText, isPaidAccessError, usePlan } from "./head";
import { Turntable } from "./turntable";
import {
  MAX_PHOTOS,
  PHOTO_ACCEPT,
  canAdd,
  dropTitle,
  goHint,
  goLabel,
  levelWord,
  metaState,
  modeOf,
  photoProblem,
  progressFraction,
  sheetMeta,
  statusLabel,
  stepNote,
  stepNow,
  steps,
  type Phase,
} from "./photo-model";

function useObjectUrls(files: File[]): string[] {
  const [urls, setUrls] = React.useState<string[]>([]);
  React.useEffect(() => {
    const next = files.map((f) => URL.createObjectURL(f));
    setUrls(next);
    return () => next.forEach((u) => URL.revokeObjectURL(u));
  }, [files]);
  return urls;
}

export function PhotoScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const canMutate = canMutateWorkspace(user?.role);
  const plan = usePlan();
  const [cap, setCap] = React.useState<ReconstructionCapability | null>(null);
  const [capErr, setCapErr] = React.useState<string | null>(null);
  const [capTry, setCapTry] = React.useState(0);
  const [consent, setConsent] = React.useState(false);
  const [photos, setPhotos] = React.useState<File[]>([]);
  const [pickErr, setPickErr] = React.useState<string | null>(null);
  const [over, setOver] = React.useState(false);
  const [phase, setPhase] = React.useState<Phase>("upload");
  const [submitting, setSubmitting] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [gated, setGated] = React.useState(false);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [estimate, setEstimate] = React.useState(30);
  const [status, setStatus] = React.useState("queued");
  const [elapsed, setElapsed] = React.useState(0);
  const [result, setResult] = React.useState<ReconstructionJobResult | null>(null);
  const [partial, setPartial] = React.useState(false);
  const [handing, setHanding] = React.useState(false);
  const attempt = React.useRef<ReconstructionAttempt | null>(null);
  const input = React.useRef<HTMLInputElement>(null);
  const thumbs = useObjectUrls(photos);

  React.useEffect(() => {
    const ctl = new AbortController();
    setCap(null);
    setCapErr(null);
    getReconstructionCapability(ctl.signal)
      .then(setCap)
      .catch((e) => {
        if (!ctl.signal.aborted) setCapErr(errorText(e, "The availability check didn’t finish."));
      });
    return () => ctl.abort();
  }, [capTry]);

  const mode = modeOf(cap, !!capErr);
  const on = mode === "egress" || mode === "local";
  const readOnly = on && (!cap?.can_submit || !canMutate);
  const pilotBlocked = on && !readOnly && (gated || plan === "other");
  const allowed = on && !readOnly && !pilotBlocked;
  const step = stepNow(mode, phase, photos.length);
  const adding = allowed && canAdd(mode, consent, photos.length);
  const ready = allowed && photos.length > 0 && (mode !== "egress" || consent) && !submitting;

  const add = (list: FileList | File[] | null) => {
    if (!list || !adding) return;
    const incoming = Array.from(list);
    const problem = photoProblem(photos.length, incoming);
    setPickErr(problem);
    if (!problem) setPhotos((p) => [...p, ...incoming]);
  };
  const remove = (i: number) => {
    setPhotos((p) => p.filter((_, j) => j !== i));
    setPickErr(null);
  };

  // Poll the job until it ends; the elapsed clock is the only progress the server gives.
  React.useEffect(() => {
    if (phase !== "proc" || !jobId) return;
    const tick = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    const stop = startReconstructionPolling<ReconstructionJobResult>({
      jobId,
      fetchStatus: getJobStatus,
      fetchResult: getJobResult,
      onStatus: setStatus,
      onComplete: (r, terminal) => {
        setResult(r);
        setPartial(terminal === "partial");
        setPhase("done");
      },
      onError: (message) => {
        // A real terminal failure: a retry makes a new job, unlike a network retry.
        attempt.current = null;
        setErr(message);
        setPhase("upload");
      },
    });
    return () => {
      stop();
      window.clearInterval(tick);
    };
  }, [phase, jobId]);

  const submit = async () => {
    if (!ready) return;
    setSubmitting(true);
    setErr(null);
    try {
      // Retrying re-sends the same photos under the same submission id; nothing runs twice.
      const a = reconstructionAttempt(attempt.current, photos, createReconstructionSubmissionId);
      attempt.current = a;
      const res = await submitReconstruction(photos, undefined, undefined, a.submissionId, mode === "egress" && consent);
      setJobId(res.job_id);
      setEstimate(res.estimated_seconds || 30);
      setStatus(res.status || "queued");
      setElapsed(0);
      setPhase("proc");
    } catch (e) {
      if (isPaidAccessError(e)) setGated(true);
      setErr(errorText(e, "The provider didn’t answer."));
    } finally {
      setSubmitting(false);
    }
  };

  const restart = () => {
    setPhase("upload");
    setPhotos([]);
    setConsent(false);
    setJobId(null);
    setResult(null);
    setPartial(false);
    setErr(null);
    setPickErr(null);
    attempt.current = null;
  };

  const vm = reconstructionViewModel(result);
  const meshUrl = jobId && phase === "done" ? getReconstructionMeshUrl(jobId) : null;

  const checkMesh = async () => {
    if (!meshUrl || handing) return;
    setHanding(true);
    try {
      const res = await fetch(meshUrl, { cache: "no-store" });
      if (!res.ok) throw new Error(`The mesh didn’t download (${res.status}).`);
      const blob = await res.blob();
      setPendingFile(new File([blob], `reconstructed_${jobId}.stl`, { type: "model/stl" }));
      router.push(R.check);
    } catch (e) {
      setErr(errorText(e, "The mesh didn’t download."));
      setHanding(false);
    }
  };

  return (
    <MakeWorld label="Photo to 3D">
      <MakeHead title="Photo to 3D" meta={[metaState(mode), "JPEG, PNG, WebP", "Up to 4 photos · 20 MB each", "Result is an estimate"]} />
      <Content>
        {mode === "loading" ? (
          <div className="panel" role="status">
            <div className="empty">
              <span className="spin" aria-hidden="true" />
              <span>Checking whether Photo to 3D runs on this server</span>
            </div>
          </div>
        ) : mode === "error" ? (
          <div className="panel">
            <div className="empty">
              <b>Availability check didn’t finish</b>
              <span>Nothing was uploaded. {capErr}</span>
              <button className="btn sm" type="button" onClick={() => setCapTry((n) => n + 1)}>
                Try again
              </button>
            </div>
          </div>
        ) : mode === "off" ? (
          <div className="panel">
            <div className="hero4">
              <Chip tone="unk">Not available on this server</Chip>
              <b>Photo to 3D is off</b>
              <span>{cap?.message}</span>
              <Link className="btn ink" href={R.check}>
                Check a CAD file
              </Link>
              <small>No image has been uploaded or sent to a third party.</small>
            </div>
          </div>
        ) : (
          <div className="panel">
            <div className="hero4">
              <Chip tone="ok">{mode === "egress" ? "Approved third-party provider" : "In this deployment"}</Chip>
              <b>Photo to 3D is on</b>
              <span>{cap?.message}</span>
            </div>
          </div>
        )}

        {phase === "done" && meshUrl ? (
          <section className="panel" aria-labelledby="mk-mesh">
            <div className="ph">
              <h2 id="mk-mesh">Reconstructed mesh</h2>
              <span>
                {levelWord(vm.confidenceLevel)} confidence · {vm.faceCount.toLocaleString("en-US")} faces
              </span>
            </div>
            <div style={{ padding: "0 12px 12px" }}>
              <Turntable className="pobj" label="The reconstructed mesh. Drag, or use the arrow keys, to turn it." layers={[{ key: "mesh", source: { kind: "stl-url", url: meshUrl }, look: "solid" }]} />
            </div>
          </section>
        ) : null}

        <section className="panel" aria-labelledby="mk-steps">
          <div className="ph">
            <h2 id="mk-steps">Steps</h2>
            <span>{stepNote(mode, step)}</span>
          </div>
          <ol className="steps">
            {steps(mode).map((s, i) => (
              <li key={s.t} className={cx("stp", step === i + 1 && "on")} aria-current={step === i + 1 ? "step" : undefined}>
                <i>{i + 1}</i>
                <b>{s.t}</b>
                <span>{s.d}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className="panel" aria-labelledby="mk-get">
          <div className="ph">
            <h2 id="mk-get">What you get</h2>
            <span>From the server’s own notice</span>
          </div>
          <div className="facts">
            <div>
              <b>Mesh</b>An estimate from photographs, not dimensionally authoritative CAD
            </div>
            <div>
              <b>DFM check</b>Runs on the mesh, opens as an analysis
            </div>
            <div>
              <b>Confidence</b>High, medium or low, with a score
            </div>
          </div>
          <p style={{ margin: 0, padding: "0 16px 14px", color: "var(--ink3)", fontSize: 12.5 }}>Verify critical dimensions against measurements before making or quoting.</p>
        </section>
      </Content>

      <Sheet label="Photos">
        <div className="top">
          <h2 className="stitle">New reconstruction</h2>
          <p className="smeta">{sheetMeta(mode)}</p>
        </div>
        <div className="scroll">
          {readOnly ? (
            <div className="note">
              <b>Read only for your role</b>
              <span>Analysts and admins can reconstruct.</span>
              <span>
                <Link className="btn sm" href={R.analyses}>
                  Review analyses
                </Link>
              </span>
            </div>
          ) : pilotBlocked ? (
            <>
              <div className="note" style={{ marginBottom: 6 }}>
                <b>Reconstruction is part of the pilot plan</b>
                <span>Your plan covers single-part checks. No photo has been uploaded.</span>
              </div>
              <PilotPlanCard includes={["Photo to 3D", "Batch runs", "Assemblies", "Recalibration from real costs"]} />
            </>
          ) : phase === "upload" ? (
            <div className="swap">
              {mode === "off" || mode === "egress" ? (
                <label className={cx("cons", mode === "off" && "off")}>
                  <input type="checkbox" checked={consent} disabled={mode === "off"} onChange={(e) => setConsent(e.target.checked)} aria-describedby="mk-consent" />
                  <span id="mk-consent">
                    <b>Third-party transfer.</b> {mode === "egress" ? cap?.message : "Image-to-3D uses an approved third-party provider. Uploaded and derived imagery leaves this ScaleCAD deployment."} I approve this transfer.
                  </span>
                </label>
              ) : null}
              <button
                type="button"
                className={cx("drop4", over && "over")}
                aria-disabled={!adding}
                aria-describedby="mk-drop-hint"
                onClick={() => adding && input.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  if (adding) setOver(true);
                }}
                onDragLeave={() => setOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setOver(false);
                  add(e.dataTransfer.files);
                }}
              >
                <b>{dropTitle(mode, consent, photos.length)}</b>
                <span id="mk-drop-hint">JPEG, PNG or WebP · up to {MAX_PHOTOS} photos · 20 MB each</span>
              </button>
              <input
                ref={input}
                type="file"
                accept={PHOTO_ACCEPT}
                multiple
                hidden
                aria-label="Add photos"
                onChange={(e) => {
                  add(e.target.files);
                  e.target.value = "";
                }}
              />
              {pickErr ? (
                <p className="err" role="alert" style={{ marginTop: 8 }}>
                  {pickErr}
                </p>
              ) : null}
              {photos.length ? (
                <div className="thumbs">
                  {photos.map((p, i) => (
                    <div className="th4" key={`${p.name}-${i}`}>
                      {thumbs[i] ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={thumbs[i]} alt={`Photo ${i + 1}: ${p.name}`} />
                      ) : (
                        `Photo ${i + 1}`
                      )}
                      <button type="button" aria-label={`Remove image ${i + 1}`} onClick={() => remove(i)}>
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
              <p className="acc">{cap?.accuracy_notice ?? "A reconstructed mesh is an estimate from photographs, not dimensionally authoritative CAD. Verify critical dimensions before making or quoting."}</p>
              {err ? (
                <div className="errc" role="alert">
                  <b>Reconstruction didn’t start</b>
                  <span>{err} Your photos are still selected.</span>
                  <span className="row-btns">
                    <button className="btn ink sm" type="button" onClick={() => void submit()} aria-disabled={!ready}>
                      Try again
                    </button>
                    <button className="btn sm" type="button" onClick={() => setErr(null)}>
                      Dismiss
                    </button>
                  </span>
                </div>
              ) : null}
              <div style={{ display: "flex", gap: 8, alignItems: "center", padding: 12, flexWrap: "wrap" }}>
                <button className="btn ink" type="button" aria-disabled={!ready} onClick={() => void submit()}>
                  {submitting ? "Sending…" : goLabel(photos.length)}
                </button>
                <span className="fine" style={{ margin: 0 }}>
                  {goHint(mode, consent, photos.length)}
                </span>
              </div>
            </div>
          ) : phase === "proc" ? (
            <div className="prog4" role="status" aria-live="polite">
              <b>{statusLabel(status)}</b>
              <span className="num">
                {elapsed} s elapsed · estimated ~{estimate} s
              </span>
              <span className="pb" aria-hidden="true">
                <i style={{ transform: `scaleX(${progressFraction(elapsed, estimate)})` }} />
              </span>
              <span className="num" style={{ color: "var(--ink3)", fontSize: 12 }}>
                Job {jobId?.slice(0, 12)} · leaving this page doesn’t stop it
              </span>
            </div>
          ) : (
            <div className="prog4">
              <b>Reconstruction result</b>
              <span>
                {levelWord(vm.confidenceLevel)} confidence ({Math.round(vm.confidencePercent)}%) · {vm.faceCount.toLocaleString("en-US")} faces
              </span>
              {partial ? <span style={{ color: "var(--warn)" }}>Completed with limited output. Review the mesh before using its analysis.</span> : null}
              {err ? (
                <span className="err" role="alert" style={{ margin: 0 }}>
                  {err}
                </span>
              ) : null}
              <span className="row-btns">
                {vm.analysisId ? (
                  <Link className="btn ink sm" href={R.analysis(vm.analysisId)}>
                    Open analysis
                  </Link>
                ) : null}
                <button className={cx("btn sm", !vm.analysisId && "ink")} type="button" onClick={() => void checkMesh()} aria-disabled={handing}>
                  {handing ? "Opening…" : "Check this mesh"}
                </button>
                <button className="btn sm" type="button" onClick={restart}>
                  Start new
                </button>
              </span>
            </div>
          )}
        </div>
      </Sheet>
    </MakeWorld>
  );
}
