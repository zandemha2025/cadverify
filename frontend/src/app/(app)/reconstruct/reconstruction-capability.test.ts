import assert from "node:assert/strict";
import test from "node:test";

import type { ReconstructionCapability } from "@/lib/api";
import { reconstructionSubmissionGate } from "./reconstruction-capability.ts";

const local: ReconstructionCapability = {
  available: true,
  can_submit: true,
  effective_backend: "local",
  customer_data_egress: false,
  requires_egress_acknowledgement: false,
  message: "local",
  accuracy_notice: "estimated",
  verify_path: "/verify",
};

test("only a configured, authorized capability can accept an upload", () => {
  assert.deepEqual(reconstructionSubmissionGate(local, false), {
    allowed: true,
    reason: null,
  });
  assert.match(
    reconstructionSubmissionGate({ ...local, available: false }, false).reason ?? "",
    /not enabled/,
  );
  assert.match(
    reconstructionSubmissionGate({ ...local, can_submit: false }, false).reason ?? "",
    /analyst role/,
  );
});

test("remote egress remains blocked until this request is acknowledged", () => {
  const remote = {
    ...local,
    effective_backend: "remote" as const,
    customer_data_egress: true,
    requires_egress_acknowledgement: true,
  };
  assert.equal(reconstructionSubmissionGate(remote, false).allowed, false);
  assert.equal(reconstructionSubmissionGate(remote, true).allowed, true);
});
