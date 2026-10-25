import { test, mock } from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";

// Load the real run pipeline (and the real API client under it) with only the
// browser-only packages stubbed; every request goes through the mocked fetch.
const src = new URL("../../", import.meta.url);
const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "sonner") return next("data:text/javascript,export const toast={error(){},success(){},info(){}}", context);
  if (specifier === "@sentry/nextjs") return next("data:text/javascript,export function captureException(){};export function captureMessage(){}", context);
  if (specifier.startsWith("@/")) return next(new URL(`${specifier.slice(2)}.ts`, src).href, context);
  if (/^\.\.?\//.test(specifier) && !/\.[a-z]+$/.test(specifier) && context.parentURL?.startsWith(src.href)) {
    return next(new URL(`${specifier}.ts`, context.parentURL).href, context);
  }
  return next(specifier, context);
} });
const { runVerification } = await import("./run.ts");
const conditions = await import("./service-conditions.ts");
hooks.deregister();

// The bug report's part: everything the API accepts, declared on the record.
const STORED_ENV = {
  corrosive: true,
  sour_service: true,
  min_temp_c: -20,
  max_temp_c: 120,
  pressure_bar: 350,
  medium: "sour gas (H2S)",
  standard: "NACE MR0175",
};

function storedContext(meshHash = "stored-mesh") {
  return {
    mesh_hash: meshHash,
    program: "Wellhead",
    parent_assembly: null,
    units_per_parent: null,
    annual_volume: null,
    provenance: "user" as const,
    service_environment: { ...STORED_ENV },
  };
}

interface Call { method: string; path: string; body: unknown }

function mockBackend(
  stored: ReturnType<typeof storedContext> | null,
  readFailure?: string,
  validationFailure = false
) {
  const calls: Call[] = [];
  const fetchMock = mock.method(globalThis, "fetch", async (url: unknown, init: RequestInit = {}) => {
    const path = new URL(String(url), "http://localhost").pathname;
    const method = init.method ?? "GET";
    calls.push({ method, path, body: typeof init.body === "string" ? JSON.parse(init.body) : null });
    if (path === "/api/proxy/validate" && validationFailure) {
      return Response.json({ detail: "Unsupported geometry" }, { status: 400 });
    }
    if (path === "/api/proxy/validate") return Response.json({ best_process: "fdm", process_scores: [], issues: [] });
    if (path === "/api/proxy/machine-inventory") return Response.json({ machines: [], next_cursor: null });
    if (path === "/api/proxy/validate/cost") return Response.json({ quantities: [1, 100] });
    if (path.startsWith("/api/proxy/part-context/") && method === "GET") {
      if (readFailure) return Response.json({ detail: readFailure }, { status: 503 });
      return stored
        ? Response.json(stored)
        : Response.json({ detail: "no declared context for part" }, { status: 404 });
    }
    if (path.startsWith("/api/proxy/part-context/") && method === "PUT") {
      const body = JSON.parse(String(init.body));
      return Response.json({ ...(stored ?? storedContext()), service_environment: body.service_environment ?? undefined });
    }
    throw new Error(`unexpected ${method} ${path}`);
  });
  return { calls, restore: () => fetchMock.mock.restore() };
}

const writes = (calls: Call[]) =>
  calls.filter((call) => call.path.startsWith("/api/proxy/part-context/") && call.method !== "GET");

test("a run and a re-run with no edits never write the part context", async () => {
  for (const stored of [storedContext(), null]) {
    const backend = mockBackend(stored);
    try {
      const file = new File(["solid part"], "bracket.stl");
      await runVerification({ file, materialClass: "steel" });
      await runVerification({ file: new File([file], file.name), materialClass: "steel" });
      assert.deepEqual(writes(backend.calls), []);
      // Both runs still read the record and were costed (the server applies it).
      assert.equal(backend.calls.filter((c) => c.path.startsWith("/api/proxy/part-context/")).length, 2);
      assert.equal(backend.calls.filter((c) => c.path === "/api/proxy/validate/cost").length, 2);
    } finally { backend.restore(); }
  }
});

test("Verify loads the part's stored conditions and shows every field", async () => {
  const backend = mockBackend(storedContext());
  try {
    const result = await runVerification({ file: new File(["solid part"], "bracket.stl"), materialClass: "steel" });
    assert.deepEqual(result.serviceEnvironment, STORED_ENV);
    assert.equal(result.envDeclared, true);
    assert.equal(result.envError, null);
    assert.deepEqual(conditions.draftFromServiceEnvironment(result.serviceEnvironment), {
      min_temp_c: "-20",
      max_temp_c: "120",
      pressure_bar: "350",
      corrosive: true,
      sour_service: true,
      medium: "sour gas (H2S)",
      standard: "NACE MR0175",
    });
    // Nothing changed since the run, so nothing is flagged as needing a re-verify.
    assert.equal(conditions.conditionsChangedSinceRun(result.serviceEnvironment, result.partContext), false);
  } finally { backend.restore(); }
});

