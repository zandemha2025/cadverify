"use client";

/**
 * /app/check: takes the picked or dropped file (or the sample), runs the real
 * check, shows its progress, and hands over to the part page as soon as the
 * first answer lands. Where a check stops early (out of checks, phone, a file
 * that can't be read, an open shell, an assembly), it says so here.
 */
import * as React from "react";
import { useRouter } from "next/navigation";
import { sampleBracketFile } from "@/lib/verify/sample-cad";
import { takePendingFile } from "../pending-file";
import { R } from "../routes";
import { markCheckOpened, resumableSession, startCheck, useSession, retryPrices, retryPreview, setPanel, type CheckSession } from "./store";
import { StartScreen } from "./start";
import { OutOfChecks } from "./blocked";
import { DesignImportBanner, PhoneGateView } from "../moments";
import { designIdFromSearch, designRevisionFromSearch, importDesignStep } from "@/lib/verify/design-import";
import { ProgressPanel } from "./progress";
import { PartView, type MeshSource } from "./part-view";
import { liveData } from "./data";
import { CantReadView } from "./cant-read";
import { RepairView } from "./repair";
import { AssemblyView } from "./assembly";
import { SampleFlow } from "../home/sample-result";
import "./part.css";

export function liveMesh(s: CheckSession): MeshSource {
  return { url: s.preview.url, faceHash: s.preview.faceHash, faceSpace: s.preview.faceSpace, kind: "glb", origin: s.preview.url ? "live" : null, loading: s.preview.status === "loading", error: s.preview.error };
}

