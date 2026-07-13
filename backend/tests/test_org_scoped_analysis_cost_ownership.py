"""Focused tenant regressions for analysis/cost dedup and delayed workers."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth.require_api_key import AuthedUser
from src.db.models import Analysis, Batch, BatchItem, Job

ORG_AT_ENQUEUE = "01ORG_AT_ENQUEUE0000000001"
ORG_AFTER_SWITCH = "01ORG_AFTER_SWITCH00000001"


def _query_params(stmt) -> set[object]:
    return set(stmt.compile().params.values())


def _row_result(row):
    result = MagicMock()
    result.scalars.return_value.first.return_value = row
    return result


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _session_factory(session):
    factory = MagicMock()
    context = AsyncMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = context
    return factory


@pytest.mark.asyncio
async def test_analysis_cache_and_latest_are_distinct_for_two_orgs_same_user():
    """The same user/file can resolve independent rows in two organizations."""
    from src.services.analysis_service import _check_cache, get_latest_analysis_id

    analysis_a = SimpleNamespace(id=101, org_id=ORG_AT_ENQUEUE)
    analysis_b = SimpleNamespace(id=202, org_id=ORG_AFTER_SWITCH)
    session = AsyncMock()
    session.execute.side_effect = [
        _row_result(analysis_a),
        _row_result(analysis_b),
        _scalar_result(101),
        _scalar_result(202),
    ]

    got_a = await _check_cache(
        session, 42, "mesh", "processes", "version", org_id=ORG_AT_ENQUEUE
    )
    got_b = await _check_cache(
        session, 42, "mesh", "processes", "version", org_id=ORG_AFTER_SWITCH
    )
    latest_a = await get_latest_analysis_id(
        session, 42, "mesh", org_id=ORG_AT_ENQUEUE
    )
    latest_b = await get_latest_analysis_id(
        session, 42, "mesh", org_id=ORG_AFTER_SWITCH
    )

    assert (got_a, got_b, latest_a, latest_b) == (
        analysis_a,
        analysis_b,
        101,
        202,
    )
    statements = [call.args[0] for call in session.execute.await_args_list]
    assert ORG_AT_ENQUEUE in _query_params(statements[0])
    assert ORG_AFTER_SWITCH in _query_params(statements[1])
    assert ORG_AT_ENQUEUE in _query_params(statements[2])
    assert ORG_AFTER_SWITCH in _query_params(statements[3])
    assert all("analyses.org_id" in str(stmt) for stmt in statements)


@pytest.mark.asyncio
async def test_cost_dedup_is_distinct_for_two_orgs_same_user():
    from src.services.cost_decision_service import _lookup_dedup

    decision_a = SimpleNamespace(id=301, org_id=ORG_AT_ENQUEUE)
    decision_b = SimpleNamespace(id=302, org_id=ORG_AFTER_SWITCH)
    session = AsyncMock()
    session.execute.side_effect = [_row_result(decision_a), _row_result(decision_b)]

    got_a = await _lookup_dedup(
        session, 42, "mesh", "params", org_id=ORG_AT_ENQUEUE
    )
    got_b = await _lookup_dedup(
        session, 42, "mesh", "params", org_id=ORG_AFTER_SWITCH
    )

    assert (got_a, got_b) == (decision_a, decision_b)
    statements = [call.args[0] for call in session.execute.await_args_list]
    assert ORG_AT_ENQUEUE in _query_params(statements[0])
    assert ORG_AFTER_SWITCH in _query_params(statements[1])
    assert all("cost_decisions.org_id" in str(stmt) for stmt in statements)


@pytest.mark.asyncio
async def test_analysis_explicit_org_persist_and_usage_never_resolve_switch():
    """The service honors a worker-supplied org through writes and telemetry."""
    from src.db.models import UsageEvent
    from src.services.analysis_service import _persist_analysis, _write_usage_event

    user = AuthedUser(user_id=42, api_key_id=0, key_prefix="worker")
    session = AsyncMock()
    added = []
    session.add = added.append
    session.flush = AsyncMock()

    with (
        patch(
            "src.auth.org_context.resolve_org",
            new=AsyncMock(side_effect=AssertionError("must not resolve switched org")),
        ) as resolve_org,
        patch(
            "src.services.part_summary_service.refresh_part_summary_safe",
            new=AsyncMock(),
        ),
        patch(
            "src.services.part_signature_service.upsert_signature_safe",
            new=AsyncMock(),
        ),
    ):
        analysis = await _persist_analysis(
            session,
            user,
            mesh_hash="mesh",
            process_set_hash="processes",
            analysis_version="version",
            filename="part.stl",
            file_type="stl",
            file_size_bytes=4,
            result_json={"verdict": "pass"},
            verdict="pass",
            face_count=12,
            duration_ms=1.0,
            org_id=ORG_AT_ENQUEUE,
        )
        await _write_usage_event(
            session,
            user,
            "analysis_complete",
            analysis.id,
            analysis.mesh_hash,
            analysis.duration_ms,
            analysis.face_count,
            org_id=ORG_AT_ENQUEUE,
        )

    usage = next(row for row in added if isinstance(row, UsageEvent))
    assert analysis.org_id == ORG_AT_ENQUEUE
    assert usage.org_id == ORG_AT_ENQUEUE
    resolve_org.assert_not_awaited()


@pytest.mark.asyncio
async def test_cost_explicit_org_persist_never_resolves_switch():
    """A delayed cost write cannot migrate to the owner's newly active org."""
    from src.services.cost_decision_service import persist_cost_decision

    user = AuthedUser(user_id=42, api_key_id=0, key_prefix="worker")
    session = AsyncMock()
    session.execute.return_value = _row_result(None)
    session.add = MagicMock()
    session.flush = AsyncMock()

    with (
        patch(
            "src.auth.org_context.resolve_org",
            new=AsyncMock(side_effect=AssertionError("must not resolve switched org")),
        ) as resolve_org,
        patch(
            "src.services.cost_decision_service._refresh_summary_for",
            new=AsyncMock(),
        ),
        patch(
            "src.services.notification_service.emit_notification",
            new=AsyncMock(),
        ),
        patch("src.services.audit_service.emit_event", new=AsyncMock()),
    ):
        decision = await persist_cost_decision(
            session,
            user,
            mesh_hash="mesh",
            params_hash="params",
            engine_version="version",
            filename="part.stl",
            file_type="stl",
            result_json={"decision": {}, "quantities": [1]},
            org_id=ORG_AT_ENQUEUE,
        )

    assert decision.org_id == ORG_AT_ENQUEUE
    resolve_org.assert_not_awaited()


