"use client";

/**
 * LandingEntry — the flag gate for the app home, kept in a CLIENT component so
 * the three-door surface can be code-split behind `NEXT_PUBLIC_STAGE_UI` exactly
 * like the FE-2 part hero: `LandingRouter` (and everything it pulls — the chooser,
 * the doors, the recent-parts strip) lands in its own lazy chunk that a flag-off
 * build never requests. Flag-off renders today's PartWorkspace directly, so the
 * `/cost` page's initial bundle is byte-identical to before.
 *
 * (`dynamic(..., { ssr:false })` can only live in a client component — hence this
 * thin wrapper rather than gating in the server `page.tsx`.)
 */

import dynamic from "next/dynamic";
import PartWorkspace from "@/components/workspace/PartWorkspace";
import { STAGE_UI } from "@/lib/stage-flag";

const LandingRouter = dynamic(() => import("./LandingRouter"), { ssr: false });

export function LandingEntry() {
  if (STAGE_UI) return <LandingRouter />;
  return <PartWorkspace defaultRole="design" />;
}
