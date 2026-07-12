"""Fail-closed operational configuration shared by API and worker processes."""
from __future__ import annotations

import base64
import os
from urllib.parse import parse_qs, urlsplit

_TRUTHY = {"1", "true", "yes", "on"}
_DEV_RELEASES = {"", "dev", "development", "local", "test", "ci"}


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in _TRUTHY


def is_production() -> bool:
    return os.getenv("RELEASE", "dev").strip().lower() not in _DEV_RELEASES


def _strong_base64_secret(name: str, *, exact_bytes: int | None = None) -> None:
    """Reject absent, malformed, short, or obvious low-entropy launch stubs."""
    raw = os.getenv(name, "").strip()
    try:
        decoded = base64.b64decode(raw, altchars=b"-_", validate=True)
    except Exception as exc:
        raise RuntimeError(f"{name} must be valid base64") from exc
    if exact_bytes is not None:
        valid_length = len(decoded) == exact_bytes
    else:
        valid_length = len(decoded) >= 32
    if not valid_length:
        expected = f"exactly {exact_bytes}" if exact_bytes is not None else "at least 32"
        raise RuntimeError(f"{name} must decode to {expected} bytes")
    # Public handoff stubs commonly repeat one byte (base64(a*32), etc.). A
    # real 256-bit random secret having fewer than eight distinct bytes is
    # vanishingly unlikely; reject that entire unsafe class without printing it.
    if len(set(decoded)) < 8:
        raise RuntimeError(f"{name} appears to be a low-entropy launch stub")


