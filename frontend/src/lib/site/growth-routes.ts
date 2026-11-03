/** Explicit public paths: never include user-created slugs or customer data. */
export const GROWTH_ROUTES = [
  "/resources",
  "/solutions/dfm-software",
  "/guides/step-file-manufacturability-check",
  "/guides/cnc-dfm-checklist",
  "/guides/make-vs-buy-analysis",
  "/compare/scalecad-vs-apriori",
  "/tools/make-vs-buy-calculator",
] as const;

export const SITE_ORIGIN = (process.env.NEXT_PUBLIC_SITE_URL || "https://scalecad.ai").replace(/\/+$/, "");
