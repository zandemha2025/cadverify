/** Deleting and share-link wording: every sentence from the server's own counts. */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EXPIRY_CHOICES,
  accountReceiptLine,
  accountRemovalLines,
  emailMatches,
  choiceFromKey,
  choiceKey,
  linkEndText,
  linksLine,
  nameMatches,
  orgMembersAfterLine,
  orgPlanLine,
  orgRemovalLines,
  partRemovalLines,
  receiptLine,
  statusLabel,
  type AccountPreview,
  type OrgPreview,
  type PartPreview,
  type Receipt,
} from "./words.ts";

const PREVIEW: PartPreview = {
  mesh_hash: "a".repeat(64),
  exists: true,
  file_name: "bracket.step",
  source_kept: true,
  will_remove: { checks: 2, cost_records: 1, fixed_copies: 1, active_share_links: 3, actual_costs: 1, part_context: 1, batch_items: 0, rfq_packages_touched: 1 },
  fixed_copies: ["b".repeat(64)],
  can_delete: true,
  kept: [],
};

test("a part's delete lists what goes, plainly, from the counts", () => {
  assert.deepEqual(partRemovalLines(PREVIEW, false), [
    "The stored file you uploaded",
    "2 checks and 1 cost record, with their results and PDFs",
    "1 copy ScaleCAD fixed from it, with their own checks",
    "Its program, assembly and yearly volume",
    "1 actual cost logged against this file",
    "Its items in 1 supplier package",
  ]);
  // Keeping the copies drops that line.
  assert.ok(!partRemovalLines(PREVIEW, true).some((l) => l.includes("fixed from it")));
  assert.equal(linksLine(PREVIEW), "The 3 shared links to it stop working now.");
  assert.equal(linksLine({ ...PREVIEW, will_remove: { ...PREVIEW.will_remove!, active_share_links: 1 } }), "The shared link to it stops working now.");
  assert.equal(linksLine({ ...PREVIEW, will_remove: { ...PREVIEW.will_remove!, active_share_links: 0 } }), null);
  // No stored file: the line isn't claimed.
  assert.ok(!partRemovalLines({ ...PREVIEW, source_kept: false }, false).includes("The stored file you uploaded"));
});

