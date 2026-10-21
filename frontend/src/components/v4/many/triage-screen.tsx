"use client";

/**
 * Triage (board M2): every part's latest check against your machines, in
 * buckets that sum to the whole inventory. Each bucket opens its parts; out-of-
 * date verdicts are counted and marked, never hidden. The sheet ranks the
 * capability changes that would unlock the most parts, and a part's Tooling
 * button swaps it for that part's tooling comparison. Declared BOM parts are
 * listed apart: they have no file, so no verdict and no cost.
 */
import * as React from "react";
import Link from "next/link";
import {
  fetchCapabilityInvestment,
  fetchManifest,
  fetchManifestCoverage,
  importManifestCsv,
} from "@/lib/verify/triage-api";
import { allAwaitingGeometry, coverageHeadline, partMetaBits, type ManifestCoverage, type ManifestPart } from "@/lib/verify/manifest";
import { R, TABS } from "../routes";
import { Content, Empty, Loading, Panel, cx } from "../ui";
import { ManyWorld, PilotGate, Thumb, errorText, unchanged, isPaidAccessError, useManyTabs, useToast } from "./common";
import { useCatalogAccess } from "./catalog-access";
import { CapabilitySheet, type Ranking } from "./capability-sheet";
import { ToolingSheet } from "./tooling-sheet";
import { fetchBucket, fetchMachines, fetchRollup, type Rollup } from "./many-api";
import { bucketDef, costLabel, countOf, isStale, orderedBuckets, reasonOf, wallTooThin, type Machine, type MakeRow } from "./makeability";

export const TRIAGE_GATE = {
  title: "Make or buy",
  slot: "Your whole catalog",
  tab: 1,
  features: [
    { title: "Makeability buckets", text: "On your machines, outside only, one change, ruled out", tone: "#E3F1E8" },
    { title: "Capability changes", text: "Which change to your machines unlocks the most parts", tone: "#FAEFD8" },
    { title: "Tooling payback", text: "Make now against tooling, across quantity", tone: "#ECEEF1" },
  ],
  inputs: ["Inputs: your checked parts", "Optional BOM CSV"],
};