def _batch_and_item(*, job_type: str) -> tuple[MagicMock, MagicMock]:
    batch = MagicMock(spec=Batch)
    batch.id = 1
    batch.ulid = "01BATCH00000000000000001"
    batch.user_id = 42
    batch.org_id = ORG_AT_ENQUEUE
    batch.api_key_id = None
    batch.job_type = job_type
    batch.input_mode = "zip"
    batch.webhook_url = None
    batch.manifest_json = {}
    batch.completed_items = 0
    batch.failed_items = 0

    item = MagicMock(spec=BatchItem)
    item.id = 2
    item.ulid = "01ITEM000000000000000001"
    item.batch_id = batch.id
    item.filename = "part.stl"
    item.status = "queued"
    item.process_types = "fdm"
    item.rule_pack = None
    item.analysis_id = None
    item.cost_decision_id = None
    item.quantities = None
    item.region = None
    item.material_class = None
    item.shop = None
    item.error_message = None
    item.duration_ms = None
    return batch, item


@pytest.mark.asyncio
async def test_dfm_batch_keeps_enqueued_org_after_user_switch():
    """A delayed DFM item never follows users.current_org_id after enqueue."""
    from src.jobs.batch_tasks import run_batch_item

    batch, item = _batch_and_item(job_type="dfm")
    session = AsyncMock()
    session.execute.side_effect = [_row_result(item), _row_result(batch)]
    session.commit = AsyncMock()

    with (
        patch(
            "src.jobs.batch_tasks.get_session_factory",
            return_value=_session_factory(session),
        ),
        patch(
            "src.auth.org_context.resolve_org",
            new=AsyncMock(side_effect=AssertionError("must not resolve switched org")),
        ) as resolve_org,
        patch(
            "src.services.analysis_service.run_analysis",
            new=AsyncMock(return_value={"verdict": "pass"}),
        ) as run_analysis,
        patch(
            "src.services.analysis_service.get_latest_analysis_id",
            new=AsyncMock(return_value=101),
        ) as latest,
        patch(
            "src.services.analysis_service.compute_mesh_hash", return_value="mesh"
        ),
        patch("src.services.batch_service.read_batch_blob", return_value=b"mesh"),
        patch(
            "src.services.batch_service.update_batch_counters",
            new=AsyncMock(),
        ),
    ):
        await run_batch_item({}, item.ulid)

    assert run_analysis.await_args.kwargs["org_id"] == ORG_AT_ENQUEUE
    assert latest.await_args.kwargs["org_id"] == ORG_AT_ENQUEUE
    assert item.analysis_id == 101
    resolve_org.assert_not_awaited()


