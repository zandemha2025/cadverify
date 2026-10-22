"use client";

/**
 * The way into a catalog run from elsewhere (Home, Your shop): "Check a batch
 * of parts", with what the account gets (up to 50 free with a work email,
 * pilot, or pilot-only for personal email). Several files dropped somewhere
 * else are handed straight to the new-run sheet.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useShell } from "../shell";
import { catalogAccess, type CatalogAccess } from "./catalog-model";
import { NEW_RUN_HREF } from "./catalog-routes";
import { setPendingBatch } from "./pending-batch";
import { listBatches } from "@/lib/api/batch";
import { R } from "../routes";

/** "Up to 50 free · files, a folder or a ZIP", by what the account has. */
export function batchEntryNote(a: CatalogAccess): string {
  if (a.kind === "free") {
    const { cap, remaining, used, reserved } = a.usage;
    if (cap != null && remaining != null && (used ?? 0) + (reserved ?? 0) > 0) return remaining ? `${remaining} of ${cap} free parts left` : `${cap} free parts used · pilot for more`;
    return `Up to ${cap ?? 50} free · files, a folder or a ZIP`;
  }
  if (a.kind === "pilot") return "Files, a folder or a ZIP · no part limit";
  if (a.kind === "personal") return "Pilot, or 50 free with a work email";
  return "Files, a folder or a ZIP";
}

export function useBatchAccess(): CatalogAccess {
  const { usage } = useShell();
  return React.useMemo(() => (usage ? catalogAccess(usage) : { kind: "loading" as const }), [usage]);
}

/** Hands dropped files to a new catalog run and opens it. */
export function useHandOffBatch(): (files: File[]) => void {
  const router = useRouter();
  return React.useCallback(
    (files: File[]) => {
      setPendingBatch(files);
      router.push(NEW_RUN_HREF);
    },
    [router],
  );
}

/** The newest catalog run of the organization, for a way back to its answer from Home. */
export function useLastRun(): { id: string; name: string; status: string; files: number; notChecked: number } | null {
  const [run, setRun] = React.useState<{ id: string; name: string; status: string; files: number; notChecked: number } | null>(null);
  React.useEffect(() => {
    let live = true;
    listBatches({ limit: 20 }).then(
      (r) => {
        const b = r.batches.find((x) => x.job_type === "catalog");
        if (live && b) setRun({ id: b.batch_ulid, name: b.name || "Catalog run", status: b.status, files: b.total_items, notChecked: b.failed_items });
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);
  return run;
}

/** "Finished · 50 files · 16 not checked" for the way back to a run. */
export function lastRunNote(r: { status: string; files: number; notChecked: number }): string {
  const state = r.status === "completed" ? "Finished" : r.status === "cancelled" ? "Cancelled" : r.status === "failed" ? "Didn’t start" : "Running";
  return [state, `${r.files.toLocaleString("en-US")} ${r.files === 1 ? "file" : "files"}`, r.notChecked ? `${r.notChecked} not checked` : null].filter(Boolean).join(" · ");
}

/** A row link in a list of ways to start (Home's "Start" and "Check another part" lists), with the way back to the last run. */
export function BatchEntryRow() {
  const a = useBatchAccess();
  const last = useLastRun();
  return (
    <>
      {last ? (
        <Link href={R.batch(last.id)}>
          <span>
            Your catalog run: {last.name}
            <small>{lastRunNote(last)}</small>
          </span>
          <i aria-hidden="true">→</i>
        </Link>
      ) : null}
      <Link href={NEW_RUN_HREF}>
        <span>
          Check a batch of parts<small>{batchEntryNote(a)}</small>
        </span>
        <i aria-hidden="true">→</i>
      </Link>
    </>
  );
}

/** A button next to the single-part start, with its note. */
export function BatchEntryButton({ className = "btn" }: { className?: string }) {
  return (
    <Link className={className} href={NEW_RUN_HREF}>
      Check a batch of parts
    </Link>
  );
}

export { NEW_RUN_HREF };
