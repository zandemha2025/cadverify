"""W3.5 rung-1 declared part-context — pure validators + mocked-session adapters.

No live DB: the validation / annualization logic is pure, and the insert-vs-
update adapter path is exercised with a lightweight fake session (mirrors the
repo's mocked-session convention in ``test_rate_library``). The Postgres CRUD
lifecycle + tenant isolation is covered by the DATABASE_URL-guarded
``test_part_context_api.py``.

Honesty pins: a non-positive declared count is rejected (never silently stored),
and an annualized $/year is None unless a real annual_volume was declared (never
a fabricated demand quantity).
"""
from __future__ import annotations

import pytest

from src.db.models import PartContext
from src.services import part_context_service as svc


# ---------------------------------------------------------------------------
# validate_context — reject non-positive declared counts
# ---------------------------------------------------------------------------


def test_validate_accepts_positive_and_strings_and_none():
    # All optional; positive counts, strings, and omitted fields all pass.
    svc.validate_context({})  # no raise
    svc.validate_context({"program": "Zoox", "parent_assembly": "chassis"})
    svc.validate_context({"units_per_parent": 4, "annual_volume": 12000})
    svc.validate_context({"units_per_parent": None, "annual_volume": None})


@pytest.mark.parametrize("field", ["units_per_parent", "annual_volume"])
@pytest.mark.parametrize("bad", [0, -1, -1000])
def test_validate_rejects_non_positive(field, bad):
    with pytest.raises(ValueError):
        svc.validate_context({field: bad})


@pytest.mark.parametrize("field", ["units_per_parent", "annual_volume"])
def test_validate_rejects_non_int(field):
    with pytest.raises(ValueError):
        svc.validate_context({field: 3.5})
    # bool is not an honest integer count
    with pytest.raises(ValueError):
        svc.validate_context({field: True})


# ---------------------------------------------------------------------------
# annualized_cost — None without a declared volume, product with it
# ---------------------------------------------------------------------------


def test_annualized_cost_none_without_volume():
    # No declared annual_volume → None (NEVER a fabricated demand quantity).
    assert svc.annualized_cost(12.5, None) is None


def test_annualized_cost_none_without_unit_cost():
    # No unit cost to annualize (e.g. a DFM-withheld price) → None.
    assert svc.annualized_cost(None, 1000) is None


def test_annualized_cost_product_with_volume():
    assert svc.annualized_cost(12.5, 1000) == 12500.0
    assert svc.annualized_cost(2.5, 4) == 10.0


# ---------------------------------------------------------------------------
# upsert_context — insert vs update on a mocked session
# ---------------------------------------------------------------------------


class _FakeSingleResult:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    """Minimal async session: ``execute`` returns the same (optional) existing
    row; ``add`` records an insert; ``flush`` is counted."""

    def __init__(self, existing=None):
        self._existing = existing
        self.added = None
        self.flush_calls = 0

    async def execute(self, _stmt):
        return _FakeSingleResult(self._existing)

    def add(self, row):
        self.added = row

    async def flush(self):
        self.flush_calls += 1


@pytest.mark.asyncio
async def test_upsert_inserts_when_absent():
    sess = _FakeSession(existing=None)
    fields = {"program": "Zoox", "units_per_parent": 4, "annual_volume": 12000}
    row = await svc.upsert_context(sess, "org-a", "mesh-1", fields, created_by=7)
    # a brand-new row was added and populated from the declared fields
    assert sess.added is row
    assert row.org_id == "org-a" and row.mesh_hash == "mesh-1"
    assert row.program == "Zoox"
    assert row.units_per_parent == 4
    assert row.annual_volume == 12000
    assert row.created_by == 7
    assert sess.flush_calls == 1


@pytest.mark.asyncio
async def test_upsert_updates_existing_row_in_place():
    existing = PartContext(org_id="org-a", mesh_hash="mesh-1", created_by=1)
    existing.program = "OldProgram"
    existing.parent_assembly = "pump skid"
    existing.units_per_parent = 2
    existing.annual_volume = 500
    existing.service_environment = {"max_temp_c": 90, "sour_service": True}
    sess = _FakeSession(existing=existing)

    row = await svc.upsert_context(
        sess,
        "org-a",
        "mesh-1",
        {"program": "NewProgram", "annual_volume": 9000},
        created_by=99,
    )
    # updated the SAME row in place — no insert
    assert row is existing
    assert sess.added is None
    assert row.program == "NewProgram"
    assert row.annual_volume == 9000
    # omitted fields are preserved: Verify can refresh service-world context
    # without erasing the user's declared parent assembly / demand context.
    assert row.parent_assembly == "pump skid"
    assert row.units_per_parent == 2
    assert row.service_environment == {"max_temp_c": 90, "sour_service": True}
    # created_by is not overwritten on update (stamped at insert)
    assert row.created_by == 1
    assert sess.flush_calls == 1


@pytest.mark.asyncio
async def test_upsert_explicit_null_clears_existing_declared_field():
    existing = PartContext(org_id="org-a", mesh_hash="mesh-1", created_by=1)
    existing.program = "OldProgram"
    existing.parent_assembly = "pump skid"
    existing.units_per_parent = 2
    existing.annual_volume = 500
    sess = _FakeSession(existing=existing)

    row = await svc.upsert_context(
        sess,
        "org-a",
        "mesh-1",
        {"parent_assembly": None, "annual_volume": None},
        created_by=99,
    )

    assert row is existing
    assert row.program == "OldProgram"
    assert row.parent_assembly is None
    assert row.units_per_parent == 2
    assert row.annual_volume is None
    assert sess.flush_calls == 1


@pytest.mark.asyncio
async def test_upsert_rejects_non_positive_before_touching_session():
    sess = _FakeSession(existing=None)
    with pytest.raises(ValueError):
        await svc.upsert_context(sess, "org-a", "mesh-1", {"annual_volume": 0})
    assert sess.added is None
    assert sess.flush_calls == 0


# ---------------------------------------------------------------------------
# serialize_context — provenance is always "user"
# ---------------------------------------------------------------------------


def test_serialize_context_provenance_user():
    row = PartContext(org_id="org-a", mesh_hash="mesh-1")
    row.program = "Zoox"
    row.parent_assembly = "chassis"
    row.units_per_parent = 4
    row.annual_volume = 12000
    out = svc.serialize_context(row)
    assert out == {
        "mesh_hash": "mesh-1",
        "program": "Zoox",
        "parent_assembly": "chassis",
        "units_per_parent": 4,
        "annual_volume": 12000,
        "provenance": "user",
    }