@pytest.mark.asyncio
async def test_cost_batch_keeps_enqueued_org_after_user_switch():
    """Cost calibration and persistence stay on the batch's persisted tenant."""
    from src.jobs.batch_tasks import _run_cost_item

    batch, item = _batch_and_item(job_type="cost")
    report = SimpleNamespace(status="OK", reason=None)
    saved = SimpleNamespace(id=401, ulid="01COST000000000000000001")
    session = AsyncMock()
    session.commit = AsyncMock()

    with (
        patch(
            "src.auth.org_context.resolve_org",
            new=AsyncMock(side_effect=AssertionError("must not resolve switched org")),
        ) as resolve_org,
        patch(
            "src.jobs.batch_tasks._compute_cost_report",
            return_value=(report, ".stl"),
        ),
        patch("src.services.batch_service.read_batch_blob", return_value=b"mesh"),
        patch(
            "src.services.groundtruth_service.load_served_calibration",
            return_value=(None, None),
        ) as load_calibration,
        patch("src.costing.report_to_dict", return_value={"decision": {}}),
        patch("src.services.analysis_service.compute_mesh_hash", return_value="mesh"),
        patch(
            "src.services.cost_decision_service.persist_cost_decision",
            new=AsyncMock(return_value=saved),
        ) as persist,
        patch(
            "src.services.batch_service.update_batch_counters",
            new=AsyncMock(),
        ),
        patch("src.services.catalog_service.make_now_estimate", return_value=None),
    ):
        await _run_cost_item(session, batch, item)

    load_calibration.assert_called_once_with(ORG_AT_ENQUEUE)
    assert persist.await_args.kwargs["org_id"] == ORG_AT_ENQUEUE
    assert item.cost_decision_id == saved.id
    resolve_org.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconstruction_keeps_job_org_after_user_switch():
    """Reconstruction auto-analysis is owned by the queued job's organization."""
    from src.jobs.reconstruction_tasks import run_reconstruction_job

    job = MagicMock(spec=Job)
    job.ulid = "01JOB0000000000000000001"
    job.user_id = 42
    job.org_id = ORG_AT_ENQUEUE
    job.params_json = {"process_types": "fdm", "rule_pack": None}
    job.status = "queued"
    job.result_json = None
    job.started_at = None
    job.completed_at = None
    analysis = SimpleNamespace(id=501, ulid="01ANALYSIS00000000000001")

    session = AsyncMock()
    session.execute.side_effect = [_row_result(job), _row_result(analysis)]
    session.commit = AsyncMock()

    processed_image = MagicMock()
    processed_image.save.side_effect = lambda buffer, format: buffer.write(b"png")
    reconstruction = SimpleNamespace(
        mesh_bytes=b"stl",
        face_count=12,
        duration_ms=10.0,
        method="test",
    )
    engine = AsyncMock()
    engine.reconstruct.return_value = reconstruction

    with (
        patch(
            "src.db.engine.get_session_factory",
            return_value=_session_factory(session),
        ),
        patch(
            "src.auth.org_context.resolve_org",
            new=AsyncMock(side_effect=AssertionError("must not resolve switched org")),
        ) as resolve_org,
        patch(
            "src.services.reconstruction_service.load_reconstruction_images",
            return_value=[(b"image", "image/png")],
        ),
        patch(
            "src.reconstruction.preprocessing.select_best_image", return_value=0
        ),
        patch(
            "src.reconstruction.preprocessing.preprocess_image",
            return_value=(processed_image, {}),
        ),
        patch(
            "src.services.reconstruction_service.get_reconstruction_engine",
            return_value=engine,
        ),
        patch(
            "src.services.reconstruction_service.save_reconstruction_mesh",
            new=AsyncMock(),
        ),
        patch("trimesh.load", return_value=MagicMock()),
        patch("src.reconstruction.scoring.compute_reconstruction_confidence", return_value=0.9),
        patch("src.reconstruction.scoring.confidence_level", return_value="high"),
        patch("src.reconstruction.scoring.confidence_message", return_value="high"),
        patch(
            "src.services.analysis_service.run_analysis",
            new=AsyncMock(return_value={"verdict": "pass"}),
        ) as run_analysis,
        patch(
            "src.services.analysis_service.get_latest_analysis_id",
            new=AsyncMock(return_value=501),
        ) as latest,
        patch(
            "src.services.analysis_service.compute_mesh_hash", return_value="mesh"
        ),
    ):
        result = await run_reconstruction_job({}, job.ulid)

    assert result["analysis_id"] == analysis.ulid
    assert run_analysis.await_args.kwargs["org_id"] == ORG_AT_ENQUEUE
    assert latest.await_args.kwargs["org_id"] == ORG_AT_ENQUEUE
    analysis_lookup = session.execute.await_args_list[1].args[0]
    assert ORG_AT_ENQUEUE in _query_params(analysis_lookup)
    resolve_org.assert_not_awaited()
