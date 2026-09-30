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
