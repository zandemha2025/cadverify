"use client";

/**
 * Has this file been checked before? A check means a part: the server counts
 * a file once (its name and bytes), and every later step on the same file
 * reuses that check, even with the allowance spent. The browser can't ask the
 * allowance directly, so it asks the organization's records: one with this
 * file's fingerprint and name means it was checked before. The server stays the
 * authority; this only keeps the copy and the client-side gate from claiming a
 * check the server won't take.
 */
import { fetchCostDecisions } from "@/lib/api";
import { computeMeshHash } from "@/lib/verify/part-context";

const memo = new Map<string, Promise<boolean | null>>();

function sig(f: File): string {
  return `${f.name}\u0000${f.size}\u0000${f.lastModified}`;
}

/** true: a record exists for this exact file; false: none; null: couldn't tell. */
export function checkedBefore(file: File): Promise<boolean | null> {
  const k = sig(file);
  let p = memo.get(k);
  if (!p) {
    p = (async () => {
      const hash = await computeMeshHash(file).catch(() => null);
      if (!hash) return null;
      try {
        const page = await fetchCostDecisions({ meshHash: hash, limit: 20 });
        return (page.cost_decisions ?? []).some((d) => d.filename === file.name);
      } catch {
        return null;
      }
    })();
    p.then((v) => {
      if (v == null) memo.delete(k);
    });
    memo.set(k, p);
  }
  return p;
}

/** Forget what's known (after a check finishes, a file that wasn't checked now is). */
export function forgetChecked(): void {
  memo.clear();
}
