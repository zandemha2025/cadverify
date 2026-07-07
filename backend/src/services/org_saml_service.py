"""SAML group-to-organization role mapping.

Enterprise IdPs commonly send group claims such as ``groups`` or ``memberOf``.
This service turns a configured claim value into a CadVerify org membership at
login time. It is deliberately JIT assignment, not SCIM: matching groups can
grant/promote membership and choose the active org; missing groups never demote
or deprovision existing memberships.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import Membership, SamlGroupMapping, User
from src.services.org_service import ORG_ROLE_RANK, VALID_ORG_ROLES

MAX_ATTRIBUTE_NAME_LEN = 200
MAX_GROUP_VALUE_LEN = 1000
MAX_ASSERTION_VALUES = 256


class SamlGroupMappingAmbiguousError(Exception):
    """Raised when one assertion matches mappings in multiple organizations."""

    def __init__(self, org_ids: list[str]):
        super().__init__("SAML assertion matched multiple organizations")
        self.org_ids = sorted(set(org_ids))


@dataclass(frozen=True)
class SamlGroupAssignment:
    matched: bool
    org_id: str | None = None
    org_role: str | None = None
    created: bool = False
    promoted: bool = False
    unchanged: bool = False
    matched_mapping_ids: tuple[int, ...] = ()
    attribute_names: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if not self.matched:
            return "no_match"
        if self.created:
            return "created"
        if self.promoted:
            return "promoted"
        return "unchanged"

    def to_audit_detail(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "org_id": self.org_id,
            "org_role": self.org_role,
            "matched_mapping_ids": list(self.matched_mapping_ids),
            "attribute_names": list(self.attribute_names),
            "note": "jit_group_assignment_no_demote_no_deprovision",
        }


def normalize_saml_attributes(attributes: dict[str, Any] | None) -> dict[str, list[str]]:
    """Return a trimmed ``attribute -> values`` mapping safe for exact matching."""
    if not attributes:
        return {}
    out: dict[str, list[str]] = {}
    total = 0
    for raw_name, raw_values in attributes.items():
        name = str(raw_name or "").strip()
        if not name:
            continue
        if isinstance(raw_values, str) or raw_values is None:
            values_iter = [raw_values]
        else:
            try:
                values_iter = list(raw_values)
            except TypeError:
                values_iter = [raw_values]

        clean_values: list[str] = []
        seen: set[str] = set()
        for raw_value in values_iter:
            value = str(raw_value or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            clean_values.append(value)
            total += 1
            if total >= MAX_ASSERTION_VALUES:
                break
        if clean_values:
            out[name] = clean_values
        if total >= MAX_ASSERTION_VALUES:
            break
    return out


def _clean_config_text(value: str, field: str, max_len: int) -> str:
    clean = (value or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail=f"{field} is required.")
    if len(clean) > max_len:
        raise HTTPException(
            status_code=400, detail=f"{field} is too long (max {max_len})."
        )
    return clean


def _validate_org_role(role: str) -> str:
    clean = (role or "").strip().lower()
    if clean not in VALID_ORG_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{role}'. Must be one of {sorted(VALID_ORG_ROLES)}.",
        )
    return clean


async def list_saml_group_mappings(
    session: AsyncSession, org_id: str
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(SamlGroupMapping)
            .where(SamlGroupMapping.org_id == org_id)
            .order_by(
                SamlGroupMapping.attribute_name.asc(),
                SamlGroupMapping.group_value.asc(),
                SamlGroupMapping.id.asc(),
            )
        )
    ).scalars().all()
    return [serialize_mapping(row) for row in rows]


async def create_saml_group_mapping(
    session: AsyncSession,
    org_id: str,
    *,
    attribute_name: str,
    group_value: str,
    org_role: str,
    created_by: int | None,
) -> SamlGroupMapping:
    attr = _clean_config_text(attribute_name, "attribute_name", MAX_ATTRIBUTE_NAME_LEN)
    value = _clean_config_text(group_value, "group_value", MAX_GROUP_VALUE_LEN)
    role = _validate_org_role(org_role)

    duplicate = (
        await session.execute(
            select(SamlGroupMapping.id).where(
                SamlGroupMapping.org_id == org_id,
                SamlGroupMapping.attribute_name == attr,
                SamlGroupMapping.group_value == value,
            )
        )
    ).scalars().first()
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail="A SAML group mapping for this org, attribute, and value already exists.",
        )

    row = SamlGroupMapping(
        org_id=org_id,
        attribute_name=attr,
        group_value=value,
        org_role=role,
        created_by=created_by,
    )
    session.add(row)
    await session.flush()
    return row


async def delete_saml_group_mapping(
    session: AsyncSession, org_id: str, mapping_id: int
) -> SamlGroupMapping:
    row = (
        await session.execute(
            select(SamlGroupMapping).where(
                SamlGroupMapping.org_id == org_id,
                SamlGroupMapping.id == mapping_id,
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="SAML group mapping not found.")
    await session.delete(row)
    await session.flush()
    return row


def serialize_mapping(row: SamlGroupMapping) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "attribute_name": row.attribute_name,
        "group_value": row.group_value,
        "org_role": row.org_role,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def resolve_saml_group_assignment(
    session: AsyncSession, attributes: dict[str, Any] | None
) -> SamlGroupAssignment:
    normalized = normalize_saml_attributes(attributes)
    if not normalized:
        return SamlGroupAssignment(matched=False)

    pairs = {
        (attribute_name, group_value)
        for attribute_name, values in normalized.items()
        for group_value in values
    }
    attribute_names = tuple(sorted(normalized))
    values = sorted({value for values_for_attr in normalized.values() for value in values_for_attr})
    rows = (
        await session.execute(
            select(SamlGroupMapping).where(
                SamlGroupMapping.attribute_name.in_(sorted(normalized)),
                SamlGroupMapping.group_value.in_(values),
            )
        )
    ).scalars().all()
    matches = [
        row
        for row in rows
        if (row.attribute_name, row.group_value) in pairs
        and row.org_role in VALID_ORG_ROLES
    ]
    if not matches:
        return SamlGroupAssignment(matched=False, attribute_names=attribute_names)

    org_ids = sorted({row.org_id for row in matches})
    if len(org_ids) > 1:
        raise SamlGroupMappingAmbiguousError(org_ids)

    best = max(matches, key=lambda row: ORG_ROLE_RANK[row.org_role])
    return SamlGroupAssignment(
        matched=True,
        org_id=best.org_id,
        org_role=best.org_role,
        matched_mapping_ids=tuple(sorted(int(row.id) for row in matches if row.id is not None)),
        attribute_names=attribute_names,
    )


async def apply_saml_group_assignment(
    session: AsyncSession, user_id: int, attributes: dict[str, Any] | None
) -> SamlGroupAssignment:
    """Grant/promote org membership from SAML attributes and select active org."""
    assignment = await resolve_saml_group_assignment(session, attributes)
    if not assignment.matched or assignment.org_id is None or assignment.org_role is None:
        return assignment

    membership = (
        await session.execute(
            select(Membership).where(
                Membership.org_id == assignment.org_id,
                Membership.user_id == user_id,
            )
        )
    ).scalars().first()
    created = False
    promoted = False
    unchanged = False
    if membership is None:
        session.add(
            Membership(
                id=str(ULID()),
                org_id=assignment.org_id,
                user_id=user_id,
                org_role=assignment.org_role,
            )
        )
        created = True
    else:
        current_rank = ORG_ROLE_RANK.get(membership.org_role, 0)
        mapped_rank = ORG_ROLE_RANK[assignment.org_role]
        if mapped_rank > current_rank:
            membership.org_role = assignment.org_role
            promoted = True
        else:
            unchanged = True

    await session.execute(
        User.__table__.update()
        .where(User.id == user_id)
        .values(current_org_id=assignment.org_id)
    )
    await session.flush()
    return SamlGroupAssignment(
        matched=True,
        org_id=assignment.org_id,
        org_role=assignment.org_role,
        created=created,
        promoted=promoted,
        unchanged=unchanged,
        matched_mapping_ids=assignment.matched_mapping_ids,
        attribute_names=assignment.attribute_names,
    )
