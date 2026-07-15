import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("batch upload UI exposes honest progress, automatic retry, and terminal error states", async () => {
  const source = await readFile(
    new URL("./BatchUploadForm.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /onUploadProgress: setUploadProgress/);
  assert.match(source, /data-upload-stage=\{uploadProgress\.stage\}/);
  assert.match(source, /<Progress value=\{uploadProgress\.percent\}/);
  assert.match(source, /role="progressbar"/);
  assert.match(source, /A byte percentage is unavailable for this compatibility upload\./);
  assert.match(source, /Retrying automatically in \$\{seconds\} \$\{unit\}/);
  assert.match(source, /attempt \$\{progress\.nextAttempt\} of \$\{progress\.maxAttempts\}/);
  assert.match(source, /data-upload-error/);
  assert.match(source, /err instanceof DirectUploadError/);
  assert.match(source, /No batch was created\. The ZIP remains selected so you can retry it\./);
  assert.match(source, /Check Recent batches before retrying/);
});
