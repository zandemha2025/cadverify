/**
 * What the browser says about a pasted share link before sending it.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/lib/link-import.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LINK_FAILURE_TITLE, LINK_NOT_SUPPORTED, linkNameProblem, readLink } from "./link-import.ts";

const backend = new URL("../../../backend/", import.meta.url);

test("each provider's share link is named, with the file's name when the link carries it", () => {
  const cases: [string, string, string | null][] = [
    ["https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing", "Google Drive", null],
    ["https://www.dropbox.com/scl/fi/abc/bracket%20v2.step?rlkey=k&dl=0", "Dropbox", "bracket v2.step"],
    ["https://dropbox.com/s/abc/plate.stl", "Dropbox", "plate.stl"],
    ["https://1drv.ms/u/s!AbCdEf123", "OneDrive", null],
    ["https://contoso.sharepoint.com/:u:/g/personal/x/EabcDEF", "SharePoint", null],
    ["https://contoso.sharepoint.com/sites/eng/Shared%20Documents/frame.iges", "SharePoint", "frame.iges"],
    ["https://my-parts.s3.us-east-1.amazonaws.com/a/b.step.gz?X-Amz-Signature=x", "Amazon S3", "b.step.gz"],
    ["https://s3.amazonaws.com/my-parts/a/notes.pdf", "Amazon S3", null],
  ];
  for (const [url, label, name] of cases) {
    const r = readLink(url);
    assert.ok(r.ok, url);
    if (r.ok) {
      assert.equal(r.label, label, url);
      assert.equal(r.nameHint, name, url);
    }
  }
});

test("what plainly can't be imported is said at once, in the server's words", () => {
  const no = (url: string) => {
    const r = readLink(url);
    assert.equal(r.ok, false, url);
    return r.ok ? "" : r.message;
  };
  assert.equal(no("http://www.dropbox.com/s/a/b.step"), "Only https:// links can be imported.");
  assert.equal(no("https://u:p@www.dropbox.com/s/a/b.step"), "Paste the link without a user name or password in it.");
  assert.equal(no("https://www.dropbox.com:8443/s/a/b.step"), "Only links on the standard https port can be imported.");
  assert.equal(no("https://example.com/b.step"), LINK_NOT_SUPPORTED);
  assert.equal(no("https://www.dropbox.com.evil.example/s/a/b.step"), LINK_NOT_SUPPORTED);
  assert.equal(no("https://169.254.169.254/latest"), LINK_NOT_SUPPORTED);
  assert.equal(no("bracket.step"), "Paste the share link as copied, starting with https://.");
  assert.equal(no("  "), "Paste the file's share link.");
  // The same refusal text as the server's.
  const service = readFileSync(new URL("src/services/link_import.py", backend), "utf8");
  assert.ok(service.includes(`NOT_SUPPORTED = "${LINK_NOT_SUPPORTED}"`));
});

test("a name typed with a link must be a CAD file's", () => {
  assert.equal(linkNameProblem(""), null);
  assert.equal(linkNameProblem("bracket.step"), null);
  assert.equal(linkNameProblem("asm.stp.gz"), null);
  assert.match(linkNameProblem("notes.pdf")!, /STEP, IGES or STL/);
  assert.match(linkNameProblem("../x.step")!, /STEP, IGES or STL/);
});

test("every fetch failure the worker can report has a title", () => {
  const service = readFileSync(new URL("src/services/link_import.py", backend), "utf8");
  const codes = new Set([...service.matchAll(/LinkFetchError\(\s*"(LINK_[A-Z_]+)"/g)].map((m) => m[1]));
  for (const code of codes) assert.ok(LINK_FAILURE_TITLE[code], code);
});
