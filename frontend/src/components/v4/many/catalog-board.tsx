"use client";

/**
 * A catalog run's board (boards M1 + M2, for the catalog run): every part
 * sorted into make in-house / buy outside / needs a new machine / can't be
 * made as drawn, each with its one-line reason, then machine time, material
 * and ownership, and the price last. Totals per bucket. Filter, sort, search;
 * any part opens its own page in one click (its record and kept file, no
 * re-upload). CSV, a summary to print or save as PDF, and a link for the
 * organization. While the run goes, parts arrive one by one; the run keeps
 * going if this page is left or closed (the work bar shows it everywhere).
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cancelBatch, getBatchProgress, type BatchProgress } from "@/lib/api/batch";
import { R } from "../routes";
import { Content, Empty, Fig, Figs, Loading, PageHead, Panel, Sheet, cx } from "../ui";
import { markWorkSeen, registerWork, runKey } from "../work/work-bar";
import { ConfirmDialog, ManyWorld, Thumb, errorText, saveBlob, useManyTabs, useToast, whenLabel } from "./common";
import { etaText, runCounts, runCountsLine, runWork, stoppedLine } from "./batch-model";
import { ReadOnlyLine, useReadOnly } from "../read-only";
import { CatalogRunError, downloadBoardCsv, fetchBoard, inviteToRun, recheckParts } from "./catalog-api";
import { runSummaryHref } from "./catalog-routes";
import { AccuracyPanel } from "../validation/accuracy-panel";
import { reportHref } from "../validation/routes";
import {
  BUCKETS,
  OTHER,
  SORTS,
  answerText,
  boardProgress,
  compareLine,
  countLine,
  machinesText,
  recheckable,
  recheckStarted,
  recheckTrouble,
  rowName,
  runTitle,
  runningRateLines,
  scopedRows,
  unlistedRows,
  breakdownOf,
  bucketCount,
  bucketDef,
  capabilityGroups,
  filterRows,
  hoursText,
  machineLine,
  massText,
  materialLine,
  materialWord,
  money,
  partLine,
  rowWords,
  procName,
  sortRows,
  totalsText,
  type Board,
  type BoardMachine,
  type BoardRow,
  type BucketBreakdown,
  type BucketTotal,
  type SortKey,
} from "./catalog-model";
import "./catalog.css";
import { rowMustHold, rowSignoffLine, rowSpecLine } from "./row-specs";
import { useUnits } from "../units/use-units";
import { inText } from "../units/units";

const POLL_MS = 4000;
const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function useBoard(batchId: string) {
  const [board, setBoard] = React.useState<Board | null>(null);
  const [progress, setProgress] = React.useState<BatchProgress | null>(null);
  const [err, setErr] = React.useState<{ msg: string; status: number } | null>(null);
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const run = async () => {
      try {
        // The progress read only adds the start time for the ETA; it never holds up the board.
        const progressRead = Promise.race([getBatchProgress(batchId).catch(() => null), new Promise<null>((res) => setTimeout(() => res(null), 10_000))]);
        const [b, p] = await Promise.all([fetchBoard(batchId), progressRead]);
        if (!live) return;
        setBoard(b);
        if (p) setProgress(p);
        setErr(null);
        if (!TERMINAL.has(b.status) || boardProgress(b).checking > 0) timer = setTimeout(run, POLL_MS);
      } catch (e) {
        if (!live) return;
        const status = (e as { status?: number }).status ?? 0;
        setErr({ msg: errorText(e, "The board didn’t load."), status });
        if (status !== 404 && status !== 403) timer = setTimeout(run, POLL_MS * 2);
      }
    };
    void run();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [batchId, tick]);
  return { board, progress, err, reload: () => setTick((t) => t + 1) };
}

export function CatalogBoard({ batchId }: { batchId: string }) {
  const { board, progress, err, reload } = useBoard(batchId);
  // Lengths in the engine's words (walls, sizes, work areas) read in the person's unit.
  const { unit } = useUnits();
  const tabs = useManyTabs();
  const [toastNode, toast] = useToast();
  const [bucket, setBucket] = React.useState<string>("all");
  const [sort, setSort] = React.useState<SortKey>("bucket");
  const [query, setQuery] = React.useState("");
  const [csvBusy, setCsvBusy] = React.useState(false);
  const [asking, setAsking] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const [rechecking, setRechecking] = React.useState<Set<string>>(() => new Set());
  // Why the last "Check again" was refused, kept on the board until the next try.
  const [recheckErr, setRecheckErr] = React.useState<{ code: string | null; message: string } | null>(null);
  const searchId = React.useId();
  const sortId = React.useId();

  const status = board?.status ?? progress?.status ?? null;
  const running = status != null && !TERMINAL.has(status);
  const prog = boardProgress(board);
  // One count of the run's files everywhere (this page, its side panel, the work bar).
  const counts = runCounts(progress, board?.rows);
  const work = runWork(counts);
  // A viewer sees the run; checking parts again or cancelling it is a member's.
  const readOnly = useReadOnly("check parts again or cancel a run");

  // On its own page the run needs no bar; once it has finished here, it's been seen.
  React.useEffect(() => {
    if (!board) return;
    if (!TERMINAL.has(board.status)) {
      registerWork({ key: runKey(batchId), href: R.batch(batchId), persist: true, state: "running", label: work.label, detail: work.detail, progress: work.progress });
    } else markWorkSeen(runKey(batchId));
  }, [board, batchId, work.label, work.detail, work.progress]);

  if (err && !board) {
    return (
      <ManyWorld label="Catalog run">
        <PageHead title="Catalog run" meta={[<span key="i" className="mono">{batchId}</span>]} tabs={tabs} tabsLabel="Many parts" wide />
        <Content full>
          <Panel>
            <Empty
              title={err.status === 404 ? "This run isn’t available" : "The board didn’t load"}
              actions={
                err.status === 404 ? (
                  <Link className="btn sm" href={R.many}>
                    Back to batches
                  </Link>
                ) : (
                  <button className="btn sm" type="button" onClick={reload}>
                    Try again
                  </button>
                )
              }
            >
              {err.status === 404 ? "It may belong to another organization, or the link is wrong." : `Saved results are unchanged. ${err.msg}`}
            </Empty>
          </Panel>
        </Content>
      </ManyWorld>
    );
  }

  // With a parts list, the answer and the table are the list's parts; the rest is shown apart.
  const rows = scopedRows(board);
  const apart = unlistedRows(board);
  const shown = sortRows(filterRows(rows, bucket, query), sort);
  const total = rows.length;
  const nMachines = board?.machines.length ?? null;
  const sel = bucket !== "all" ? bucketDef(bucket) : null;
  const failed = recheckable(board);
  const trouble = recheckTrouble(recheckErr);
  const answer = answerText(board);
  const rates = runningRateLines(board);

  const recheck = async (ids?: string[]) => {
    const keys = ids ?? failed.map((r) => r.item_id);
    if (!keys.length) return;
    setRechecking((cur) => new Set([...cur, ...keys]));
    setRecheckErr(null);
    try {
      const res = await recheckParts(batchId, ids);
      toast(recheckStarted(res));
      reload();
    } catch (e) {
      const message = errorText(e, "The parts weren’t checked again.");
      setRecheckErr({ code: e instanceof CatalogRunError ? e.code : null, message });
      toast(message);
    } finally {
      setRechecking((cur) => {
        const next = new Set(cur);
        for (const k of keys) next.delete(k);
        return next;
      });
    }
  };

  const csv = async () => {
    if (csvBusy) return;
    setCsvBusy(true);
    try {
      saveBlob(await downloadBoardCsv(batchId), `catalog_run_${batchId}.csv`);
      toast(`Downloaded catalog_run_${batchId}.csv`);
    } catch (e) {
      toast(errorText(e, "The CSV didn’t download."));
    } finally {
      setCsvBusy(false);
    }
  };
  const copyLink = async () => {
    const url = `${window.location.origin}${R.batch(batchId)}`;
    try {
      await navigator.clipboard.writeText(url);
      toast("Link copied. Anyone in your organization can open it.");
    } catch {
      toast(url);
    }
  };
  const doCancel = async () => {
    setCancelling(true);
    try {
      await cancelBatch(batchId);
      toast("Run cancelled. Parts already checked stay; the rest are skipped.");
      setAsking(false);
      reload();
    } catch (e) {
      toast(errorText(e, "The run wasn’t cancelled."));
      setAsking(false);
    } finally {
      setCancelling(false);
    }
  };

  const statusWord = status ? (running ? "Running" : status === "completed" ? "Finished" : status[0].toUpperCase() + status.slice(1)) : null;
  const meta: React.ReactNode[] = [
    <span key="n" className="num">
      {board ? countLine(board) : "Loading"}
    </span>,
    machinesText(board),
    board?.material_class ? materialWord(board.material_class) : null,
    board ? `${board.quantity.toLocaleString("en-US")} a year each unless listed` : null,
    statusWord && board ? `${statusWord} · ${board.free ? "free run" : "pilot plan"}` : statusWord,
  ].filter(Boolean);

  return (
    <ManyWorld label="Catalog run">
      <PageHead
        title={runTitle(board)}
        meta={meta}
        tabs={tabs}
        tabsLabel="Many parts"
        tabsCurrent={R.many}
        tabsAside={
          <span className="cr-head">
            <button className="btn sm" type="button" onClick={() => void csv()} disabled={csvBusy || !board}>
              {csvBusy ? "Downloading…" : "CSV"}
            </button>
            <Link className="btn sm" href={runSummaryHref(batchId)}>
              Summary to print
            </Link>
            <Link className="btn sm" href={reportHref(batchId)}>
              Pilot report
            </Link>
            <button className="btn sm" type="button" onClick={() => void copyLink()}>
              Copy link
            </button>
          </span>
        }
      />
      <Content>
        {!board ? (
          <Loading rows={4} label="Loading the board" />
        ) : (
          <>
            {nMachines === 0 ? (
              <div className="panel cr-note" role="note">
                <b>No machines to sort against</b>
                <span>Every part lands in Not sorted until your machines are in Your shop. A machine from the catalog, added as it is, can already say yes; then check the parts again.</span>
                <span>
                  <Link className="btn sm ink" href={`${R.shop}?add=1`}>
                    Add machines
                  </Link>
                </span>
              </div>
            ) : null}

            {answer && (TERMINAL.has(board.status) || total > 0) ? (
              <section className="panel cr-ans" aria-label="The answer">
                <h2>{answer.head}</h2>
                <p className="cr-ans-sub num">{answer.sub}</p>
                {answer.missing ? <p className="cr-ans-miss">{answer.missing}</p> : null}
                {board.bucket_rule ? <p className="cr-ans-rule">{board.bucket_rule}</p> : null}
                {rates.length ? (
                  <details className="cr-ans-rate">
                    <summary>Running rate: what your machines cost an hour here</summary>
                    <p>A machine you own is already paid for, so its time is priced at the hourly rate you set less the share that pays for the machine itself. Each part’s machine cost also carries utilization and margin; a machine’s cycle doesn’t learn, so the learning curve is on the hand work only.</p>
                    <ul>
                      {rates.map((l) => (
                        <li key={l}>{l}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </section>
            ) : null}

            {failed.length && !running ? (
              <div className="panel cr-note cr-again" role="note">
                <b>
                  {board.status === "failed"
                    ? stoppedLine(counts, stopTime(board.completed_at))
                    : `${failed.length} ${failed.length === 1 ? "part wasn’t" : "parts weren’t"} checked`}
                </b>
                {stopReason(board) ? <span>{stopReason(board)}</span> : null}
                <span>{failed.length === 1 ? "It goes" : "They go"} back in this run at {failed.length === 1 ? "its" : "their"} listed quantity and land on {failed.length === 1 ? "its own row" : "their own rows"}.</span>
                <span>
                  <button className="btn sm ink" type="button" onClick={() => void recheck()} disabled={rechecking.size > 0 || !!readOnly} title={readOnly ?? undefined}>
                    {rechecking.size ? "Starting…" : `Check ${failed.length === 1 ? "it" : `all ${failed.length}`} again`}
                  </button>
                </span>
                <ReadOnlyLine line={readOnly} />
              </div>
            ) : null}

            {trouble ? (
              <div className="panel cr-note cr-again" role="alert">
                <b>{trouble.title}</b>
                <span>{trouble.body}</span>
                {trouble.offerList ? (
                  <span>
                    <button className="btn sm ink" type="button" onClick={() => void csv()} disabled={csvBusy}>
                      {csvBusy ? "Downloading…" : "Download the parts list (CSV)"}
                    </button>
                  </span>
                ) : null}
              </div>
            ) : null}

            {running || prog.checking ? (
              <div className="panel prog cr-prog" aria-live="polite">
                <span className="st">Running</span>
                <span className="num">{runCountsLine(counts)}</span>
                <span className="pb" aria-hidden="true">
                  <i style={{ transform: `scaleX(${work.progress ?? 0})` }} />
                </span>
                <span className="num">{progress ? etaText(progress, Date.now(), ["part", "parts"]) : ""}</span>
                <span className="act">
                  Keeps going if you leave or close this page. The bar at the foot of every page brings you back, and you get a notification when it finishes or stops.
                  {running && !readOnly ? (
                    <>
                      {" "}
                      <button className="lk" type="button" onClick={() => setAsking(true)}>
                        Cancel run
                      </button>
                    </>
                  ) : null}
                </span>
              </div>
            ) : null}

            <section className="panel" aria-label="Buckets">
              <div className="bk4 cr-bk" role="group" aria-label="Show parts">
                <button type="button" className={cx("bk", bucket === "all" && "on")} aria-pressed={bucket === "all"} onClick={() => setBucket("all")}>
                  <b className="num">{total}</b>
                  <span>All parts</span>
                  <small>{prog.checking ? `${prog.checking} still checking` : "Sorted below"}</small>
                </button>
                {BUCKETS.map((d) => (
                  <button key={d.key} type="button" className={cx("bk", bucket === d.key && "on")} aria-pressed={bucket === d.key} onClick={() => setBucket((b) => (b === d.key ? "all" : d.key))}>
                    <b className="num">{bucketCount(board, d.key)}</b>
                    <span>
                      <i style={{ background: d.color }} />
                      {d.label}
                    </span>
                    <small className="num">{totalsText(board.totals[d.key]) || d.note}</small>
                  </button>
                ))}
              </div>
              <div className={cx("bbar", !total && "empty")} role="img" aria-label={BUCKETS.map((d) => `${bucketCount(board, d.key)} ${d.label.toLowerCase()}`).join(", ")}>
                {[...BUCKETS, ...OTHER].map((d) => {
                  const n = bucketCount(board, d.key);
                  return n ? (
                    <i key={d.key} style={{ flex: `${n} 1 0`, background: d.color }}>
                      {n}
                    </i>
                  ) : null;
                })}
              </div>
              <div className="hon">
                {OTHER.map((d) => (
                  <button key={d.key} type="button" aria-pressed={bucket === d.key} onClick={() => setBucket((b) => (b === d.key ? "all" : d.key))}>
                    {d.label} <b className="num">{bucketCount(board, d.key)}</b>
                  </button>
                ))}
                <span>
                  Buckets sum to <b className="num">{total}</b>
                  {apart.length ? ` · ${apart.length} not on your parts list, below` : ""}
                </span>
              </div>
            </section>

            <Panel title={sel ? sel.label : "Parts"} note={`${shown.length} of ${total}`}>
              <div className="cr-tools">
                <label className="cr-find" htmlFor={searchId}>
                  <span className="sr">Find a part</span>
                  <input id={searchId} type="search" placeholder="Find a part, number or machine" value={query} onChange={(e) => setQuery(e.target.value)} />
                </label>
                <label className="cr-sort" htmlFor={sortId}>
                  Sort by
                  <select id={sortId} value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
                    {SORTS.map(([k, l]) => (
                      <option key={k} value={k}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {shown.length === 0 ? (
                <Empty
                  title={total === 0 ? "No parts yet" : `No parts in ${sel ? sel.label.toLowerCase() : "this view"}`}
                  actions={
                    bucket !== "all" || query ? (
                      <button
                        className="btn sm"
                        type="button"
                        onClick={() => {
                          setBucket("all");
                          setQuery("");
                        }}
                      >
                        Show all
                      </button>
                    ) : undefined
                  }
                >
                  {total === 0 ? "Parts appear here one by one as they’re checked." : sel ? sel.note : "Nothing matches."}
                </Empty>
              ) : (
                <div className="cr-wrap">
                  <table className="cr-t">
                    <thead>
                      <tr>
                        <th scope="col">Part</th>
                        <th scope="col">Machine time</th>
                        <th scope="col">Material</th>
                        <th scope="col">Ownership</th>
                        <th scope="col" className="r">
                          Price
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((r) => (
                        <PartRow key={r.item_id} r={r} machines={board.machines} onRecheck={() => void recheck([r.item_id])} rechecking={rechecking.has(r.item_id)} readOnly={readOnly} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="tfoot" style={{ padding: "0 8px 10px" }}>
                <span>Machine time, material and prices are model estimates from your machines and rates, not quotes; a current price is yours. Material is what the route uses (stock, printed material with supports), with the part’s own mass beside it when that differs. Open a part for its sources.</span>
              </p>
            </Panel>

            {apart.length ? (
              <Panel title="Not on your parts list" note={`${apart.length}`}>
                <p className="cr-p0">Files in the ZIP the parts list doesn’t name. Checked at the run’s quantity and material, and kept out of the answer and the totals above.</p>
                <div className="cr-wrap">
                  <table className="cr-t">
                    <thead>
                      <tr>
                        <th scope="col">Part</th>
                        <th scope="col">Machine time</th>
                        <th scope="col">Material</th>
                        <th scope="col">Ownership</th>
                        <th scope="col" className="r">
                          Price
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortRows(apart, sort).map((r) => (
                        <PartRow key={r.item_id} r={r} machines={board.machines} onRecheck={() => void recheck([r.item_id])} rechecking={rechecking.has(r.item_id)} readOnly={readOnly} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            ) : null}

            {TERMINAL.has(board.status) ? <AccuracyPanel run={batchId} compact /> : null}

            {board.split_files?.length ? (
              <Panel title="Files with several bodies" note={`${board.split_files.length}`}>
                <div className="kv cr-un">
                  {board.split_files.map((f) => (
                    <React.Fragment key={f.filename}>
                      <span>
                        {f.part_key ? <Link href={R.part(f.part_key)}>{f.filename}</Link> : f.filename}
                        <small> · {inText(f.summary, unit)}</small>
                      </span>
                      <b className="num">
                        {f.rows} {f.rows === 1 ? "row" : "rows"}
                      </b>
                    </React.Fragment>
                  ))}
                </div>
                <p className="tfoot" style={{ padding: "0 8px 10px" }}>
                  <span>Each body shape is a part on the board, at the file’s quantity times its copies. A file counts as one part of the run’s allowance, however many bodies it holds. A weldment’s members are cut stock: welding isn’t priced yet.</span>
                </p>
              </Panel>
            ) : null}

            {board.unmatched.length ? (
              <Panel title="In the parts list, no file in the run" note={`${board.parts_list?.unmatched ?? board.unmatched.length}`}>
                <div className="kv cr-un">
                  {board.unmatched.slice(0, 50).map((u, i) => (
                    <React.Fragment key={i}>
                      <span>
                        {u.part_number ?? u.file}
                        {u.row ? <small> · row {u.row}</small> : null}
                      </span>
                      <b className="num">{[u.quantity ? `${u.quantity.toLocaleString("en-US")} each` : null, u.material].filter(Boolean).join(" · ") || "—"}</b>
                    </React.Fragment>
                  ))}
                </div>
                <p className="tfoot" style={{ padding: "0 8px 10px" }}>
                  <span>No file means no check. Add their STEP, STL or IGES files to a run to sort them.</span>
                </p>
              </Panel>
            ) : null}
          </>
        )}
      </Content>

      <Sheet label="This run">
        <RunSheet board={board} bucket={bucket} onBucket={setBucket} progress={progress} onCsv={() => void csv()} csvBusy={csvBusy} onCopy={() => void copyLink()} batchId={batchId} />
      </Sheet>
      {asking && running ? (
        <ConfirmDialog
          title="Cancel this run?"
          text="Parts not checked yet are skipped and give their free slots back. Parts already checked stay. This can’t be undone."
          keepLabel="Keep running"
          confirmLabel="Cancel run"
          busy={cancelling}
          onKeep={() => setAsking(false)}
          onConfirm={() => void doCancel()}
        />
      ) : null}
      {toastNode}
    </ManyWorld>
  );
}

function PartRow({ r, machines, onRecheck, rechecking, readOnly }: { r: BoardRow; machines?: BoardMachine[]; onRecheck?: () => void; rechecking?: boolean; readOnly?: string | null }) {
  const router = useRouter();
  const { unit } = useUnits();
  const d = bucketDef(r.bucket);
  const line = partLine(r, machines ?? []);
  // The engine's words (reason, body, spec line, withheld price, note) in the person's unit.
  const words = rowWords(r, unit, rowSpecLine(r));
  const href = r.part_key ? R.part(r.part_key) : null;
  const sub = (s: string) => {
    const i = s.indexOf(" · ");
    return i > 0 ? [s.slice(0, i), s.slice(i + 3)] : [s, ""];
  };
  const [t1, t2] = sub(line.time);
  const [m1, m2] = sub(line.material);
  const [o1, o2] = sub(line.ownership);
  const [p1, p2] = sub(words.price);
  const sign = rowSignoffLine(r);
  const name = rowName(r);
  const compare = compareLine(r);
  return (
    <tr
      className={cx("cr-r", href && "click")}
      data-bucket={r.bucket}
      onClick={(e) => {
        if (!href || (e.target as HTMLElement).closest("a,button")) return;
        router.push(href);
      }}
    >
      <td className="cr-pc">
        <div className="cr-p">
        <Thumb name={r.body?.file ?? r.filename} />
        <span className="cr-pt">
          {href ? (
            <Link href={href} className="cr-name" title={name}>
              {name}
            </Link>
          ) : (
            <b className="cr-name" title={name}>
              {name}
            </b>
          )}
          {r.part_number || r.description ? (
            <small>
              {r.part_number ? <span className="mono">{r.part_number}</span> : null}
              {r.part_number && r.description ? " · " : null}
              {r.description}
            </small>
          ) : null}
          <span className="cr-why">
            <i style={{ background: d.color }} aria-hidden="true" />
            <span className="sr">{d.label}: </span>
            {words.reason ?? d.label}
          </span>
          {words.body ? <small className="cr-spec">{words.body}</small> : null}
          {words.spec ? <small className="cr-spec">{words.spec}</small> : null}
          {rowMustHold(r) ? <small className="cr-spec">{rowMustHold(r)}</small> : null}
          {sign ? <small className={cx("cr-sign", sign.tone)}>{sign.text}</small> : null}
          {compare ? <small className="cr-cmp num">{compare}</small> : null}
          {words.note ? <small className="cr-warn">{words.note}</small> : null}
          {r.bucket === "not_checked" && onRecheck ? (
            <span className="cr-again-row">
              <button className="btn sm" type="button" onClick={onRecheck} disabled={rechecking || !!readOnly} title={readOnly ?? undefined}>
                {rechecking ? "Starting…" : "Check again"}
              </button>
            </span>
          ) : null}
        </span>
        </div>
      </td>
      <td data-k="Machine time" className={cx(t1 === "—" && "nil")}>
        <b className="num">{t1}</b>
        {t2 ? <small className="num">{t2}</small> : null}
      </td>
      <td data-k="Material" className={cx(m1 === "—" && "nil")}>
        <b>{m1}</b>
        {m2 ? <small className="num">{m2}</small> : null}
      </td>
      <td data-k="Ownership" className={cx(o1 === "—" && "nil")}>
        <b>{o1}</b>
        {o2 ? <small>{o2}</small> : null}
      </td>
      <td className={cx("r", p1 === "—" && !r.cheaper_outside && "nil")} data-k="Price">
        <b className="num">{p1}</b>
        {p2 ? <small className="num">{p2}</small> : null}
        {!compare && r.cheaper_outside ? (
          <small title={`Cheaper outside by ${procName(r.cheaper_outside.process).toLowerCase()}`}>
            Outside {money(r.cheaper_outside.unit_cost_usd)} · {procName(r.cheaper_outside.process).toLowerCase()}
          </small>
        ) : null}
      </td>
    </tr>
  );
}

function RunSheet({
  board,
  bucket,
  onBucket,
  progress,
  onCsv,
  csvBusy,
  onCopy,
  batchId,
}: {
  board: Board | null;
  bucket: string;
  onBucket: (b: string) => void;
  progress: BatchProgress | null;
  onCsv: () => void;
  csvBusy: boolean;
  onCopy: () => void;
  batchId: string;
}) {
  const { unit } = useUnits();
  if (!board) return <Loading rows={4} label="Loading this run" />;
  const sel = bucket !== "all" ? bucketDef(bucket) : null;
  const scoped = scopedRows(board);
  const total = scoped.length;
  const prog = boardProgress(board);
  const selRows = sel ? scoped.filter((r) => r.bucket === bucket) : [];
  const inHouse = scoped.filter((r) => r.bucket === "in_house");
  const ihB = breakdownOf(board, "in_house");
  const outB = breakdownOf(board, "outside");
  const selB = sel ? breakdownOf(board, bucket) : null;
  const groups = capabilityGroups(scoped);
  const t = board.totals;
  return (
    <>
      <div className="top">
        <h2 className="stitle">{sel ? sel.label : "This run"}</h2>
        <p className="smeta">
          {sel
            ? `${selRows.length} of ${total} parts · ${sel.note}`
            : `${runCountsLine(runCounts(progress, board.rows))}${progress?.started_at ? ` · started ${whenLabel(progress.started_at)}` : ""}`}
        </p>
        {!sel ? (
          <Figs>
            <Fig k="In-house" v={String(bucketCount(board, "in_house"))} sub={`of ${total}`} tone="ok" />
            <Fig k="Outside" v={String(bucketCount(board, "outside"))} />
            <Fig k="New machine" v={String(bucketCount(board, "new_machine"))} tone={bucketCount(board, "new_machine") ? "warn" : undefined} />
            <Fig k="Can’t make" v={String(bucketCount(board, "cant_make"))} tone={bucketCount(board, "cant_make") ? "bad" : undefined} />
          </Figs>
        ) : null}
      </div>
      <div className="scroll swap" key={bucket}>
        {!sel ? (
          <>
            <div className="gh">
              <span>Made in-house</span>
              <span>at each part’s quantity</span>
            </div>
            {inHouse.length ? (
              <>
                <Resources t={t.in_house} b={ihB} />
                <div className="kv">
                  <span>At your machines’ running rates</span>
                  <b className="num">{money(t.in_house?.cost_usd, 0)}</b>
                </div>
              </>
            ) : (
              <p className="cr-p0">{prog.checking ? "None yet." : "No part fits one of your machines."}</p>
            )}
            {groups.length ? (
              <>
                <div className="gh" style={{ marginTop: 6 }}>
                  <span>What a new machine needs</span>
                  <span>parts</span>
                </div>
                <div className="kv">
                  {groups.slice(0, 6).map((g) => (
                    <React.Fragment key={g.key}>
                      <span>{inText(g.text, unit)}</span>
                      <b className="num">{g.rows.length}</b>
                    </React.Fragment>
                  ))}
                </div>
                <p className="cr-p0">No machine prices in ScaleCAD: these are the capabilities missing, not quotes.</p>
              </>
            ) : null}
            <div className="gh" style={{ marginTop: 6 }}>
              <span>Buy outside</span>
              <span>at each part’s quantity</span>
            </div>
            <div className="kv">
              <span>Parts</span>
              <b className="num">{bucketCount(board, "outside")}</b>
            </div>
            {bucketCount(board, "outside") ? <Resources t={t.outside} b={outB} /> : null}
            <div className="kv">
              <span>At the buy prices</span>
              <b className="num">{money(t.outside?.cost_usd, 0)}</b>
            </div>
            <div className="gh" style={{ marginTop: 6 }}>
              <span>Export and share</span>
              <span />
            </div>
            <div className="cr-acts">
              <button className="btn sm" type="button" onClick={onCsv} disabled={csvBusy}>
                {csvBusy ? "Downloading…" : "Download CSV"}
              </button>
              <Link className="btn sm" href={runSummaryHref(batchId)}>
                Summary to print or save as PDF
              </Link>
              <button className="btn sm" type="button" onClick={onCopy}>
                Copy link
              </button>
            </div>
            <p className="cr-p0">The link opens for people in your organization. Catalog runs have no public link: they name your machines and rates.</p>
            <InviteToRun batchId={batchId} />
          </>
        ) : (
          <>
            {selRows.length && selB ? (
              <>
                <Resources t={t[bucket]} b={selB} />
                <div className="kv">
                  <span>{bucket === "in_house" ? "At your machines’ running rates" : "At the buy prices"}</span>
                  <b className="num">{money(t[bucket]?.cost_usd, 0)}</b>
                </div>
              </>
            ) : (
              <Empty title={`No parts in ${sel.label.toLowerCase()}`}>{sel.note}</Empty>
            )}
            {bucket === "new_machine" && groups.length ? (
              <>
                <div className="gh">
                  <span>Missing capability</span>
                  <span>parts</span>
                </div>
                {groups.map((g) => (
                  <div key={g.key} className="cr-cap">
                    <b>{inText(g.text, unit)}</b>
                    <span>
                      {g.rows
                        .slice(0, 4)
                        .map((r) => r.filename)
                        .join(", ")}
                      {g.rows.length > 4 ? ` and ${g.rows.length - 4} more` : ""}
                    </span>
                  </div>
                ))}
              </>
            ) : null}
            {selRows.length ? (
              <>
                <div className="gh">
                  <span>Why they’re here</span>
                  <span />
                </div>
                <div className="kv">
                  {reasonsOf(selRows).map(([why, n]) => (
                    <React.Fragment key={why}>
                      <span>{inText(why, unit)}</span>
                      <b className="num">{n}</b>
                    </React.Fragment>
                  ))}
                </div>
              </>
            ) : null}
            <div style={{ padding: 12 }}>
              <button className="btn sm" type="button" onClick={() => onBucket("all")}>
                Show all
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}

/** A bucket's resources: machine time and material in total, then by machine (or process) and by grade. */
function Resources({ t, b }: { t: BucketTotal | undefined; b: BucketBreakdown }) {
  const usedKnown = t?.used_kg != null && !!t.used_parts;
  const cover = (n: number | undefined) => (t && n != null && n < t.parts ? ` (${n} of ${t.parts})` : "");
  return (
    <div className="kv">
      <span>Machine time</span>
      <b className="num">
        {hoursText(t?.hours)}
        {t?.hours != null ? cover(t.hours_parts) : ""}
      </b>
      {b.machines.map((m) => {
        const l = machineLine(m);
        return (
          <React.Fragment key={`m-${m.machine ?? ""}-${m.process ?? ""}`}>
            <span>{l.label}</span>
            <b className="num">{l.value}</b>
          </React.Fragment>
        );
      })}
      <span>{usedKnown ? "Material used" : "Material in the parts"}</span>
      <b className="num">
        {massText(usedKnown ? t?.used_kg : t?.mass_kg)}
        {usedKnown ? cover(t?.used_parts) : t?.mass_kg != null ? cover(t?.mass_parts) : ""}
      </b>
      {b.materials.map((g) => {
        const l = materialLine(g);
        return (
          <React.Fragment key={`g-${g.material}`}>
            <span>{l.label}</span>
            <b className="num">{l.value}</b>
          </React.Fragment>
        );
      })}
    </div>
  );
}

