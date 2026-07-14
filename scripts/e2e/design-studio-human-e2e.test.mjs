import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("./design-studio-human-e2e.mjs", import.meta.url),
  "utf8",
);

function method(name, nextName) {
  const start = source.indexOf(`async ${name}(`);
  assert.ok(start >= 0, `${name} method is missing`);
  const end = nextName ? source.indexOf(`async ${nextName}(`, start + 1) : source.length;
  assert.ok(end > start, `${name} method boundary is missing`);
  return source.slice(start, end);
}

test("authenticated API evidence runs inside the signed-in page through the live proxy", () => {
  const body = method("api", "listDesigns");
  assert.match(body, /targetUrl\.pathname\.startsWith\("\/api\/proxy\/"\)/);
  assert.match(body, /this\.page\.evaluate/);
  assert.match(body, /await fetch\(target/);
  assert.match(body, /credentials: "same-origin"/);
  assert.match(body, /crypto\.subtle\.digest\("SHA-256", bytes\)/);
  assert.doesNotMatch(source, /context\.request|request\.newContext|pw\.request/);
});

test("download and Verify artifact integrity re-reads stay on the browser proxy", () => {
  const download = method("downloadHash", "generateCurrentForm");
  assert.match(download, /const evidenceResponse = await this\.api\(href\)/);
  assert.match(download, /evidenceResponse\.sha256/);
  assert.match(download, /responseHeaderSha256 === hash/);

  const verify = method("verifySelectedRevision", "run");
  assert.match(verify, /this\.api\(artifactResponse\.url\(\)\)/);
  assert.match(verify, /artifactEvidenceResponse\.byteLength/);
  assert.match(verify, /importedBytes,/);
  assert.doesNotMatch(verify, /importedBytes:\s*importedBytes\.length/);
  assert.match(verify, /browserHeaderSha256 === importedHeaderSha256/);

  const artifact = method("revisionArtifact", "expectText");
  assert.match(artifact, /const hash = response\.sha256/);
  assert.match(artifact, /bytes: response\.byteLength/);
});

test("every structured Design Studio path binds its screenshot to the path ID", () => {
  for (const id of ["DES-01", "DES-02", "DES-03", "DES-04", "DES-05", "DES-06", "DES-08", "DES-10", "DES-12"]) {
    assert.match(source, new RegExp(`shot\\(\\s*[\"\\\`]${id}-`), `${id} screenshot is not ID-bound`);
  }
  for (const id of ["DES-07", "DES-09", "DES-11"]) {
    assert.ok(source.includes(`criticalPathId: "${id}"`), `${id} Verify screenshot is not ID-bound`);
  }
  assert.match(source, /criticalPathId \? `\$\{criticalPathId\}-` : ""/);
});
