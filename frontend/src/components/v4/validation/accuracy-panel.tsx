"use client";

/**
 * "Checked against your real numbers": ScaleCAD's estimate against your actual
 * machine hours and cost per part, per part and overall, per method. Works on
 * every plan. Honest about how many parts it rests on. Used on Actual costs
 * (every part, every actual) and on a catalog run's board (that run's parts).
 */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { Fig, Loading, Panel, cx } from "../ui";
import { getAccuracy, type Accuracy, type Comparison, type Metric, type Stats } from "./api";
import { reportHref } from "./routes";
import { absPct, contextLine, leanWord, methodWord, metricValue, partsWord, pctWord, rangeWord, statsLine, summaryLine } from "./words";
import "./validation.css";

export function useAccuracy(scope: { part?: string | null; run?: string | null }, tick = 0) {
  const [data, setData] = React.useState<Accuracy | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [n, setN] = React.useState(0);
  const key = `${scope.part ?? ""}|${scope.run ?? ""}`;
  React.useEffect(() => {
    let live = true;
    setError(null);
    getAccuracy({ part: scope.part, run: scope.run }).then(
      (d) => live && setData(d),
      (e) => live && setError(e instanceof Error ? e.message : "The comparison didn’t load.")
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick, n]);
  return { data, error, reload: () => setN((x) => x + 1) };
}

function MetricCell({ kind, m }: { kind: "hours" | "cost"; m: Metric | null }) {
  if (!m) return <span className="muted">—</span>;
  const range = rangeWord(kind, m);
  return (
    <>
      <b className="num">{metricValue(kind, m.actual)}</b> <span className="num">vs {metricValue(kind, m.estimate)}</span>{" "}
      <span className="val-err">{pctWord(m.error_pct)}</span>
      <small>
        {range ?? "No stated range"}
        {kind === "cost" && m.basis === "between" ? " · between priced quantities" : ""}
      </small>
    </>
  );
}

function rangeChip(c: Comparison) {
  const ins = [c.hours?.inside, c.cost?.inside].filter((x) => x != null) as boolean[];
  if (!ins.length) return null;
  const all = ins.every(Boolean);
  const none = ins.every((x) => !x);
  return (
    <span className={cx("chip", all ? "c-ok" : none ? "c-bad" : "c-warn")}>
      <i aria-hidden="true" />
      {all ? "In range" : none ? "Outside range" : "Partly in range"}
    </span>
  );
}

function figsOf(d: Accuracy) {
  const s = d.summary;
  const cov = (st: Stats) => (st.with_range ? `${st.inside} of ${st.with_range}` : "—");
  const inside = s.hours.with_range + s.cost.with_range;
  return (
    <div className="val-figs">
      <Fig k="Parts with actuals" v={String(s.parts)} sub={s.enough ? "a fair picture" : `${s.min_parts} or more for a fair picture`} tone={s.enough ? undefined : "warn"} />
      <Fig k="Machine hours" v={s.hours.n ? absPct(s.hours.median_abs_pct) : "—"} sub={s.hours.n ? `median error · worst ${pctWord(s.hours.worst_pct)}` : "no hours given"} />
      <Fig k="Cost per part" v={s.cost.n ? absPct(s.cost.median_abs_pct) : "—"} sub={s.cost.n ? `median error · worst ${pctWord(s.cost.worst_pct)}` : "no costs given"} />
      <Fig k="Inside ScaleCAD’s range" v={inside ? `${s.hours.inside + s.cost.inside} of ${inside}` : "—"} sub={inside ? `hours ${cov(s.hours)} · cost ${cov(s.cost)}` : "no ranges to check"} />
    </div>
  );
}

export function MethodTable({ d }: { d: Accuracy }) {
  const per = d.summary.per_process;
  if (!per.length) return null;
  return (
    <div className="val-wrap">
      <table className="val-t stack">
        <thead>
          <tr>
            <th scope="col">Method</th>
            <th scope="col">Machine hours</th>
            <th scope="col">Cost per part</th>
          </tr>
        </thead>
        <tbody>
          {per.map((p) => (
            <tr key={p.process}>
              <td>
                <b>{methodWord(p.process)}</b>
                <small>{!p.hours.enough && !p.cost.enough ? `Fewer than ${d.summary.min_per_method} actuals: says little yet` : leanWord(p.hours.n >= p.cost.n ? p.hours : p.cost) ?? "No lean either way"}</small>
              </td>
              <td data-k="Machine hours">
                {statsLine(p.hours)}
                {p.hours.n && !p.hours.enough ? <small>{`${p.hours.n} of ${d.summary.min_per_method} actuals`}</small> : null}
              </td>
              <td data-k="Cost per part">
                {statsLine(p.cost)}
                {p.cost.n && !p.cost.enough ? <small>{`${p.cost.n} of ${d.summary.min_per_method} actuals`}</small> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ActualsTable({ rows, limit = 40 }: { rows: Comparison[]; limit?: number }) {
  const [all, setAll] = React.useState(false);
  // Real actuals first, test rows after them; newest first within each.
  const ordered = React.useMemo(() => [...rows].sort((a, b) => Number(a.test) - Number(b.test)), [rows]);
  const shown = all ? ordered : ordered.slice(0, limit);
  if (!rows.length) return null;
  return (
    <>
      <div className="val-wrap">
        <table className="val-t stack">
          <thead>
            <tr>
              <th scope="col">Part</th>
              <th scope="col">Machine hours each: yours vs ScaleCAD</th>
              <th scope="col">Cost each: yours vs ScaleCAD</th>
              <th scope="col">
                <span className="sr">Range</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.id}>
                <td>
                  {c.part_key ? <Link href={R.part(c.part_key)}>{c.file_name ?? "Part"}</Link> : <b>{c.file_name}</b>}
                  {c.part_number ? <span className="muted"> · {c.part_number}</span> : null}
                  <small>{contextLine(c)}</small>
                  {c.note ? <small>{c.note}</small> : null}
                </td>
                <td data-k="Machine hours each">
                  <MetricCell kind="hours" m={c.hours} />
                </td>
                <td data-k="Cost each">
                  <MetricCell kind="cost" m={c.cost} />
                </td>
                <td>
                  {c.test ? (
                    <span className="chip c-unk">
                      <i aria-hidden="true" />
                      Test
                    </span>
                  ) : (
                    rangeChip(c)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > limit ? (
        <p className="val-more">
          {all ? `All ${rows.length}.` : `Newest ${limit} of ${rows.length}.`}
          <button className="btn sm ghost" type="button" onClick={() => setAll((a) => !a)}>
            {all ? "Show fewer" : "Show all"}
          </button>
        </p>
      ) : null}
    </>
  );
}

/**
 * The panel. `run` narrows it to one catalog run's parts (compact: no per-actual
 * table, links to Actual costs and the report). `onImport` offers the import when
 * there are no actuals yet.
 */
export function AccuracyPanel({
  run,
  compact,
  tick,
  onImport,
}: {
  run?: string | null;
  compact?: boolean;
  tick?: number;
  onImport?: () => void;
}) {
  const { data, error, reload } = useAccuracy({ run }, tick);
  const s = data?.summary ?? null;
  const lead = summaryLine(s);
  return (
    <Panel
      id="accuracy"
      title="Checked against your real numbers"
      note={s ? (s.parts ? `${partsWord(s.parts)}${s.test ? ` · ${s.test} test` : ""}` : s.test ? `${s.test} test` : undefined) : undefined}
      actions={
        <span className="val-noprint" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {compact ? (
            <Link className="btn sm" href={R.actuals}>
              Actual costs
            </Link>
          ) : null}
          <Link className="btn sm" href={reportHref(run ?? null)}>
            Pilot report
          </Link>
        </span>
      }
    >
      {error ? (
        <p className="val-lead warn" role="alert" style={{ paddingBottom: 12 }}>
          The comparison didn’t load: {error}{" "}
          <button className="btn sm" type="button" onClick={reload}>
            Retry
          </button>
        </p>
      ) : !data || !s ? (
        <Loading rows={2} label="Comparing with your actuals" />
      ) : (
        <>
          <p className={cx("val-lead", s.parts > 0 && !s.enough && "warn")} aria-live="polite">
            {lead}
          </p>
          {s.parts > 0 ? figsOf(data) : null}
          {s.parts > 0 ? <MethodTable d={data} /> : null}
          {!compact && data.rows.length ? <ActualsTable rows={data.rows} /> : null}
          {s.parts === 0 && !compact && onImport ? (
            <p className="val-more">
              <button className="btn sm ink" type="button" onClick={onImport}>
                Import actuals
              </button>
              <span>A CSV or Excel export with a part number or file name, quantity, and machine hours or cost per part.</span>
            </p>
          ) : null}
          <p className="val-sub">
            {compact && s.parts === 0
              ? "Import your shop’s actual hours or costs in Your shop › Actual costs; parts of this run are compared here."
              : `Error is ScaleCAD’s estimate against your actual: +10% means ScaleCAD said 10% more. Compared with the estimate for the same part, method and quantity${data.calibration ? ", from before your calibration" : ""}.`}
            {s.not_compared ? ` ${s.not_compared} ${s.not_compared === 1 ? "actual isn’t" : "actuals aren’t"} comparable (method not priced, or quantity outside the priced ones).` : ""}
          </p>
        </>
      )}
    </Panel>
  );
}
