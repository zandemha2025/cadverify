"use client";

/**
 * ComingDoor — the honest coming-state hero for the `cost` and `portfolio`
 * doors. Their real surfaces (the catalog grid, the exception-first queue) land
 * in FE-4 / FE-5, so this states plainly what's coming and what phase it lands
 * in (mirroring the rail), then points to the REAL capability that exists today.
 * No stubbed grid, no invented rows — a truthful empty zone (D1 standing gate).
 */

import { useRouter } from "next/navigation";
import { Layers, ArrowRight } from "lucide-react";
import { doorById, type DoorId } from "@/lib/doors";
import { Rise } from "@/components/ui/motion";
import { Button } from "@/components/ui/button";
import { DoorCrossNav, DOOR_ICONS, type DoorNav } from "./DoorCrossNav";

/** Per-door honest copy: what's coming, and the real path available today. */
const COMING: Record<
  Exclude<DoorId, "part">,
  { coming: string; today: string; realHref?: { label: string; href: string } }
> = {
  cost: {
    coming:
      "The catalog grid — every part's drivers, rates and calibration in one governed table you can sort, filter and override in bulk — lands with the Governed Catalog.",
    today:
      "It's the same engine today: drop a part and override any rate or assumption in its Glass Box, then save the calibrated scenario.",
  },
  portfolio: {
    coming:
      "The exception-first triage queue over your DFM batch aggregates lands next; the ranked savings pipeline follows once portfolio cost is real (W3).",
    today: "Run many parts at once now — the batch surfaces the exceptions across the set.",
    realHref: { label: "Open a batch run", href: "/batch" },
  },
};

export function ComingDoor({ door, nav }: { door: DoorId; nav: DoorNav }) {
  const router = useRouter();
  const def = doorById(door);
  const Icon = DOOR_ICONS[door];
  const copy = door === "part" ? null : COMING[door];

  return (
    <div className="flex h-full min-h-full flex-col p-6">
      <DoorCrossNav nav={nav} />

      <div className="flex flex-1 items-center justify-center">
        <Rise>
          <div className="max-w-lg text-center">
            <span className="mx-auto flex size-11 items-center justify-center rounded-[var(--radius-lg)] bg-muted text-muted-foreground">
              <Icon className="size-5" />
            </span>

            <p className="num mt-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-text">
              {def.verb} · {def.persona}
            </p>
            <h1 className="mt-1 text-display font-semibold tracking-tight text-foreground">
              {def.question}
            </h1>
            <p className="mx-auto mt-1.5 max-w-prose text-sm text-muted-foreground">
              {def.blurb}
            </p>

            {copy && (
              <div className="mt-5 rounded-[var(--radius-lg)] border border-dashed border-border bg-card p-4 text-left">
                <p className="cv-eyebrow">Coming{def.phase ? ` · ${def.phase}` : ""}</p>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                  {copy.coming}
                </p>
                <p className="mt-3 text-sm leading-relaxed text-foreground">{copy.today}</p>
                {copy.realHref && (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-3"
                    onClick={() => router.push(copy.realHref!.href)}
                  >
                    <Layers className="size-4" />
                    {copy.realHref.label}
                  </Button>
                )}
              </div>
            )}

            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
              <Button onClick={() => nav.onGoDoor("part")}>
                Drop a part instead
                <ArrowRight className="size-4" />
              </Button>
              <Button variant="ghost" onClick={nav.onReChoose}>
                Switch door
              </Button>
            </div>
          </div>
        </Rise>
      </div>
    </div>
  );
}
