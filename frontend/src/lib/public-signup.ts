const TRUTHY = new Set(["1", "true", "yes", "on"]);
const DEV_RELEASES = new Set(["", "dev", "development", "local", "test", "ci"]);

/** Keep the signup surface aligned with the API's environment-boolean parser. */
export function publicPasswordSignupEnabled(
  rawOverride: string | undefined,
  rawRelease: string | undefined,
): boolean {
  const release = (rawRelease || "dev").trim().toLowerCase();
  const released = !DEV_RELEASES.has(release);
  const override = rawOverride?.trim().toLowerCase();
  if (!override) return !released;
  return TRUTHY.has(override);
}
