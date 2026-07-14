import { isIP } from "node:net";

export type AuthProxyClientIpSource = "auto" | "fly" | "nginx" | "cloudfront";

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
  req: Pick<Request, "headers">,
  source: string = "auto",
): string | null {
  switch (source.trim().toLowerCase() as AuthProxyClientIpSource) {
    case "fly":
      return validIp(req.headers.get("fly-client-ip"));
    case "nginx":
      return validIp(req.headers.get("x-real-ip"));
    case "cloudfront":
      return cloudFrontViewerIp(req.headers.get("cloudfront-viewer-address"));
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
