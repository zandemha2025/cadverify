import { test, mock } from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";

const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "@/lib/api-base") return next(new URL("../api-base.ts", import.meta.url).href, context);
  return next(specifier, context);
} });
const { measureContextFit } = await import("./context-fit.ts");
const { fetchPreviewMesh } = await import("./preview-mesh.ts");
hooks.deregister();

test("fit and preview requests preserve independent source units and mm nudges", async () => {
  const calls: URL[] = [];
  const fetchMock = mock.method(globalThis, "fetch", async (url: unknown) => {
    calls.push(new URL(String(url), "http://localhost"));
    return String(url).includes("preview-mesh") ? new Response(new Blob(["test-shell"])) : Response.json({});
  });
  const file = new File(["test coordinates"], "part.stl");
  try {
    await measureContextFit(file, file, "shared_frame", [35.4, 0, 0], { part: "inch", context: "mm" });
    assert.equal(calls[0].searchParams.get("part_a_units"), "inch");
    assert.equal(calls[0].searchParams.get("part_b_units"), "mm");
    assert.equal(calls[0].searchParams.get("nudge_x_mm"), "35.4");
    for (const options of [{ units: "inch" as const }, { units: "mm" as const }, { forAnalysis: true, units: "inch" as const }]) {
      const preview = await fetchPreviewMesh(file, options);
      assert.ok(preview);
      preview.revoke();
      assert.equal(calls.at(-1)!.searchParams.get("units"), options.units);
      assert.equal(calls.at(-1)!.searchParams.get("purpose"), options.forAnalysis ? "analysis" : null);
    }
  } finally { fetchMock.mock.restore(); }
});

test("preview preserves allowance exhaustion while ordinary failures remain retryable", async () => {
  const file = new File(["test"], "part.stl");
  const fetchMock = mock.method(globalThis, "fetch", async () =>
    Response.json({ code: "org_validation_cap_exceeded", message: "100 validations used in total" }, { status: 429 }));
  try {
    await assert.rejects(fetchPreviewMesh(file), /Verification allowance used up.*100 validations/);
    fetchMock.mock.mockImplementation(async () => new Response(null, { status: 503 }));
    assert.equal(await fetchPreviewMesh(file), null);
  } finally { fetchMock.mock.restore(); }
});


test("viewer remounts and concurrent viewers reuse one preview with independent URLs", async () => {
  let calls = 0;
  const fetchMock = mock.method(globalThis, "fetch", async () => {
    calls++;
    return new Response(new Blob(["recorded preview"]), { headers: { "x-mesh-original-faces": "12" } });
  });
  try {
    const file = new File(["CAD"], "part.stp");
    const [a, b] = await Promise.all([fetchPreviewMesh(file), fetchPreviewMesh(file)]);
    assert.ok(a && b);
    assert.equal(calls, 1);
    assert.notEqual(a.url, b.url);
    a.revoke(); b.revoke();
    const remount = await fetchPreviewMesh(file);
    assert.equal(remount?.originalFaces, 12);
    assert.equal(calls, 1);
    remount?.revoke();
    const recheck = await fetchPreviewMesh(new File([file], file.name));
    assert.equal(calls, 2);
    recheck?.revoke();
  } finally { fetchMock.mock.restore(); }
});
