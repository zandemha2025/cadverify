import { test, mock } from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";

const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "@/lib/api-base") return next(new URL("../api-base.ts", import.meta.url).href, context);
  return next(specifier, context);
} });
const { listMachines } = await import("./machine-api.ts");
hooks.deregister();

test("inventory consumers receive every page and reject incomplete reads", async () => {
  const calls: string[] = [];
  let secondPage: Response;
  const fetchMock = mock.method(globalThis, "fetch", async (url: unknown) => {
    calls.push(String(url));
    return String(url).includes("cursor=") ? secondPage.clone()
      : Response.json({ machines: [{ id: "first" }], next_cursor: "next+/=" });
  });
  try {
    secondPage = Response.json({ machines: [{ id: "last" }], next_cursor: null });
    assert.deepEqual((await listMachines()).machines.map((m) => m.id), ["first", "last"]);
    assert.match(calls[1], /cursor=next%2B%2F%3D/);
    secondPage = Response.json({ detail: "Inventory unavailable" }, { status: 503 });
    await assert.rejects(listMachines(), /Inventory unavailable/);
    secondPage = Response.json({ machines: [], next_cursor: "next+/=" });
    await assert.rejects(listMachines(), /pagination/i);
  } finally { fetchMock.mock.restore(); }
});