def assert_production_operations() -> None:
    """Reject released API/worker processes with incomplete production wiring."""
    if not is_production():
        return

    if _enabled("RATE_LIMIT_ALLOW_MEMORY"):
        raise RuntimeError(
            "RATE_LIMIT_ALLOW_MEMORY cannot be enabled in a released process"
        )

    if _enabled("PARSE_PROCESS_POOL_DISABLED"):
        raise RuntimeError(
            "PARSE_PROCESS_POOL_DISABLED cannot be enabled in production; "
            "untrusted CAD must run in killable worker processes"
        )

    if _enabled("PRODUCTION_CRYPTO_SECRET_QUALITY_REQUIRED"):
        session_secret = os.getenv("SESSION_SECRET", "").strip()
        if (
            len(session_secret) < 32
            or len(set(session_secret)) < 8
            or any(
                marker in session_secret.lower()
                for marker in ("change-me", "dev-only", "test-secret")
            )
        ):
            raise RuntimeError(
                "SESSION_SECRET must be a strong non-development production secret"
            )
        for name in (
            "DASHBOARD_SESSION_SECRET",
            "AUTH_PROXY_SECRET",
            "API_KEY_PEPPER",
            "CONNECTOR_FINGERPRINT_KEY",
            "DEEP_HEALTH_TOKEN",
        ):
            _strong_base64_secret(name)
        _strong_base64_secret("CONNECTOR_SECRET_KEY", exact_bytes=32)
        if _enabled("MAGIC_LINK_ENABLED"):
            _strong_base64_secret("MAGIC_LINK_SECRET")

    if _enabled("PRODUCTION_STORAGE_REQUIRED"):
        if os.getenv("OBJECT_STORE_BACKEND", "local").strip().lower() != "s3":
            raise RuntimeError(
                "PRODUCTION_STORAGE_REQUIRED is enabled but "
                "OBJECT_STORE_BACKEND is not 's3'; refusing to start."
            )
        for var in ("OBJECT_STORE_S3_BUCKET", "OBJECT_STORE_S3_REGION"):
            if not os.getenv(var, "").strip():
                raise RuntimeError(
                    f"{var} is required when production S3 storage is enforced; "
                    "refusing to start."
                )

    if _enabled("PRODUCTION_OBSERVABILITY_REQUIRED"):
        sentry = os.getenv("SENTRY_DSN", "").strip()
        otlp = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not sentry and not otlp:
            raise RuntimeError(
                "PRODUCTION_OBSERVABILITY_REQUIRED is enabled but neither "
                "SENTRY_DSN nor OTEL_EXPORTER_OTLP_ENDPOINT is configured; "
                "refusing to start."
            )

    if _enabled("PRODUCTION_DEEP_HEALTH_AUTH_REQUIRED"):
        deep_health_token = os.getenv("DEEP_HEALTH_TOKEN", "").strip()
        if len(deep_health_token) < 32:
            raise RuntimeError(
                "DEEP_HEALTH_TOKEN must contain at least 32 characters when "
                "production deep-health authentication is enforced"
            )

    if _enabled("PRODUCTION_AUTH_PROXY_REQUIRED"):
        raw = os.getenv("AUTH_PROXY_SECRET", "").strip()
        try:
            auth_proxy_secret = base64.b64decode(raw, validate=True)
        except Exception as exc:
            raise RuntimeError(
                "AUTH_PROXY_SECRET must be valid base64 when the production "
                "auth proxy is enforced"
            ) from exc
        if len(auth_proxy_secret) < 32:
            raise RuntimeError(
                "AUTH_PROXY_SECRET must decode to at least 32 bytes when the "
                "production auth proxy is enforced"
            )

    if _enabled("PRODUCTION_VERIFIED_SIGNUP_REQUIRED") and _enabled(
        "PUBLIC_PASSWORD_SIGNUP_ENABLED"
    ):
        raise RuntimeError(
            "PUBLIC_PASSWORD_SIGNUP_ENABLED must be disabled when production "
            "verified signup is enforced"
        )

    if _enabled("PRODUCTION_HOST_ONLY_SESSION_COOKIE_REQUIRED") and os.getenv(
        "SESSION_COOKIE_DOMAIN", ""
    ).strip():
        raise RuntimeError(
            "SESSION_COOKIE_DOMAIN must be empty when host-only production "
            "sessions are required"
        )

    if _enabled("PRODUCTION_SSRF_GUARD_REQUIRED") and not _enabled(
        "WEBHOOK_SSRF_GUARD_ENABLED"
    ):
        raise RuntimeError(
            "WEBHOOK_SSRF_GUARD_ENABLED cannot be disabled in this production "
            "deployment"
        )

    if _enabled("PRODUCTION_SECURITY_HEADERS_REQUIRED") and not _enabled(
        "SECURITY_HEADERS_ENABLED"
    ):
        raise RuntimeError(
            "SECURITY_HEADERS_ENABLED cannot be disabled in this production "
            "deployment"
        )

    if _enabled("PRODUCTION_REGULATED_BOUNDARY_REQUIRED"):
        auth_mode = os.getenv("AUTH_MODE", "").strip().lower()
        if auth_mode != "saml":
            raise RuntimeError(
                "regulated production requires AUTH_MODE=saml for the approved "
                "delivery baseline"
            )
        if _enabled("PASSWORD_LOGIN_ENABLED") or _enabled("MAGIC_LINK_ENABLED"):
            raise RuntimeError(
                "regulated SAML production must disable password and magic-link auth"
            )
        reconstruction_backend = os.getenv(
            "RECONSTRUCTION_BACKEND", "local"
        ).strip().lower()
        if reconstruction_backend not in {"local", "none"} or _enabled(
            "RECONSTRUCTION_ALLOW_REMOTE_EGRESS"
        ):
            raise RuntimeError(
                "regulated production prohibits remote reconstruction egress"
            )
        if os.getenv("SENTRY_DSN", "").strip():
            raise RuntimeError(
                "regulated production prohibits the external SENTRY_DSN sink; "
                "use the in-boundary OTLP collector"
            )

    if _enabled("PRODUCTION_TLS_REQUIRED"):
        dashboard_origin = os.getenv("DASHBOARD_ORIGIN", "").strip()
        try:
            dashboard = urlsplit(dashboard_origin)
        except ValueError as exc:
            raise RuntimeError("DASHBOARD_ORIGIN is not a valid HTTPS origin") from exc
        if (
            dashboard.scheme != "https"
            or not dashboard.hostname
            or dashboard.username
            or dashboard.password
            or dashboard.path not in {"", "/"}
            or dashboard.query
            or dashboard.fragment
        ):
            raise RuntimeError(
                "DASHBOARD_ORIGIN must be a canonical HTTPS origin in production"
            )

        redis_url = os.getenv("REDIS_URL", "").strip()
        if not redis_url.lower().startswith("rediss://"):
            raise RuntimeError(
                "REDIS_URL must use rediss:// when production TLS is enforced"
            )

        if os.getenv("DB_REQUIRE_TLS", "1").strip().lower() not in _TRUTHY:
            raise RuntimeError(
                "DB_REQUIRE_TLS cannot be disabled when production TLS is enforced"
            )
        for database_var in ("DATABASE_URL", "DATABASE_URL_DIRECT"):
            database_url = os.getenv(database_var, "").strip()
            if not database_url:
                raise RuntimeError(
                    f"{database_var} is required when production TLS is enforced"
                )
            parsed_database = urlsplit(database_url)
            if parsed_database.scheme not in {"postgresql", "postgresql+asyncpg"}:
                raise RuntimeError(f"{database_var} must be a PostgreSQL URL")
            query = parse_qs(parsed_database.query, keep_blank_values=True)
            sslmode = [value.lower() for value in query.get("sslmode", [])]
            ssl = [value.lower() for value in query.get("ssl", [])]
            secure_modes = {"require", "verify-ca", "verify-full", "true", "1"}
            if sslmode and any(value not in secure_modes for value in sslmode):
                raise RuntimeError(
                    f"{database_var} contains an insecure sslmode setting"
                )
            if ssl and any(value not in secure_modes for value in ssl):
                raise RuntimeError(f"{database_var} contains an insecure ssl setting")
            host = (parsed_database.hostname or "").lower()
            if host in {"", "localhost", "127.0.0.1", "::1", "postgres"} and not (
                sslmode or ssl
            ):
                raise RuntimeError(
                    f"{database_var} must explicitly enable TLS for a local hostname"
                )

        object_endpoint = os.getenv("OBJECT_STORE_S3_ENDPOINT", "").strip()
        if object_endpoint and urlsplit(object_endpoint).scheme != "https":
            raise RuntimeError(
                "OBJECT_STORE_S3_ENDPOINT must use https in production"
            )

        sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
        if sentry_dsn and urlsplit(sentry_dsn).scheme != "https":
            raise RuntimeError("SENTRY_DSN must use https in production")

    if _enabled("PRODUCTION_OTLP_TLS_REQUIRED"):
        otlp = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not otlp.lower().startswith("https://"):
            raise RuntimeError(
                "OTEL_EXPORTER_OTLP_ENDPOINT must use https in regulated production"
            )
        if not os.getenv("OTEL_EXPORTER_OTLP_CERTIFICATE", "").strip():
            raise RuntimeError(
                "OTEL_EXPORTER_OTLP_CERTIFICATE is required for regulated production"
            )

    if _enabled("PRODUCTION_KMS_REQUIRED") and not os.getenv(
        "OBJECT_STORE_S3_KMS_KEY_ID", ""
    ).strip():
        raise RuntimeError(
            "OBJECT_STORE_S3_KMS_KEY_ID is required for regulated production"
        )
