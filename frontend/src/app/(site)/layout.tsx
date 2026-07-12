import type { Metadata } from "next";
import "./site-theater.css";

/**
 * The dark-theater marketing shell (route group `(site)`).
 *
 * This is a NESTED layout — it renders no <html>/<body> (the root layout owns
 * those). It only:
 *  1. imports the scoped `site-theater.css`, whose every rule is under
 *     `.site-theater` (the product's light-instrument tokens are untouched by
 *     construction — there is no bare :root/body selector in that file), and
 *  2. wraps the subtree in `.site-theater`, switching the register to
 *     near-black #050506 / Helvetica Neue light / mono evidence.
 *
 * Pages under this group compose the shared chrome from `@/components/site`
 * (SiteNav / SiteFooter / SiteShell). At cutover the 12 site routes move under
 * this group (see frontend/SITE-ROUTE-PLAN.md); the light-instrument product
 * routes — (app), (verify), (auth), /docs, /scalar — stay outside it and never
 * render `.site-theater`.
 */

export const metadata: Metadata = {
  title: "ProofShape — verification, made of glass",
  description:
    "Makeability verification: can this part be made — on your machines, in materials that survive its world — and what will it really take? Should-cost is one artifact inside the verdict, never the destination.",
};

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="site-theater" style={{ flex: "1 1 auto", display: "flex", flexDirection: "column" }}>
      {children}
    </div>
  );
}
