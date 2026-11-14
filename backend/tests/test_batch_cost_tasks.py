"""Unit tests for the W3 cost path in run_batch_item (mock style of
test_batch_tasks).

Covers: cost-item happy path (persist + link + counters + webhook extras),
GEOMETRY_INVALID → failed item (no persist, no crash), dedup-conflict reuse (the
item points at whatever row persist_cost_decision returns), and the DFM
regression (job_type='dfm' hits run_analysis, never the cost compute).
"""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from src.db.models import Batch, BatchItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_batch(job_type: str = "cost", webhook_url: str | None = None) -> MagicMock:
    batch = MagicMock(spec=Batch)
    batch.id = 1
    batch.ulid = "01BATCH00000000000001"
    batch.user_id = 42
    batch.org_id = "org-a"
    batch.status = "processing"
    batch.job_type = job_type
    batch.input_mode = "zip"
    batch.total_items = 1
    batch.completed_items = 0
    batch.failed_items = 0
    batch.concurrency_limit = 10
    batch.webhook_url = webhook_url
    batch.webhook_secret = "secret" if webhook_url else None
    batch.api_key_id = 1
    batch.manifest_json = None
    return batch


def _make_item() -> MagicMock:
    item = MagicMock(spec=BatchItem)
    item.id = 1
    item.ulid = "01ITEM000000000000001"
    item.batch_id = 1
    item.org_id = "org-a"
    item.filename = "part1.stl"
    item.status = "queued"
    item.priority = "normal"
    item.process_types = None
    item.rule_pack = None
    item.analysis_id = None
    item.cost_decision_id = None
    item.quantities = None
    item.region = None
    item.material_class = None
    item.shop = None
    item.error_message = None
    item.duration_ms = None
    return item


def _mock_session_factory(session):
    factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = ctx
    return factory


def _session_returning(item, batch):
    """A session.execute that returns item, then batch, then None (the load
    order run_batch_item uses)."""
    call_count = 0

    async def execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars = MagicMock()
        if call_count == 1:
            scalars.first.return_value = item
        elif call_count == 2:
            scalars.first.return_value = batch
        else:
            scalars.first.return_value = None
        result.scalars.return_value = scalars
        return result

    return execute


def _result_dict(*, make_now="cnc_3axis", dfm_ready=True, blockers=None):
    """A report_to_dict-shaped cost artifact with a make-now estimate."""
    return {
        "quantities": [50, 5000],
        "decision": {
            "make_now_process": make_now,
            "make_now_material": "aluminum_6061",
            "crossover_qty": 1200.0,
            "recommendation": {
                "50": {"process": make_now, "unit_cost_usd": 40.0},
                "5000": {"process": make_now, "unit_cost_usd": 30.0},
            },
            "if_redesigned": {
                "50": None,
                "5000": {"process": "injection_molding", "unit_cost_usd": 6.0,
                         "caveat": "invest in tooling"},
            },
        },
        "estimates": [
            {
                "process": make_now,
                "material": "aluminum_6061",
                "quantity": 50,
                "unit_cost_usd": 40.0,
                "dfm_ready": dfm_ready,
                "dfm_blockers": blockers or [],
                "confidence": {"validated": False},
                "drivers": [
                    {"name": "machine_rate", "provenance": "DEFAULT", "source": "generic"},
                ],
            }
        ],
    }


def _patches(*, report_dict, saved, geometry_invalid=False, reason=None):
    """Patch the cost-compute + persistence seams _run_cost_item depends on."""
    status = "GEOMETRY_INVALID" if geometry_invalid else "OK"
    stub_report = SimpleNamespace(status=status, reason=reason)

    import src.jobs.batch_tasks as bt_mod
    import src.costing as costing_mod
    import src.services.analysis_service as as_mod
    import src.services.batch_service as bs_mod
    import src.services.cost_context_service as ccs_mod
    import src.services.cost_decision_service as cds_mod

    return [
        patch.object(bt_mod, "_compute_cost_report",
                     return_value=(stub_report, ".stl")),
        patch.object(costing_mod, "report_to_dict", return_value=report_dict),
        patch.object(ccs_mod, "bind_cost_org_context", new_callable=AsyncMock),
        patch.object(as_mod, "compute_mesh_hash", return_value="meshhash123"),
        patch.object(bs_mod, "update_batch_counters", new_callable=AsyncMock),
        patch.object(cds_mod, "persist_cost_decision", new_callable=AsyncMock,
                     return_value=saved),
    ]


