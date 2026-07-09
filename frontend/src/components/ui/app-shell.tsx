"use client";

/**
 * The persistent 4-zone platform shell — the "governed catalog" frame that
 * replaces the single-part instrument's slim top strip (Gen-3) and the orphaned
 * tabbed workspace's ad-hoc chrome (Gen-2). One shell, four zones:
 *
 *   rail 56 · sidebar 240 (collapsible) · context bar 48 · content · [Inspector]
 *
 * The Inspector (340) is a PER-DECISION zone owned by the L2 object frame
 * (PartWorkspace), so it mounts inside `children`, not here — the shell reserves
 * the frame and hosts navigation for the routes that exist in this app tree.
 *
 * Server-gated upstream (AppLayout → verifySession); this is presentation only.
 */

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Boxes,
  Code2,
  Command,
  Search,
  ScanLine,
  Calculator,
  Database,
  FileCheck2,
  Layers,
  History,
  PiggyBank,
  GitCompareArrows,
  PanelLeftClose,
  PanelLeftOpen,
  ChevronRight,
  User,
  Building2,
  LogOut,
  Lock,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/components/ui/auth-provider";
import { CommandPaletteProvider, useCommandPalette } from "@/components/ui/command-palette";
import { InstrumentChromeProvider, useInstrumentChrome } from "@/components/instrument/instrument-chrome";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { StatusBadge } from "@/components/ui/status-badge";

/* Routes that render full-fluid (the workspace needs its width); everything
   else gets a comfortable reading container. */
const FLUID = new Set(["/cost", "/analyze"]);
/* The genuinely local cost/DFM decision path — the ONLY place we assert
   zero-egress (image→mesh reconstruction is out of scope, handled elsewhere). */
const LOCAL_PATHS = ["/cost", "/analyze", "/cost-decisions", "/history", "/batch", "/rfq-packages"];

/* ── L1 icon rail — the object domains you fly between (catalog-forward). ──── */
type RailItem = {
  id: string;
  label: string;
  icon: LucideIcon;
  href: string;
};
const RAIL: RailItem[] = [
  { id: "verify", label: "Verify workspace", icon: FileCheck2, href: "/verify" },
  { id: "home", label: "Legacy workbench", icon: Boxes, href: "/cost" },
  { id: "analyze", label: "Analyze DFM", icon: ScanLine, href: "/analyze" },
  { id: "batch", label: "Batch runs", icon: Layers, href: "/batch" },
  { id: "decisions", label: "Cost decisions", icon: PiggyBank, href: "/cost-decisions" },
  { id: "history", label: "Recent analyses", icon: History, href: "/history" },
];

function railActive(pathname: string, item: RailItem): boolean {
  return pathname === item.href || pathname.startsWith(item.href + "/");
}

function IconRail() {
  const pathname = usePathname();
  return (
    <Tooltip.Provider delayDuration={200}>
      <nav
        aria-label="Domains"
        className="flex w-[var(--rail-w)] shrink-0 flex-col items-center gap-1 border-r border-border bg-background py-3"
      >
        {/* brand mark — the datum crosshair, cobalt */}
        <Link
          href="/verify"
          aria-label="CadVerify"
          className="mb-2 flex size-9 items-center justify-center rounded-[var(--radius-sm)] text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <svg viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth={1.6}>
            <circle cx="10" cy="10" r="6.4" />
            <path d="M10 1.5v5M10 13.5v5M1.5 10h5M13.5 10h5" strokeLinecap="round" />
          </svg>
        </Link>

        {RAIL.map((item) => {
          const Icon = item.icon;
          const active = railActive(pathname, item);
          const inner = (
            <span
              className={cn(
                "relative flex size-9 items-center justify-center rounded-[var(--radius-sm)] transition-colors",
                active
                  ? "bg-accent-subtle text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {active && (
                <span className="absolute -left-3 top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-full bg-primary" aria-hidden />
              )}
              <Icon className="size-[18px]" />
            </span>
          );
          return (
            <Tooltip.Root key={item.id}>
              <Tooltip.Trigger asChild>
                <Link href={item.href} aria-label={item.label} aria-current={active ? "page" : undefined}>
                  {inner}
                </Link>
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content
                  side="right"
                  sideOffset={8}
                  className="z-[90] rounded-[var(--radius-sm)] border border-border bg-card px-2 py-1 text-xs text-foreground shadow-pop"
                >
                  {item.label}
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>
          );
        })}

        <div className="flex-1" />
        <ThemeToggle className="size-9 border-0 bg-transparent" />
        <AccountMenu />
      </nav>
    </Tooltip.Provider>
  );
}

