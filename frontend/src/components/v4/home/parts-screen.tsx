"use client";

/**
 * Parts (board O8): every checked part with its machine verdict, way, unit cost
 * and findings. Search covers every part in the organization (it loads the
 * rest of the catalog when needed), filters live in the URL so a view can be
 * shared or linked from Home, and the sheet shows a part's peek or, with
 * nothing picked, what needs attention, decided parts and the parts library.
 */
import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { R, TABS } from "../routes";
import { Chip, Fig, Figs, SubNav, cx } from "../ui";
import { Column, Frame, Head } from "./frame";
import { InlineFailed, LoadMore, NoneYet, Skeleton } from "./states";
import { PartGlyph } from "./thumb";
import { LibraryPanel } from "./library";
import { JoinedWelcome } from "../onboard/teammate";
import { DeletePartButton } from "../datacontrol/delete-part";
import * as api from "./data";
import { buildQueue } from "./home-derive";
import {
  countBy,
  filterFromSearch,
  isFiltered,
  matches,
  NO_FILTER,
  partsFacts,
  peekFigs,
  priceText,
  searchFromFilter,
  verdictOf,
  VERDICT_FILTERS,
  type DecisionLite,
  type PartFilter,
  type Verdict,
} from "./parts-derive";
import type { MakeRow, MakeSummary, PartRow, RecordRow } from "./model";
import { longDate, sizeText, wayName } from "./words";
import "./home.css";

const SHOW = 48;
const MAX_PAGES = 20;

interface CatalogState {
  rows: PartRow[];
  page: number;
  more: boolean;
  total: number;
  facets: api.CatalogPage["facets"];
  truncated: boolean;
}

function useCatalog() {
  const [cat, setCatState] = React.useState<CatalogState | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const ref = React.useRef<CatalogState | null>(null);
  const busy = React.useRef(false);
  const setCat = (c: CatalogState | null) => {
    ref.current = c;
    setCatState(c);
  };

  const first = React.useCallback((fresh: boolean) => {
    setErr(null);
    api.catalogPage(1, fresh).then(
      (p) => setCat({ rows: p.rows, page: 1, more: p.pagination.has_more, total: api.catalogTotal(p.facets), facets: p.facets, truncated: p.truncated }),
      (e) => setErr(api.errorText(e)),
    );
  }, []);

  React.useEffect(() => first(false), [first]);

  /** Load further catalog pages until `need` rows are loaded (or all of them, for a search). */
  const ensure = React.useCallback(async (need: number) => {
    if (busy.current) return;
    busy.current = true;
    setLoadingMore(true);
    setErr(null);
    try {
      let c = ref.current;
      while (c && c.more && c.rows.length < need && c.page < MAX_PAGES) {
        const p = await api.catalogPage(c.page + 1);
        const seen = new Set(c.rows.map((r) => r.part_key));
        c = { ...c, rows: [...c.rows, ...p.rows.filter((r) => !seen.has(r.part_key))], page: c.page + 1, more: p.pagination.has_more };
        setCat(c);
      }
    } catch (e) {
      setErr(api.errorText(e));
    } finally {
      busy.current = false;
      setLoadingMore(false);
    }
  }, []);

  return {
    cat,
    err,
    loadingMore,
    retry: () => first(true),
    ensure,
    reload: () => {
      api.forget("/catalog");
      first(true);
    },
  };
}

function useMachineVerdicts() {
  const [state, setState] = React.useState<{ summary: MakeSummary; byPart: Map<string, MakeRow>; partial: boolean } | null>(null);
  const [failed, setFailed] = React.useState(false);
  const run = React.useCallback((fresh: boolean) => {
    setFailed(false);
    api
      .makeRollup(fresh)
      .then(async (r) => ({ summary: r.summary, ...(await api.makeIndex(r.summary, fresh)) }))
      .then(setState, () => setFailed(true));
  }, []);
  React.useEffect(() => run(false), [run]);
  return { make: state, failed, retry: () => run(true) };
}

