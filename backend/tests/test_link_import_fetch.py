"""Import from a link: the guarded fetch, with fake DNS and a fake transport.

No request leaves the process. Every address is resolved by a stand-in DNS,
every request answered by ``httpx.MockTransport``, so the tests see exactly
what the fetch would send: the pinned address, SNI and Host, the headers,
each redirect re-validated, the caps and the refusals.
"""
from __future__ import annotations

import hashlib
import os

import httpx
import pytest

from src.services import link_import as L
from src.services.url_guard import resolve_public_host

PUBLIC = {
    "www.dropbox.com": ["162.125.1.18"],
    "uc0a1b.dl.dropboxusercontent.com": ["162.125.2.15"],
    "drive.usercontent.google.com": ["142.250.1.132"],
    "doc-08-docs.googleusercontent.com": ["142.250.1.133"],
    "my-parts.s3.us-east-1.amazonaws.com": ["52.216.1.1", "2600:1f18::1"],
    "api.onedrive.com": ["13.107.42.12"],
    "public.am.files.1drv.com": ["13.107.42.13"],
    "contoso.sharepoint.com": ["13.107.136.9"],
}
STEP = b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('bracket'),'2;1');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def fake_dns(table: dict[str, list[str]]):
    """A resolver that applies url_guard's address rules to a fixed table, never the network."""
    import socket

    def resolve(host: str) -> list[str]:
        addresses = table.get(host)
        if addresses is None:
            raise L.UnsafeURLError(f"host does not resolve: {host}")
        infos = [(socket.AF_INET6 if ":" in a else socket.AF_INET, 0, 0, "", (a, 443)) for a in addresses]
        from unittest.mock import patch

        with patch("socket.getaddrinfo", return_value=infos):
            return resolve_public_host(host)

    return resolve


class Recorder:
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            response = self.handler(request)
            if hasattr(response, "_content"):
                # Built with content=: serve it as a stream, as a network response arrives.
                response = httpx.Response(response.status_code, headers=response.headers,
                                          stream=httpx.ByteStream(response._content))
            return response

        return httpx.MockTransport(handle)


async def _fetch(url: str, handler, *, dns=None, max_bytes=10 * 1024 * 1024, fetch_url=None):
    plan = L.plan_link(url)
    rec = Recorder(handler)
    try:
        got = await L.fetch_to_file(plan, fetch_url=fetch_url, max_bytes=max_bytes,
                                    resolve=fake_dns(dns or PUBLIC), transport=rec.transport())
    except L.LinkFetchError as exc:
        return rec, exc
    return rec, got


def _done(got) -> bytes:
    assert isinstance(got, L.Fetched), got
    with open(got.path, "rb") as fh:
        data = fh.read()
    os.unlink(got.path)
    return data


@pytest.mark.asyncio
async def test_dropbox_file_is_fetched_from_the_pinned_address_with_sni_and_host():
    def handler(req: httpx.Request) -> httpx.Response:
        sni = req.extensions.get("sni_hostname")
        if sni == "www.dropbox.com":
            return httpx.Response(302, headers={
                "location": "https://uc0a1b.dl.dropboxusercontent.com/cd/0/get/X/file?dl=1",
                "set-cookie": "t=tracking; Domain=.dropbox.com; Path=/; Secure",
            })
        assert sni == "uc0a1b.dl.dropboxusercontent.com"
        return httpx.Response(200, content=STEP, headers={
            "content-length": str(len(STEP)), "content-type": "application/octet-stream",
            "content-disposition": 'attachment; filename="bracket.step"',
        })

    rec, got = await _fetch("https://www.dropbox.com/scl/fi/abc/bracket.step?rlkey=K&dl=0", handler)
    assert _done(got) == STEP
    assert got.sha256 == hashlib.sha256(STEP).hexdigest() and got.size == len(STEP)
    assert got.filename == "bracket.step" and got.final_host == "uc0a1b.dl.dropboxusercontent.com"
    first, second = rec.requests
    # Pinned: the request goes to the vetted address, the name rides in SNI and Host.
    assert first.url.host == "162.125.1.18" and first.url.port is None and first.url.scheme == "https"
    assert first.headers["host"] == "www.dropbox.com"
    assert first.url.query == b"rlkey=K&dl=1"
    assert second.url.host == "162.125.2.15" and second.headers["host"] == "uc0a1b.dl.dropboxusercontent.com"
    for req in rec.requests:
        assert req.method == "GET"
        assert req.headers["accept-encoding"] == "identity"
        assert req.headers["user-agent"] == L.USER_AGENT
        assert "cookie" not in req.headers and "authorization" not in req.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("address", [
    "10.0.0.5", "172.16.3.4", "192.168.1.1",          # private
    "127.0.0.1", "::1",                               # loopback
    "169.254.169.254", "fe80::1",                     # link-local, the metadata address
    "fd00:ec2::254",                                  # the IPv6 metadata address
    "100.64.0.1", "100.100.100.200",                  # CGNAT
    "224.0.0.1", "ff02::1",                           # multicast
    "0.0.0.0", "::",                                  # unspecified
    "240.0.0.1", "192.0.0.8",                         # reserved, IETF protocol assignments
    "::ffff:10.0.0.1",                                # IPv4-mapped private
    "64:ff9b::a9fe:a9fe", "2002:a9fe:a9fe::1",        # NAT64 and 6to4 of the metadata address
])
async def test_a_host_resolving_to_a_non_public_address_is_never_requested(address):
    def handler(req):
        raise AssertionError("a request was sent to a refused address")

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", handler, dns={"www.dropbox.com": [address]})
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_ADDRESS_REFUSED"
    assert rec.requests == []


