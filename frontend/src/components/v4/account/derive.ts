/**
 * Account derivations (boards A1–A7): role wording and who may change what,
 * plan facts, the audit log's plain-English lines, notification groups and
 * their v4 destinations, service-health rows. Pure and import-light so it
 * unit-tests under `node --test`.
 *
 * Honesty: nothing here invents a number. A count that didn't load is null and
 * reads "Not measured yet" or "—", never 0.
 */
import { R } from "../routes.ts";

export type OrgRole = "viewer" | "member" | "admin";
export const ORG_ROLES: OrgRole[] = ["viewer", "member", "admin"];
const RANK: Record<OrgRole, number> = { viewer: 1, member: 2, admin: 3 };

/** Platform ("workspace") roles a superadmin can assign. superadmin is provisioned out of band. */
export const WORKSPACE_ROLES = ["viewer", "analyst", "admin"] as const;

export function roleName(role: string | null | undefined): string {
  if (!role) return "—";
  return role[0].toUpperCase() + role.slice(1);
}

export const ORG_ROLE_DOES: Record<OrgRole, string> = {
  viewer: "Views parts, records, rates.",
  member: "Checks parts, saves decisions, proposes rate changes.",
  admin: "Members, invites, sign-on, rates, approvals.",
};

/** What a viewer loses or gains when their org role changes, for the confirm. */
export function orgRoleChange(
  target: { email: string; role: OrgRole; self: boolean },
  next: OrgRole,
  orgName: string,
): { question: string; detail: string; demotesSelf: boolean } {
  const who = target.self ? "your" : `${target.email}’s`;
  const question = `Change ${who} org role in ${orgName} to ${roleName(next)}?`;
  const down = RANK[next] < RANK[target.role];
  const demotesSelf = target.self && down;
  let detail: string;
  if (demotesSelf && target.role === "admin") {
    detail = "You can’t manage members, invites, sign-on or approvals after this. Another admin has to change it back.";
  } else if (demotesSelf) {
    detail = "Viewers can’t check parts or save decisions. An admin has to change it back.";
  } else if (next === "admin") {
    detail = `${target.self ? "You" : "They"} can manage members, invites, sign-on, rates and approvals.`;
  } else if (next === "viewer") {
    detail = `${target.self ? "You" : "They"} can view parts, records and rates, but can’t check parts or save decisions.`;
  } else {
    detail = `${target.self ? "You" : "They"} can check parts, save decisions and propose rate changes.`;
  }
  return { question, detail, demotesSelf };
}

/** The last admin can't be demoted (the backend refuses with 409); show the role as fixed instead. */
export function orgRoleLocked(target: { role: OrgRole }, adminCount: number): boolean {
  return target.role === "admin" && adminCount <= 1;
}

export function workspaceRoleChange(target: { email: string }, next: string): { question: string; detail: string } {
  const detail =
    next === "viewer"
      ? "Viewers can’t check parts or save decisions, in every organization they belong to."
      : next === "admin"
        ? "Workspace admins can change rates and approvals, in every organization they belong to."
        : "Analysts can check parts and save decisions, in every organization they belong to.";
  return { question: `Change ${target.email}’s workspace role to ${roleName(next)}?`, detail };
}

export function inviteChip(status: string): { tone: "ok" | "warn" | "bad" | "unk"; label: string } {
  if (status === "pending") return { tone: "warn", label: "Pending" };
  if (status === "accepted") return { tone: "ok", label: "Accepted" };
  if (status === "revoked") return { tone: "unk", label: "Revoked" };
  if (status === "expired") return { tone: "unk", label: "Expired" };
  return { tone: "unk", label: roleName(status) };
}

/** "designdata.17@acme-aero.com" → "DE"; "austin.lee@x" → "AL". */
export function initials(email: string): string {
  const name = email.split("@")[0] ?? "";
  const parts = name.split(/[._-]+/).filter(Boolean);
  const two = parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return two.toUpperCase() || "?";
}

