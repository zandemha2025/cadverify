"use client";

/**
 * The part (Main board): the real part fills the stage, five lenses answer
 * about it, and the dial moves the same object between them. Used by the check
 * page while a check runs and by the part page for a live or saved result.
 */
import * as React from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { downloadCostPdf } from "@/lib/api";
import { partFacts, shareRecord } from "../records/api";
import { ShareDialog } from "../share/share-dialog";
import { madeText } from "../share/words";
import { CAD_ACCEPT } from "../pending-file";
import { R } from "../routes";
import { cx } from "../ui";
import { useRegisterPaletteItems, usePalette, type PaletteItem } from "../palette";
import { LENSES, PartProvider, initialPick, useMethods, type Lens, type PartCtxValue, type PartData, type Toast } from "./ctx";
import { KIND_COLOR, cheapestAt, defaultQty, dimsText, machineViews, methodName, money, nearestComputed, priceAt, qtyWord, shortId } from "./model";
import type { ViewerController, ViewerHighlight, ViewerState } from "./viewer";
import { no3dTitle } from "./mesh-url";
import { revisionLine, type Revisions } from "./revision-link";
import { followed, recordedChoice } from "./choice";
import type { CheckSession } from "./store";
import { MakeSheet } from "./lens-make";
import { CostLayer, CostSheet } from "./lens-cost";
import { ShopLayer, ShopSheet } from "./lens-shop";
import { DecideSheet, DecideTicket } from "./lens-decide";
import { UseLayer, UseSheet } from "./lens-use";
import { AskDock } from "./ask";
import { PreviewFailed, RatesChip } from "../moments";
import { useShell } from "../shell";
import { FixProvider, useFixController } from "../fix/ctx";
import { problemForIssue } from "../fix/problems";
import { wbHref } from "../workbench/chrome";
import { FixStage, fixHint } from "../fix/stage";
import { ProblemSheet } from "../fix/problem-sheet";
import { AllProblemsSheet } from "../fix/all-sheet";
import { AskDialog } from "../fix/ask-dialog";
import { AfterFixView } from "../fix/after-fix";
import { OrientChip, OrientTool } from "../orient/panel";
import { useOrientView } from "../orient/state";
import { DeletePartButton } from "../datacontrol/delete-part";
import { BodiesChip, BodiesSheet, bodyHighlight, useBodies } from "./bodies";
import { normalizeSpecs, specLines } from "./specs";
import "./part.css";
import { UnitSwitch } from "../units/unit-switch";
import { dims as unitDims, volume as unitVolume } from "../units/units";
import { useUnits } from "../units/use-units";

const PartViewer = dynamic(() => import("./viewer"), { ssr: false });

export interface MeshSource {
  url: string | null;
  faceHash: string | null;
  faceSpace: "analysis" | "preview";
  kind: "glb" | "stl";
  /** live: fetched for this check · cache: this browser's copy · stored: built from the kept source file · drop: from a dropped copy */
  origin: "live" | "cache" | "stored" | "drop" | null;
  loading: boolean;
  error: string | null;
}

