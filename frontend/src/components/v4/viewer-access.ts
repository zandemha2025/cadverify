/**
 * Org viewers are read-only: they open their organization's parts and records
 * but can't check new parts. The server refuses a viewer's check with
 * `org_member_required` (403) and this same line as its message; these helpers
 * let the app say it before any file moves, so Check a part is off instead of
 * failing.
 */

export interface ActiveOrg {
  name: string;
  org_role: string;
}

/** The line a viewer sees wherever they would check a part. */
export function viewerCheckLine(orgName: string | null | undefined): string {
  const org = orgName && orgName.trim() ? orgName.trim() : "this organization";
  return `You're a viewer in ${org}: you can open its parts and records. Ask an admin for member access to check new parts.`;
}

/** The viewer line for the active org, or null when the role may check parts (or isn't known yet). */
export function checkBlockedLine(active: ActiveOrg | null | undefined): string | null {
  if (!active || active.org_role !== "viewer") return null;
  return viewerCheckLine(active.name);
}

/**
 * The one line beside a write control a viewer can't use (disabled, never
 * offered as if it would work): "Viewers can't change parts. Ask an admin for
 * Member access." `what` names the thing ("change the shop's machines").
 */
export function viewerWriteLine(what = "change parts"): string {
  return `Viewers can't ${what}. Ask an admin for Member access.`;
}

/** The viewer write line for the active org, or null when the role may write (or isn't known yet). */
export function writeBlockedLine(active: ActiveOrg | null | undefined, what?: string): string | null {
  if (!active || active.org_role !== "viewer") return null;
  return viewerWriteLine(what);
}
