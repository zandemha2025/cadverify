"""W4 governed materials-library — pure logic, validation, and resolution/cache.

No live DB: the versioning / effective-dating / validation logic is pure and the
DB-adapter resolution path is exercised with a lightweight fake session (mirrors
the repo's mocked-session convention). The Postgres CRUD lifecycle is covered by
the DATABASE_URL-guarded ``test_material_library_api.py``.

The load-bearing guarantee: with the flag OFF (default) and/or no governed
catalog, the cost path is BYTE-IDENTICAL to pre-W4 (``resolve`` returns None so
nothing is overlaid).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.costing.rates import RATE_CARD_V0
from src.services import material_library_service as svc


UTC = timezone.utc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _row(version, status, effective_from, effective_to):
    return SimpleNamespace(
        version=version,
        status=status,
        effective_from=effective_from,
        effective_to=effective_to,
    )


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    """Minimal async session: every execute returns the same published rows."""

    def __init__(self, rows):
        self._rows = rows
        self.execute_calls = 0

    async def execute(self, _stmt):
        self.execute_calls += 1
        return _FakeResult(self._rows)


# ---------------------------------------------------------------------------
# flag
# ---------------------------------------------------------------------------


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("MATERIAL_LIBRARY_ENABLED", raising=False)
    assert svc.material_library_enabled() is False


def test_flag_on(monkeypatch):
    for v in ("1", "true", "on", "YES"):
        monkeypatch.setenv("MATERIAL_LIBRARY_ENABLED", v)
        assert svc.material_library_enabled() is True
    monkeypatch.setenv("MATERIAL_LIBRARY_ENABLED", "0")
    assert svc.material_library_enabled() is False


# ---------------------------------------------------------------------------
# default payload + validation
# ---------------------------------------------------------------------------


def test_default_payload_seeds_from_rate_card_and_is_deep_copy():
    p = svc.default_material_payload()
    assert p["material_prices"] == RATE_CARD_V0.get("material_prices", {})
    assert p["materials"] == {}
    # mutating the seed must not touch the canonical rate card
    p["material_prices"]["PA12 (Nylon 12)"] = 999.0
    assert "PA12 (Nylon 12)" not in RATE_CARD_V0.get("material_prices", {})


def test_validate_accepts_real_material_prices():
    svc.validate_material_payload(
        {
            "material_prices": {"PA12 (Nylon 12)": 24.5, "@aluminum": 12.0},
            "materials": {"PA12 (Nylon 12)": {"family": "polymer", "density_g_cm3": 1.01}},
        }
    )  # no raise


def test_validate_accepts_default_seed():
    svc.validate_material_payload(svc.default_material_payload())  # no raise (empty ok)


@pytest.mark.parametrize("bad", [None, [], "x", 3, {}])
def test_validate_rejects_non_catalog(bad):
    with pytest.raises(ValueError):
        svc.validate_material_payload(bad)


def test_validate_rejects_negative_price():
    with pytest.raises(ValueError):
        svc.validate_material_payload({"material_prices": {"@polymer": -5.0}})


def test_validate_rejects_zero_price():
    with pytest.raises(ValueError):
        svc.validate_material_payload({"material_prices": {"@polymer": 0}})


@pytest.mark.parametrize("bad", ["12.0", None, [1], {"x": 1}])
def test_validate_rejects_non_numeric_price(bad):
    with pytest.raises(ValueError):
        svc.validate_material_payload({"material_prices": {"@polymer": bad}})


def test_validate_rejects_bool_price():
    # bool is an int subclass — must not slip through as a "number"
    with pytest.raises(ValueError):
        svc.validate_material_payload({"material_prices": {"@polymer": True}})


def test_validate_rejects_non_string_key():
    with pytest.raises(ValueError):
        svc.validate_material_payload({"material_prices": {5: 10.0}})


def test_validate_rejects_bad_materials_type():
    with pytest.raises(ValueError):
        svc.validate_material_payload(
            {"material_prices": {"@polymer": 10.0}, "materials": [1, 2]}
        )


# ---------------------------------------------------------------------------
# effective-date resolution (pure)
# ---------------------------------------------------------------------------


def test_select_effective_empty():
    assert svc.select_effective([], datetime.now(UTC)) is None


def test_select_effective_ignores_drafts():
    now = datetime.now(UTC)
    assert svc.select_effective([_row(1, "draft", None, None)], now) is None


def test_select_effective_single_open():
    now = datetime.now(UTC)
    r = _row(1, "published", now - timedelta(days=1), None)
    assert svc.select_effective([r], now) is r


def test_select_effective_superseded_timeline():
    now = datetime.now(UTC)
    switch = now - timedelta(hours=1)
    v1 = _row(1, "published", now - timedelta(days=2), switch)
    v2 = _row(2, "published", switch, None)
    assert svc.select_effective([v1, v2], now) is v2
    assert svc.select_effective([v1, v2], switch - timedelta(minutes=1)) is v1


def test_select_effective_to_boundary_is_exclusive():
    now = datetime.now(UTC)
    r = _row(1, "published", now - timedelta(days=1), now)
    assert svc.select_effective([r], now) is None


def test_select_effective_ignores_archived():
    now = datetime.now(UTC)
    archived = _row(2, "archived", now - timedelta(days=1), None)
    published = _row(1, "published", now - timedelta(days=1), None)
    assert svc.select_effective([archived], now) is None
    assert svc.select_effective([published, archived], now) is published


# ---------------------------------------------------------------------------
# resolution + cache (fake session)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_none_when_flag_off(monkeypatch):
    monkeypatch.delenv("MATERIAL_LIBRARY_ENABLED", raising=False)
    sess = _FakeSession(
        [_row(1, "published", datetime.now(UTC) - timedelta(days=1), None)]
    )
    out = await svc.resolve_material_overrides_for(sess, "org_x")
    assert out is None
    assert sess.execute_calls == 0  # never touches the DB when flag is off


@pytest.mark.asyncio
async def test_resolve_none_without_org(monkeypatch):
    monkeypatch.setenv("MATERIAL_LIBRARY_ENABLED", "1")
    sess = _FakeSession([])
    assert await svc.resolve_material_overrides_for(sess, None) is None
    assert await svc.resolve_material_overrides_for(sess, "") is None


@pytest.mark.asyncio
async def test_resolve_returns_payload_and_caches(monkeypatch):
    monkeypatch.setenv("MATERIAL_LIBRARY_ENABLED", "1")
    svc.invalidate("org_cache")
    payload = {"material_prices": {"@polymer": 21.0}, "materials": {}}
    row = SimpleNamespace(
        version=3,
        status="published",
        effective_from=datetime.now(UTC) - timedelta(days=1),
        effective_to=None,
        payload=payload,
    )
    sess = _FakeSession([row])
    out1 = await svc.resolve_material_overrides_for(sess, "org_cache")
    assert out1 is payload
    assert sess.execute_calls == 1
    # second call within the effective window is served from cache (no new query)
    out2 = await svc.resolve_material_overrides_for(sess, "org_cache")
    assert out2 is payload
    assert sess.execute_calls == 1
    svc.invalidate("org_cache")


@pytest.mark.asyncio
async def test_resolve_none_when_no_published_in_effect(monkeypatch):
    monkeypatch.setenv("MATERIAL_LIBRARY_ENABLED", "1")
    svc.invalidate("org_future")
    # published but effective_from in the future — not in effect now
    row = SimpleNamespace(
        version=1,
        status="published",
        effective_from=datetime.now(UTC) + timedelta(days=1),
        effective_to=None,
        payload={"material_prices": {"@polymer": 21.0}},
    )
    sess = _FakeSession([row])
    assert await svc.resolve_material_overrides_for(sess, "org_future") is None


# ---------------------------------------------------------------------------
# CRUD guards (mocked session, no live DB)
# ---------------------------------------------------------------------------


class _FakeSingleResult:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _FakeRowSession:
    def __init__(self, row):
        self._row = row
        self.deleted = None
        self.flush_calls = 0

    async def execute(self, _stmt):
        return _FakeSingleResult(self._row)

    async def delete(self, row):
        self.deleted = row

    async def flush(self):
        self.flush_calls += 1


@pytest.mark.asyncio
async def test_discard_draft_ok():
    row = SimpleNamespace(status="draft")
    sess = _FakeRowSession(row)
    out = await svc.discard_draft(sess, "org1", 1)
    assert out is row and sess.deleted is row and sess.flush_calls == 1


@pytest.mark.asyncio
async def test_discard_published_raises_409():
    sess = _FakeRowSession(SimpleNamespace(status="published"))
    with pytest.raises(HTTPException) as ei:
        await svc.discard_draft(sess, "org1", 1)
    assert ei.value.status_code == 409 and sess.deleted is None


@pytest.mark.asyncio
async def test_archive_in_effect_raises_409():
    now = datetime.now(UTC)
    row = SimpleNamespace(
        status="published",
        effective_from=now - timedelta(days=1),
        effective_to=None,
    )
    sess = _FakeRowSession(row)
    with pytest.raises(HTTPException) as ei:
        await svc.archive_version(sess, "org1", 1)
    assert ei.value.status_code == 409 and row.status == "published"


@pytest.mark.asyncio
async def test_archive_superseded_ok():
    now = datetime.now(UTC)
    row = SimpleNamespace(
        status="published",
        effective_from=now - timedelta(days=2),
        effective_to=now - timedelta(hours=1),
    )
    sess = _FakeRowSession(row)
    out = await svc.archive_version(sess, "org1", 1)
    assert out is row and row.status == "archived"


# ---------------------------------------------------------------------------
# serialization honesty
# ---------------------------------------------------------------------------


def test_serialize_is_never_validated():
    row = SimpleNamespace(
        id=1,
        ulid="u",
        version=1,
        name="n",
        status="published",
        change_note="",
        effective_from=None,
        effective_to=None,
        created_by=None,
        created_at=None,
        published_at=None,
        payload={"material_prices": {"@polymer": 10.0}},
    )
    out = svc.serialize_version(row)
    assert out["provenance"] == "default" and out["validated"] is False
    assert "payload" not in out
    out2 = svc.serialize_version(row, include_payload=True)
    assert out2["payload"] == {"material_prices": {"@polymer": 10.0}}
