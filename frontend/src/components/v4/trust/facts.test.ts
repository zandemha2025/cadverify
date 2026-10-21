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

test("share links say plainly who can see them and that they don't expire today", () => {
  const text = SHARE_LINKS.rows.map((r) => r.v).join(" ");
  assert.match(text, /Anyone with the link, without signing in, can see the file name/);
  assert.match(text, /findings/);
  assert.match(text, /Links don’t expire today/);
  assert.match(text, /The file, the 3D model/);
});

test("deleting says it isn't in the product yet", () => {
  assert.match(DELETING.rows.map((r) => r.v).join(" "), /isn’t in ScaleCAD yet/);
  assert.doesNotMatch(DELETING.rows.map((r) => r.v).join(" "), /\b\d+ days\b/);
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
});
