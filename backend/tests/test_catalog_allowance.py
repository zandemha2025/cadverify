"""Real PostgreSQL checks for the free catalog run's allowance.

A work-email account gets its first 50 catalog parts free; a part means a
distinct file (the check identity: name and bytes). Run with DATABASE_URL
pointing at local/CI PostgreSQL. Each test uses its own schema with the few
tables the allowance reads; nothing else is touched.
"""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.auth import catalog_allowance as ca
from src.auth import validation_caps as vc
from src.db.models import TrialCheck

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(not _PG, reason="requires PostgreSQL (DATABASE_URL=postgresql://...)")

WORK, PERSONAL, PILOT, UNVERIFIED = 1, 2, 3, 4


@pytest_asyncio.fixture
async def db(monkeypatch):
    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "catalog_test_" + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as c:
        await c.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}}, pool_size=20)
    try:
        async with engine.begin() as c:
            await c.execute(text(
                "CREATE TABLE users (id bigint PRIMARY KEY, plan text NOT NULL, email_lower text, "
                "free_check_grant integer, phone_verified_at timestamptz)"
            ))
            await c.execute(text(
                "CREATE TABLE batches (id bigserial PRIMARY KEY, ulid text UNIQUE NOT NULL, user_id bigint NOT NULL, "
                "job_type text NOT NULL DEFAULT 'dfm', status text NOT NULL DEFAULT 'pending', manifest_json jsonb)"
            ))
            await c.execute(text(
                "CREATE TABLE batch_items (id bigserial PRIMARY KEY, batch_id bigint REFERENCES batches(id), "
                "status text NOT NULL DEFAULT 'pending')"
            ))
            await c.execute(text(
                "CREATE TABLE catalog_parts (user_id bigint REFERENCES users(id) ON DELETE CASCADE, file_hash text, "
                "batch_id bigint REFERENCES batches(id) ON DELETE SET NULL, "
                "batch_item_id bigint REFERENCES batch_items(id) ON DELETE SET NULL, state text NOT NULL "
                "CHECK (state IN ('reserved','counted')), created_at timestamptz NOT NULL DEFAULT now(), "
                "updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (user_id, file_hash))"
            ))
            await c.run_sync(TrialCheck.__table__.create)
            await c.execute(text(
                "INSERT INTO users VALUES "
                "(1, 'trial', 'ops@acme-aero.com', NULL, now()), "
                "(2, 'trial', 'someone@gmail.com', NULL, now()), "
                "(3, 'pilot', 'pilot@acme-aero.com', NULL, NULL), "
                "(4, 'trial', 'new@acme-aero.com', NULL, NULL)"
            ))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(ca, "get_session_factory", lambda: factory)
        monkeypatch.setattr(vc, "get_session_factory", lambda: factory)
        monkeypatch.delenv("FREE_CATALOG_PARTS", raising=False)
        monkeypatch.delenv("SMS_VERIFICATION_REQUIRED", raising=False)
        yield factory
    finally:
        await engine.dispose()
        async with admin.begin() as c:
            await c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


async def _batch(factory, user_id: int, n: int, *, free: bool = True, status: str = "pending") -> tuple[int, list[int]]:
    async with factory() as s, s.begin():
        bid = (await s.execute(text(
            "INSERT INTO batches (ulid, user_id, job_type, status, manifest_json) "
            "VALUES (:u, :uid, 'catalog', :st, CAST(:m AS jsonb)) RETURNING id"
        ), {"u": uuid4().hex, "uid": user_id, "st": status,
            "m": '{"catalog": {"free": %s}}' % ("true" if free else "false")})).scalar_one()
        ids = []
        for _ in range(n):
            ids.append((await s.execute(text(
                "INSERT INTO batch_items (batch_id) VALUES (:b) RETURNING id"), {"b": bid})).scalar_one())
    return bid, ids


async def _set(factory, sql: str, **params) -> None:
    async with factory() as s, s.begin():
        await s.execute(text(sql), params)


