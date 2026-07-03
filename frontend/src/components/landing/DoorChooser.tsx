"use client";

/**
 * DoorChooser — the first-run "Where do you work?" screen. Three co-equal doors,
 * three first verbs (DROP / OVERRIDE / TRIAGE). Picking one persists `cv_door`
 * and routes; it walls nothing off — every door stays one "Switch door" away.
 *
 * The `part` door is live today; the `cost` and `portfolio` doors carry their
 * honest roadmap phase (mirroring the rail) so the chooser never oversells a
 * surface that lands in FE-4 / FE-5.
 *
 * Tempo-aware via the shared motion primitives: the first session gets the full
 * showcase choreography, returning sessions get the working (near-instant) pace.
 */

import { ArrowRight } from "lucide-react";
import { DOORS, doorById, type DoorId } from "@/lib/doors";
import { Rise, Stagger } from "@/components/ui/motion";
import { cn } from "@/lib/utils";
import { DOOR_ICONS } from "./DoorCrossNav";

export function DoorChooser({
  current,
  onPick,
}: {
  /** the currently-active door, if re-opening the chooser to switch */
  current: DoorId | null;
  onPick: (id: DoorId) => void;
}) {
  return (
    <div className="flex min-h-full w-full items-center justify-center p-6">
      <div className="w-full max-w-4xl">
        <Rise>
          <div>
            <span className="cv-eyebrow">Three doors · one engine</span>
            <h1 className="mt-2 text-display font-semibold tracking-tight text-foreground">
              Where do you work?
            </h1>
            <p className="mt-1.5 max-w-prose text-sm text-muted-foreground">
              Pick the door that fits how you&apos;ll use CadVerify. You can switch anytime — it&apos;s
              one governed object model behind all three, never three apps.
            </p>
          </div>
        </Rise>

        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <Stagger step={70} ms={380}>
            {DOORS.map((door) => (
              <DoorCard
                key={door.id}
                id={door.id}
                active={door.id === current}
                onPick={onPick}
              />
            ))}
          </Stagger>
        </div>
      </div>
    </div>
  );
}

function DoorCard({
  id,
  active,
  onPick,
}: {
  id: DoorId;
  active: boolean;
  onPick: (id: DoorId) => void;
}) {
  const door = doorById(id);
  const Icon = DOOR_ICONS[id];
  return (
    <button
      type="button"
      onClick={() => onPick(id)}
      aria-current={active ? "true" : undefined}
      className={cn(
        "group flex h-full flex-col rounded-[var(--radius-lg)] border bg-card p-5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-primary bg-accent-subtle"
          : "border-border hover:border-border-strong hover:bg-muted/50"
      )}
    >
      <div className="flex items-center justify-between">
        <span
          className={cn(
            "flex size-9 items-center justify-center rounded-[var(--radius)] transition-colors",
            active
              ? "bg-primary/10 text-primary"
              : "bg-muted text-muted-foreground group-hover:text-foreground"
          )}
        >
          <Icon className="size-[18px]" />
        </span>
        {door.phase ? (
          <span className="cv-eyebrow text-subtle-foreground">{door.phase}</span>
        ) : (
          <span className="num cv-eyebrow text-accent-text">Live</span>
        )}
      </div>

      <span className="num mt-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-text">
        {door.verb}
      </span>
      <span className="mt-1 text-lg font-semibold text-foreground">{door.question}</span>
      <span className="mt-1.5 flex-1 text-sm leading-relaxed text-muted-foreground">
        {door.blurb}
      </span>

      <span className="mt-4 flex items-center gap-1.5 text-xs font-medium text-subtle-foreground">
        {door.persona}
        <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
      </span>
    </button>
  );
}
