"use client";

/**
 * Batches (board M4): recent batches with their status, items and CSV, the
 * per-batch limits, and the New batch sheet. Pilot plan; other plans see the gate.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { downloadBatchCsv, listBatches, type BatchSummaryRow } from "@/lib/api/batch";
import { R } from "../routes";
import { Chip, Content, Empty, Loading, PageHead, Panel } from "../ui";
import { ManyWorld, PilotGate, errorText, isPaidAccessError, saveBlob, useManyTabs, usePilotAccess, useToast, whenLabel } from "./common";
import { batchStatus } from "./batch-model";
import { NewBatchSheet } from "./new-batch";

export const BATCH_GATE = {
  title: "Batches",
  slot: "ZIP of CAD files",
  features: [
    { title: "Every file checked", text: "DFM on each STL, STEP and IGES in a ZIP up to 5 GB", tone: "#E8EEFB" },
    { title: "Sorted by what you can make", text: "In-house, new equipment, design change, ruled out", tone: "#E3F1E8" },
    { title: "Results CSV", text: "One row per file, with its verdict and findings", tone: "#ECEEF1" },
  ],
  inputs: ["Inputs: a ZIP of parts", "Optional manifest CSV and webhook"],
};

export function BatchesScreen() {
  const router = useRouter();
  const [access, gate] = usePilotAccess();
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

  const csv = async (id: string) => {
    if (csvBusy) return;
    setCsvBusy(id);
    try {
      saveBlob(await downloadBatchCsv(id), `batch_${id}_results.csv`);
      toast(`Downloaded batch_${id}_results.csv`);
    } catch (e) {
      toast(errorText(e, "The CSV didn’t download."));
    } finally {
      setCsvBusy(null);
    }
  };

  const tabs = useManyTabs(rows ? { count: rows.length, exact: !more } : null);

  if (access === "gated") return <PilotGate {...BATCH_GATE} />;

  const n = rows?.length ?? 0;
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
          "ZIP up to 5 GB",
          "1 to 12 files at a time",
          "Pilot plan",
        ]}
        tabs={tabs}
        tabsLabel="Many parts"
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
              Saved batches are unchanged. {err}
            </Empty>
          ) : !rows ? (
            <Loading rows={3} label="Loading batches" />
          ) : rows.length === 0 ? (
            <Empty title="No batches yet">Start one with a ZIP of CAD files. Each file gets its own DFM check.</Empty>
          ) : (
            <div style={{ padding: "0 8px 8px" }}>
              <table className="bt stack">
                <thead>
                  <tr>
                    <th scope="col">Batch</th>
                    <th scope="col">Status</th>
                    <th scope="col">Items</th>
                    <th scope="col">Created</th>
                    <th scope="col">
                      <span className="sr">Results</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((b) => {
                    const s = batchStatus(b.status);
                    const canCsv = b.status === "completed" || b.status === "failed";
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
                          <Link className="rowlink" href={R.batch(b.batch_ulid)} aria-label={`Open batch ${b.batch_ulid}`}>
                            {b.batch_ulid.slice(0, 12)}…
                          </Link>
                        </td>
                        <td>
                          <Chip tone={s.tone}>{s.label}</Chip>
                        </td>
                        <td className="num" data-k="Items">
                          {b.completed_items}/{b.total_items}
                          {b.failed_items > 0 ? <span style={{ color: "var(--bad)" }}> · {b.failed_items} failed</span> : null}
                          {b.skipped_items > 0 ? <span style={{ color: "var(--ink3)" }}> · {b.skipped_items} skipped</span> : null}
                        </td>
                        <td className="num" style={{ color: "var(--ink2)" }}>
                          {whenLabel(b.created_at)}
                        </td>
                        <td className="r">
                          {canCsv ? (
                            <button className="btn sm" type="button" onClick={() => void csv(b.batch_ulid)} disabled={csvBusy === b.batch_ulid}>
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
        <Panel title="Limits" note="Per batch">
          <div className="lim num">
            <div>
              <b>5 GB</b>ZIP size
            </div>
            <div>
              <b>1–12</b>Files at a time
            </div>
            <div>
              <b>STL · STEP · IGES</b>Inside the ZIP
            </div>
            <div>
              <b>CSV</b>Results when done
            </div>
          </div>
        </Panel>
      </Content>
      <NewBatchSheet onCreated={() => void load()} onPaidAccess={gate} toast={toast} />
      {toastNode}
    </ManyWorld>
  );
}
