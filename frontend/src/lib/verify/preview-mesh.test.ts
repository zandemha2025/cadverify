import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { mock, test } from "node:test";

const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "@/lib/api-base") return next(new URL("../api-base.ts", import.meta.url).href, context);
  return next(specifier, context);
} });
const { fetchPreviewMesh, fetchPreviewMeshOrBusy } = await import("./preview-mesh.ts");
hooks.deregister();

const ask = async (reply: () => Response | Promise<Response>) => {
  const fetchMock = mock.method(globalThis, "fetch", async () => reply());
  try {
    // A fresh File each time: the preview cache is per File.
    return {
      either: await fetchPreviewMeshOrBusy(new File(["solid x"], "part.stl"), { forAnalysis: true, units: "mm" }),
      plain: await fetchPreviewMesh(new File(["solid x"], "part.stl"), { forAnalysis: true, units: "mm" }),
    };
  } finally {
    fetchMock.mock.restore();
  }
};

test("the 3D preview tells ScaleCAD's side from a file it can't draw, and busy from both", async () => {
  // A gateway timeout, another 5xx, no answer: ScaleCAD's side, with its status.
  assert.deepEqual((await ask(() => new Response("Gateway Timeout", { status: 504 }))).either, { server: 504 });
  assert.deepEqual((await ask(() => new Response("Bad Gateway", { status: 502 }))).either, { server: 502 });
  assert.deepEqual((await ask(() => Response.json({ detail: "Service Unavailable" }, { status: 503 }))).either, { server: 503 });
  assert.deepEqual((await ask(() => { throw new TypeError("network down"); })).either, { server: 0 });
  // Busy: asked again by the caller.
  const busy = await ask(() => Response.json({ detail: { code: "server_busy", message: "server is at capacity, retry shortly" } }, { status: 429, headers: { "retry-after": "5" } }));
  assert.deepEqual(busy.either, { busy: { kind: "server", retryAfterS: 5 } });
  // A refusal of the file stays what it was: no preview.
  assert.equal((await ask(() => Response.json({ detail: "could not mesh" }, { status: 400 }))).either, null);
  // fetchPreviewMesh's other callers keep their contract: null for every failure.
  for (const reply of [() => new Response("x", { status: 504 }), () => Response.json({ detail: { code: "server_busy" } }, { status: 429 })]) {
    assert.equal((await ask(reply)).plain, null);
  }
});
