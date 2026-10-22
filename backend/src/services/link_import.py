"""Import a part from a share link: which links are taken, and the guarded fetch.

``POST /api/v1/uploads/from-link`` takes a share link to one CAD file (Google
Drive, Dropbox, OneDrive or SharePoint, an Amazon S3 object URL). The web
request only reads the link: it applies the rules below, rewrites it to the
provider's download address, keeps the full link sealed on the check's job
(the query of a share or presigned link is a secret) and reserves the
organization's upload admission like a direct upload (a ``direct_uploads`` row,
purpose ``link``). The worker fetches the bytes (stage ``fetching``) and the
check continues as a big file's does (``src.jobs.stored_check_tasks``).

Rules for every address requested, the pasted link and each redirect alike:

* HTTPS on port 443 only; no user name or password in the URL.
* The host is on the provider's allowlist (an allowlist, not a blocklist);
  a redirect stays within the same provider's hosts.
* The host is resolved once and every address must be publicly routable
  (``url_guard.resolve_public_host``: not private, loopback, link-local,
  CGNAT, multicast, unspecified, reserved or a cloud metadata address); the
  connection goes to that exact address with SNI and Host set to the name,
  so DNS can't change between the check and the connect.
* At most ``MAX_REDIRECTS`` redirects; a Google Drive download's virus-scan
  page is followed once through its confirm form.
* No cookies are kept or sent, no ScaleCAD credential or Authorization header,
  a fixed User-Agent, ``Accept-Encoding: identity`` (the cap counts the real
  bytes; a compressed transfer is refused).
* ``Content-Length`` over the cap is refused before the body is read; without
  one the stream is cut at the cap. 10 s to connect, 30 s between bytes, and a
  total budget by size.
* A page (HTML) instead of a file is refused.
* Logs, errors and stored records carry the host (and, stored, the path),
  never the query string.

``LINK_IMPORT_ENABLED`` turns it on (default on); a deployment with the
regulated boundary (``PRODUCTION_REGULATED_BOUNDARY_REQUIRED``) never runs it.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import parse_qsl, unquote, urlencode, urljoin

import httpx

from src.services.url_guard import UnsafeURLError, resolve_public_host

logger = logging.getLogger("cadverify.link_import")

USER_AGENT = "ScaleCAD-LinkImport/1.0"
MAX_URL_LENGTH = 4096
MAX_REDIRECTS = 3
CONNECT_TIMEOUT_SEC = 10.0
READ_TIMEOUT_SEC = 30.0
# Total budget: a base plus one second per MiB (at least 1 MiB/s), capped.
TOTAL_BASE_SEC = 60.0
TOTAL_SEC_PER_MIB = 1.0
TOTAL_CAP_SEC = 1800.0
CHUNK_BYTES = 1024 * 1024
# An HTML page read to find Google Drive's confirm form, at most.
MAX_PAGE_BYTES = 512 * 1024
SEALED_PREFIX = "fernet:v1:"

PROVIDER_LABELS = {
    "google_drive": "Google Drive",
    "dropbox": "Dropbox",
    "onedrive": "OneDrive",
    "sharepoint": "SharePoint",
    "s3": "Amazon S3",
}
NOT_SUPPORTED = "Paste a share link from Google Drive, Dropbox, OneDrive or SharePoint, or an S3 presigned URL."


class LinkRefused(ValueError):
    """A link the rules don't take (the request answers 422 with this)."""

    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class LinkFetchError(Exception):
    """The fetch stopped; ``message`` is fixed text that never holds the URL."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_TRUTHY = {"1", "true", "yes", "on"}


def link_import_enabled() -> bool:
    """On unless ``LINK_IMPORT_ENABLED`` is off; never on the regulated plane."""
    if os.getenv("PRODUCTION_REGULATED_BOUNDARY_REQUIRED", "0").strip().lower() in _TRUTHY:
        return False
    return os.getenv("LINK_IMPORT_ENABLED", "1").strip().lower() in _TRUTHY


def own_buckets() -> set[str]:
    """ScaleCAD's own S3 buckets, which a link may never read from."""
    names = {os.getenv("OBJECT_STORE_S3_BUCKET", ""), os.getenv("DIRECT_UPLOAD_S3_BUCKET", "")}
    names.update(os.getenv("LINK_IMPORT_REFUSED_S3_BUCKETS", "").split(","))
    return {n.strip().lower() for n in names if n and n.strip()}