test("a part with no record verifies at ambient and a failed read is reported, not guessed", async () => {
  for (const [readFailure, envError] of [[undefined, null], ["Context store unavailable", "Context store unavailable"]]) {
    const backend = mockBackend(null, readFailure ?? undefined);
    try {
      const result = await runVerification({ file: new File(["solid part"], "bracket.stl"), materialClass: "steel" });
      assert.deepEqual(result.serviceEnvironment, {});
      assert.equal(result.envDeclared, false);
      assert.equal(result.envError, envError);
      assert.deepEqual(writes(backend.calls), []);
    } finally { backend.restore(); }
  }
});

test("conditions set before verifying are saved only onto a record that has none", async () => {
  const declare = { max_temp_c: 120, sour_service: true, pressure_bar: 350 };

  // An empty record: the explicit pre-run declaration is saved, before costing.
  let backend = mockBackend(null);
  try {
    const result = await runVerification({ file: new File(["new part"], "new.stl"), materialClass: "polymer", declare });
    assert.deepEqual(writes(backend.calls).map((c) => c.body), [{ service_environment: declare }]);
    const at = (method: string, path: string) =>
      backend.calls.findIndex((c) => c.method === method && c.path === path);
    const put = backend.calls.findIndex((c) => c.method === "PUT");
    assert.ok(at("POST", "/api/proxy/validate") < put, "saved only after routing + DFM returned");
    assert.ok(put < at("POST", "/api/proxy/validate/cost"), "saved before the cost route reads it");
    assert.deepEqual(result.serviceEnvironment, declare);
    assert.deepEqual(result.declaredBeforeRun, { outcome: "saved", error: null });
  } finally { backend.restore(); }

  // A stored record wins: nothing is written over it, and the run says so.
  backend = mockBackend(storedContext());
  try {
    const result = await runVerification({ file: new File(["stored part"], "stored.stl"), materialClass: "polymer", declare });
    assert.deepEqual(writes(backend.calls), []);
    assert.deepEqual(result.serviceEnvironment, STORED_ENV);
    assert.deepEqual(result.declaredBeforeRun, { outcome: "kept_stored", error: null });
  } finally { backend.restore(); }

  // Routing + DFM did not return: nothing is persisted (QA ISSUE-001).
  backend = mockBackend(null, undefined, true);
  try {
    const result = await runVerification({ file: new File(["new part"], "new.stl"), materialClass: "polymer", declare });
    assert.deepEqual(writes(backend.calls), []);
    assert.equal(result.declaredBeforeRun, null);
  } finally { backend.restore(); }
});

test("the editor round-trips the stored set and validates like the API", () => {
  const draft = conditions.draftFromServiceEnvironment(STORED_ENV);
  assert.deepEqual(conditions.serviceEnvironmentFromDraft(draft), { env: STORED_ENV, errors: [] });
  assert.deepEqual(
    conditions.serviceEnvironmentFromDraft({ ...draft, min_temp_c: "200", pressure_bar: "-1", max_temp_c: "hot" }).errors,
    ["Max temperature must be a number.", "Pressure must be 0 bar or more."]
  );
  assert.deepEqual(
    conditions.serviceEnvironmentFromDraft({ ...draft, min_temp_c: "200" }).errors,
    ["Min temperature must not be above max temperature."]
  );
  // false / blank declare nothing, so a cleared editor is "no conditions".
  const cleared = conditions.serviceEnvironmentFromDraft(conditions.draftFromServiceEnvironment({}));
  assert.deepEqual(cleared, { env: {}, errors: [] });
  assert.equal(conditions.hasServiceConditions({ corrosive: false, medium: "  " }), false);
  assert.equal(conditions.sameServiceEnvironment({ corrosive: false, max_temp_c: 120 }, { max_temp_c: 120 }), true);
});

test("an explicit save sends the complete edited set, and clearing sends null", async () => {
  const backend = mockBackend(storedContext());
  try {
    const edited = { ...STORED_ENV, max_temp_c: 150 };
    const saved = await conditions.saveServiceConditions("stored-mesh", edited);
    assert.equal(saved.ok, true);
    assert.deepEqual(writes(backend.calls).map((c) => c.body), [{ service_environment: edited }]);
    assert.deepEqual(saved.context?.service_environment, edited);
    assert.equal(conditions.conditionsChangedSinceRun(STORED_ENV, saved.context), true);

    backend.calls.length = 0;
    const clearedSave = await conditions.saveServiceConditions("stored-mesh", { corrosive: false });
    assert.equal(clearedSave.ok, true);
    assert.deepEqual(writes(backend.calls).map((c) => c.body), [{ service_environment: null }]);
  } finally { backend.restore(); }
});

test("a failed save reports the server's reason and returns no record", async () => {
  const fetchMock = mock.method(globalThis, "fetch", async () =>
    Response.json({ detail: "insufficient role" }, { status: 403 }));
  try {
    const saved = await conditions.saveServiceConditions("stored-mesh", STORED_ENV);
    assert.deepEqual(saved, { ok: false, error: "insufficient role", context: null });
  } finally { fetchMock.mock.restore(); }
});
