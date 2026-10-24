"use client";

/**
 * Was this part made in Design Studio? A part's key is the SHA-256 of its file;
 * a Design Studio revision's STEP carries the same digest (`geometry_hash`, checked
 * on import). So the design and revision are found by matching that hash: never
 * guessed from the file name.
 */
import * as React from "react";
import { listDesignRevisions, listDesigns } from "@/lib/designs-api";
import type { StudioOrigin } from "./capabilities";

const cache = new Map<string, Promise<StudioOrigin | null>>();

async function find(key: string): Promise<StudioOrigin | null> {
  const designs = await listDesigns().catch(() => []);
  for (const d of designs) {
    const r = d.revision;
    if (r?.geometry_hash === key) return { designId: d.id, designName: d.name, revision: r.number, currentRevision: d.current_revision, plan: r.plan, volumeCm3: r.geometry?.volume_cm3 ?? null };
  }
  // Older revisions: only designs that have more than one (a few requests at most).
  for (const d of designs.filter((x) => x.current_revision > 1 && x.status !== "archived").slice(0, 12)) {
    const revs = await listDesignRevisions(d.id).catch(() => []);
    const r = revs.find((x) => x.geometry_hash === key);
    if (r) return { designId: d.id, designName: d.name, revision: r.number, currentRevision: d.current_revision, plan: r.plan, volumeCm3: r.geometry?.volume_cm3 ?? null };
  }
  return null;
}

export function studioOriginOf(key: string): Promise<StudioOrigin | null> {
  if (!cache.has(key)) cache.set(key, find(key).catch(() => null));
  return cache.get(key)!;
}

/** Forget a lookup (a new revision was just made). */
export function forgetStudioOrigin(key: string) {
  cache.delete(key);
}

/** The Design Studio design and revision behind this part, or null (an upload, or not known yet). */
export function useStudioOrigin(key: string | null, tick = 0): StudioOrigin | null {
  const [origin, setOrigin] = React.useState<{ key: string; o: StudioOrigin | null } | null>(null);
  React.useEffect(() => {
    if (!key) return;
    let live = true;
    // A new revision was made since the last look: the current revision number changed.
    if (tick) forgetStudioOrigin(key);
    void studioOriginOf(key).then((o) => {
      if (live) setOrigin({ key, o });
    });
    return () => {
      live = false;
    };
  }, [key, tick]);
  return origin && origin.key === key ? origin.o : null;
}