# ---------------------------------------------------------------------------
# The URL rules (pure: no DNS, no network)
# ---------------------------------------------------------------------------

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_REGION = r"[a-z]{2}(?:-[a-z]+)+-\d{1,2}"
_BUCKET = r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"
_S3_ENDPOINT = rf"s3(?:[.-]{_REGION}|\.dualstack\.{_REGION})?\.amazonaws\.com"
_S3_VIRTUAL = re.compile(rf"^(?P<bucket>{_BUCKET})\.{_S3_ENDPOINT}$")
_S3_PATH = re.compile(rf"^{_S3_ENDPOINT}$")
_SHAREPOINT = re.compile(rf"^(?P<tenant>{_LABEL})\.sharepoint\.com$")

_HOSTS: dict[str, tuple[re.Pattern[str], ...]] = {
    # Where each provider's download may go (its own hosts and content hosts).
    "google_drive": (
        re.compile(r"^drive\.google\.com$"),
        re.compile(r"^docs\.google\.com$"),
        re.compile(r"^drive\.usercontent\.google\.com$"),
        re.compile(rf"^{_LABEL}\.googleusercontent\.com$"),
    ),
    "dropbox": (
        re.compile(r"^(?:www\.)?dropbox\.com$"),
        re.compile(r"^dl\.dropboxusercontent\.com$"),
        re.compile(rf"^{_LABEL}\.dl\.dropboxusercontent\.com$"),
    ),
    "onedrive": (
        re.compile(r"^api\.onedrive\.com$"),
        re.compile(r"^onedrive\.live\.com$"),
        re.compile(rf"^(?:{_LABEL}\.)+files\.1drv\.com$"),
        re.compile(rf"^(?:{_LABEL}\.)+livefilestore\.com$"),
        re.compile(rf"^(?:{_LABEL}\.)+microsoftpersonalcontent\.com$"),
    ),
}
# Sign-in pages a private link redirects to: named in the refusal, never fetched.
_SIGN_IN_HOSTS = frozenset({"accounts.google.com", "login.live.com", "login.microsoftonline.com"})

_DRIVE_ID = r"[A-Za-z0-9_-]{10,200}"


@dataclass(frozen=True)
class LinkPlan:
    """What a pasted link becomes: its provider and the address the worker requests first."""

    provider: str
    fetch_url: str
    host: str
    path: str
    filename_hint: Optional[str] = None
    # S3: the bucket; SharePoint: the tenant. Redirects stay within it.
    scope: Optional[str] = None

    @property
    def label(self) -> str:
        return PROVIDER_LABELS[self.provider]

    def public(self) -> dict[str, str]:
        """What may be shown and stored: provider, label, host (never the query)."""
        return {"provider": self.provider, "label": self.label, "host": self.host}


