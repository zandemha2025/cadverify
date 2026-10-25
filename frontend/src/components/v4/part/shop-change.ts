/**
 * Whether Your shop changed after the answer on the part page was worked out
 * (me-11): the record marked out of date by a machine change, or a machine
 * added or edited after the check. The part page then says the answer
 * predates the change and offers Re-check, and a machine row never shows a
 * value declared since next to the check's "not declared".
 *
 * Pure: no React, no fetch, for node --test (shop-change.test.ts).
 */

export const MACHINE_CHANGE_REASON = "machine_inventory_changed";

export interface MachineStamp {
  id: string;
  name: string | null;
  process: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface RecordStamp {
  created_at?: string | null;
  is_stale?: boolean;
  stale_at?: string | null;
  stale_reason?: string | null;
}

export interface ShopChange {
  /** Machines added or edited after the check, newest first. */
  machines: { id: string; name: string; added: boolean; at: string }[];
  /** When the record was marked out of date by a machine change (a removed machine shows only here). */
  staleAt: string | null;
}

function time(s: string | null | undefined): number | null {
  if (!s) return null;
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : null;
}

/** What changed in Your shop after the check at `checkedAt`; null when nothing did, or when it isn't known when the check ran. */
export function shopChangedSince(machines: readonly MachineStamp[], record: RecordStamp | null | undefined, checkedAt: string | null | undefined): ShopChange | null {
  const at = time(checkedAt ?? record?.created_at ?? null);
  const stale = !!record?.is_stale && record.stale_reason === MACHINE_CHANGE_REASON;
  if (at == null) return stale ? { machines: [], staleAt: record?.stale_at ?? null } : null;
  const changed = machines
    .map((m) => {
      const created = time(m.created_at);
      const updated = time(m.updated_at) ?? created;
      const added = created != null && created > at;
      return updated != null && updated > at ? { id: m.id, name: m.name?.trim() || m.process, added, at: (added ? m.created_at : m.updated_at) ?? "" } : null;
    })
    .filter((x): x is NonNullable<typeof x> => x != null)
    .sort((a, b) => (time(b.at) ?? 0) - (time(a.at) ?? 0));
  if (!changed.length && !stale) return null;
  return { machines: changed, staleAt: stale ? record?.stale_at ?? null : null };
}

/** "Amada HG-1003 press brake was edited after this check" / "2 machines were added or edited after this check". */
export function shopChangeText(c: ShopChange): string {
  if (c.machines.length === 1) {
    const m = c.machines[0];
    return `Your ${m.name} was ${m.added ? "added" : "edited"} after this check`;
  }
  if (c.machines.length > 1) return `${c.machines.length} of your machines were added or edited after this check`;
  return "Your machines changed after this check";
}

/** A machine row's reason from the check, said as of the check when the machine changed since. */
export function asOfCheck(why: string, changed: boolean): string {
  if (!changed || !why) return why;
  return `At this check: ${why[0].toLowerCase()}${why.slice(1)} You've changed this machine since; re-check to see it as it is now.`;
}