test("receipts say what is done and what is still going", () => {
  const base: Receipt = { id: "01DEL", scope: "part", target: "a", status: "done", removed: {}, files: { steps_total: 4, steps_done: 4, removed: 6, retrying: false }, created_at: null, completed_at: null, kept: [] };
  assert.match(receiptLine(base), /^Deleted\./);
  assert.equal(
    receiptLine({ ...base, status: "removing_files", files: { steps_total: 4, steps_done: 1, removed: 2, retrying: true } }),
    "The records are deleted. Removing the stored files: 1 of 4 storage areas done, retrying.",
  );
  assert.match(receiptLine({ ...base, status: "failed" }), /deletion ID: 01DEL/);
  assert.match(receiptLine({ ...base, scope: "organization" }), /organization's files/);
});

test("link ends read as dates or plain states", () => {
  const at = "2026-11-20T12:00:00+00:00";
  assert.equal(linkEndText("active", at), "Ends 20 Nov 2026");
  assert.equal(linkEndText("active", null), "No end date");
  assert.equal(linkEndText("expired", at), "Ended 20 Nov 2026");
  assert.equal(linkEndText("off", null, "2026-10-03T09:00:00+00:00"), "Switched off 3 Oct 2026");
  assert.equal(linkEndText(null, null), "No link");
  assert.equal(statusLabel("expired"), "Ended");
  assert.equal(statusLabel("off"), "Switched off");
});

test("expiry choices: 30 days first, the explicit no-end-date last, keys round-trip", () => {
  assert.deepEqual(EXPIRY_CHOICES.map((c) => c.value), [30, 90, 365, null]);
  for (const c of EXPIRY_CHOICES) assert.equal(choiceFromKey(choiceKey(c.value)), c.value);
  assert.equal(choiceFromKey("garbage"), 30);
});

test("deleting the organization: typed name must match exactly; the list counts what goes", () => {
  assert.equal(nameMatches(" Acme Machining ", "Acme Machining"), true);
  assert.equal(nameMatches("acme machining", "Acme Machining"), false);
  assert.equal(nameMatches("", ""), false);
  const p: OrgPreview = {
    org_id: "o",
    name: "Acme",
    will_remove: { parts: 3, checks: 5, cost_records: 2, batches: 0, designs: 1, actual_costs: 0, members: 4, pending_invites: 1, api_keys: 2, active_share_links: 1 },
    kept: [],
  };
  const lines = orgRemovalLines(p);
  assert.equal(lines[0], "3 parts with their stored files, 5 checks and 2 cost records");
  assert.ok(lines.includes("1 Design Studio design"));
  assert.ok(lines.includes("1 shared link: they stop working now"));
  assert.ok(lines.includes("2 API keys: they stop working now"));
  assert.equal(lines[lines.length - 1], "Access for 4 members and 1 pending invite");
  assert.ok(!lines.some((l) => l.includes("catalog run")));
  const empty = orgRemovalLines({ ...p, will_remove: { ...p.will_remove, parts: 0, checks: 0, cost_records: 0 } });
  assert.equal(empty[0], "No parts, checks or cost records yet");

  // it-24: the plan is cancelled with the org, said before confirming; members' fate plainly.
  assert.equal(orgPlanLine(p, false), null);
  const paying: OrgPreview = { ...p, name: "Kestrel Aero", billing: { plan: "pro", subscription_status: "active", period_end: "2026-11-20T00:00:00Z", cancels_now: true } };
  assert.equal(orgPlanLine(paying, false), "Your Pro plan is cancelled with Kestrel Aero: nothing more is charged. The rest of the period to 20 Nov 2026 isn't refunded.");
  assert.match(orgPlanLine(paying, true) ?? "", /^Your Pro plan stays/);
  const after = orgMembersAfterLine(paying);
  assert.match(after, /^Everyone in Kestrel Aero keeps their sign-in account and loses all access to Kestrel Aero\. The 3 other members are signed out\./);
  assert.match(after, /their own workspace, named "<first name>'s workspace" \(new and empty if they don't have one\)\. Nothing from Kestrel Aero is in it\./);
  assert.match(after, /Other members' own plans aren't changed\.$/);
  assert.doesNotMatch(orgMembersAfterLine({ ...paying, will_remove: { ...paying.will_remove, members: 1 } }), /other member/);
  assert.match(receiptLine({ id: "01DEL", scope: "organization", target: "o", status: "done", removed: { pro_plan_cancelled: true }, files: { steps_total: 1, steps_done: 1, removed: 0, retrying: false }, created_at: null, completed_at: null, kept: [] } as Receipt), /your Pro plan is cancelled\.$/);
});

const ACCOUNT: AccountPreview = {
  email: "mia@acme-aero.com",
  can_delete: true,
  blockers: [],
  orgs_deleted: [{ org_id: "o1", name: "Mia's workspace", will_remove: { parts: 3, checks: 4, cost_records: 1, batches: 0, designs: 0, actual_costs: 0, members: 1, pending_invites: 0, api_keys: 1, active_share_links: 0 } }],
  orgs_left: [{ org_id: "o2", name: "Acme Aero", role: "member", members: 6 }],
  api_keys: 2,
  billing: { plan: "pro", subscription_status: "active", period_end: "2026-11-20T00:00:00Z", cancels_now: true },
  kept: [],
};

test("deleting your account lists what goes, from the server's counts", () => {
  const lines = accountRemovalLines(ACCOUNT);
  assert.equal(lines[0], "Your sign-in: email, name, phone, password and single sign-on links. Every browser and key is signed out.");
  assert.ok(lines.includes("Mia's workspace, which only you are in: 3 parts with their stored files, 4 checks and 1 cost record, and its settings"));
  assert.ok(lines.includes("Your access to Acme Aero. What you made there stays with it."));
  assert.ok(lines.includes("2 API keys: they stop working now"));
  assert.ok(lines.includes("Your Pro plan, cancelled now: nothing more is charged. The rest of the period to 20 Nov 2026 isn't refunded."));
  const free = accountRemovalLines({ ...ACCOUNT, orgs_deleted: [], orgs_left: [{ org_id: "a", name: "A", role: "member", members: 2 }, { org_id: "b", name: "B", role: "admin", members: 3 }, { org_id: "c", name: "C", role: "viewer", members: 2 }], api_keys: 0, billing: { plan: "trial", subscription_status: null, period_end: null, cancels_now: false } });
  assert.ok(free.includes("Your access to A, B and C. What you made there stays with them."));
  assert.ok(!free.some((l) => /API key|Pro plan|which only you/.test(l)));
  for (const l of [...lines, ...free]) assert.doesNotMatch(l, /!/);
});

test("deleting your account: the typed email must be the account's, ignoring case and outer spaces", () => {
  assert.equal(emailMatches("  MIA@acme-aero.com ", "mia@acme-aero.com"), true);
  assert.equal(emailMatches("mia@acme-aero.co", "mia@acme-aero.com"), false);
  assert.equal(emailMatches("   ", "mia@acme-aero.com"), false);
});

test("an account receipt says what is gone, or what ScaleCAD is still removing", () => {
  const base: Receipt = { id: "01ACCOUNT", scope: "account", target: "7", status: "done", removed: { organizations_deleted: 1 }, files: { steps_total: 6, steps_done: 6, removed: 9, retrying: false }, created_at: null, completed_at: null, kept: [] };
  assert.equal(accountReceiptLine(base), "Deleted. Your account and the organization only you were in are gone.");
  assert.equal(receiptLine({ ...base, removed: { organizations_deleted: 0 } }), "Deleted. Your account is gone.");
  assert.equal(receiptLine({ ...base, status: "removing_files", files: { steps_total: 6, steps_done: 2, removed: 3, retrying: true } }), "Your account is deleted. Stored files: 2 of 6 storage areas removed, retrying. ScaleCAD finishes the rest; nothing more is needed from you.");
  assert.match(receiptLine({ ...base, status: "failed" }), /01ACCOUNT/);
});
