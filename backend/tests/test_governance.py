"""W4 governance change-request flow — pure/mocked logic (no live DB).

The propose/approve/reject state machine and its guards are exercised with a
lightweight fake session and monkeypatched library adapters (mirrors the repo's
mocked-session convention in ``test_rate_library.py``). The Postgres CRUD
lifecycle — a real draft proposed, approved-and-published, or rejected — is
covered by the DATABASE_URL-guarded ``test_governance_api.py``.

Load-bearing guarantees asserted here:
  * ``propose`` refuses a missing (404) or non-draft (400) target.
  * ``approve``/``reject`` are the only two transitions out of ``proposed`` and
    are terminal (a second decision is a 409).
  * ``approve`` delegates to the library's real ``publish_version`` (governance
    gates WHO publishes; it never reimplements the publish).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.services import governance_service as svc
from src.services import rate_library_service, shop_library_service

UTC = timezone.utc


class _FakeSession:
    """Records ``add``; ``flush`` is a no-op. ``execute`` is unused because the
    transition tests monkeypatch ``svc.get_request`` directly."""

    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None


def _cr(**kw):
    base = dict(
        id=1,
        ulid="cr-ulid",
        org_id="orgA",
        asset_type=svc.ASSET_RATE_CARD,
        target_version_id=7,
        status="proposed",
        title="Bump labor rate",
        note="",
        proposed_by=10,
        reviewed_by=None,
        created_at=datetime.now(UTC),
        decided_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# propose guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_rejects_missing_target(monkeypatch):
    async def _get_version(session, org_id, vid):
        return None

    monkeypatch.setattr(rate_library_service, "get_version", _get_version)
    with pytest.raises(HTTPException) as ei:
        await svc.propose(_FakeSession(), "orgA", svc.ASSET_RATE_CARD, 99)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_propose_rejects_non_draft_target(monkeypatch):
    async def _get_version(session, org_id, vid):
        return SimpleNamespace(status="published")

    monkeypatch.setattr(rate_library_service, "get_version", _get_version)
    with pytest.raises(HTTPException) as ei:
        await svc.propose(_FakeSession(), "orgA", svc.ASSET_RATE_CARD, 7)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_propose_rejects_unknown_asset_type():
    with pytest.raises(HTTPException) as ei:
        await svc.propose(_FakeSession(), "orgA", "widget", 7)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_propose_creates_proposed_and_dispatches_by_asset_type(monkeypatch):
    seen = {}

    async def _get_version(session, org_id, vid):
        seen["called"] = (org_id, vid)
        return SimpleNamespace(status="draft")

    # Dispatch must go to the SHOP library for a shop_profile asset_type.
    monkeypatch.setattr(shop_library_service, "get_version", _get_version)
    sess = _FakeSession()
    row = await svc.propose(
        sess,
        "orgA",
        svc.ASSET_SHOP_PROFILE,
        7,
        title="new shop calibration",
        proposed_by=10,
    )
    assert seen["called"] == ("orgA", 7)
    assert row.status == "proposed"
    assert row.asset_type == svc.ASSET_SHOP_PROFILE
    assert row.target_version_id == 7
    assert row.proposed_by == 10
    assert row in sess.added


# ---------------------------------------------------------------------------
# approve / reject transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_publishes_and_marks_approved(monkeypatch):
    cr = _cr(status="proposed", asset_type=svc.ASSET_RATE_CARD)
    published = SimpleNamespace(id=7, status="published")
    calls = {}

    async def _get_request(session, org_id, rid):
        return cr

    async def _publish(session, org_id, vid):
        calls["publish"] = (org_id, vid)
        return published

    monkeypatch.setattr(svc, "get_request", _get_request)
    monkeypatch.setattr(rate_library_service, "publish_version", _publish)

    row, pub = await svc.approve(_FakeSession(), "orgA", 1, reviewer_id=20)
    # Governance delegated to the REAL publish path with the target draft's id.
    assert calls["publish"] == ("orgA", 7)
    assert pub is published
    assert row.status == "approved"
    assert row.reviewed_by == 20
    assert row.decided_at is not None


@pytest.mark.asyncio
async def test_approve_aborts_if_publish_fails(monkeypatch):
    """A publish failure surfaces and the request is NOT marked approved."""
    cr = _cr(status="proposed")

    async def _get_request(session, org_id, rid):
        return cr

    async def _publish(session, org_id, vid):
        raise HTTPException(status_code=409, detail="version already published")

    monkeypatch.setattr(svc, "get_request", _get_request)
    monkeypatch.setattr(rate_library_service, "publish_version", _publish)

    with pytest.raises(HTTPException) as ei:
        await svc.approve(_FakeSession(), "orgA", 1, reviewer_id=20)
    assert ei.value.status_code == 409
    assert cr.status == "proposed"  # unchanged
    assert cr.decided_at is None


@pytest.mark.asyncio
async def test_reject_marks_rejected_and_leaves_draft(monkeypatch):
    cr = _cr(status="proposed", note="orig")

    async def _get_request(session, org_id, rid):
        return cr

    # publish_version must NOT be called on reject — make it explode if it is.
    async def _boom(*a, **k):
        raise AssertionError("reject must never publish")

    monkeypatch.setattr(svc, "get_request", _get_request)
    monkeypatch.setattr(rate_library_service, "publish_version", _boom)

    row = await svc.reject(
        _FakeSession(), "orgA", 1, reviewer_id=20, note="stale numbers"
    )
    assert row.status == "rejected"
    assert row.reviewed_by == 20
    assert row.decided_at is not None
    assert "stale numbers" in row.note


@pytest.mark.asyncio
@pytest.mark.parametrize("decided", ["approved", "rejected"])
async def test_cannot_decide_an_already_decided_request(monkeypatch, decided):
    cr = _cr(status=decided)

    async def _get_request(session, org_id, rid):
        return cr

    monkeypatch.setattr(svc, "get_request", _get_request)

    with pytest.raises(HTTPException) as ei:
        await svc.approve(_FakeSession(), "orgA", 1, reviewer_id=20)
    assert ei.value.status_code == 409

    with pytest.raises(HTTPException) as ei2:
        await svc.reject(_FakeSession(), "orgA", 1, reviewer_id=20)
    assert ei2.value.status_code == 409


@pytest.mark.asyncio
async def test_decide_missing_request_is_404(monkeypatch):
    async def _get_request(session, org_id, rid):
        return None

    monkeypatch.setattr(svc, "get_request", _get_request)
    with pytest.raises(HTTPException) as ei:
        await svc.approve(_FakeSession(), "orgA", 999, reviewer_id=20)
    assert ei.value.status_code == 404


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------


def test_serialize_request_shape():
    ts = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    cr = _cr(status="approved", reviewed_by=20, decided_at=ts, created_at=ts)
    out = svc.serialize_request(cr)
    assert out == {
        "id": 1,
        "ulid": "cr-ulid",
        "org_id": "orgA",
        "asset_type": "rate_card",
        "target_version_id": 7,
        "status": "approved",
        "title": "Bump labor rate",
        "note": "",
        "proposed_by": 10,
        "reviewed_by": 20,
        "created_at": ts.isoformat(),
        "decided_at": ts.isoformat(),
    }
