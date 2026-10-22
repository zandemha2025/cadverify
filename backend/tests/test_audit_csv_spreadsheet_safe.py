"""The audit-log CSV neutralises formula-looking cells like the other CSV exports.

Text fields that start with = + - @ (or a tab / carriage return) get the
apostrophe prefix from cost_decision_service.spreadsheet_safe_cell, so a
spreadsheet opens them as text. Ordinary values are unchanged.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.audit_service import export_audit_csv


def _entry(**fields):
    e = MagicMock()
    e.id = 1
    e.timestamp = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    e.user_email = "test@example.com"
    e.action = "analysis.created"
    e.resource_type = "analysis"
    e.resource_id = "abc123"
    e.ip_address = "127.0.0.1"
    e.file_hash = "deadbeef"
    e.result_summary = "pass"
    for k, v in fields.items():
        setattr(e, k, v)
    return e


def _session(entries):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = entries
    session.execute.return_value = result
    return session


async def _rows(entries):
    now = datetime.now(timezone.utc)
    text = await export_audit_csv(start=now - timedelta(days=1), end=now + timedelta(days=1),
                                  session=_session(entries))
    return list(csv.reader(io.StringIO(text)))


@pytest.mark.asyncio
async def test_formula_like_audit_cells_are_neutralised():
    rows = await _rows([_entry(
        user_email="=HYPERLINK(\"http://x\")@example.com",
        action="+cmd",
        resource_type="-2+3",
        resource_id="@SUM(A1:A9)",
        ip_address="\t=1+1",
        file_hash=" =evil",
        result_summary="\r=x",
    )])
    data = rows[1]
    assert data[1] == "'=HYPERLINK(\"http://x\")@example.com"
    assert data[2] == "'+cmd"
    assert data[3] == "'-2+3"
    assert data[4] == "'@SUM(A1:A9)"
    assert data[5] == "'\t=1+1"
    assert data[6] == "' =evil"
    assert data[7] == "'\r=x"


@pytest.mark.asyncio
async def test_ordinary_audit_cells_are_unchanged():
    rows = await _rows([_entry()])
    assert rows[0][:3] == ["timestamp", "user_email", "action"]
    assert rows[1] == ["2026-10-22T12:00:00+00:00", "test@example.com", "analysis.created",
                       "analysis", "abc123", "127.0.0.1", "deadbeef", "pass"]
