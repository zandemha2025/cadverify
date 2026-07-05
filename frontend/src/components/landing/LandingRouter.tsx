"use client";

/**
 * LandingRouter — the flag-gated entry experience (D5 FE-3). On authed app load
 * with STAGE_UI on, it resolves which door to land the user at:
 *
 *   1. a persisted choice (`cv_door` in localStorage) — always wins;
 *   2. otherwise a recognised persona from the session role;
 *   3. otherwise the first-run DOOR CHOOSER ("Where do you work?").
 *
 * Picking a door persists it and routes. The door graduates the glass-box
 * `role-lens` idea from a topbar toggle into the front door — the persona is now
 * chosen at entry, not mid-part. The router walls nothing off: every hero carries
 * cross-nav to the other doors and a "Switch door" back to the chooser.
 *
 * SSR note: the first paint (server + first client render) is a neutral skeleton
 * — localStorage can't be read on the server — and the real door resolves in an
 * effect on mount, matching the TempoProvider's SSR-safe pattern. This component
 * is only ever mounted from the `STAGE_UI` branch of the /cost route, so flag-off
 * it never renders.
 */

import { useCallback, useEffect, useState } from "react";
import { DOOR_STORAGE_KEY, resolveDoor, type DoorId } from "@/lib/doors";
import { useAuth } from "@/components/ui/auth-provider";
import { Skeleton } from "@/components/ui/skeleton";
import { DoorChooser } from "./DoorChooser";
import { PartDoor } from "./PartDoor";
import { CatalogDoor } from "./catalog/CatalogDoor";
import { PortfolioDoor } from "./portfolio/PortfolioDoor";
import type { DoorNav } from "./DoorCrossNav";

function readDoor(): string | null {
  try {
    return window.localStorage.getItem(DOOR_STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistDoor(id: DoorId) {
  try {
    window.localStorage.setItem(DOOR_STORAGE_KEY, id);
  } catch {
    /* private mode / disabled storage: the choice just won't survive a reload */
  }
}

export default function LandingRouter() {
  const { user } = useAuth();
  const [ready, setReady] = useState(false);
  const [door, setDoor] = useState<DoorId | null>(null);
  const [choosing, setChoosing] = useState(false);

  useEffect(() => {
    const resolved = resolveDoor({ persisted: readDoor(), role: user?.role ?? null });
    setDoor(resolved);
    setChoosing(resolved === null);
    setReady(true);
  }, [user]);

  // Chosen from the first-run chooser: persist + route.
  const pick = useCallback((id: DoorId) => {
    persistDoor(id);
    setDoor(id);
    setChoosing(false);
  }, []);

  // Cross-nav: a transient peek at another door for this session only. It does
  // NOT re-persist the home door — the chooser is the one place that sets your
  // home (so a curious "Open portfolio" click doesn't quietly move you there
  // next session). Reloading returns to the persisted/role-resolved door.
  const goDoor = useCallback((id: DoorId) => {
    setDoor(id);
    setChoosing(false);
  }, []);

  const reChoose = useCallback(() => setChoosing(true), []);

  if (!ready) return <LandingSkeleton />;

  if (choosing || door === null) {
    return <DoorChooser current={door} onPick={pick} />;
  }

  const nav: DoorNav = { current: door, onGoDoor: goDoor, onReChoose: reChoose };

  switch (door) {
    case "part":
      return <PartDoor nav={nav} />;
    case "cost":
      return <CatalogDoor nav={nav} />;
    case "portfolio":
      return <PortfolioDoor nav={nav} />;
  }
}

/** Neutral first-paint placeholder — no door flicker before resolution. */
function LandingSkeleton() {
  return (
    <div className="flex min-h-full w-full items-center justify-center p-6">
      <div className="w-full max-w-4xl space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-9 w-72" />
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-44 w-full rounded-[var(--radius-lg)]" />
          ))}
        </div>
      </div>
    </div>
  );
}
