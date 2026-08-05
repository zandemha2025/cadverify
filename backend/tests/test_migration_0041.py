"""Schema contract for organization-scoped analysis/cost deduplication."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.models import Analysis, CostDecision


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0041_org_scoped_dedup.py"
    )
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0041_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def _constraint_columns(model, name: str) -> list[str]:
    constraint = next(c for c in model.__table__.constraints if c.name == name)
    return [column.name for column in constraint.columns]


def test_models_include_org_in_analysis_and_cost_dedup_keys():
    assert _constraint_columns(Analysis, "uq_analyses_dedup") == [
        "org_id",
        "user_id",
        "mesh_hash",
        "process_set_hash",
        "analysis_version",
    ]
    assert _constraint_columns(CostDecision, "uq_cost_decisions_dedup") == [
        "org_id",
        "user_id",
        "mesh_hash",
        "params_hash",
    ]


def test_migration_replaces_both_unique_constraints_with_org_scoped_keys():
    migration, op = _load()
    assert migration.revision == "0041_org_scoped_dedup"
    assert migration.down_revision == "0040_design_studio"
    assert len(migration.revision) <= 32

    migration.upgrade()

    dropped = {
        (call.args[0], call.args[1], call.kwargs["type_"])
        for call in op.drop_constraint.call_args_list
    }
    assert dropped == {
        ("uq_analyses_dedup", "analyses", "unique"),
        ("uq_cost_decisions_dedup", "cost_decisions", "unique"),
    }
    created = {
        call.args[0]: (call.args[1], call.args[2])
        for call in op.create_unique_constraint.call_args_list
    }
    assert created == {
        "uq_analyses_dedup": (
            "analyses",
            [
                "org_id",
                "user_id",
                "mesh_hash",
                "process_set_hash",
                "analysis_version",
            ],
        ),
        "uq_cost_decisions_dedup": (
            "cost_decisions",
            ["org_id", "user_id", "mesh_hash", "params_hash"],
        ),
    }
