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
import { etaText } from "./batch-model";
import { downloadBoardCsv, fetchBoard } from "./catalog-api";
import { runSummaryHref } from "./catalog-routes";
import { AccuracyPanel } from "../validation/accuracy-panel";
import { reportHref } from "../validation/routes";
import {
  BUCKETS,
  OTHER,
  SORTS,
  boardProgress,
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
  procName,
  sortRows,
  totalsText,
  type Board,
  type BoardRow,
  type BucketBreakdown,
  type BucketTotal,
  type SortKey,
} from "./catalog-model";
import "./catalog.css";
import { rowMustHold, rowSignoffLine, rowSpecLine } from "./row-specs";

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
  const tabs = useManyTabs();
  const [toastNode, toast] = useToast();
  const [bucket, setBucket] = React.useState<string>("all");
  const [sort, setSort] = React.useState<SortKey>("bucket");
  const [query, setQuery] = React.useState("");
  const [csvBusy, setCsvBusy] = React.useState(false);
  const [asking, setAsking] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const searchId = React.useId();
  const sortId = React.useId();

  const status = board?.status ?? progress?.status ?? null;
  const running = status != null && !TERMINAL.has(status);
  const prog = boardProgress(board);

  // On its own page the run needs no bar; once it has finished here, it's been seen.
  React.useEffect(() => {
    if (!board) return;
    if (!TERMINAL.has(board.status)) {
      registerWork({ key: runKey(batchId), href: R.batch(batchId), persist: true, state: "running", label: `Checking ${prog.total} ${prog.total === 1 ? "part" : "parts"}`, detail: `${prog.done} of ${prog.total}`, progress: prog.total ? prog.done / prog.total : null });
    } else markWorkSeen(runKey(batchId));
  }, [board, batchId, prog.done, prog.total]);

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

  const rows = board?.rows ?? [];
  const shown = sortRows(filterRows(rows, bucket, query), sort);
  const total = rows.length;
  const nMachines = board?.machines.length ?? null;
  const sel = bucket !== "all" ? bucketDef(bucket) : null;

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
    <span key="n">
      <b className="num">{total.toLocaleString("en-US")}</b> {total === 1 ? "part" : "parts"}
    </span>,
    nMachines == null ? "Machines loading" : nMachines ? `Against ${nMachines} ${nMachines === 1 ? "machine" : "machines"}` : "No machines yet",
    board?.material_class ? materialWord(board.material_class) : null,
    board ? `${board.quantity.toLocaleString("en-US")} each unless listed` : null,
    statusWord && board ? `${statusWord} · ${board.free ? "free run" : "pilot plan"}` : statusWord,
  ].filter(Boolean);

  return (
    <ManyWorld label="Catalog run">
      <PageHead
        title="Catalog run"
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

            {running || prog.checking ? (
              <div className="panel prog cr-prog" aria-live="polite">
                <span className="st">Running</span>
                <span className="num">
                  {prog.done} of {prog.total} checked{prog.checking ? ` · ${prog.checking} to go` : ""}
                  {prog.failed ? ` · ${prog.failed} couldn’t be checked` : ""}
                </span>
                <span className="pb" aria-hidden="true">
                  <i style={{ transform: `scaleX(${prog.total ? prog.done / prog.total : 0})` }} />
                </span>
                <span className="num">{progress ? etaText(progress) : ""}</span>
                <span className="act">
                  Keeps going if you leave or close this page. The bar at the foot of every page brings you back.
                  {running ? (
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
                        <PartRow key={r.item_id} r={r} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="tfoot" style={{ padding: "0 8px 10px" }}>
                <span>Machine time, material and prices are model estimates from your machines and rates, not quotes. Material is what the route uses (stock, printed material with supports), with the part’s own mass beside it when that differs. Open a part for its sources.</span>
              </p>
            </Panel>

            {TERMINAL.has(board.status) ? <AccuracyPanel run={batchId} compact /> : null}

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

function PartRow({ r }: { r: BoardRow }) {
  const router = useRouter();
  const d = bucketDef(r.bucket);
  const line = partLine(r);
  const href = r.part_key ? R.part(r.part_key) : null;
  const sub = (s: string) => {
    const i = s.indexOf(" · ");
    return i > 0 ? [s.slice(0, i), s.slice(i + 3)] : [s, ""];
  };
  const [t1, t2] = sub(line.time);
  const [m1, m2] = sub(line.material);
  const [o1, o2] = sub(line.ownership);
  const [p1, p2] = sub(line.price);
  const sign = rowSignoffLine(r);
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
        <Thumb name={r.filename} />
        <span className="cr-pt">
          {href ? (
            <Link href={href} className="cr-name" title={r.filename}>
              {r.filename}
            </Link>
          ) : (
            <b className="cr-name" title={r.filename}>
              {r.filename}
            </b>
          )}
          {r.part_number ? <small className="mono">{r.part_number}</small> : null}
          <span className="cr-why">
            <i style={{ background: d.color }} aria-hidden="true" />
            <span className="sr">{d.label}: </span>
            {r.reason ?? d.label}
          </span>
          {rowSpecLine(r) ? <small className="cr-spec">{rowSpecLine(r)}</small> : null}
          {rowMustHold(r) ? <small className="cr-spec">{rowMustHold(r)}</small> : null}
          {sign ? <small className={cx("cr-sign", sign.tone)}>{sign.text}</small> : null}
          {r.material.note ? <small className="cr-warn">{r.material.note}; priced in {r.material.class ? materialWord(r.material.class).toLowerCase() : "the run’s material"}</small> : null}
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
        {r.cheaper_outside ? (
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
  if (!board) return <Loading rows={4} label="Loading this run" />;
  const sel = bucket !== "all" ? bucketDef(bucket) : null;
  const total = board.rows.length;
  const prog = boardProgress(board);
  const selRows = sel ? board.rows.filter((r) => r.bucket === bucket) : [];
  const inHouse = board.rows.filter((r) => r.bucket === "in_house");
  const ihB = breakdownOf(board, "in_house");
  const outB = breakdownOf(board, "outside");
  const selB = sel ? breakdownOf(board, bucket) : null;
  const groups = capabilityGroups(board.rows);
  const t = board.totals;
  return (
    <>
      <div className="top">
        <h2 className="stitle">{sel ? sel.label : "This run"}</h2>
        <p className="smeta">
          {sel
            ? `${selRows.length} of ${total} parts · ${sel.note}`
            : `${prog.done} of ${total} checked${progress?.started_at ? ` · started ${whenLabel(progress.started_at)}` : ""}`}
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
                  <span>At your marginal rates</span>
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
                      <span>{g.text}</span>
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
              <span>Model price</span>
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
          </>
        ) : (
          <>
            {selRows.length && selB ? (
              <>
                <Resources t={t[bucket]} b={selB} />
                <div className="kv">
                  <span>{bucket === "in_house" ? "At your marginal rates" : "Model price"}</span>
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
                    <b>{g.text}</b>
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
                      <span>{why}</span>
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

