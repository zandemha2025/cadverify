"""Regression coverage for dashboard-session batch creation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.services import batch_service


class _Session:
    def __init__(self) -> None:
        self.added = []

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_dashboard_session_sentinel_never_enters_batch_api_key_fk(monkeypatch):
    """A web-session batch stores NULL while a real key remains attributable."""

    # Regression: ISSUE-006 — dashboard batch creation persisted api_key_id=0
    # Found by /qa on 2026-07-13
    # Report: .gstack/qa-reports/qa-report-training-guide-e2e-2026-07-13.md
    monkeypatch.setattr("src.auth.org_context.resolve_org", AsyncMock(return_value="01ORG"))
    monkeypatch.setattr("src.services.audit_service.emit_event", AsyncMock())

    session = _Session()
    dashboard_batch = await batch_service.create_batch(
        session=session,
        user_id=7,
        input_mode="zip",
        api_key_id=0,
    )
    keyed_batch = await batch_service.create_batch(
        session=session,
        user_id=7,
        input_mode="zip",
        api_key_id=42,
    )

    assert dashboard_batch.api_key_id is None
    assert keyed_batch.api_key_id == 42
