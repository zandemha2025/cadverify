import type { Issue } from "@/lib/api";
import { issueIdentity, issueProcesses, issueWithFaces, type IndexedIssue } from "./dfm-scope.ts";

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

/** Only matching evidence can share advice and affected-process labels. */
export function groupPinpointIssues(rows: readonly IndexedIssue[]): PinpointGroup[] {
  const groups = new Map<string, PinpointGroup>();
  const keys = new Set<string>();
  for (const row of rows) {
    const issue = row.issue;
    if (issue.severity !== "error" && issue.severity !== "warning") continue;
    const identity = issueIdentity(issue);
    const existing = groups.get(identity);
    if (existing) {
      existing.members.push(row);
      existing.faces = Array.from(new Set([...existing.faces, ...row.faces]));
      existing.issue = issueWithFaces(existing.issue, existing.faces);
      existing.processes = Array.from(new Set([...existing.processes, ...issueProcesses(row)]));
      continue;
    }
    const base = `${issue.code}|${regionKey(issue.region_center)}`;
    let key = base;
    for (let suffix = 1; keys.has(key); suffix++) key = `${base}:${suffix}`;
    keys.add(key);
    groups.set(identity, {
      key,
      code: issue.code,
      regionCenter: issue.region_center ?? null,
      faces: [...row.faces],
      members: [row],
      processes: [...issueProcesses(row)],
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
