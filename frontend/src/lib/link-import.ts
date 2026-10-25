/**
 * Import a part from a share link: what the browser can say about a pasted
 * link before it is sent (POST /api/v1/uploads/from-link). The server applies
 * the real rules (backend `src/services/link_import.py`) and fetches the file
 * on the worker; nothing is downloaded to this browser. These helpers only
 * name the source and catch what is plainly not a share link, so the field
 * answers at once. Pure: no React, no fetch (link-import.test.ts).
 */

export type LinkProvider = "google_drive" | "dropbox" | "onedrive" | "sharepoint" | "s3";

export const LINK_LABEL: Record<LinkProvider, string> = {
  google_drive: "Google Drive",
  dropbox: "Dropbox",
  onedrive: "OneDrive",
  sharepoint: "SharePoint",
  s3: "Amazon S3",
};

/** The server's own words for an unknown host (link_import.NOT_SUPPORTED). */
export const LINK_NOT_SUPPORTED = "Paste a share link from Google Drive, Dropbox, OneDrive or SharePoint, or an S3 presigned URL.";

const CAD = /\.(step|stp|stl|iges|igs)(\.gz)?$|\.zip$/i;

export type LinkRead =
  | { ok: true; provider: LinkProvider; label: string; nameHint: string | null }
  | { ok: false; message: string };

function providerOf(host: string): LinkProvider | null {
  const h = host.toLowerCase();
  if (h === "drive.google.com" || h === "docs.google.com") return "google_drive";
  if (h === "www.dropbox.com" || h === "dropbox.com") return "dropbox";
  if (h === "1drv.ms" || h === "onedrive.live.com") return "onedrive";
  if (/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.sharepoint\.com$/.test(h)) return "sharepoint";
  if (/(^|\.)s3(?:[.-][a-z0-9-]+)*\.amazonaws\.com$/.test(h)) return "s3";
  return null;
}

/** What a pasted link is, or why it can't be imported, before it is sent. */
export function readLink(raw: string): LinkRead {
  const text = raw.trim();
  if (!text) return { ok: false, message: "Paste the file's share link." };
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return { ok: false, message: "Paste the share link as copied, starting with https://." };
  }
  if (url.protocol !== "https:") return { ok: false, message: "Only https:// links can be imported." };
  if (url.username || url.password) return { ok: false, message: "Paste the link without a user name or password in it." };
  if (url.port && url.port !== "443") return { ok: false, message: "Only links on the standard https port can be imported." };
  const provider = providerOf(url.hostname);
  if (!provider) return { ok: false, message: LINK_NOT_SUPPORTED };
  return { ok: true, provider, label: LINK_LABEL[provider], nameHint: nameHint(url, provider) };
}

/** The file's name when the link carries it (Dropbox, S3, a SharePoint path), else null. */
function nameHint(url: URL, provider: LinkProvider): string | null {
  if (provider === "google_drive" || provider === "onedrive") return null;
  if (provider === "sharepoint" && url.pathname.startsWith("/:")) return null;
  const seg = url.pathname.replace(/\/+$/, "").split("/").pop() ?? "";
  let name: string;
  try {
    name = decodeURIComponent(seg);
  } catch {
    return null;
  }
  return CAD.test(name) && name.length <= 255 && !/[\u0000-\u001f\\/]/.test(name) ? name : null;
}

/** A name typed with the link must be a CAD file's name (the server checks it again). */
export function linkNameProblem(name: string): string | null {
  const n = name.trim();
  if (!n) return null;
  if (n.length > 255 || /[\u0000-\u001f\\/]/.test(n) || !CAD.test(n)) {
    return "Name the file as a STEP, IGES or STL file (or a .zip or .gz of one), for example bracket.step.";
  }
  return null;
}

/** The title a link check's failure shows, by the server's code. */
export const LINK_FAILURE_TITLE: Record<string, string> = {
  LINK_NEEDS_SIGN_IN: "The link needs sign-in",
  LINK_IS_A_PAGE: "The link opens a page, not a file",
  LINK_NOT_FOUND: "No file at that link",
  LINK_TOO_LARGE: "Too large to import",
  LINK_EMPTY: "The link gave an empty file",
  LINK_UNKNOWN_TYPE: "Not named as a CAD file",
  LINK_ENCODED: "The file came compressed in transit",
  LINK_TIMEOUT: "The download was too slow",
  LINK_CONNECT_FAILED: "Couldn’t connect to the link’s server",
  LINK_PROVIDER_ERROR: "The provider answered with an error",
  LINK_RATE_LIMITED: "The provider is limiting downloads",
  LINK_FETCH_FAILED: "The download stopped",
  LINK_REDIRECT_REFUSED: "The link went somewhere ScaleCAD doesn’t fetch from",
  LINK_TOO_MANY_REDIRECTS: "The link redirected too many times",
  LINK_ADDRESS_REFUSED: "The link’s server isn’t a public address",
  LINK_IMPORT_OFF: "Import from a link is off",
  LINK_UNREADABLE: "The link couldn’t be read back",
  LINK_DISK: "The worker couldn’t store the file",
};
