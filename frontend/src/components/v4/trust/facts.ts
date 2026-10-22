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
 * The public Security, Privacy and Data processing pages render these same
 * sections (it-10), so the pages a reviewer reads before signing up and the
 * page behind sign-in can't drift apart. Facts the code can't see (hosting,
 * region, encryption at rest, backup retention) come only from the deployment's
 * configuration (GET /api/v1/deployment, see hostingSection); unset, they say
 * so instead of guessing.
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
  short: "Only your team can open your parts. Your original file leaves ScaleCAD only in a package or link your team sends with it.",
  rows: [
    { k: "Your organization", v: "Everyone in it can see its parts, checks and records and open a saved part in 3D. Viewers can’t change anything." },
    { k: "Other organizations", v: "No one outside your organization can open your parts in ScaleCAD, or see that they exist." },
    { k: "Downloads", v: "Your original file leaves ScaleCAD only in an RFQ package your team builds with the CAD files included, or a share link made with the CAD file ticked. Your team can also download copies ScaleCAD made, Design Studio files and record exports." },
    { k: "ScaleCAD staff", v: "Platform administrators see account and activity details for every organization: names, emails, file names, check results and network addresses. They can’t open your files or 3D views in ScaleCAD." },
    { k: "Server operators", v: "People who run ScaleCAD’s servers can reach the storage and the database, as with any hosted service." },
  ],
};

/** Share links as the Share dialog makes them (backend share_links.py, supplier_links.py). */
export const SHARE_LINKS: FactSection = {
  id: "share",
  title: "Share links",
  short: "Anyone with a share link can open it without signing in. It ends after 7 days unless you pick another length, and shows your cost only if you include it.",
  link: { label: "Your share links", href: "/app/account/links" },
  rows: [
    { k: "Who sees it", v: "Anyone with the link, without signing in. A check’s link shows the file name, the verdicts, the findings and the measurements. A part’s link, for a supplier, shows the part, its size, material and specs, the quantity and your note. A package’s link shows the package." },
    { k: "Your cost", v: "A part’s link shows your cost estimate only when you turn it on in the Share dialog; a package’s link only when the package was built with it. Links made before that choice existed show no cost." },
    { k: "Never included", v: "Your machines, rates, approvals and notes, the 3D model, who uploaded the file and their email. The CAD file only when you tick it." },
    { k: "How long", v: "A link ends 7 days after it’s made, unless whoever makes it picks 1, 30 or 90 days or a date up to a year ahead. Links made before end dates existed were given one, 30 days after the change." },
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
  ],
};

/** This deployment's own configuration, from GET /api/v1/deployment (null when it couldn't be read). */
export type DeploymentFacts = {
  file_storage: { kind: "local" | "s3"; region: string | null; encryption: "sse-kms" | null; s3_compatible: boolean };
  declared: { hosting: string | null; data_region: string | null; encryption_at_rest: string | null; backup_retention_days: number | null };
};

const NOT_STATED = "Not stated for this deployment. Ask for it in a security review.";

/** Where files and data live, as this deployment's configuration states it. */
export function hostingSection(d: DeploymentFacts | null): FactSection {
  const fs = d?.file_storage;
  const declared = d?.declared;
  const storage = !fs
    ? NOT_STATED
    : fs.kind === "local"
      ? "On the server’s own disk. This deployment has no separate object store."
      : fs.s3_compatible
        ? `An S3-compatible object store${fs.region ? ` (${fs.region})` : ""}.`
        : `Amazon S3${fs.region ? `, region ${fs.region}` : ""}.`;
  const atRest = [
    fs?.encryption === "sse-kms" ? "Every stored file is written encrypted with an AWS KMS key." : null,
    declared?.encryption_at_rest ? `${declared.encryption_at_rest.replace(/[.\s]+$/, "")}.` : null,
  ].filter(Boolean).join(" ");
  const where = [declared?.hosting, declared?.data_region].filter(Boolean).join(", ");
  const days = declared?.backup_retention_days;
  return {
    id: "hosting",
    title: "Hosting",
    rows: [
      { k: "File storage", v: storage },
      { k: "Encryption at rest", v: atRest || NOT_STATED },
      { k: "Hosting and region", v: where ? `${where.replace(/[.\s]+$/, "")}.` : NOT_STATED },
      { k: "Backups", v: days ? `Kept ${days} days by the hosting setup. Deleting in ScaleCAD doesn’t change backups already made.` : "How long backups are kept is set in the hosting setup. " + NOT_STATED },
    ],
  };
}

