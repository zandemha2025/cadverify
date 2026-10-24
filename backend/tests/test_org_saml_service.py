from __future__ import annotations

import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from ulid import ULID

from src.db.models import Membership, Organization, SamlGroupMapping, User
from src.auth.org_context import personal_org_name, personal_org_slug
from src.services.org_saml_service import (
    apply_saml_group_assignment,
    create_saml_group_mapping,
    normalize_saml_attributes,
)


@pytest.fixture(autouse=True)
def _enterprise_owns_the_idp(monkeypatch):
    """The deployment's IdP belongs to org_enterprise unless a test says otherwise."""
    monkeypatch.setenv("SSO_ORG_ID", "org_enterprise")


async def _maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for table in (
            Organization.__table__,
            User.__table__,
            Membership.__table__,
            SamlGroupMapping.__table__,
        ):
            await conn.run_sync(table.create)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _user(user_id: int = 1) -> User:
    return User(
        id=user_id,
        email=f"user{user_id}@enterprise.com",
        email_lower=f"user{user_id}@enterprise.com",
        auth_provider="saml",
        role="analyst",
    )


def _org(org_id: str, name: str) -> Organization:
    return Organization(id=org_id, name=name, slug=f"{org_id}-slug")


def _membership(org_id: str, user_id: int, role: str) -> Membership:
    return Membership(
        id=str(ULID()),
        org_id=org_id,
        user_id=user_id,
        org_role=role,
    )


def _mapping(mapping_id: int, org_id: str, value: str, role: str) -> SamlGroupMapping:
    return SamlGroupMapping(
        id=mapping_id,
        org_id=org_id,
        attribute_name="memberOf",
        group_value=value,
        org_role=role,
    )


def test_normalize_saml_attributes_accepts_strings_and_lists():
    out = normalize_saml_attributes(
        {
            " memberOf ": " cn=cad-engineers ",
            "groups": ["Exxon AM", "Exxon AM", "", None, 12],
            "empty": [],
        }
    )
    assert out == {
        "memberOf": ["cn=cad-engineers"],
        "groups": ["Exxon AM", "12"],
    }


@pytest.mark.asyncio
async def test_saml_group_assignment_grants_membership_and_sets_active_org():
    engine, maker = await _maker()
    try:
        async with maker() as session:
            session.add_all(
                [
                    _org("org_personal", "Personal"),
                    _org("org_enterprise", "Enterprise"),
                    _user(1),
                    _membership("org_personal", 1, "admin"),
                    _mapping(1, "org_enterprise", "cn=cad-engineers", "member"),
                ]
            )
            await session.execute(
                User.__table__.update()
                .where(User.id == 1)
                .values(current_org_id="org_personal")
            )
            await session.commit()

        async with maker() as session:
            result = await apply_saml_group_assignment(
                session, 1, {"memberOf": ["cn=cad-engineers"]}
            )
            await session.commit()

        async with maker() as session:
            enterprise = (
                await session.execute(
                    select(Membership).where(
                        Membership.org_id == "org_enterprise",
                        Membership.user_id == 1,
                    )
                )
            ).scalars().one()
            active = (
                await session.execute(select(User.current_org_id).where(User.id == 1))
            ).scalar_one()

        assert result.status == "created"
        assert enterprise.org_role == "member"
        assert active == "org_enterprise"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_saml_group_assignment_promotes_but_never_demotes_manual_admin():
    engine, maker = await _maker()
    try:
        async with maker() as session:
            session.add_all(
                [
                    _org("org_enterprise", "Enterprise"),
                    _user(2),
                    _membership("org_enterprise", 2, "admin"),
                    _mapping(2, "org_enterprise", "cn=viewers", "viewer"),
                ]
            )
            await session.commit()

        async with maker() as session:
            result = await apply_saml_group_assignment(
                session, 2, {"memberOf": ["cn=viewers"]}
            )
            await session.commit()

        async with maker() as session:
            role = (
                await session.execute(
                    select(Membership.org_role).where(
                        Membership.org_id == "org_enterprise",
                        Membership.user_id == 2,
                    )
                )
            ).scalar_one()

        assert result.status == "unchanged"
        assert role == "admin"
    finally:
        await engine.dispose()


async def _seed_duplicate_mappings(maker):
    """Org A holds the real mapping; org B copied the same group value."""
    async with maker() as session:
        session.add_all(
            [
                _org("org_personal", "Personal"),
                _org("org_a", "A"),
                _org("org_b", "B"),
                _user(3),
                _membership("org_personal", 3, "admin"),
                _mapping(3, "org_a", "cn=shared-cad", "member"),
                _mapping(4, "org_b", "cn=shared-cad", "admin"),
            ]
        )
        await session.execute(
            User.__table__.update()
            .where(User.id == 3)
            .values(current_org_id="org_personal")
        )
        await session.commit()


async def _memberships_and_active(maker, user_id: int):
    async with maker() as session:
        rows = (
            await session.execute(
                select(Membership.org_id, Membership.org_role).where(
                    Membership.user_id == user_id
                )
            )
        ).all()
        active = (
            await session.execute(select(User.current_org_id).where(User.id == user_id))
        ).scalar_one()
    return dict(rows), active


