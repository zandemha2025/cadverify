/**
 * Photo to 3D rules: the capability's meaning, the steps, photo validation,
 * the Reconstruct button and the progress line.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/make/photo-model.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ReconstructionCapability } from "../../../lib/api";
import {
  canAdd,
  dropTitle,
  goHint,
  goLabel,
  levelWord,
  metaState,
  modeOf,
  photoProblem,
  progressFraction,
  sheetMeta,
  statusLabel,
  stepNote,
  stepNow,
  steps,
} from "./photo-model.ts";

const cap = (over: Partial<ReconstructionCapability>): ReconstructionCapability => ({
  available: true,
  can_submit: true,
  effective_backend: "local",
  customer_data_egress: false,
  requires_egress_acknowledgement: false,
  message: "m",
  accuracy_notice: "a",
  verify_path: "/verify?screen=verify",
  ...over,
});

test("the server's capability decides the mode", () => {
  assert.equal(modeOf(null, false), "loading");
  assert.equal(modeOf(null, true), "error");
  assert.equal(modeOf(cap({ available: false }), false), "off");
  assert.equal(modeOf(cap({ requires_egress_acknowledgement: true, customer_data_egress: true, effective_backend: "remote" }), false), "egress");
  assert.equal(modeOf(cap({}), false), "local");
  assert.equal(metaState("off"), "Off on this server");
  assert.equal(sheetMeta("off"), "Off on this server · nothing can be uploaded");
  assert.equal(sheetMeta("egress"), "Third-party provider · approve, then add photos");
});

test("steps follow the job", () => {
  assert.equal(stepNow("off", "upload", 0), 0);
  assert.equal(stepNow("local", "upload", 0), 1);
  assert.equal(stepNow("local", "upload", 2), 2);
  assert.equal(stepNow("egress", "proc", 2), 3);
  assert.equal(stepNow("egress", "done", 2), 4);
  assert.equal(stepNote("off", 0), "Available after an admin approves a backend");
  assert.equal(stepNote("local", 2), "Step 2 of 4");
  assert.equal(steps("egress")[0].d, "Consent to the third-party transfer");
  assert.equal(steps("off")[0].d, "Admin enables a backend");
});

test("photos: up to 4 JPEG, PNG or WebP, 20 MB each", () => {
  const jpg = { name: "a.jpg", type: "image/jpeg", size: 1000 };
  assert.equal(photoProblem(0, [jpg]), null);
  assert.equal(photoProblem(3, [jpg, jpg]), "Up to 4 photos. You have 3; that would make 5.");
  assert.equal(photoProblem(0, [{ name: "a.gif", type: "image/gif", size: 1 }]), "“a.gif” isn’t a JPEG, PNG or WebP image.");
  assert.equal(photoProblem(0, [{ ...jpg, size: 21 * 1024 * 1024 }]), "“a.jpg” is over 20 MB.");
});

test("adding and reconstructing need the tool on and, for a provider, consent", () => {
  assert.equal(canAdd("off", true, 0), false);
  assert.equal(canAdd("egress", false, 0), false);
  assert.equal(canAdd("egress", true, 3), true);
  assert.equal(canAdd("local", false, 4), false);
  assert.equal(dropTitle("off", false, 0), "Uploads are off");
  assert.equal(dropTitle("egress", false, 0), "Approve the transfer first");
  assert.equal(dropTitle("local", false, 4), "4 photos added");
  assert.equal(dropTitle("local", false, 1), "Drop photos or click to add");
  assert.equal(goLabel(0), "Reconstruct");
  assert.equal(goLabel(1), "Reconstruct (1 image)");
  assert.equal(goLabel(3), "Reconstruct (3 images)");
  assert.equal(goHint("off", false, 0), "Off on this server");
  assert.equal(goHint("egress", false, 1), "Approve the transfer");
  assert.equal(goHint("local", false, 0), "Add at least 1 photo");
  assert.equal(goHint("local", false, 1), "");
});

test("progress is time against the estimate, never shown as done", () => {
  assert.equal(progressFraction(0, 30), 0.05);
  assert.equal(progressFraction(15, 30), 0.5);
  assert.equal(progressFraction(300, 30), 0.95);
  assert.equal(statusLabel("queued"), "Preparing images…");
  assert.equal(statusLabel("running"), "Building 3D model…");
  assert.equal(levelWord("medium"), "Medium");
});