export function PartsScreen() {
  const router = useRouter();
  const pathname = usePathname() ?? R.parts;
  const sp = useSearchParams();
  const spKey = sp?.toString() ?? "";
  const [filter, setFilterState] = React.useState<PartFilter>(() => (sp ? filterFromSearch(sp) : NO_FILTER));
  const [shown, setShown] = React.useState(SHOW);
  const [sel, setSel] = React.useState<string | null>(null);
  const headRef = React.useRef<HTMLDivElement>(null);
  const sheetRef = React.useRef<HTMLElement>(null);
  const { cat, err, loadingMore, retry, ensure, reload } = useCatalog();
  const { make, failed: makeFailed, retry: retryMake } = useMachineVerdicts();
  const [records, setRecords] = React.useState<RecordRow[] | null>(null);
  const [aside, setAside] = React.useState<{ rates: Awaited<ReturnType<typeof api.rateSource>> | null; posture: api.PortfolioLite["summary"]["posture"] | null }>({ rates: null, posture: null });

  // Links (Home, the sheet) change the URL; the URL is the filter.
  React.useEffect(() => {
    setFilterState(filterFromSearch(new URLSearchParams(spKey)));
    setShown(SHOW);
  }, [spKey]);

  React.useEffect(() => {
    api.records().then((b) => setRecords(b.cost_decisions), () => setRecords(null));
    api.rateSource().then((r) => setAside((a) => ({ ...a, rates: r })), () => {});
    api.portfolio().then((p) => setAside((a) => ({ ...a, posture: p.summary.posture ?? null })), () => {});
  }, []);

  const setFilter = (f: PartFilter) => {
    setFilterState(f);
    setShown(SHOW);
    router.replace(`${pathname}${searchFromFilter(f)}`, { scroll: false });
  };

  const filtered = isFiltered(filter);
  // A search or filter has to see every part, not only the pages on screen.
  React.useEffect(() => {
    if (filtered && cat?.more) void ensure(Number.MAX_SAFE_INTEGER);
  }, [filtered, cat?.more, ensure]);

  const rows = React.useMemo(() => cat?.rows ?? [], [cat]);
  const verdicts = React.useMemo(() => {
    const m = new Map<string, Verdict>();
    for (const r of rows) m.set(r.part_key, verdictOf(r, make?.byPart.get(r.part_key)?.makeability ?? null));
    return m;
  }, [rows, make]);
  const list = rows.filter((r) => matches(r, verdicts.get(r.part_key)!, filter));
  const visible = list.slice(0, shown);
  const counts = countBy([...verdicts.values()]);
  const allLoaded = cat ? !cat.more : false;
  const costed = cat?.facets.state.Costed ?? 0;
  const picked = sel ? rows.find((r) => r.part_key === sel) ?? null : null;

  // Esc closes the peek (not while typing in a field or inside a dialog).
  React.useEffect(() => {
    if (!picked) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (document.querySelector(".ob [aria-modal='true']")) return;
      setSel(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [picked]);

  const tabs = TABS.parts.map((t) => (t.href === R.parts && cat ? { ...t, count: cat.total } : t));
  // Machine verdicts are known only once they loaded; a blocked route is known from the catalog alone.
  const verdictsReady = Boolean(make);
  // Until machine verdicts load, only the catalog's own facts (and blocked routes) are known.
  const known = verdictsReady ? counts : { ...countBy([]), design: counts.design };
  const facts = cat ? partsFacts(cat.total, costed, known) : [];

  const more = list.length > shown || (!filtered && Boolean(cat?.more));
  const loadMore = () => {
    const next = shown + SHOW;
    setShown(next);
    if (cat && cat.rows.length < next && cat.more) void ensure(next);
  };

  return (
    <Frame label="Your parts">
      <Head ref={headRef}>
        <h1 className="ptitle">Parts</h1>
        {facts.length ? (
          <p className="pmeta">
            {facts.map((f, i) => (
              <span key={i}>
                <b className="num">{f.n}</b> {f.t}
              </span>
            ))}
          </p>
        ) : null}
        <SubNav tabs={tabs} label="Parts" />
        <div className="h-ctl" role="search" aria-label="Find parts">
          <input
            type="search"
            aria-label="Search all parts by file name or part ID"
            placeholder="Search parts"
            value={filter.q}
            onChange={(e) => setFilter({ ...filter, q: e.target.value })}
          />
          <select aria-label="Stage" value={filter.stage} onChange={(e) => setFilter({ ...filter, stage: e.target.value as PartFilter["stage"] })}>
            <option value="all">All stages</option>
            <option value="costed">Costed{cat ? ` · ${cat.facets.state.Costed ?? 0}` : ""}</option>
            <option value="drafted">Drafted{cat ? ` · ${cat.facets.state.Drafted ?? 0}` : ""}</option>
          </select>
          <select aria-label="Findings" value={filter.finds} onChange={(e) => setFilter({ ...filter, finds: e.target.value as PartFilter["finds"] })}>
            <option value="any">Any findings</option>
            <option value="with">With findings{cat ? ` · ${cat.facets.findings.with_findings}` : ""}</option>
            <option value="none">No findings{cat ? ` · ${cat.facets.findings.without_findings}` : ""}</option>
          </select>
          <span className="seg" role="group" aria-label="Machines">
            <SegButton on={filter.machines === "all"} onClick={() => setFilter({ ...filter, machines: "all" })} label="All" n={cat ? rows.length : null} />
            {VERDICT_FILTERS.filter((v) => v.always || (verdictsReady && counts[v.key] > 0)).map((v) => (
              <SegButton key={v.key} on={filter.machines === v.key} onClick={() => setFilter({ ...filter, machines: v.key })} label={v.label} n={verdictsReady || v.key === "design" ? counts[v.key] : null} />
            ))}
            {counts.stale > 0 ? <SegButton on={filter.machines === "stale"} onClick={() => setFilter({ ...filter, machines: "stale" })} label="Out of date" n={counts.stale} /> : null}
          </span>
          <span className="h-cnt num" aria-live="polite">
            {cat ? `${Math.min(visible.length, list.length)} of ${filtered ? (allLoaded ? list.length : `${list.length}+`) : cat.total}` : ""}
          </span>
        </div>
      </Head>

      <Column head={headRef}>
        <JoinedWelcome />
        {makeFailed ? (
          <section className="panel" aria-label="Machine verdicts didn't load">
            <InlineFailed what="machine verdicts" detail="Tiles say Not loaded until they do; prices and findings are complete." onRetry={retryMake} />
          </section>
        ) : null}
        {cat?.truncated ? <p className="smeta" style={{ margin: "0 4px" }}>This list covers the most recent parts; older parts aren&apos;t included.</p> : null}
        {err && !cat ? (
          <section className="panel" aria-label="Parts didn't load">
            <InlineFailed what="parts" detail={err} onRetry={retry} />
          </section>
        ) : !cat ? (
          <div className="h-shelf" aria-busy="true">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="h-tile" aria-hidden="true" style={{ cursor: "default" }}>
                <span className="h-pic" />
                <span className="h-sk" style={{ width: "62%" }} />
                <span className="h-sk" style={{ width: "44%", marginTop: 8 }} />
              </div>
            ))}
            <span className="sr" role="status">
              Loading parts
            </span>
          </div>
        ) : cat.total === 0 ? (
          <section className="panel">
            <NoneYet
              title="No parts"
              actions={
                <Link className="btn sm ink" href={R.check}>
                  Check a part
                </Link>
              }
            >
              A part appears here after its first check.
            </NoneYet>
          </section>
        ) : (
          <>
            <div className="h-shelf" role="list" aria-label="Parts">
              {visible.map((r) => {
                const v = verdicts.get(r.part_key)!;
                const on = r.part_key === sel;
                const price = priceText(r);
                return (
                  <div role="listitem" key={r.part_key} style={{ display: "flex", minWidth: 0 }}>
                    <button
                      type="button"
                      className={cx("h-tile", on && "on")}
                      style={{ flex: 1 }}
                      aria-pressed={on}
                      aria-label={`${r.filename}, ${verdictsReady || v.key === "design" ? v.label : makeFailed ? "machine verdict not loaded" : "machine verdict loading"}, ${price === "—" ? "no price" : price}`}
                      onClick={() => {
                        setSel(on ? null : r.part_key);
                        if (!on && window.matchMedia("(max-width:900px)").matches) {
                          const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
                          requestAnimationFrame(() => sheetRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }));
                        }
                      }}
                    >
                      <span className="h-pic">
                        <PartGlyph size={58} />
                      </span>
                      <b title={r.filename}>{r.filename}</b>
                      <small>{v.stale ? `${v.where} · out of date` : v.where}</small>
                      <span className="h-tr">
                        {verdictsReady || v.key === "design" ? <Chip tone={v.tone}>{v.label}</Chip> : <Chip tone="unk">{makeFailed ? "Not loaded" : "Checking"}</Chip>}
                        <span className="c num">{price}</span>
                      </span>
                    </button>
                  </div>
                );
              })}
              {list.length === 0 && (allLoaded || !loadingMore) ? (
                <div className="h-none panel" role="listitem">
                  <NoneYet
                    title="No parts match"
                    actions={
                      <button type="button" className="btn sm" onClick={() => setFilter(NO_FILTER)}>
                        Clear search and filters
                      </button>
                    }
                  >
                    Nothing matches the search and filters.
                  </NoneYet>
                </div>
              ) : null}
            </div>
            {loadingMore && filtered ? <Skeleton rows={2} label="Searching every part" /> : null}
            {err ? <InlineFailed what="more parts" detail={err} onRetry={() => void ensure(shown + SHOW)} /> : null}
            {list.length > 0 ? (
              <section className="panel" aria-label="Pages">
                <LoadMore shown={visible.length} total={filtered ? (allLoaded ? list.length : null) : cat.total} more={more} loading={loadingMore} onMore={loadMore} />
              </section>
            ) : null}
          </>
        )}
      </Column>

      <aside className="sheet" aria-label={picked ? "Part" : "Needs you"} ref={sheetRef}>
        {picked ? (
          <Peek
            key={picked.part_key}
            row={picked}
            v={verdicts.get(picked.part_key)!}
            onClose={() => setSel(null)}
            onDeleted={() => {
              setSel(null);
              reload();
            }}
          />
        ) : (
          <SheetHome
            rows={rows}
            make={make?.summary ?? null}
            records={records}
            rates={aside.rates}
            posture={aside.posture ?? null}
            onFilter={(m) => setFilter({ ...NO_FILTER, machines: m })}
            onLibrary={reload}
          />
        )}
      </aside>
    </Frame>
  );
}

