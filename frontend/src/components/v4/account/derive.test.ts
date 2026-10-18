/**
 * Account derivations: role wording and locks, plan facts, audit lines,
 * notification groups and destinations, health rows, sign-in modes.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/account/derive.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  allowanceLine,
  actionName,
  auditWhat,
  dateLabel,
  groupNotifications,
  healthRows,
  initials,
  inviteChip,
  kindName,
  notificationHref,
  orgRoleChange,
  orgRoleLocked,
  partOf,
  passwordProblem,
  planName,
  proPrice,
  signIn,
  usageEventsLine,
  whenLabel,
  workerFig,
  type NotificationRow,
} from "./derive.ts";

test("demoting yourself from admin warns that another admin must change it back", () => {
  const c = orgRoleChange({ email: "a@x.com", role: "admin", self: true }, "member", "Acme Aero");
  assert.equal(c.question, "Change your org role in Acme Aero to Member?");
  assert.match(c.detail, /Another admin has to change it back/);
  assert.equal(c.demotesSelf, true);
});

test("changing someone else's role names them and what they can do", () => {
  const c = orgRoleChange({ email: "dana@x.com", role: "member", self: false }, "viewer", "Acme Aero");
  assert.equal(c.question, "Change dana@x.com’s org role in Acme Aero to Viewer?");
  assert.match(c.detail, /can’t check parts or save decisions/);
  assert.equal(c.demotesSelf, false);
  const up = orgRoleChange({ email: "dana@x.com", role: "member", self: false }, "admin", "Acme Aero");
  assert.match(up.detail, /manage members, invites/);
});

test("promoting yourself is not a self-demotion", () => {
  assert.equal(orgRoleChange({ email: "a@x.com", role: "viewer", self: true }, "member", "O").demotesSelf, false);
});

test("the only admin's role is locked; with two admins it isn't", () => {
  assert.equal(orgRoleLocked({ role: "admin" }, 1), true);
  assert.equal(orgRoleLocked({ role: "admin" }, 2), false);
  assert.equal(orgRoleLocked({ role: "member" }, 1), false);
});

test("invite chips", () => {
  assert.deepEqual(inviteChip("pending"), { tone: "warn", label: "Pending" });
  assert.deepEqual(inviteChip("revoked"), { tone: "unk", label: "Revoked" });
  assert.deepEqual(inviteChip("accepted"), { tone: "ok", label: "Accepted" });
});

test("initials and dates", () => {
  assert.equal(initials("austin.lee@acme.com"), "AL");
  assert.equal(initials("x@acme.com"), "X");
  assert.equal(dateLabel("2026-10-18T02:58:37+00:00"), "Oct 18, 2026");
  assert.equal(dateLabel(null), "—");
  const now = new Date("2026-10-18T12:00:00Z");
  assert.equal(whenLabel("2026-10-18T05:00:33Z", now), "05:00");
  assert.equal(whenLabel("2026-10-17T23:10:00Z", now), "Oct 17 23:10");
});

test("plan names and the allowance line never invent a number", () => {
  assert.equal(planName({ plan: "pilot", unlimited: true, used: null, cap: null, remaining: null }), "Pilot");
  assert.equal(planName({ plan: "pro", unlimited: false, used: 1, cap: 50, remaining: 49 }), "Pro");
  assert.equal(planName({ plan: "trial", unlimited: false, used: 0, cap: 15, remaining: 15 }), "Free trial");
  assert.equal(planName(null), null);
  assert.equal(allowanceLine(null, false), "Checking your allowance…");
  assert.equal(allowanceLine(null, true), "Allowance temporarily unavailable.");
  assert.equal(allowanceLine({ plan: "trial", unlimited: false, used: 3, cap: 15, remaining: 12 }, true), "12 of 15 free checks left");
  assert.equal(allowanceLine({ plan: "pro", unlimited: false, used: 1, cap: 4, remaining: 3 }, true), "3 of 4 Pro checks left this month");
});

test("the Pro price comes from Stripe's amount, or nothing", () => {
  assert.deepEqual(proPrice({ unit_amount: 14900, currency: "usd", interval: "month" }), { amount: "$149", per: "a month" });
  assert.deepEqual(proPrice({ unit_amount: 1999, currency: "usd", interval: "month" }), { amount: "$19.99", per: "a month" });
  assert.equal(proPrice(null), null);
  assert.equal(proPrice({ unit_amount: Number.NaN, currency: "usd", interval: "month" }), null);
});

test("audit lines read in plain words", () => {
  assert.equal(actionName("decision.created"), "Decision saved");
  assert.equal(actionName("something.new_thing"), "Something new thing");
  assert.equal(
    auditWhat({ action: "decision.created", resource_type: "cost_decision", resource_id: "01M", detail: { filename: "bored-block-mm.iges", make_now_process: "fdm" }, result_summary: null }),
    "bored-block-mm.iges · make now: filament printing",
  );
  assert.equal(auditWhat({ action: "machine.deleted", resource_type: "machine", resource_id: "01M56N5Q10FVVWS00Q6P7S1296", detail: { org_id: "x" }, result_summary: null }), "machine 01M56N5Q10");
  assert.equal(auditWhat({ action: "api_key.revoked", resource_type: "api_key", resource_id: "4", detail: { key_prefix: "ab12cd34", reason: "rotation" }, result_summary: null }), "cv_live_ab12cd34_… · rotated");
  assert.equal(auditWhat({ action: "analysis.created", resource_type: "analysis", resource_id: "01", detail: { file_name: "object.stl" }, result_summary: "issues" }), "object.stl · has findings");
});

const row = (over: Partial<NotificationRow>): NotificationRow => ({
  id: "n",
  kind: "decision.created",
  severity: "pass",
  title: "Verification recorded - object.stl",
  body: "",
  dest: "records",
  source_type: "cost_decision",
  source_id: "01M58203TBNNKPS71E5ZA2EF31",
  metadata: { filename: "object.stl" },
  created_at: "2026-10-18T05:00:00Z",
  is_read: false,
  read_at: null,
  is_dismissed: false,
  dismissed_at: null,
  ...over,
});

test("notifications open the record, the changes list, or records", () => {
  assert.equal(notificationHref(row({})), "/app/parts/records/01M58203TBNNKPS71E5ZA2EF31");
  assert.equal(notificationHref(row({ source_type: "change_request", source_id: "7", dest: "calibration" })), "/app/shop/changes");
  assert.equal(notificationHref(row({ source_type: "cost_decision", source_id: "not-a-ulid" })), "/app/parts/records");
  assert.equal(notificationHref(row({ source_type: undefined, dest: "verify" })), "/app/parts");
});

test("notifications group by part, newest group first, with unread counts", () => {
  const g = groupNotifications([
    row({ id: "1", created_at: "2026-10-18T03:00:00Z", is_read: true }),
    row({ id: "2", metadata: { filename: "bored-block-mm.iges" }, title: "Verification recorded - bored-block-mm.iges", created_at: "2026-10-18T05:00:00Z" }),
    row({ id: "3", created_at: "2026-10-18T04:00:00Z" }),
    row({ id: "4", kind: "governance.change_requested", title: "Governed change awaiting review", metadata: {}, created_at: "2026-10-18T01:00:00Z" }),
  ]);
  assert.deepEqual(g.map((x) => x.file), ["bored-block-mm.iges", "object.stl", "Change needs review"]);
  assert.equal(g[1].items.length, 2);
  assert.equal(g[1].unread, 1);
  assert.deepEqual(g[1].items.map((i) => i.id), ["3", "1"]);
  assert.equal(g[2].isPart, false);
  assert.equal(partOf({ title: "Verification recorded - a.stl", kind: "decision.created", metadata: {} }), "a.stl");
  assert.equal(kindName({ kind: "decision.created", title: "x" }), "Check recorded");
});

test("usage events and health rows", () => {
  assert.equal(usageEventsLine({ analysis_complete: 12, analysis_cached: 9 }), "Usage events: 12 checks completed, 9 served from cache.");
  assert.equal(usageEventsLine({}), null);
  const rows = healthRows({
    postgres: { ok: true, error: null },
    redis: { ok: true, expected: true, configured: true, error: null },
    worker: { state: "unknown", heartbeat_age_seconds: null, stale_threshold_seconds: 90 },
    queue: { depth: 0, name: "arq:queue" },
    object_store: { ok: false, expected: false, backend: "local", error: null },
  });
  assert.deepEqual(rows.map((r) => r.name), ["Database", "Cache and queue", "Background worker", "Queue depth", "File storage"]);
  assert.equal(rows[2].note, "No heartbeat yet. Stale after 90 s.");
  assert.equal(rows[3].value, "0");
  assert.deepEqual(rows[4].chip, { tone: "unk", label: "Local disk" });
  assert.deepEqual(workerFig({}), { v: "Unknown", sub: "not reported" });
});

test("sign-in modes by AUTH_MODE", () => {
  assert.equal(signIn("password", true).mode, "Password or email link");
  assert.equal(signIn("password", false).mode, "Password");
  assert.equal(signIn("hybrid", false).mode, "Password or single sign-on");
  const sso = signIn("saml", true);
  assert.equal(sso.ssoOnly, true);
  assert.equal(sso.linkOn, false);
  assert.equal(sso.mode, "Single sign-on");
});

test("password rule: 8 to 128 characters, and both match", () => {
  assert.equal(passwordProblem("short", "short"), "Use 8 to 128 characters.");
  assert.equal(passwordProblem("long enough", "long enougj"), "Passwords don’t match.");
  assert.equal(passwordProblem("long enough", "long enough"), null);
  assert.equal(passwordProblem("😀".repeat(8), "😀".repeat(8)), null);
});
