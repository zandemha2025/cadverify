import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { mock, test } from "node:test";

const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "sonner") return next("data:text/javascript,export const toast={error(){}}", context);
  if (specifier === "@sentry/nextjs") return next("data:text/javascript,export function captureException(){};export function captureMessage(){}", context);
  if (specifier === "@/lib/api-recovery") return next(new URL("./api-recovery.ts", import.meta.url).href, context);
  if (["./api-base", "./reconstruction-id", "./mesh-repair-client", "./api", "./verify/check-id"].includes(specifier)) return next(new URL(`${specifier}.ts`, import.meta.url).href, context);
  return next(specifier, context);
} });
const api = await import("./api.ts");
const { partCheckHeaders } = await import("./verify/check-id.ts");
hooks.deregister();

test("failed compute and writes run once; reads and keyed submissions retain bounded retries", async () => {
  const calls: RequestInit[] = [];
  let reply = async () => Response.json({ detail: "Analysis exceeded 60s timeout." }, { status: 504 });
  const fetchMock = mock.method(globalThis, "fetch", async (_url: unknown, init: RequestInit = {}) => {
    calls.push(init);
    return reply();
  });
  const file = new File(["test CAD"], "part.step");
  try {
    for (const action of [
      () => api.validateFile(file),
      () => api.createRfqPackage({ decisionIds: ["saved"] }),
      () => api.approveCostDecision("saved"),
      () => api.reopenCostDecisionApproval("saved"),
      () => api.setCostDecisionDisposition("saved", null),
    ]) {
      calls.length = 0;
      await assert.rejects(action(), /Analysis exceeded 60s timeout/);
      assert.equal(calls.length, 1, "A failed write or expensive upload must not run again automatically");
    }
    calls.length = 0;
    reply = async () => { throw new TypeError("Connection lost after submission"); };
    await assert.rejects(api.validateFile(file), /Connection interrupted.*refresh the saved list, and retry once/);
    assert.equal(calls.length, 1, "A transport failure does not prove that a write was rejected");

    calls.length = 0;
    reply = async () => calls.length === 1 ? new Response(null, { status: 503 }) : Response.json({ processes: [] });
    assert.deepEqual(await api.getProcesses(), { processes: [] });
    assert.equal(calls.length, 2);

    calls.length = 0;
    reply = async () => new Response(null, { status: 503 });
    await assert.rejects(api.getProcesses(), /could not finish/);
    assert.equal(calls.length, 3, "Read retries must stop at the existing limit");

    calls.length = 0;
    reply = async () => calls.length < 3 ? new Response(null, { status: 503 }) : Response.json({ job_id: "same-job" });
    const key = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
    await api.submitReconstruction([new File(["test image"], "part.png")], undefined, undefined, key);
    assert.equal(calls.length, 3);
    assert.ok(calls.every(call => new Headers(call.headers).get("Idempotency-Key") === key));

    calls.length = 0;
    reply = async () => Response.json({ detail: "Cost analysis exceeded 60s timeout." }, { status: 504 });
    await assert.rejects(api.costEstimate(file, { qty: "1", region: "auto", material_class: "aluminum", units: "mm", complexity: "moderate", cavities: 1 }), /Cost analysis exceeded 60s timeout/);
    assert.equal(calls.length, 1);
  } finally { fetchMock.mock.restore(); }
});


test("one uploaded part shares its allowance ID across DFM, cost and preview", async () => {
  const ids: (string | null)[] = [];
  const fetchMock = mock.method(globalThis, "fetch", async (_url: unknown, init: RequestInit = {}) => {
    ids.push(new Headers(init.headers).get("x-part-check-id"));
    return Response.json({});
  });
  try {
    const file = new File(["CAD"], "part.stp");
    const id = partCheckHeaders(file)["x-part-check-id"];
    await api.validateFile(file, undefined, undefined, undefined, "mm", id);
    await api.costEstimate(file, { qty: "1", region: "auto", material_class: "aluminum", units: "mm", complexity: "moderate", cavities: 1 }, id);
    assert.deepEqual(ids, [id, id]);
    assert.equal(partCheckHeaders(file)["x-part-check-id"], id);
    const recheck = new File([file], file.name);
    assert.notEqual(partCheckHeaders(recheck)["x-part-check-id"], id);
  } finally { fetchMock.mock.restore(); }
});
