import assert from "node:assert/strict";

// A Verify run reads the part's stored context before costing and never writes
// over it (c485111a). For a part the organization has declared nothing about,
// GET /api/v1/part-context/{mesh_hash} answers 204 No Content: the documented
// "none declared" standing, not a failure — and, being a 2xx, not even a
// console error. (Before the audit fix it was a 404 with a body, which the
// browser logged; the 404 path remains only for org-less reads and keeps the
// old shape.)

export function isPartContextRead(response, meshHash) {
  return response.request().method() === "GET" &&
    new URL(response.url()).pathname === `/api/proxy/part-context/${meshHash}`;
}

export function assertNoDeclaredPartContext(status, body) {
  if (status === 204) {
    assert.equal(body, null);
    return;
  }
  assert.equal(status, 404);
  assert.equal(body?.code, "NOT_FOUND");
  assert.equal(body?.message, "no declared context for part");
}

export function isExpectedNoContextConsoleError(error, resourceUrl) {
  return error.sourceUrl === resourceUrl &&
    error.text === "Failed to load resource: the server responded with a status of 404 (Not Found)";
}

/**
 * Check the run's context read: a stored context (200) or the verified
 * "none declared" 204. A 204 needs no console-error bookkeeping (the browser
 * does not log 2xx); the legacy 404 shape still moves at most its one resource
 * error out of the failure set.
 */
export async function checkPartContextRead(response, { consoleErrors, expectedConsoleErrors, consoleStart }) {
  if (response.status() === 204) {
    return { status: 204, declared: false };
  }
  if (response.status() !== 404) {
    assert(response.ok(), `GET /part-context returned ${response.status()}`);
    return { status: response.status(), declared: true };
  }
  assertNoDeclaredPartContext(response.status(), await response.json().catch(() => null));
  const index = consoleErrors.findIndex((error, i) =>
    i >= consoleStart && isExpectedNoContextConsoleError(error, response.url()),
  );
  if (index >= 0) expectedConsoleErrors.push(...consoleErrors.splice(index, 1));
  return { status: response.status(), declared: false };
}
