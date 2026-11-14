from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load():
    mock_op = MagicMock()
    path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0036_analysis_dedup_org_scope.py"
    )
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        original = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0036_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
        finally:
            alembic.op = original
    return module, mock_op


def test_upgrade_replaces_user_only_dedup_with_org_scoped_constraint():
    module, mock_op = _load()
    module.upgrade()

    assert module.down_revision == "0035_connector_credentials"
    assert mock_op.drop_constraint.call_args_list == [
        (("uq_analyses_dedup", "analyses"), {"type_": "unique"}),
        (("uq_cost_decisions_dedup", "cost_decisions"), {"type_": "unique"}),
    ]
    assert mock_op.create_unique_constraint.call_args_list == [
        (
            ("uq_analyses_dedup", "analyses", [
                "org_id", "user_id", "mesh_hash", "process_set_hash",
                "analysis_version",
            ]),
            {},
        ),
        (
            ("uq_cost_decisions_dedup", "cost_decisions", [
                "org_id", "user_id", "mesh_hash", "params_hash",
            ]),
            {},
        ),
    ]


def test_model_dedup_constraint_includes_org():
    from src.db.models import Analysis, CostDecision

    constraint = next(
        item
        for item in Analysis.__table__.constraints
        if item.name == "uq_analyses_dedup"
    )
    assert [column.name for column in constraint.columns] == [
        "org_id",
        "user_id",
        "mesh_hash",
        "process_set_hash",
        "analysis_version",
    ]
    cost_constraint = next(
        item
        for item in CostDecision.__table__.constraints
        if item.name == "uq_cost_decisions_dedup"
    )
    assert [column.name for column in cost_constraint.columns] == [
        "org_id",
        "user_id",
        "mesh_hash",
        "params_hash",
    ]
