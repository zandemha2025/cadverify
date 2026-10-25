/**
 * Every v4 route in one place, so screens, the search palette, keyboard
 * shortcuts and the control-inventory check agree on where things live.
 */
export const R = {
  home: "/app",
  setup: "/app/setup",
  check: "/app/check",
  phone: "/app/phone",
  notices: "/app/notices",
  part: (key: string) => `/app/part/${encodeURIComponent(key)}`,
  partHistory: (key: string) => `/app/part/${encodeURIComponent(key)}/history`,
  /** The part's cost breakdown (it used to be /app/make/workbench?part=…, which redirects here). */
  cost: (key: string) => `/app/part/${encodeURIComponent(key)}/cost`,
  parts: "/app/parts",
  records: "/app/parts/records",
  record: (id: string) => `/app/parts/records/${encodeURIComponent(id)}`,
  analyses: "/app/parts/analyses",
  analysis: (id: string) => `/app/parts/analyses/${encodeURIComponent(id)}`,
  compare: "/app/parts/compare",
  packages: "/app/parts/packages",
  pkg: (id: string) => `/app/parts/packages/${encodeURIComponent(id)}`,
  programs: "/app/parts/programs",
  many: "/app/many",
  batch: (id: string) => `/app/many/${encodeURIComponent(id)}`,
  triage: "/app/many/triage",
  imports: "/app/many/imports",
  bom: "/app/many/bom",
  studio: "/app/make",
  fit: "/app/make/fit",
  photo: "/app/make/photo",
  shop: "/app/shop",
  rates: "/app/shop/rates",
  actuals: "/app/shop/actuals",
  changes: "/app/shop/changes",
  org: "/app/account",
  sso: "/app/account/sso",
  security: "/app/account/security",
  api: "/app/account/api",
  billing: "/app/account/billing",
  notifications: "/app/account/notifications",
  activity: "/app/account/activity",
  data: "/app/account/data",
  links: "/app/account/links",
} as const;

export type NavSection = "home" | "parts" | "many" | "make" | "shop" | "account";

/**
 * Top-bar sections, in the order of the ops owner's job: your parts, which of
 * them to make on your own machines (make or buy across parts, with batches and
 * imports beside it), your shop, then the design tools. `pilot` marks a
 * pilot-plan section (shown, labelled, gated on use); none is labelled today.
 */
export const NAV: { key: NavSection; label: string; href: string; pilot?: boolean }[] = [
  { key: "home", label: "Home", href: R.home },
  { key: "parts", label: "Parts", href: R.parts },
  { key: "many", label: "Make or buy", href: R.triage },
  { key: "shop", label: "Your shop", href: R.shop },
  { key: "make", label: "Design tools", href: R.studio },
];

/** Sibling tabs per section (the `.subnav` row under a page title). */
export const TABS: Record<Exclude<NavSection, "home">, { label: string; href: string }[]> = {
  parts: [
    { label: "Parts", href: R.parts },
    { label: "Cost records", href: R.records },
    { label: "DFM checks", href: R.analyses },
    { label: "Compare", href: R.compare },
    { label: "RFQ packages", href: R.packages },
    { label: "Programs", href: R.programs },
  ],
  many: [
    { label: "Batches", href: R.many },
    { label: "Make or buy", href: R.triage },
    { label: "Imports", href: R.imports },
  ],
  make: [
    { label: "Design Studio", href: R.studio },
    { label: "Fit in assembly", href: R.fit },
    { label: "Photo to 3D", href: R.photo },
  ],
  shop: [
    { label: "Machines and printers", href: R.shop },
    { label: "Rates", href: R.rates },
    { label: "Actual costs", href: R.actuals },
    { label: "Changes to review", href: R.changes },
  ],
  account: [
    { label: "Organization", href: R.org },
    { label: "Single sign-on", href: R.sso },
    { label: "Security", href: R.security },
    { label: "API and keys", href: R.api },
    { label: "Plan and billing", href: R.billing },
    { label: "Notifications", href: R.notifications },
    { label: "Activity", href: R.activity },
    { label: "Share links", href: R.links },
    { label: "Files and data", href: R.data },
  ],
};

/** Which top-bar section a pathname belongs to. A part's cost breakdown belongs with the part, under Parts. */
export function sectionOf(pathname: string): NavSection {
  if (pathname.startsWith("/app/parts") || pathname.startsWith("/app/part/") || pathname.startsWith("/app/check")) return "parts";
  if (pathname.startsWith("/app/many")) return "many";
  if (pathname.startsWith("/app/make")) return "make";
  if (pathname.startsWith("/app/shop")) return "shop";
  if (pathname.startsWith("/app/account")) return "account";
  return "home";
}

/** Single-letter go-to keys (X8). They fire outside text fields and dialogs, never with a modifier held. */
export const GO_KEYS: Record<string, string> = {
  h: R.home,
  p: R.parts,
  r: R.records,
  g: R.programs,
  m: R.shop,
  t: R.triage,
  c: R.rates,
  f: R.fit,
};
