import { test, mock } from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";

const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "@/lib/api-base") return next(new URL("../api-base.ts", import.meta.url).href, context);
  if (specifier === "./program-rollup") return next(new URL("./program-rollup.ts", import.meta.url).href, context);
  return next(specifier, context);
} });
const { assignContext } = await import("./program-api.ts");
const { declarePartProgram } = await import("./programs-api.ts");
hooks.deregister();

test("program edits send only the requested fields, without a fallible read/merge", async () => {
  const calls: { method?: string; body: unknown }[] = [];
  const fetchMock = mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    calls.push({ method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : null });
    return init?.method === "PUT"
      ? Response.json({ program: "New", annual_volume: 50 })
      : Response.json({ detail: "Read unavailable" }, { status: 503 });
  });
  try {
    for (const write of [assignContext, declarePartProgram]) {
      calls.length = 0;
      await write("mesh", { program: "New" });
      assert.deepEqual(calls, [{ method: "PUT", body: { program: "New" } }]);
      calls.length = 0;
      await write("mesh", { annual_volume: null });
      assert.deepEqual(calls, [{ method: "PUT", body: { annual_volume: null } }]);
    }
  } finally { fetchMock.mock.restore(); }
});
