/**
 * Plain wording for deleting a part or the organization, and for share links
 * that end. Pure functions over the API's answers so every sentence is tested.
 */

export type LinkStatus = "active" | "expired" | "off";
export type ExpiryChoice = 30 | 90 | 365 | null;

export const EXPIRY_CHOICES: { value: ExpiryChoice; label: string }[] = [
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
  { value: 365, label: "1 year" },
  { value: null, label: "No end date" },
];

export function choiceKey(v: ExpiryChoice): string {
  return v == null ? "none" : String(v);
}

export function choiceFromKey(k: string): ExpiryChoice {
  return k === "none" ? null : k === "90" ? 90 : k === "365" ? 365 : 30;
}

/** "20 Nov 2026" in the reader's zone; "" for nothing. */
export function day(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** One line about a link's end: "Ends 20 Nov 2026", "No end date", "Ended 20 Nov 2026", "Switched off 3 Oct 2026". */
export function linkEndText(status: LinkStatus | null | undefined, expiresAt: string | null | undefined, endedAt?: string | null): string {
  if (status === "off") return endedAt ? `Switched off ${day(endedAt)}` : "Switched off";
  if (status === "expired") return `Ended ${day(endedAt ?? expiresAt)}`;
  if (status === "active") return expiresAt ? `Ends ${day(expiresAt)}` : "No end date";
  return "No link";
}

/** For a link that existed before links had end dates. */
export function endDateAddedNote(expiresAt: string | null | undefined): string {
  return `Made before links had an end date. It was given one: ${day(expiresAt) || "30 days after the change"}.`;
}

export function statusLabel(status: LinkStatus | null | undefined): string {
  return status === "active" ? "On" : status === "expired" ? "Ended" : status === "off" ? "Switched off" : "Off";
}

export interface PartPreview {
  mesh_hash: string;
  exists: boolean;
  file_name?: string | null;
  source_kept?: boolean;
  will_remove?: {
    checks: number;
    cost_records: number;
    fixed_copies: number;
    active_share_links: number;
    actual_costs: number;
    part_context: number;
    batch_items: number;
    rfq_packages_touched: number;
  };
  fixed_copies?: string[];
  can_delete?: boolean;
  reason?: string | null;
  kept?: string[];
  already_deleted?: Receipt;
}

export interface Receipt {
  id: string;
  scope: "part" | "organization";
  target: string;
  status: "removing_files" | "done" | "failed";
  removed: Record<string, unknown>;
  files: { steps_total: number; steps_done: number; removed: number; retrying: boolean };
  created_at: string | null;
  completed_at: string | null;
  kept: string[];
}

function n(count: number, one: string, many = `${one}s`): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? one : many}`;
}

/** What goes, one plain line each, in the order people care about. */
export function partRemovalLines(p: PartPreview, keepCopies: boolean): string[] {
  const w = p.will_remove;
  if (!w) return [];
  const lines: string[] = [];
  if (p.source_kept) lines.push("The stored file you uploaded");
  const results = [w.checks ? n(w.checks, "check") : "", w.cost_records ? n(w.cost_records, "cost record") : ""].filter(Boolean);
  if (results.length) lines.push(`${results.join(" and ")}, with their results and PDFs`);
  const copies = p.fixed_copies?.length ?? 0;
  if (copies && !keepCopies) lines.push(`${n(copies, "copy", "copies")} ScaleCAD fixed from it, with their own checks`);
  if (w.part_context) lines.push("Its program, assembly and yearly volume");
  if (w.actual_costs) lines.push(`${n(w.actual_costs, "actual cost")} logged against this file`);
  if (w.batch_items) lines.push(`Its ${w.batch_items === 1 ? "entry" : "entries"} in ${w.batch_items === 1 ? "a catalog run" : "catalog runs"}`);
  if (w.rfq_packages_touched) lines.push(`Its items in ${n(w.rfq_packages_touched, "supplier package")}`);
  return lines;
}

export function linksLine(p: PartPreview): string | null {
  const k = p.will_remove?.active_share_links ?? 0;
  if (!k) return null;
  return k === 1 ? "The shared link to it stops working now." : `The ${k} shared links to it stop working now.`;
}

export function fingerprint(hash: string): string {
  return hash.slice(0, 12);
}

export function receiptLine(r: Receipt): string {
  if (r.status === "done") return r.scope === "part" ? "Deleted. The stored file and every record of it are gone." : "Deleted. The organization's files and records are gone.";
  if (r.status === "failed") return `The records are deleted. Removing the stored files stopped after repeated errors. Send ScaleCAD support this deletion ID: ${r.id}.`;
  const f = r.files;
  return `The records are deleted. Removing the stored files: ${f.steps_done} of ${f.steps_total} storage areas done${f.retrying ? ", retrying" : ""}.`;
}

export interface OrgPreview {
  org_id: string;
  name: string;
  will_remove: {
    parts: number;
    checks: number;
    cost_records: number;
    batches: number;
    designs: number;
    actual_costs: number;
    members: number;
    pending_invites: number;
    api_keys: number;
    active_share_links: number;
  };
  kept: string[];
}

export function orgRemovalLines(p: OrgPreview): string[] {
  const w = p.will_remove;
  const lines = [
    `${n(w.parts, "part")} with their stored files, ${n(w.checks, "check")} and ${n(w.cost_records, "cost record")}`,
  ];
  if (w.batches) lines.push(n(w.batches, "catalog run"));
  if (w.designs) lines.push(n(w.designs, "Design Studio design"));
  if (w.actual_costs) lines.push(n(w.actual_costs, "logged actual cost"));
  lines.push("Machines, rates, materials, programs, BOMs and settings");
  if (w.active_share_links) lines.push(`${n(w.active_share_links, "shared link")}: they stop working now`);
  if (w.api_keys) lines.push(`${n(w.api_keys, "API key")}: they stop working now`);
  lines.push(`Access for ${n(w.members, "member")}${w.pending_invites ? ` and ${n(w.pending_invites, "pending invite")}` : ""}`);
  return lines;
}

/** The typed name must match exactly (spaces at the ends don't count), as the server checks. */
export function nameMatches(typed: string, name: string): boolean {
  return typed.trim() !== "" && typed.trim() === name.trim();
}
