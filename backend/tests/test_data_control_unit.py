"""Data control without a database: the 0053 migration contract, share-link
rules, process-cache eviction, and the role gates on the delete routes."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _load_migration():
    mock_op = MagicMock()
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0053_data_control.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0053_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_migration_0053_is_additive_and_downgrade_keeps_off_links_off():
    migration, op = _load_migration()
    assert migration.revision == "0053_data_control"
    assert migration.down_revision == "0052_catalog_allowance"
    assert len(migration.revision) <= 32

    migration.upgrade()
    added = {(c.args[0], c.args[1].name) for c in op.add_column.call_args_list}
    for table in ("analyses", "cost_decisions"):
        for column in ("share_created_at", "share_created_by", "share_expires_at", "share_revoked_at"):
            assert (table, column) in added
    for call in op.add_column.call_args_list:
        assert call.args[1].nullable is True  # additive: every new column is nullable
    (create,) = op.create_table.call_args_list
    assert create.args[0] == "data_deletions"
    sql = " ".join(str(c.args[0]) for c in op.execute.call_args_list)
    assert "now() + interval '30 days'" in sql  # existing links end 30 days after the release
    assert "share.created" in sql  # their maker comes from the audit row that made them

    op.reset_mock()
    migration.downgrade()
    calls = [c[0] for c in op.method_calls]
    first_drop = calls.index("drop_column")
    keep_off = [i for i, c in enumerate(op.method_calls) if c[0] == "execute" and "is_public = FALSE" in str(c.args[0])]
    assert keep_off and keep_off[0] < first_drop
    assert op.drop_table.call_args.args == ("data_deletions",)


def test_model_matches_migration():
    from src.db.models import Analysis, CostDecision, DataDeletion

    for model in (Analysis, CostDecision):
        table = model.__table__
        for column in ("share_created_at", "share_created_by", "share_expires_at", "share_revoked_at"):
            assert table.c[column].nullable is True
        (fk,) = table.c.share_created_by.foreign_keys
        assert fk.ondelete == "SET NULL"
    table = DataDeletion.__table__
    assert not table.c.org_id.foreign_keys  # the receipt outlives the organization
    (fk,) = table.c.requested_by.foreign_keys
    assert fk.ondelete == "SET NULL"


def _row(**kw):
    base = dict(share_short_id="abc", is_public=True, share_revoked_at=None, share_expires_at=None,
                share_created_at=datetime.now(timezone.utc), share_created_by=1, user_id=1, org_id="o")
    base.update(kw)
    return SimpleNamespace(**base)


def test_share_status_and_public_answers():
    from src.services import share_links as sl

    now = datetime.now(timezone.utc)
    assert sl.status(_row(share_short_id=None)) is None
    assert sl.status(_row()) == "active"
    assert sl.status(_row(share_expires_at=now + timedelta(days=1))) == "active"
    assert sl.status(_row(share_expires_at=now - timedelta(seconds=1))) == "expired"
    assert sl.status(_row(share_revoked_at=now)) == "off"
    assert sl.status(_row(is_public=False)) == "off"
    # Switched off wins over expired.
    assert sl.status(_row(share_revoked_at=now, share_expires_at=now - timedelta(days=1))) == "off"
    naive = (now - timedelta(days=1)).replace(tzinfo=None)
    assert sl.status(_row(share_expires_at=naive)) == "expired"

    with pytest.raises(HTTPException) as gone:
        sl.public_or_raise(_row(share_expires_at=now - timedelta(days=1)), "nf")
    assert gone.value.status_code == 410 and gone.value.detail["code"] == "share_expired"
    with pytest.raises(HTTPException) as off:
        sl.public_or_raise(_row(share_revoked_at=now), "nf")
    assert off.value.status_code == 410 and off.value.detail["code"] == "share_switched_off"
    with pytest.raises(HTTPException) as nf:
        sl.public_or_raise(None, "nf")
    assert nf.value.status_code == 404

    fields = sl.fields(_row(share_created_at=None, share_expires_at=now + timedelta(days=30)))
    assert fields["share_end_date_added"] is True and fields["is_public"] is True
    ended = sl.fields(_row(share_expires_at=now - timedelta(days=1)))
    assert ended["is_public"] is False and ended["share_url"] is None and ended["share_status"] == "expired"


def test_share_options_accept_only_the_offered_choices():
    from pydantic import ValidationError

    from src.services.share_links import ShareOptions

    assert ShareOptions().expires_in_days == 30
    assert ShareOptions(expires_in_days=None).expires_in_days is None
    for days in (30, 90, 365):
        assert ShareOptions(expires_in_days=days).expires_in_days == days
    for bad in (0, 1, 45, 366, -30):
        with pytest.raises(ValidationError):
            ShareOptions(expires_in_days=bad)


def test_open_and_close_link():
    from src.services import share_links as sl

    row = _row(share_short_id=None, is_public=False, share_created_at=None, share_created_by=None)
    sl.open_link(row, 7, 90, "new123")
    assert row.share_short_id == "new123" and row.is_public and row.share_created_by == 7
    assert timedelta(days=89, hours=23) < row.share_expires_at - datetime.now(timezone.utc) <= timedelta(days=90)
    sl.open_link(row, 7, None, "new456")
    assert row.share_expires_at is None
    sl.close_link(row)
    assert row.share_revoked_at is not None and row.share_short_id == "new456" and sl.status(row) == "off"
    assert sl.made_by(_row(share_created_by=None, user_id=9)) == 9


def test_process_caches_forget_a_deleted_hash():
    import trimesh

    from src.parsers import mesh_cache
    from src.services import part_geometry_cache as pgc

    pgc.clear()
    gone, kept = "a" * 64, "b" * 64
    for h in (gone, kept):
        pgc._entries[(1, h, "f.stl", "mm")] = pgc.AnalysedPart(None, MagicMock(), None, None, ".stl", 10)
    assert pgc.forget_hashes({gone}) == 1
    assert [k[1] for k in pgc._entries] == [kept]
    pgc.clear()

    cache = mesh_cache.MeshParseCache()
    cache.put((gone, ".stl"), trimesh.creation.box())
    cache.put((kept, ".stl"), trimesh.creation.box())
    before = cache.total_bytes
    assert cache.forget_hashes({gone}) == 1
    assert (gone, ".stl") not in cache and (kept, ".stl") in cache
    assert cache.total_bytes < before


def test_forget_cached_drops_one_org_part_views():
    from src.api import part_orientation, part_preview
    from src.services.data_deletion_service import forget_cached

    part_preview._cache.clear()
    part_orientation._cache.clear()
    part_preview._cache[("A", "h1", "mm")] = (b"g", {})
    part_preview._cache[("A", "h2", "mm")] = (b"g", {})
    part_preview._cache[("B", "h1", "mm")] = (b"g", {})
    part_orientation._cache[("A", "h1", "mm", None)] = {}
    forget_cached("A", ["h1"])
    assert set(part_preview._cache) == {("A", "h2", "mm"), ("B", "h1", "mm")}
    assert not part_orientation._cache
    forget_cached("A", None)
    assert set(part_preview._cache) == {("B", "h1", "mm")}
    part_preview._cache.clear()


def test_a_cached_3d_view_is_not_served_once_the_source_is_gone(tmp_path, monkeypatch):
    """Another API process deleted the part: this process's cached GLB must not answer."""
    import asyncio
    import shutil

    import trimesh

    from src.api import part_preview
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.services.source_artifact_service import save_source_artifact

    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))
    monkeypatch.setattr("src.auth.rbac.lookup_org_membership", AsyncMock(return_value=("ORGA", "viewer")))
    part_preview._cache.clear()
    raw = trimesh.creation.box(extents=[10, 10, 10]).export(file_type="stl")
    digest = hashlib.sha256(raw).hexdigest()
    asyncio.run(save_source_artifact("ORGA", digest, "cube.stl", raw))

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(part_preview.router, prefix="/api/v1/parts")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=1, api_key_id=0, key_prefix="session", role="viewer"
    )
    client = TestClient(app)
    assert client.get(f"/api/v1/parts/{digest}/preview.glb").status_code == 200
    assert part_preview._cache
    shutil.rmtree(tmp_path / "objects" / "source-artifacts" / "ORGA" / digest)
    assert client.get(f"/api/v1/parts/{digest}/preview.glb").status_code == 404
    assert not part_preview._cache


