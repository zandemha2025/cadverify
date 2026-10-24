"""Import from a link end to end, against a local HTTPS server on loopback.

Real Postgres, the real router stack, the real worker task and engine, and a
real TLS connection: POST /api/v1/uploads/from-link -> run_stored_check (the
``fetching`` stage, then the check) -> GET /api/v1/checks/{id}. The fake
provider is an HTTPS server on 127.0.0.1 with a certificate for the
provider's names from a test CA. DNS is a stand-in that answers public
addresses (so url_guard's rules apply as in production), and only the TCP
connect to those pinned addresses is sent to loopback; SNI, the certificate
check and the Host header are the real ones. Nothing leaves the machine.

Skipped unless DATABASE_URL is PostgreSQL at schema head (0058+).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import os
import ssl
import uuid

import pytest
import pytest_asyncio
import trimesh

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (DATABASE_URL=postgresql://...)")

DNS = {
    "www.dropbox.com": ["162.125.1.18"],
    "uc0a1b.dl.dropboxusercontent.com": ["162.125.2.15"],
}
SECRET = "rlkey=k3yTOPSECRET"


def _stl() -> bytes:
    return trimesh.creation.box(extents=(40, 30, 20)).export(file_type="stl")


def _certs(tmp_path):
    """A test CA and a leaf certificate for the fake provider's names."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "link-import test CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
          .not_valid_after(now + dt.timedelta(hours=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "www.dropbox.com")]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("www.dropbox.com"), x509.DNSName("*.dl.dropboxusercontent.com")]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "leaf.pem", tmp_path / "leaf.key"
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return ca.public_bytes(serialization.Encoding.PEM).decode(), str(cert_path), str(key_path)


class FakeProvider:
    """A minimal HTTPS/1.1 server: Dropbox's share host redirects to its content host."""

    def __init__(self, cert: str, key: str, body: bytes, *, page: bool = False):
        self.body = body
        self.page = page
        self.seen: list[dict] = []
        self.sni: list[str] = []
        self.ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self.ctx.load_cert_chain(cert, key)
        self.ctx.sni_callback = lambda sock, name, ctx: self.sni.append(name)

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0, ssl=self.ctx)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {k.strip().lower(): v.strip() for k, v in (ln.split(":", 1) for ln in lines[1:] if ":" in ln)}
            self.seen.append({"method": method, "target": target, "headers": headers})
            host = headers.get("host")
            if host == "www.dropbox.com" and target.startswith("/scl/fi/abc/bracket.stl?"):
                status, extra, body = "302 Found", [
                    "Location: https://uc0a1b.dl.dropboxusercontent.com/cd/0/get/T/file?dl=1",
                    "Set-Cookie: t=tracking; Domain=.dropbox.com; Path=/; Secure",
                ], b""
            elif host == "uc0a1b.dl.dropboxusercontent.com" and self.page:
                status, extra, body = "200 OK", ["Content-Type: text/html"], b"<html><body>Sign in</body></html>"
            elif host == "uc0a1b.dl.dropboxusercontent.com":
                status, extra, body = "200 OK", [
                    "Content-Type: application/octet-stream",
                    'Content-Disposition: attachment; filename="bracket.stl"',
                ], self.body
            else:
                status, extra, body = "404 Not Found", [], b""
            out = [f"HTTP/1.1 {status}", f"Content-Length: {len(body)}", "Connection: close", *extra, "", ""]
            writer.write("\r\n".join(out).encode("latin-1") + body)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()


def _loopback_transport(ca_pem: str, server_port: int):
    """httpx's transport, trusting the test CA, whose TCP connects to the pinned addresses land on loopback."""
    import httpcore
    import httpx

    pinned = {a for addrs in DNS.values() for a in addrs}

    class Loopback(httpcore.AnyIOBackend):
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            assert host in pinned and port == 443, (host, port)
            return await super().connect_tcp("127.0.0.1", server_port, timeout=timeout)

    ctx = ssl.create_default_context(cadata=ca_pem)
    transport = httpx.AsyncHTTPTransport(verify=ctx)
    transport._pool = httpcore.AsyncConnectionPool(ssl_context=ctx, network_backend=Loopback())
    return transport


class _Pool:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args))
        return object()