/** What signing up and signing in collect, and where it goes (it-13). */
export const ACCOUNT: FactSection = {
  id: "account",
  title: "Your account details",
  short: "Name, email and phone go to ScaleCAD’s customer list in Notion, whatever your privacy choices.",
  rows: [
    { k: "At sign-up", v: "Your name, email, password (kept only as a one-way hash), optional phone number and your browser’s timezone." },
    { k: "Phone check", v: "Twilio sends and checks the code; ScaleCAD never stores codes. The verified number stays on your account so one number can’t unlock free checks twice." },
    { k: "Customer list", v: "Your name, email, phone, timezone, sign-in method, sign-up date and last visit go to ScaleCAD’s customer list in Notion for support and follow-up, whatever your privacy choices. Campaign source and approximate location go too only with product analytics on." },
    { k: "Deleting your account", v: "The customer-list entry is blanked, keeping only an account number, and moved to Notion’s trash. Notion’s API can’t delete a page outright; Notion empties its trash after 30 days." },
  ],
};

/** The three separate privacy choices (it-23); each off until turned on. */
export const CHOICES: FactSection = {
  id: "choices",
  title: "Privacy choices",
  short: "Product analytics, session recordings and business visitor identification are three separate choices, all off until you turn one on.",
  rows: [
    { k: "Product analytics", v: "PostHog counts pages and button clicks with all text masked, browser and device type, and errors with their messages removed. It may infer approximate country, region and city from your connection." },
    { k: "Session recordings", v: "PostHog records public website pages with all text and form fields masked. Never inside the app. Needs product analytics." },
    { k: "Business visitor identification", v: "RB2B uses cookies and public website visits to tell ScaleCAD’s sales team which company visited. Never inside the app." },
    { k: "Changing them", v: "Privacy choices at the foot of the website or in the account menu shows what is on and changes it in place. Turning one off stops it at once; RB2B stops with a page reload." },
    { k: "Never asked", v: "Supplier share pages load none of these. Browsers that send Do Not Track get none of them." },
  ],
};

/** Signing in and who may do what (it-05, it-18): what the code enforces today. */
export const ACCESS: FactSection = {
  id: "access",
  title: "Sign-in and access",
  short: "Two-step sign-in with an authenticator app, which an admin can require; roles per organization; scoped API keys.",
  rows: [
    { k: "Sign-in", v: "A password (8 to 128 characters, kept as an Argon2id hash) or a single-use email link. Single sign-on (SAML or OIDC) is set up with ScaleCAD support for your organization." },
    { k: "Two-step sign-in", v: "A code from an authenticator app after a password, email-link or Google sign-in, with ten single-use recovery codes. Five wrong codes in a row pause code entry for 15 minutes. An admin can require it for every member; single sign-on uses the identity provider’s own checks." },
    { k: "Sessions", v: "A signed cookie that lasts 30 days. Changing the password or turning on two-step signs out other browsers, and Security can sign out other browsers or every browser." },
    { k: "Roles", v: "Admin, member or viewer in each organization. Viewers can open parts and records but change nothing." },
    { k: "API keys", v: "Each key belongs to one person and one organization, is read only or read and write, can end after 30, 90 or 365 days, and is kept as a one-way hash. An admin sees every key in the organization and can revoke any of them." },
    { k: "Activity log", v: "Sign-ins, two-step changes, API keys, invitations and role changes, with who and when. Admins read and export 7, 30 or 90 days as CSV." },
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
  { name: "Notion (ScaleCAD’s customer list)", gets: "Name, email, phone, timezone, sign-in method, sign-up date and last visit; campaign source and approximate location only with product analytics on. No files, file names or results", when: "After sign-up, then at most hourly while you use ScaleCAD, whatever your privacy choices. Deleting your account blanks the entry and moves it to Notion’s trash" },
  { name: "Sentry (error reports)", gets: "Error details, with sign-in secrets removed", when: "When something fails" },
  { name: "PostHog (product analytics)", gets: "Page and button activity with all text masked", when: "Only with product analytics on" },
  { name: "PostHog (session recordings)", gets: "Recordings of public website pages, text and form fields masked; never inside the app", when: "Only with session recordings on" },
  { name: "RB2B (business visitors)", gets: "Visits to the public website, to identify business visitors for sales follow-up", when: "Only with business visitor identification on, on public pages" },
];

export const SECTIONS: FactSection[] = [WHERE, WHO, SHARE_LINKS, USE, ACCOUNT, CHOICES, ACCESS, TRANSIT, DELETING];
