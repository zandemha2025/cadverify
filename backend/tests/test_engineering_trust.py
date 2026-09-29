"""Regression cases from the supplied-package discovery, using real shared seams."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.analysis.models import ProcessType
from src.costing.estimate import EstimateOptions, _build_verification
from src.costing.groundtruth import Residual, ResidualModel
from src.costing.makeability import MachineCap, environment_gate
from src.services import cost_decision_service as decisions


def test_residuals_cannot_validate_an_unmeasured_process():
    rows = [Residual(str(i), "cnc_3axis", 1, 10, 10, 10, e, abs(e), False)
            for i, e in enumerate([-.1, 0, .1])]
    model = ResidualModel(rows)
    assert model.interval(100, process="cnc_3axis").validated
    assert not model.interval(100, process="sls").validated
    assert model.interval(100, process=None).validated  # explicitly pooled


def test_missing_environment_coverage_is_unknown_and_cannot_pass_machine_fit():
    env = {"max_temp_c": 900, "min_temp_c": -190, "pressure_bar": 1000,
           "medium": "chlorides"}
    gate, _ = environment_gate(["cnc_3axis"], ["6061-T6 Aluminum"], env, {})
    assert gate["unknown_materials"] == {"6061-T6 Aluminum"}
    assert {f.axis for f in gate["unknowns"]} >= {"max_temp_c", "min_temp_c", "pressure_bar", "medium"}
    verification, _, _ = _verification(env=env)
    assert verification["verdict"] == "unknown"
    assert verification["environment_unknowns"]


def _verification(verdict="pass", env=None, bbox=(10, 20, 30)):
    options = EstimateOptions(inventory=(MachineCap(
        process="cnc_3axis", name="Mill A", max_workpiece_kg=100,
        materials=("aluminum",), capabilities={"x": 100, "y": 100, "z": 100},
    ),), service_environment=env)
    return _build_verification([{
        "process": ProcessType.CNC_3AXIS,
        "material": SimpleNamespace(name="6061-T6 Aluminum", density=2.7),
        "score": SimpleNamespace(verdict=verdict, score=0 if verdict == "fail" else 100),
    }], SimpleNamespace(bbox_mm=bbox, mass_kg=lambda _: .1, nominal_wall_mm=3), options)


def test_machine_gap_cannot_hide_unknown_service_requirements():
    result, overrides, _ = _verification(env={"pressure_bar": 350}, bbox=(200, 200, 200))
    assert result["verdict"] == "unknown"
    route = result["per_route"]["cnc_3axis"]
    assert route["verdict"] == "unknown"
    assert any(f["have"] is not None for f in route["failures"])
    assert any(f["axis"] == "pressure_bar" and f["have"] is None for f in route["failures"])
    assert not route.get("resource")
    assert not overrides


def test_machine_fit_does_not_override_dfm_failure():
    assert _verification()[0]["verdict"] == "makeable_in_house"
    result, overrides, _ = _verification("fail")
    assert result["verdict"] == "not_makeable"
    assert result["per_route"]["cnc_3axis"]["dfm_verdict"] == "fail"
    assert not overrides


@pytest.mark.asyncio
async def test_persistence_never_reuses_incompatible_computed_results():
    captured = []
    async def lookup(session, user_id, mesh_hash, params_hash, **kwargs):
        captured.append(params_hash)
        return SimpleNamespace(org_id="org", mesh_hash=mesh_hash)
    with patch.object(decisions, "_lookup_dedup", lookup), patch.object(
        decisions, "_refresh_summary_for", AsyncMock()
    ):
        for verdict in ["makeable_in_house", "environment_excluded", "makeable_in_house"]:
            await decisions.persist_cost_decision(
                AsyncMock(), SimpleNamespace(user_id=1), mesh_hash="mesh", params_hash="params",
                engine_version="v1", filename="part.step", file_type="step",
                result_json={"verification": {"verdict": verdict}},
            )
    assert captured[0] != captured[1]
    assert captured[0] == captured[2]


def test_hash_tracks_evaluated_context_even_when_result_is_identical():
    from src.services.cost_decision_service import evaluation_context
    base = EstimateOptions()
    for changed in [replace(base, units="inch"), replace(base, tolerance_class="tight"),
                    replace(base, service_environment={"max_temp_c": 10}),
                    replace(base, owned_processes=frozenset({ProcessType.CNC_3AXIS}))]:
        assert evaluation_context(base) != evaluation_context(changed)
