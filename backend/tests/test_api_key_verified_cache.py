"""API-key auth never blocks the event loop (round 14 capacity defect).

Every Bearer request used to run the Argon2id check of its secret (0.3-0.6 s)
on the event loop: at 10 req/s with keys the API stalled, its pool ran out and
most requests timed out. These tests pin:

* the check runs in a worker thread, with no database session open;
* a verified secret is remembered briefly (keyed by an HMAC of the token, never
  the token), and a remembered key is still refused at once when it is revoked,
  expired, rotated, re-hashed, deactivated, owes two-step or is out of scope:
  the row is read on every request;
* many concurrent key requests share a small pool without running it dry;
* last_used_at writes never raise and come at most once a minute per key.
"""
from __future__ import annotations

import asyncio
import contextlib
import threading
from dataclasses import dataclass, replace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.auth import require_api_key as rak
from src.auth import verified_keys
from src.auth.hashing import hmac_index, mint_token, verify_token


@dataclass
class _Row:
    id: int
    user_id: int
    prefix: str
    hmac_index: str
    secret_hash: str
    revoked_at: object = None
    role: str = "analyst"
    is_active: bool = True
    org_id: str = "org-a"
    active_org_id: str = "org-a"
    scope: str | None = None
    expires_at: object = None
    expired: bool = False
    key_org_role: str | None = "member"
    two_step_owed: bool = False


class _Req:
    def __init__(self, method: str = "GET"):
        self.method = method
        self.client = type("C", (), {"host": "1.2.3.4"})()
        self.state = type("S", (), {})()
        self.url = type("U", (), {"path": "/api/v1/things"})()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(verified_keys, "_entries", type(verified_keys._entries)())
    monkeypatch.setattr(verified_keys, "_inflight", {})
    monkeypatch.setattr(rak, "_touched", {})
    monkeypatch.setattr(rak, "touch_last_used", AsyncMock())
    monkeypatch.setattr(rak, "_record_read_only_refusal", AsyncMock())


def _key(key_id: int = 7):
    token, prefix, secret_hash = mint_token()
    return token, _Row(id=key_id, user_id=40 + key_id, prefix=prefix, hmac_index=hmac_index(token),
                       secret_hash=secret_hash)


class _Checks:
    """The real Argon2 check, counted, with the thread it ran on."""

    def __init__(self):
        self.n = 0
        self.threads: list[tuple[int, bool]] = []

    def __call__(self, secret_hash: str, token: str) -> bool:
        self.n += 1
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        self.threads.append((threading.get_ident(), on_loop))
        return verify_token(secret_hash, token)


def _serve(monkeypatch, rows: dict) -> _Checks:
    checks = _Checks()
    monkeypatch.setattr(rak, "verify_token", checks)
    monkeypatch.setattr(rak, "lookup_api_key", AsyncMock(side_effect=lambda idx: rows.get(idx)))
    return checks


async def _auth(token: str, method: str = "GET"):
    return await rak.require_api_key(_Req(method), authorization=f"Bearer {token}")


async def _refused(token: str, method: str = "GET") -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        await _auth(token, method)
    return exc.value


@pytest.mark.asyncio
async def test_the_secret_check_runs_off_the_event_loop_with_no_session_open(monkeypatch):
    from src.auth import models

    token, row = _key()
    open_sessions = []

    class _Result:
        def first(self):
            return (row.id, row.user_id, row.prefix, row.hmac_index, row.secret_hash, None, "analyst", True,
                    "org-a", "org-a", None, None, False, "member", False)

    class _Session:
        async def __aenter__(self):
            open_sessions.append(self)
            return self

        async def __aexit__(self, *exc):
            open_sessions.remove(self)

        async def execute(self, *a, **k):
            return _Result()

    monkeypatch.setattr(models, "_session", lambda: (lambda: _Session()))
    monkeypatch.setattr(rak, "lookup_api_key", models.lookup_api_key)  # the real lookup, on a fake session
    seen = []

    def check(secret_hash, t):
        seen.append((threading.get_ident(), len(open_sessions)))
        try:
            asyncio.get_running_loop()
            seen.append("on the loop")
        except RuntimeError:
            pass
        return verify_token(secret_hash, t)

    monkeypatch.setattr(rak, "verify_token", check)
    user = await _auth(token)
    assert user.api_key_id == row.id and user.org_id == "org-a"
    (thread, sessions_open), = seen
    assert thread != threading.get_ident()  # a worker thread, not the loop's
    assert sessions_open == 0  # the lookup's session closed before the check


