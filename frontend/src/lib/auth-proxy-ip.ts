import { isIP } from "node:net";

export type AuthProxyClientIpSource = "auto" | "fly" | "nginx" | "cloudfront" | "render";

/** What these helpers read from a request: its headers (a Request, or next/headers in a server page). */
export type IncomingHeaders = { headers: { get(name: string): string | null } };

function validIp(raw: string | null): string | null {
  const candidate = (raw || "").trim();
  return isIP(candidate) ? candidate : null;
}

/** Parse CloudFront-Viewer-Address without ever accepting a forwarded chain. */
export function cloudFrontViewerIp(raw: string | null): string | null {
  const candidate = (raw || "").trim();
  if (!candidate || candidate.includes(",")) return null;

  const bracketed = candidate.match(/^\[([^\]]+)]:(\d{1,5})$/);
  if (bracketed) {
    const port = Number(bracketed[2]);
    const ip = validIp(bracketed[1]);
    return ip && port >= 1 && port <= 65535 ? ip : null;
  }

  // CloudFront documents this header as viewer-address:source-port, so require
  // the port rather than accepting a browser-supplied bare address. Splitting
  // at the final colon also handles an unbracketed IPv6 value whose complete
  // text can otherwise be mistaken for a valid IPv6 address (for example,
  // `2001:db8::42:443`).
  const separator = candidate.lastIndexOf(":");
  if (separator <= 0) return null;
  const portText = candidate.slice(separator + 1);
  if (!/^\d{1,5}$/.test(portText)) return null;
  const port = Number(portText);
  const ip = validIp(candidate.slice(0, separator));
  return ip && port >= 1 && port <= 65535 ? ip : null;
}

/**
 * Select only the header written by the deployment's protected ingress.
 *
 * `auto` exists for local development and old test harnesses. Released
 * environments must select one explicit source in startup validation so a
 * browser-supplied header for a different proxy can never win.
 */
export function requestClientIp(
  req: IncomingHeaders,
  source: string = "auto",
): string | null {
  switch (source.trim().toLowerCase() as AuthProxyClientIpSource) {
    case "fly":
      return validIp(req.headers.get("fly-client-ip"));
    case "nginx":
      return validIp(req.headers.get("x-real-ip"));
    case "cloudfront":
      return cloudFrontViewerIp(req.headers.get("cloudfront-viewer-address"));
    // Render's public web services sit behind Cloudflare, which writes
    // CF-Connecting-IP on every request and overwrites whatever the caller sent
    // (render.com/articles/host-pocketbase-on-render). Its X-Forwarded-For is
    // only appended to, so the leftmost entry is the caller's to choose.
    case "render":
      return validIp(req.headers.get("cf-connecting-ip"));
    case "auto":
      return (
        validIp(req.headers.get("fly-client-ip")) ||
        validIp(req.headers.get("x-real-ip")) ||
        cloudFrontViewerIp(req.headers.get("cloudfront-viewer-address"))
      );
    default:
      return null;
  }
}

/** The browser's User-Agent, forwarded on auth requests so a sign-in's audit
 *  row names the person's browser rather than this server's fetch client.
 *  Informational only (never authority); at most 500 characters. */
export function requestUserAgent(req: IncomingHeaders): Record<string, string> {
  const ua = (req.headers.get("user-agent") || "").trim().slice(0, 500);
  return ua ? { "user-agent": ua } : {};
}