@pytest_asyncio.fixture
async def world(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    import src.jobs.arq_backend as arq_backend
    from src.api.checks import router as checks_router
    from src.api.link_import import router as link_router
    from src.api.uploads import router as uploads_router
    from src.auth.rate_limit import limiter
    from src.services import link_import

    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("DIRECT_UPLOAD_LOCAL_ROOT", str(tmp_path / "incoming"))
    monkeypatch.setenv("SOURCE_ARTIFACT_BLOB_DIR", str(tmp_path / "sources"))
    monkeypatch.setenv("RELEASE", "dev")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("CONNECTOR_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("SMS_VERIFICATION_REQUIRED", raising=False)
    monkeypatch.delenv("CHECK_MEMORY_BUDGET_MB", raising=False)
    monkeypatch.delenv("LINK_IMPORT_ENABLED", raising=False)
    monkeypatch.delenv("PRODUCTION_REGULATED_BOUNDARY_REQUIRED", raising=False)
    pool = _Pool()

    async def _get_pool():
        return pool

    monkeypatch.setattr(arq_backend, "get_arq_pool", _get_pool)

    from tests.test_link_import_fetch import fake_dns

    monkeypatch.setattr(link_import, "resolve_public_host", fake_dns(DNS))
    ca_pem, cert, key = _certs(tmp_path)
    provider = FakeProvider(cert, key, _stl())
    port = await provider.start()
    monkeypatch.setattr(link_import, "_make_transport", lambda: _loopback_transport(ca_pem, port))
    limiter.reset()

    await eng.dispose_engine()
    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    users: dict[str, int] = {}
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :n, now())"),
                        {"id": org, "n": f"link-{tag}"})
        for label, email, plan, role in (("work", f"eng-{tag}@acme-aero.com", "trial", "admin"),
                                         ("pilot", f"pilot-{tag}@acme-aero.com", "pilot", "admin"),
                                         ("viewer", f"view-{tag}@acme-aero.com", "pilot", "viewer")):
            uid = (await s.execute(text(
                "INSERT INTO users (email, email_lower, role, auth_provider, plan, phone_verified_at, current_org_id) "
                "VALUES (:e, :e, 'analyst', 'password', :p, now(), :o) RETURNING id"
            ), {"e": email, "p": plan, "o": org})).scalar_one()
            await s.execute(text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:id, :o, :u, :r, now())"
            ), {"id": str(ULID()), "o": org, "u": uid, "r": role})
            users[label] = uid

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(link_router)
    app.include_router(uploads_router)
    app.include_router(checks_router)
    try:
        yield {"app": app, "org": org, "users": users, "pool": pool, "provider": provider, "tmp": tmp_path}
    finally:
        await provider.stop()
        async with eng.get_session_factory()() as s, s.begin():
            ids = list(users.values())
            await s.execute(text("DELETE FROM jobs WHERE user_id = ANY(:u)"), {"u": ids})
            await s.execute(text("DELETE FROM direct_uploads WHERE user_id = ANY(:u)"), {"u": ids})
            await s.execute(text("DELETE FROM trial_checks WHERE user_id = ANY(:u)"), {"u": ids})
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": ids})
        await eng.dispose_engine()