async def _reserve(factory, user_id: int, bid: int, items: list[tuple[int, str]]):
    """One create request: the access read, then the locked reservation in the batch's transaction."""
    async with factory() as s:
        access = await ca._access(s, user_id)
    async with factory() as s, s.begin():
        return await ca.reserve_catalog_parts(s, user_id, bid, items, access=access, exclude_batch_id=bid)


async def _complete(factory, user_id: int, bid: int, item_id: int, file_hash: str) -> None:
    async with factory() as s, s.begin():
        await s.execute(text("UPDATE batch_items SET status = 'completed' WHERE id = :i"), {"i": item_id})
        await ca.count_completed_part(s, user_id, bid, item_id, file_hash)


async def _finish_batch(factory, bid: int) -> None:
    await _set(factory, "UPDATE batches SET status = 'completed' WHERE id = :b", b=bid)


def test_file_identity_is_the_check_identity():
    import hashlib

    name, data = "bracket.step", b"ISO-10303-21;\n"
    raw = name.encode()
    expected = hashlib.sha256(len(raw).to_bytes(8, "big") + raw + data).hexdigest()
    assert ca.file_identity(name, data) == expected
    assert ca.file_identity("other.step", data) != expected


@pytest.mark.asyncio
async def test_fifty_free_parts_then_the_51st_is_refused(db):
    bid, items = await _batch(db, WORK, 50)
    r = await _reserve(db, WORK, bid, [(i, f"part-{n}") for n, i in enumerate(items)])
    assert (r.new, r.reruns, r.cap, r.remaining) == (50, 0, 50, 0)
    usage = await ca.catalog_usage(WORK)
    assert (usage["eligible"], usage["used"], usage["reserved"], usage["remaining"]) == (True, 0, 50, 0)
    for n, i in enumerate(items):
        await _complete(db, WORK, bid, i, f"part-{n}")
    await _finish_batch(db, bid)
    usage = await ca.catalog_usage(WORK)
    assert (usage["used"], usage["reserved"], usage["remaining"]) == (50, 0, 0)

    bid2, items2 = await _batch(db, WORK, 1)
    with pytest.raises(ca.HTTPException) as refused:
        await _reserve(db, WORK, bid2, [(items2[0], "part-51")])
    assert refused.value.status_code == 403
    detail = refused.value.detail
    assert detail["code"] == "catalog_allowance_exceeded"
    assert (detail["cap"], detail["used"], detail["remaining"], detail["needed"]) == (50, 50, 0, 1)
    assert "50 free catalog parts are used" in detail["message"]


@pytest.mark.asyncio
async def test_a_set_bigger_than_whats_left_is_refused_whole_and_says_how_many(db):
    bid, items = await _batch(db, WORK, 52)
    with pytest.raises(ca.HTTPException) as refused:
        await _reserve(db, WORK, bid, [(i, f"p{n}") for n, i in enumerate(items)])
    detail = refused.value.detail
    assert (detail["needed"], detail["remaining"]) == (52, 50)
    assert "has 52 parts not run before" in detail["message"] and "Remove 2" in detail["message"]
    # Nothing was reserved by the refused run.
    assert (await ca.catalog_usage(WORK))["remaining"] == 50


@pytest.mark.asyncio
async def test_rerunning_parts_already_run_or_checked_is_free(db):
    bid, items = await _batch(db, WORK, 3)
    await _reserve(db, WORK, bid, list(zip(items, ["a", "b", "c"])))
    for i, h in zip(items, ["a", "b", "c"]):
        await _complete(db, WORK, bid, i, h)
    await _finish_batch(db, bid)
    # A part checked on its own (a completed single check) is the same part.
    await _set(db, "INSERT INTO trial_checks (user_id, check_id, file_hash, completed, operations) "
                   "VALUES (1, 'single-1', 'single', true, '{}'::jsonb)")
    bid2, items2 = await _batch(db, WORK, 5)
    r = await _reserve(db, WORK, bid2, list(zip(items2, ["a", "b", "c", "single", "d"])))
    assert (r.new, r.reruns) == (1, 4)
    for i, h in zip(items2, ["a", "b", "c", "single", "d"]):
        await _complete(db, WORK, bid2, i, h)
    usage = await ca.catalog_usage(WORK)
    # a, b, c, d counted once each; the single-checked part never counts here.
    assert (usage["used"], usage["remaining"]) == (4, 46)
    # The same file twice in one run takes one slot.
    await _finish_batch(db, bid2)
    bid3, items3 = await _batch(db, WORK, 2)
    r = await _reserve(db, WORK, bid3, list(zip(items3, ["e", "e"])))
    assert (r.new, r.reruns) == (1, 1)


