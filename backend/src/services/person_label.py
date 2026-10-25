"""How a record names a person: their name, else their email; a deleted account
reads "Deleted account".

Account deletion keeps the account row as a tombstone: its name is cleared and
its email becomes ``deleted-account-<id>@deleted.invalid``
(``account_deletion_service.tombstone_email``), and the audit rows the person
made read ``deleted account`` (``ACCOUNT_DELETED_EMAIL``). Every place that
names who made, signed or recorded something (the share's "made by", the
sign-off stamp, the pilot report's "By") names people through ``person_label``,
so none of them prints the tombstone address. The frontend's twin is
``frontend/src/lib/person-label.ts``.
"""
from __future__ import annotations

import re
from typing import Optional

DELETED_ACCOUNT = "Deleted account"
_TOMBSTONE = re.compile(r"deleted-account-\d+@deleted\.invalid", re.IGNORECASE)
_REDACTED_ACTOR = "deleted account"


def is_deleted_account(email: Optional[str]) -> bool:
    """True for a deleted account's tombstone address or redacted audit actor."""
    if not isinstance(email, str):
        return False
    value = email.strip()
    return bool(_TOMBSTONE.fullmatch(value)) or value.lower() == _REDACTED_ACTOR


def person_label(full_name: Optional[str], email: Optional[str]) -> Optional[str]:
    """The person's name, else their email; "Deleted account" for a deleted one."""
    if is_deleted_account(email):
        return DELETED_ACCOUNT
    return (full_name or "").strip() or email or None
