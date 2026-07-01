"use client";

/**
 * The slim top strip — all that's left of the chrome after the fat admin
 * sidebar was killed. One row, gets out of the way:
 *
 *   [ wordmark ]  · · ·  [ contextual: the loaded part's identity ]  · · ·  [ ⌘K ] [ theme ] [ account ]
 *
 * When no part is loaded it's just the wordmark + controls. When the Living
 * Instrument publishes a part, the strip shows the part's name, its measured
 * facts, the verdict, and a "New part" reset — the chrome becomes contextual
 * to what you're holding, instead of a persistent list of admin destinations.
 * Everything secondary (Batch, History, Developer, docs) is one ⌘K away.
 */

import Link from "next/link";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, LogOut, Code2, User, Command, RotateCcw } from "lucide-react";
import { useAuth } from "@/components/ui/auth-provider";
import { useCommandPalette } from "@/components/ui/command-palette";
import { useInstrumentChrome } from "@/components/instrument/instrument-chrome";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { StatusBadge } from "@/components/ui/status-badge";

function PartIdentityStrip() {
  const { part } = useInstrumentChrome();
  if (!part) return null;
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="hidden h-5 w-px bg-border sm:block" aria-hidden />
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="num truncate text-sm font-medium text-foreground">
          {part.name}
        </span>
        <span className="hidden items-center gap-x-3 md:flex">
          {part.facts.slice(0, 4).map((f) => (
            <span key={f.label} className="num text-[11px] text-subtle-foreground">
              {f.label} <span className="text-muted-foreground">{f.value}</span>
            </span>
          ))}
        </span>
        {part.verdict ? (
          <StatusBadge verdict={part.verdict} size="sm" />
        ) : part.analyzing ? (
          <span className="num hidden text-[11px] text-subtle-foreground sm:inline">
            analyzing…
          </span>
        ) : null}
      </div>
      {part.onReset && (
        <button
          type="button"
          onClick={part.onReset}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] border border-border px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <RotateCcw className="size-3.5" />
          <span className="hidden sm:inline">New part</span>
        </button>
      )}
    </div>
  );
}

function AccountMenu() {
  const { user, signOut } = useAuth();
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger className="flex items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-sm text-foreground transition-colors hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="flex size-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          <User className="size-3.5" />
        </span>
        {user?.email && (
          <span className="hidden max-w-[12rem] truncate text-muted-foreground lg:inline">
            {user.email}
          </span>
        )}
        <ChevronDown className="size-4 text-subtle-foreground" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="z-[70] min-w-56 rounded-[var(--radius)] border border-border bg-card p-1 text-sm shadow-pop"
        >
          {user && (
            <div className="px-2 py-1.5">
              <p className="truncate font-medium text-foreground">{user.email}</p>
              <p className="text-xs capitalize text-muted-foreground">{user.role}</p>
            </div>
          )}
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item asChild>
            <Link
              href="/settings/developer"
              className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 outline-none hover:bg-muted"
            >
              <Code2 className="size-4" />
              Settings · Developer
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item
            onSelect={() => void signOut()}
            className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-fail outline-none hover:bg-fail-bg"
          >
            <LogOut className="size-4" />
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function TopStrip() {
  const { open } = useCommandPalette();

  return (
    <header className="z-40 flex h-[var(--topbar-h)] shrink-0 items-center gap-3 border-b border-border bg-card px-3 sm:px-4">
      {/* wordmark — the cut display face, not body text */}
      <Link
        href="/cost"
        className="flex shrink-0 items-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="CadVerify — the instrument"
      >
        <span
          aria-hidden
          className="flex size-6 items-center justify-center rounded-[var(--radius-sm)] bg-primary/12 text-primary"
        >
          {/* datum crosshair mark */}
          <svg viewBox="0 0 20 20" className="size-4" fill="none" stroke="currentColor" strokeWidth={1.6}>
            <circle cx="10" cy="10" r="6.4" />
            <path d="M10 1.5v5M10 13.5v5M1.5 10h5M13.5 10h5" strokeLinecap="round" />
          </svg>
        </span>
        <span className="cv-wordmark hidden text-[15px] text-foreground sm:inline">
          CadVerify
        </span>
      </Link>

      {/* contextual: the loaded part's identity */}
      <PartIdentityStrip />

      <div className="flex-1" />

      {/* ⌘K — the secondary nav lives here now, not in a sidebar */}
      <button
        type="button"
        onClick={open}
        className="hidden items-center gap-2 rounded-[var(--radius-sm)] border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex"
        aria-label="Open command palette"
      >
        <span>Jump to…</span>
        <kbd className="num inline-flex items-center gap-0.5 rounded-xs border border-border px-1 py-0.5 text-[10px]">
          <Command className="size-2.5" />K
        </kbd>
      </button>
      {/* compact trigger on small screens */}
      <button
        type="button"
        onClick={open}
        className="inline-flex size-9 items-center justify-center rounded-[var(--radius-sm)] border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:hidden"
        aria-label="Open command palette"
      >
        <Command className="size-4" />
      </button>

      <ThemeToggle />
      <AccountMenu />
    </header>
  );
}
