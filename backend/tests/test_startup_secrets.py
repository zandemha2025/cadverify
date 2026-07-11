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
    monkeypatch.setenv("MAGIC_LINK_ENABLED", "0")
    main._assert_production_secrets()  # no raise


def test_off_switch_cannot_bypass_released_secret_enforcement(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("SESSION_SECRET", "dev-only")
    monkeypatch.setenv("SECRET_ENFORCEMENT_ENABLED", "0")
    with pytest.raises(RuntimeError, match="cannot be disabled"):
        main._assert_production_secrets()


# ──────────────────────────────────────────────────────────────
# Production operations: durable storage + telemetry fail closed
# ──────────────────────────────────────────────────────────────


def test_production_operations_are_opt_in(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.delenv("PRODUCTION_STORAGE_REQUIRED", raising=False)
    monkeypatch.delenv("PRODUCTION_OBSERVABILITY_REQUIRED", raising=False)
    main._assert_production_operations()


def test_released_process_rejects_memory_rate_limit_override(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("RATE_LIMIT_ALLOW_MEMORY", "1")
    with pytest.raises(RuntimeError, match="RATE_LIMIT_ALLOW_MEMORY"):
        main._assert_production_operations()


def test_production_rejects_public_low_entropy_secret_stubs(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_CRYPTO_SECRET_QUALITY_REQUIRED", "1")
    monkeypatch.setenv("MAGIC_LINK_ENABLED", "0")
    monkeypatch.setenv(
        "SESSION_SECRET",
        "strong-session-secret-with-enough-variety-1234567890",
    )
    for name, byte in (
        ("DASHBOARD_SESSION_SECRET", b"dashboard-secret-material-123456"),
        ("AUTH_PROXY_SECRET", b"auth-proxy-secret-material-1234567"),
        ("API_KEY_PEPPER", b"api-key-pepper-material-123456789"),
        ("CONNECTOR_FINGERPRINT_KEY", b"fingerprint-key-material-1234567"),
        ("DEEP_HEALTH_TOKEN", b"deep-health-token-material-1234567"),
        ("CONNECTOR_SECRET_KEY", b"connector-fernet-material-123456"),
    ):
        monkeypatch.setenv(name, base64.urlsafe_b64encode(byte[:32]).decode())

    main._assert_production_operations()

    monkeypatch.setenv(
        "API_KEY_PEPPER",
        base64.b64encode(b"a" * 32).decode(),
    )
    with pytest.raises(RuntimeError, match="low-entropy launch stub"):
        main._assert_production_operations()


def test_production_storage_refuses_local_backend(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_STORAGE_REQUIRED", "1")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "local")
    with pytest.raises(RuntimeError, match="OBJECT_STORE_BACKEND"):
        main._assert_production_operations()


@pytest.mark.parametrize("missing", ["OBJECT_STORE_S3_BUCKET", "OBJECT_STORE_S3_REGION"])
def test_production_storage_requires_s3_coordinates(monkeypatch, missing):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_STORAGE_REQUIRED", "1")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORE_S3_BUCKET", "cadverify-prod")
    monkeypatch.setenv("OBJECT_STORE_S3_REGION", "us-east-1")
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(RuntimeError, match=missing):
        main._assert_production_operations()


def test_production_storage_with_s3_passes(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_STORAGE_REQUIRED", "1")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORE_S3_BUCKET", "cadverify-prod")
    monkeypatch.setenv("OBJECT_STORE_S3_REGION", "us-east-1")
    main._assert_production_operations()


def test_production_observability_refuses_missing_sink(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_OBSERVABILITY_REQUIRED", "true")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="SENTRY_DSN"):
        main._assert_production_operations()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SENTRY_DSN", "https://public@example.ingest.sentry.io/1"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318"),
    ],
)
def test_production_observability_accepts_configured_sink(monkeypatch, name, value):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_OBSERVABILITY_REQUIRED", "1")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setenv(name, value)
    main._assert_production_operations()


def test_production_deep_health_requires_strong_token(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_DEEP_HEALTH_AUTH_REQUIRED", "1")
    monkeypatch.setenv("DEEP_HEALTH_TOKEN", "too-short")
    with pytest.raises(RuntimeError, match="DEEP_HEALTH_TOKEN"):
        main._assert_production_operations()

    monkeypatch.setenv("DEEP_HEALTH_TOKEN", "h" * 32)
    main._assert_production_operations()


def test_production_auth_proxy_requires_strong_base64_secret(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_AUTH_PROXY_REQUIRED", "1")
    monkeypatch.setenv("AUTH_PROXY_SECRET", "not-base64")
    with pytest.raises(RuntimeError, match="AUTH_PROXY_SECRET"):
        main._assert_production_operations()

    monkeypatch.setenv(
        "AUTH_PROXY_SECRET", base64.b64encode(b"proxy" * 7).decode()
    )
    main._assert_production_operations()


def test_production_verified_signup_rejects_public_password_creation(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_VERIFIED_SIGNUP_REQUIRED", "1")
    monkeypatch.setenv("PUBLIC_PASSWORD_SIGNUP_ENABLED", "1")
    with pytest.raises(RuntimeError, match="PUBLIC_PASSWORD_SIGNUP_ENABLED"):
        main._assert_production_operations()

    monkeypatch.setenv("PUBLIC_PASSWORD_SIGNUP_ENABLED", "0")
    main._assert_production_operations()


def test_production_host_only_session_cookie_rejects_parent_domain(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_HOST_ONLY_SESSION_COOKIE_REQUIRED", "1")
    monkeypatch.setenv("SESSION_COOKIE_DOMAIN", ".example.com")
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_DOMAIN"):
        main._assert_production_operations()

    monkeypatch.setenv("SESSION_COOKIE_DOMAIN", "")
    main._assert_production_operations()


def test_production_ssrf_guard_cannot_be_disabled(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_SSRF_GUARD_REQUIRED", "1")
    monkeypatch.setenv("WEBHOOK_SSRF_GUARD_ENABLED", "0")
    with pytest.raises(RuntimeError, match="WEBHOOK_SSRF_GUARD_ENABLED"):
        main._assert_production_operations()

    monkeypatch.setenv("WEBHOOK_SSRF_GUARD_ENABLED", "1")
    main._assert_production_operations()


def test_production_security_headers_cannot_be_disabled(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_SECURITY_HEADERS_REQUIRED", "1")
    monkeypatch.setenv("SECURITY_HEADERS_ENABLED", "0")
    with pytest.raises(RuntimeError, match="SECURITY_HEADERS_ENABLED"):
        main._assert_production_operations()

    monkeypatch.setenv("SECURITY_HEADERS_ENABLED", "1")
    main._assert_production_operations()


def test_regulated_boundary_rejects_external_auth_compute_and_telemetry(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_REGULATED_BOUNDARY_REQUIRED", "1")
    monkeypatch.setenv("AUTH_MODE", "saml")
    monkeypatch.setenv("PASSWORD_LOGIN_ENABLED", "0")
    monkeypatch.setenv("MAGIC_LINK_ENABLED", "0")
    monkeypatch.setenv("RECONSTRUCTION_BACKEND", "local")
    monkeypatch.setenv("RECONSTRUCTION_ALLOW_REMOTE_EGRESS", "0")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    main._assert_production_operations()

    monkeypatch.setenv("RECONSTRUCTION_BACKEND", "remote")
    with pytest.raises(RuntimeError, match="remote reconstruction"):
        main._assert_production_operations()

    monkeypatch.setenv("RECONSTRUCTION_BACKEND", "local")
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.ingest.sentry.io/1")
    with pytest.raises(RuntimeError, match="SENTRY_DSN"):
        main._assert_production_operations()


def set_valid_transport_security(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_TLS_REQUIRED", "1")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://app.cadverify.com")
    monkeypatch.setenv("REDIS_URL", "rediss://cache.example.com:6379/0")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@db.example.com/cadverify?sslmode=require",
    )
    monkeypatch.setenv(
        "DATABASE_URL_DIRECT",
        "postgresql://user:pass@db.example.com/cadverify?sslmode=verify-full",
    )
    monkeypatch.delenv("OBJECT_STORE_S3_ENDPOINT", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)


def test_production_transport_security_passes(monkeypatch):
    set_valid_transport_security(monkeypatch)
    main._assert_production_operations()


@pytest.mark.parametrize(
    "origin",
    [
        "http://app.cadverify.com",
        "https://user:pass@app.cadverify.com",
        "https://app.cadverify.com/path",
        "https://app.cadverify.com?debug=1",
    ],
)
def test_production_requires_canonical_https_dashboard_origin(monkeypatch, origin):
    set_valid_transport_security(monkeypatch)
    monkeypatch.setenv("DASHBOARD_ORIGIN", origin)
    with pytest.raises(RuntimeError, match="DASHBOARD_ORIGIN"):
        main._assert_production_operations()


def test_production_requires_tls_redis(monkeypatch):
    set_valid_transport_security(monkeypatch)
    monkeypatch.setenv("REDIS_URL", "redis://cache.example.com:6379/0")
    with pytest.raises(RuntimeError, match="rediss"):
        main._assert_production_operations()


def test_production_rejects_database_tls_bypass(monkeypatch):
    set_valid_transport_security(monkeypatch)
    monkeypatch.setenv("DB_REQUIRE_TLS", "0")
    with pytest.raises(RuntimeError, match="DB_REQUIRE_TLS"):
        main._assert_production_operations()

    monkeypatch.setenv("DB_REQUIRE_TLS", "1")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@db.example.com/cadverify?sslmode=disable",
    )
    with pytest.raises(RuntimeError, match="insecure sslmode"):
        main._assert_production_operations()


def test_production_local_database_requires_explicit_tls(monkeypatch):
    set_valid_transport_security(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL_DIRECT",
        "postgresql://user:pass@postgres:5432/cadverify",
    )
    with pytest.raises(RuntimeError, match="explicitly enable TLS"):
        main._assert_production_operations()


@pytest.mark.parametrize(
    ("name", "value", "match"),
    [
        ("OBJECT_STORE_S3_ENDPOINT", "http://minio.example.com", "OBJECT_STORE"),
        ("SENTRY_DSN", "http://public@sentry.example.com/1", "SENTRY_DSN"),
    ],
)
def test_production_requires_https_external_services(monkeypatch, name, value, match):
    set_valid_transport_security(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=match):
        main._assert_production_operations()


def test_regulated_otlp_requires_https_and_ca(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_OTLP_TLS_REQUIRED", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_CERTIFICATE", raising=False)
    with pytest.raises(RuntimeError, match="must use https"):
        main._assert_production_operations()

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector:4318")
    with pytest.raises(RuntimeError, match="CERTIFICATE"):
        main._assert_production_operations()

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_CERTIFICATE", "/run/otel/ca.crt")
    main._assert_production_operations()


def test_regulated_storage_requires_kms_key(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_KMS_REQUIRED", "1")
    monkeypatch.delenv("OBJECT_STORE_S3_KMS_KEY_ID", raising=False)
    with pytest.raises(RuntimeError, match="KMS_KEY_ID"):
        main._assert_production_operations()
    monkeypatch.setenv("OBJECT_STORE_S3_KMS_KEY_ID", "arn:aws-us-gov:kms:key/real")
    main._assert_production_operations()


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


def test_prod_google_mode_with_enabled_magic_missing_resend_refuses(monkeypatch):
    """An enabled production route may never be left half-configured."""
    monkeypatch.setenv("RELEASE", "v1.0.0")
    set_valid_session_secrets(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "real-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "real-secret")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="magic-link enabled"):
        main._assert_production_secrets()