export function TriageScreen() {
  // Make or buy is the catalog run's result: open to pilot and to work-email
  // accounts on their free run; personal email keeps single checks.
  const catalog = useCatalogAccess();
  const [refused, setRefused] = React.useState(false);
  const gate = React.useCallback(() => setRefused(true), []);
  const access = refused || catalog.kind === "personal" ? "gated" : "open";
  const tabs = useManyTabs();
  const [toastNode, toast] = useToast();
  const [roll, setRoll] = React.useState<Rollup | null>(null);
  const [rollErr, setRollErr] = React.useState<string | null>(null);
  const [cap, setCap] = React.useState<Ranking | null>(null);
  const [capErr, setCapErr] = React.useState<string | null>(null);
  const [machines, setMachines] = React.useState<Machine[] | null>(null);
  const [bucket, setBucket] = React.useState<string | null>(null);
  const [rows, setRows] = React.useState<MakeRow[] | null>(null);
  const [cursor, setCursor] = React.useState<string | null>(null);
  const [rowsErr, setRowsErr] = React.useState<string | null>(null);
  const [moreBusy, setMoreBusy] = React.useState(false);
  const [rowsRetry, setRowsRetry] = React.useState(0);
  const [tool, setTool] = React.useState<MakeRow | null>(null);
  const [cov, setCov] = React.useState<ManifestCoverage | null>(null);
  const [declared, setDeclared] = React.useState<ManifestPart[] | null>(null);
  const [declCursor, setDeclCursor] = React.useState<string | null>(null);
  const [declBusy, setDeclBusy] = React.useState(false);
  const [importing, setImporting] = React.useState(false);
  const [importMsg, setImportMsg] = React.useState<string | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const toolFrom = React.useRef<string | null>(null);

  const loadRoll = React.useCallback(async () => {
    setRollErr(null);
    try {
      setRoll(await fetchRollup());
    } catch (e) {
      if (isPaidAccessError(e)) gate();
      setRollErr(errorText(e, "Make or buy didn’t load."));
    }
  }, [gate]);

  const loadCap = React.useCallback(() => {
    setCapErr(null);
    fetchCapabilityInvestment().then(
      (r) => setCap(r as unknown as Ranking),
      (e) => setCapErr(errorText(e, "Capability changes didn’t load.")),
    );
  }, []);

  const loadDeclared = React.useCallback(() => {
    fetchManifestCoverage().then(setCov, () => setCov(null));
    fetchManifest().then(
      (p) => {
        setDeclared(p.parts);
        setDeclCursor(p.next_cursor);
      },
      () => setDeclared(null),
    );
  }, []);

  React.useEffect(() => {
    void loadRoll();
    loadCap();
    loadDeclared();
    fetchMachines().then(setMachines, () => setMachines([]));
  }, [loadRoll, loadCap, loadDeclared]);

  const summary = (roll?.summary ?? {}) as Record<string, unknown>;
  const keys = roll ? orderedBuckets(roll.buckets, summary) : [];
  const several = (cap?.summary.blocked_by_multiple_constraints ?? 0) > 0;
  const def = (k: string) => bucketDef(k, { severalChanges: several });

  // Default to the first primary bucket with parts.
  React.useEffect(() => {
    if (!roll || bucket) return;
    const first = keys.find((k) => def(k).primary && countOf(summary, k) > 0) ?? keys.find((k) => countOf(summary, k) > 0) ?? "makeable_in_house";
    setBucket(first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roll]);

  React.useEffect(() => {
    if (!bucket) return;
    let live = true;
    setRows(null);
    setCursor(null);
    setRowsErr(null);
    if (roll && countOf(roll.summary as Record<string, unknown>, bucket) === 0) {
      setRows([]);
      return;
    }
    fetchBucket(bucket).then(
      (p) => {
        if (!live) return;
        setRows(p.rows);
        setCursor(p.next_cursor);
      },
      (e) => live && setRowsErr(errorText(e, "This bucket didn’t load.")),
    );
    return () => {
      live = false;
    };
  }, [bucket, roll, rowsRetry]);

  const loadMore = async () => {
    if (!bucket || !cursor || moreBusy) return;
    setMoreBusy(true);
    try {
      const p = await fetchBucket(bucket, cursor);
      setRows((prev) => [...(prev ?? []), ...p.rows]);
      setCursor(p.next_cursor);
    } catch (e) {
      toast(errorText(e, "More parts didn’t load."));
    } finally {
      setMoreBusy(false);
    }
  };

  const loadMoreDeclared = async () => {
    if (!declCursor || declBusy) return;
    setDeclBusy(true);
    try {
      const p = await fetchManifest(declCursor);
      setDeclared((prev) => [...(prev ?? []), ...p.parts]);
      setDeclCursor(p.next_cursor);
    } catch (e) {
      toast(errorText(e, "More declared parts didn’t load."));
    } finally {
      setDeclBusy(false);
    }
  };

  const onImport = async (file: File) => {
    setImporting(true);
    setImportMsg(null);
    try {
      const s = await importManifestCsv(file);
      const errs = s.errors.length ? ` · ${s.errors.length} ${s.errors.length === 1 ? "row" : "rows"} with errors (${s.errors.slice(0, 2).map((e) => `line ${e.line}: ${e.reason}`).join("; ")})` : "";
      setImportMsg(`${file.name}: ${s.imported} imported · ${s.updated} updated · ${s.skipped} skipped${errs}. Dry runs live in Imports.`);
      toast("BOM imported.");
      loadDeclared();
      void loadRoll();
    } catch (e) {
      if (isPaidAccessError(e)) gate();
      setImportMsg(errorText(e, "The BOM wasn’t imported."));
    } finally {
      setImporting(false);
    }
  };

  const openTool = (r: MakeRow) => {
    if (tool?.part_key === r.part_key) {
      closeTool();
      return;
    }
    toolFrom.current = r.part_key;
    setTool(r);
  };
  const closeTool = React.useCallback(() => {
    setTool(null);
    const key = toolFrom.current;
    requestAnimationFrame(() => {
      const el = key ? document.querySelector<HTMLElement>(`[data-tool="${CSS.escape(key)}"]`) : null;
      el?.focus();
    });
  }, []);

  if (access === "gated") return <PilotGate {...TRIAGE_GATE} />;

  const total = countOf(summary, "total");
  const staleN = countOf(summary, "stale_count");
  const cur = bucket ? def(bucket) : null;
  const curN = bucket ? countOf(summary, bucket) : 0;
  const primary = keys.filter((k) => def(k).primary);
  const honesty = keys.filter((k) => !def(k).primary);
  const segs = keys.map((k) => ({ k, d: def(k), n: countOf(summary, k) })).filter((x) => x.n > 0);
  const shownStale = (rows ?? []).filter(isStale).length;
  const importLabel = importing ? "Importing…" : "Import BOM CSV";

  return (
    <ManyWorld label="Make or buy">
      <div className="pagehead">
        <h1 className="ptitle">Make or buy</h1>
        <p className="pmeta" style={{ marginTop: 6 }}>
          {roll ? (
            <>
              <span>
                <b className="num">{total}</b> {total === 1 ? "part" : "parts"}
              </span>
              <span>
                <b className="num">{countOf(summary, "makeable_in_house")}</b> on your machines
              </span>
              <span>
                <b className="num">{countOf(summary, "needs_capability")}</b> {several ? "need a capability change" : "need one change"}
              </span>
              <span>
                <b className="num">{countOf(summary, "not_makeable")}</b> ruled out
              </span>
              {staleN ? (
                <span>
                  <b className="num">{staleN}</b> out of date
                </span>
              ) : null}
            </>
          ) : (
            <span>Loading</span>
          )}
        </p>
        <div className="hrow">
          <nav className="subnav" aria-label="Many parts">
            {tabs.map((t) => (
              <Link key={t.href} href={t.href} className={cx(t.href === TABS.many[1].href && "on")} aria-current={t.href === TABS.many[1].href ? "page" : undefined}>
                {t.label}
                {"count" in t && t.count != null ? <b className="num">{t.count}</b> : null}
              </Link>
            ))}
          </nav>
          <div className="tools">
            <Link className="btn sm" href={R.check}>
              Check a part
            </Link>
            <button className="btn sm" type="button" onClick={() => !importing && fileRef.current?.click()} aria-disabled={importing}>
              {importLabel}
            </button>
          </div>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          aria-label="BOM CSV to import"
          tabIndex={-1}
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) void onImport(f);
          }}
        />
      </div>

      <Content>
        {rollErr && !roll ? (
          <Panel>
            <Empty
              title="Make or buy didn’t load"
              actions={
                <button className="btn sm" type="button" onClick={() => void loadRoll()}>
                  Try again
                </button>
              }
            >
              {unchanged("Saved checks are unchanged.", rollErr)}
            </Empty>
          </Panel>
        ) : !roll ? (
          <Loading rows={4} label="Loading triage" />
        ) : (
          <>
            {roll.summary.stale ? (
              <div className="stale" role="status">
                <span>
                  <b>
                    {staleN} {staleN === 1 ? "result" : "results"} out of date.
                  </b>{" "}
                  Machine list changed after these checks. Still counted and marked; open a part to check it again.
                </span>
              </div>
            ) : null}
            {roll.cold_projection || roll.evaluation_note ? (
              <div className="stale" role="status" style={{ background: "var(--typ-bg)", color: "var(--ink2)" }}>
                <span>
                  {roll.cold_projection
                    ? "These parts haven’t been sorted against your machines yet. Check a part again to sort it."
                    : "No part has been checked against your machines. Add your machines in Your shop, then check parts."}
                </span>
                {!roll.cold_projection ? (
                  <Link className="btn sm" href={R.shop} style={{ marginLeft: "auto", background: "#fff" }}>
                    Your machines
                  </Link>
                ) : null}
              </div>
            ) : null}

            <div className="panel">
              <div className="bk4" role="group" aria-label="Show parts">
                {primary.map((k) => {
                  const d = def(k);
                  return (
                    <button key={k} type="button" className={cx("bk", bucket === k && "on")} onClick={() => setBucket(k)} aria-pressed={bucket === k}>
                      <b className="num">{countOf(summary, k)}</b>
                      <span>
                        <i style={{ background: d.color }} />
                        {d.label}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div
                className={cx("bbar", !total && "empty")}
                role="img"
                aria-label={total ? segs.map((x) => `${x.n} ${x.d.label.toLowerCase()}`).join(", ") + ` of ${total}` : "No parts yet"}
              >
                {segs.map((x) => (
                  <i key={x.k} style={{ flex: `${x.n} 1 0`, background: x.d.color }} title={`${x.d.label}: ${x.n}`}>
                    {x.n / Math.max(1, total) > 0.18 ? `${x.n} · ${x.d.label}` : x.n}
                  </i>
                ))}
              </div>
              <div className="hon">
                {honesty.map((k) => {
                  const d = def(k);
                  const n = countOf(summary, k);
                  return n > 0 ? (
                    <button key={k} type="button" aria-pressed={bucket === k} onClick={() => setBucket(k)}>
                      {d.label} <b className="num">{n}</b>
                    </button>
                  ) : (
                    <span key={k}>
                      {d.label} <b className="num">0</b>
                    </span>
                  );
                })}
                <span>Buckets sum to {total}</span>
              </div>
            </div>

            <Panel
              title={cur ? cur.label : "Parts"}
              note={cur ? `${curN} ${curN === 1 ? "part" : "parts"}${shownStale ? ` · ${shownStale} out of date` : ""}` : undefined}
            >
              {rowsErr ? (
                <Empty
                  title="This bucket didn’t load"
                  actions={
                    <button className="btn sm" type="button" onClick={() => setRowsRetry((n) => n + 1)}>
                      Try again
                    </button>
                  }
                >
                  {rowsErr}
                </Empty>
              ) : rows === null ? (
                <Loading rows={3} label="Loading parts" />
              ) : rows.length === 0 ? (
                <Empty
                  title={`No ${cur ? cur.label.toLowerCase() : ""} parts`}
                  actions={
                    <Link className="btn sm" href={R.check}>
                      Check a part
                    </Link>
                  }
                >
                  {cur?.empty}
                </Empty>
              ) : (
                <div className="list" role="list" aria-label={cur?.label}>
                  {rows.map((r) => {
                    const name = r.filename ?? r.part_key.slice(0, 12);
                    const on = tool?.part_key === r.part_key;
                    return (
                      <div role="listitem" className="trow" key={r.part_key}>
                        <Link className={cx("lrow", on && "on")} href={R.part(r.part_key)}>
                          <Thumb name={r.filename} className="th" />
                          <span style={{ minWidth: 0 }}>
                            <b>{name}</b>
                            <small>{reasonOf(r, machines)}</small>
                          </span>
                          <span className="flags">
                            {wallTooThin(r) ? <span className="flag f-wall">Wall too thin</span> : null}
                            {isStale(r) ? <span className="flag f-stale">Out of date</span> : null}
                          </span>
                          <span className="c num">{costLabel(r)}</span>
                        </Link>
                        {r.cost_decision?.id ? (
                          <button
                            className={cx("btn sm", on && "ink")}
                            type="button"
                            data-tool={r.part_key}
                            onClick={() => openTool(r)}
                            aria-pressed={on}
                            aria-label={`Tooling alternative for ${name}`}
                          >
                            Tooling
                          </button>
                        ) : (
                          <span />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              {rows && rows.length ? (
                <p className="tfoot" style={{ padding: "0 8px 10px" }}>
                  {cursor ? (
                    <>
                      <span>
                        {rows.length} of {curN} shown
                      </span>
                      <button className="btn sm" type="button" onClick={() => void loadMore()} disabled={moreBusy}>
                        {moreBusy ? "Loading…" : "Load more"}
                      </button>
                    </>
                  ) : (
                    <span>All {rows.length} shown · rows open the part</span>
                  )}
                </p>
              ) : null}
            </Panel>
          </>
        )}

        <div className="panel">
          <div className="dec">
            <span>
              <b>Declared parts {cov?.total_declared ?? 0}.</b>{" "}
              {cov && cov.total_declared > 0 ? coverageHeadline(cov) : "No BOM imported yet. Imported parts show here before any file is checked."}
            </span>
            <button className="btn sm" type="button" onClick={() => !importing && fileRef.current?.click()} aria-disabled={importing}>
              {importLabel}
            </button>
          </div>
          {importMsg ? (
            <p style={{ margin: 0, padding: "0 16px 12px", color: "var(--ink2)", fontSize: 12.5 }} role="status">
              {importMsg}
            </p>
          ) : null}
          {cov && cov.by_program.length ? (
            <div className="progs">
              {cov.by_program.map((p) => (
                <span key={p.program}>
                  {p.program} · <b className="num">{p.count}</b>
                </span>
              ))}
            </div>
          ) : null}
          {cov && cov.total_declared > 0 && declared ? (
            <>
              <div className="list" role="list" aria-label="Declared parts">
                {declared.map((p) => (
                  <div role="listitem" key={p.id} className="lrow" style={{ cursor: "default" }}>
                    <span className="th2" aria-hidden="true">
                      BOM
                    </span>
                    <span style={{ minWidth: 0 }}>
                      <b>{p.part_id}</b>
                      <small>{[p.description ?? "No description", ...partMetaBits(p)].join(" · ")}</small>
                    </span>
                    <span>
                      <span className="flag f-stale">{allAwaitingGeometry(cov) ? "Awaiting a file" : "Declared"}</span>
                    </span>
                    <span className="c" />
                  </div>
                ))}
              </div>
              <p className="tfoot" style={{ padding: "0 8px 10px" }}>
                {declCursor ? (
                  <>
                    <span>
                      {declared.length} of {cov.total_declared} shown
                    </span>
                    <button className="btn sm" type="button" onClick={() => void loadMoreDeclared()} disabled={declBusy}>
                      {declBusy ? "Loading…" : "Load more"}
                    </button>
                  </>
                ) : (
                  <span>
                    All {declared.length} shown · no file, so no verdict or cost ·{" "}
                    <Link className="lk" href={R.check}>
                      Check a part
                    </Link>
                  </span>
                )}
              </p>
            </>
          ) : null}
        </div>
      </Content>

      {tool ? (
        <ToolingSheet
          row={tool}
          machines={machines}
          ranking={cap?.ranking ?? null}
          onBack={closeTool}
          onSeeCapability={() => {
            closeTool();
            setBucket("needs_capability");
          }}
        />
      ) : (
        <CapabilitySheet data={cap} err={capErr} onRetry={loadCap} machines={machines} />
      )}
      {toastNode}
    </ManyWorld>
  );
}
