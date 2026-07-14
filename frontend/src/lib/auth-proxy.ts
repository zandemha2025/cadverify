/** Server-only authenticated client-IP forwarding for public auth routes. */
import "server-only";

import { createHmac } from "node:crypto";

import { requestClientIp } from "./auth-proxy-ip";

const CLIENT_IP_HEADER = "x-cadverify-client-ip";
const TIMESTAMP_HEADER = "x-cadverify-proxy-timestamp";
const SIGNATURE_HEADER = "x-cadverify-proxy-signature";

function proxySecret(): Buffer | null {
  const raw = (process.env.AUTH_PROXY_SECRET || "").trim();
  if (!raw) return null;
  // Match Python's base64.b64decode(..., validate=True). Buffer.from silently
  // ignores malformed characters, which could make the two services derive
  // different keys and turn a deploy typo into a broken auth boundary.
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(raw)) {
    throw new Error("AUTH_PROXY_SECRET must be canonical base64");
  }
  const decoded = Buffer.from(raw, "base64");
  if (decoded.toString("base64") !== raw) {
    throw new Error("AUTH_PROXY_SECRET must be canonical base64");
  }
  if (decoded.length < 32) {
    throw new Error("AUTH_PROXY_SECRET must decode to at least 32 bytes");
  }
  return decoded;
}

export function signedAuthProxyHeaders(
  req: Request,
  backendPath: string,
): Record<string, string> {
  const secret = proxySecret();
  const ip = requestClientIp(
    req,
    process.env.AUTH_PROXY_CLIENT_IP_SOURCE || "auto",
  );
  // Local development intentionally works without the production-only shared
  // secret. Production startup and promotion gates require it and prove the
  // signed handshake end to end.
  if (!secret || !ip) return {};
  if (!backendPath.startsWith("/")) {
    throw new Error("Auth proxy backend path must be absolute");
  }
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const payload = `${timestamp}\n${req.method.toUpperCase()}\n${backendPath}\n${ip}`;
  const signature = createHmac("sha256", secret)
    .update(payload)
    .digest("base64url");
  return {
    [CLIENT_IP_HEADER]: ip,
    [TIMESTAMP_HEADER]: timestamp,
    [SIGNATURE_HEADER]: signature,
  };
}
