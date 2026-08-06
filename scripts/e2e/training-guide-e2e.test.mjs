import assert from "node:assert/strict";
import test from "node:test";

import {
  reconcileSuccessfulUploadAborts,
  recoverableUploadAbortKey,
  redactRequestUrl,
} from "./training-guide-e2e.mjs";

const appUrl = "http://127.0.0.1:3001";
const signedPartUrl =
  "http://127.0.0.1:5001/bucket/direct-uploads/org/upload/batch.zip" +
  "?uploadId=provider-secret&partNumber=1&AWSAccessKeyId=test&Signature=secret";

test("training-guide diagnostics redact every provider query credential", () => {
  assert.equal(
    redactRequestUrl(signedPartUrl),
    "http://127.0.0.1:5001/bucket/direct-uploads/org/upload/batch.zip",
  );
  assert.equal(redactRequestUrl("not a URL"), "<invalid-url>");
});

test("only exact multipart upload and completion requests are recoverable aborts", () => {
  const partKey = recoverableUploadAbortKey("PUT", signedPartUrl, appUrl);
  assert.match(partKey, /^multipart-part\|/);
  assert.equal(recoverableUploadAbortKey("GET", signedPartUrl, appUrl), null);
  assert.equal(
    recoverableUploadAbortKey(
      "PUT",
      "http://127.0.0.1:5001/bucket/direct-uploads/org/upload/batch.zip?partNumber=1",
      appUrl,
    ),
    null,
  );
  assert.match(
    recoverableUploadAbortKey(
      "POST",
      `${appUrl}/api/proxy/uploads/01KXTESTUPLOAD000000000000/complete`,
      appUrl,
    ),
    /^multipart-complete\|/,
  );
  assert.equal(
    recoverableUploadAbortKey(
      "POST",
      "http://127.0.0.1:5001/api/proxy/uploads/01KXTESTUPLOAD000000000000/complete",
      appUrl,
    ),
    null,
  );
});

test("an aborted upload passes diagnostics only with the same request's 2xx receipt", () => {
  const key = recoverableUploadAbortKey("PUT", signedPartUrl, appUrl);
  const pending = [{
    key,
    evidence: {
      method: "PUT",
      url: redactRequestUrl(signedPartUrl),
      error: "net::ERR_ABORTED",
    },
  }];

  const recovered = reconcileSuccessfulUploadAborts(pending, new Map([[key, 200]]));
  assert.equal(recovered.expected.length, 1);
  assert.equal(recovered.expected[0].recoveredStatus, 200);
  assert.deepEqual(recovered.failures, []);

  const unmatched = reconcileSuccessfulUploadAborts(
    pending,
    new Map([[`${key}|different-request`, 200]]),
  );
  assert.deepEqual(unmatched.expected, []);
  assert.equal(unmatched.failures.length, 1);
  assert.match(unmatched.failures[0].reason, /no exact matching successful HTTP response/);
  assert.doesNotMatch(JSON.stringify(unmatched), /Signature=|AWSAccessKeyId=/);
});
