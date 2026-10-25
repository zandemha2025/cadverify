"""The local labeling tool's corpus routes have no authentication, so a
released build must never mount them, even with LABELING_ENABLED=1 set."""
import logging

import pytest
from fastapi import FastAPI

import main


def _corpus_paths(app: FastAPI) -> list[str]:
    return [path for path in app.openapi().get("paths", {}) if path.startswith("/api/v1/corpus")]


@pytest.mark.parametrize("release", ["2026.10.21", "production", "prod-abc123"])
def test_a_release_never_mounts_the_corpus_routes(monkeypatch, caplog, release):
    monkeypatch.setenv("LABELING_ENABLED", "1")
    monkeypatch.setenv("RELEASE", release)
    app = FastAPI()
    with caplog.at_level(logging.WARNING, logger="cadverify"):
        assert main._mount_labeling_tool(app) is False
    assert _corpus_paths(app) == []
    assert main._labeling_enabled() is False
    assert any("LABELING_ENABLED=1 ignored in a production build" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("release", [None, "dev", "local", "test", "ci"])
def test_a_local_build_mounts_them_only_when_asked(monkeypatch, release):
    if release is None:
        monkeypatch.delenv("RELEASE", raising=False)
    else:
        monkeypatch.setenv("RELEASE", release)
    monkeypatch.delenv("LABELING_ENABLED", raising=False)
    off = FastAPI()
    assert main._mount_labeling_tool(off) is False and _corpus_paths(off) == []
    monkeypatch.setenv("LABELING_ENABLED", "1")
    on = FastAPI()
    assert main._mount_labeling_tool(on) is True
    assert "/api/v1/corpus/parts" in _corpus_paths(on)


def test_a_release_doesnt_widen_cors_for_the_tool(monkeypatch):
    import re

    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://app.scalecad.example")
    monkeypatch.setenv("LABELING_ENABLED", "1")
    monkeypatch.setenv("RELEASE", "production")
    monkeypatch.setattr(main, "LABELING_ENABLED", main._labeling_enabled())
    pattern = main._default_cors_regex()
    assert re.fullmatch(pattern, "https://app.scalecad.example")
    assert not re.fullmatch(pattern, "http://localhost:3000")
