/**
 * A part's next revision (de-11): the fixed file uploaded from a problem card
 * becomes the next revision of the part it fixes, not a stranger.
 *
 * The problem card hands the part it came from to the check page with the
 * file (memory only); the check page notes it on the new check's session; once
 * the check is saved, the part page links the two (PUT /parts/{new}/revision-of)
 * and both parts' pages then say so, with a Compare of the two records.
 */
import { R } from "../routes.ts";

export type RevisionFrom = { key: string; name: string; problem: string | null };
export type RevisionSide = { mesh_hash: string; filename: string; record_id: string | null; problem: string | null; at: string | null };
export type Revisions = { mesh_hash: string; revision_of: RevisionSide | null; next: RevisionSide | null };

let pending: RevisionFrom | null = null;
const bySession = new Map<number, RevisionFrom>();

export function setPendingRevision(from: RevisionFrom): void {
  pending = from;
}

export function takePendingRevision(): RevisionFrom | null {
  const p = pending;
  pending = null;
  return p;
}

export function noteRevision(sessionId: number, from: RevisionFrom): void {
  bySession.set(sessionId, from);
}

export function revisionForSession(sessionId: number | null | undefined): RevisionFrom | null {
  return sessionId == null ? null : bySession.get(sessionId) ?? null;
}

export type RevisionLine = { lead: string; name: string; partHref: string; compareHref: string | null };

/** The header line: "Revision of X · Compare" on the new part, "Next revision: Y · Compare" on the old one. */
export function revisionLine(rev: Revisions | null, selfRecordId: string | null): RevisionLine | null {
  if (!rev) return null;
  const compare = (older: string | null, newer: string | null) => (older && newer ? `${R.compare}?a=${encodeURIComponent(older)}&b=${encodeURIComponent(newer)}` : null);
  if (rev.revision_of) {
    const o = rev.revision_of;
    return { lead: "Revision of", name: o.filename, partHref: R.part(o.mesh_hash), compareHref: compare(o.record_id, selfRecordId) };
  }
  if (rev.next) {
    const n = rev.next;
    return { lead: "Next revision:", name: n.filename, partHref: R.part(n.mesh_hash), compareHref: compare(selfRecordId, n.record_id) };
  }
  return null;
}
