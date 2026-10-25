"""Unit tests for the W1 org-resolution helpers (src/auth/org_context.py).

Consistent with the repo's mocked-AsyncSession convention (no live DB needed
here); the real create/read behaviour is proven end-to-end by the seeded
up/down/up Postgres proof that accompanies migration 0009.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.auth.org_context import (
    ORG_ROLES,
    ensure_personal_org,
    personal_org_name,
    personal_org_slug,
    resolve_org,
    resolve_org_via_batch,
)


# ---- pure slug/name helpers (no DB) --------------------------------------


def test_slug_shape_local_plus_short_ulid():
    slug = personal_org_slug("Alice.Smith+tag@example.com")
    head, sep, tail = slug.rpartition("-")
    assert sep == "-"
    # local part is lowercased and sanitized to [a-z0-9-]
    assert head == "alice-smith-tag"
    # short-ulid suffix: 8 lowercase base32 chars
    assert len(tail) == 8 and tail == tail.lower() and tail.isalnum()


def test_slug_unique_across_calls_same_email():
    a = personal_org_slug("bob@x.com")
    b = personal_org_slug("bob@x.com")
    assert a != b  # the trailing short-ULID guarantees uniqueness
    assert a.startswith("bob-") and b.startswith("bob-")


def test_slug_empty_local_falls_back():
    slug = personal_org_slug("@weird.com")
    assert slug.startswith("org-")


def test_personal_org_name():
    assert personal_org_name("carol@acme.io") == "carol's Organization"


def test_org_roles_constant():
    assert ORG_ROLES == ("admin", "member", "viewer")


# ---- resolve_org / resolve_org_via_batch ---------------------------------


@pytest.mark.asyncio
async def test_resolve_org_returns_membership_org():
    session = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = "01ORG0000000000000000000AA"
    session.execute.return_value = res
    assert await resolve_org(session, 42) == "01ORG0000000000000000000AA"


@pytest.mark.asyncio
async def test_resolve_org_none_when_no_membership():
    session = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = None
    session.execute.return_value = res
    assert await resolve_org(session, 999) is None


@pytest.mark.asyncio
async def test_resolve_org_via_batch():
    session = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = "01ORGBATCH0000000000000000"
    session.execute.return_value = res
    assert await resolve_org_via_batch(session, 7) == "01ORGBATCH0000000000000000"


# ---- ensure_personal_org (get-or-create) ---------------------------------


@pytest.mark.asyncio
async def test_ensure_personal_org_get_path_is_noop():
    """Existing membership -> return its org, write nothing else."""
    session = AsyncMock()
    res = MagicMock()
    res.first.return_value = ("01ORGEXISTING0000000000000",)
    session.execute.return_value = res

    org_id = await ensure_personal_org(session, 5, "dave@x.com")

    assert org_id == "01ORGEXISTING0000000000000"
    assert session.execute.await_count == 1  # only the lookup SELECT


@pytest.mark.asyncio
async def test_ensure_personal_org_create_path():
    """No membership -> insert org + admin membership + set current_org_id."""
    session = AsyncMock()
    res = MagicMock()
    res.first.return_value = None  # no existing membership
    session.execute.return_value = res

    org_id = await ensure_personal_org(session, 5, "erin@x.com")

    assert isinstance(org_id, str) and len(org_id) == 26  # a ULID
    # 1 lookup + org insert + membership insert + users update
    assert session.execute.await_count == 4
    sql_blob = " ".join(
        str(c.args[0]) for c in session.execute.await_args_list
    ).lower()
    assert "insert into organizations" in sql_blob
    assert "insert into memberships" in sql_blob
    assert "update users set current_org_id" in sql_blob
    # membership is created as admin
    assert "'admin'" in sql_blob