function SegButton({ on, onClick, label, n }: { on: boolean; onClick: () => void; label: string; n: number | null }) {
  return (
    <button type="button" className={cx(on && "on")} aria-pressed={on} onClick={onClick}>
      {label}
      {n != null ? (
        <span className="num" style={{ opacity: 0.7 }}>
          {" "}
          {n}
        </span>
      ) : null}
    </button>
  );
}

function Peek({ row, v, onClose, onDeleted }: { row: PartRow; v: Verdict; onClose: () => void; onDeleted: () => void }) {
  const [d, setD] = React.useState<DecisionLite | null>(null);
  const closeRef = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    if (!row.cost_decision) return;
    let live = true;
    api.load<DecisionLite>(`/cost-decisions/${encodeURIComponent(row.cost_decision.id)}`).then((x) => live && setD(x), () => {});
    return () => {
      live = false;
    };
  }, [row.cost_decision]);
  const figs = peekFigs(row, v, d);
  const route = row.recommended_route;
  const post = row.provenance_posture;
  const f = row.findings;
  const size = sizeText(d?.result?.geometry?.bbox_mm);
  const kv: [string, string][] = [];
  if (route) kv.push(["Process", [wayName(route.process), route.material].filter(Boolean).join(" · ")]);
  if (post && post.total) kv.push(["Cost inputs yours", `${post.shop + post.user} of ${post.total}`]);
  if (row.unit_cost?.qty != null) kv.push(["Shown at", `${row.unit_cost.qty.toLocaleString("en-US")} ${row.unit_cost.qty === 1 ? "part" : "parts"}`]);
  if (size) kv.push(["Size", size]);
  return (
    <>
      <div className="top" style={{ position: "relative" }}>
        <h2 className="stitle" style={{ paddingRight: 40, overflowWrap: "anywhere" }}>
          {row.filename}
        </h2>
        <p className="smeta">
          {row.lifecycle_state} · {row.file_type.toUpperCase()} · updated {longDate(row.updated_at)}
        </p>
        <button ref={closeRef} type="button" className="btn sm h-peekx" aria-label="Close" onClick={onClose}>
          ✕
        </button>
        <Figs>
          {figs.map((g, i) => (
            <Fig key={i} k={g.k} v={g.v} sub={g.s} tone={g.c} />
          ))}
        </Figs>
      </div>
      <div className="scroll swap">
        <div className="gh">
          <span>Engine pick</span>
          <span>{route ? (route.source === "costed" ? "Costed record" : "Shape suggestion, not costed") : "No process found"}</span>
        </div>
        {kv.length ? (
          <div className="kv">
            {kv.map(([k, val]) => (
              <React.Fragment key={k}>
                <span>{k}</span>
                <b>{val}</b>
              </React.Fragment>
            ))}
          </div>
        ) : null}
        <div className="gh">
          <span>Findings on this way</span>
          <span className="num">{f ? `${f.total} total` : "Not checked"}</span>
        </div>
        {f ? (
          <div className="kv">
            <span>Must change</span>
            <b className="num">{f.critical}</b>
            <span>Advisory</span>
            <b className="num">{f.advisory}</b>
            <span>Info</span>
            <b className="num">{f.info}</b>
          </div>
        ) : (
          <p className="h-foot">This part has no manufacturability check yet.</p>
        )}
        <div className="h-sheetacts">
          <Link className="btn ink sm" href={R.part(row.part_key)}>
            Open part
          </Link>
          {row.cost_decision ? (
            <Link className="btn sm" href={R.record(row.cost_decision.id)}>
              Record
            </Link>
          ) : null}
          {row.analysis ? (
            <Link className="btn sm" href={R.analysis(row.analysis.id)}>
              Analysis
            </Link>
          ) : null}
          <DeletePartButton partKey={row.part_key} fileName={row.filename} className="btn sm ghost" label="Delete" onDeleted={onDeleted} />
        </div>
      </div>
    </>
  );
}