@pytest.mark.asyncio
async def test_batch_and_live_cost_bind_identical_org_context(monkeypatch):
    """The same part + overlapping request params must reach the engine with
    identical options in the live route and the background batch worker."""
    from src.api import routes
    from src.auth.require_api_key import AuthedUser
    from src.jobs import batch_tasks

    monkeypatch.setenv("COST_PERSIST_ENABLED", "false")
    monkeypatch.setenv("COST_ENSEMBLE_ENABLED", "0")

    session = AsyncMock()
    session.commit = AsyncMock()
    batch = _make_batch(job_type="cost")
    item = _make_item()
    item.shop = "org-governed-only"
    file_bytes = b"same-cad-bytes"

    inventory = [object()]
    shop_caps = object()
    residual_model = object()
    calibration = object()
    stored_environment = {"sour_service": True}
    governed_rates = {
        "global": {},
        "process": {},
        "material_prices": {"polymer": 2.0},
        "materials": {"polymer": {"label": "base"}},
    }
    material_overlay = {
        "material_prices": {"polymer": 7.5},
        "materials": {"polymer": {"label": "governed"}},
    }
    governed_shop = {
        "name": "Org Governed Only",
        "region": "US",
        "labor_rate": 47.0,
    }

    report = SimpleNamespace(
        status="OK",
        reason=None,
        geometry={},
        decision=SimpleNamespace(
            make_now_process="cnc_3axis",
            crossover_qty=None,
        ),
    )
    result_dict = {
        "quantities": [50, 5000],
        "decision": {"make_now_process": "cnc_3axis", "crossover_qty": None},
        "estimates": [],
    }
    live_options = []
    batch_options = []

    def capture_live(_result, _mesh, _features, options):
        live_options.append(options)
        return report

    def capture_batch(_data, _filename, options):
        batch_options.append(options)
        return report, ".stl"

    open_mock = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(
                return_value=MagicMock(read=MagicMock(return_value=file_bytes))
            ),
            __exit__=MagicMock(return_value=False),
        )
    )

    with (
        patch.object(routes, "resolve_org", new_callable=AsyncMock, return_value="org-a"),
        patch.object(routes, "_parse_mesh_async", new_callable=AsyncMock, return_value=(object(), ".stl")),
        patch.object(routes, "_run_cost_engine", return_value=(object(), object(), object())),
        patch("src.costing.units.scale_mesh_to_mm", side_effect=lambda mesh, _units: mesh),
        patch("src.costing.estimate_decision", side_effect=capture_live),
        patch("src.costing.report_to_dict", return_value=result_dict),
        patch.object(batch_tasks, "_compute_cost_report", side_effect=capture_batch),
        patch("src.services.analysis_service.compute_mesh_hash", return_value="mesh-hash"),
        patch("src.services.machine_inventory_service.load_org_inventory", new_callable=AsyncMock, return_value=inventory),
        patch("src.services.machine_inventory_service.load_shop_caps", new_callable=AsyncMock, return_value=shop_caps),
        patch("src.services.part_context_service.get_context", new_callable=AsyncMock, return_value=SimpleNamespace(service_environment=stored_environment)),
        patch("src.services.groundtruth_service.load_served_calibration", return_value=(residual_model, calibration)),
        patch("src.services.rate_library_service.resolve_rate_table_for_org", new_callable=AsyncMock, return_value=governed_rates),
        patch("src.services.material_library_service.resolve_material_overrides_for", new_callable=AsyncMock, return_value=material_overlay),
        patch("src.services.shop_library_service.shop_library_enabled", return_value=True),
        patch("src.services.shop_library_service.resolve_shop_overrides_for", new_callable=AsyncMock, return_value=governed_shop),
        patch("src.services.batch_service.update_batch_counters", new_callable=AsyncMock),
        patch("src.services.cost_decision_service.persist_cost_decision", new_callable=AsyncMock, return_value=SimpleNamespace(id=99, ulid="CD99")),
        patch("builtins.open", open_mock),
    ):
        await routes._run_cost_decision(
            file=UploadFile(filename="part1.stl", file=io.BytesIO(file_bytes)),
            qty="50,5000",
            region=None,
            cavities=1,
            complexity="moderate",
            material_class="polymer",
            shop="org-governed-only",
            user=AuthedUser(user_id=42, api_key_id=1, key_prefix="test"),
            session=session,
        )
        await batch_tasks._run_cost_item(session, batch, item)

    assert len(live_options) == len(batch_options) == 1
    assert vars(live_options[0]) == vars(batch_options[0])
    assert batch_options[0].inventory == tuple(inventory)
    assert batch_options[0].shop_caps is shop_caps
    assert batch_options[0].service_environment == stored_environment
    assert batch_options[0].residual_model is residual_model
    assert batch_options[0].calibration is calibration
    assert batch_options[0].shop.slug == "org-governed-only"
    assert batch_options[0].base_rate_table["material_prices"]["polymer"] == 7.5
    assert batch_options[0].base_rate_table["materials"]["polymer"] == {
        "label": "governed"
    }


