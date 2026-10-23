import assert from "node:assert/strict";

// A Verify run reads the part's stored context before costing and never writes
// over it (c485111a). For a part the organization has declared nothing about,
// GET /api/v1/part-context/{mesh_hash} answers 404 "no declared context for
// part": the documented "none declared" state, not a failure. The browser still
// logs that 404 as a console error, so a runner may set aside exactly that one.

export function isPartContextRead(response, meshHash) {
  return response.request().method() === "GET" &&
    new URL(response.url()).pathname === `/api/proxy/part-context/${meshHash}`;
}

export function assertNoDeclaredPartContext(status, body) {
  assert.equal(status, 404);
  assert.equal(body?.code, "NOT_FOUND");
  assert.equal(body?.message, "no declared context for part");
}

export function isExpectedNoContextConsoleError(error, resourceUrl) {
  return error.sourceUrl === resourceUrl &&
    error.text === "Failed to load resource: the server responded with a status of 404 (Not Found)";
}

/**
 * Check the run's context read: a stored context (2xx) or the verified
 * "none declared" 404. For the 404, move at most its one resource error (logged
 * at or after `consoleStart`) from `consoleErrors` to `expectedConsoleErrors`;
 * every other endpoint, status and runtime error stays a failure.
 */
export async function checkPartContextRead(response, { consoleErrors, expectedConsoleErrors, consoleStart }) {
  if (response.status() !== 404) {
    assert(response.ok(), `GET /part-context returned ${response.status()}`);
    return { status: response.status(), declared: true };
  }
  assertNoDeclaredPartContext(response.status(), await response.json());
  const index = consoleErrors.findIndex((error, i) =>
    i >= consoleStart && isExpectedNoContextConsoleError(error, response.url()),
  );
  if (index >= 0) expectedConsoleErrors.push(...consoleErrors.splice(index, 1));
  return { status: response.status(), declared: false };
}
