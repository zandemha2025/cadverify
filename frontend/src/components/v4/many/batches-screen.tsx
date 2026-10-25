"use client";

/**
 * Batches (board M4): recent runs with their status, items and CSV, the limits,
 * and the New catalog run sheet. Work-email accounts run catalogs free within
 * their allowance; pilot accounts run any size and keep the DFM batch (ZIP,
 * manifest, webhook) one click away. Personal email sees the gate.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { downloadBatchCsv, listBatches, type BatchSummaryRow } from "@/lib/api/batch";
import { R } from "../routes";
import { Chip, Content, Empty, Loading, PageHead, Panel } from "../ui";
import { ManyWorld, PilotGate, errorText, unchanged, isPaidAccessError, revealSheetOnPhone, saveBlob, useManyTabs, useToast, whenLabel } from "./common";
import { batchStatus } from "./batch-model";
import { NewBatchSheet } from "./new-batch";
import { useCatalogAccess } from "./catalog-access";
import { downloadBoardCsv } from "./catalog-api";
import { allowanceText } from "./catalog-model";
import { CatalogStartSheet } from "./catalog-start";

export const BATCH_GATE = {
  title: "Batches",
  slot: "Parts, a folder or a ZIP",
  features: [
    { title: "50 parts free with a work email", text: "A work-email account runs its first 50 catalog parts free; this account has single-part checks", tone: "#E3F1E8" },
    { title: "Sorted on your machines", text: "Make in-house, buy outside, needs a new machine, can’t be made as drawn", tone: "#E8EEFB" },
    { title: "Hours and material first", text: "Machine time, material and ownership per part, then the price; CSV and a printable summary", tone: "#ECEEF1" },
  ],
  inputs: ["Inputs: many files, a folder or a ZIP", "Optional parts list with quantities and materials"],
};

export function BatchesScreen() {
  const router = useRouter();
  const catalog = useCatalogAccess();
  const [refused, setRefused] = React.useState(false);
  const gate = React.useCallback(() => setRefused(true), []);
  const access = refused || catalog.kind === "personal" ? "gated" : catalog.kind === "loading" ? "loading" : "open";
  const [sheet, setSheet] = React.useState<"catalog" | "dfm">("catalog");
  // ?new=1 (Home, Your shop): on a phone the sheet sits under the list, so bring it into view.
  React.useEffect(() => {
    if (catalog.kind === "loading") return;
    const q = new URLSearchParams(window.location.search);
    if (q.get("dfm") === "1") setSheet("dfm");
    if (q.get("new") === "1") revealSheetOnPhone("New catalog run");
  }, [catalog.kind]);
  const [rows, setRows] = React.useState<BatchSummaryRow[] | null>(null);
  const [cursor, setCursor] = React.useState<string | null>(null);
  const [more, setMore] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [csvBusy, setCsvBusy] = React.useState<string | null>(null);
  const [toastNode, toast] = useToast();

  const load = React.useCallback(async () => {
    setErr(null);
    try {
      const r = await listBatches({ limit: 20 });
      setRows(r.batches);
      setCursor(r.next_cursor);
      setMore(r.has_more);
    } catch (e) {
      if (isPaidAccessError(e)) gate();
      setErr(errorText(e, "Recent batches didn’t load."));
    }
  }, [gate]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const loadMore = async () => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const r = await listBatches({ limit: 20, cursor });
      setRows((prev) => [...(prev ?? []), ...r.batches]);
      setCursor(r.next_cursor);
      setMore(r.has_more);
    } catch (e) {
      toast(errorText(e, "More batches didn’t load."));
    } finally {
      setLoadingMore(false);
    }
  };

  const csv = async (id: string, catalogRun: boolean) => {
    if (csvBusy) return;
    setCsvBusy(id);
    try {
      const name = catalogRun ? `catalog_run_${id}.csv` : `batch_${id}_results.csv`;
      saveBlob(catalogRun ? await downloadBoardCsv(id) : await downloadBatchCsv(id), name);
      toast(`Downloaded ${name}`);
    } catch (e) {
      toast(errorText(e, "The CSV didn’t download."));
    } finally {
      setCsvBusy(null);
    }
  };

  const tabs = useManyTabs(rows ? { count: rows.length, exact: !more } : null);

  if (access === "gated") return <PilotGate {...BATCH_GATE} />;

  const n = rows?.length ?? 0;
  const pilot = catalog.kind === "pilot";
  const free = catalog.kind === "free";
  return (
    <ManyWorld label="Batches">
      <PageHead
        title="Batches"
        meta={[
          rows ? (
            <>
              <b>{more ? `${n}+` : n}</b> {n === 1 && !more ? "batch" : "batches"}
            </>
          ) : (
            "Batches loading"
          ),
          free ? allowanceText(catalog) : "ZIP up to 5 GB",
          free ? "4 parts at a time" : "1 to 12 files at a time",
          pilot ? "Pilot plan" : free ? "Free with a work email" : "",
        ].filter(Boolean)}
        tabs={tabs}
        tabsLabel="Many parts"
        actions={
          pilot ? (
            <button className="btn sm ghost" type="button" onClick={() => setSheet((x) => (x === "dfm" ? "catalog" : "dfm"))} aria-pressed={sheet === "dfm"}>
              {sheet === "dfm" ? "New catalog run" : "DFM batch with webhook"}
            </button>
          ) : undefined
        }
      />
      <Content>
        <Panel title="Recent batches" note="Newest first · 20 per page">
          {err && !rows ? (
            <Empty
              title="Recent batches didn’t load"
              actions={
                <button className="btn sm" type="button" onClick={() => void load()}>
                  Try again
                </button>
              }
            >
              {unchanged("Saved batches are unchanged.", err)}
            </Empty>
          ) : !rows ? (
            <Loading rows={3} label="Loading batches" />
          ) : rows.length === 0 ? (
            <Empty title="No runs yet">Start one with many parts, a folder or a ZIP. Each part is checked against your machines and sorted.</Empty>
          ) : (
            <div style={{ padding: "0 8px 8px" }}>
              <table className="bt stack">
                <thead>
                  <tr>
                    <th scope="col">Batch</th>
                    <th scope="col">Status</th>
                    <th scope="col">Files</th>
                    <th scope="col">Created</th>
                    <th scope="col">
                      <span className="sr">Results</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((b) => {
                    const catalogRun = b.job_type === "catalog";
                    // A catalog run reads as its own page does: its name, "Finished", files and not checked.
                    const s = catalogRun && b.status === "completed" ? { label: "Finished", tone: "ok" as const } : batchStatus(b.status);
                    const title = catalogRun ? b.name || "Catalog run" : `${b.batch_ulid.slice(0, 12)}…`;
                    const canCsv = catalogRun || b.status === "completed" || b.status === "failed";
                    return (
                      <tr
                        key={b.batch_ulid}
                        className="click"
                        onClick={(e) => {
                          if ((e.target as HTMLElement).closest("a,button")) return;
                          router.push(R.batch(b.batch_ulid));
                        }}
                      >
                        <td>
                          <Link className="rowlink" href={R.batch(b.batch_ulid)} aria-label={`Open ${catalogRun ? `catalog run ${title}` : `batch ${b.batch_ulid}`}`}>
                            {title}
                          </Link>
                          <span className="sub">{catalogRun ? `Catalog run${b.name ? "" : ` ${b.batch_ulid.slice(0, 8)}`}` : "DFM batch"}</span>
                        </td>
                        <td>
                          <Chip tone={s.tone}>{s.label}</Chip>
                        </td>
                        <td className="num" data-k={catalogRun ? "Files" : "Items"}>
                          {catalogRun ? `${b.total_items.toLocaleString("en-US")} ${b.total_items === 1 ? "file" : "files"}` : `${b.completed_items}/${b.total_items}`}
                          {b.failed_items > 0 ? <span style={{ color: catalogRun ? "var(--ink2)" : "var(--bad)" }}> · {b.failed_items} {catalogRun ? "not checked" : "failed"}</span> : null}
                          {b.skipped_items > 0 ? <span style={{ color: "var(--ink3)" }}> · {b.skipped_items} skipped</span> : null}
                        </td>
                        <td className="num" style={{ color: "var(--ink2)" }}>
                          {whenLabel(b.created_at)}
                        </td>
                        <td className="r">
                          {canCsv ? (
                            <button className="btn sm" type="button" onClick={() => void csv(b.batch_ulid, catalogRun)} disabled={csvBusy === b.batch_ulid}>
                              {csvBusy === b.batch_ulid ? "Downloading…" : "Download CSV"}
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="tfoot">
                {more ? (
                  <>
                    <span>
                      {n} shown · more below
                    </span>
                    <button className="btn sm" type="button" onClick={() => void loadMore()} disabled={loadingMore}>
                      {loadingMore ? "Loading…" : "Load more"}
                    </button>
                  </>
                ) : (
                  <span>All batches shown. Click a row to open it.</span>
                )}
              </p>
            </div>
          )}
        </Panel>
        <Panel title="Limits" note={free ? "Free catalog run" : "Per run"}>
          <div className="lim num">
            <div>
              <b>{free && catalog.usage.cap != null ? `${catalog.usage.cap} parts` : "5 GB"}</b>
              {free ? "Free, separate from checks" : "ZIP size"}
            </div>
            <div>
              <b>{free ? "1 GB" : "1–12"}</b>
              {free ? "Upload per run" : "Files at a time"}
            </div>
            <div>
              <b>STL · STEP · IGES</b>Files, a folder or a ZIP
            </div>
            <div>
              <b>CSV · PDF</b>Board, summary to print
            </div>
          </div>
        </Panel>
      </Content>
      {pilot && sheet === "dfm" ? (
        <NewBatchSheet onCreated={() => void load()} onPaidAccess={gate} toast={toast} />
      ) : catalog.kind === "loading" ? null : (
        <CatalogStartSheet access={catalog} onStarted={() => void load()} />
      )}
      {toastNode}
    </ManyWorld>
  );
}
