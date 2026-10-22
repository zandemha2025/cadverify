/**
 * "Your files and data" says only what the code does today. These pin the
 * statements that matter most to someone deciding whether to upload a CAD file.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/trust/facts.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { DATA_PAGE, DELETING, SECTIONS, SERVICES, SHARE_LINKS, UPLOAD_LINE, WHO } from "./facts.ts";

const all = [UPLOAD_LINE, ...DATA_PAGE.meta, ...SECTIONS.flatMap((s) => [s.title, ...s.rows.flatMap((r) => [r.k, r.v])]), ...SERVICES.flatMap((s) => [s.name, s.gets, s.when])].join("\n");

test("the upload line says the three true things, and only those", () => {
  assert.equal(UPLOAD_LINE, "Your file stays in your organization. Only your team can open it, and ScaleCAD doesn’t use it to train anything.");
});

test("share links say plainly who can see them, that they end after 30 days, and who can switch them off", () => {
  const text = SHARE_LINKS.rows.map((r) => r.v).join(" ");
  assert.match(text, /Anyone with the link, without signing in, can see the file name/);
  assert.match(text, /findings/);
  assert.match(text, /ends 30 days after it’s made/);
  assert.match(text, /90 days, a year or no end date/);
  assert.match(text, /The person who made a link, or an admin, can switch it off/);
  assert.match(text, /The file, the 3D model/);
});

test("deleting says what goes, who may, what stays, and promises nothing about backups", () => {
  const text = DELETING.rows.map((r) => r.v).join(" ");
  assert.match(text, /removes the stored file/);
  assert.match(text, /It can’t be undone/);
  assert.match(text, /admin can delete the organization/);
  assert.match(text, /without its name or results/);
  // An org's audit rows lose the actor; usage counts lose the file's fingerprint.
  assert.match(text, /also without who did them or from where: no email, network address or browser/);
  assert.match(text, /usage counts, without the files’ fingerprints/);
  assert.match(text, /Backups and the storage provider’s earlier versions of files aren’t changed by it/);
  // No retention period is promised for backups.
  assert.doesNotMatch(text, /\b\d+ days\b/);
  // Account deletion is in the app, with what blocks it and what stays.
  assert.match(text, /You can delete your sign-in account in Account, Security/);
  assert.match(text, /Not while you’re the only admin of an organization others are in/);
  assert.match(text, /one-way fingerprint of its email with the number of free checks used, so free checks aren’t issued twice/);
  assert.match(text, /The email can’t be read back from the fingerprint/);
  assert.doesNotMatch(text, /isn’t in ScaleCAD yet/);
});

test("staff access is disclosed, including file names", () => {
  const staff = WHO.rows.find((r) => r.k === "ScaleCAD staff")!.v;
  assert.match(staff, /file names/);
  assert.match(staff, /can’t open your files/);
});

test("no certification, at-rest encryption promise or retention period is claimed", () => {
  assert.doesNotMatch(all, /SOC ?2|ISO ?27001|HIPAA|GDPR compliant|certified/i);
  assert.doesNotMatch(all, /encrypted at rest|AES-?256/i);
  assert.doesNotMatch(all, /retained for|deleted after|\bwithin \d+ days\b/i);
  assert.doesNotMatch(all, /!/);
});

test("every section has an id, a noun title and plain rows", () => {
  const ids = new Set(SECTIONS.map((s) => s.id));
  assert.equal(ids.size, SECTIONS.length);
  for (const s of SECTIONS) {
    assert.ok(s.rows.length > 0, s.id);
    for (const r of s.rows) assert.ok(r.k && r.v.endsWith("."), `${s.id}: ${r.k}`);
  }
});

test("the CRM row says no files, file names or results go there", () => {
  const crm = SERVICES.find((s) => s.name.startsWith("Notion"))!;
  assert.match(crm.gets, /No files, file names or results/);
  assert.match(crm.when, /Deleting your account moves the entry to Notion’s trash/);
});
