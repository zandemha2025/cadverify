"""Schema contract for self-serve plans (email tiers, Pro billing, verified phones)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.db.models import BillingAccount, BillingEvent, User


def _load():
    mock_op = MagicMock()
    mock_op.get_bind.return_value.dialect.name = "postgresql"
    path = Path(__file__).parent.parent / "alembic" / "versions" / "0051_self_serve_plans.py"
    with patch.dict(sys.modules, {"alembic.op": mock_op}):
        import alembic

        old = getattr(alembic, "op", None)
        alembic.op = mock_op
        try:
            spec = importlib.util.spec_from_file_location("migration_0051_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            alembic.op = old
    return module, mock_op


def test_models_match_the_migration():
    for column in ("free_check_grant", "verified_phone", "phone_verified_at"):
        assert User.__table__.c[column].nullable is True
    assert BillingAccount.__table__.c.stripe_customer_id.unique is True
    assert BillingAccount.__table__.c.stripe_subscription_id.unique is True
    assert BillingEvent.__table__.c.event_id.primary_key is True


def test_migration_0051_grandfathers_existing_accounts_and_is_reversible():
    migration, op = _load()
    assert migration.revision == "0051_self_serve_plans"
    assert migration.down_revision == "0050_customer_profiles"
    assert len(migration.revision) <= 32

    migration.upgrade()
    added = [call.args[1].name for call in op.add_column.call_args_list]
    assert added == ["free_check_grant", "verified_phone", "phone_verified_at"]
    statements = [str(call.args[0]) for call in op.execute.call_args_list]
    assert "UPDATE users SET free_check_grant = 10" in statements
    index = op.create_index.call_args
    assert index.args[:3] == ("uq_users_verified_phone", "users", ["verified_phone"])
    assert index.kwargs["unique"] is True
    assert {call.args[0] for call in op.create_table.call_args_list} == {"billing_accounts", "billing_events"}

    migration.downgrade()
    statements = [str(call.args[0]) for call in op.execute.call_args_list]
    assert "UPDATE users SET plan = 'trial' WHERE plan = 'pro'" in statements
    assert {call.args[0] for call in op.drop_table.call_args_list} == {"billing_accounts", "billing_events"}
    assert [call.args[1] for call in op.drop_column.call_args_list] == ["phone_verified_at", "verified_phone", "free_check_grant"]
