import { test, mock } from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";

const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "@/lib/api-base") return next(new URL("../api-base.ts", import.meta.url).href, context);
  return next(specifier, context);
} });
const { countMachines, envelopeSummary, listMachines } = await import("./machine-api.ts");
hooks.deregister();

test("inventory totals include declared quantities and the service's count default", () => {
  assert.equal(countMachines([{ count: 2 }, { count: null }, { count: 1 }, { count: 2 }]), 6);
  assert.equal(countMachines([{ count: 2 }, { count: 1 }]), 3);
  assert.equal(countMachines([]), 0);
});

test("lathe envelope is read from the same keys the API stores and the engine reads", () => {
  const lathe = (capabilities: Record<string, unknown>) =>
    envelopeSummary({ capabilities } as Parameters<typeof envelopeSummary>[0]);
  assert.equal(lathe({ swing_dia: 254, between_centers: 533 }), "Ø254 × 533 mm swing");
  assert.equal(lathe({ between_centers: 533 }), "Ø? × 533 mm swing");
  // The API rejects swing_dia_mm, so showing it would describe an envelope the
  // engine never evaluates.
  assert.equal(lathe({ swing_dia_mm: 254 }), null);
});

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