# ---------------------------------------------------------------------------
# Cost happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_cost_item_happy_path_persists_and_links(mock_gsf):
    from src.jobs.batch_tasks import run_batch_item

    session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(session)
    item = _make_item()
    batch = _make_batch(job_type="cost")
    session.execute = _session_returning(item, batch)
    session.commit = AsyncMock()

    saved = SimpleNamespace(id=99, ulid="CD99")
    patches = _patches(report_dict=_result_dict(), saved=saved)

    open_mock = MagicMock(return_value=MagicMock(
        __enter__=MagicMock(return_value=MagicMock(
            read=MagicMock(return_value=b"stl data"))),
        __exit__=MagicMock(return_value=False),
    ))

    with patches[0], patches[1], patches[2], patches[3], patches[4] as counters, \
         patches[5] as persist, patch("builtins.open", open_mock):
        await run_batch_item({"redis": AsyncMock()}, item.ulid)

    assert item.status == "completed"
    assert item.cost_decision_id == 99          # linked to the persisted decision
    persist.assert_awaited_once()
    assert persist.await_args.kwargs["org_id"] == "org-a"
    counters.assert_awaited_once_with(session, batch.id, "completed_items")


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_cost_item_webhook_carries_engine_numbers(mock_gsf):
    """The item webhook adds cost_decision_id + engine cost fields, copied from
    the report — never fabricated."""
    from src.jobs.batch_tasks import run_batch_item

    session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(session)
    item = _make_item()
    batch = _make_batch(job_type="cost", webhook_url="https://hook.example.com/x")
    session.execute = _session_returning(item, batch)
    session.commit = AsyncMock()

    saved = SimpleNamespace(id=99, ulid="CD99")
    patches = _patches(report_dict=_result_dict(), saved=saved)

    open_mock = MagicMock(return_value=MagicMock(
        __enter__=MagicMock(return_value=MagicMock(
            read=MagicMock(return_value=b"stl data"))),
        __exit__=MagicMock(return_value=False),
    ))

    import src.services.webhook_service as ws_mod
    delivery = SimpleNamespace(id=7)
    pool = AsyncMock()

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patch("builtins.open", open_mock), \
         patch.object(ws_mod, "create_webhook_delivery", new_callable=AsyncMock,
                      return_value=delivery) as mk_wh:
        await run_batch_item({"redis": pool}, item.ulid)

    mk_wh.assert_awaited_once()
    payload = mk_wh.await_args.args[3]
    assert payload["cost_decision_id"] == "CD99"
    assert payload["cost_decision"] == {
        "id": "CD99",
        "url": "/api/v1/cost-decisions/CD99",
    }
    assert payload["make_now_process"] == "cnc_3axis"
    assert payload["unit_cost_usd"] == 40.0     # from the make-now estimate
    assert payload["crossover_qty"] == 1200.0


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_unknown_safe_manifest_shop_fails_item_clearly(mock_gsf, monkeypatch):
    """Creation may preserve a governed candidate; authoritative worker
    resolution must still fail an identifier absent from both org and local stores."""
    from src.jobs.batch_tasks import run_batch_item

    monkeypatch.setenv("SHOP_LIBRARY_ENABLED", "0")
    session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(session)
    item = _make_item()
    item.shop = "unknown-safe-shop"
    batch = _make_batch(job_type="cost")
    session.execute = _session_returning(item, batch)
    session.commit = AsyncMock()

    saved = SimpleNamespace(id=99, ulid="CD99")
    patches = _patches(report_dict=_result_dict(), saved=saved)
    open_mock = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(
                return_value=MagicMock(read=MagicMock(return_value=b"stl data"))
            ),
            __exit__=MagicMock(return_value=False),
        )
    )

    with (
        patches[0] as compute,
        patches[1],
        patches[2],
        patches[3],
        patches[4] as counters,
        patches[5] as persist,
        patch("builtins.open", open_mock),
    ):
        await run_batch_item({"redis": AsyncMock()}, item.ulid)

    assert item.status == "failed"
    assert "Unknown shop 'unknown-safe-shop'" in item.error_message
    compute.assert_not_called()
    persist.assert_not_awaited()
    counters.assert_awaited_once_with(session, batch.id, "failed_items")


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_stored_service_environment_read_failure_fails_batch_item(mock_gsf):
    """A background cost item must not run without its authoritative safety gate."""
    from src.jobs.batch_tasks import run_batch_item

    session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(session)
    item = _make_item()
    batch = _make_batch(job_type="cost")
    session.execute = _session_returning(item, batch)
    session.commit = AsyncMock()

    saved = SimpleNamespace(id=99, ulid="CD99")
    patches = _patches(report_dict=_result_dict(), saved=saved)
    open_mock = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(
                return_value=MagicMock(read=MagicMock(return_value=b"stl data"))
            ),
            __exit__=MagicMock(return_value=False),
        )
    )

    with (
        patches[0] as compute,
        patches[1],
        patches[3],
        patches[4] as counters,
        patches[5] as persist,
        patch("src.services.machine_inventory_service.load_org_inventory", new_callable=AsyncMock, return_value=[]),
        patch("src.services.part_context_service.get_context", new_callable=AsyncMock, side_effect=RuntimeError("context unavailable")),
        patch("builtins.open", open_mock),
    ):
        await run_batch_item({"redis": AsyncMock()}, item.ulid)

    assert item.status == "failed"
    compute.assert_not_called()
    persist.assert_not_awaited()
    counters.assert_awaited_once_with(session, batch.id, "failed_items")