export function domainOf(email: string): string {
  const at = email.lastIndexOf("@");
  return at >= 0 ? email.slice(at + 1) : "";
}

// ── dates (UTC, the boards' convention) ────────────────────────────────────
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  // Some rows come as Postgres text ("2026-10-18 05:00:00.12+00:00"); make them ISO.
  const t = Date.parse(/^\d{4}-\d{2}-\d{2} /.test(iso) ? iso.replace(" ", "T") : iso);
  return Number.isFinite(t) ? new Date(t) : null;
}
const p2 = (n: number) => String(n).padStart(2, "0");

/** "Oct 18, 2026"; "—" when missing. */
export function dateLabel(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? `${MON[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}` : "—";
}
/** "Oct 18". */
export function dayLabel(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? `${MON[d.getUTCMonth()]} ${d.getUTCDate()}` : "—";
}
/** "05:00" (UTC). */
export function timeLabel(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? `${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}` : "—";
}
/** "05:00" when the same UTC day as `now`, else "Oct 18 05:00". */
export function whenLabel(iso: string | null | undefined, now: Date = new Date()): string {
  const d = parse(iso);
  if (!d) return "—";
  const same = d.getUTCFullYear() === now.getUTCFullYear() && d.getUTCMonth() === now.getUTCMonth() && d.getUTCDate() === now.getUTCDate();
  return same ? timeLabel(iso) : `${dayLabel(iso)} ${timeLabel(iso)}`;
}

// ── plan ───────────────────────────────────────────────────────────────────
export type Usage = { plan: string; tier?: string; unlimited: boolean; used: number | null; cap: number | null; remaining: number | null };

export function planName(usage: Usage | null | undefined, billingPlan?: string | null): string | null {
  const plan = billingPlan ?? usage?.plan ?? null;
  if (plan === "pro") return "Pro";
  if (plan === "pilot") return "Pilot";
  if (usage?.unlimited) return "Pilot";
  if (plan) return "Free trial";
  return null;
}

/** The allowance strip line (A4): never a number that didn't load. */
export function allowanceLine(usage: Usage | null, loaded: boolean): string {
  if (!usage) return loaded ? "Allowance temporarily unavailable." : "Checking your allowance…";
  if (usage.unlimited) return "Pilot plan: checks aren’t counted.";
  if (usage.remaining == null || usage.cap == null) return "Allowance temporarily unavailable.";
  return usage.plan === "pro"
    ? `${usage.remaining} of ${usage.cap} Pro checks left this month`
    : `${usage.remaining} of ${usage.cap} free checks left`;
}

export type ProPrice = { unit_amount: number; currency: string; interval: string };

/** "$149" + "a month" from Stripe's price; null when the billing API didn't give one. */
export function proPrice(price: ProPrice | null | undefined): { amount: string; per: string } | null {
  if (!price || !Number.isFinite(price.unit_amount) || price.unit_amount < 0 || !price.currency) return null;
  let amount: string;
  try {
    amount = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: price.currency.toUpperCase(),
      minimumFractionDigits: price.unit_amount % 100 === 0 ? 0 : 2,
    }).format(price.unit_amount / 100);
  } catch {
    return null;
  }
  const per = price.interval === "year" ? "a year" : price.interval === "month" ? "a month" : `per ${price.interval}`;
  return { amount, per };
}

