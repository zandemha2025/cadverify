"use client";

/**
 * The command palette (⌘K) — the secondary navigation for the instrument shell.
 *
 * The founder killed the persistent left admin sidebar; the destinations that
 * used to live there (Batch, History, Developer, API docs) now live here, one
 * keystroke away, out of the way of the part→decision core. This is the
 * pro-tool move (Figma/Linear/Raycast): the chrome disappears until you summon
 * it. Open with ⌘K / Ctrl-K anywhere, or the ⌘K button in the top strip.
 *
 * Built on the installed Radix Dialog (no cmdk dependency): a focus-trapped
 * overlay with a live filter, arrow-key navigation, Enter to run, Esc to close.
 */

import * as React from "react";
import { useRouter, usePathname } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import {
  ScanLine,
  Calculator,
  Layers,
  History,
  PiggyBank,
  GitCompareArrows,
  Code2,
  BookOpen,
  Tags,
  Palette,
  Moon,
  LogOut,
  Search,
  CornerDownLeft,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/components/ui/auth-provider";
import { DEV_TOOLS_ENV, devToolsEnabled } from "@/lib/dev-flag";

type Command = {
  id: string;
  label: string;
  hint?: string;
  keywords?: string;
  icon: LucideIcon;
  section: "Go to" | "Actions";
  devOnly?: boolean;
  run: (ctx: CommandCtx) => void;
};

type CommandCtx = {
  push: (href: string) => void;
  signOut: () => void;
  toggleTheme: () => void;
};

const COMMANDS: Command[] = [
  { id: "analyze", label: "Analyze a part", hint: "DFM · geometry", keywords: "dfm flags manufacturability geometry inspect", icon: ScanLine, section: "Go to", run: (c) => c.push("/analyze") },
  { id: "cost", label: "Cost & make-vs-buy", hint: "the instrument", keywords: "should cost price quantity crossover breakeven scrubber", icon: Calculator, section: "Go to", run: (c) => c.push("/cost") },
  { id: "batch", label: "Batch analysis", hint: "many parts at once", keywords: "zip upload bulk", icon: Layers, section: "Go to", run: (c) => c.push("/batch") },
  { id: "cost-decisions", label: "Cost history", hint: "saved should-cost decisions", keywords: "saved should cost make vs buy decisions export share compare artifact", icon: PiggyBank, section: "Go to", run: (c) => c.push("/cost-decisions") },
  { id: "cost-decisions/compare", label: "Compare cost decisions", hint: "two decisions side by side", keywords: "compare diff make vs buy cost side by side", icon: GitCompareArrows, section: "Go to", run: (c) => c.push("/cost-decisions/compare") },
  { id: "history", label: "History", hint: "recent analyses · quota", keywords: "past quota usage", icon: History, section: "Go to", run: (c) => c.push("/history") },
  { id: "developer", label: "Developer", hint: "API keys", keywords: "api keys tokens settings", icon: Code2, section: "Go to", run: (c) => c.push("/settings/developer") },
  { id: "docs", label: "API docs", keywords: "reference openapi scalar", icon: BookOpen, section: "Go to", run: (c) => c.push("/docs") },
  { id: "label", label: "Parts (Label)", hint: "corpus annotator", keywords: "corpus label internal", icon: Tags, section: "Go to", devOnly: true, run: (c) => c.push("/label") },
  { id: "design-system", label: "Design system", hint: "build proof", keywords: "showcase tokens components", icon: Palette, section: "Go to", devOnly: true, run: (c) => c.push("/design-system") },
  { id: "theme", label: "Toggle theme", hint: "light · dark", keywords: "dark light mode appearance", icon: Moon, section: "Actions", run: (c) => c.toggleTheme() },
  { id: "signout", label: "Sign out", keywords: "logout exit leave", icon: LogOut, section: "Actions", run: (c) => c.signOut() },
];

const PaletteContext = React.createContext<{ open: () => void }>({
  open: () => {},
});

export function useCommandPalette() {
  return React.useContext(PaletteContext);
}

function toggleTheme() {
  const next = !document.documentElement.classList.contains("dark");
  document.documentElement.classList.toggle("dark", next);
  try {
    localStorage.setItem("cv_theme", next ? "dark" : "light");
  } catch {}
}

export function CommandPaletteProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { signOut } = useAuth();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState(0);
  const [showDev, setShowDev] = React.useState(DEV_TOOLS_ENV);
  const listRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => setShowDev(devToolsEnabled()), []);

  // ⌘K / Ctrl-K anywhere summons the palette; Esc is handled by Radix.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openPalette = React.useCallback(() => setOpen(true), []);

  // reset the query + selection each time it opens
  React.useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
    }
  }, [open]);

  const results = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return COMMANDS.filter((c) => (showDev || !c.devOnly)).filter((c) => {
      if (!q) return true;
      return (c.label + " " + (c.hint ?? "") + " " + (c.keywords ?? ""))
        .toLowerCase()
        .includes(q);
    });
  }, [query, showDev]);

  // keep the active index in range as results shrink
  React.useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, results.length - 1)));
  }, [results.length]);

  const ctx = React.useMemo<CommandCtx>(
    () => ({
      push: (href) => router.push(href),
      signOut: () => void signOut(),
      toggleTheme,
    }),
    [router, signOut]
  );

  const run = React.useCallback(
    (cmd: Command) => {
      setOpen(false);
      cmd.run(ctx);
    },
    [ctx]
  );

  const onInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const cmd = results[active];
      if (cmd) run(cmd);
    }
  };

  // scroll the active row into view as the user arrows through
  React.useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active, results]);

  // group results by section, preserving global index for keyboard nav
  const sections = React.useMemo(() => {
    const order: Command["section"][] = ["Go to", "Actions"];
    return order
      .map((s) => ({
        section: s,
        items: results
          .map((c, i) => ({ c, i }))
          .filter(({ c }) => c.section === s),
      }))
      .filter((g) => g.items.length > 0);
  }, [results]);

  const value = React.useMemo(() => ({ open: openPalette }), [openPalette]);

  return (
    <PaletteContext.Provider value={value}>
      {children}
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[80] bg-neutral-950/55 backdrop-blur-[2px]" />
          <Dialog.Content
            onOpenAutoFocus={(e) => {
              // focus the input, not the first item
              e.preventDefault();
              const root = e.currentTarget as HTMLElement | null;
              root?.querySelector<HTMLInputElement>("input")?.focus();
            }}
            className="fixed left-1/2 top-[14vh] z-[81] w-[min(92vw,640px)] -translate-x-1/2 overflow-hidden rounded-[var(--radius-lg)] border border-border-strong bg-card shadow-pop focus:outline-none"
          >
            <Dialog.Title className="sr-only">Command palette</Dialog.Title>
            <Dialog.Description className="sr-only">
              Jump to a destination or run an action. Arrow keys to move, Enter to run, Escape to close.
            </Dialog.Description>

            {/* search input */}
            <div className="flex items-center gap-2.5 border-b border-border px-4">
              <Search className="size-4 shrink-0 text-subtle-foreground" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder="Jump to… Batch, History, Developer, API docs"
                className="w-full bg-transparent py-3.5 text-sm text-foreground placeholder:text-subtle-foreground focus:outline-none"
                autoComplete="off"
                spellCheck={false}
              />
              <kbd className="num hidden shrink-0 rounded-sm border border-border px-1.5 py-0.5 text-[10px] text-subtle-foreground sm:inline">
                esc
              </kbd>
            </div>

            {/* results */}
            <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-2">
              {sections.length === 0 && (
                <p className="px-3 py-8 text-center text-sm text-muted-foreground">
                  No destination matches “{query}”.
                </p>
              )}
              {sections.map((group) => (
                <div key={group.section} className="mb-1">
                  <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">
                    {group.section}
                  </p>
                  {group.items.map(({ c, i }) => {
                    const Icon = c.icon;
                    // Route for this destination, matched by exact segment (so
                    // /cost and /cost-decisions never both read "current").
                    const route = c.id === "developer" ? "/settings/developer" : "/" + c.id;
                    const current =
                      c.section === "Go to" &&
                      (pathname === route || pathname.startsWith(route + "/"));
                    const isActive = i === active;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        data-idx={i}
                        onMouseMove={() => setActive(i)}
                        onClick={() => run(c)}
                        className={[
                          "flex w-full items-center gap-3 rounded-[var(--radius-sm)] px-3 py-2 text-left transition-colors",
                          isActive ? "bg-accent-subtle text-foreground" : "text-muted-foreground",
                        ].join(" ")}
                      >
                        <Icon
                          className={[
                            "size-4 shrink-0",
                            isActive ? "text-primary" : "text-subtle-foreground",
                          ].join(" ")}
                        />
                        <span className="text-sm font-medium text-foreground">{c.label}</span>
                        {c.hint && (
                          <span className="truncate text-xs text-subtle-foreground">
                            {c.hint}
                          </span>
                        )}
                        {current && (
                          <span className="num ml-auto rounded-xs border border-accent-subtle-border bg-accent-subtle px-1.5 py-0.5 text-[10px] text-accent-text">
                            current
                          </span>
                        )}
                        {isActive && !current && (
                          <CornerDownLeft className="ml-auto size-3.5 shrink-0 text-subtle-foreground" />
                        )}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </PaletteContext.Provider>
  );
}
