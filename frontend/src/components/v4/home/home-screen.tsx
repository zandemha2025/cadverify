"use client";

/**
 * Home (board P1): what needs you, recent records, setup, and a drop target to
 * check a part. Every count is loaded from the organization's data; a source
 * that fails is named in one alert with Retry, and nothing it would have
 * produced is shown as zero. The Get started overlay (X9) opens over Home.
 */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { Chip, Fig, Figs, Panel, cx } from "../ui";
import { Column, Frame, Head } from "./frame";
import { DropZone } from "./drop";
import { PartialAlert, NoneYet, Skeleton, InlineFailed } from "./states";
import { PartThumb } from "./thumb";
import { useGetStarted } from "./welcome";
import * as api from "./data";
import { buildQueue, homeFacts, recentRows, setupSteps, STEP_CHIP, type HomeInput, type InvolvedPart, type QueueItem } from "./home-derive";
import { verdictOf } from "./parts-derive";
import type { MakeRow } from "./model";
import "./home.css";

type Source = "records" | "parts" | "make" | "machines" | "changes" | "actuals" | "portfolio" | "rates";

const SOURCE_NAME: Record<Source, string> = {
  records: "records",
  parts: "parts",
  make: "machine verdicts",
  machines: "machines",
  changes: "changes to review",
  actuals: "actual costs",
  portfolio: "programs and cost inputs",
  rates: "rates",
};

const ALL: Source[] = ["records", "parts", "make", "machines", "changes", "actuals", "portfolio", "rates"];

function useHomeData() {
  const [input, setInput] = React.useState<HomeInput>({
    records: null,
    recordsMore: false,
    parts: null,
    partsTotal: null,
    make: null,
    machines: null,
    changes: null,
    actuals: null,
    posture: null,
    rates: null,
    programs: null,
    withVolume: null,
  });
  const [failed, setFailed] = React.useState<Set<Source>>(new Set());
  const [pending, setPending] = React.useState<Set<Source>>(new Set(ALL));

  const run = React.useCallback((which: Source[], fresh: boolean) => {
    setPending((p) => new Set([...p, ...which]));
    setFailed((f) => new Set([...f].filter((s) => !which.includes(s))));
    const done = (s: Source, ok: boolean) => {
      setPending((p) => {
        const n = new Set(p);
        n.delete(s);
        return n;
      });
      if (!ok) setFailed((f) => new Set([...f, s]));
    };
    const patch = (p: Partial<HomeInput>) => setInput((cur) => ({ ...cur, ...p }));
    const go = <T,>(s: Source, p: Promise<T>, on: (v: T) => void) =>
      p.then(
        (v) => {
          on(v);
          done(s, true);
        },
        () => done(s, false),
      );
    for (const s of which) {
      if (s === "records") go(s, api.records(fresh), (b) => patch({ records: b.cost_decisions, recordsMore: b.has_more }));
      if (s === "parts") go(s, api.catalogPage(1, fresh), (b) => patch({ parts: b.rows, partsTotal: api.catalogTotal(b.facets) }));
      if (s === "make") go(s, api.makeRollup(fresh), (b) => patch({ make: b.summary }));
      if (s === "machines") go(s, api.machines(fresh), (m) => patch({ machines: m }));
      if (s === "changes") go(s, api.changes(fresh), (c) => patch({ changes: c }));
      if (s === "actuals") go(s, api.actualCount(fresh), (n) => patch({ actuals: n }));
      if (s === "portfolio")
        go(s, api.portfolio(fresh), (p) => {
          const f = api.programFacts(p);
          patch({ posture: p.summary.posture ?? null, programs: f.programs, withVolume: f.withVolume });
        });
      if (s === "rates") go(s, api.rateSource(fresh), (r) => patch({ rates: r }));
    }
  }, []);

  React.useEffect(() => {
    run(ALL, false);
  }, [run]);

  return { input, failed, pending, retry: () => run([...failed], true) };
}

function factNodes(facts: ReturnType<typeof homeFacts>): React.ReactNode[] {
  return facts.map((f, i) =>
    f.href ? (
      <Link key={i} className="h-fact" href={f.href}>
        <b className="num">{f.n}</b> {f.t}
      </Link>
    ) : (
      <React.Fragment key={i}>
        <b className="num">{f.n}</b> {f.t}
      </React.Fragment>
    ),
  );
}

