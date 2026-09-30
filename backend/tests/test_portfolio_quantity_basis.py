"""Regression coverage for quantity-matched portfolio annualization."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import datetime, timezone

import pytest

from src.services import catalog_service as svc


def _cost_result():
    return {
        "decision": {
            "recommendation": {
                "1": {"process": "fdm", "material": "PLA", "unit_cost_usd": 30.0},
                "100": {"process": "mjf", "material": "PP", "unit_cost_usd": 3.62},
                "1000": {"process": "mjf", "material": "PP", "unit_cost_usd": 3.48},
            },
            "if_redesigned": {"1": None, "100": None, "1000": None},
        },
        "estimates": [
            {"process": "fdm", "quantity": 1, "unit_cost_usd": 30.0, "dfm_ready": True},
            {
                "process": "mjf",
                "quantity": 100,
                "unit_cost_usd": 3.62,
                "dfm_ready": True,
                "confidence": {"validated": False},
            },
            {"process": "mjf", "quantity": 1000, "unit_cost_usd": 3.48, "dfm_ready": True},
        ],
    }


def test_annualization_uses_exact_recommended_quantity_not_qty_one():
    result = svc.annualization_at_quantity(_cost_result(), 100)
    assert result["annualized_unit_cost"] == {
        "usd": 3.62,
        "qty": 100,
        "currency": "USD",
        "process": "mjf",
        "material": "PP",
        "validated": False,
        "basis": "decision.recommendation",
    }
    assert result["annualized_cost_usd"] == 362.0


def test_annualization_withholds_when_declared_volume_has_no_engine_point():
    result = svc.annualization_at_quantity(_cost_result(), 750)
    assert result["annualized_unit_cost"] is None
    assert result["annualized_cost_usd"] is None
    assert "annual_volume 750" in result["annualized_reason"]
    assert "1, 100, 1000" in result["annualized_reason"]


def test_blocked_exact_recommendation_is_not_annualized():
    result_json = _cost_result()
    result_json["decision"]["recommendation"]["100"]["dfm_ready"] = False
    result = svc.annualization_at_quantity(result_json, 100)
    assert result["annualized_cost_usd"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("roots,flat,child,expected,basis", [
    (125, None, "part", 1000, "bom_rollup"),
    (126, None, "part", 1008, "bom_rollup"),
    (125, 55, "part", 1000, "bom_rollup"),
    (None, 50, "part", 50, "declared"),
    (125, 55, "missing", 55, "declared"),
    (None, None, "part", None, "default"),
])
async def test_portfolio_exposes_resolved_demand_even_without_a_price(monkeypatch, roots, flat, child, expected, basis):
    from src.services import bom_service as bom

    context = SimpleNamespace(mesh_hash="mesh", program="Assembly", annual_volume=flat,
                              bom_assembly_key="tree", bom_child_ref=child, bom_roots_per_year=roots)
    edges = [
        {"parent_ref": "root", "child_ref": "left", "qty_per_parent": 2},
        {"parent_ref": "left", "child_ref": "part", "qty_per_parent": 3},
        {"parent_ref": "root", "child_ref": "right", "qty_per_parent": 1},
        {"parent_ref": "right", "child_ref": "part", "qty_per_parent": 2},
    ]
    cost = svc.SourceRef("cost", "part.step", "step", datetime.now(timezone.utc), _cost_result())
    monkeypatch.setattr(svc, "_fold_org_parts", AsyncMock(return_value=([("mesh", None, cost)], False)))
    monkeypatch.setattr(svc.pcsvc, "list_contexts", AsyncMock(return_value=[context]))
    monkeypatch.setattr(bom, "load_org_trees", AsyncMock(return_value={"tree": edges}))
    portfolio = await svc.build_portfolio(None, "org")
    row = portfolio["rows"][0]
    assert row["resolved_annual_volume"] == expected
    assert row["annual_volume_basis"] == basis
    assert row["context"]["annual_volume"] == flat  # preserve the separate fallback
    assert portfolio["summary"]["programs"][0]["declared_volume_parts"] == int(expected is not None)
    if expected == 1000:
        assert row["annualized_unit_cost"]["qty"] == 1000
        assert row["annualized_cost_usd"] == 3480.0
    else:
        assert row["annualized_cost_usd"] is None
        assert row["annualized_unit_cost"] is None
