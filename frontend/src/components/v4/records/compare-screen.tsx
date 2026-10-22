"use client";

/**
 * Compare (board P3): pick two saved records and see what's different — the
 * cheapest way and your machines' way at a shared quantity, every way side by
 * side (cheapest workable material each), make-now against tooling with the
 * engine's crossover, and the differences in plain words. Every figure comes
 * from the two records' own estimates; quantities are never interpolated.
 * Replaces Verify › Compare and /cost-decisions/compare.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { R, TABS } from "../routes";
import { Content, PageHead, cx } from "../ui";
import { useRecordList, usePartContext, useRecords } from "./api";
import { Glyph, LoadFailed, NoneYet, RecSheet, RecWorld, Skeleton } from "./common";
import { KeptStill } from "./kept-still";
import {
  chartPaths,
  cheapestAt,
  cheapestWorkableAt,
  inHouseAt,
  rangeOf,
  recordFacts,
  sharedQuantities,
  summaryLines,
  toolingChart,
  wayTable,
  waysCount,
  type RecordFacts,
} from "./facts";
import { VERDICT, conditionsTag, conditionsText, dateUtc, money, num, parts, rowTime, short, sizeText, volumeText, way, wayLower } from "./words";
import type { CostDecisionDetail, CostDecisionSummary } from "@/lib/api";

export function CompareScreen() {
  const sp = useSearchParams();
  const router = useRouter();
  const list = useRecordList();
  const rows = list.rows;
  const [find, setFind] = React.useState("");
  const [q, setQ] = React.useState<number | null>(null);
  const [side, setSide] = React.useState<"a" | "b">("b");
  const [si, setSi] = React.useState<number | null>(null);

  // A and B: from the URL, else the newest record and another record of the same part (else the next newest).
  const pa = sp?.get("a") ?? null;
  const pb = sp?.get("b") ?? null;
  const a = pa ?? rows?.[0]?.id ?? null;
  const b = React.useMemo(() => {
    if (pb && pb !== a) return pb;
    if (!rows || !a) return null;
    const ra = rows.find((r) => r.id === a);
    const same = ra?.mesh_hash ? rows.find((r) => r.id !== a && r.mesh_hash === ra.mesh_hash) : undefined;
    return (same ?? rows.find((r) => r.id !== a))?.id ?? null;
  }, [pb, a, rows]);

  const go = (na: string | null, nb: string | null) => {
    const p = new URLSearchParams();
    if (na) p.set("a", na);
    if (nb) p.set("b", nb);
    setQ(null);
    setSi(null);
    router.replace(`${R.compare}?${p.toString()}`, { scroll: false });
  };

  const [A, B] = useRecords([a, b]);
  const ctxA = usePartContext(A.detail?.mesh_hash);
  const ctxB = usePartContext(B.detail?.mesh_hash);

  const tabs = TABS.parts;
  const n = rows?.length ?? 0;

  // ── whole-page states ─────────────────────────────────────────────────
  if (!rows || (rows.length < 2 && !list.more)) {
    return (
      <RecWorld label="Compare records">
        <PageHead title="Compare" meta={[rows ? (rows.length ? "1 record" : "No records") : list.error ? "Records didn't load" : "Loading records"]} tabs={tabs} tabsLabel="Parts" wide />
        <Content full>
          <section className="panel">
            {!rows ? (
              list.error ? (
                <LoadFailed what="records" detail={list.error} onRetry={() => void list.reload()} />
              ) : (
                <Skeleton rows={4} label="Loading records" />
              )
            ) : (
              <NoneYet
                title="Compare needs two records"
                actions={
                  <>
                    <Link className="btn sm ink" href={R.check}>
                      Check a part
                    </Link>
                    <Link className="btn sm" href={R.records}>
                      Records
                    </Link>
                  </>
                }
              >
                Check the part again with other conditions, or another part.
              </NoneYet>
            )}
          </section>
        </Content>
      </RecWorld>
    );
  }

  const ra = A.detail?.result ?? null;
  const rb = B.detail?.result ?? null;
  const shared = ra && rb ? sharedQuantities(ra, rb) : [];
  const qv = q != null && shared.includes(q) ? q : shared.includes(10) ? 10 : shared[shared.length - 1] ?? null;
  const qw = qv != null ? num(qv) : "—";
  const fa = recordFacts(ra);
  const fb = recordFacts(rb);
  const tagA = conditionsTag(ctxA?.service_environment);
  const tagB = conditionsTag(ctxB?.service_environment);
  const samePart = !!A.detail && !!B.detail && A.detail.mesh_hash === B.detail.mesh_hash;
  const ready = !!A.detail && !!B.detail;

  const sideOf = (d: CostDecisionDetail | null, f: RecordFacts, tag: string | null, k: "A" | "B") => {
    const r = d?.result ?? null;
    // The cheapest way that works as drawn, the one the table marks; the engine's pick is said when it differs.
    const rec = r && qv != null ? cheapestWorkableAt(r, qv) : null;
    const pick = r && qv != null ? cheapestAt(r, qv) : null;
    const ih = r && qv != null ? inHouseAt(r, qv)[0] ?? null : null;
    const verdict = f.verdict && VERDICT[f.verdict] ? VERDICT[f.verdict][0].toLowerCase() : "not checked";
    return {
      k,
      title: d ? `${f.material}${f.envDeclared === true ? `, for ${tag ?? "its conditions"}` : f.envDeclared === false ? ", no conditions" : ""}` : "Loading",
      what: d ? `${f.material}, ${f.envDeclared === true ? tag ?? "with conditions" : f.envDeclared === false ? "no conditions" : "conditions not recorded"}` : "",
      rec,
      ih,
      cost: rec ? money(rec.usd) : "—",
      by: rec
        ? `cheapest that works at ${qw}, ${wayLower(rec.process)}${rec.leadLo != null && rec.leadHi != null ? ` · ${Math.round(rec.leadLo)}–${Math.round(rec.leadHi)} days` : ""}${pick && pick.process !== rec.process ? ` · ScaleCAD’s pick: ${wayLower(pick.process)}, ${money(pick.usd)}` : ""}`
        : shared.length
          ? `no pick at ${qw}`
          : "no shared quantity",
      mine: ih ? `${ih.machine ?? "your machine"}, ${money(ih.usd)}` : verdict === "in-house" ? "in-house, not priced here" : verdict,
    };
  };
  const sa = sideOf(A.detail, fa, tagA, "A");
  const sb = sideOf(B.detail, fb, tagB, "B");
  const ratio = sa.rec && sb.rec && sa.rec.usd > 0 ? sb.rec.usd / sa.rec.usd : null;
  const rA = rangeOf(sa.rec?.est);
  const rB = rangeOf(sb.rec?.est);
  const lohi = (r: ReturnType<typeof rangeOf>, usd: number) => {
    const p = (r?.pct ?? 0) / 100;
    return [usd * (1 - p), usd * (1 + p)];
  };
  const overlap = (() => {
    if (!sa.rec || !sb.rec) return false;
    const [a0, a1] = lohi(rA, sa.rec.usd);
    const [b0, b1] = lohi(rB, sb.rec.usd);
    return b0 <= a1 && a0 <= b1;
  })();

  const table = ready && qv != null ? wayTable(ra, rb, qv) : [];

  const envLong = (f: RecordFacts, env: Record<string, unknown> | null | undefined) =>
    f.envDeclared === true ? conditionsText(env) ?? "declared when checked" : f.envDeclared === false ? "none" : "not recorded";
  const ways = (r: typeof ra) => {
    if (!r || qv == null) return "—";
    const c = waysCount(r, qv);
    return `${c.ok}${c.redesign ? `, plus ${c.redesign} after a redesign` : ""}`;
  };
  const pickText = (s: typeof sa, r: ReturnType<typeof rangeOf>) => (s.rec ? `${s.cost}, ${wayLower(s.rec.process)}${r ? `, range ${r.text}` : ""}` : "no pick");
  const mineText = (s: typeof sa, f: RecordFacts) => (s.ih ? `${s.ih.machine ?? "your machine"}, ${wayLower(s.ih.process)}, ${money(s.ih.usd)}` : f.verdict && VERDICT[f.verdict] ? VERDICT[f.verdict][0].toLowerCase() : "not checked");
  const lead = (s: typeof sa) => (s.rec && s.rec.leadLo != null && s.rec.leadHi != null ? `${Math.round(s.rec.leadLo)}–${Math.round(s.rec.leadHi)} days` : "—");
  const diffs = ready
    ? [
        { c: "#5B3FC4", t: "Service conditions", s: `A: ${envLong(fa, ctxA?.service_environment)}. B: ${envLong(fb, ctxB?.service_environment)}.` },
        { c: "#141414", t: `Cheapest at ${qw}`, s: `A: ${pickText(sa, rA)}. B: ${pickText(sb, rB)}.` },
        { c: "#146C43", t: "On your machines", s: `A: ${mineText(sa, fa)}. B: ${mineText(sb, fb)}.` },
        { c: "#8C5200", t: "Lead time", s: `A: ${lead(sa)}. B: ${lead(sb)}.` },
        { c: "#B42318", t: "Materials ruled out by conditions", s: `A: ${fa.ruledOut.length}${fa.ruledOut.length ? ` (${fa.ruledOut.join(", ")})` : ""}. B: ${fb.ruledOut.length}${fb.ruledOut.length ? ` (${fb.ruledOut.join(", ")})` : ""}.` },
        { c: "#3E434A", t: "Processes that can make it", s: `A: ${ways(ra)}. B: ${ways(rb)}.` },
        ...(A.detail!.engine_version !== B.detail!.engine_version ? [{ c: "#5F656E", t: "Engine", s: `A: ${A.detail!.engine_version ?? "not recorded"}. B: ${B.detail!.engine_version ?? "not recorded"}.` }] : []),
      ]
    : [];
  const same: [string, string][] = ready
    ? [
        ...(samePart && ra ? ([["Part", `${sizeText(ra.geometry?.bbox_mm)} · ${volumeText(ra.geometry?.volume_cm3)}`]] as [string, string][]) : []),
        ...(A.detail!.engine_version === B.detail!.engine_version ? ([["Engine", `${A.detail!.engine_version ?? "not recorded"} · ${dateUtc(A.detail!.created_at)}`]] as [string, string][]) : []),
      ]
    : [];

  // pickers: the other side's record is left out, so A and B can't match.
  const label = (r: CostDecisionSummary) => `${r.label || r.filename} · ${summaryLines(r).what} · ${rowTime(r.created_at)} · #${short(r.id)}`;
  const needle = find.trim().toLowerCase();
  const matches = (r: CostDecisionSummary) => !needle || r.filename.toLowerCase().includes(needle) || r.id.toLowerCase().includes(needle.replace(/^#/, "")) || (r.label ?? "").toLowerCase().includes(needle);
  // The picked record stays in its list even when the search hides the rest.
  const optsFor = (other: string | null, mine: string | null) => rows.filter((r) => r.id !== other && (matches(r) || r.id === mine));
  const optsA = optsFor(b, a);
  const optsB = optsFor(a, b);
  const loadedHere = (id: string | null) => !id || rows.some((r) => r.id === id);

  const head = ready ? (samePart ? A.detail!.filename : `${A.detail!.filename} vs ${B.detail!.filename}`) : "Loading the two records";

  return (
    <RecWorld label="Compare records">
      <PageHead
        title="Compare"
        meta={[
          head,
          ...(ready
            ? [
                <>
                  <b>A</b> #{short(a)} · {sa.what}
                </>,
                <>
                  <b>B</b> #{short(b)} · {sb.what}
                </>,
              ]
            : []),
        ]}
        tabs={tabs}
        tabsLabel="Parts"
      />
      <Content>
        {A.error || B.error ? (
          <section className="panel">
            <LoadFailed what={A.error ? "record A" : "record B"} detail={A.error ?? B.error} onRetry={() => void (A.error ? A.retry() : B.retry())} />
          </section>
        ) : null}
        <div className="pair">
          {[sa, sb].map((s, i) => {
            const d = i === 0 ? A.detail : B.detail;
            return (
              <div className="side" key={s.k}>
                <span className="tag2">
                  <i>{s.k}</i>
                  <b>{s.title}</b>
                </span>
                <span className="idl nm" title={`Record ${i === 0 ? a : b}`}>
                  {d ? `${d.label || d.filename} · checked ${rowTime(d.created_at)}` : `Record ${s.k}`}
                </span>
                {d ? (
                  <KeptStill meshHash={d.mesh_hash} filename={d.filename} label={`Part ${s.k}, ${d.filename}. Drag to turn it.`} />
                ) : (
                  <span className="still" role="img" aria-label={`Part ${s.k}`}>
                    <span className="shade" />
                    <Glyph size={84} />
                  </span>
                )}
                {d ? (
                  <>
                    <span className="price num">{s.cost}</span>
                    <span className="by">{s.by}</span>
                    <span className="mine">
                      On your machines: <b>{s.mine}</b>
                    </span>
                  </>
                ) : (
                  <Skeleton rows={2} label={`Loading record ${s.k}`} />
                )}
              </div>
            );
          })}
        </div>

        <section className="panel" aria-label="Each process, A and B">
          <div className="ph">
            <h2>Each process at {qw}</h2>
            <span>Cheapest workable material per process · range in small type</span>
          </div>
          {!ready ? (
            <Skeleton rows={4} label="Loading the ways" />
          ) : (
            <div className="tbl" role="region" aria-label="Cost of each process for A and B" tabIndex={0}>
              <div className="tr th">
                <span>Process</span>
                <span>A</span>
                <span>B</span>
                <span>B vs A</span>
              </div>
              {table.map((t) => (
                <div className={cx("tr", t.pick && "pick")} key={t.process}>
                  <span>{way(t.process)}</span>
                  <Cell c={t.a} />
                  <Cell c={t.b} />
                  <span className={cx("d", t.pct != null && t.pct < 0 && "lo", t.pct != null && t.pct > 0 && "hi")}>{t.pct == null ? "—" : `${t.pct > 0 ? "+" : ""}${t.pct}%`}</span>
                </div>
              ))}
              {qv == null ? <p style={{ margin: 8, color: "var(--ink3)", fontSize: 13 }}>No shared quantity.</p> : !table.length ? <p style={{ margin: 8, color: "var(--ink3)", fontSize: 13 }}>No prices at this quantity.</p> : null}
            </div>
          )}
        </section>

        <ToolingPanel A={A.detail} B={B.detail} fa={fa} fb={fb} side={side} onSide={(s) => { setSide(s); setSi(null); }} si={si} onSi={setSi} />
      </Content>

      <RecSheet label="What's different">
        <div className="top">
          <h2 className="stitle">A vs B at {qw}</h2>
          <p className="smeta">{ready ? `${sa.what.replace(/^./, (c) => c.toUpperCase())} vs ${sb.what.toLowerCase()}` : "Loading"}</p>
          <div className="figs" aria-live="polite">
            <div className="fig">
              <span>Cheapest, A</span>
              <b className="num">{sa.cost}</b>
              <small>{sa.rec ? way(sa.rec.process) : "—"}</small>
            </div>
            <div className="fig">
              <span>Cheapest, B</span>
              <b className="num">{sb.cost}</b>
              <small>{sb.rec ? way(sb.rec.process) : "—"}</small>
            </div>
            <div className="fig">
              <span>B ÷ A</span>
              <b className="num">{ratio ? `${ratio.toFixed(2)}×` : "—"}</b>
              <small>{overlap ? "Ranges overlap" : ratio ? `at ${qw}` : ""}</small>
            </div>
          </div>
        </div>
        <div className="scroll">
          <div className="gh">
            <span>Records</span>
            <span className="num">
              {optsA.length + (b && !optsA.some((r) => r.id === b) ? 1 : 0)} of {n}
              {list.more ? "+" : ""}
            </span>
          </div>
          <label className="find2">
            Find a record
            <input type="search" placeholder="File name or record number" value={find} onChange={(e) => setFind(e.target.value)} />
          </label>
          <label className="pick2">
            <i aria-hidden="true">A</i>
            <select aria-label="Record A" value={a ?? ""} onChange={(e) => go(e.target.value, b)}>
              {!loadedHere(a) && a ? <option value={a}>Record #{short(a)}</option> : null}
              {optsA.map((r) => (
                <option key={r.id} value={r.id}>
                  {label(r)}
                </option>
              ))}
            </select>
          </label>
          <label className="pick2">
            <i aria-hidden="true">B</i>
            <select aria-label="Record B" value={b ?? ""} onChange={(e) => go(a, e.target.value)}>
              {!loadedHere(b) && b ? <option value={b}>Record #{short(b)}</option> : null}
              {optsB.map((r) => (
                <option key={r.id} value={r.id}>
                  {label(r)}
                </option>
              ))}
            </select>
          </label>
          <div style={{ display: "flex", gap: 8, padding: "6px 12px 0", flexWrap: "wrap", alignItems: "center" }}>
            <button type="button" className="btn sm" onClick={() => { setSide(side === "a" ? "b" : "a"); go(b, a); }} disabled={!a || !b}>
              Swap A and B
            </button>
            {list.more ? (
              <button type="button" className="btn sm" onClick={() => void list.loadMore()} disabled={list.loadingMore}>
                {list.loadingMore ? "Loading records…" : "Load older records"}
              </button>
            ) : null}
          </div>
          {list.moreError ? (
            <p className="err2" role="alert">
              {list.moreError}
            </p>
          ) : null}
          {ready && !samePart ? <p className="warn2">Different parts. Prices differ by shape as well as inputs.</p> : null}

          <div className="gh">
            <span>Quantity</span>
            <span />
          </div>
          {!ready ? null : shared.length ? (
            <div style={{ padding: "0 12px 6px" }}>
              <span className="seg" role="group" aria-label="Quantity">
                {shared.map((v) => (
                  <button key={v} type="button" className={cx("num", v === qv && "on")} aria-pressed={v === qv} onClick={() => setQ(v)}>
                    {num(v)}
                  </button>
                ))}
              </span>
            </div>
          ) : (
            <p className="warn2">No shared quantity. Pick two records priced at the same quantities.</p>
          )}

          <div className="gh">
            <span>What&apos;s different</span>
            <span>A · B</span>
          </div>
          {ready ? (
            <div>
              {diffs.map((d, i) => (
                <div className="diff" key={d.t}>
                  <i style={{ background: d.c }} aria-hidden="true">
                    {i + 1}
                  </i>
                  <span>
                    <b>{d.t}</b>
                    <span>{d.s}</span>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <Skeleton rows={4} label="Loading the differences" />
          )}
          {same.length ? (
            <>
              <div className="gh">
                <span>Same in both</span>
                <span />
              </div>
              <div className="kv ev">
                {same.map(([k, v]) => (
                  <React.Fragment key={k}>
                    <span>{k}</span>
                    <b>{v}</b>
                  </React.Fragment>
                ))}
              </div>
            </>
          ) : null}
          <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap" }}>
            {a ? (
              <Link className="btn sm" href={R.record(a)}>
                Open A
              </Link>
            ) : null}
            {b ? (
              <Link className="btn sm" href={R.record(b)}>
                Open B
              </Link>
            ) : null}
          </div>
        </div>
      </RecSheet>
    </RecWorld>
  );
}

function Cell({ c }: { c: ReturnType<typeof wayTable>[number]["a"] }) {
  if (!c) return <span>—</span>;
  if (c.state === "out")
    return (
      <span>
        <b className="x">Ruled out</b>
        <small>conditions</small>
      </span>
    );
  return (
    <span>
      <b className={cx(c.state === "redesign" && "w")}>{money(c.usd)}</b>
      <small>
        {c.band != null ? `±${c.band}%` : "no range"}
        {c.state === "redesign" ? " · needs redesign" : ""}
      </small>
    </span>
  );
}

function ToolingPanel({
  A,
  B,
  fa,
  fb,
  side,
  onSide,
  si,
  onSi,
}: {
  A: CostDecisionDetail | null;
  B: CostDecisionDetail | null;
  fa: RecordFacts;
  fb: RecordFacts;
  side: "a" | "b";
  onSide: (s: "a" | "b") => void;
  si: number | null;
  onSi: (i: number) => void;
}) {
  const d = side === "a" ? A : B;
  const chart = d ? toolingChart(d.result) : null;
  const i = chart ? Math.max(0, Math.min(chart.qs.length - 1, si ?? chart.qs.length - 1)) : 0;
  const p = chart ? chartPaths(chart, i) : null;
  const qAt = chart ? chart.qs[i] : null;
  const mk = chart ? chart.make[i] : null;
  const tl = chart ? chart.tool[i] : null;
  const anyPrice = d ? d.result.estimates.some((e) => !e.environment_excluded) : false;
  return (
    <section className="panel" aria-label="Make now or tooling">
      <div className="ph">
        <h2>Make now or tooling</h2>
        <span className="seg" role="group" aria-label="Record">
          {(["a", "b"] as const).map((k) => (
            <button key={k} type="button" className={cx(side === k && "on")} aria-pressed={side === k} onClick={() => onSide(k)}>
              {k.toUpperCase()} · {(k === "a" ? fa : fb).material}
            </button>
          ))}
        </span>
      </div>
      {!d ? (
        <Skeleton rows={3} label="Loading the record" />
      ) : chart && p && qAt != null ? (
        <>
          <div className="lg">
            <span>
              <i aria-hidden="true" />
              Make now: cheapest way without tooling
            </span>
            <span>
              <i className="dash" aria-hidden="true" />
              With tooling: {way(chart.toolWay)}
              {chart.toolNeedsRedesign ? " · needs redesign" : ""}
            </span>
          </div>
          <div className="chart">
            <svg viewBox="0 0 600 190" preserveAspectRatio="none" aria-hidden="true">
              <path d="M0 189.5H600" stroke="rgba(20,24,31,.12)" />
              {p.cross ? <path d={p.cross} stroke="#5F656E" strokeDasharray="3 4" fill="none" /> : null}
              <path d={p.make} stroke="#141414" strokeWidth="2" fill="none" vectorEffect="non-scaling-stroke" />
              <path d={p.tool} stroke="#8C5200" strokeWidth="2" strokeDasharray="6 5" fill="none" vectorEffect="non-scaling-stroke" />
              <path d={p.marker} stroke="#1F4FC4" strokeWidth="1.5" fill="none" />
            </svg>
            <div className="ax">
              <span>{num(chart.qs[0])}</span>
              <span>{chart.crossover != null ? `engine crossover ≈ ${num(Math.round(chart.crossover))}` : "no crossover priced"}</span>
              <span>{num(chart.qs[chart.qs.length - 1])}</span>
            </div>
            <label style={{ display: "block", fontSize: 12.5, color: "var(--ink2)", marginTop: 8 }}>
              Quantity
              <input type="range" min={0} max={chart.qs.length - 1} step={1} value={i} aria-valuetext={parts(qAt)} onChange={(e) => onSi(Number(e.target.value))} />
            </label>
            <div className="rd" aria-live="polite">
              <span>
                At <b className="num">{parts(qAt)}</b>: make now <b className="num">{mk != null ? `${money(mk)} (${wayLower(chart.makeWay[i])})` : "—"}</b> · with tooling <b className="num">{tl != null ? money(tl) : "—"}</b>
              </span>
              <span>
                <b>{mk == null || tl == null ? "One process has no price here" : mk <= tl ? "Make now is cheaper" : `Tooling is cheaper${chart.toolNeedsRedesign ? ", after a redesign" : ""}`}</b>
              </span>
            </div>
            <p style={{ margin: "6px 0 0", color: "var(--ink3)", fontSize: 12.5 }}>Stops only at priced quantities.</p>
          </div>
        </>
      ) : (
        <div className="empty" style={{ padding: "18px 24px" }}>
          <b>No tooling route</b>
          <span>{!anyPrice ? "No process without tooling is priced: its conditions rule every process out." : "The engine found no tooling process for this record."}</span>
        </div>
      )}
    </section>
  );
}