@pytest.mark.asyncio
async def test_failed_and_skipped_parts_give_their_slot_back(db):
    bid, items = await _batch(db, WORK, 3)
    await _reserve(db, WORK, bid, list(zip(items, ["x", "y", "z"])))
    await _complete(db, WORK, bid, items[0], "x")
    await _set(db, "UPDATE batch_items SET status = 'failed' WHERE id = :i", i=items[1])
    await _set(db, "UPDATE batch_items SET status = 'skipped' WHERE id = :i", i=items[2])
    await _finish_batch(db, bid)
    usage = await ca.catalog_usage(WORK)
    assert (usage["used"], usage["reserved"], usage["remaining"]) == (1, 0, 49)
    # The freed part runs again later, taking its slot back once.
    bid2, items2 = await _batch(db, WORK, 1)
    r = await _reserve(db, WORK, bid2, [(items2[0], "y")])
    assert r.new == 1
    await _complete(db, WORK, bid2, items2[0], "y")
    assert (await ca.catalog_usage(WORK))["used"] == 2


@pytest.mark.asyncio
async def test_deleting_a_run_keeps_its_counted_slots(db):
    bid, items = await _batch(db, WORK, 2)
    await _reserve(db, WORK, bid, list(zip(items, ["k1", "k2"])))
    for i, h in zip(items, ["k1", "k2"]):
        await _complete(db, WORK, bid, i, h)
    await _set(db, "DELETE FROM batch_items WHERE batch_id = :b", b=bid)
    await _set(db, "DELETE FROM batches WHERE id = :b", b=bid)
    usage = await ca.catalog_usage(WORK)
    assert (usage["used"], usage["remaining"]) == (2, 48)


@pytest.mark.asyncio
async def test_cancelling_a_run_never_frees_a_part_another_run_checked(db, monkeypatch):
    # Run A reserves X; run B (allowed to start while A runs, for this test)
    # re-runs X for free and completes it; then A is cancelled.
    async def _none(*_a, **_k):
        return None

    monkeypatch.setattr(ca, "active_free_run", _none)
    bid_a, items_a = await _batch(db, WORK, 1)
    await _reserve(db, WORK, bid_a, [(items_a[0], "X")])
    bid_b, items_b = await _batch(db, WORK, 1)
    r = await _reserve(db, WORK, bid_b, [(items_b[0], "X")])
    assert (r.new, r.reruns) == (0, 1)
    await _complete(db, WORK, bid_b, items_b[0], "X")
    await _set(db, "UPDATE batch_items SET status = 'skipped' WHERE id = :i", i=items_a[0])
    await _set(db, "UPDATE batches SET status = 'cancelled' WHERE id = :b", b=bid_a)
    usage = await ca.catalog_usage(WORK)
    assert (usage["used"], usage["remaining"]) == (1, 49)


@pytest.mark.asyncio
async def test_one_free_run_at_a_time(db):
    bid, items = await _batch(db, WORK, 1)
    await _reserve(db, WORK, bid, [(items[0], "first")])
    bid2, items2 = await _batch(db, WORK, 1)
    with pytest.raises(ca.HTTPException) as busy:
        await _reserve(db, WORK, bid2, [(items2[0], "second")])
    assert busy.value.status_code == 409
    assert busy.value.detail["code"] == "catalog_run_active"