@pytest.mark.asyncio
async def test_a_verified_key_is_remembered_and_checked_once(monkeypatch):
    token, row = _key()
    checks = _serve(monkeypatch, {row.hmac_index: row})
    for _ in range(5):
        assert (await _auth(token)).api_key_id == row.id
    assert checks.n == 1
    assert all(not on_loop for _, on_loop in checks.threads)
    # Past the TTL it is checked again.
    now = verified_keys._now()
    monkeypatch.setattr(verified_keys, "_now", lambda: now + verified_keys.TTL_S + 1)
    await _auth(token)
    assert checks.n == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change, status, code", [
    ({"revoked_at": "2026-10-22T10:00:00Z"}, 401, "auth_invalid"),
    ({"expired": True, "expires_at": None}, 401, "api_key_expired"),
    ({"is_active": False}, 403, "account_deactivated"),
    ({"two_step_owed": True}, 403, "api_key_two_step_required"),
    ({"active_org_id": "org-b"}, 403, "api_key_org_mismatch"),
    ({"org_id": None}, 401, "auth_invalid"),
])
async def test_a_remembered_key_is_still_refused_at_once(monkeypatch, change, status, code):
    token, row = _key()
    rows = {row.hmac_index: row}
    checks = _serve(monkeypatch, rows)
    await _auth(token)
    assert checks.n == 1
    rows[row.hmac_index] = replace(row, **change)  # the next request reads the changed row
    err = await _refused(token)
    assert (err.status_code, err.detail["code"]) == (status, code)
    assert checks.n == 1  # refused on the row, the remembered check notwithstanding


@pytest.mark.asyncio
async def test_a_remembered_key_made_read_only_is_refused_a_write_at_once(monkeypatch):
    token, row = _key()
    rows = {row.hmac_index: row}
    _serve(monkeypatch, rows)
    await _auth(token, "POST")
    rows[row.hmac_index] = replace(row, key_org_role="viewer")
    err = await _refused(token, "POST")
    assert (err.status_code, err.detail["code"]) == (403, "api_key_read_only")
    assert (await _auth(token, "GET")).scope == "read"


@pytest.mark.asyncio
async def test_a_rotated_key_is_refused_and_its_replacement_checked(monkeypatch):
    old_token, old = _key(7)
    rows = {old.hmac_index: old}
    checks = _serve(monkeypatch, rows)
    await _auth(old_token)
    # Rotation revokes the old row and issues a new key (keys_api.rotate_key).
    new_token, new = _key(8)
    rows[old.hmac_index] = replace(old, revoked_at="2026-10-22T10:00:00Z")
    rows[new.hmac_index] = new
    assert (await _refused(old_token)).detail["code"] == "auth_invalid"
    assert (await _auth(new_token)).api_key_id == 8
    assert checks.n == 2


@pytest.mark.asyncio
async def test_a_remembered_pass_counts_only_for_that_row_and_stored_hash(monkeypatch):
    token, row = _key(7)
    rows = {row.hmac_index: row}
    checks = _serve(monkeypatch, rows)
    await _auth(token)
    # The row's stored hash changes (re-hashed, or replaced in place): checked again, and refused.
    other, _, other_hash = mint_token()
    rows[row.hmac_index] = replace(row, secret_hash=other_hash)
    assert (await _refused(token)).detail["code"] == "auth_invalid"
    assert checks.n == 2
    # The same token resolving to another row is never answered from the first row's pass.
    rows[row.hmac_index] = replace(row, id=99)
    await _auth(token)
    assert checks.n == 3


@pytest.mark.asyncio
async def test_a_tampered_token_is_checked_and_refused(monkeypatch):
    token, row = _key()
    checks = _serve(monkeypatch, {row.hmac_index: row})
    await _auth(token)
    monkeypatch.setattr(rak, "hmac_index", lambda t: row.hmac_index)  # the lookup finds the row anyway
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert (await _refused(tampered)).detail["code"] == "auth_invalid"
    assert checks.n == 2


