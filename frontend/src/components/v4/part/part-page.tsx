"use client";

/**
 * /app/part/[key]: the part by its mesh hash. A check that just ran is shown from
 * memory (and keeps updating while it runs); otherwise the latest saved record,
 * its analysis and the part's context are loaded. 3D comes from the check, from
 * this browser's own copy, from the file the organization kept, or from dropping
 * the same file again. With no file in this browser, a re-check (another
 * material, your machines, your conditions) runs on the kept file
 * (POST /parts/{hash}/recheck): nothing to pick, no check used.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { loadPartMesh, loadSavedPart, recheckStored, RecheckError, type SavedPart } from "./api";
import { keptToastLine } from "./kept-job-model";
import { ownedProcessesFrom } from "@/lib/verify/machine-api";
import { markCheckOpened, previewFromFile, retryPreview, retryPrices, setPanel, startCheck, useSessionForKey } from "./store";
import { liveData, savedData } from "./data";
import { PartView, type MeshSource } from "./part-view";
import { ProgressPanel } from "./progress";
import { PartUrlSync } from "./url-sync";
import { OutOfChecks } from "./blocked";
import { liveMesh } from "./check-page";
import { SampleFlow } from "../home/sample-result";
import { FirstRun } from "../onboard/first-run-overlay";
import { OrientPanel } from "../orient/panel";
import { matOf, orientationParam, recordOf } from "../orient/orient";
import type { Lens } from "./ctx";
import { R } from "../routes";
import { Empty, Failed, Loading } from "../ui";
import { isQuotaErrorMessage } from "@/lib/api-recovery";
import "./part.css";

const LENS_KEYS: Lens[] = ["make", "cost", "use", "shop", "decide"];
const MATERIAL_WORD: Record<string, string> = { polymer: "plastic", aluminum: "aluminum", steel: "steel", stainless: "stainless steel", titanium: "titanium" };

export function PartPage({ partKey }: { partKey: string }) {
  const router = useRouter();
  const session = useSessionForKey(partKey);
  const [saved, setSaved] = React.useState<SavedPart | null>(null);
  const [state, setState] = React.useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [cache, setCache] = React.useState<{ url: string; faceHash: string | null; faceSpace: "analysis" | "preview"; origin: "cache" | "stored" } | null | undefined>(undefined);
  const [kept, setKept] = React.useState<boolean | null>(null);
  const [storedError, setStoredError] = React.useState<string | null>(null);
  const [meshTick, setMeshTick] = React.useState(0);
  const [drop, setDrop] = React.useState<{ url: string | null; faceHash: string | null; faceSpace: "analysis" | "preview"; error: string | null; loading: boolean } | null>(null);
  const [dropped, setDropped] = React.useState<File | null>(null);
  const [lens, setLens] = React.useState<Lens | null>(null);
  const [askedQty, setAskedQty] = React.useState<number | null>(null);
  const [quotaClosed, setQuotaClosed] = React.useState(false);
  const [reload, setReload] = React.useState(0);
  // A re-check of a saved part from the file its organization kept (no file here, no check used).
  // worker: the stage, when the kept file is large enough to be re-priced on ScaleCAD's worker.
  const [stored, setStored] = React.useState<{ s: "running"; what: string; worker?: string } | { s: "done"; what: string } | { s: "error"; msg: string; limit: boolean } | null>(null);
  const sessionDone = session?.status === "done";
  // A finished check is on screen here: the work bar lets it go.
  React.useEffect(() => {
    if (session && session.status !== "running") markCheckOpened(session.id);
  }, [session?.id, session?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // ?lens= opens a lens; ?qty=N (from a program's "Price at N") opens Cost at that quantity.
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const l = params.get("lens") as Lens | null;
    const n = Number(params.get("qty"));
    const qty = Number.isFinite(n) && n >= 1 ? Math.round(n) : null;
    setAskedQty(qty);
    setLens(l && LENS_KEYS.includes(l) ? l : qty ? "cost" : "make");
  }, []);

  // What's saved about the part (records, analysis, context). Reloaded once a live check finishes.
  React.useEffect(() => {
    let live = true;
    setState((s) => (saved ? s : "loading"));
    loadSavedPart(partKey)
      .then((p) => {
        if (!live) return;
        setSaved(p);
        setState("ready");
      })
      .catch((e) => {
        if (!live) return;
        setError(e instanceof Error ? e.message : "This part didn't load.");
        setState("error");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partKey, sessionDone, reload]);

  // 3D: this browser's copy, else the kept source file built on the server. Re-asked once a live check finishes.
  React.useEffect(() => {
    let live = true;
    let url: string | null = null;
    setStoredError(null);
    loadPartMesh(partKey, null).then((r) => {
      if (!live) return;
      setKept(r.kept);
      setStoredError(r.error);
      if (!r.mesh) return setCache(null);
      url = URL.createObjectURL(r.mesh.blob);
      setCache({ url, faceHash: r.mesh.faceHash, faceSpace: r.mesh.faceSpace, origin: r.mesh.origin });
    });
    return () => {
      live = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [partKey, sessionDone, meshTick]);

  // A re-check that stopped before any answer (out of checks) leaves the saved answers in place.
  const stoppedEarly = !!session && session.status === "failed" && !session.validation && session.failure?.kind === "quota" && !!saved;
  const data = React.useMemo(
    () => (session && !stoppedEarly ? liveData(session, saved) : saved ? savedData(partKey, saved) : null),
    [session, saved, partKey, stoppedEarly],
  );

  const mesh: MeshSource = React.useMemo(() => {
    if (session?.preview.url) return liveMesh(session);
    // A re-check of a part this browser already shows: keep that view while the check's own preview loads.
    if (session && session.preview.status === "loading" && !cache) return liveMesh(session);
    if (drop) return { url: drop.url, faceHash: drop.faceHash, faceSpace: drop.faceSpace, kind: "glb", origin: drop.url ? "drop" : null, loading: drop.loading, error: drop.error };
    if (cache) return { url: cache.url, faceHash: cache.faceHash, faceSpace: cache.faceSpace, kind: "glb", origin: cache.origin, loading: false, error: null };
    return { url: null, faceHash: null, faceSpace: "preview", kind: "glb", origin: null, loading: cache === undefined, error: session?.preview.error ?? storedError };
  }, [session, drop, cache, storedError]);

  const onDropFile = React.useCallback(
    async (file: File) => {
      setDrop({ url: null, faceHash: null, faceSpace: "preview", error: null, loading: true });
      const r = await previewFromFile(file, partKey);
      if (r.ok) {
        setDropped(file);
        setDrop({ url: r.url, faceHash: r.faceHash, faceSpace: r.faceSpace, error: null, loading: false });
      } else setDrop({ url: null, faceHash: null, faceSpace: "preview", error: r.error, loading: false });
    },
    [partKey],
  );

  const file = session?.file ?? dropped;
  // A re-check keeps the orientation of the check on screen unless it asks for another.
  const shownOrientation = session ? session.orientation : orientationParam(matOf(recordOf(data?.validation) ?? recordOf(data?.cost)));
  const storedRunning = stored?.s === "running";
  const recheck = React.useCallback(
    (opts?: { materialClass?: string; orientation?: string | null }) => {
      const materialClass = opts?.materialClass ?? session?.materialClass ?? data?.cost?.material_class ?? "polymer";
      if (file) {
        setQuotaClosed(false);
        startCheck(file, {
          materialClass,
          sample: session?.sample,
          orientation: opts?.orientation !== undefined ? opts.orientation : shownOrientation,
        });
        return;
      }
      // No file in this browser: price it again from the kept file. The decision is saved like an
      // upload's, so reloading the part shows it.
      if (kept !== true || storedRunning) return;
      const what = materialClass !== (data?.cost?.material_class ?? "polymer") ? `in ${MATERIAL_WORD[materialClass] ?? materialClass}` : "with your machines and conditions";
      setStored({ s: "running", what });
      const onWorker = (stage: string) => setStored((cur) => (cur?.s === "running" ? { ...cur, worker: stage } : cur));
      void recheckStored(partKey, { materialClass, qty: data?.cost?.quantities, owned: ownedProcessesFrom(saved?.machines ?? []), orientation: shownOrientation, onWorker })
        .then(() => {
          setStored({ s: "done", what });
          setReload((n) => n + 1);
        })
        .catch((e: unknown) => setStored({ s: "error", msg: e instanceof Error ? e.message : "The re-check didn’t finish.", limit: e instanceof RecheckError && e.limit }));
    },
    [file, kept, storedRunning, partKey, saved?.machines, session?.materialClass, session?.sample, data?.cost?.material_class, data?.cost?.quantities, shownOrientation],
  );
  React.useEffect(() => {
    if (stored?.s !== "done") return;
    const t = window.setTimeout(() => setStored(null), 4200);
    return () => window.clearTimeout(t);
  }, [stored]);

  if (!lens) return null;
  if (!data) {
    if (state === "error")
      return (
        <main className="world pv" aria-label="Part">
          <div className="pagehead" style={{ right: 24 }}>
            <h1 className="ptitle">Part</h1>
          </div>
          <div className="content full">
            <Failed title="This part didn't load" detail={error} onRetry={() => setReload((n) => n + 1)} />
          </div>
        </main>
      );
    return (
      <main className="world pv" aria-label="Part">
        <div className="pagehead" style={{ right: 24 }}>
          <h1 className="ptitle">Part</h1>
        </div>
        <div className="content full">
          <div className="panel">
            <Loading rows={5} label="Loading this part" />
          </div>
        </div>
      </main>
    );
  }
  if (!session && saved && !saved.latest && !saved.validation && !saved.decisions.length) {
    return (
      <main className="world pv" aria-label="Part">
        <div className="pagehead" style={{ right: 24 }}>
          <Link href={R.parts} style={{ fontSize: 12.5, textDecoration: "none" }}>
            ‹ Parts
          </Link>
          <h1 className="ptitle">Part not found</h1>
          <p className="pmeta">
            <span className="mono">{partKey.slice(0, 16)}</span>
          </p>
        </div>
        <div className="content full">
          <div className="panel">
            <Empty title="Nothing saved for this part" actions={<Link className="btn ink sm" href={R.check}>Check a part</Link>}>
              No check or record in your organization has this fingerprint. If you checked it in another organization, switch to it from the account menu.
            </Empty>
          </div>
        </div>
      </main>
    );
  }
  const running = session?.status === "running";
  const quotaMessage = !session || quotaClosed ? null : session.failure?.kind === "quota" ? session.failure.message : isQuotaErrorMessage(session.result?.costError ?? null) ? session.result!.costError! : null;
  const overlay = (
    <>
      {session?.sample && !running ? <SampleFlow status={session.status} result={session.result} onRetry={() => router.push(`${R.check}?sample=1`)} /> : null}
      {session && (running || (session.panel && !session.sample)) && session.status !== "failed" ? (
        <ProgressPanel
          session={session}
          open={session.panel}
          onOpenChange={(o) => setPanel(session.id, o)}
          action={
            !running ? (
              <button className="btn ink sm" type="button" onClick={() => setPanel(session.id, false)}>
                Open result
              </button>
            ) : undefined
          }
        />
      ) : null}
      {quotaMessage ? <OutOfChecks message={quotaMessage} onClose={() => setQuotaClosed(true)} /> : null}
      <FirstRun />
      <PartUrlSync />
      <OrientPanel recheck={(orientation) => recheck({ orientation })} canRecheck={!!file} />
      {stored ? (
        <div className="toast ptoast" role={stored.s === "error" ? "alert" : "status"} aria-live="polite">
          <span>
            {stored.s === "running"
              ? stored.worker
                ? `Re-checking ${data.fileName} ${stored.what}, ${keptToastLine(stored.worker)} · no check used`
                : `Re-checking ${data.fileName} ${stored.what}, from the file kept with this part · no check used`
              : stored.s === "done"
                ? `Re-checked ${stored.what} · saved as a new record · no check used`
                : stored.msg}
          </span>
          {stored.s === "error" ? (
            <span style={{ marginLeft: "auto", display: "inline-flex", gap: 8 }}>
              {stored.limit ? <Link href={R.billing}>Plans</Link> : null}
              <button className="btn sm ghost" type="button" onClick={() => setStored(null)}>
                Close
              </button>
            </span>
          ) : null}
        </div>
      ) : null}
    </>
  );
  return (
    <PartView
      key={partKey}
      data={data}
      session={stoppedEarly ? null : session}
      mesh={mesh}
      initialLens={lens}
      initialQty={askedQty}
      canRecheck={!!file || kept === true}
      onRecheck={recheck}
      onRetryPrices={() => session && void retryPrices(session.id)}
      onDropFile={session ? undefined : (f) => void onDropFile(f)}
      onRetryPreview={session?.preview.status === "failed" ? () => retryPreview(session.id) : storedError ? () => setMeshTick((n) => n + 1) : undefined}
      sourceKept={kept}
      overlay={overlay}
      file={file}
    />
  );
}