export function HomeScreen() {
  const { input, failed, pending, retry } = useHomeData();
  const queue = React.useMemo(() => buildQueue(input), [input]);
  // The queue is "known" once the sources that feed it have answered (or failed).
  const queueSettled = (["records", "parts", "make", "machines", "changes", "actuals", "rates", "portfolio"] as Source[]).every((s) => !pending.has(s));
  const facts = homeFacts(input, queueSettled ? queue.length : null);
  const recent = recentRows(input.records);
  const steps = setupSteps(input, { records: failed.has("records"), machines: failed.has("machines"), programs: failed.has("portfolio"), actuals: failed.has("actuals") });
  const doneSteps = steps.filter((s) => s.state === "done").length;
  const newOrg = input.records != null && input.records.length === 0;
  const guide = useGetStarted(newOrg);

  const [pick, setPick] = React.useState<string | null>(null);
  const sel = queue.find((q) => q.key === pick) ?? queue[0] ?? null;
  const sheetRef = React.useRef<HTMLElement>(null);
  const headRef = React.useRef<HTMLDivElement>(null);

  const missing = [...failed].map((s) => SOURCE_NAME[s]);
  const retrying = [...failed].some((s) => pending.has(s));

  return (
    <Frame label="Home">
      <Head ref={headRef}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <h1 className="ptitle">Home</h1>
            {facts.length ? (
              <p className="pmeta" style={{ marginTop: 6 }}>
                {factNodes(facts).map((n, i) => (
                  <span key={i}>{n}</span>
                ))}
              </p>
            ) : null}
          </div>
          <button type="button" className="btn ghost sm" onClick={guide.openGuide}>
            Start here
          </button>
        </div>
      </Head>
      <Column head={headRef}>
        {missing.length ? (
          <section className="panel" aria-label="Some data didn't load">
            <PartialAlert missing={missing} rest={pending.size === 0 ? "Everything else on Home is complete." : undefined} onRetry={retry} busy={retrying} />
          </section>
        ) : null}

        <Panel title="Start" note={<Link href={R.check}>Help me choose</Link>}>
          <div className="h-start">
            <DropZone />
            <div className="h-alt">
              <button type="button" onClick={guide.runSample}>
                <span>
                  Run an example<small>Sample bracket, real engine · uses 1 check</small>
                </span>
                <i aria-hidden="true">→</i>
              </button>
              <Link href={R.studio}>
                <span>
                  Make a simple part<small>Plate, bracket or enclosure</small>
                </span>
                <i aria-hidden="true">→</i>
              </Link>
              <Link href={R.triage}>
                <span>
                  Sort a parts list<small>Pilot · makeable, outside, new capability</small>
                </span>
                <i aria-hidden="true">→</i>
              </Link>
            </div>
          </div>
        </Panel>

        <div className="h-cols">
          <Panel title="Needs attention" note={queueSettled ? <span className="num">{queue.length}</span> : null}>
            {!queueSettled && queue.length === 0 ? (
              <Skeleton rows={4} label="Loading what needs attention" />
            ) : queue.length === 0 ? (
              <NoneYet title="Nothing needs attention">{missing.length ? "Some sources didn't load; retry above." : "Machines, rates and records are current."}</NoneYet>
            ) : (
              <div className="list" role="list" aria-label="Needs attention">
                {queue.map((q) => (
                  <div role="listitem" key={q.key}>
                    <button
                      type="button"
                      className={cx("lrow h-q", sel?.key === q.key && "on")}
                      aria-pressed={sel?.key === q.key}
                      onClick={() => {
                        setPick(q.key);
                        if (window.matchMedia("(max-width:900px)").matches) {
                          const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
                          requestAnimationFrame(() => sheetRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }));
                        }
                      }}
                    >
                      <span className={`h-ic t-${q.tone}`} aria-hidden="true">
                        {q.icon}
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <b>{q.title}</b>
                        <small>{q.short}</small>
                      </span>
                      <span className="h-n num">{q.n}</span>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel
            title="Recent records"
            note={
              input.records && input.records.length ? (
                <Link href={R.records}>
                  All {input.records.length}
                  {input.recordsMore ? "+" : ""}
                </Link>
              ) : null
            }
          >
            {input.records == null ? (
              failed.has("records") ? (
                <InlineFailed what="records" onRetry={retry} />
              ) : (
                <Skeleton rows={5} label="Loading recent records" />
              )
            ) : recent.length === 0 ? (
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
              <div style={{ padding: "0 6px 8px" }} role="list" aria-label="Recent records">
                {recent.map((r) => (
                  <div role="listitem" key={r.id}>
                    <Link className="h-rr" href={r.href}>
                      <span style={{ minWidth: 0 }}>
                        <b>{r.file}</b>
                        <small>{r.sub}</small>
                      </span>
                      <span className="h-t">{r.time}</span>
                    </Link>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>

        <section className="panel" aria-label="Setup">
          <div className="ph">
            <h2>Setup</h2>
            <span>
              {doneSteps} of {steps.length} done
            </span>
          </div>
          <div className="h-steps">
            {steps.map((s) => {
              const chip = STEP_CHIP[s.state];
              return (
                <div key={s.key} className={cx("h-st", s.state === "locked" && "lock")}>
                  <span className="h-bar" aria-hidden="true">
                    <i style={{ transform: `scaleX(${s.pct / 100})` }} />
                  </span>
                  <b>{s.title}</b>
                  <span>{s.meta}</span>
                  <Chip tone={chip.tone}>{chip.label}</Chip>
                  {s.act ? <Link href={s.act.href}>{s.act.label}</Link> : null}
                </div>
              );
            })}
          </div>
        </section>
      </Column>

      <SelectedSheet sel={sel} settled={queueSettled} sheetRef={sheetRef} />
      {guide.overlay}
    </Frame>
  );
}

function SelectedSheet({ sel, settled, sheetRef }: { sel: QueueItem | null; settled: boolean; sheetRef: React.RefObject<HTMLElement | null> }) {
  const lazy = useLazyParts(sel);
  return (
    <aside className="sheet" aria-label="Selected item" ref={sheetRef as React.RefObject<HTMLElement>}>
      {sel ? (
        <>
          <div className="top">
            <h2 className="stitle">{sel.name}</h2>
            <p className="smeta">{sel.meta}</p>
            <Figs>
              {sel.figs.map((g, i) => (
                <Fig key={i} k={g.k} v={g.v} sub={g.s} tone={g.c} />
              ))}
            </Figs>
          </div>
          <div className="scroll swap" key={sel.key}>
            <Involved label={sel.partsLabel} parts={sel.lazyBuckets ? lazy.parts : sel.parts} loading={Boolean(sel.lazyBuckets) && lazy.loading} failed={lazy.failed} more={sel.lazyBuckets ? lazy.more : 0} />
            {sel.kv.length ? (
              <div className="kv">
                {sel.kv.map(([k, v], i) => (
                  <React.Fragment key={i}>
                    <span>{k}</span>
                    <b>{v}</b>
                  </React.Fragment>
                ))}
              </div>
            ) : null}
            <div className="h-sheetacts">
              <Link className="btn ink" href={sel.act.href}>
                {sel.act.label}
              </Link>
              {sel.alt ? (
                <Link className="btn" href={sel.alt.href}>
                  {sel.alt.label}
                </Link>
              ) : null}
            </div>
            {sel.foot ? <p className="h-foot">{sel.foot}</p> : null}
          </div>
        </>
      ) : settled ? (
        <>
          <div className="top">
            <h2 className="stitle">Nothing needs attention</h2>
            <p className="smeta">Items appear here when a part, machine, rate or record needs you</p>
          </div>
          <div className="scroll">
            <div className="h-sheetacts">
              <Link className="btn ink" href={R.parts}>
                Parts
              </Link>
              <Link className="btn" href={R.shop}>
                Your shop
              </Link>
            </div>
          </div>
        </>
      ) : (
        <Skeleton rows={5} label="Loading" />
      )}
    </aside>
  );
}

function Involved({ label, parts, loading, failed, more }: { label: string; parts: InvolvedPart[]; loading: boolean; failed: boolean; more: number }) {
  if (!label) return null;
  if (loading) return <Skeleton rows={2} label="Loading parts" />;
  if (failed) return <p className="h-foot">Couldn&apos;t load the parts. Open the Parts list to see them.</p>;
  if (!parts.length) return null;
  return (
    <>
      <div className="gh">
        <span>{label}</span>
        <span className="num">{more > 0 ? `${parts.length} of ${parts.length + more}` : ""}</span>
      </div>
      <div className="h-involved">
        {parts.map((p, i) => {
          const body = (
            <>
              <PartThumb size={56} glyph={30} />
              <b title={p.name}>{p.name}</b>
              <span>{p.note}</span>
            </>
          );
          return p.href ? (
            <Link key={i} className="h-inv" href={p.href}>
              {body}
            </Link>
          ) : (
            <span key={i}>{body}</span>
          );
        })}
      </div>
    </>
  );
}

/** Parts for a queue item whose rollup only carries counts: loads the bucket(s) when the item is picked. */
function useLazyParts(sel: QueueItem | null) {
  const [state, setState] = React.useState<{ key: string; parts: InvolvedPart[]; more: number; failed: boolean } | null>(null);
  const key = sel?.lazyBuckets ? sel.key : null;
  React.useEffect(() => {
    if (!key || !sel?.lazyBuckets) return;
    let live = true;
    const buckets = sel.lazyBuckets;
    const staleOnly = Boolean(sel.lazyStale);
    Promise.all(buckets.map((b) => api.makeBucket(b)))
      .then((pages) => {
        if (!live) return;
        const rows: MakeRow[] = pages.flatMap((p) => p.rows).filter((r) => !staleOnly || r.makeability.stale);
        const parts = rows.map((r) => ({ name: r.filename, note: verdictOf(r, r.makeability).where, href: R.part(r.part_key) }));
        setState({ key, parts: parts.slice(0, 6), more: Math.max(0, parts.length - 6), failed: false });
      })
      .catch(() => live && setState({ key, parts: [], more: 0, failed: true }));
    return () => {
      live = false;
    };
  }, [key, sel?.lazyBuckets, sel?.lazyStale]);
  const mine = state && state.key === key ? state : null;
  return { parts: mine?.parts ?? [], more: mine?.more ?? 0, failed: mine?.failed ?? false, loading: Boolean(key) && !mine };
}
