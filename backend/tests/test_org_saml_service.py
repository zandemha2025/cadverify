from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from ulid import ULID

from src.db.models import Membership, Organization, SamlGroupMapping, User
from src.services.org_saml_service import (
    SamlGroupMappingAmbiguousError,
    apply_saml_group_assignment,
    normalize_saml_attributes,
)


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


@pytest.mark.asyncio
async def test_saml_group_assignment_ambiguous_orgs_fail_closed_without_write():
    engine, maker = await _maker()
    try:
        async with maker() as session:
            session.add_all(
                [
                    _org("org_personal", "Personal"),
                    _org("org_a", "A"),
                    _org("org_b", "B"),
                    _user(3),
                    _membership("org_personal", 3, "admin"),
                    _mapping(3, "org_a", "cn=shared-cad", "member"),
                    _mapping(4, "org_b", "cn=shared-cad", "viewer"),
                ]
            )
            await session.execute(
                User.__table__.update()
                .where(User.id == 3)
                .values(current_org_id="org_personal")
            )
            await session.commit()

        async with maker() as session:
            with pytest.raises(SamlGroupMappingAmbiguousError):
                await apply_saml_group_assignment(
                    session, 3, {"memberOf": ["cn=shared-cad"]}
                )
            await session.rollback()

        async with maker() as session:
            joined_enterprise_orgs = (
                await session.execute(
                    select(func.count())
                    .select_from(Membership)
                    .where(
                        Membership.user_id == 3,
                        Membership.org_id.in_(["org_a", "org_b"]),
                    )
                )
            ).scalar_one()
            active = (
                await session.execute(select(User.current_org_id).where(User.id == 3))
            ).scalar_one()

        assert joined_enterprise_orgs == 0
        assert active == "org_personal"
    finally:
        await engine.dispose()
