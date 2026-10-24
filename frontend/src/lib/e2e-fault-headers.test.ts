import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { E2E_FAULT_HEADERS, e2eFaultHeaders, isReleased } from "./e2e-fault-headers.ts";

const sent = new Headers({
  "x-proofshape-e2e-token": "local-release-evidence-token",
  "x-proofshape-e2e-fault": "batch_queue",
  "x-other": "kept out",
});

test("a release forwards no fault headers", () => {
  for (const release of ["3f2a9c1", "v2026.10.22", "production"]) {
    assert.equal(isReleased(release), true);
    assert.deepEqual(e2eFaultHeaders(sent, release), {});
  }
});

test("outside a release only the two fault headers are forwarded", () => {
  for (const release of [undefined, "", "dev", "test", "CI", " local "]) {
    assert.equal(isReleased(release), false);
    assert.deepEqual(e2eFaultHeaders(sent, release), {
      "x-proofshape-e2e-token": "local-release-evidence-token",
      "x-proofshape-e2e-fault": "batch_queue",
    });
  }
  assert.deepEqual(e2eFaultHeaders(new Headers(), "dev"), {});
});

test("the data proxy takes its fault headers from this rule only", () => {
  const source = readFileSync(new URL("../app/api/proxy/[...path]/route.ts", import.meta.url), "utf8");
  assert.match(source, /e2eFaultHeaders\(req\.headers\)/);
  for (const name of E2E_FAULT_HEADERS) assert.equal(source.includes(`"${name}"`), false, name);
});