@pytest.mark.asyncio
async def test_a_copied_mapping_in_another_org_is_ignored_not_ambiguous(monkeypatch):
    monkeypatch.setenv("SSO_ORG_ID", "org_a")
    engine, maker = await _maker()
    try:
        await _seed_duplicate_mappings(maker)
        async with maker() as session:
            result = await apply_saml_group_assignment(
                session, 3, {"memberOf": ["cn=shared-cad"]}
            )
            await session.commit()
        memberships, active = await _memberships_and_active(maker, 3)

        assert result.status == "created"
        assert result.org_id == "org_a"
        assert memberships == {"org_personal": "admin", "org_a": "member"}
        assert active == "org_a"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_mapping_outside_the_idp_owner_never_pulls_users_in(monkeypatch):
    monkeypatch.setenv("SSO_ORG_ID", "org_enterprise")
    engine, maker = await _maker()
    try:
        await _seed_duplicate_mappings(maker)
        async with maker() as session:
            result = await apply_saml_group_assignment(
                session, 3, {"memberOf": ["cn=shared-cad"]}
            )
            await session.commit()
        memberships, active = await _memberships_and_active(maker, 3)

        assert result.matched is False
        assert memberships == {"org_personal": "admin"}
        assert active == "org_personal"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_mapping_applies_while_no_org_owns_the_idp(monkeypatch):
    monkeypatch.delenv("SSO_ORG_ID", raising=False)
    engine, maker = await _maker()
    try:
        await _seed_duplicate_mappings(maker)
        async with maker() as session:
            result = await apply_saml_group_assignment(
                session, 3, {"memberOf": ["cn=shared-cad"]}
            )
            await session.commit()
        memberships, _active = await _memberships_and_active(maker, 3)

        assert result.matched is False
        assert memberships == {"org_personal": "admin"}
    finally:
        await engine.dispose()


_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


@pytest.fixture
def _pg_engine():
    import src.db.engine as eng

    eng._ENGINE = None
    eng._SESSION_FACTORY = None
    try:
        yield eng
    finally:
        eng._ENGINE = None
        eng._SESSION_FACTORY = None


@_requires_pg
@pytest.mark.asyncio
async def test_mapping_creation_is_limited_to_the_idp_owner(monkeypatch, _pg_engine):
    eng = _pg_engine
    tag = uuid.uuid4().hex[:10]
    email = f"pat-{tag}@corp.example"
    owner, other, personal = (str(ULID()) for _ in range(3))
    orgs = [
        (owner, f"Enterprise {tag}", f"enterprise-{tag}"),
        (other, f"Other Co {tag}", f"other-co-{tag}"),
        (personal, personal_org_name(email), personal_org_slug(email)),
    ]

    async def _create(org_id: str):
        async with eng.get_session_factory()() as session:
            row = await create_saml_group_mapping(
                session,
                org_id,
                attribute_name="memberOf",
                group_value=f"cn=cad-engineers-{tag}",
                org_role="member",
                created_by=None,
            )
            await session.commit()
            return row

    async def _count() -> int:
        async with eng.get_session_factory()() as session:
            return (
                await session.execute(
                    select(func.count())
                    .select_from(SamlGroupMapping)
                    .where(SamlGroupMapping.org_id.in_([owner, other, personal]))
                )
            ).scalar_one()

    try:
        async with eng.get_session_factory()() as session:
            for oid, name, slug in orgs:
                session.add(Organization(id=oid, name=name, slug=slug, is_personal=oid == personal))
            await session.commit()

        monkeypatch.setenv("SSO_ORG_ID", owner)
        row = await _create(owner)
        assert row.org_id == owner

        for org_id in (other, personal):
            with pytest.raises(HTTPException) as exc:
                await _create(org_id)
            assert exc.value.status_code == 403
            assert exc.value.detail["code"] == "sso_org_required"
            # it-02/it-03: plain words, no setting names, and who sets it up.
            message = exc.value.detail["message"]
            assert "SSO_ORG_ID" not in message and "(" not in message
            assert "ScaleCAD support sets it up for your organization: email nazeem@scalecad.ai." in message

        # A personal org is refused even when named as the IdP owner.
        monkeypatch.setenv("SSO_ORG_ID", personal)
        with pytest.raises(HTTPException) as exc:
            await _create(personal)
        assert exc.value.status_code == 403

        monkeypatch.delenv("SSO_ORG_ID")
        with pytest.raises(HTTPException) as exc:
            await _create(owner)
        assert exc.value.status_code == 403

        assert await _count() == 1
    finally:
        async with eng.get_session_factory()() as session:
            await session.execute(
                SamlGroupMapping.__table__.delete().where(
                    SamlGroupMapping.org_id.in_([owner, other, personal])
                )
            )
            await session.execute(
                Organization.__table__.delete().where(
                    Organization.id.in_([owner, other, personal])
                )
            )
            await session.commit()
        await eng.dispose_engine()