def _gate_app(role: str, org_role: str) -> TestClient:
    from src.api import data_control
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(data_control.parts_router, prefix="/api/v1/parts")
    app.include_router(data_control.router, prefix="/api/v1")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=7, api_key_id=0, key_prefix="session", role=role
    )

    async def _session():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _session
    return app


@pytest.mark.parametrize(
    "role,org_role",
    [("viewer", "admin"), ("analyst", "viewer"), ("auditor", "member")],
)
def test_read_only_callers_cannot_delete(role, org_role, monkeypatch):
    from src.services import data_deletion_service as svc

    for name in ("delete_part", "delete_organization"):
        monkeypatch.setattr(svc, name, AsyncMock())
    with patch("src.auth.rbac.lookup_org_membership", new=AsyncMock(return_value=("org-a", org_role))):
        client = TestClient(_gate_app(role, org_role), raise_server_exceptions=False)
        r = client.delete(f"/api/v1/parts/{'a' * 64}")
        assert r.status_code == 403, r.text
        r = client.post("/api/v1/orgs/current/delete", json={"confirm_name": "x"})
        assert r.status_code == 403, r.text
    svc.delete_part.assert_not_awaited()
    svc.delete_organization.assert_not_awaited()


def test_a_member_cannot_delete_the_organization(monkeypatch):
    from src.services import data_deletion_service as svc

    monkeypatch.setattr(svc, "delete_organization", AsyncMock())
    with patch("src.auth.rbac.lookup_org_membership", new=AsyncMock(return_value=("org-a", "member"))):
        client = TestClient(_gate_app("analyst", "member"), raise_server_exceptions=False)
        assert client.post("/api/v1/orgs/current/delete", json={"confirm_name": "x"}).status_code == 403
        assert client.get("/api/v1/orgs/current/deletion-preview").status_code == 403
    svc.delete_organization.assert_not_awaited()


def test_a_superadmin_without_membership_cannot_delete_an_org(monkeypatch):
    from src.services import data_deletion_service as svc

    monkeypatch.setattr(svc, "delete_organization", AsyncMock())
    with patch("src.auth.rbac.lookup_org_membership", new=AsyncMock(return_value=None)):
        client = TestClient(_gate_app("superadmin", "admin"), raise_server_exceptions=False)
        assert client.post("/api/v1/orgs/current/delete", json={"confirm_name": "x"}).status_code == 403
    svc.delete_organization.assert_not_awaited()


def test_unsafe_steps_are_refused():
    from src.services.data_deletion_service import _run_step_sync

    with pytest.raises(ValueError):
        _run_step_sync("org", {"kind": "prefix", "store": "source-artifacts", "value": "../other"})
    with pytest.raises(ValueError):
        _run_step_sync("org", {"kind": "nope"})