function reasonsOf(rows: BoardRow[]): [string, number][] {
  const m = new Map<string, number>();
  for (const r of rows) {
    const k = r.reason ?? "—";
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
}

/** Invite someone outside the organization to look at this run, as a viewer: the email names you, the organization and the run. */
function InviteToRun({ batchId }: { batchId: string }) {
  const [email, setEmail] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const id = React.useId();
  const send = async () => {
    const to = email.trim();
    if (!to || busy) return;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(to)) {
      setMsg({ tone: "bad", text: "Type an email address, like mark@yourcompany.com." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const r = await inviteToRun(batchId, to);
      setEmail("");
      setMsg(
        r.emailed
          ? { tone: "ok", text: `Invitation sent to ${to}. It names you, your organization and this run, and opens it once accepted.` }
          : { tone: "ok", text: `Invitation made. Email isn’t set up here, so send ${to} this link: ${r.accept_link}` },
      );
    } catch (e) {
      setMsg({ tone: "bad", text: errorText(e, "The invitation wasn’t sent.") });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="cr-inv"
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      <label htmlFor={id}>Invite someone to see this run</label>
      <span>
        <input id={id} type="email" autoComplete="off" placeholder="name@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <button className="btn sm" type="submit" disabled={busy || !email.trim()}>
          {busy ? "Sending…" : "Invite as viewer"}
        </button>
      </span>
      {msg ? (
        <small role={msg.tone === "bad" ? "alert" : "status"} className={msg.tone === "bad" ? "cr-warn" : undefined}>
          {msg.text}
        </small>
      ) : null}
    </form>
  );
}

/** When a run stopped, for its line: "16:55" today, else the day and time. */
function stopTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }) : whenLabel(iso).replace(/^Yesterday/, "yesterday");
}

/** Why a stopped run stopped, from its failure ("The run stopped before every part was checked: why."). */
function stopReason(board: Board): string | null {
  const msg = (board as Board & { failure?: { message?: string | null } | null }).failure?.message;
  if (board.status !== "failed" || !msg) return null;
  const why = msg.includes(": ") ? msg.slice(msg.indexOf(": ") + 2) : msg;
  return why ? why[0].toUpperCase() + why.slice(1) : null;
}
