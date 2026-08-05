"""Regression coverage for quantity-matched portfolio annualization."""
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