@pytest.mark.asyncio
async def test_concurrent_runs_never_spend_more_than_fifty(db, monkeypatch):
    # Lift the one-run-at-a-time rule so only the locked count stands between
    # eight simultaneous runs of ten new parts each and the cap.
    async def _none(*_a, **_k):
        return None

    monkeypatch.setattr(ca, "active_free_run", _none)
    batches = [await _batch(db, WORK, 10) for _ in range(8)]
    results = await asyncio.gather(*(
        _reserve(db, WORK, bid, [(i, f"run{n}-part{k}") for k, i in enumerate(items)])
        for n, (bid, items) in enumerate(batches)
    ), return_exceptions=True)
    admitted = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(admitted) == 5
    assert all(isinstance(r, ca.HTTPException) and r.detail["code"] == "catalog_allowance_exceeded" for r in refused)
    usage = await ca.catalog_usage(WORK)
    assert (usage["reserved"], usage["remaining"]) == (50, 0)


@pytest.mark.asyncio
async def test_personal_email_is_refused_and_pilot_is_unlimited(db):
    from src.auth.require_api_key import AuthedUser

    def user(uid):
        return AuthedUser(user_id=uid, api_key_id=0, key_prefix="session")

    with pytest.raises(ca.HTTPException) as personal:
        await ca.require_catalog_access(user(PERSONAL))
    assert personal.value.status_code == 403
    assert personal.value.detail["code"] == "catalog_run_work_email"
    assert (await ca.catalog_usage(PERSONAL))["eligible"] is False

    access = await ca.require_catalog_access(user(PILOT))
    assert access.cap is None and not access.free
    bid, items = await _batch(db, PILOT, 200, free=False)
    r = await _reserve(db, PILOT, bid, [(i, f"pilot-{n}") for n, i in enumerate(items)])
    assert r.new == 0
    assert (await ca.catalog_usage(PILOT))["unlimited"] is True

    work = await ca.require_catalog_access(user(WORK))
    assert (work.cap, work.free, work.tier) == (50, True, "work")


@pytest.mark.asyncio
async def test_phone_verification_applies_as_for_free_checks(db, monkeypatch):
    from src.auth.require_api_key import AuthedUser

    monkeypatch.setenv("SMS_VERIFICATION_REQUIRED", "1")
    with pytest.raises(ca.HTTPException) as phone:
        await ca.require_catalog_access(AuthedUser(user_id=UNVERIFIED, api_key_id=0, key_prefix="session"))
    assert phone.value.detail["code"] == "phone_verification_required"
    # A verified work account goes through.
    assert (await ca.require_catalog_access(AuthedUser(user_id=WORK, api_key_id=0, key_prefix="session"))).free


@pytest.mark.asyncio
async def test_the_allowance_size_is_an_operator_setting(db, monkeypatch):
    monkeypatch.setenv("FREE_CATALOG_PARTS", "3")
    bid, items = await _batch(db, WORK, 4)
    with pytest.raises(ca.HTTPException) as refused:
        await _reserve(db, WORK, bid, [(i, f"s{n}") for n, i in enumerate(items)])
    assert refused.value.detail["cap"] == 3


@pytest.mark.asyncio
async def test_a_part_counted_in_the_catalog_never_takes_a_single_check(db):
    bid, items = await _batch(db, WORK, 1)
    await _reserve(db, WORK, bid, [(items[0], "catalog-part")])
    await _complete(db, WORK, bid, items[0], "catalog-part")
    before = await vc.user_trial_usage(WORK)
    assert before["catalog"]["used"] == 1
    check = str(uuid4())
    assert await vc.reserve_check(WORK, check, "catalog-part", "analysis") == check
    await vc.finish_check(WORK, check, "analysis", True)
    after = await vc.user_trial_usage(WORK)
    assert (after["used"], after["remaining"]) == (before["used"], before["remaining"])
    # A different file still counts as a check.
    other = str(uuid4())
    await vc.reserve_check(WORK, other, "not-in-catalog", "analysis")
    await vc.finish_check(WORK, other, "analysis", True)
    assert (await vc.user_trial_usage(WORK))["used"] == before["used"] + 1
