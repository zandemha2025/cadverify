/**
 * What happens to people's CAD files, in plain words. Every line is a fact the
 * code enforces today; the sources are listed in the data-facts write-up
 * (backend: source_artifact_service, part_preview, part_fixes, share_service,
 * admin_routes, part_signature_service, production config). Nothing here is a
 * certification, a retention promise or a claim about provider settings the
 * code can't see.
 *
 * DELETING and SHARE_LINKS hold the two answers that are about to change
 * (deleting a part or all of an organization's data, and share links that
 * expire). Edit them in place when that lands; the page and the tests read
 * them from here.
 *
 * Pure: no React, no fetch (runs under node --test).
 */

export type Fact = { k: string; v: string };
/** `short`: the section in one line, for the page's "In short" summary. */
export type FactSection = { id: string; title: string; short?: string; note?: string; link?: { label: string; href: string }; rows: Fact[] };

/** The line shown where a file is picked or dropped. */
export const UPLOAD_LINE = "Your file stays in your organization. Only your team can open it, and ScaleCAD doesn’t use it to train anything.";

/** The page's title, meta facts and where it lives. */
export const DATA_PAGE = {
  title: "Your files and data",
  meta: ["Kept per organization", "Originals can’t be downloaded back out", "Not used for training"],
} as const;

export const WHERE: FactSection = {
  id: "where",
  title: "Where your files are kept",
  short: "A file you check is saved to your organization; your file itself is never changed.",
  rows: [
    { k: "Your file", v: "When a check finishes, the exact file is saved to your organization’s storage, with a copy in millimetres for costing. A check that fails keeps nothing." },
    { k: "Not kept", v: "The 3D preview before a check, both files in Fit in assembly, and the 3D view of a saved part are made in memory and not saved." },
    { k: "Copies ScaleCAD makes", v: "A fix or a mesh repair saves a copy as a new part, linked to your file. Your file is never changed." },
    { k: "Results", v: "Checks, costs and records are saved in ScaleCAD’s database under your organization." },
  ],
};

export const WHO: FactSection = {
  id: "who",
  title: "Who can see them",
  short: "Only your team can open your parts. Nobody can download your original back out.",
  rows: [
    { k: "Your organization", v: "Everyone in it can see its parts, checks and records and open a saved part in 3D. Viewers can’t change anything." },
    { k: "Other organizations", v: "No one outside your organization can open your parts in ScaleCAD, or see that they exist." },
    { k: "Downloads", v: "No one can download your original file back out of ScaleCAD. Your team can download copies ScaleCAD made, Design Studio files and record exports." },
    { k: "ScaleCAD staff", v: "Platform administrators see account and activity details for every organization: names, emails, file names, check results and network addresses. They can’t open your files or 3D views in ScaleCAD." },
    { k: "Server operators", v: "People who run ScaleCAD’s servers can reach the storage and the database, as with any hosted service." },
  ],
};

/** Share links today: public, no sign-in, no expiry. Replace when expiring links land. */
export const SHARE_LINKS: FactSection = {
  id: "share",
  title: "Share links",
  short: "Anyone with a share link can see the file name and findings. Links don’t expire today.",
  rows: [
    { k: "Who sees it", v: "Anyone with the link, without signing in, can see the file name, the verdicts, the findings and the measurements." },
    { k: "Never included", v: "The file, the 3D model, who uploaded it and their email." },
    { k: "How long", v: "Links don’t expire today. A link stays on until someone in your team turns it off; it stops working at once." },
  ],
};

export const USE: FactSection = {
  id: "use",
  title: "How your files are used",
  short: "Not used to train anything, and never compared with other organizations’ parts.",
  rows: [
    { k: "Purpose", v: "To check, cost and fix your parts and show them to your team." },
    { k: "Training", v: "Your files aren’t used to train any model and aren’t added to any shared collection. ScaleCAD’s test parts come from public, openly licensed collections." },
    { k: "Similar parts", v: "ScaleCAD keeps 18 shape measurements of each part to suggest similar parts from your own organization. They’re never compared with another organization’s parts." },
    { k: "AI services", v: "No AI service sees your CAD files. Design Studio reads your description with fixed rules on ScaleCAD’s servers." },
  ],
};

export const TRANSIT: FactSection = {
  id: "transit",
  title: "Connections",
  rows: [
    { k: "In transit", v: "HTTPS only. The servers won’t start unless their database and cache connections are encrypted too." },
    { k: "At rest", v: "Depends on the storage provider’s settings for your deployment. Ask for the details in a security review." },
  ],
};

/** Deleting today: not in the product. Replace when part and organization deletion land. */
export const DELETING: FactSection = {
  id: "delete",
  title: "Keeping and deleting",
  short: "Kept until deleted. Deleting isn’t in ScaleCAD yet; send a privacy request.",
  link: { label: "Privacy requests", href: "/privacy#retention" },
  rows: [
    { k: "How long", v: "Saved files, checks and records are kept. Nothing expires them." },
    { k: "Deleting", v: "Deleting a part, its file or an account isn’t in ScaleCAD yet. To ask for deletion, send a privacy request." },
    { k: "People leaving", v: "Removing someone from your organization ends their access. The organization keeps its parts." },
    { k: "Taking data out", v: "Cost records export as JSON, CSV or PDF." },
  ],
};

export type Service = { name: string; gets: string; when: string };

/** Every outside service the code sends data to, and what it gets. */
export const SERVICES: Service[] = [
  { name: "Cloud storage and database hosting", gets: "Your files, results and account", when: "Always" },
  { name: "Resend (email)", gets: "Your email address, for sign-in links, password resets and invites", when: "When an email is sent" },
  { name: "Twilio (text messages)", gets: "Your phone number", when: "When a code is sent to it" },
  { name: "Stripe (payments)", gets: "Billing details; card numbers go to Stripe only", when: "If you buy Pro" },
  { name: "Cloudflare Turnstile", gets: "A browser check", when: "At sign-up and sign-in" },
  { name: "Notion (ScaleCAD’s customer list)", gets: "Name, email, phone, timezone, campaign source and location if given. No files, file names or results", when: "After sign-up" },
  { name: "Sentry (error reports)", gets: "Error details, with sign-in secrets removed", when: "When something fails" },
  { name: "PostHog (product analytics)", gets: "Page and button activity with text masked; nothing inside the app is recorded on screen", when: "Only if you allow analytics" },
  { name: "RB2B (business visitors)", gets: "Visits to the public website, to identify business visitors", when: "Only if you allow analytics, on public pages" },
];

export const SECTIONS: FactSection[] = [WHERE, WHO, SHARE_LINKS, USE, TRANSIT, DELETING];