# ---------------------------------------------------------------------------
# GEOMETRY_INVALID → failed item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_cost_item_geometry_invalid_fails_without_persist(mock_gsf):
    from src.jobs.batch_tasks import run_batch_item

    session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(session)
    item = _make_item()
    batch = _make_batch(job_type="cost")
    session.execute = _session_returning(item, batch)
    session.commit = AsyncMock()

    saved = SimpleNamespace(id=99, ulid="CD99")
    patches = _patches(
        report_dict=_result_dict(), saved=saved,
        geometry_invalid=True, reason="volume <= 0 (non-watertight)",
    )

    open_mock = MagicMock(return_value=MagicMock(
        __enter__=MagicMock(return_value=MagicMock(
            read=MagicMock(return_value=b"bad"))),
        __exit__=MagicMock(return_value=False),
    ))

    with patches[0], patches[1], patches[2], patches[3], patches[4] as counters, \
         patches[5] as persist, patch("builtins.open", open_mock):
        await run_batch_item({"redis": AsyncMock()}, item.ulid)

    assert item.status == "failed"
    assert "volume" in (item.error_message or "")
    assert item.cost_decision_id is None
    persist.assert_not_awaited()                 # no fake decision persisted
    counters.assert_awaited_once_with(session, batch.id, "failed_items")


# ---------------------------------------------------------------------------
# Dedup-conflict reuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_cost_item_reuses_deduped_decision_row(mock_gsf):
    """persist_cost_decision returns the EXISTING row on a dup (same mesh+params
    in a ZIP); the item still completes, pointing at it."""
    from src.jobs.batch_tasks import run_batch_item

    session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(session)
    item = _make_item()
    batch = _make_batch(job_type="cost")
    session.execute = _session_returning(item, batch)
    session.commit = AsyncMock()

    existing = SimpleNamespace(id=7, ulid="CDexisting")   # the deduped row
    patches = _patches(report_dict=_result_dict(), saved=existing)

    open_mock = MagicMock(return_value=MagicMock(
        __enter__=MagicMock(return_value=MagicMock(
            read=MagicMock(return_value=b"dup"))),
        __exit__=MagicMock(return_value=False),
    ))

    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5] as persist, patch("builtins.open", open_mock):
        await run_batch_item({"redis": AsyncMock()}, item.ulid)

    assert item.status == "completed"
    assert item.cost_decision_id == 7            # reused the existing decision
    persist.assert_awaited_once()


# ---------------------------------------------------------------------------
# DFM regression — cost compute is never touched for a DFM batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_dfm_batch_never_hits_cost_path(mock_gsf):
    from src.jobs.batch_tasks import run_batch_item

    session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(session)
    item = _make_item()
    batch = _make_batch(job_type="dfm")
    session.execute = _session_returning(item, batch)
    session.commit = AsyncMock()

    import src.jobs.batch_tasks as bt_mod
    import src.services.analysis_service as as_mod
    import src.services.batch_service as bs_mod

    open_mock = MagicMock(return_value=MagicMock(
        __enter__=MagicMock(return_value=MagicMock(
            read=MagicMock(return_value=b"stl"))),
        __exit__=MagicMock(return_value=False),
    ))

    with patch.object(bt_mod, "_compute_cost_report") as compute, \
         patch.object(as_mod, "run_analysis", new_callable=AsyncMock,
                      return_value={"verdict": "pass", "saved": {"id": "AN55"}}) as run_an, \
         patch.object(as_mod, "get_analysis_id_by_ulid", new_callable=AsyncMock,
                      return_value=55), \
         patch.object(bs_mod, "update_batch_counters", new_callable=AsyncMock), \
         patch("builtins.open", open_mock):
        await run_batch_item({"redis": AsyncMock()}, item.ulid)

    run_an.assert_awaited_once()          # DFM path taken
    compute.assert_not_called()           # cost compute never touched
    assert item.status == "completed"
    assert item.analysis_id == 55
