"""Tests for the production fail-closed secret guard (S5).

_assert_production_secrets must be a no-op in dev/test (so the suite and local
run are never locked out) and must refuse startup in a production build with
default secrets.
"""
from __future__ import annotations

import pytest

import main


def test_is_production_matrix(monkeypatch):
    for dev_val in ("", "dev", "development", "local", "test", "ci", "DEV"):
        monkeypatch.setenv("RELEASE", dev_val)
        assert main._is_production() is False
    for prod_val in ("v1.2.3", "prod", "2026-07-02-abc123", "production"):
        monkeypatch.setenv("RELEASE", prod_val)
        assert main._is_production() is True


def test_dev_build_is_noop(monkeypatch):
    monkeypatch.setenv("RELEASE", "dev")
    monkeypatch.setenv("SESSION_SECRET", "dev-only")
    main._assert_production_secrets()  # no raise


def test_prod_missing_session_secret_refuses(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        main._assert_production_secrets()


def test_prod_dev_only_session_secret_refuses(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("SESSION_SECRET", "dev-only")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        main._assert_production_secrets()


def test_prod_dummy_google_creds_refuse(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("SESSION_SECRET", "a-real-strong-secret")
    monkeypatch.setenv("AUTH_MODE", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "dummy")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "dummy")
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        main._assert_production_secrets()


def test_prod_saml_mode_skips_google_check(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("SESSION_SECRET", "a-real-strong-secret")
    monkeypatch.setenv("AUTH_MODE", "saml")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "dummy")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "dummy")
    main._assert_production_secrets()  # no raise — google not used


def test_prod_with_real_secrets_passes(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("SESSION_SECRET", "a-real-strong-secret")
    monkeypatch.setenv("AUTH_MODE", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "real-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "real-secret")
    main._assert_production_secrets()  # no raise


def test_off_switch_bypasses_enforcement(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("SESSION_SECRET", "dev-only")
    monkeypatch.setenv("SECRET_ENFORCEMENT_ENABLED", "0")
    main._assert_production_secrets()  # no raise — enforcement disabled