// ── audit log ──────────────────────────────────────────────────────────────
const ACTION: Record<string, string> = {
  "auth.signup": "Signed up",
  "auth.login": "Signed in",
  "auth.logout": "Signed out",
  "auth.password_changed": "Password changed",
  "auth.password_set": "Password set",
  "analysis.created": "Part checked",
  "decision.created": "Decision saved",
  "decision.approved": "Decision approved",
  "decision.rejected": "Decision rejected",
  "machine.created": "Machine added",
  "machine.updated": "Machine edited",
  "machine.deleted": "Machine deleted",
  "share.created": "Link shared",
  "share.revoked": "Shared link turned off",
  "batch.submitted": "Batch started",
  "batch.cancelled": "Batch cancelled",
  "api_key.created": "API key created",
  "api_key.revoked": "API key revoked",
  "api_key.renamed": "API key renamed",
  "org.created": "Organization created",
  "org.switched": "Organization switched",
  "org.renamed": "Organization renamed",
  "member.invited": "Member invited",
  "member.joined": "Member joined",
  "member.role_changed": "Org role changed",
  "member.removed": "Member removed",
  "member.left": "Member left",
  "user.role_changed": "Workspace role changed",
  "saml.group_mapping.created": "Group mapping added",
  "saml.group_mapping.deleted": "Group mapping deleted",
  "rate_card.published": "Rates published",
  "change_request.approved": "Change approved",
  "change_request.rejected": "Change rejected",
};

