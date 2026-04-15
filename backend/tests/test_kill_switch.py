"""Unit tests for src.auth.kill_switch (AUTH-09)."""
from __future__ import annotations

import importlib
import time

import pytest
from fastapi import HTTPException


def _reload():
    import src.auth.kill_switch as m

    importlib.reload(m)
    return m


def test_default_accepting(monkeypatch):
    monkeypatch.delenv("ACCEPTING_NEW_ANALYSES", raising=False)
    m = _reload()
    assert m.is_accepting() is True


@pytest.mark.parametrize("v", ["false", "FALSE", "0", "no", "off"])
def test_disabled_values(monkeypatch, v):
    monkeypatch.setenv("ACCEPTING_NEW_ANALYSES", v)
    m = _reload()
    assert m.is_accepting() is False


def test_30s_cache(monkeypatch):
    monkeypatch.setenv("ACCEPTING_NEW_ANALYSES", "true")
    m = _reload()
    assert m.is_accepting() is True
    monkeypatch.setenv("ACCEPTING_NEW_ANALYSES", "false")
    # Still True within cache window — env change not yet observed.
    assert m.is_accepting() is True
    # Jump past the cache window by rewinding the cache timestamp.
    monkeypatch.setattr(m, "_CACHE_TS", time.time() - 31.0)
    assert m.is_accepting() is False


def test_require_kill_switch_open_503(monkeypatch):
    monkeypatch.setenv("ACCEPTING_NEW_ANALYSES", "false")
    m = _reload()
    with pytest.raises(HTTPException) as exc:
        m.require_kill_switch_open()
    assert exc.value.status_code == 503
    assert exc.value.headers["Retry-After"] == "3600"
    assert exc.value.detail["code"] == "service_paused"
    assert "doc_url" in exc.value.detail


def test_require_kill_switch_open_passes_when_accepting(monkeypatch):
    monkeypatch.setenv("ACCEPTING_NEW_ANALYSES", "true")
    m = _reload()
    # Does not raise.
    m.require_kill_switch_open()
