import assert from "node:assert/strict";
import test from "node:test";
import { ProofShapeClient, ProofShapeApiError } from "../src/client.js";

const SOURCE = { host: "onshape", workspaceId: "w1", documentId: "d1", revisionId: "r1", elementId: "e1" };

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("validates a STEP multipart request and normalizes a synchronous verdict", async () => {
  const calls = [];
  const client = new ProofShapeClient({ baseUrl: "https://staging.example", apiKey: "cv_live_test", fetchImpl: async (url, init) => {
    calls.push({ url, init });
    return json({ overall_verdict: "pass", issues: [], share_url: "/s/abc", sampled: { faces: 20 }, provenance: "occ-v1" });
  }});
  const verdict = await client.validateStep({ bytes: new Uint8Array([1, 2]), filename: "part.step", source: SOURCE });
  assert.equal(calls[0].url, "https://staging.example/api/v1/validate");
  assert.equal(calls[0].init.headers.Authorization, "Bearer cv_live_test");
  assert.ok(calls[0].init.body instanceof FormData);
  assert.equal(calls[0].init.body.get("connector_source"), JSON.stringify(SOURCE));
  assert.deepEqual(verdict, { badge: "PASS", issues: [], recordUrl: "https://staging.example/s/abc", sampled: { faces: 20 }, provenance: "occ-v1", raw: verdict.raw });
});

test("polls a 202 job through result and preserves honesty marks", async () => {
  const responses = [json({ job_id: "j1", poll_url: "/api/v1/jobs/j1" }, 202), json({ job_id: "j1", status: "running" }), json({ job_id: "j1", status: "done", result_url: "/api/v1/jobs/j1/result" }), json({ result: { verdict: "issues", findings: [{ message: "Thin wall" }], sampling: "mesh", provenance: "rule-pack" } })];
  const client = new ProofShapeClient({ baseUrl: "https://staging.example", apiKey: "cv_live_test", pollIntervalMs: 0, fetchImpl: async () => responses.shift() });
  const result = await client.validateStep({ bytes: new Blob(["STEP"]), source: SOURCE });
  assert.equal(result.badge, "ISSUES");
  assert.deepEqual(result.issues, ["Thin wall"]);
  assert.equal(result.sampled, "mesh");
});

test("fails loudly on terminal job failure", async () => {
  const responses = [json({ job_id: "j2" }, 202), json({ job_id: "j2", status: "failed", error: { code: "bad_step", message: "STEP rejected" } })];
  const client = new ProofShapeClient({ baseUrl: "https://staging.example", apiKey: "cv_live_test", pollIntervalMs: 0, fetchImpl: async () => responses.shift() });
  await assert.rejects(() => client.validateStep({ bytes: new Blob(["bad"]), source: SOURCE }), (error) => error instanceof ProofShapeApiError && error.code === "bad_step");
});


test("refuses exports without load-bearing source identity", async () => {
  const client = new ProofShapeClient({ baseUrl: "https://staging.example", apiKey: "cv_live_test", fetchImpl: async () => json({}) });
  await assert.rejects(() => client.validateStep({ bytes: new Blob(["STEP"]) }), /revision identity/);
});

test("refuses native host files before upload", async () => {
  let called = false;
  const client = new ProofShapeClient({ baseUrl: "https://staging.example", apiKey: "cv_live_test", fetchImpl: async () => { called = true; return json({}); } });
  await assert.rejects(() => client.validateStep({ bytes: new Blob(["native"]), filename: "part.sldprt", source: SOURCE }), /must export STEP/);
  assert.equal(called, false);
});

test("normalizes the current /validate contract: priority_fixes and share_url", async () => {
  const client = new ProofShapeClient({ baseUrl: "https://api.example", apiKey: "cv_live_x", fetchImpl: async () => json({
    overall_verdict: "issues",
    priority_fixes: [
      { code: "WALL_THIN", severity: "error", message: "Wall below 2mm minimum", fix: "Thicken wall to 2mm", process: "fdm" },
      { code: "DRAIN_SMALL", severity: "warning", message: "Drain hole under 2mm" },
    ],
    share_url: "/s/rec1",
  }) });
  const verdict = await client.validateStep({ bytes: new Blob(["STEP"]), source: SOURCE });
  assert.equal(verdict.badge, "ISSUES");
  assert.deepEqual(verdict.issues, ["Wall below 2mm minimum (Fix: Thicken wall to 2mm)", "Drain hole under 2mm"]);
  assert.equal(verdict.recordUrl, "https://api.example/s/rec1");
});

test("flattens process_scores issues when priority_fixes is absent", async () => {
  const client = new ProofShapeClient({ baseUrl: "https://api.example", apiKey: "cv_live_x", fetchImpl: async () => json({
    overall_verdict: "fail",
    process_scores: [
      { process: "fdm", verdict: "fail", issues: [{ code: "TRAP", message: "Trapped volume", fix_suggestion: "Add drain" }] },
      { process: "cnc", verdict: "pass", issues: [] },
    ],
  }) });
  const verdict = await client.validateStep({ bytes: new Blob(["STEP"]), source: SOURCE });
  assert.equal(verdict.badge, "FAIL");
  assert.deepEqual(verdict.issues, ["Trapped volume (Fix: Add drain)"]);
});