def _client(app, uid: int):
    from httpx import ASGITransport, AsyncClient

    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=uid, api_key_id=0, key_prefix="session", role="analyst"
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _row(model, **where):
    from sqlalchemy import select

    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        stmt = select(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        return (await s.execute(stmt)).scalar_one()


LINK = f"https://www.dropbox.com/scl/fi/abc/bracket.stl?{SECRET}&dl=0"


@pytest.mark.asyncio
async def test_a_dropbox_link_is_fetched_on_the_worker_and_checked(world):
    from src.db.models import DirectUpload, Job
    from src.jobs.stored_check_tasks import run_stored_check

    uid = world["users"]["work"]
    data = world["provider"].body
    async with _client(world["app"], uid) as ac:
        caps = (await ac.get("/api/v1/uploads/from-link")).json()
        assert caps["enabled"] is True and "Dropbox" in caps["providers"]
        r = await ac.post("/api/v1/uploads/from-link", json={"url": LINK, "material_class": "polymer"})
        assert r.status_code == 202, r.text
        started = r.json()
        assert started["status"] == "queued" and started["source"] == "link"
        assert started["link"] == {"provider": "dropbox", "label": "Dropbox", "host": "www.dropbox.com"}
        assert started["filename"] == "bracket.stl"
        assert "TOPSECRET" not in r.text
        assert world["pool"].jobs[-1] == ("run_stored_check", (started["check_id"],))

        # The web request fetched nothing.
        assert world["provider"].seen == []
        job = await _row(Job, ulid=started["check_id"])
        assert job.params_json["link_url_sealed"].startswith("fernet:v1:")
        assert "TOPSECRET" not in str(job.params_json)
        upload = await _row(DirectUpload, ulid=started["direct_upload_id"])
        assert upload.purpose == "link" and upload.status == "attached"
        assert upload.expected_size_bytes == 2 * 1024**3  # the reservation until the size is known

        await run_stored_check({}, started["check_id"])
        done = (await ac.get(f"/api/v1/checks/{started['check_id']}")).json()

    assert done["status"] == "done", done
    key = hashlib.sha256(data).hexdigest()
    assert done["mesh_hash"] == key and done["part_url"] == f"/app/part/{key}"
    assert done["fetched_bytes"] == len(data) and done["filename"] == "bracket.stl"
    assert set(done["timings_ms"]) >= {"fetching", "sizing", "measuring", "pricing"}
    assert "verifying" not in done["timings_ms"]

    # What the provider saw: SNI and Host are the names, the share key reached it,
    # no cookie came back on the redirect, no credentials, identity encoding.
    seen = world["provider"].seen
    assert [s["headers"]["host"] for s in seen] == ["www.dropbox.com", "uc0a1b.dl.dropboxusercontent.com"]
    assert world["provider"].sni == ["www.dropbox.com", "uc0a1b.dl.dropboxusercontent.com"]
    assert seen[0]["target"] == f"/scl/fi/abc/bracket.stl?{SECRET}&dl=1"
    for s in seen:
        assert s["method"] == "GET"
        assert "cookie" not in s["headers"] and "authorization" not in s["headers"]
        assert s["headers"]["accept-encoding"] == "identity"
        assert s["headers"]["user-agent"].startswith("ScaleCAD-LinkImport/")

    # The sealed link is gone; the upload ended with the real size and digest.
    job = await _row(Job, ulid=done["check_id"])
    assert "link_url_sealed" not in job.params_json and "TOPSECRET" not in str(job.params_json)
    upload = await _row(DirectUpload, ulid=started["direct_upload_id"])
    assert upload.status == "consumed" and upload.storage_cleaned_at is not None
    assert upload.actual_size_bytes == upload.expected_size_bytes == len(data)
    assert upload.expected_checksum_sha256 == key and upload.filename == "bracket.stl"

    from src.services.source_artifact_service import find_source_artifact_suffix

    assert await find_source_artifact_suffix(world["org"], key) == ".stl"


@pytest.mark.asyncio
async def test_a_link_that_opens_a_page_fails_plainly_and_frees_the_reservation(world):
    from src.db.models import DirectUpload
    from src.jobs.stored_check_tasks import run_stored_check

    world["provider"].page = True
    uid = world["users"]["pilot"]
    async with _client(world["app"], uid) as ac:
        started = (await ac.post("/api/v1/uploads/from-link", json={"url": LINK})).json()
        await run_stored_check({}, started["check_id"])
        done = (await ac.get(f"/api/v1/checks/{started['check_id']}")).json()
    assert done["status"] == "failed" and done["error"]["code"] == "LINK_IS_A_PAGE"
    assert done["error"]["message"].startswith("That link opens a page, not a file.")
    assert done["error"]["message"].endswith("Nothing was charged.") and done["error"]["charged"] is False
    upload = await _row(DirectUpload, ulid=started["direct_upload_id"])
    assert upload.status == "failed" and upload.storage_cleaned_at is not None


@pytest.mark.asyncio
async def test_refusals_admission_idempotency_and_the_setting(world, monkeypatch):
    work = world["users"]["work"]
    async with _client(world["app"], work) as ac:
        r = await ac.post("/api/v1/uploads/from-link", json={"url": "https://example.com/bracket.step"})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "LINK_NOT_SUPPORTED"
        r = await ac.post("/api/v1/uploads/from-link", json={"url": "https://169.254.169.254/latest/meta-data/"})
        assert r.status_code == 422
        r = await ac.post("/api/v1/uploads/from-link", json={"url": LINK, "filename": "notes.pdf"})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "LINK_FILENAME"
        assert world["provider"].seen == []

        # Same Idempotency-Key, same link: the same check.
        key = f"link-{uuid.uuid4().hex}"
        a = await ac.post("/api/v1/uploads/from-link", json={"url": LINK}, headers={"Idempotency-Key": key})
        b = await ac.post("/api/v1/uploads/from-link", json={"url": LINK}, headers={"Idempotency-Key": key})
        assert a.status_code == 202 and b.status_code == 200
        assert a.json()["check_id"] == b.json()["check_id"]

        # A free account's organization: two uploads at once, as a direct upload.
        c = await ac.post("/api/v1/uploads/from-link", json={"url": LINK})
        assert c.status_code == 202, c.text
        d = await ac.post("/api/v1/uploads/from-link", json={"url": LINK})
        assert d.status_code == 429 and d.json()["detail"]["code"] == "DIRECT_UPLOAD_ADMISSION_LIMIT"
        assert d.headers.get("retry-after") == "60"

    # An org viewer can't import.
    async with _client(world["app"], world["users"]["viewer"]) as ac:
        r = await ac.post("/api/v1/uploads/from-link", json={"url": LINK})
        assert r.status_code == 403

    monkeypatch.setenv("LINK_IMPORT_ENABLED", "0")
    async with _client(world["app"], world["users"]["pilot"]) as ac:
        assert (await ac.get("/api/v1/uploads/from-link")).json()["enabled"] is False
        r = await ac.post("/api/v1/uploads/from-link", json={"url": LINK})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "LINK_IMPORT_OFF"
