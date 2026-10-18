"use client";

/**
 * One batch run (board M1): progress, the finished parts sorted into lanes by
 * what your shop can do with them, the items list, the portfolio verdict, the
 * results CSV and cancel (confirmed). Progress polls every 5 s until the batch
 * settles; loaded item pages are refreshed in place, never dropped.
 */
import * as React from "react";
import Link from "next/link";
import {
  cancelBatch,
  downloadBatchCsv,
  getBatchItems,
  getBatchProgress,
  getPortfolioVerdict,
  type BatchItem,
  type BatchProgress,
  type PortfolioVerdict,
} from "@/lib/api/batch";
import { batchActivityCopy } from "@/lib/batch-progress-copy";
import { batchProgressSettled } from "@/lib/recovery-records";
import { R } from "../routes";
import { Chip, Content, Empty, Fig, Figs, Loading, PageHead, Panel, Row, Sheet, cx } from "../ui";
import { ConfirmDialog, ManyWorld, PilotGate, Thumb, errorText, revealSheetOnPhone, saveBlob, useManyTabs, usePilotAccess, useToast, whenLabel } from "./common";
import { BATCH_GATE } from "./batches-screen";
import {
  ITEM_FILTERS,
  TERMINAL,
  analysisIdOf,
  batchStatus,
  cancelText,
  doneFraction,
  etaText,
  filterCounts,
  itemStatus,
  laneItems,
  progressText,
  resultText,
  seconds,
  sortItems,
  type LanedItem,
  type SortKey,
} from "./batch-model";
import { LANE_ORDER, costLabel, laneDef, procName, reasonOf, routeName, type Machine, type MakeRow } from "./makeability";
import { fetchMachines, fetchMakeLookup } from "./many-api";

const POLL_MS = 5000;
const PAGE = 50;
/** The makeability lookup is a handful of reads; refresh it at most this often while the batch runs. */
const LOOKUP_EVERY_MS = 60_000;

type Lookup = Map<string, { bucket: string; row: MakeRow }>;

function useItems(batchId: string, status: string | null, enabled = true) {
  const [items, setItems] = React.useState<BatchItem[] | null>(null);
  const [cursor, setCursor] = React.useState<string | null>(null);
  const [more, setMore] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const pages = React.useRef(1);
  const run = React.useRef(0);

  /** Re-reads the first `pages` pages, so polling never drops what Load more fetched. */
  const reload = React.useCallback(async () => {
    if (!enabled) return;
    const id = ++run.current;
    try {
      let acc: BatchItem[] = [];
      let c: string | null = null;
      let has = false;
      for (let i = 0; i < pages.current; i++) {
        const r = await getBatchItems(batchId, { status: status ?? undefined, cursor: c ?? undefined, limit: PAGE });
        acc = acc.concat(r.items);
        c = r.next_cursor;
        has = r.has_more;
        if (!has) break;
      }
      if (id !== run.current) return;
      setItems(acc);
      setCursor(c);
      setMore(has);
      setErr(null);
    } catch (e) {
      if (id !== run.current) return;
      setErr(errorText(e, "Items didn’t load."));
    }
  }, [batchId, status, enabled]);

  React.useEffect(() => {
    pages.current = 1;
    setItems(null);
    void reload();
  }, [reload]);

  const loadMore = React.useCallback(async () => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    const id = run.current;
    try {
      const r = await getBatchItems(batchId, { status: status ?? undefined, cursor, limit: PAGE });
      if (id !== run.current) return;
      pages.current += 1;
      setItems((prev) => [...(prev ?? []), ...r.items]);
      setCursor(r.next_cursor);
      setMore(r.has_more);
    } catch (e) {
      setErr(errorText(e, "More items didn’t load."));
    } finally {
      setLoadingMore(false);
    }
  }, [batchId, status, cursor, loadingMore]);

  return { items, more, err, loadingMore, reload, loadMore };
}

