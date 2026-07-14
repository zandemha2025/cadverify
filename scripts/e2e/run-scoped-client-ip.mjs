import { createHash } from "node:crypto";
import { isIP } from "node:net";

/**
 * Return a stable RFC 3849 documentation address for one evidence run/scope.
 * A new run ID yields a new signup-rate-limit bucket without pretending that
 * production throttling is disabled.
 */
export function runScopedClientIp(runId, scope = "browser") {
  const run = String(runId || "").trim();
  const label = String(scope || "").trim();
  if (!run || !label) {
    throw new Error("runScopedClientIp requires non-empty runId and scope values");
  }
  const digest = createHash("sha256").update(`${run}:${label}`).digest("hex");
  return `2001:db8:${digest.slice(0, 4)}:${digest.slice(4, 8)}:${digest.slice(8, 12)}::${digest.slice(12, 16)}`;
}

export function configuredClientIp(runId, scope = "browser", env = process.env) {
  const explicit = String(env.E2E_CLIENT_IP || "").trim();
  if (!explicit) return runScopedClientIp(runId, scope);
  if (isIP(explicit) === 0) {
    throw new Error("E2E_CLIENT_IP must be one exact IPv4 or IPv6 address");
  }
  return explicit;
}
