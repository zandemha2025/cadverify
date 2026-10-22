/**
 * What happens to people's CAD files, in plain words. Every line is a fact the
 * code enforces today; the sources are listed in the data-facts write-up
 * (backend: source_artifact_service, part_preview, part_fixes, share_service,
 * admin_routes, part_signature_service, production config). Nothing here is a
 * certification, a retention promise or a claim about provider settings the
 * code can't see.
 *
 * DELETING and SHARE_LINKS describe deleting a part or the organization and
 * share links that end (src/services/data_deletion_service.py,
 * src/services/share_links.py); the page and the tests read them from here.
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
  short: "Anyone with a share link can see the file name and findings. A link ends after 30 days unless you pick longer.",
  link: { label: "Your share links", href: "/app/account/links" },
  rows: [
    { k: "Who sees it", v: "Anyone with the link, without signing in, can see the file name, the verdicts, the findings and the measurements." },
    { k: "Never included", v: "The file, the 3D model, who uploaded it and their email." },
    { k: "How long", v: "A link ends 30 days after it’s made, unless whoever makes it picks 90 days, a year or no end date. Links made before end dates existed were given one, 30 days after the change." },
    { k: "Switching off", v: "The person who made a link, or an admin, can switch it off at any time in Share links. It stops working at once; anyone who opens it then sees only that it ended or was switched off." },
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

/** Deleting a part, the organization (data control, 2026-10-21) or your account (2026-10-22). */
export const DELETING: FactSection = {
  id: "delete",
  title: "Keeping and deleting",
  short: "Kept until you delete it. A member can delete a part; an admin can delete the whole organization; anyone can delete their own account.",
  link: { label: "Privacy requests", href: "/privacy#retention" },
  rows: [
    { k: "How long", v: "Saved files, checks and records are kept until someone deletes them. Nothing expires them." },
    { k: "Deleting a part", v: "From the part or the Parts list. It removes the stored file, its checks, cost records and PDFs, its program and volume, actual costs logged against that file, and the copies ScaleCAD fixed from it unless you keep them. Share links to it stop working. Members delete parts only they checked; admins delete any part. It can’t be undone." },
    { k: "Deleting the organization", v: "An admin can delete the organization in Account: every part, file, record and setting, for every member. Members are signed out. Accounts, plans and billing records stay." },
    { k: "What stays", v: "A record that a file with a given fingerprint was deleted, by whom and when, without its name or results; audit events with their details removed (after an organization is deleted, also without who did them or from where: no email, network address or browser); usage counts, without the files’ fingerprints; and each account’s free-check count." },
    { k: "Backups", v: "Deleting removes the data from ScaleCAD at once. Backups and the storage provider’s earlier versions of files aren’t changed by it; how long those are kept is set in the hosting setup." },
    { k: "Your account", v: "You can delete your sign-in account in Account, Security. Organizations only you are in are deleted with it; you leave the others, and what you made there stays with them. Not while you’re the only admin of an organization others are in. A Pro plan is cancelled at once. It can’t be undone." },
    { k: "After an account is deleted", v: "ScaleCAD keeps the billing records the law requires (the payment processor’s customer reference and invoices), a record that the account was deleted, and a one-way fingerprint of its email with the number of free checks used, so free checks aren’t issued twice. The email can’t be read back from the fingerprint. Audit events lose the person’s email, network address and browser." },
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
