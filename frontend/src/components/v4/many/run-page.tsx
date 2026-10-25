"use client";

/**
 * /app/many/[id]: a catalog run opens its sorted board; any other batch opens
 * the batch run screen. One progress read decides which.
 */
import * as React from "react";
import { getBatchProgress } from "@/lib/api/batch";
import { Content, Loading, PageHead } from "../ui";
import { BatchRun } from "./batch-run";
import { CatalogBoard } from "./catalog-board";
import { ManyWorld } from "./common";

export function RunPage({ batchId }: { batchId: string }) {
  const [kind, setKind] = React.useState<"loading" | "catalog" | "batch">("loading");
  React.useEffect(() => {
    let live = true;
    getBatchProgress(batchId)
      .then((p) => live && setKind((p as { job_type?: string }).job_type === "catalog" ? "catalog" : "batch"))
      .catch(() => live && setKind("batch"));
    return () => {
      live = false;
    };
  }, [batchId]);
  if (kind === "catalog") return <CatalogBoard batchId={batchId} />;
  if (kind === "batch") return <BatchRun batchId={batchId} />;
  return (
    <ManyWorld label="Run">
      <PageHead title="Run" />
      <Content>
        <Loading rows={4} label="Loading the run" />
      </Content>
    </ManyWorld>
  );
}