@pytest.mark.asyncio
async def test_one_bad_address_among_good_ones_refuses_the_host():
    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", lambda r: httpx.Response(200, content=STEP),
                            dns={"www.dropbox.com": ["162.125.1.18", "10.1.2.3"]})
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_ADDRESS_REFUSED"
    assert rec.requests == []


@pytest.mark.asyncio
async def test_a_redirect_to_a_host_resolving_privately_is_refused_before_it_is_requested():
    dns = {**PUBLIC, "uc0a1b.dl.dropboxusercontent.com": ["169.254.169.254"]}

    def handler(req):
        assert req.extensions["sni_hostname"] == "www.dropbox.com"
        return httpx.Response(302, headers={"location": "https://uc0a1b.dl.dropboxusercontent.com/f"})

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", handler, dns=dns)
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_ADDRESS_REFUSED"
    assert len(rec.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("location,code", [
    ("http://uc0a1b.dl.dropboxusercontent.com/f", "LINK_REDIRECT_REFUSED"),
    ("https://uc0a1b.dl.dropboxusercontent.com:444/f", "LINK_REDIRECT_REFUSED"),
    ("https://x@uc0a1b.dl.dropboxusercontent.com/f", "LINK_REDIRECT_REFUSED"),
    ("https://169.254.169.254/latest/meta-data/iam", "LINK_REDIRECT_REFUSED"),
    ("https://evil.example/f.step", "LINK_REDIRECT_REFUSED"),
    ("https://drive.usercontent.google.com/download?id=x", "LINK_REDIRECT_REFUSED"),
    ("https://www.dropbox.com/login?cont=x", "LINK_NEEDS_SIGN_IN"),
])
async def test_every_redirect_is_checked_against_the_same_rules(location, code):
    def handler(req):
        return httpx.Response(302, headers={"location": location})

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", handler)
    assert isinstance(got, L.LinkFetchError) and got.code == code
    assert len(rec.requests) == 1


@pytest.mark.asyncio
async def test_at_most_three_redirects():
    hops = iter(range(10))

    def handler(req):
        return httpx.Response(302, headers={"location": f"https://www.dropbox.com/s/abc/b{next(hops)}.step"})

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", handler)
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_TOO_MANY_REDIRECTS"
    assert len(rec.requests) == L.MAX_REDIRECTS + 1


@pytest.mark.asyncio
async def test_three_redirects_are_followed():
    def handler(req):
        n = req.url.path.count("/r")
        if n < 3:
            return httpx.Response(307, headers={"location": req.url.path + "/r"})
        return httpx.Response(200, content=STEP)

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", handler)
    assert _done(got) == STEP and len(rec.requests) == 4


@pytest.mark.asyncio
async def test_content_length_over_the_cap_is_refused_before_the_body_is_read():
    class Body(httpx.AsyncByteStream):
        read = False

        async def __aiter__(self):
            Body.read = True
            yield b"x"

    def handler(req):
        return httpx.Response(200, headers={"content-length": str(5 * 1024 * 1024)}, stream=Body())

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", handler, max_bytes=1024 * 1024)
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_TOO_LARGE"
    assert Body.read is False
    assert "1 MB" in got.message


@pytest.mark.asyncio
async def test_a_stream_without_length_is_cut_at_the_cap():
    sent = []

    class Endless(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                sent.append(1)
                yield b"s" * 65536

    def handler(req):
        return httpx.Response(200, stream=Endless())

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.stl", handler, max_bytes=256 * 1024)
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_TOO_LARGE"
    assert len(sent) < 100


@pytest.mark.asyncio
async def test_a_compressed_transfer_is_refused():
    import gzip

    def handler(req):
        return httpx.Response(200, content=gzip.compress(STEP), headers={"content-encoding": "gzip"})

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", handler)
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_ENCODED"


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,body", [
    ({"content-type": "text/html; charset=utf-8"}, b"<html><body>Sign in to Dropbox</body></html>"),
    ({"content-type": "application/octet-stream"}, b"  <!DOCTYPE html><html><body>Error</body></html>"),
])
async def test_a_page_instead_of_a_file_is_refused(headers, body):
    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", lambda r: httpx.Response(200, content=body, headers=headers))
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_IS_A_PAGE"
    assert got.message.startswith("That link opens a page, not a file.")


