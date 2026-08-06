import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";

import {
  designFilename,
  designIdFromSearch,
  designRevisionFromSearch,
  importDesignStep,
} from "./design-import.ts";

const ID = "01KXC3RGR5GNNEWMD512EWTGMT";

test("design handoff accepts only one valid ULID query value", () => {
  assert.equal(designIdFromSearch(`?design=${ID}`), ID);
  assert.equal(designIdFromSearch("?design=../../secret"), null);
  assert.equal(designIdFromSearch("?design=short"), null);
});

test("revision handoff is optional and bounded to a positive integer", () => {
  assert.equal(designRevisionFromSearch("?revision=2"), 2);
  assert.equal(designRevisionFromSearch(""), null);
  assert.equal(designRevisionFromSearch("?revision=0"), null);
  assert.equal(designRevisionFromSearch("?revision=2.5"), null);
});

test("artifact filename is path-stripped, bounded, and STEP-only", () => {
  assert.equal(designFilename('attachment; filename="Motor_mount.step"'), "Motor_mount.step");
  assert.equal(designFilename('attachment; filename="../../evil.step"'), "evil.step");
  assert.equal(designFilename('attachment; filename="payload.exe"'), "proofshape-design.step");
});

test("real STEP response becomes the same File contract as a manual upload", async () => {
  let requested = "";
  const body = "ISO-10303-21;\nEND-ISO-10303-21;";
  const hash = createHash("sha256").update(body).digest("hex");
  const fetcher = async (url: string | URL | Request) => {
    requested = String(url);
    return new Response(body, {
      status: 200,
      headers: {
        "content-disposition": 'attachment; filename="Fixture-r2.step"',
        "x-geometry-sha256": hash,
      },
    });
  };
  const file = await importDesignStep(ID, fetcher as typeof fetch, 2);
  assert.match(requested, /revisions\/2\/download\.step$/);
  assert.equal(file.name, "Fixture-r2.step");
  assert.equal(file.type, "model/step");
  assert.match(await file.text(), /ISO-10303-21/);
});

test("handoff rejects a STEP whose bytes do not match revision evidence", async () => {
  const fetcher = async () => new Response("tampered", {
    status: 200,
    headers: {
      "content-disposition": 'attachment; filename="Fixture.step"',
      "x-geometry-sha256": "0".repeat(64),
    },
  });
  await assert.rejects(
    () => importDesignStep(ID, fetcher as typeof fetch),
    /failed its integrity check/,
  );
});
