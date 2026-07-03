"use client";

/**
 * DoorCrossNav — the slim, secondary cross-navigation that rides at the top of
 * every door hero. It is deliberately NOT the hero: it names the door you're in
 * and offers a one-click hop to the other two doors, plus "Switch door" to
 * re-open the first-run chooser. (D5 FE-3 requirement: cross-nav present on every
 * door, never the hero.)
 *
 * Icons mirror the app-shell rail (Catalog = Table2, Portfolio = LayoutDashboard)
 * so a door and its rail domain read as the same object.
 */

import { UploadCloud, Table2, LayoutDashboard, ArrowLeftRight, type LucideIcon } from "lucide-react";
import { DOORS, doorById, type DoorId } from "@/lib/doors";
import { cn } from "@/lib/utils";

export const DOOR_ICONS: Record<DoorId, LucideIcon> = {
  part: UploadCloud,
  cost: Table2,
  portfolio: LayoutDashboard,
};

/** the door-switching handles a hero receives from the landing router. */
export interface DoorNav {
  current: DoorId;
  /** peek at another door for this session (does not change your home door) */
  onGoDoor: (id: DoorId) => void;
  /** re-open the "Where do you work?" chooser */
  onReChoose: () => void;
}

export function DoorCrossNav({ nav, className }: { nav: DoorNav; className?: string }) {
  const here = doorById(nav.current);
  const others = DOORS.filter((d) => d.id !== nav.current);

  return (
    <nav
      aria-label="Switch door"
      className={cn("flex flex-wrap items-center gap-2", className)}
    >
      <span className="cv-eyebrow shrink-0">In · {here.persona}</span>
      <span className="text-subtle-foreground" aria-hidden>
        ·
      </span>
      {others.map((d) => {
        const Icon = DOOR_ICONS[d.id];
        return (
          <button
            key={d.id}
            type="button"
            onClick={() => nav.onGoDoor(d.id)}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-border bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Icon className="size-3.5 text-subtle-foreground" />
            Open {d.object}
            {d.phase && <span className="text-subtle-foreground">· {d.phase}</span>}
          </button>
        );
      })}
      <button
        type="button"
        onClick={nav.onReChoose}
        className="inline-flex items-center gap-1.5 rounded-[var(--radius)] px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeftRight className="size-3.5" />
        Switch door
      </button>
    </nav>
  );
}
