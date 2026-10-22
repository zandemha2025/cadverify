/**
 * A big kept part's re-price or mesh repair on ScaleCAD's worker
 * (POST /parts/{hash}/recheck or /repair answered 202 with the job): what the
 * work bar and the part page say about it, from the job's own state
 * (GET /checks/{id}). Pure, so it runs under node --test.
 */

export type KeptAction = "recheck" | "repair";

export interface KeptJobStatus {
  check_id: string;
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  progress: number | null;
  source?: string;
  action?: string;
  filename: string | null;
  part_filename?: string | null;
  mesh_hash: string | null;
  summary?: string | null;
  part_url: string | null;
  error: { code: string; message: string } | null;
  result?: unknown;
}

/** A 202 from a kept-part route: the job, not the answer. */
export function isKeptJob(body: unknown): body is KeptJobStatus {
  const b = body as Partial<KeptJobStatus> | null;
  return !!b && typeof b.check_id === "string" && b.source === "kept" && (b.action === "recheck" || b.action === "repair");
}

const STAGE: Record<string, string> = {
  queued: "Waiting for a worker",
  sizing: "Sizing the file",
  pricing: "Pricing",
  repairing: "Repairing a copy",
};

export function keptStageWord(stage: string | null | undefined): string {
  return STAGE[stage ?? ""] ?? "Working";
}

function nameOf(s: Pick<KeptJobStatus, "part_filename" | "filename">): string {
  return s.part_filename || s.filename || "part";
}

/** The work bar's line for the job: running, done or stopped. */
export function keptWorkLine(s: KeptJobStatus): { state: "running" | "done" | "stopped"; label: string; detail: string; href: string; progress: number | null } {
  const name = nameOf(s);
  const repair = s.action === "repair";
  const partHref = s.mesh_hash ? `/app/part/${encodeURIComponent(s.mesh_hash)}` : "/app/parts";
  if (s.status === "done") {
    return { state: "done", label: repair ? `Mesh repair of ${name}` : `Re-priced ${name}`, detail: s.summary || (repair ? "Finished" : "Ready"), href: s.part_url || partHref, progress: 1 };
  }
  if (s.status === "failed") {
    const first = s.error?.message?.split(". ")[0];
    return { state: "stopped", label: repair ? `${name}: not repaired` : `${name}: not re-priced`, detail: first || "It didn’t finish", href: partHref, progress: null };
  }
  return { state: "running", label: repair ? `Repairing a copy of ${name}` : `Re-pricing ${name}`, detail: keptStageWord(s.stage), href: partHref, progress: s.progress };
}

/** What the part page says while its kept file is worked on by the worker. */
export function keptToastLine(stage: string | null | undefined): string {
  return `a large file, on ScaleCAD’s worker: ${keptStageWord(stage).toLowerCase()}`;
}
