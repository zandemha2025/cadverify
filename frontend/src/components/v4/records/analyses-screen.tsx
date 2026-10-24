"use client";

/**
 * Analyses (board P4): every DFM check on a timeline, filtered by verdict and
 * ordered newest or slowest, with your plan's allowance in the header. The
 * selected analysis opens in the sheet at /app/parts/analyses/{id}; the
 * analyses layout keeps the list in place while the selection changes.
 */
import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import type { AnalysisListRow } from "@/lib/recent-parts";
import { R, TABS } from "../routes";
import { useShell } from "../shell";
import { Chip, Content, PageHead, cx } from "../ui";
import { useAnalysisList } from "./api";
import { AnalysisSheet } from "./analysis-sheet";
import { Glyph, ListFoot, LoadFailed, NoneYet, RecWorld, Skeleton, useToast } from "./common";
import { dateUtc, num, rowTime, seconds, wayLower, type Tone } from "./words";

type VerdictFilter = "all" | "pass" | "issues" | "fail";

const FILTERS: [VerdictFilter, string][] = [
  ["all", "All"],
  ["pass", "Clear"],
  ["issues", "Advisory"],
  ["fail", "Must change"],
];

export const VERDICT_CHIP: Record<string, { label: string; tone: Tone }> = {
  pass: { label: "Clear", tone: "ok" },
  issues: { label: "Advisory", tone: "warn" },
  fail: { label: "Must change", tone: "bad" },
};

function verdictOf(r: AnalysisListRow): string {
  return (r.verdict ?? (r as { overall_verdict?: string }).overall_verdict ?? "unknown") as string;
}

/** Bar width on a log scale against the slowest loaded check (4px minimum). */
export function barWidth(ms: number, max: number): number {
  if (!(ms > 0) || !(max > 1)) return 4;
  return Math.max(4, Math.round((110 * Math.log10(Math.max(1, ms))) / Math.log10(max)));
}