/* ── L1 sidebar — object lists + saved views within a domain. ───────── */
type NavLink = { label: string; href: string; icon: LucideIcon; hint?: string };
const WORKSPACE_NAV: NavLink[] = [
  { label: "Verify workspace", href: "/verify", icon: FileCheck2, hint: "canonical product surface" },
  { label: "Legacy analysis", href: "/cost", icon: Calculator, hint: "should-cost · make-vs-buy" },
  { label: "Analyze DFM", href: "/analyze", icon: ScanLine, hint: "geometry · flags" },
  { label: "Batch run", href: "/batch", icon: Layers, hint: "many parts" },
];
const LEDGER_NAV: NavLink[] = [
  { label: "Cost decisions", href: "/cost-decisions", icon: PiggyBank, hint: "saved" },
  { label: "Compare A/B", href: "/cost-decisions/compare", icon: GitCompareArrows },
  { label: "RFQ packages", href: "/rfq-packages", icon: FileCheck2 },
  { label: "Recent analyses", href: "/history", icon: History },
  { label: "Integrations", href: "/integrations", icon: Database },
  { label: "API & docs", href: "/settings/developer", icon: Code2 },
  { label: "Organization", href: "/settings/organization", icon: Building2, hint: "members · SSO" },
];

function SidebarLink({ link }: { link: NavLink }) {
  const pathname = usePathname();
  const Icon = link.icon;
  const active = pathname === link.href;
  return (
    <Link
      href={link.href}
      className={cn(
        "group flex items-center gap-2.5 rounded-[var(--radius-sm)] px-2 py-1.5 text-sm transition-colors",
        active
          ? "bg-accent-subtle text-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      <Icon className={cn("size-4 shrink-0", active ? "text-primary" : "text-subtle-foreground")} />
      <span className="min-w-0 flex-1 truncate font-medium">{link.label}</span>
      {link.hint && (
        <span className="hidden truncate text-[10px] text-subtle-foreground group-hover:inline">
          {link.hint}
        </span>
      )}
    </Link>
  );
}

function SidebarSection({ title, links }: { title: string; links: NavLink[] }) {
  return (
    <div className="px-2">
      <p className="px-2 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-subtle-foreground">
        {title}
      </p>
      <div className="space-y-0.5">
        {links.map((l) => (
          <SidebarLink key={l.href} link={l} />
        ))}
      </div>
    </div>
  );
}

function AppSidebar() {
  const { open } = useCommandPalette();
  return (
    <aside className="flex w-[var(--sidebar-w)] shrink-0 flex-col overflow-y-auto border-r border-border bg-background">
      {/* ⌘K search — the co-primary navigator lives at the top of the sidebar */}
      <div className="p-2">
        <button
          type="button"
          onClick={open}
          className="flex w-full items-center gap-2 rounded-[var(--radius-sm)] border border-border bg-card px-2.5 py-2 text-left text-sm text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Search className="size-4 shrink-0 text-subtle-foreground" />
          <span className="flex-1">Search…</span>
          <kbd className="num inline-flex items-center gap-0.5 rounded-xs border border-border px-1 py-0.5 text-[10px]">
            <Command className="size-2.5" />K
          </kbd>
        </button>
      </div>

      <SidebarSection title="Workspace" links={WORKSPACE_NAV} />
      <SidebarSection title="Ledger" links={LEDGER_NAV} />

      <div className="flex-1" />
      <p className="p-3 text-[10px] leading-relaxed text-subtle-foreground">
        One governed object model · a Decision contains Estimates.
      </p>
    </aside>
  );
}

/* ── L1 context bar — the lakehouse breadcrumb + data-locality signal. ─────── */
function ContextBar({
  sidebarOpen,
  onToggleSidebar,
}: {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}) {
  const pathname = usePathname();
  const { part } = useInstrumentChrome();
  const isLocal = LOCAL_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"));

  return (
    <header className="flex h-[var(--contextbar-h)] shrink-0 items-center gap-2 border-b border-border bg-background px-3">
      <button
        type="button"
        onClick={onToggleSidebar}
        aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
        className="inline-flex size-7 items-center justify-center rounded-[var(--radius-sm)] text-subtle-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {sidebarOpen ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}
      </button>

      {/* namespace breadcrumb — the single cheapest "governed platform" signal */}
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
        <span className="num text-muted-foreground">workspace</span>
        <ChevronRight className="size-3.5 shrink-0 text-subtle-foreground" aria-hidden />
        <span className="num text-muted-foreground">decisions</span>
        {part && (
          <>
            <ChevronRight className="size-3.5 shrink-0 text-subtle-foreground" aria-hidden />
            <span className="num truncate font-medium text-foreground">{part.name}</span>
            {part.verdict ? (
              <StatusBadge verdict={part.verdict} size="sm" />
            ) : part.analyzing ? (
              <span className="num text-[11px] text-subtle-foreground">analyzing…</span>
            ) : null}
          </>
        )}
      </nav>

      <div className="flex-1" />

      {/* data-locality — asserted ONLY on the genuinely local cost/DFM path */}
      {isLocal && (
        <span
          title="CAD is parsed and discarded in-process — zero network egress on the cost/DFM decision path."
          className="hidden items-center gap-1.5 rounded-[var(--radius-sm)] border border-prov-shop-border bg-prov-shop-bg px-2 py-1 text-[11px] font-medium text-prov-shop sm:inline-flex"
        >
          <Lock className="size-3" aria-hidden />
          LOCAL · zero-egress
        </span>
      )}
    </header>
  );
}

function AccountMenu() {
  const { user, signOut } = useAuth();
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        aria-label="Account"
        className="flex size-9 items-center justify-center rounded-[var(--radius-sm)] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex size-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          <User className="size-3.5" />
        </span>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="right"
          align="end"
          sideOffset={8}
          className="z-[90] min-w-56 rounded-[var(--radius)] border border-border bg-card p-1 text-sm shadow-pop"
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
          <DropdownMenu.Item asChild>
            <Link
              href="/settings/organization"
              className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 outline-none hover:bg-muted"
            >
              <Building2 className="size-4" />
              Settings · Organization
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

function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = React.useState(true);
  const fluid = FLUID.has(pathname);

  return (
    <div className="flex h-screen overflow-hidden bg-canvas text-foreground">
      <IconRail />
      {sidebarOpen && <AppSidebar />}
      <div className="flex min-w-0 flex-1 flex-col">
        <ContextBar sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen((o) => !o)} />
        <main className="min-h-0 flex-1 overflow-y-auto">
          {fluid ? (
            <div className="h-full">{children}</div>
          ) : (
            <div className="mx-auto w-full max-w-screen-2xl px-6 py-8 lg:px-8">{children}</div>
          )}
        </main>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <InstrumentChromeProvider>
      <CommandPaletteProvider>
        <Shell>{children}</Shell>
      </CommandPaletteProvider>
    </InstrumentChromeProvider>
  );
}