export function BatchRun({ batchId }: { batchId: string }) {
  const [access] = usePilotAccess();
  const [toastNode, toast] = useToast();
  const [progress, setProgress] = React.useState<BatchProgress | null>(null);
  const [progErr, setProgErr] = React.useState<{ msg: string; status?: number } | null>(null);
  const [pollKey, setPollKey] = React.useState(0);
  const [portfolio, setPortfolio] = React.useState<PortfolioVerdict | null>(null);
  const [lookup, setLookup] = React.useState<Lookup | null>(null);
  const [lookupErr, setLookupErr] = React.useState(false);
  const [machines, setMachines] = React.useState<Machine[] | null>(null);
  const [view, setView] = React.useState<"lanes" | "list">("lanes");
  const [lane, setLane] = React.useState<string>("all");
  const [filter, setFilter] = React.useState("all");
  const [sort, setSort] = React.useState<SortKey>("arrival");
  const [errs, setErrs] = React.useState<Set<string>>(new Set());
  const [asking, setAsking] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const [csvBusy, setCsvBusy] = React.useState(false);
  const tabs = useManyTabs();

  const all = useItems(batchId, null);
  const filtered = useItems(batchId, filter, filter !== "all");
  const snapshot = React.useRef("");
  const lastLookup = React.useRef(0);

  const loadLookup = React.useCallback(async () => {
    lastLookup.current = Date.now();
    try {
      setLookup(await fetchMakeLookup());
      setLookupErr(false);
    } catch {
      setLookupErr(true);
    }
  }, []);

  React.useEffect(() => {
    fetchMachines().then(setMachines, () => setMachines([]));
  }, []);

  // Progress: poll until settled. A change in the counters refreshes items, the verdict and (throttled) the lanes.
  React.useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const p = await getBatchProgress(batchId);
        if (!live) return;
        setProgress(p);
        setProgErr(null);
        const snap = [p.status, p.completed_items, p.failed_items, p.skipped_items, p.pending_items].join(":");
        const changed = snap !== snapshot.current;
        const first = snapshot.current === "";
        snapshot.current = snap;
        const settled = batchProgressSettled(p.status, p.pending_items);
        if (changed) {
          if (!first) {
            void all.reload();
            if (filter !== "all") void filtered.reload();
          }
          getPortfolioVerdict(batchId).then((v) => live && setPortfolio(v), () => {});
          if (p.completed_items > 0 && (first || settled || Date.now() - lastLookup.current > LOOKUP_EVERY_MS)) void loadLookup();
        }
        if (!settled) timer = setTimeout(tick, POLL_MS);
      } catch (e) {
        if (!live) return;
        const status = (e as { status?: number }).status;
        setProgErr({ msg: errorText(e, "Progress didn’t load."), status });
      }
    };
    void tick();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
    // all/filtered reloads are stable per batch+filter; re-running on them would restart polling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId, pollKey, loadLookup]);

  const terminal = progress ? TERMINAL.has(progress.status) : false;
  const canCsv = progress?.status === "completed" || progress?.status === "failed";
  const canCancel = !!progress && !terminal;

  const doCancel = async () => {
    setCancelling(true);
    try {
      await cancelBatch(batchId);
      const n = progress?.pending_items ?? 0;
      toast(`Batch cancelled. ${n.toLocaleString("en-US")} unfinished ${n === 1 ? "item" : "items"} skipped.`);
      setAsking(false);
      snapshot.current = "x";
      setPollKey((k) => k + 1);
      void all.reload();
    } catch (e) {
      toast(errorText(e, "The batch wasn’t cancelled."));
      setAsking(false);
    } finally {
      setCancelling(false);
    }
  };

  const csv = async () => {
    if (csvBusy) return;
    setCsvBusy(true);
    try {
      saveBlob(await downloadBatchCsv(batchId), `batch_${batchId}_results.csv`);
      toast(`Downloaded batch_${batchId}_results.csv`);
    } catch (e) {
      toast(errorText(e, "The CSV didn’t download."));
    } finally {
      setCsvBusy(false);
    }
  };

  if (access === "gated") return <PilotGate {...BATCH_GATE} title="Batch run" />;

  if (progErr?.status === 404) {
    return (
      <ManyWorld label="Batch run">
        <PageHead title="Batch run" meta={[<span key="i" className="mono">{batchId}</span>]} tabs={tabs} tabsLabel="Many parts" wide />
        <Content full>
          <Panel>
            <Empty title="This batch isn’t available" actions={<Link className="btn sm" href={R.many}>Back to batches</Link>}>
              It may belong to another organization, or the link is wrong.
            </Empty>
          </Panel>
        </Content>
      </ManyWorld>
    );
  }

  const lanes = laneItems(all.items ?? [], lookup);
  const laneKeys = LANE_ORDER.filter((k) => ["makeable_in_house", "design_change", "needs_capability", "not_makeable"].includes(k) || (lanes.get(k)?.length ?? 0) > 0);
  for (const k of lanes.keys()) if (!laneKeys.includes(k) && (lanes.get(k)?.length ?? 0) > 0) laneKeys.push(k);
  const count = (k: string) => lanes.get(k)?.length ?? 0;
  const done = progress?.completed_items ?? 0;
  const st = progress ? batchStatus(progress.status) : null;
  const p = progress;

  const pickLane = (k: string) => {
    setLane((cur) => (cur === k ? "all" : k));
    revealSheetOnPhone("This batch");
  };
  const tileHref = (x: LanedItem) => (x.row ? R.part(x.row.part_key) : analysisIdOf(x.item) ? R.analysis(analysisIdOf(x.item)!) : R.batch(batchId));
  const dfmLine = (it: BatchItem) => (it.best_process ? `DFM: ${procName(it.best_process)}` : "DFM checked");
  const tileWhy = (x: LanedItem) => (x.row?.makeability?.verdict ? reasonOf(x.row, machines) : dfmLine(x.item));
  const tileCost = (x: LanedItem) => {
    if (x.row?.makeability?.verdict) {
      const c = costLabel(x.row);
      return c === "—" ? "" : c;
    }
    return x.item.issue_count != null ? `${x.item.issue_count} ${x.item.issue_count === 1 ? "finding" : "findings"}` : "";
  };

  const routeCounts = (rows: LanedItem[]) => {
    const m = new Map<string, number>();
    for (const x of rows) {
      const name = routeName(x.row?.recommended_route?.process, machines);
      m.set(name, (m.get(name) ?? 0) + 1);
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  };
  const reasons = (rows: LanedItem[]) => {
    const m = new Map<string, number>();
    for (const x of rows) m.set(tileWhy(x), (m.get(tileWhy(x)) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  };
  const laneNote = (k: string): string => {
    const rows = lanes.get(k) ?? [];
    if (k === "makeable_in_house") {
      const rc = routeCounts(rows);
      return rc.length ? rc.slice(0, 2).map(([n, c]) => `${n}: ${c}`).join(" · ") : "Fits one of your machines";
    }
    if (k === "design_change") return "Passes once the design changes";
    if (k === "needs_capability") return "Owns the kind of machine; none fits";
    if (k === "not_makeable") return "No route makes it as drawn";
    if (k === "unknown") return "DFM only; no check against your machines";
    if (k === "makeable_outside") return "No owned machine of the kind";
    return "Its own verdict";
  };

  const listItems = filter === "all" ? all : filtered;
  const shown = sortItems(listItems.items ?? [], sort);
  const counts = filterCounts(progress, all.items ?? [], !!all.items && !all.more);

  const pv = portfolio;
  const pvWord = pv ? ({ pass: "Pass", issues: "Issues", fail: "Fail", incomplete: done ? "Incomplete" : "Waiting" } as Record<string, string>)[pv.verdict] ?? pv.verdict : "—";

  const laneSel = lane !== "all" ? laneDef(lane) : null;
  const selRows = lane !== "all" ? lanes.get(lane) ?? [] : [];

  return (
    <ManyWorld label="Batch run">
      <div className="pagehead">
        <h1 className="ptitle">Batch run</h1>
        <p className="pmeta" style={{ marginTop: 6 }}>
          <span className="mono" title={batchId}>
            {batchId.slice(0, 12)}…
          </span>
          {p ? (
            <span>
              <b className="num">{p.total_items.toLocaleString("en-US")}</b> {p.total_items === 1 ? "part" : "parts"}
            </span>
          ) : null}
          {p ? <span>{p.concurrency_limit} at a time</span> : null}
          {st ? <span>{st.label}</span> : null}
          {p ? <span>{p.started_at ? `Started ${whenLabel(p.started_at)}` : `Created ${whenLabel(p.created_at)}`}</span> : null}
          <span>Pilot plan</span>
        </p>
        <div className="hrow">
          <nav className="subnav" aria-label="Many parts">
            {tabs.map((t, i) => (
              <Link key={t.href} href={t.href} className={cx(i === 0 && "on")} aria-current={i === 0 ? "page" : undefined}>
                {t.label}
                {"count" in t && t.count != null ? <b className="num">{t.count}</b> : null}
              </Link>
            ))}
          </nav>
          <div className="tools">
            <span className="seg" role="group" aria-label="View">
              <button type="button" className={cx(view === "lanes" && "on")} aria-pressed={view === "lanes"} onClick={() => setView("lanes")}>
                Lanes
              </button>
              <button type="button" className={cx(view === "list" && "on")} aria-pressed={view === "list"} onClick={() => setView("list")}>
                List
              </button>
            </span>
            {canCsv ? (
              <button className="btn sm" type="button" onClick={() => void csv()} disabled={csvBusy}>
                {csvBusy ? "Downloading…" : "Download CSV"}
              </button>
            ) : null}
            {canCancel ? (
              <button className="btn sm danger" type="button" onClick={() => setAsking(true)}>
                Cancel batch
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <Content>
        {progErr ? (
          <div className="panel errx" role="alert">
            <b>Progress didn’t load</b>
            <span>Saved results are unchanged. {progErr.msg}</span>
            <span>
              <button className="btn sm ink" type="button" onClick={() => setPollKey((k) => k + 1)}>
                Try again
              </button>
            </span>
          </div>
        ) : null}

        {p ? (
          <div className="panel prog" aria-live="polite">
            <span className="st">{st?.label}</span>
            <span className="num">{progressText(p)}</span>
            <span className="pb" aria-hidden="true">
              <i className={cx(p.status === "cancelled" && "cx")} style={{ transform: `scaleX(${doneFraction(p)})` }} />
            </span>
            <span className="num">{etaText(p)}</span>
            <span className="act">
              {terminal
                ? p.completed_at
                  ? `${st?.label} ${whenLabel(p.completed_at)}`
                  : st?.label
                : batchActivityCopy({
                    status: p.status,
                    totalItems: p.total_items,
                    pendingItems: p.pending_items,
                    processedItems: p.completed_items + p.failed_items + p.skipped_items,
                    concurrencyLimit: p.concurrency_limit,
                  })}
            </span>
          </div>
        ) : !progErr ? (
          <Loading rows={1} label="Loading progress" />
        ) : null}

        {view === "lanes" ? (
          <>
            {lookupErr ? (
              <div className="errx" role="alert">
                <b>Lanes didn’t load</b>
                <span>Each part’s check against your machines couldn’t be read. The items list still works.</span>
                <span>
                  <button className="btn sm" type="button" onClick={() => void loadLookup()}>
                    Try again
                  </button>
                </span>
              </div>
            ) : null}
            <div className="lanes">
              {laneKeys.map((k) => {
                const d = laneDef(k);
                const rows = lanes.get(k) ?? [];
                return (
                  <div key={k} className={cx("panel lane", lane === k && "on", lane !== "all" && lane !== k && "dim")}>
                    <button type="button" className="lh" onClick={() => pickLane(k)} aria-pressed={lane === k}>
                      <b className="num">{rows.length}</b>
                      <span>
                        <i style={{ background: d.color }} />
                        {d.label}
                      </span>
                      <small>{laneNote(k)}</small>
                    </button>
                    <div className="tiles">
                      {rows.map((x) => (
                        <Link key={x.item.item_ulid} className="tile" href={tileHref(x)}>
                          <Thumb name={x.item.filename} />
                          <span style={{ minWidth: 0 }}>
                            <b title={x.item.filename}>{x.item.filename}</b>
                            <small>{tileWhy(x)}</small>
                            {tileCost(x) ? <span className="c num">{tileCost(x)}</span> : null}
                          </span>
                        </Link>
                      ))}
                      {!rows.length ? <span className="none">{all.items ? "None yet" : "Loading"}</span> : null}
                    </div>
                  </div>
                );
              })}
            </div>
            {p && p.failed_items + p.pending_items + p.skipped_items > 0 ? (
              <p className="pmeta" style={{ margin: "0 4px" }}>
                {p.pending_items ? <span>{p.pending_items} still checking</span> : null}
                {p.failed_items ? <span>{p.failed_items} couldn’t be checked</span> : null}
                {p.skipped_items ? <span>{p.skipped_items} skipped</span> : null}
                <button className="lk" type="button" onClick={() => setView("list")}>
                  See them in the list
                </button>
              </p>
            ) : null}
          </>
        ) : (
          <Panel title="Items" note={`${shown.length.toLocaleString("en-US")} of ${(counts[filter] ?? shown.length).toLocaleString("en-US")}`}>
            <div className="segs">
              <span className="seg" role="group" aria-label="Status">
                {ITEM_FILTERS.map(([k, label]) => (
                  <button key={k} type="button" className={cx(filter === k && "on")} aria-pressed={filter === k} onClick={() => setFilter(k)}>
                    {label}
                    {counts[k] != null ? <span className="n">{counts[k]}</span> : null}
                  </button>
                ))}
              </span>
            </div>
            {listItems.err && !listItems.items ? (
              <Empty
                title="Items didn’t load"
                actions={
                  <button className="btn sm" type="button" onClick={() => void listItems.reload()}>
                    Try again
                  </button>
                }
              >
                Saved results are unchanged. {listItems.err}
              </Empty>
            ) : !listItems.items ? (
              <Loading rows={4} label="Loading items" />
            ) : shown.length === 0 ? (
              <Empty
                title={filter === "all" ? "No items yet" : "No items with this status"}
                actions={
                  filter !== "all" ? (
                    <button className="btn sm" type="button" onClick={() => setFilter("all")}>
                      Show all
                    </button>
                  ) : undefined
                }
              >
                {filter === "all" ? "Items appear once the ZIP is opened." : "Pick another status."}
              </Empty>
            ) : (
              <div style={{ padding: "0 8px 4px" }}>
                <table className="it">
                  <thead>
                    <tr>
                      <th scope="col" aria-sort={sort === "name" ? "ascending" : "none"}>
                        <button type="button" className="sh" onClick={() => setSort((s) => (s === "name" ? "arrival" : "name"))}>
                          File {sort === "name" ? "↑" : ""}
                        </button>
                      </th>
                      <th scope="col">Status</th>
                      <th scope="col">Priority</th>
                      <th scope="col" className="r" aria-sort={sort === "time" ? "descending" : "none"}>
                        <button type="button" className="sh" onClick={() => setSort((s) => (s === "time" ? "arrival" : "time"))}>
                          Time {sort === "time" ? "↓" : ""}
                        </button>
                      </th>
                      <th scope="col">Result</th>
                      <th scope="col">
                        <span className="sr">Open</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((it) => {
                      const s = itemStatus(it.status);
                      const aid = analysisIdOf(it);
                      const hit = aid && lookup ? lookup.get(aid) : null;
                      const open = errs.has(it.item_ulid);
                      const note =
                        it.status === "skipped"
                          ? `Skipped: ${it.error_message || "batch cancelled"}`
                          : it.status === "completed"
                            ? hit
                              ? reasonOf(hit.row, machines)
                              : "Not checked against your machines"
                            : it.status === "failed"
                              ? "Couldn’t be checked"
                              : "";
                      return (
                        <tr key={it.item_ulid}>
                          <td className="fn">
                            <b title={it.filename}>{it.filename}</b>
                            {note ? <small>{note}</small> : null}
                            {it.status === "failed" && it.error_message ? (
                              <>
                                <button
                                  type="button"
                                  className="lk"
                                  aria-expanded={open}
                                  onClick={() =>
                                    setErrs((prev) => {
                                      const n = new Set(prev);
                                      if (n.has(it.item_ulid)) n.delete(it.item_ulid);
                                      else n.add(it.item_ulid);
                                      return n;
                                    })
                                  }
                                >
                                  {open ? "Hide error" : "Show error"}
                                </button>
                                {open ? <span className="err">{it.error_message}</span> : null}
                              </>
                            ) : null}
                          </td>
                          <td>
                            <Chip tone={s.tone}>{s.label}</Chip>
                          </td>
                          <td className="hm" style={{ color: "var(--ink2)" }}>
                            {it.priority ? it.priority[0].toUpperCase() + it.priority.slice(1) : "Normal"}
                          </td>
                          <td className="r num">{it.status === "completed" || it.status === "failed" ? seconds(it.duration_ms) : "—"}</td>
                          <td style={{ color: "var(--ink2)" }}>{resultText(it, procName)}</td>
                          <td className="r">
                            {it.status === "completed" && aid ? (
                              <Link className="lk" href={R.analysis(aid)} aria-label={`View ${it.filename}`}>
                                View
                              </Link>
                            ) : (
                              <span className="lk off" aria-disabled="true">
                                View
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="tfoot" style={{ padding: "0 8px 10px" }}>
              {listItems.more ? (
                <>
                  <span>{shown.length.toLocaleString("en-US")} loaded · more below</span>
                  <button className="btn sm" type="button" onClick={() => void listItems.loadMore()} disabled={listItems.loadingMore}>
                    {listItems.loadingMore ? "Loading…" : "Load more"}
                  </button>
                </>
              ) : listItems.items && shown.length ? (
                <span>
                  All {shown.length.toLocaleString("en-US")} shown · sorted by {sort === "name" ? "file name" : sort === "time" ? "time, longest first" : "arrival"}
                </span>
              ) : null}
            </p>
          </Panel>
        )}
      </Content>

      <Sheet label="This batch">
        <div className="top">
          <h2 className="stitle">{laneSel ? laneSel.label : "This batch"}</h2>
          <p className="smeta">
            {laneSel
              ? `${selRows.length} of ${done} checked ${done === 1 ? "part" : "parts"}`
              : p
                ? `${p.total_items} ${p.total_items === 1 ? "part" : "parts"} · ${done} checked${p.failed_items ? ` · ${p.failed_items} failed` : ""}`
                : "Loading"}
          </p>
          {!laneSel ? (
            <Figs>
              <Fig k="Make in-house" v={String(count("makeable_in_house"))} sub={`of ${done}`} tone="ok" />
              <Fig k="Design change" v={String(count("design_change"))} tone={count("design_change") ? "warn" : undefined} />
              <Fig k="New equipment" v={String(count("needs_capability"))} tone={count("needs_capability") ? "warn" : undefined} />
              <Fig k="Ruled out" v={String(count("not_makeable"))} tone={count("not_makeable") ? "bad" : undefined} />
              <Fig k="Outside only" v={String(count("makeable_outside"))} />
              {count("unknown") ? <Fig k="Not checked on machines" v={String(count("unknown"))} /> : null}
            </Figs>
          ) : null}
        </div>
        <div className="scroll">
          {!laneSel ? (
            <div className="swap" key="all">
              <div className="pv" aria-live="polite">
                <b>{pvWord}</b>
                <span className="num">
                  {pv
                    ? `${pv.pass_items} pass · ${pv.issues_items} issues · ${pv.fail_items + pv.processing_failed_items} fail · ${pv.skipped_items} skipped`
                    : "Not available yet"}
                </span>
                <span style={{ color: "var(--ink3)", fontSize: 12 }}>DFM verdicts of the checked parts</span>
              </div>
              <div className="gh">
                <span>By machine</span>
                <span>parts in-house</span>
              </div>
              {count("makeable_in_house") ? (
                <div className="kv">
                  {routeCounts(lanes.get("makeable_in_house") ?? []).map(([n, c]) => (
                    <React.Fragment key={n}>
                      <span>{n}</span>
                      <b className="num">{c}</b>
                    </React.Fragment>
                  ))}
                </div>
              ) : (
                <p style={{ margin: "0 12px 6px", color: "var(--ink3)", fontSize: 13 }}>No part fits one of your machines yet.</p>
              )}
              <div className="gh" style={{ marginTop: 6 }}>
                <span>Export</span>
                <span />
              </div>
              <div style={{ display: "flex", gap: 8, padding: "4px 12px 8px", flexWrap: "wrap" }}>
                <button className="btn sm" type="button" onClick={() => void csv()} disabled={!canCsv || csvBusy}>
                  Results CSV
                </button>
              </div>
              <p style={{ margin: "4px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
                {canCsv ? "One row per file: verdict, best route and findings." : "Ready when the batch finishes."}
              </p>
              <p style={{ margin: "10px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
                Lanes come from each part’s latest check against your machines. A part never checked for cost sits in “Not checked against your machines”.
              </p>
            </div>
          ) : (
            <div className="swap" key={lane}>
              {selRows.length ? (
                <div className="list" role="list" aria-label={laneSel.label}>
                  {selRows.map((x) => (
                    <div role="listitem" key={x.item.item_ulid}>
                      <Row href={tileHref(x)} thumb={<Thumb name={x.item.filename} className="th" />} title={x.item.filename} sub={tileWhy(x)} value={tileCost(x)} />
                    </div>
                  ))}
                </div>
              ) : (
                <Empty title={`No parts in ${laneSel.label.toLowerCase()}`}>Pick another lane.</Empty>
              )}
              {selRows.length ? (
                <div className="note">
                  <b>{lane === "makeable_in_house" ? "Where they’d run" : "Why they’re here"}</b>
                  <span>
                    {lane === "makeable_in_house"
                      ? routeCounts(selRows).map(([n, c]) => `${n}: ${c}`).join(" · ")
                      : reasons(selRows)
                          .slice(0, 3)
                          .map(([r, c]) => (c > 1 ? `${r} (${c})` : r))
                          .join(" · ")}
                  </span>
                </div>
              ) : null}
              <div style={{ padding: 12 }}>
                <button className="btn sm" type="button" onClick={() => setLane("all")}>
                  Show all
                </button>
              </div>
            </div>
          )}
        </div>
      </Sheet>

      {asking && canCancel ? (
        <ConfirmDialog
          title="Cancel this batch?"
          text={cancelText(progress)}
          keepLabel="Keep running"
          confirmLabel="Cancel batch"
          busy={cancelling}
          onKeep={() => setAsking(false)}
          onConfirm={() => void doCancel()}
        />
      ) : null}
      {toastNode}
    </ManyWorld>
  );
}