export function actionName(action: string): string {
  const known = ACTION[action];
  if (known) return known;
  const words = action.replace(/[._]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : action;
}

const WAY: Record<string, string> = {
  fdm: "filament printing",
  sla: "resin printing",
  dlp: "resin printing",
  sls: "nylon powder printing",
  mjf: "Multi Jet Fusion",
  binder_jetting: "binder jetting",
  dmls: "metal powder printing",
  slm: "metal powder printing",
  ebm: "electron beam melting",
  ded: "metal deposition",
  waam: "wire arc deposition",
  cnc_3axis: "3-axis milling",
  cnc_5axis: "5-axis milling",
  cnc_turning: "lathe",
  wire_edm: "wire EDM",
  investment_casting: "investment casting",
  sand_casting: "sand casting",
  die_casting: "die casting",
  injection_molding: "injection molding",
  forging: "forging",
  sheet_metal: "sheet metal",
};
export function wayWord(process: string): string {
  return WAY[process] ?? process.replace(/[_-]+/g, " ");
}

type AuditLike = { action: string; resource_type: string | null; resource_id: string | null; detail: Record<string, unknown> | null; result_summary: string | null };

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

/** The "What" column: the file, key or member it touched, then the outcome. */
export function auditWhat(e: AuditLike): string {
  const d = e.detail ?? {};
  const file = str(d.filename) ?? str(d.file_name);
  const parts: string[] = [];
  if (file) parts.push(file);
  const way = str(d.make_now_process);
  if (way) parts.push(`make now: ${wayWord(way)}`);
  const email = str(d.email);
  if (email) parts.push(email);
  const role = str(d.new_role) ?? str(d.role) ?? str(d.org_role);
  if (role && e.action !== "decision.created") parts.push(roleName(role));
  const name = str(d.name);
  if (name) parts.push(name);
  const prefix = str(d.key_prefix);
  if (prefix) parts.push(`cv_live_${prefix}_…`);
  if (str(d.reason) === "rotation") parts.push("rotated");
  const group = str(d.group_value);
  if (group) parts.push(group);
  if (e.result_summary && !parts.length) parts.push(e.result_summary);
  else if (e.result_summary && e.action === "analysis.created") parts.push(e.result_summary === "issues" ? "has findings" : e.result_summary);
  if (!parts.length && e.resource_type) parts.push(`${e.resource_type.replace(/_/g, " ")}${e.resource_id ? ` ${e.resource_id.slice(0, 10)}` : ""}`);
  return parts.join(" · ") || "—";
}

// ── notifications ──────────────────────────────────────────────────────────
export type NotificationRow = {
  id: string;
  kind?: string;
  severity: string;
  title: string;
  body: string;
  dest: string;
  source_type?: string;
  source_id?: string;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
  is_read: boolean;
  read_at: string | null;
  is_dismissed: boolean;
  dismissed_at: string | null;
};

const ULID = /^[0-7][0-9A-HJKMNP-TV-Z]{25}$/;

/** Where a notification opens in v4. */
export function notificationHref(row: Pick<NotificationRow, "dest" | "source_type" | "source_id">): string {
  if (row.source_type === "cost_decision" && ULID.test(row.source_id ?? "")) return R.record(row.source_id as string);
  if (row.source_type === "change_request" || row.dest === "calibration") return R.changes;
  if (row.dest === "records") return R.records;
  return R.parts;
}

export function kindName(row: Pick<NotificationRow, "kind" | "title">): string {
  if (row.kind === "decision.created") return "Check recorded";
  if (row.kind === "governance.change_requested") return "Change needs review";
  const t = row.title.replace(/\s+-\s+.*$/, "").trim();
  return t || "Notification";
}

/** The part a notification is about (its file), or null for org-wide ones. */
export function partOf(row: Pick<NotificationRow, "metadata" | "title" | "kind">): string | null {
  const f = row.metadata && typeof row.metadata.filename === "string" ? row.metadata.filename.trim() : "";
  if (f) return f;
  if (row.kind === "decision.created") {
    const m = /\s-\s(.+)$/.exec(row.title);
    if (m) return m[1].trim();
  }
  return null;
}

export type NotificationGroup = { key: string; file: string; kind: string; items: NotificationRow[]; unread: number; latest: string | null; isPart: boolean };

/** Group by part (newest group first); org-wide notifications group by kind. */
export function groupNotifications(rows: NotificationRow[]): NotificationGroup[] {
  const map = new Map<string, NotificationGroup>();
  for (const r of rows) {
    const file = partOf(r);
    const key = file ? `part:${file}` : `kind:${kindName(r)}`;
    let g = map.get(key);
    if (!g) {
      g = { key, file: file ?? kindName(r), kind: kindName(r), items: [], unread: 0, latest: null, isPart: !!file };
      map.set(key, g);
    }
    g.items.push(r);
    if (!r.is_read) g.unread += 1;
    const t = r.created_at ?? null;
    if (t && (!g.latest || t > g.latest)) g.latest = t;
  }
  const out = [...map.values()];
  for (const g of out) g.items.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  return out.sort((a, b) => (b.latest ?? "").localeCompare(a.latest ?? ""));
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}

// ── usage and health ───────────────────────────────────────────────────────
const EVENT: Record<string, [string, string]> = {
  analysis_complete: ["check completed", "checks completed"],
  analysis_cached: ["served from cache", "served from cache"],
};

const EVENT_ORDER = ["analysis_complete", "analysis_cached"];

/** "Usage events: 12 checks completed, 9 served from cache." from the event counts. */
export function usageEventsLine(counts: Record<string, number> | null | undefined): string | null {
  if (!counts) return null;
  const parts = Object.entries(counts)
    .filter(([, n]) => typeof n === "number" && n > 0)
    .sort((a, b) => (EVENT_ORDER.indexOf(a[0]) + 1 || 99) - (EVENT_ORDER.indexOf(b[0]) + 1 || 99) || b[1] - a[1])
    .map(([k, n]) => {
      const w = EVENT[k];
      return w ? `${n} ${n === 1 ? w[0] : w[1]}` : `${n} ${k.replace(/_/g, " ")}`;
    });
  return parts.length ? `Usage events: ${parts.join(", ")}.` : null;
}

export type HealthChecks = {
  postgres?: { ok: boolean; error: string | null };
  redis?: { ok: boolean; expected: boolean; configured: boolean; error: string | null };
  worker?: { state: string; heartbeat_age_seconds: number | null; stale_threshold_seconds: number; strict?: boolean };
  queue?: { depth: number | null; name: string };
  object_store?: { ok: boolean; expected: boolean; backend?: string; error: string | null };
};
export type Tone = "ok" | "warn" | "bad" | "unk";
export type HealthRow = { name: string; chip?: { tone: Tone; label: string }; value?: string; note: string };

export function healthRows(c: HealthChecks): HealthRow[] {
  const rows: HealthRow[] = [];
  const pg = c.postgres;
  rows.push({ name: "Database", chip: pg ? (pg.ok ? { tone: "ok", label: "Healthy" } : { tone: "bad", label: "Unhealthy" }) : { tone: "unk", label: "Unknown" }, note: pg?.error ? `Postgres · ${pg.error}` : "Postgres" });
  const rd = c.redis;
  rows.push({
    name: "Cache and queue",
    chip: !rd ? { tone: "unk", label: "Unknown" } : rd.ok ? { tone: "ok", label: "Healthy" } : rd.configured ? { tone: "bad", label: "Unhealthy" } : { tone: "unk", label: "Not set up" },
    note: rd?.error ? `Redis · ${rd.error}` : rd && !rd.expected && !rd.configured ? "Redis isn’t used on this deployment" : "Redis",
  });
  const wk = c.worker;
  const age = wk?.heartbeat_age_seconds;
  rows.push({
    name: "Background worker",
    chip: !wk ? { tone: "unk", label: "Unknown" } : wk.state === "ok" ? { tone: "ok", label: "Healthy" } : wk.state === "stale" ? { tone: "warn", label: "Stale" } : wk.state === "unknown" ? { tone: "unk", label: "Unknown" } : { tone: "bad", label: roleName(wk.state) },
    note: !wk ? "Not reported" : age != null ? `Last heartbeat ${age} s ago. Stale after ${wk.stale_threshold_seconds} s.` : `No heartbeat yet. Stale after ${wk.stale_threshold_seconds} s.`,
  });
  rows.push({ name: "Queue depth", value: c.queue?.depth != null ? String(c.queue.depth) : "Not measured yet", note: c.queue?.name ?? "—" });
  const os = c.object_store;
  if (os) {
    rows.push({
      name: "File storage",
      chip: os.ok ? { tone: "ok", label: "Healthy" } : os.expected ? { tone: "bad", label: "Unhealthy" } : { tone: "unk", label: os.backend === "local" ? "Local disk" : "Not set up" },
      note: os.error ? os.error : os.ok ? "Object store" : os.expected ? "Object store unreachable" : "No object store on this deployment",
    });
  }
  return rows;
}

export function workerFig(c: HealthChecks): { v: string; sub: string } {
  const wk = c.worker;
  if (!wk) return { v: "Unknown", sub: "not reported" };
  if (wk.state === "ok") return { v: "Healthy", sub: wk.heartbeat_age_seconds != null ? `${wk.heartbeat_age_seconds} s ago` : "heartbeat" };
  if (wk.state === "stale") return { v: "Stale", sub: "late heartbeat" };
  return { v: roleName(wk.state), sub: wk.heartbeat_age_seconds == null ? "no heartbeat" : `${wk.heartbeat_age_seconds} s ago` };
}

// ── sign-in modes (A2, A1 sheet, A6 sheet) ─────────────────────────────────
export type SignIn = { mode: string; passwordOn: boolean; linkOn: boolean; ssoOn: boolean; ssoOnly: boolean };

export function signIn(authMode: string, magicLink: boolean): SignIn {
  const m = (authMode || "password").trim().toLowerCase();
  const passwordOn = m === "password" || m === "hybrid";
  const ssoOn = m === "saml" || m === "oidc" || m === "hybrid";
  const ssoOnly = ssoOn && !passwordOn;
  const linkOn = magicLink && !ssoOnly;
  const mode = ssoOnly
    ? "Single sign-on"
    : [passwordOn ? "Password" : null, linkOn ? "email link" : null, ssoOn ? "single sign-on" : null].filter(Boolean).join(" or ").replace(/^./, (c) => c.toUpperCase());
  return { mode, passwordOn, linkOn, ssoOn, ssoOnly };
}

/** New-password rule shared with the server: 8 to 128 characters (code points). */
export function passwordProblem(next: string, confirm: string): string | null {
  const n = [...next].length;
  if (n < 8 || n > 128) return "Use 8 to 128 characters.";
  if (next !== confirm) return "Passwords don’t match.";
  return null;
}
