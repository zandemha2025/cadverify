"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { TopStrip } from "@/components/ui/top-strip";
import { CommandPaletteProvider } from "@/components/ui/command-palette";
import { InstrumentChromeProvider } from "@/components/instrument/instrument-chrome";

/**
 * The instrument shell. The fat left admin sidebar (Analyze/Cost/Batch/History/
 * Developer) and its breadcrumb topbar are GONE. What's left is deliberately
 * minimal:
 *
 *   • a slim top strip (wordmark + the loaded part's identity + account), and
 *   • a ⌘K command palette for every secondary destination.
 *
 * The core routes (/cost, /analyze) render FULL-BLEED — the whole surface is the
 * instrument, no padded content panel. Secondary "document" routes (Batch,
 * History, Developer, docs) keep a comfortable reading container so they work
 * unchanged without a redesign this round.
 */
const FULL_BLEED = new Set(["/analyze", "/cost"]);

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const fullBleed = FULL_BLEED.has(pathname);

  return (
    <InstrumentChromeProvider>
      <CommandPaletteProvider>
        <div className="flex h-screen flex-col overflow-hidden bg-canvas">
          <TopStrip />
          <main className="min-h-0 flex-1 overflow-y-auto">
            {fullBleed ? (
              <div className="h-full">{children}</div>
            ) : (
              <div className="mx-auto w-full max-w-screen-2xl px-6 py-8 lg:px-8">
                {children}
              </div>
            )}
          </main>
        </div>
      </CommandPaletteProvider>
    </InstrumentChromeProvider>
  );
}