@pytest.mark.asyncio
async def test_drive_virus_scan_page_is_followed_once_through_its_form():
    page = b"""<html><body><form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
      <input type="hidden" name="id" value="1AbCdEfGhIjKlMnOp"><input type="hidden" name="export" value="download">
      <input type="hidden" name="confirm" value="t"><input type="hidden" name="uuid" value="u1"></form></body></html>"""

    def handler(req):
        q = dict(httpx.QueryParams(req.url.query))
        if q.get("confirm") == "t":
            return httpx.Response(200, content=STEP, headers={"content-disposition": "attachment; filename=\"big.step\""})
        return httpx.Response(200, content=page, headers={"content-type": "text/html"})

    rec, got = await _fetch("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing", handler)
    assert _done(got) == STEP and got.filename == "big.step"
    assert [r.headers["host"] for r in rec.requests] == ["drive.usercontent.google.com"] * 2


@pytest.mark.asyncio
async def test_drive_page_twice_is_refused():
    page = b"""<html><form action="https://drive.usercontent.google.com/download"><input type="hidden" name="id" value="1AbCdEfGhIjKlMnOp"></form></html>"""
    rec, got = await _fetch("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view",
                            lambda r: httpx.Response(200, content=page, headers={"content-type": "text/html"}))
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_IS_A_PAGE"
    assert len(rec.requests) == 2


@pytest.mark.asyncio
async def test_drive_form_pointing_elsewhere_is_refused():
    page = b"""<html><form action="https://evil.example/download"><input type="hidden" name="id" value="x"></form></html>"""
    rec, got = await _fetch("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view",
                            lambda r: httpx.Response(200, content=page, headers={"content-type": "text/html"}))
    assert isinstance(got, L.LinkFetchError) and got.code == "LINK_REDIRECT_REFUSED"
    assert len(rec.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [
    (401, "LINK_NEEDS_SIGN_IN"), (403, "LINK_NEEDS_SIGN_IN"), (404, "LINK_NOT_FOUND"), (410, "LINK_NOT_FOUND"),
    (429, "LINK_RATE_LIMITED"), (500, "LINK_PROVIDER_ERROR"), (503, "LINK_PROVIDER_ERROR"), (204, "LINK_FETCH_FAILED"),
])
async def test_provider_answers_are_named(status, code):
    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", lambda r: httpx.Response(status))
    assert isinstance(got, L.LinkFetchError) and got.code == code
    assert "Dropbox" in got.message or code == "LINK_NEEDS_SIGN_IN"


@pytest.mark.asyncio
async def test_an_expired_s3_link_says_so():
    rec, got = await _fetch("https://my-parts.s3.us-east-1.amazonaws.com/b.step?X-Amz-Signature=old",
                            lambda r: httpx.Response(403, content=b"<Error><Code>AccessDenied</Code></Error>"))
    assert got.code == "LINK_NEEDS_SIGN_IN" and "expire" in got.message


