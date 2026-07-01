"use client";

/**
 * RoleLens — one engine, five users who pull the UI in opposite directions. The
 * lens is a topbar selector that sets the LANDING tab + default density + default
 * disclosure per role; it walls nothing off (every tab stays one click away —
 * real users wear several hats in one sitting). This is a client-side
 * default-setter over one report; it needs no engine change.
 */

import * as React from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  PenTool,
  Calculator,
  Scale,
  Factory,
  BadgeCheck,
  ChevronDown,
  Check,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type RoleId = "design" | "cost" | "sourcing" | "mfg" | "buyer";
export type Density = "airy" | "medium" | "compact";

export interface RoleDef {
  id: RoleId;
  label: string;
  verb: string;
  /** the tab this role lands on */
  lands: string;
  density: Density;
  /** glass box open by default? */
  disclosed: boolean;
  icon: LucideIcon;
}

export const ROLES: RoleDef[] = [
  { id: "design", label: "Design eng", verb: "Tweak", lands: "Decision", density: "airy", disclosed: false, icon: PenTool },
  { id: "cost", label: "Cost eng", verb: "Override & audit", lands: "Glass Box", density: "compact", disclosed: true, icon: Calculator },
  { id: "sourcing", label: "Sourcing", verb: "Compare & decide", lands: "Compare", density: "medium", disclosed: true, icon: Scale },
  { id: "mfg", label: "Mfg eng", verb: "Verify routing", lands: "Routing & DFM", density: "medium", disclosed: true, icon: Factory },
  { id: "buyer", label: "Buyer", verb: "Trust & approve", lands: "Decision", density: "airy", disclosed: false, icon: BadgeCheck },
];

export function roleById(id: RoleId): RoleDef {
  return ROLES.find((r) => r.id === id) ?? ROLES[0];
}

export function RoleLens({
  value,
  onChange,
  className,
}: {
  value: RoleId;
  onChange: (id: RoleId) => void;
  className?: string;
}) {
  const active = roleById(value);
  const Icon = active.icon;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        className={cn(
          "inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-border bg-card px-2.5 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className
        )}
      >
        <Icon className="size-4 text-accent-text" />
        <span className="text-muted-foreground">Lens</span>
        <span className="font-semibold">{active.label}</span>
        <ChevronDown className="size-3.5 text-muted-foreground" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="cv-reveal z-50 w-72 rounded-[var(--radius-lg)] border border-border bg-card p-1 shadow-pop"
        >
          <p className="cv-eyebrow px-2 py-1.5">Role lens · sets your landing view</p>
          {ROLES.map((r) => {
            const RIcon = r.icon;
            const selected = r.id === value;
            return (
              <DropdownMenu.Item
                key={r.id}
                onSelect={() => onChange(r.id)}
                className={cn(
                  "flex cursor-pointer items-start gap-2.5 rounded-sm px-2 py-2 outline-none focus:bg-muted",
                  selected && "bg-accent-subtle"
                )}
              >
                <RIcon className={cn("mt-0.5 size-4 shrink-0", selected ? "text-accent-text" : "text-muted-foreground")} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-semibold text-foreground">{r.label}</span>
                    {selected && <Check className="size-3.5 text-accent-text" />}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {r.verb} · lands on <span className="font-medium text-foreground">{r.lands}</span>
                  </p>
                </div>
              </DropdownMenu.Item>
            );
          })}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