@pytest.mark.asyncio
async def test_the_cache_never_holds_the_token(monkeypatch):
    token, row = _key()
    _serve(monkeypatch, {row.hmac_index: row})
    await _auth(token)
    assert len(verified_keys._entries) == 1
    secret = token.rsplit("_", 1)[-1]
    for k, v in verified_keys._entries.items():
        blob = k + b"".join(x if isinstance(x, bytes) else repr(x).encode() for x in v)
        for needle in (token, secret, row.secret_hash, row.hmac_index):
            assert needle.encode() not in blob
            assert needle not in repr((k, v))
        assert k != bytes.fromhex(row.hmac_index)  # not the database's lookup index either
    assert verified_keys._inflight == {}


@pytest.mark.asyncio
async def test_many_concurrent_key_requests_share_a_small_pool(monkeypatch):
    """60 requests at once over 4 keys, a pool of 3 connections that times out after 1 s.

    With the check on the loop the loop stood still for 60 Argon2 checks in a row and the
    pool's waiters timed out (QueuePool limit ... reached); now each key is checked once,
    off the loop, and the lookups go through.
    """

    class _Pool:
        def __init__(self, size: int, timeout_s: float):
            self.size, self.timeout_s = size, timeout_s
            self.out = self.peak = self.timeouts = 0

        @contextlib.asynccontextmanager
        async def connection(self):
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.timeout_s
            while self.out >= self.size:
                if loop.time() >= deadline:
                    self.timeouts += 1
                    raise TimeoutError("QueuePool limit of size 3 reached, connection timed out")
                await asyncio.sleep(0.002)
            self.out += 1
            self.peak = max(self.peak, self.out)
            try:
                await asyncio.sleep(0.005)  # the query's round trip
                yield
            finally:
                self.out -= 1

    pool = _Pool(3, 1.0)
    keys = [_key(i) for i in range(1, 5)]
    rows = {row.hmac_index: row for _, row in keys}
    checks = _Checks()
    held_during_check = []

    def check(secret_hash, token):
        held_during_check.append(pool.out)
        return checks(secret_hash, token)

    async def lookup(idx):
        async with pool.connection():
            return rows.get(idx)

    async def touch(key_id):
        async with pool.connection():
            pass

    monkeypatch.setattr(rak, "verify_token", check)
    monkeypatch.setattr(rak, "lookup_api_key", lookup)
    monkeypatch.setattr(rak, "touch_last_used", touch)
    users = await asyncio.gather(*(_auth(keys[i % 4][0]) for i in range(60)))
    assert sorted({u.api_key_id for u in users}) == [1, 2, 3, 4]
    assert pool.timeouts == 0 and pool.peak <= 3
    assert checks.n == 4  # concurrent requests with the same key share one check
    assert all(not on_loop for _, on_loop in checks.threads)
    await asyncio.gather(*list(rak._touch_tasks))
    assert len(rak._touched) == 4  # one last_used_at write per key


@pytest.mark.asyncio
async def test_last_used_writes_never_raise_and_come_once_a_minute(monkeypatch, caplog):
    token, row = _key()
    _serve(monkeypatch, {row.hmac_index: row})
    touch = AsyncMock(side_effect=TimeoutError("QueuePool limit of size 10 overflow 10 reached"))
    monkeypatch.setattr(rak, "touch_last_used", touch)
    loop = asyncio.get_running_loop()
    unretrieved = []
    loop.set_exception_handler(lambda _loop, ctx: unretrieved.append(ctx))
    clock = [1000.0]
    monkeypatch.setattr(rak, "_now", lambda: clock[0])
    for _ in range(10):
        await _auth(token)
    tasks = list(rak._touch_tasks)
    await asyncio.gather(*tasks)
    assert touch.await_count == 1
    assert all(t.exception() is None for t in tasks)
    assert "api_key_last_used_not_recorded" in caplog.text
    clock[0] += rak.TOUCH_EVERY_S + 1
    await _auth(token)
    await asyncio.gather(*list(rak._touch_tasks))
    assert touch.await_count == 2
    loop.set_exception_handler(None)
    assert unretrieved == []