export function PartView({
  data: initial,
  session,
  mesh,
  initialLens = "make",
  initialQty = null,
  canRecheck,
  onRecheck,
  onRetryPrices,
  onDropFile,
  onRetryPreview,
  sourceKept = null,
  overlay,
  file = null,
  revisions = null,
}: {
  data: PartData;
  session: CheckSession | null;
  mesh: MeshSource;
  initialLens?: Lens;
  /** A quantity from the link (?qty=N): shown at that quantity, or the nearest one the check priced. */
  initialQty?: number | null;
  canRecheck: boolean;
  onRecheck: (opts?: { materialClass?: string; qty?: number }) => void;
  onRetryPrices: () => void;
  onDropFile?: (file: File) => void;
  /** Ask for the 3D preview again (same file, same check) after it failed. */
  onRetryPreview?: () => void;
  /** Whether the exact uploaded file is kept with the record (GET /parts/{hash}/source-status); null when unknown. */
  sourceKept?: boolean | null;
  /** The progress panel or a dialog over the part. */
  overlay?: React.ReactNode;
  /** The part's file in this browser, when there is one (a fix such as mesh repair needs the file itself). */
  file?: File | null;
  /** The part this one revises, or its next revision (a fixed file uploaded from a problem card). */
  revisions?: Revisions | null;
}) {
  const [data, setData] = React.useState<PartData>(initial);
  React.useEffect(() => setData(initial), [initial]);
  const { methods, rows, qs } = useMethods(data);
  const [asked, setAsked] = React.useState<number | null>(initialQty);
  const startQty = (list: number[]) => (asked != null ? nearestComputed(list, asked, defaultQty(list)) : defaultQty(list));
  const [q, setQState] = React.useState<number>(() => startQty(qs));
  // Whether the person chose the quantity (picked it here); until then the page follows the
  // default for the quantities priced (np-19: the check handed over before prices, so the page
  // fixed on 1 from an empty list and stayed there once 1 was priced).
  const [chosen, setChosen] = React.useState(false);
  // A quantity asked for (a link's ?qty=, or one just priced from Other quantity) is shown once priced.
  React.useEffect(() => {
    if (initialQty != null) setAsked(initialQty);
  }, [initialQty]);
  React.useEffect(() => {
    if (asked != null && qs.includes(asked) && q !== asked) {
      setQState(asked);
      return;
    }
    if (!qs.length) return;
    if (!qs.includes(q) || (!chosen && asked == null && q !== startQty(qs))) setQState(startQty(qs));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qs, q, asked, chosen]);
  const setQ = React.useCallback((n: number) => {
    setAsked(null);
    setChosen(true);
    setQState(n);
  }, []);
  const [oq, setOq] = React.useState("");
  const [lens, setLensState] = React.useState<Lens>(initialLens);
  const [selCode, setSelCode] = React.useState<string | null>(null);
  const [costPick, setCostPick] = React.useState<string | null>(null);
  const [machinePick, setMachinePick] = React.useState<string | null>(null);
  const [decidePick, setDecidePick] = React.useState<string | null>(null);
  const [toastState, setToastState] = React.useState<Toast | null>(null);
  const [xray, setXray] = React.useState(false);
  const [hint, setHint] = React.useState(true);
  const [viewer, setViewer] = React.useState<ViewerState>("loading");
  // Each new picture gets its own attempt: a load that failed doesn't hide the next one.
  React.useEffect(() => setViewer("loading"), [mesh.url]);
  const shell = useShell();
  const router = useRouter();
  const retryPreview = mesh.url ? (
    <button className="btn sm" type="button" onClick={() => setViewer("loading")}>
      Retry preview
    </button>
  ) : mesh.error && onRetryPreview && !mesh.loading ? (
    <button className="btn sm" type="button" onClick={onRetryPreview}>
      Retry preview
    </button>
  ) : null;
  const [over, setOver] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const controller = React.useRef(null) as ViewerController;
  const toastTimer = React.useRef<number | null>(null);

  // Opens on your choice for the part, else ScaleCAD's pick at this quantity, else the cheapest.
  const follow = followed(data.cost, q, recordedChoice(data.decision))?.process ?? null;
  const sel =
    methods.find((m) => m.code === selCode) ??
    rows.find((m) => m.code === selCode) ??
    methods.find((m) => m.code === follow && m.prices.has(q)) ??
    methods.find((m) => m.code === initialPick(methods, q)) ??
    null;
  const checking = session?.status === "running";
  const interrupted = !checking && !data.validation && !data.cost && session?.failure?.kind === "interrupted";
  const costOff = !checking && !!data.validation && !data.cost && !!data.costError;
  const has3d = !!mesh.url && viewer === "ready";
  const faceAligned = mesh.faceSpace === "analysis" && !!mesh.faceHash && mesh.faceHash === data.validation?.analysis_mesh_hash;
  const finding = sel?.finding ?? null;
  const lensHighlight: ViewerHighlight | null =
    lens === "make" && !interrupted && faceAligned && finding?.kind && finding.faces.length
      ? { faces: finding.faces, color: KIND_COLOR[finding.kind], region: finding.region, label: "1", kindClass: `k-${finding.kind}` }
      : null;

  const toast = React.useCallback((t: Toast) => {
    setToastState(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    if (!t.sticky) toastTimer.current = window.setTimeout(() => setToastState(null), 3600);
  }, []);
  React.useEffect(() => () => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
  }, []);

  const setLens = React.useCallback((l: Lens) => {
    setLensState(l);
    try {
      const u = new URL(window.location.href);
      u.searchParams.set("lens", l);
      window.history.replaceState(window.history.state, "", u.toString());
    } catch {
      /* the lens still changes */
    }
  }, []);

  // Find and fix: one problem on the part (K1), all of them (K4), asking (K2), before and after (K3).
  const fx = useFixController({ data, methods, qs, q, selCode: sel?.code ?? null, has3d, faceAligned, controller, xray, setXray, onOpen: () => setLens("make"), toast, sourceKept });
  const fixOn = !!fx.value.view && !checking;
  const ov = useOrientView(data.key);
  // A file of several bodies: body by body, each lit on the part.
  const bodies = useBodies(data, { sourceKept, qs, checking });
  const bodiesOn = !!bodies?.open && !fixOn;
  const highlight = fixOn ? fx.highlight : bodiesOn ? bodyHighlight(bodies, faceAligned) : lensHighlight;
  const pickLens = (l: Lens) => {
    if (fx.value.view) fx.value.close();
    bodies?.setOpen(false);
    setLens(l);
  };
  const openAllRef = React.useRef(fx.value.openAll);
  React.useEffect(() => {
    openAllRef.current = fx.value.openAll;
  });
  const problemCount = fx.value.set.problems.length;
  const fixSet = fx.value.set;

  const value: PartCtxValue = {
    data,
    session,
    methods,
    rows,
    qs,
    q,
    setQ,
    askedQty: asked != null && qs.length && !qs.includes(asked) ? asked : null,
    oq,
    setOq,
    lens,
    setLens: pickLens,
    sel,
    setSel: setSelCode,
    costPick,
    setCostPick,
    machinePick,
    setMachinePick,
    decidePick,
    setDecidePick,
    checking,
    interrupted,
    costOff,
    has3d,
    toast,
    turnTo: () => {
      setHint(false);
      controller.current?.turnToHighlight();
    },
    canTurn: has3d && !!highlight,
    patchData: (patch) => setData((d) => ({ ...d, ...patch })),
    recheck: onRecheck,
    canRecheck,
    retryPrices: onRetryPrices,
    pickFile: () => fileRef.current?.click(),
    openBodies: bodies ? () => bodies.setOpen(true) : null,
  };

  // Answers for the search palette, computed from this part's own results.
  const { setCurrentPart } = usePalette();
  React.useEffect(() => {
    if (!data.key) return;
    setCurrentPart({ label: data.fileName, href: R.part(data.key) });
  }, [data.key, data.fileName, setCurrentPart]);
  const views = React.useMemo(
    () => machineViews(data.machines, methods, data.cost, q, data.validation?.geometry.bounding_box_mm ?? data.cost?.geometry.bbox_mm ?? null),
    [data.machines, methods, data.cost, data.validation, q],
  );
  const paletteItems = React.useMemo<PaletteItem[]>(() => {
    if (!data.key || checking) return [];
    const src = `this part's check${data.decisionId ? `, record ${shortId(data.decisionId)}` : ""}`;
    const items: PaletteItem[] = [];
    for (const m of methods.filter((x) => x.verdict === "bad" && x.blockedReason)) {
      // The answer opens that problem on the part, for this process (K1).
      const pr = problemForIssue(fixSet, m.finding?.issue.code) ?? fixSet.problems.find((x) => x.blocks.includes(m.code)) ?? null;
      items.push({ id: `why-${m.code}`, group: "This part", label: `Why can't ${m.name.toLowerCase()} make it?`, sub: m.short, words: `${m.code} ${m.name} ${m.short} blocked can't cannot dfm`, answer: { text: m.blockedReason!, source: `DFM, ${src}` }, href: pr ? `${R.part(data.key)}?problem=${encodeURIComponent(pr.id)}&method=${encodeURIComponent(m.code)}` : `${R.part(data.key)}?lens=make` });
    }
    for (const qq of qs) {
      const c = cheapestAt(methods, qq);
      if (c) items.push({ id: `cheap-${qq}`, group: "This part", label: `Cheapest at ${qtyWord(qq)}`, words: `cost price quantity ${qq}`, answer: { text: `${c.name} · ${c.short} ${c.prices.get(qq)!.material}: ${money(priceAt(c, qq))} each`, source: `cost model, ${src}` }, href: `${R.part(data.key)}?lens=cost` });
    }
    if (views.length) {
      const can = views.filter((v) => v.tone === "ok");
      items.push({ id: "machines", group: "This part", label: "Which of my machines can make it?", words: "machine printer shop in-house", answer: { text: can.length ? can.map((v) => `${v.name}${v.cost != null ? ` (${money(v.cost)} at ${qtyWord(q)})` : ""}`).join(", ") : `None of your ${views.length} machines clears every check.`, source: `machine fit, ${src}` }, href: `${R.part(data.key)}?lens=shop` });
    }
    const d = data.cost?.decision;
    if (d?.tooling_process && d.crossover_qty) {
      items.push({ id: "crossover", group: "This part", label: `When does ${methodName(d.tooling_process).toLowerCase()} get cheaper?`, words: "crossover tooling mold molding payback", answer: { text: `From about ${qtyWord(Math.round(d.crossover_qty))} parts${d.tooling_dfm_ready ? "" : ", once the design passes its DFM"}.`, source: `cost model, ${src}` }, href: `${R.part(data.key)}?lens=cost` });
    }
    if (problemCount) items.push({ id: "problems", group: "This part", label: "All problems on this part", sub: `${problemCount} ranked by what fixing each makes possible, for every process or one`, words: "problems findings fix issues dfm wrong filter process fdm fff", run: () => openAllRef.current() });
    if (data.decisionId) items.push({ id: "breakdown", group: "This part", label: "Cost breakdown", sub: "Every line of the price, its source and rate", words: "workbench glass box should-cost drivers rates lines", href: wbHref("glass", data.key, { decision: data.decisionId }) });
    return items;
  }, [data.key, data.decisionId, data.cost, checking, methods, qs, views, q, problemCount, fixSet]);
  useRegisterPaletteItems("part", paletteItems);

  // HUD facts
  const v = data.validation;
  const g = v?.geometry;
  const bbox = g?.bounding_box_mm ?? data.cost?.geometry.bbox_mm ?? null;
  const { unit } = useUnits();
  const dims = bbox && bbox.length ? unitDims(bbox, unit) : dimsText(bbox);
  const faces = g?.faces ?? data.cost?.geometry.face_count ?? null;
  const cadFaces = g?.cad_faces ?? null;
  // Several closed bodies: their volume, and "4 closed bodies" rather than "not watertight".
  const bodiesClosed = !!bodies && bodies.pt.all_closed === true && !bodies.pt.provisional;
  const volume = bodiesClosed
    ? bodies!.pt.bodies.reduce((n, x) => n + x.volume_mm3, 0) / 1000
    : g ? g.volume_mm3 / 1000 : data.cost?.geometry.volume_cm3 ?? null;
  const watertight = g?.is_watertight ?? data.cost?.geometry.watertight ?? null;
  const tightWord = bodiesClosed ? `${bodies!.pt.body_count} closed bodies` : watertight == null ? null : watertight ? "watertight" : "not watertight";
  // While the picture is still on its way the header says so, not "unavailable".
  const pictureComing = !has3d && (mesh.loading || (!!mesh.url && viewer === "loading"));
  const hudMeta = interrupted
    ? "Not checked yet · 3D preview drawn from the file"
    : [dims, volume != null ? unitVolume(volume, unit) : null, tightWord, has3d ? (cadFaces ? `${cadFaces.toLocaleString("en-US")} faces, ${faces ? `${faces.toLocaleString("en-US")} mesh triangles` : "meshed"}` : faces ? `real shell, ${faces.toLocaleString("en-US")} mesh triangles` : "real shell") : pictureComing ? "3D view loading" : dims ? "measured size, 3D view unavailable" : null]
        .filter(Boolean)
        .join(" · ") || (checking ? "Measuring…" : "");
  const ctx = data.context;
  const annual = ctx?.resolved_annual_volume ?? ctx?.annual_volume ?? null;
  const revLine = revisionLine(revisions ?? null, data.decisionId ?? null);
  // The part's specs near the top, one tap from the Specs view (buyer-15: a buyer on a supplier's call
  // scrolled 1,800 px past sour gas and pressure fields to find the finish, and never found a tolerance).
  const specsLine = specLines(normalizeSpecs(ctx?.part_specs ?? null)).join(" · ");
  const hudCtx = [ctx?.program ? `Program ${ctx.program}` : "No program", ctx?.parent_assembly ? `in ${ctx.parent_assembly}` : "not in an assembly", annual ? `${qtyWord(annual)} a year` : "no yearly volume"].join(" · ");

  // Share opens the Share dialog: who, how long, what the supplier sees (never an instant link).
  const [sharing, setSharing] = React.useState(false);
  const share = () => {
    if (data.decisionId) setSharing(true);
  };
  const pdf = async () => {
    if (!data.decisionId) return;
    try {
      await downloadCostPdf(data.decisionId, data.fileName);
    } catch (e) {
      toast({ text: e instanceof Error ? e.message : "The PDF didn't download." });
    }
  };

  const li = LENSES.findIndex(([k]) => k === lens);
  const noModel = !mesh.url && !mesh.loading;
  // This check's own preview failed (the check still runs on the file): the shared X11 notice.
  const failedLive = !!mesh.error && !!onRetryPreview && !mesh.url && !mesh.loading && !onDropFile;
  const showNo3d = !interrupted && (noModel || viewer === "failed" || viewer === "nowebgl");
  const drop = (f: File | undefined | null) => {
    setOver(false);
    if (f && onDropFile) onDropFile(f);
  };
  const objLabel = fixOn && fx.value.problem ? `The part, ${fx.value.problem.title.toLowerCase()}. Drag, or use the arrow keys, to turn it.` : "The part. Drag, or use the arrow keys, to turn it.";
  if (fx.value.after)
    return (
      <PartProvider value={value}>
        <FixProvider value={fx.value}>
          <AfterFixView mesh={mesh} />
        </FixProvider>
      </PartProvider>
    );
  return (
    <PartProvider value={value}>
      <FixProvider value={fx.value}>
      <main className="world pv" aria-label={data.fileName}>
        <section className={cx("stage", showNo3d && "flat")} aria-label="The part">
          <div className="floor" />
          <div className="hud">
            {fixOn ? (
              <button className="khud-back" type="button" onClick={fx.value.close}>
                ‹ Ways to make it
              </button>
            ) : (
              <Link href={R.parts} style={{ fontSize: 12.5, textDecoration: "none", marginBottom: 2 }}>
                ‹ Parts
              </Link>
            )}
            <h1 title={data.fileName}>{data.fileName}</h1>
            <span className="num" style={{ display: "inline-flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              {hudMeta}
              {!interrupted && dims ? <UnitSwitch className="unit-switch" /> : null}
            </span>
            <span>
              {hudCtx}
              {data.key ? (
                <>
                  {" · "}
                  <Link href={R.partHistory(data.key)}>History{data.checks != null ? `, ${data.checks} ${data.checks === 1 ? "check" : "checks"}` : ""}</Link>
                </>
              ) : null}
            </span>
            {specsLine ? (
              <span className="specline" title={specsLine}>
                Specs:{" "}
                <a
                  className="speclink"
                  href="?lens=use"
                  onClick={(e) => {
                    e.preventDefault();
                    pickLens("use");
                  }}
                >
                  {specsLine}
                </a>
              </span>
            ) : null}
            {revLine ? (
              <span className="revline">
                {revLine.lead} <Link href={revLine.partHref}>{revLine.name}</Link>
                {revLine.compareHref ? (
                  <>
                    {" · "}
                    <Link href={revLine.compareHref}>Compare before and after</Link>
                  </>
                ) : null}
              </span>
            ) : null}
            {bodies ? <BodiesChip b={bodies} /> : null}
            <span className="chips">
              {data.key ? (
                <span
                  className="src s-file"
                  title={
                    sourceKept
                      ? `The exact file you uploaded is kept with the record, in your organization only. File fingerprint (SHA-256): ${data.key}.`
                      : `File fingerprint (SHA-256 of the uploaded file): ${data.key}.`
                  }
                >
                  {sourceKept ? "Source file kept with the record" : "File fingerprint"} <span className="fp" style={{ marginLeft: 4 }}>{data.key.slice(0, 8)}</span>
                </span>
              ) : null}
              <RatesChip />
              <OrientChip />
              {mesh.origin === "cache" && has3d ? <span className="src s-typ">3D from this browser&apos;s copy</span> : null}
              {mesh.origin === "stored" && has3d ? <span className="src s-typ">3D from the kept source file</span> : null}
            </span>
          </div>

          <div className="ptools">
            <button className={cx("btn sm", xray && "ink")} type="button" aria-pressed={xray} aria-disabled={!has3d} title={has3d ? "See through the part" : "X-ray needs the 3D view"} onClick={() => has3d && setXray((x) => !x)} style={!has3d ? { opacity: 0.45, cursor: "default" } : undefined}>
              X-ray
            </button>
            <OrientTool />
            <Link className="btn sm" href={R.fit} title="Load the assembly around this part to measure interference and clearance">
              Fit in assembly
            </Link>
            <button className="btn sm" type="button" onClick={share} disabled={!data.decisionId} title={data.decisionId ? "A view-only link for a supplier: you pick how long and what they see" : "Saved records only"}>
              Share
            </button>
            <button className="btn sm" type="button" onClick={() => void pdf()} disabled={!data.decisionId} title={data.decisionId ? "The record as a PDF" : "Saved records only"}>
              Export PDF
            </button>
            {data.key && !checking ? <DeletePartButton partKey={data.key} fileName={data.fileName} label="Delete" onDeleted={() => router.push(R.parts)} /> : null}
          </div>

          <UseLayer />
          <CostLayer />
          <ShopLayer />

          {!showNo3d ? (
            <button
              type="button"
              className={cx("obj", `l-${lens}`, xray && "xray")}
              aria-label={objLabel}
              onPointerDown={() => setHint(false)}
              onKeyDown={(e) => {
                const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
                if (!step) return;
                e.preventDefault();
                setHint(false);
                controller.current?.turnBy((step * Math.PI) / 18);
              }}
            >
              <span className="shade" />
              {mesh.url ? <PartViewer url={mesh.url} kind={mesh.kind} highlight={highlight} xray={xray} controllerRef={controller} onState={setViewer} markers={fixOn ? fx.markers : undefined} onPin={fx.onPin} onLit={fx.onLit} orient={ov.orient} onFacePick={ov.onFacePick} /> : null}
              {checking || mesh.loading ? <span className="scan" /> : null}
              {fixOn && fx.value.view?.kind === "problem" && has3d && fixHint(fx.value.pin, "problem", "1") ? (
                <span className="hint">{fixHint(fx.value.pin, "problem", "1")}</span>
              ) : (
                <span className={cx("hint", (!hint || lens !== "make" || checking || !has3d || fixOn) && "gone")}>Drag to turn it</span>
              )}
            </button>
          ) : (
            <div
              className={cx("no3d swap", `l-${lens}`, over && "over")}
              onDragEnter={(e) => {
                if (!onDropFile) return;
                e.preventDefault();
                setOver(true);
              }}
              onDragOver={(e) => {
                if (!onDropFile) return;
                e.preventDefault();
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false);
              }}
              onDrop={(e) => {
                if (!onDropFile) return;
                e.preventDefault();
                drop(e.dataTransfer?.files?.[0]);
              }}
            >
              <svg width="150" height="110" viewBox="0 0 150 110" aria-hidden="true">
                <path d="M20 40 L75 14 L130 40 L130 78 L75 104 L20 78 Z M20 40 L75 66 L130 40 M75 66 L75 104" fill="none" stroke="#9AA3AE" strokeWidth="1.5" strokeDasharray="4 4" strokeLinejoin="round" />
              </svg>
              <b>{no3dTitle(viewer, mesh)}</b>
              <span>Every answer <span className="on-desk">on the right</span><span className="on-phone">below</span> still holds; they come from the file, not the picture.</span>
              {dims ? <span className="num">Measured size {dims}</span> : null}
              {mesh.error ? <span className="err" role="alert">{mesh.error}</span> : null}
              {failedLive && onRetryPreview ? (
                <PreviewFailed onRetry={onRetryPreview} onChooseFile={shell.pickFile} />
              ) : onDropFile ? (
                <>
                  <span>Drop the file to see it in 3D. It must be the same file, and it doesn&apos;t use a check.</span>
                  <span style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                    <button className="btn sm" type="button" onClick={() => fileRef.current?.click()}>
                      Choose the file
                    </button>
                    {retryPreview}
                  </span>
                </>
              ) : (
                retryPreview
              )}
            </div>
          )}
          <input
            ref={fileRef}
            type="file"
            accept={CAD_ACCEPT}
            aria-label="Choose this part's CAD file"
            tabIndex={-1}
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              drop(f);
            }}
          />

          <DecideTicket />
          {fixOn ? <FixStage has3d={has3d} /> : null}

          {toastState ? (
            <div className="toast ptoast" role="status">
              <span>{toastState.text}</span>
              {toastState.link ? (
                <Link href={toastState.link.href} style={{ marginLeft: "auto" }}>
                  {toastState.link.label}
                </Link>
              ) : null}
              {toastState.sticky ? (
                <button type="button" className="btn sm ghost" onClick={() => setToastState(null)} aria-label="Dismiss" style={{ marginLeft: toastState.link ? 0 : "auto" }}>
                  Dismiss
                </button>
              ) : null}
            </div>
          ) : null}
          {sharing && data.decisionId ? (
            <ShareDialog
              target={{ kind: "record", id: data.decisionId, name: data.fileName }}
              loadPart={() => partFacts(data.decisionId as string)}
              create={(link) => shareRecord(data.decisionId as string, link)}
              onMade={(m) => toast({ text: madeText(m.share_expires_at), link: { label: "Share links", href: R.links }, sticky: true })}
              onClose={() => setSharing(false)}
            />
          ) : null}
        </section>
        {fixOn ? <FixStage has3d={has3d} part="key" /> : null}

        <aside className="sheet" aria-label="The answer">
          {fixOn && fx.value.view?.kind === "problem" ? (
            <ProblemSheet />
          ) : fixOn && fx.value.view?.kind === "all" ? (
            <AllProblemsSheet />
          ) : bodiesOn && bodies ? (
            <BodiesSheet b={bodies} qs={qs} aligned={faceAligned} has3d={has3d} />
          ) : lens === "make" ? (
            <MakeSheet />
          ) : lens === "cost" ? (
            <CostSheet />
          ) : lens === "use" ? (
            <UseSheet />
          ) : lens === "shop" ? (
            <ShopSheet />
          ) : (
            <DecideSheet />
          )}
          {fixOn || bodiesOn ? null : <AskDock />}
        </aside>

        <nav className="dial" aria-label="Questions about this part">
          <span className="ind" style={{ transform: `translateX(${li * 100}%)` }} aria-hidden="true" />
          {LENSES.map(([k, label, sub]) => (
            <button key={k} type="button" className={cx(k === lens && !bodiesOn && "on")} aria-pressed={k === lens && !bodiesOn} onClick={() => pickLens(k)}>
              {label}
              <small>{sub}</small>
            </button>
          ))}
        </nav>
        {overlay}
        {fx.value.ask ? <AskDialog file={file} /> : null}
      </main>
      </FixProvider>
    </PartProvider>
  );
}