export function CheckPage() {
  const router = useRouter();
  const [sid, setSid] = React.useState<number | null>(null);
  const [picked, setPicked] = React.useState<File | null>(null);
  const [view, setView] = React.useState<"progress" | "cant" | "repair">("progress");
  const session = useSession(sid);
  const data = React.useMemo(() => (session ? liveData(session, null) : null), [session]);
  const mesh = React.useMemo(() => (session ? liveMesh(session) : null), [session]);
  const started = React.useRef(false);
  // Design Studio's "Verify revision n" (?design=<id>&revision=<n>): the exact STEP revision, checked like an upload.
  const [design, setDesign] = React.useState<{ state: "loading" | "done" | "error"; name?: string; revision: number | null; detail?: string } | null>(null);

  const begin = React.useCallback((f: File, opts: { sample?: boolean } = {}) => {
    setPicked(null);
    setDesign(null);
    setView("progress");
    setSid(startCheck(f, opts));
  }, []);

  // The sample never uses a check: the server knows its exact bytes, so it runs with none left.
  const beginSample = React.useCallback(() => {
    begin(sampleBracketFile(), { sample: true });
  }, [begin]);

  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    const f = takePendingFile();
    if (f) return begin(f);
    const search = window.location.search;
    if (new URLSearchParams(search).get("design") !== null) {
      // Read once, then drop the params so Back or a reload can't import (and check) it again.
      window.history.replaceState(window.history.state, "", R.check);
      const id = designIdFromSearch(search);
      const rawRevision = new URLSearchParams(search).get("revision");
      const revision = designRevisionFromSearch(search);
      if (!id) return setDesign({ state: "error", revision: null, detail: "That Design Studio link isn't valid. Open the design again from Design Studio." });
      if (rawRevision !== null && revision === null) return setDesign({ state: "error", revision: null, detail: "That design revision isn't valid. Open the design again from Design Studio." });
      setDesign({ state: "loading", revision });
      void importDesignStep(id, fetch, revision)
        .then((file) => {
          begin(file);
          setDesign({ state: "done", name: file.name, revision, detail: [revision != null ? `Revision ${revision}` : null, "STEP from Design Studio", "checking now"].filter(Boolean).join(" · ") });
        })
        .catch((e) => setDesign({ state: "error", revision, detail: e instanceof Error ? e.message : "The design couldn't be imported." }));
      return;
    }
    if (new URLSearchParams(search).get("sample") === "1") {
      window.history.replaceState(window.history.state, "", R.check);
      beginSample();
      return;
    }
    // Back on this page with no new file: the check that was left (still running, or
    // finished and not yet looked at) carries on here, rather than a blank start.
    const resume = resumableSession();
    if (resume != null) setSid(resume);
  }, [begin, beginSample]);

  // A finished check is on screen here: the work bar lets it go.
  React.useEffect(() => {
    if (session && session.status !== "running") markCheckOpened(session.id);
  }, [session?.id, session?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // A file picked from the top bar while this page is open.
  React.useEffect(() => {
    const onFocus = () => {
      const f = takePendingFile();
      if (f) begin(f);
    };
    window.addEventListener("focus", onFocus);
    const t = window.setInterval(onFocus, 500);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.clearInterval(t);
    };
  }, [begin]);

  // Hand over to the part page once the first answer lands on a closed solid.
  React.useEffect(() => {
    if (!session?.key) return;
    const v = session.validation;
    if (v && v.geometry.is_watertight && (session.status === "running" || session.status === "done")) {
      router.replace(R.part(session.key));
    }
  }, [session?.key, session?.validation, session?.status, router]);

  const designBanner = design ? <DesignImportBanner state={design.state} name={design.name} revision={design.revision} detail={design.detail} onDismiss={design.state === "done" ? () => setDesign(null) : undefined} /> : null;
  if (!session) {
    return <StartScreen file={picked} onFile={setPicked} onClear={() => setPicked(null)} onCheck={() => picked && begin(picked)} onSample={beginSample} notice={designBanner} />;
  }
  const f = session.failure;
  if (session.status === "assembly" && session.assembly) return <AssemblyView session={session} onPick={(file) => begin(file)} />;
  if (f?.kind === "quota")
    return (
      <>
        <StartScreen file={null} onFile={(file) => setPicked(file)} onClear={() => setPicked(null)} onCheck={() => picked && begin(picked)} onSample={beginSample} />
        <OutOfChecks message={f.message} />
      </>
    );
  if (f?.kind === "phone")
    return <PhoneGateView fileName={session.file.name} onVerified={() => undefined} onContinue={() => begin(session.file, { sample: session.sample })} continueLabel="Check the part" />;
  if (f?.kind === "unreadable") return <CantReadView session={session} onPick={(file) => begin(file)} onRetry={f.retry ? () => begin(session.file) : undefined} />;
  if (session.status === "stopped") {
    if (view === "repair") return <RepairView session={session} onPick={(file) => begin(file)} onBack={() => setView("cant")} />;
    return (
      <CantReadView
        session={session}
        onPick={(file) => begin(file)}
        onRepair={() => setView("repair")}
        overlay={
          view === "progress" ? (
            <ProgressPanel
              session={session}
              open={session.panel}
              onOpenChange={(o) => {
                setPanel(session.id, o);
                if (!o) setView("cant");
              }}
              action={
                <button className="btn ink sm" type="button" onClick={() => setView("cant")}>
                  See what&apos;s wrong
                </button>
              }
            />
          ) : null
        }
      />
    );
  }
  // Running before the first answer, or interrupted.
  return (
    <PartView
      data={data!}
      session={session}
      mesh={mesh!}
      canRecheck
      onRecheck={() => begin(session.file, { sample: session.sample })}
      onRetryPrices={() => void retryPrices(session.id)}
      onRetryPreview={() => retryPreview(session.id)}
      overlay={
        session.status === "running" ? (
          <>
            {design?.state === "done" ? <div className="design-note">{designBanner}</div> : null}
            <ProgressPanel session={session} open={session.panel} onOpenChange={(o) => setPanel(session.id, o)} />
          </>
        ) : session.sample ? (
          <SampleFlow status={session.status} result={session.result} onRetry={beginSample} />
        ) : null
      }
    />
  );
}