def _parse(raw: str) -> httpx.URL:
    """The shared rules: https, port 443, no user info, a host name; the fragment dropped."""
    if not isinstance(raw, str):
        raise LinkRefused("LINK_INVALID", "Paste the share link as copied, starting with https://.")
    raw = raw.strip()
    if (not raw or len(raw) > MAX_URL_LENGTH or "\\" in raw
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw)):
        raise LinkRefused("LINK_INVALID", "Paste the share link as copied, starting with https://.")
    try:
        url = httpx.URL(raw)
    except (httpx.InvalidURL, ValueError, TypeError, UnicodeError):
        raise LinkRefused("LINK_INVALID", "Paste the share link as copied, starting with https://.") from None
    if url.scheme != "https":
        raise LinkRefused("LINK_NOT_HTTPS", "Only https:// links can be imported.")
    if url.userinfo:
        raise LinkRefused("LINK_USERINFO", "Paste the link without a user name or password in it.")
    if url.port not in (None, 443):
        raise LinkRefused("LINK_PORT", "Only links on the standard https port can be imported.")
    try:
        host = url.raw_host.decode("ascii").lower()
    except UnicodeDecodeError:
        raise LinkRefused("LINK_NOT_SUPPORTED", NOT_SUPPORTED) from None
    if not host:
        raise LinkRefused("LINK_INVALID", "Paste the share link as copied, starting with https://.")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise LinkRefused("LINK_NOT_SUPPORTED", NOT_SUPPORTED)
    return url.copy_with(fragment=None)


def _host(url: httpx.URL) -> str:
    return url.raw_host.decode("ascii").lower()


def _query(url: httpx.URL) -> list[tuple[str, str]]:
    return parse_qsl(url.query.decode("ascii", "replace"), keep_blank_values=True)


def _with_query(url: httpx.URL, pairs: list[tuple[str, str]]) -> httpx.URL:
    return url.copy_with(query=urlencode(pairs).encode("ascii") if pairs else None)


def _last_segment(path: str) -> Optional[str]:
    seg = unquote(path.rstrip("/").rsplit("/", 1)[-1]) if path else ""
    return safe_filename(seg)


