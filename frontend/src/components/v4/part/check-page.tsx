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
import { startCheck, useSession, retryPrices, setPanel, type CheckSession } from "./store";
import { StartScreen } from "./start";
import { OutOfChecks, PhoneNeeded } from "./blocked";
import { ProgressPanel } from "./progress";
import { PartView, type MeshSource } from "./part-view";
import { liveData } from "./data";
import { CantReadView } from "./cant-read";
import { RepairView } from "./repair";
import { AssemblyView } from "./assembly";
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

  const begin = React.useCallback((f: File, opts: { sample?: boolean } = {}) => {
    setPicked(null);
    setView("progress");
    setSid(startCheck(f, opts));
  }, []);

  React.useEffect(() => {
    if (started.current) return;
    started.current = true;
    const f = takePendingFile();
    if (f) return begin(f);
    if (new URLSearchParams(window.location.search).get("sample") === "1") {
      window.history.replaceState(window.history.state, "", R.check);
      begin(sampleBracketFile(), { sample: true });
    }
  }, [begin]);

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

  if (!session) {
    return <StartScreen file={picked} onFile={setPicked} onClear={() => setPicked(null)} onCheck={() => picked && begin(picked)} onSample={() => begin(sampleBracketFile(), { sample: true })} />;
  }
  const f = session.failure;
  if (session.status === "assembly" && session.assembly) return <AssemblyView session={session} onPick={(file) => begin(file)} />;
  if (f?.kind === "quota")
    return (
      <>
        <StartScreen file={null} onFile={(file) => setPicked(file)} onClear={() => setPicked(null)} onCheck={() => picked && begin(picked)} onSample={() => begin(sampleBracketFile(), { sample: true })} />
        <OutOfChecks message={f.message} />
      </>
    );
  if (f?.kind === "phone")
    return <StartScreen file={picked} onFile={setPicked} onClear={() => setPicked(null)} onCheck={() => picked && begin(picked)} onSample={() => begin(sampleBracketFile(), { sample: true })} notice={<PhoneNeeded message={f.message} />} />;
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
      overlay={session.status === "running" ? <ProgressPanel session={session} open={session.panel} onOpenChange={(o) => setPanel(session.id, o)} /> : null}
    />
  );
}