export function AnalysesScreen() {
  const params = useParams<{ id?: string }>();
  const routeId = typeof params?.id === "string" ? decodeURIComponent(params.id) : null;
  const router = useRouter();
  const { usage } = useShell();
  const list = useAnalysisList();
  const [filter, setFilter] = React.useState<VerdictFilter>("all");
  const [order, setOrder] = React.useState<"new" | "slow">("new");
  const [toastNode, toast] = useToast();
  const rows = list.rows;
  const n = rows?.length ?? 0;
  const plus = list.more ? "+" : "";

  // Slowest first has to see every analysis, not just the loaded page: load the rest (bounded).
  const pages = React.useRef(0);
  React.useEffect(() => {
    if (order !== "slow" || !list.more || list.loadingMore || list.moreError || pages.current >= 20) return;
    pages.current += 1;
    void list.loadMore();
  }, [order, list]);

  const counts = React.useMemo(() => {
    const c: Record<VerdictFilter, number> = { all: 0, pass: 0, issues: 0, fail: 0 };
    for (const r of rows ?? []) {
      c.all += 1;
      const v = verdictOf(r) as VerdictFilter;
      if (v in c) c[v] += 1;
    }
    return c;
  }, [rows]);
  const shown = React.useMemo(() => {
    const keep = (rows ?? []).filter((r) => filter === "all" || verdictOf(r) === filter);
    return order === "slow" ? [...keep].sort((a, b) => (b.duration_ms ?? 0) - (a.duration_ms ?? 0)) : keep;
  }, [rows, filter, order]);
  const durs = (rows ?? []).map((r) => r.duration_ms ?? 0).filter((x) => x > 0);
  const maxMs = durs.length ? Math.max(...durs) : 0;
  const minMs = durs.length ? Math.min(...durs) : 0;
  const ways = new Set((rows ?? []).map((r) => r.process_count).filter((x) => x != null));
  const selId = routeId ?? rows?.[0]?.id ?? null;

  const plan = !usage
    ? null
    : usage.plan === "pilot" || usage.unlimited
      ? "Pilot plan · usage"
      : usage.plan === "pro"
        ? `Pro · ${num(usage.used)} of ${num(usage.cap)} checks this month`
        : `Free trial · ${num(usage.used)} of ${num(usage.cap)} checks used`;

  const tabs = TABS.parts.map((t) => (t.href === R.analyses && rows ? { ...t, count: n } : t));

  return (
    <RecWorld label="Recent analyses">
      <PageHead
        title="Analyses"
        meta={[
          ...(rows
            ? [
                <>
                  <b className="num">
                    {n}
                    {plus}
                  </b>{" "}
                  {n === 1 && !plus ? "analysis" : "analyses"}
                </>,
                ...(rows.length ? [`Newest ${dateUtc(rows[0].created_at)}`] : []),
                ...(durs.length
                  ? [
                      <>
                        Fastest <b className="num">{seconds(minMs)}</b>
                      </>,
                      <>
                        Slowest <b className="num">{seconds(maxMs)}</b>
                      </>,
                    ]
                  : []),
                ...(ways.size === 1 ? [`${[...ways][0]} processes each`] : []),
              ]
            : [list.error ? "Analyses didn't load" : "Loading analyses"]),
          ...(plan ? [<Link key="plan" href={R.billing}>{plan}</Link>] : []),
        ]}
        tabs={tabs}
        tabsLabel="Parts"
      />
      <Content full={!selId}>
        {rows && rows.length ? (
          <div className="bar3">
            <span className="seg" role="group" aria-label="Verdict">
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
            <span className="seg" role="group" aria-label="Order">
              {(
                [
                  ["new", "Newest"],
                  ["slow", "Slowest"],
                ] as const
              ).map(([k, label]) => (
                <button key={k} type="button" className={cx(order === k && "on")} aria-pressed={order === k} onClick={() => setOrder(k)}>
                  {label}
                </button>
              ))}
            </span>
          </div>
        ) : null}
        <section className="panel" aria-label="Timeline">
          {!rows ? (
            list.error ? (
              <LoadFailed what="analyses" detail={list.error} onRetry={() => void list.reload()} />
            ) : (
              <>
                <div className="ph">
                  <h2>Analyses</h2>
                  <span>Loading</span>
                </div>
                <Skeleton rows={5} label="Loading analyses" />
              </>
            )
          ) : rows.length === 0 ? (
            <NoneYet
              title="No analyses"
              actions={
                <Link className="btn sm ink" href={R.check}>
                  Check a part
                </Link>
              }
            >
              Each check of a file adds one.
            </NoneYet>
          ) : (
            <>
              <div className="ph">
                <h2>{order === "slow" ? "Slowest first" : "Newest first"}</h2>
                <span>Times in UTC · bars on a log scale</span>
              </div>
              {shown.length ? (
                <div className="tl">
                  {shown.map((r) => {
                    const v = VERDICT_CHIP[verdictOf(r)] ?? { label: "Unknown", tone: "unk" as Tone };
                    const on = r.id === selId;
                    return (
                      <button key={r.id} type="button" className={cx("lrow ev", on && "on")} aria-pressed={on} onClick={() => router.push(R.analysis(r.id), { scroll: false })}>
                        <span className="when">{rowTime(r.created_at)}</span>
                        <span className="th" aria-hidden="true">
                          <Glyph size={20} />
                        </span>
                        <span style={{ minWidth: 0 }}>
                          <b>{r.filename}</b>
                          <small>
                            {num(r.face_count)} faces · best fit: {r.best_process ? wayLower(r.best_process) : "none"}
                          </small>
                        </span>
                        <span className="dur">
                          <i style={{ width: barWidth(r.duration_ms ?? 0, maxMs) }} aria-hidden="true" />
                          <span className="num">{seconds(r.duration_ms)}</span>
                        </span>
                        <Chip tone={v.tone}>{v.label}</Chip>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="empty">
                  <b>No analyses</b>
                  <span>None with this verdict.</span>
                  <button type="button" className="btn sm" onClick={() => setFilter("all")}>
                    Clear filter
                  </button>
                </div>
              )}
              <ListFoot
                shown={shown.length}
                loaded={n}
                noun="analyses"
                more={list.more}
                loading={list.loadingMore}
                onMore={() => void list.loadMore()}
                error={list.moreError}
                hint={order === "slow" && list.more ? "slowest of those loaded" : undefined}
              />
            </>
          )}
        </section>
      </Content>
      {selId ? <AnalysisSheet key={selId} id={selId} toast={toast} /> : null}
      {toastNode}
    </RecWorld>
  );
}
