"""A deleted account reads "Deleted account" wherever a record names who made it.

Account deletion keeps the account row as a tombstone whose email becomes
``deleted-account-<id>@deleted.invalid`` (and clears the name), and the audit
rows the person made read ``deleted account``. A record that names its maker by
name-else-email (the share's "made by", the sign-off stamp, the pilot report's
"By") would otherwise print the tombstone address. One backend helper,
``person_label``, names people for every such place.
"""
from __future__ import annotations

import pytest

from src.db.models import Membership, Organization, User
from src.services.account_deletion_service import ACCOUNT_DELETED_EMAIL, tombstone_email
from src.services.person_label import DELETED_ACCOUNT, is_deleted_account, person_label
from tests.sqlite_tables import sqlite_sessionmaker


def test_a_tombstone_or_redacted_actor_reads_deleted_account():
    assert person_label(None, tombstone_email(52)) == DELETED_ACCOUNT == "Deleted account"
    assert person_label("", "Deleted-Account-7@DELETED.invalid") == "Deleted account"
    assert person_label(None, ACCOUNT_DELETED_EMAIL) == "Deleted account"
    assert is_deleted_account(tombstone_email(52)) and is_deleted_account(" deleted account ")


def test_a_person_reads_as_their_name_else_their_email():
    assert person_label("Dana Ortiz", "dana@northfieldpumps.com") == "Dana Ortiz"
    assert person_label("  ", "dana@northfieldpumps.com") == "dana@northfieldpumps.com"
    assert person_label(None, None) is None
    # Only the exact tombstone shape: a real address that merely looks close is a person.
    for email in ("deleted-account-x@deleted.invalid", "deleted-account-5@deleted.invalid.com",
                  "dana+deleted-account-5@deleted.invalid.example.com"):
        assert not is_deleted_account(email)
        assert person_label(None, email) == email


@pytest.mark.asyncio
async def test_the_sign_off_stamp_and_pilot_report_name_a_deleted_signer_deleted_account():
    from src.services.signoff_service import names_for

    engine, maker = await sqlite_sessionmaker(Organization, User, Membership)
    try:
        async with maker() as s:
            s.add_all([
                User(id=1, email="dana@northfieldpumps.com", email_lower="dana@northfieldpumps.com",
                     full_name="Dana Ortiz", role="analyst", auth_provider="password"),
                User(id=2, email="sam@northfieldpumps.com", email_lower="sam@northfieldpumps.com",
                     role="analyst", auth_provider="password"),
                User(id=52, email=tombstone_email(52), email_lower=tombstone_email(52),
                     role="analyst", auth_provider="password", is_active=False),
            ])
            await s.commit()
            assert await names_for(s, [1, 2, 52, None]) == {
                1: "Dana Ortiz", 2: "sam@northfieldpumps.com", 52: "Deleted account"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_share_made_by_a_deleted_account_reads_deleted_account():
    from datetime import datetime, timezone

    from src.db.models import Analysis, ApiKey, CostDecision, Job, RfqPackage
    from src.services import share_links

    engine, maker = await sqlite_sessionmaker(Organization, User, Membership, ApiKey, Analysis, Job, CostDecision, RfqPackage)
    try:
        async with maker() as s:
            s.add(Organization(id="01ORG0000000000000000000NF", name="Northfield Pumps", slug="nfp"))
            s.add_all([
                User(id=1, email="dana@northfieldpumps.com", email_lower="dana@northfieldpumps.com",
                     full_name="Dana Ortiz", role="analyst", auth_provider="password"),
                User(id=52, email=tombstone_email(52), email_lower=tombstone_email(52),
                     role="analyst", auth_provider="password", is_active=False),
            ])
            await s.flush()
            s.add(Membership(org_id="01ORG0000000000000000000NF", user_id=1, org_role="admin"))
            now = datetime.now(timezone.utc)
            for uid, short in ((1, "AAAAAAAAAAAA"), (52, "BBBBBBBBBBBB")):
                s.add(Analysis(ulid=f"01ANALYSIS00000000000000{uid:02d}", user_id=uid, org_id="01ORG0000000000000000000NF",
                               mesh_hash=f"{uid:064d}", process_set_hash="p", analysis_version="v", filename=f"part-{uid}.step",
                               file_type="step", file_size_bytes=1,
                               result_json={}, verdict="pass", face_count=1, duration_ms=1.0,
                               is_public=True, share_short_id=short, share_created_at=now, share_created_by=uid))
            await s.commit()
            links = await share_links.list_links(s, "01ORG0000000000000000000NF", 1, everyone=True)
        made_by = {link["name"]: link["made_by"] for link in links}
        assert made_by == {"part-1.step": "Dana Ortiz", "part-52.step": "Deleted account"}
    finally:
        await engine.dispose()
