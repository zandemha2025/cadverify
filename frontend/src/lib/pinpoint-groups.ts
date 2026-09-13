import type { Issue } from "@/lib/api";
import type { IndexedIssue } from "@/lib/dfm-scope";

export interface PinpointGroup {
  key: string;
  code: string;
  regionCenter: [number, number, number] | null;
  faces: number[];
  members: IndexedIssue[];
  processes: string[];
  severity: "error" | "warning";
  issue: Issue;
}

function regionKey(region: [number, number, number] | undefined): string {
  return region ? region.map((value) => Number(value.toFixed(6))).join(",") : "faces";
}

/** One physical defect per code + payload location. Process rows become implications. */
export function groupPinpointIssues(rows: readonly IndexedIssue[]): PinpointGroup[] {
  const groups = new Map<string, PinpointGroup>();
  for (const row of rows) {
    const issue = row.issue;
    if (issue.severity !== "error" && issue.severity !== "warning") continue;
    const key = `${issue.code}|${regionKey(issue.region_center)}`;
    const existing = groups.get(key);
    if (existing) {
      existing.members.push(row);
      existing.faces = Array.from(new Set([...existing.faces, ...row.faces]));
      if (issue.process && !existing.processes.includes(issue.process)) existing.processes.push(issue.process);
      if (issue.severity === "error") {
        existing.severity = "error";
        existing.issue = issue;
      }
      continue;
    }
    groups.set(key, {
      key,
      code: issue.code,
      regionCenter: issue.region_center ?? null,
      faces: [...row.faces],
      members: [row],
      processes: issue.process ? [issue.process] : [],
      severity: issue.severity,
      issue,
    });
  }
  return Array.from(groups.values());
}

export function groupForIssueKey(groups: readonly PinpointGroup[], issueKey: string | null): PinpointGroup | null {
  if (!issueKey) return null;
  return groups.find((group) => group.members.some((row) => row.key === issueKey)) ?? null;
}
