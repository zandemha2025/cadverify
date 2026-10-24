/**
 * Release-evidence fault headers the data proxy may pass to the API.
 *
 * Local release-evidence runs select a record-scoped fault with these headers
 * (the API honours them only with its own E2E token). In a release (RELEASE set
 * to a non-dev value) the proxy forwards neither, whatever the browser sends.
 * Pure: no React, no fetch.
 */
const DEV_RELEASES = new Set(["", "dev", "development", "local", "test", "ci"]);

export const E2E_FAULT_HEADERS = ["x-proofshape-e2e-token", "x-proofshape-e2e-fault"] as const;

/** Whether this process runs a release: RELEASE names a deployment. */
export function isReleased(release: string | undefined = process.env.RELEASE): boolean {
  return !DEV_RELEASES.has((release || "dev").trim().toLowerCase());
}

/** The fault headers to forward from `incoming`; none in a release. */
export function e2eFaultHeaders(
  incoming: { get(name: string): string | null },
  release: string | undefined = process.env.RELEASE,
): Record<string, string> {
  if (isReleased(release)) return {};
  const out: Record<string, string> = {};
  for (const name of E2E_FAULT_HEADERS) {
    const value = incoming.get(name);
    if (value) out[name] = value;
  }
  return out;
}