def safe_filename(name: Optional[str]) -> Optional[str]:
    """A plain basename (no path, no control characters, at most 255 characters), else None."""
    if not name:
        return None
    name = name.strip().strip('"').strip()
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    if (not name or name in {".", ".."} or len(name) > 255
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        return None
    return name


def _plan_drive(url: httpx.URL) -> LinkPlan:
    path = url.path
    pairs = dict(_query(url))
    if re.match(r"^/drive/(?:u/\d+/)?folders/", path):
        raise LinkRefused("LINK_FOLDER", "That's a link to a folder. Share one file and paste its link.")
    m = re.match(rf"^/file/(?:u/\d+/)?d/({_DRIVE_ID})(?:/|$)", path)
    file_id = m.group(1) if m else None
    if file_id is None and path in ("/open", "/uc", "/u/0/uc"):
        candidate = pairs.get("id", "")
        file_id = candidate if re.fullmatch(_DRIVE_ID, candidate) else None
    if file_id is None:
        raise LinkRefused(
            "LINK_NOT_A_FILE_LINK",
            "That Google Drive link doesn't point at one file. In Drive, choose Share, then Copy link, and paste that.",
        )
    query = [("id", file_id), ("export", "download")]
    if pairs.get("resourcekey"):
        query.append(("resourcekey", pairs["resourcekey"]))
    fetch = httpx.URL("https://drive.usercontent.google.com/download").copy_with(query=urlencode(query).encode("ascii"))
    return LinkPlan("google_drive", str(fetch), _host(url), path)


def _plan_dropbox(url: httpx.URL) -> LinkPlan:
    path = url.path
    if re.match(r"^/(?:sh|scl/fo)/", path):
        raise LinkRefused("LINK_FOLDER", "That's a link to a folder. Share one file and paste its link.")
    if not re.match(r"^/(?:s|scl/fi)/[^/]+/[^/]+", path):
        raise LinkRefused(
            "LINK_NOT_A_FILE_LINK",
            "That Dropbox link doesn't point at one file. In Dropbox, choose Share, then Copy link, and paste that.",
        )
    pairs = [(k, v) for k, v in _query(url) if k not in ("dl", "raw")] + [("dl", "1")]
    fetch = _with_query(url.copy_with(host="www.dropbox.com"), pairs)
    return LinkPlan("dropbox", str(fetch), _host(url), path, filename_hint=_last_segment(path))


def _plan_onedrive(url: httpx.URL) -> LinkPlan:
    host, path = _host(url), url.path
    if host == "1drv.ms":
        if path.startswith("/f/"):
            raise LinkRefused("LINK_FOLDER", "That's a link to a folder. Share one file and paste its link.")
        if not re.match(r"^/[a-z]/", path):
            raise LinkRefused("LINK_NOT_A_FILE_LINK", "That OneDrive link doesn't point at one file. Copy the file's share link and paste that.")
    elif not dict(_query(url)).get("resid") and not path.startswith("/redir"):
        raise LinkRefused("LINK_NOT_A_FILE_LINK", "That OneDrive link doesn't point at one file. Copy the file's share link and paste that.")
    # The OneDrive shares API: "u!" + the share link, base64url without padding.
    token = base64.urlsafe_b64encode(str(url).encode("utf-8")).decode("ascii").rstrip("=")
    fetch = f"https://api.onedrive.com/v1.0/shares/u!{token}/root/content"
    return LinkPlan("onedrive", fetch, host, path)


def _plan_sharepoint(url: httpx.URL, tenant: str) -> LinkPlan:
    path = url.path
    if path.startswith("/:f:/"):
        raise LinkRefused("LINK_FOLDER", "That's a link to a folder. Share one file and paste its link.")
    if not re.match(r"^/(?::[a-z]:/|personal/|sites/|teams/)", path):
        raise LinkRefused("LINK_NOT_A_FILE_LINK", "That SharePoint link doesn't point at one file. Copy the file's share link and paste that.")
    pairs = [(k, v) for k, v in _query(url) if k != "download"] + [("download", "1")]
    hint = None if path.startswith("/:") else _last_segment(path)
    return LinkPlan("sharepoint", str(_with_query(url, pairs)), _host(url), path, filename_hint=hint,
                    scope=tenant.removesuffix("-my"))


def _plan_s3(url: httpx.URL) -> LinkPlan:
    host, path = _host(url), url.path
    virtual = _S3_VIRTUAL.match(host)
    if virtual:
        bucket, key = virtual.group("bucket"), path.lstrip("/")
    else:
        parts = path.lstrip("/").split("/", 1)
        bucket, key = parts[0], (parts[1] if len(parts) > 1 else "")
    if not re.fullmatch(_BUCKET, bucket or "") or not key:
        raise LinkRefused("LINK_NOT_A_FILE_LINK", "That S3 link doesn't point at one object. Paste the object's presigned URL.")
    if bucket.lower() in own_buckets():
        raise LinkRefused("LINK_OWN_STORAGE", "That link points at ScaleCAD's own storage, which links can't read from.")
    return LinkPlan("s3", str(url), host, path, filename_hint=_last_segment(key), scope=bucket.lower())


def plan_link(raw: str) -> LinkPlan:
    """The provider and first download address of a pasted link, or LinkRefused."""
    url = _parse(raw)
    host = _host(url)
    if host in ("drive.google.com", "docs.google.com"):
        return _plan_drive(url)
    if host in ("www.dropbox.com", "dropbox.com"):
        return _plan_dropbox(url)
    if host in ("1drv.ms", "onedrive.live.com"):
        return _plan_onedrive(url)
    sp = _SHAREPOINT.match(host)
    if sp:
        return _plan_sharepoint(url, sp.group("tenant"))
    if _S3_VIRTUAL.match(host) or _S3_PATH.match(host):
        return _plan_s3(url)
    raise LinkRefused("LINK_NOT_SUPPORTED", NOT_SUPPORTED)


def host_allowed(plan: LinkPlan, url: httpx.URL) -> bool:
    """Whether an address (a redirect's target) is within the plan's provider."""
    host = _host(url)
    if plan.provider == "s3":
        virtual = _S3_VIRTUAL.match(host)
        if virtual:
            return virtual.group("bucket") == plan.scope
        if _S3_PATH.match(host):
            return url.path.lstrip("/").split("/", 1)[0].lower() == plan.scope
        return False
    if plan.provider == "sharepoint":
        sp = _SHAREPOINT.match(host)
        return bool(sp) and sp.group("tenant").removesuffix("-my") == plan.scope
    return any(p.match(host) for p in _HOSTS.get(plan.provider, ()))


def check_target(plan: LinkPlan, raw: str, base: Optional[httpx.URL] = None) -> httpx.URL:
    """A redirect or form target: the shared rules and the provider's hosts, else LinkFetchError."""
    try:
        joined = urljoin(str(base), raw) if base is not None else raw
        url = _parse(joined)
    except (LinkRefused, ValueError):
        raise LinkFetchError("LINK_REDIRECT_REFUSED", "The link redirected to an address ScaleCAD doesn't fetch from.") from None
    if _host(url) in _SIGN_IN_HOSTS or (plan.provider == "dropbox" and url.path.startswith("/login")):
        raise LinkFetchError("LINK_NEEDS_SIGN_IN", _sign_in_message(plan))
    if not host_allowed(plan, url):
        raise LinkFetchError("LINK_REDIRECT_REFUSED", "The link redirected to an address ScaleCAD doesn't fetch from.")
    return url


def _sign_in_message(plan: LinkPlan) -> str:
    if plan.provider == "s3":
        return "That S3 link was refused. Presigned links expire; make a new one and paste it."
    return (
        f"That {plan.label} link needs sign-in. Share the file so anyone with the link can view it, "
        "or download it and upload the file."
    )


# ---------------------------------------------------------------------------
# Sealing the link for the worker (the query is a secret)
# ---------------------------------------------------------------------------

def seal_url(url: str) -> str:
    from src.services.connector_credentials_service import _fernet

    return SEALED_PREFIX + _fernet().encrypt(url.encode("utf-8")).decode("ascii")


def open_sealed_url(sealed: str) -> str:
    from cryptography.fernet import InvalidToken

    from src.services.connector_credentials_service import _fernet

    if not isinstance(sealed, str) or not sealed.startswith(SEALED_PREFIX):
        raise LinkFetchError("LINK_UNREADABLE", "The link couldn't be read back on the worker. Paste it again.")
    try:
        return _fernet().decrypt(sealed[len(SEALED_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, RuntimeError, UnicodeError, ValueError):
        raise LinkFetchError("LINK_UNREADABLE", "The link couldn't be read back on the worker. Paste it again.") from None


# ---------------------------------------------------------------------------
# The fetch
# ---------------------------------------------------------------------------

Resolver = Callable[[str], list[str]]


@dataclass
class Fetched:
    path: str
    size: int
    sha256: str
    # The name the server gave (Content-Disposition), else the last path segment.
    filename: Optional[str]
    final_host: str


def _resolve_pinned(host: str, resolve: Resolver) -> list[str]:
    try:
        addresses = resolve(host)
    except UnsafeURLError:
        raise LinkFetchError(
            "LINK_ADDRESS_REFUSED", "The link's server resolved to an address ScaleCAD doesn't fetch from."
        ) from None
    except Exception:
        raise LinkFetchError("LINK_CONNECT_FAILED", "ScaleCAD couldn't reach the link's server.") from None
    out: list[str] = []
    for a in addresses:
        try:
            ip = ipaddress.ip_address(str(a).split("%", 1)[0])
        except ValueError:
            continue
        mapped = getattr(ip, "ipv4_mapped", None)
        # Belt and braces over url_guard: only globally routable addresses.
        if not (mapped or ip).is_global or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local):
            raise LinkFetchError(
                "LINK_ADDRESS_REFUSED", "The link's server resolved to an address ScaleCAD doesn't fetch from."
            )
        out.append(str(ip))
    if not out:
        raise LinkFetchError("LINK_CONNECT_FAILED", "ScaleCAD couldn't reach the link's server.")
    return out


class _FormFinder(HTMLParser):
    """Google Drive's virus-scan page: the download form's action and hidden fields."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[tuple[str, list[tuple[str, str]]]] = []
        self._current: Optional[tuple[str, list[tuple[str, str]]]] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "form":
            self._current = (a.get("action", ""), [])
            self.forms.append(self._current)
        elif tag == "input" and self._current is not None and a.get("name"):
            if a.get("type", "text").lower() in ("hidden", "text"):
                self._current[1].append((a["name"], a.get("value", "")))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._current = None


def drive_confirm_target(page: bytes, base: httpx.URL) -> Optional[str]:
    """The confirm URL from Drive's virus-scan page (its download form), else None."""
    finder = _FormFinder()
    try:
        finder.feed(page.decode("utf-8", "replace"))
    except Exception:
        return None
    for action, fields in finder.forms:
        names = {k for k, _ in fields}
        if "id" in names and action:
            target = urljoin(str(base), action)
            return target.split("?", 1)[0] + "?" + urlencode(fields)
    return None


def disposition_filename(value: Optional[str]) -> Optional[str]:
    """The file name in a Content-Disposition header (RFC 6266 ``filename*`` first)."""
    if not value:
        return None
    m = re.search(r"filename\*\s*=\s*([A-Za-z0-9_-]+)'[^']*'([^;]+)", value)
    if m:
        try:
            return safe_filename(unquote(m.group(2).strip(), encoding=m.group(1), errors="strict"))
        except (LookupError, UnicodeDecodeError):
            pass
    m = re.search(r'filename\s*=\s*"((?:[^"\\]|\\.)*)"', value) or re.search(r"filename\s*=\s*([^;]+)", value)
    return safe_filename(m.group(1).replace('\\"', '"')) if m else None


_HTML_STARTS = (b"<!doctype html", b"<html", b"<head", b"<body")


def _looks_like_html(head: bytes) -> bool:
    return head.lstrip()[:32].lower().startswith(_HTML_STARTS)


def _status_error(plan: LinkPlan, status: int) -> LinkFetchError:
    if status in (401, 403):
        return LinkFetchError("LINK_NEEDS_SIGN_IN", _sign_in_message(plan))
    if status in (404, 410):
        return LinkFetchError(
            "LINK_NOT_FOUND", f"{plan.label} has no file at that link. It may have been moved, deleted or unshared."
        )
    if status == 429:
        return LinkFetchError("LINK_RATE_LIMITED", f"{plan.label} is limiting downloads of this file right now. Try again later.")
    if status >= 500:
        return LinkFetchError("LINK_PROVIDER_ERROR", f"{plan.label} answered with an error (HTTP {status}). Try again later.")
    return LinkFetchError("LINK_FETCH_FAILED", f"{plan.label} didn't send the file (HTTP {status}).")


def total_budget_sec(size: Optional[int], max_bytes: int) -> float:
    basis = size if size is not None else max_bytes
    return min(TOTAL_CAP_SEC, TOTAL_BASE_SEC + TOTAL_SEC_PER_MIB * basis / 1024**2)


async def _send_pinned(client: httpx.AsyncClient, url: httpx.URL, resolve: Resolver) -> httpx.Response:
    """GET ``url`` from its vetted address(es) only, SNI and Host set to its name."""
    host = _host(url)
    addresses = await asyncio.wait_for(asyncio.to_thread(_resolve_pinned, host, resolve), timeout=CONNECT_TIMEOUT_SEC)
    headers = {
        "Host": url.netloc.decode("ascii"),
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }
    for index, address in enumerate(addresses):
        client.cookies.clear()
        request = client.build_request("GET", url.copy_with(host=address), headers=headers,
                                       extensions={"sni_hostname": host})
        for name in ("cookie", "authorization", "proxy-authorization"):
            request.headers.pop(name, None)
        try:
            return await client.send(request, stream=True, follow_redirects=False)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if index == len(addresses) - 1:
                raise
    raise httpx.ConnectError("no address")


def _make_transport() -> Optional[httpx.AsyncBaseTransport]:
    """The transport for a fetch: httpx's own (certificate checks on). Tests swap it."""
    return None


async def fetch_to_file(
    plan: LinkPlan,
    *,
    fetch_url: Optional[str] = None,
    max_bytes: int,
    resolve: Optional[Resolver] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    on_bytes: Optional[Callable[[int, Optional[int]], None]] = None,
) -> Fetched:
    """Fetch the link's file into a local temp file under the rules above.

    ``fetch_url`` is the full first address (from the sealed link); ``resolve``
    and ``transport`` are for tests. The caller owns the returned path. Every
    failure is a LinkFetchError with fixed text; nothing raised carries the URL.
    """
    resolve = resolve or resolve_public_host
    transport = transport or _make_transport()
    try:
        async with asyncio.timeout(TOTAL_CAP_SEC + 120):
            return await _fetch(plan, fetch_url or plan.fetch_url, max_bytes, resolve, transport, on_bytes)
    except LinkFetchError:
        raise
    except (TimeoutError, httpx.TimeoutException):
        raise LinkFetchError("LINK_TIMEOUT", f"{plan.label} was too slow to send the file. Try again later.") from None
    except httpx.ConnectError:
        raise LinkFetchError("LINK_CONNECT_FAILED", f"ScaleCAD couldn't connect securely to {plan.label}.") from None
    except httpx.HTTPError:
        raise LinkFetchError("LINK_FETCH_FAILED", f"The download from {plan.label} stopped before the file arrived.") from None
    except OSError:
        raise LinkFetchError("LINK_DISK", "The worker couldn't store the fetched file. Try again.") from None
    except Exception as exc:  # noqa: BLE001 - never let a message or traceback carry the link
        logger.warning("link fetch failed: %s", type(exc).__name__)
        raise LinkFetchError("LINK_FETCH_FAILED", f"The download from {plan.label} stopped before the file arrived.") from None


async def _fetch(plan, first_url, max_bytes, resolve, transport, on_bytes) -> Fetched:
    try:
        url = _parse(first_url)
    except LinkRefused:
        raise LinkFetchError("LINK_REDIRECT_REFUSED", "The link redirected to an address ScaleCAD doesn't fetch from.") from None
    if not host_allowed(plan, url):
        raise LinkFetchError("LINK_REDIRECT_REFUSED", "The link redirected to an address ScaleCAD doesn't fetch from.")
    timeout = httpx.Timeout(connect=CONNECT_TIMEOUT_SEC, read=READ_TIMEOUT_SEC, write=READ_TIMEOUT_SEC, pool=CONNECT_TIMEOUT_SEC)
    redirects = 0
    form_followed = False
    async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False, trust_env=False) as client:
        while True:
            response = await _send_pinned(client, url, resolve)
            try:
                status = response.status_code
                logger.info("link fetch: host=%s status=%d", _host(url), status)
                if status in (301, 302, 303, 307, 308):
                    redirects += 1
                    location = response.headers.get("location")
                    if redirects > MAX_REDIRECTS:
                        raise LinkFetchError("LINK_TOO_MANY_REDIRECTS", "The link redirected too many times.")
                    if not location:
                        raise LinkFetchError("LINK_FETCH_FAILED", f"{plan.label} didn't send the file.")
                    url = check_target(plan, location, base=url)
                    continue
                if status != 200:
                    raise _status_error(plan, status)
                encoding = (response.headers.get("content-encoding") or "identity").strip().lower()
                if encoding not in ("", "identity"):
                    raise LinkFetchError(
                        "LINK_ENCODED",
                        f"{plan.label} sent the file compressed in transit, which ScaleCAD doesn't take. Download it and upload the file.",
                    )
                ctype = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                if ctype in ("text/html", "application/xhtml+xml"):
                    if plan.provider == "google_drive" and not form_followed:
                        page = await _read_page(response)
                        target = drive_confirm_target(page, url)
                        if target:
                            form_followed = True
                            url = check_target(plan, target)
                            continue
                    raise _page_error()
                length = response.headers.get("content-length")
                size = int(length) if length and length.isdigit() else None
                if size is not None and size > max_bytes:
                    raise _too_large(max_bytes)
                return await _stream_body(plan, response, url, size, max_bytes, on_bytes)
            finally:
                await response.aclose()


async def _read_page(response: httpx.Response) -> bytes:
    buf = bytearray()
    async for chunk in response.aiter_raw():
        buf.extend(chunk)
        if len(buf) >= MAX_PAGE_BYTES:
            break
    return bytes(buf[:MAX_PAGE_BYTES])


def _page_error() -> LinkFetchError:
    return LinkFetchError(
        "LINK_IS_A_PAGE",
        "That link opens a page, not a file. Share the file itself, or download it and upload the file.",
    )


def _too_large(max_bytes: int) -> LinkFetchError:
    from src.services.direct_upload_service import _gib

    return LinkFetchError("LINK_TOO_LARGE", f"That file is over the {_gib(max_bytes)} limit for one file.")


async def _stream_body(plan, response, url, size, max_bytes, on_bytes) -> Fetched:
    deadline = time.monotonic() + total_budget_sec(size, max_bytes)
    fd, path = tempfile.mkstemp(prefix="cv_link_part_", suffix=".bin")
    digest = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            first = True
            async for chunk in response.aiter_raw(chunk_size=CHUNK_BYTES):
                if not chunk:
                    continue
                if first:
                    first = False
                    if _looks_like_html(chunk[:1024]):
                        raise _page_error()
                total += len(chunk)
                if total > max_bytes:
                    raise _too_large(max_bytes)
                if time.monotonic() > deadline:
                    raise LinkFetchError("LINK_TIMEOUT", f"{plan.label} was too slow to send the file. Try again later.")
                digest.update(chunk)
                out.write(chunk)
                if on_bytes is not None:
                    on_bytes(total, size)
        if size is not None and total != size:
            raise LinkFetchError("LINK_FETCH_FAILED", f"The download from {plan.label} stopped before the file arrived.")
        if total == 0:
            raise LinkFetchError("LINK_EMPTY", "The link gave an empty file.")
        name = disposition_filename(response.headers.get("content-disposition")) or _last_segment(url.path)
        return Fetched(path=path, size=total, sha256=digest.hexdigest(), filename=name, final_host=_host(url))
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def choose_filename(given: Optional[str], served: Optional[str], hint: Optional[str]) -> str:
    """The part's name: the one typed with the link, the server's, or the link's own; it must be a CAD file."""
    from src.services.direct_upload_service import part_suffix

    for name in (given, served, hint):
        name = safe_filename(name)
        if name and part_suffix(name):
            return name
    raise LinkFetchError(
        "LINK_UNKNOWN_TYPE",
        "The linked file isn't named as a STEP, IGES or STL file (or a .zip or .gz of one). "
        "Give its name, for example bracket.step, and fetch it again.",
    )


__all__ = [
    "Fetched",
    "LinkFetchError",
    "LinkPlan",
    "LinkRefused",
    "MAX_REDIRECTS",
    "PROVIDER_LABELS",
    "check_target",
    "choose_filename",
    "disposition_filename",
    "drive_confirm_target",
    "fetch_to_file",
    "host_allowed",
    "link_import_enabled",
    "open_sealed_url",
    "own_buckets",
    "plan_link",
    "safe_filename",
    "seal_url",
    "total_budget_sec",
]