function SheetHome({
  rows,
  make,
  records,
  rates,
  posture,
  onFilter,
  onLibrary,
}: {
  rows: PartRow[];
  make: MakeSummary | null;
  records: RecordRow[] | null;
  rates: Awaited<ReturnType<typeof api.rateSource>> | null;
  posture: api.PortfolioLite["summary"]["posture"] | null;
  onFilter: (m: PartFilter["machines"]) => void;
  onLibrary: () => void;
}) {
  const items = buildQueue({
    records: null,
    recordsMore: false,
    parts: rows,
    partsTotal: null,
    make,
    machines: null,
    changes: null,
    actuals: null,
    posture: posture ?? null,
    rates,
    programs: null,
    withVolume: null,
  }).filter((i) => i.key === "design" || i.key === "capability" || i.key === "out" || i.key === "stale" || i.key === "rates");
  // One decided record per part: the newest one with an outcome.
  const decided: RecordRow[] = [];
  const seen = new Set<string>();
  for (const r of records ?? []) {
    if (!r.user_disposition_label) continue;
    const k = r.mesh_hash ?? r.filename;
    if (seen.has(k)) continue;
    seen.add(k);
    decided.push(r);
  }
  const filterOf: Record<string, PartFilter["machines"]> = { design: "design", capability: "machine", out: "out", stale: "stale" };
  return (
    <>
      <div className="top">
        <h2 className="stitle">Needs attention</h2>
        <p className="smeta">
          {items.length} {items.length === 1 ? "item" : "items"}
          {records ? ` · ${decided.length} decided` : ""}
        </p>
      </div>
      <div className="scroll">
        {items.map((i) => (
          <div className="h-nd" key={i.key}>
            <b>{i.title}</b>
            <span>{i.short}</span>
            {filterOf[i.key] ? (
              <button type="button" className="h-link" onClick={() => onFilter(filterOf[i.key])}>
                Show {i.key === "design" && i.n === "1" ? "the part" : "the parts"}
              </button>
            ) : (
              <Link href={i.act.href}>{i.act.label}</Link>
            )}
            {i.key === "capability" ? <Link href={R.triage}>What machine would fit</Link> : null}
          </div>
        ))}
        {items.length === 0 && make ? <p className="h-foot" style={{ margin: "8px 12px" }}>Every part&apos;s process is current and priced.</p> : null}
        <div className="gh">
          <span>Decided</span>
          <span className="num">{records ? decided.length : ""}</span>
        </div>
        {decided.length ? (
          decided.slice(0, 6).map((r) => (
            <Link key={r.id} className="mr" href={R.record(r.id)} style={{ textDecoration: "none", color: "var(--ink)" }}>
              <span style={{ minWidth: 0 }}>
                <b style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label || r.filename}</b>
                <small>{[r.user_disposition_label, r.make_now_process ? wayName(r.make_now_process) : null].filter(Boolean).join(" · ")}</small>
              </span>
              <Chip tone="ok">Decided</Chip>
              <span className="c num" />
            </Link>
          ))
        ) : (
          <p className="h-foot" style={{ margin: "0 12px 6px" }}>{records ? "No part has a recorded outcome yet." : ""}</p>
        )}
        <LibraryPanel onAdded={onLibrary} />
      </div>
    </>
  );
}
