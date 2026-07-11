"""Tests for the production fail-closed secret guard (S5).

_assert_production_secrets must be a no-op in dev/test (so the suite and local
run are never locked out) and must refuse startup in a production build with
default secrets.
"""
from __future__ import annotations

import base64

import pytest

import main


VALID_DASHBOARD_SESSION_SECRET = base64.b64encode(b"d" * 32).decode()


def set_valid_session_secrets(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "a-real-strong-secret")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", VALID_DASHBOARD_SESSION_SECRET)


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
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "dummy")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "dummy")
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        main._assert_production_secrets()


def test_prod_missing_dashboard_session_secret_refuses(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("SESSION_SECRET", "a-real-strong-secret")
    monkeypatch.delenv("DASHBOARD_SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="DASHBOARD_SESSION_SECRET"):
        main._assert_production_secrets()


def test_prod_short_dashboard_session_secret_refuses(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("SESSION_SECRET", "a-real-strong-secret")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", base64.b64encode(b"x" * 31).decode())
    with pytest.raises(RuntimeError, match="DASHBOARD_SESSION_SECRET"):
        main._assert_production_secrets()


def test_prod_saml_mode_skips_google_check(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "saml")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "dummy")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "dummy")
    main._assert_production_secrets()  # no raise — google not used


def test_prod_password_mode_skips_external_provider_checks(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "dummy")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "dummy")
    main._assert_production_secrets()  # no raise — password auth is mounted unconditionally


def test_prod_unknown_auth_mode_refuses(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "banana")
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        main._assert_production_secrets()


def test_prod_with_real_secrets_passes(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "real-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "real-secret")
    main._assert_production_secrets()  # no raise


def test_off_switch_bypasses_enforcement(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("SESSION_SECRET", "dev-only")
    monkeypatch.setenv("SECRET_ENFORCEMENT_ENABLED", "0")
    main._assert_production_secrets()  # no raise — enforcement disabled


# ──────────────────────────────────────────────────────────────
# Magic-link decoupled from Google: password+magic launch config (S-launch)
# ──────────────────────────────────────────────────────────────


VALID_MAGIC_LINK_SECRET = base64.b64encode(b"m" * 32).decode()


def set_valid_magic_link_secrets(monkeypatch):
    monkeypatch.setenv("MAGIC_LINK_SECRET", VALID_MAGIC_LINK_SECRET)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESEND_FROM", "login@cadverify.com")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://cadverify.com")


def test_magic_link_configured_requires_all_three(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("MAGIC_LINK_SECRET", raising=False)
    monkeypatch.delenv("DASHBOARD_ORIGIN", raising=False)
    assert main._magic_link_configured() is False
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("MAGIC_LINK_SECRET", VALID_MAGIC_LINK_SECRET)
    assert main._magic_link_configured() is False  # DASHBOARD_ORIGIN still missing
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://cadverify.com")
    assert main._magic_link_configured() is True


def test_magic_link_enabled_password_mode_needs_config_trio(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert main._magic_link_enabled() is False  # trio incomplete, no override
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("MAGIC_LINK_SECRET", VALID_MAGIC_LINK_SECRET)
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://cadverify.com")
    assert main._magic_link_enabled() is True  # launch config: auto-detected


def test_magic_link_enabled_google_hybrid_unchanged(monkeypatch):
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    for mode in ("google", "hybrid"):
        monkeypatch.setenv("AUTH_MODE", mode)
        assert main._magic_link_enabled() is True  # legacy behavior preserved


def test_magic_link_enabled_override_forces_on_and_off(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("MAGIC_LINK_ENABLED", "1")
    assert main._magic_link_enabled() is True  # forced on despite no config
    monkeypatch.setenv("AUTH_MODE", "hybrid")
    monkeypatch.setenv("MAGIC_LINK_ENABLED", "0")
    assert main._magic_link_enabled() is False  # forced off despite hybrid


def test_prod_password_magic_partial_autodetect_stays_disabled_not_error(monkeypatch):
    """Auto-detection requires the FULL trio before magic-link is considered
    "enabled" at all (main._magic_link_configured). A partial config (only
    RESEND_API_KEY set) therefore leaves magic-link off — the router simply
    won't mount (404, not 500) — rather than raising. This is intentional:
    without an explicit MAGIC_LINK_ENABLED override, there is no half-mounted
    state that could reach a runtime 500. The fail-deploy guarantee for a
    genuinely-intended-but-misconfigured launch is covered by
    MAGIC_LINK_ENABLED=1 (see test_prod_explicit_magic_link_enabled_missing_secrets_refuses),
    which is exactly what backend/fly.toml sets for this production launch."""
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("MAGIC_LINK_SECRET", raising=False)
    monkeypatch.delenv("DASHBOARD_ORIGIN", raising=False)
    main._assert_production_secrets()  # no raise — magic-link never "enabled"


def test_prod_password_magic_forced_on_missing_secret_refuses(monkeypatch):
    """The real production config (backend/fly.toml sets MAGIC_LINK_ENABLED=
    "true" explicitly): if MAGIC_LINK_SECRET/DASHBOARD_ORIGIN are missing
    despite the explicit force-on, boot must refuse — this is what turns the
    first-login 500 into a deploy failure."""
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.setenv("MAGIC_LINK_ENABLED", "true")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("MAGIC_LINK_SECRET", raising=False)
    monkeypatch.delenv("DASHBOARD_ORIGIN", raising=False)
    with pytest.raises(RuntimeError, match="MAGIC_LINK_SECRET"):
        main._assert_production_secrets()


def test_prod_password_magic_missing_resend_from_refuses(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("MAGIC_LINK_SECRET", VALID_MAGIC_LINK_SECRET)
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://cadverify.com")
    monkeypatch.delenv("RESEND_FROM", raising=False)
    with pytest.raises(RuntimeError, match="RESEND_FROM"):
        main._assert_production_secrets()


def test_prod_password_magic_short_secret_refuses(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    set_valid_magic_link_secrets(monkeypatch)
    monkeypatch.setenv("MAGIC_LINK_SECRET", base64.b64encode(b"x" * 31).decode())
    with pytest.raises(RuntimeError, match="MAGIC_LINK_SECRET"):
        main._assert_production_secrets()


def test_prod_password_magic_with_real_secrets_passes_no_google_needed(monkeypatch):
    """The full launch config passes without ANY Google credentials set."""
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    set_valid_magic_link_secrets(monkeypatch)
    main._assert_production_secrets()  # no raise


def test_prod_explicit_magic_link_enabled_missing_secrets_refuses(monkeypatch):
    """MAGIC_LINK_ENABLED=1 forced on with nothing configured must also
    refuse to boot (explicit intent + missing creds = fail deploy)."""
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.setenv("MAGIC_LINK_ENABLED", "1")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_FROM", raising=False)
    monkeypatch.delenv("DASHBOARD_ORIGIN", raising=False)
    with pytest.raises(RuntimeError):
        main._assert_production_secrets()


def test_prod_google_mode_without_resend_unchanged(monkeypatch):
    """A legacy AUTH_MODE=google deployment that never configured Resend for
    magic-link must boot exactly as it did before this fix (unchanged
    google/hybrid behavior) — this fix only tightens the NEW password+magic
    launch path, not pre-existing google/hybrid deploys."""
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "real-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "real-secret")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    main._assert_production_secrets()  # no raise — unchanged legacy behavior