@pytest.mark.asyncio
async def test_the_next_address_is_tried_when_one_does_not_connect():
    def handler(req):
        if req.url.host == "52.216.1.1":
            raise httpx.ConnectError("unreachable")
        assert req.url.host == "2600:1f18::1" and req.headers["host"] == "my-parts.s3.us-east-1.amazonaws.com"
        return httpx.Response(200, content=STEP)

    rec, got = await _fetch("https://my-parts.s3.us-east-1.amazonaws.com/b.step?X-Amz-Signature=s", handler)
    assert _done(got) == STEP and len(rec.requests) == 2


@pytest.mark.asyncio
async def test_onedrive_downloads_through_the_shares_api_and_its_content_host():
    def handler(req):
        if req.headers["host"] == "api.onedrive.com":
            assert req.url.path.startswith("/v1.0/shares/u!") and req.url.path.endswith("/root/content")
            return httpx.Response(302, headers={"location": "https://public.am.files.1drv.com/y4m/abc?download&psid=1"})
        return httpx.Response(200, content=STEP, headers={"content-disposition": "attachment; filename=\"plate.step\""})

    rec, got = await _fetch("https://1drv.ms/u/s!AbCdEf123", handler)
    assert _done(got) == STEP and got.filename == "plate.step"


@pytest.mark.asyncio
async def test_an_empty_file_and_a_short_body_are_refused():
    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", lambda r: httpx.Response(200, content=b""))
    assert got.code == "LINK_EMPTY"

    class Short(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield STEP[:10]

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step",
                            lambda r: httpx.Response(200, headers={"content-length": "999"}, stream=Short()))
    assert got.code == "LINK_FETCH_FAILED"


@pytest.mark.asyncio
async def test_the_total_budget_stops_a_slow_download(monkeypatch):
    clock = iter([0.0] + [10_000.0] * 50)
    monkeypatch.setattr(L.time, "monotonic", lambda: next(clock))

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(3):
                yield b"s" * 1000

    rec, got = await _fetch("https://www.dropbox.com/s/abc/b.step", lambda r: httpx.Response(200, stream=Slow()))
    assert got.code == "LINK_TIMEOUT"


@pytest.mark.asyncio
async def test_timeouts_and_transport_errors_never_carry_the_link():
    secret = "rlkey=TOPSECRET"

    def timeout(req):
        raise httpx.ReadTimeout(f"timed out reading {req.url}", request=req)

    def broken(req):
        raise httpx.RemoteProtocolError(f"bad response from {req.url}", request=req)

    for handler, code in ((timeout, "LINK_TIMEOUT"), (broken, "LINK_FETCH_FAILED")):
        rec, got = await _fetch(f"https://www.dropbox.com/scl/fi/abc/b.step?{secret}", handler)
        assert isinstance(got, L.LinkFetchError) and got.code == code
        assert "TOPSECRET" not in got.message and "TOPSECRET" not in str(got)
        assert got.__cause__ is None and got.__suppress_context__


@pytest.mark.asyncio
async def test_the_fetch_logs_hosts_only(caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger="cadverify.link_import")
    rec, got = await _fetch("https://www.dropbox.com/scl/fi/abc/b.step?rlkey=TOPSECRET",
                            lambda r: httpx.Response(200, content=STEP))
    _done(got)
    assert "www.dropbox.com" in caplog.text
    assert "TOPSECRET" not in caplog.text and "rlkey" not in caplog.text and "/scl/fi" not in caplog.text


@pytest.mark.asyncio
async def test_a_first_address_off_the_provider_is_refused():
    # The worker's first address comes from the sealed link; it must still be the provider's.
    plan = L.plan_link("https://www.dropbox.com/s/abc/b.step")
    with pytest.raises(L.LinkFetchError) as exc:
        await L.fetch_to_file(plan, fetch_url="https://evil.example/b.step", max_bytes=1024,
                              resolve=fake_dns(PUBLIC), transport=Recorder(lambda r: httpx.Response(200)).transport())
    assert exc.value.code == "LINK_REDIRECT_REFUSED"
