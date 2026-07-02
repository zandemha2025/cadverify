"""Tests for the production DB TLS default (M4)."""
from __future__ import annotations

from src.db import engine


def test_prod_remote_host_gets_sslmode(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.2.3")
    monkeypatch.delenv("DB_REQUIRE_TLS", raising=False)
    out = engine._ensure_prod_tls("postgresql://u:p@ep-x.aws.neon.tech/db")
    assert "sslmode=require" in out
    # And it survives the asyncpg conversion as ssl=require.
    assert "ssl=require" in engine._async_url(out)


def test_prod_appends_with_existing_query(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.2.3")
    monkeypatch.delenv("DB_REQUIRE_TLS", raising=False)
    out = engine._ensure_prod_tls("postgresql://u:p@ep.neon.tech/db?application_name=cv")
    assert out.count("?") == 1
    assert "&sslmode=require" in out


def test_prod_localhost_unchanged(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.2.3")
    monkeypatch.delenv("DB_REQUIRE_TLS", raising=False)
    for host in ("localhost", "127.0.0.1", "postgres", "[::1]"):
        url = f"postgresql://u:p@{host}:5432/db"
        assert engine._ensure_prod_tls(url) == url


def test_dev_remote_host_unchanged(monkeypatch):
    monkeypatch.setenv("RELEASE", "dev")
    monkeypatch.delenv("DB_REQUIRE_TLS", raising=False)
    url = "postgresql://u:p@ep.neon.tech/db"
    assert engine._ensure_prod_tls(url) == url


def test_existing_sslmode_not_doubled(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.2.3")
    monkeypatch.delenv("DB_REQUIRE_TLS", raising=False)
    url = "postgresql://u:p@ep.neon.tech/db?sslmode=require"
    assert engine._ensure_prod_tls(url) == url
    # asyncpg 'ssl=' form is also respected.
    url2 = "postgresql://u:p@ep.neon.tech/db?ssl=require"
    assert engine._ensure_prod_tls(url2) == url2


def test_off_switch(monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.2.3")
    monkeypatch.setenv("DB_REQUIRE_TLS", "0")
    url = "postgresql://u:p@ep.neon.tech/db"
    assert engine._ensure_prod_tls(url) == url
