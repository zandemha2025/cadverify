"use client";

/**
 * Records (board P2): every saved decision, grouped by part, with real filters
 * (waiting for review, decided, out of date). The selected record opens in the
 * sheet; its URL is /app/parts/records/{id}. Rendered by the records layout so
 * the list (and its scroll and filter) stays put while the selection changes.
 */
import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { R, TABS } from "../routes";
import { Chip, Content, PageHead, cx } from "../ui";
import { useRecordList } from "./api";
import { Glyph, ListFoot, RecWorld, LoadFailed, NoneYet, Skeleton, useToast } from "./common";
import { groupByPart, keepRecord, statusOf, summaryLines, type RecordFilter } from "./facts";
import { RecordSheet } from "./record-sheet";
import { plural, rowTime } from "./words";

const FILTERS: [RecordFilter, string][] = [
  ["all", "All"],
  ["review", "Waiting for review"],
  ["decided", "Decided"],
  ["stale", "Out of date"],
];

export function RecordsScreen() {
  const params = useParams<{ id?: string }>();
  const routeId = typeof params?.id === "string" ? decodeURIComponent(params.id) : null;
  const router = useRouter();
  const list = useRecordList();
  const [filter, setFilter] = React.useState<RecordFilter>("all");
  const [toastNode, toast] = useToast();

  const rows = list.rows;
  const n = rows?.length ?? 0;
  const plus = list.more ? "+" : "";
  const counts = React.useMemo(() => {
    const c: Record<RecordFilter, number> = { all: 0, review: 0, decided: 0, stale: 0 };
    for (const r of rows ?? []) for (const [k] of FILTERS) if (keepRecord(r, k)) c[k] += 1;
    return c;
  }, [rows]);
  const shown = React.useMemo(() => (rows ?? []).filter((r) => keepRecord(r, filter)), [rows, filter]);
  const groups = React.useMemo(() => groupByPart(shown), [shown]);
  const allGroups = React.useMemo(() => groupByPart(rows ?? []), [rows]);
  const totalByPart = React.useMemo(() => new Map(allGroups.map((g) => [g.key, g.rows.length])), [allGroups]);
  const selId = routeId ?? rows?.[0]?.id ?? null;
  const nApproved = (rows ?? []).filter((r) => r.approval_status === "approved").length;
  const nShared = (rows ?? []).filter((r) => r.is_public).length;

  const tabs = TABS.parts.map((t) => (t.href === R.records && rows ? { ...t, count: n } : t));

  return (
    <RecWorld label="Records">
      <PageHead
        title="Records"
        meta={
          rows
            ? [
                <>
                  <b className="num">
                    {n}
                    {plus}
                  </b>{" "}
                  {n === 1 && !plus ? "record" : "records"}
                </>,
                <>
                  <b className="num">{nApproved}</b> approved
                </>,
                <>
                  <b className="num">{counts.decided}</b> with an outcome
                </>,
                <>
                  <b className="num">{nShared}</b> shared
                </>,
                plural(allGroups.length, "part"),
              ]
            : [list.error ? "Records didn't load" : "Loading records"]
        }
        tabs={tabs}
        tabsLabel="Parts"
      />
      <Content full={!selId}>
        {rows && rows.length ? (
          <div className="rc-filters">
            <span className="seg" role="group" aria-label="Show">
              {FILTERS.map(([k, label]) => (
                <button key={k} type="button" className={cx(filter === k && "on")} aria-pressed={filter === k} onClick={() => setFilter(k)}>
                  {label}{" "}
                  <span className="num" style={{ opacity: 0.7 }}>
                    {counts[k]}
                    {plus}
                  </span>
                </button>
              ))}
            </span>
          </div>
        ) : null}
        <section className="panel" aria-label="Records by part">
          {!rows ? (
            list.error ? (
              <LoadFailed what="records" detail={list.error} onRetry={() => void list.reload()} />
            ) : (
              <>
                <div className="ph">
                  <h2>Records</h2>
                  <span>Loading</span>
                </div>
                <Skeleton rows={5} label="Loading records" />
              </>
            )
          ) : rows.length === 0 ? (
            <NoneYet
              title="No records"
              actions={
                <Link className="btn sm ink" href={R.check}>
                  Check a part
                </Link>
              }
            >
              One is saved each time you check a part.
            </NoneYet>
          ) : (
            <>
              <div className="list">
                {groups.map((g) => (
                  <React.Fragment key={g.key}>
                    <div className="grp">
                      <span className="gl" aria-hidden="true">
                        <Glyph size={16} />
                      </span>
                      {g.key.startsWith("file:") ? <span>{g.filename}</span> : <Link href={R.part(g.key)}>{g.filename}</Link>}
                      <em className="num">{plural(totalByPart.get(g.key) ?? g.rows.length, "record")}</em>
                    </div>
                    {g.rows.map((r) => {
                      const s = statusOf(r);
                      const l = summaryLines(r);
                      const on = r.id === selId;
                      return (
                        <button
                          key={r.id}
                          type="button"
                          className={cx("lrow rec", on && "on")}
                          aria-pressed={on}
                          onClick={() => router.push(R.record(r.id), { scroll: false })}
                        >
                          <span style={{ minWidth: 0 }}>
                            <b>{l.what}</b>
                            <small>{l.answer}</small>
                          </span>
                          <span className="sh">{r.is_public ? "Shared" : ""}</span>
                          <Chip tone={s.tone}>{s.label}</Chip>
                          <span className="t" title={new Date(r.created_at).toISOString()}>
                            {rowTime(r.created_at)}
                          </span>
                        </button>
                      );
                    })}
                  </React.Fragment>
                ))}
                {!shown.length ? (
                  filter === "stale" ? (
                    <NoneYet title="No out-of-date records">A record goes out of date when a machine or rate it used changes.</NoneYet>
                  ) : (
                    <NoneYet
                      title="No records match"
                      actions={
                        <button type="button" className="btn sm" onClick={() => setFilter("all")}>
                          Show all
                        </button>
                      }
                    >
                      {filter === "decided" ? "No record has an outcome yet." : "Every loaded record is approved."}
                    </NoneYet>
                  )
                ) : null}
              </div>
              <ListFoot shown={shown.length} loaded={n} noun="records" more={list.more} loading={list.loadingMore} onMore={() => void list.loadMore()} error={list.moreError} hint="times in UTC" />
            </>
          )}
        </section>
      </Content>
      {selId ? <RecordSheet key={selId} id={selId} toast={toast} /> : null}
      {toastNode}
    </RecWorld>
  );
}
