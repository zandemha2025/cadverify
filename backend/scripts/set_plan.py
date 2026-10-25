"""Staff: set one account's plan (trial, pro or pilot), with a reason, audited.

    cd backend
    DATABASE_URL=postgresql://… python -m scripts.set_plan \\
        --email dana@northfieldpumps.com --plan pilot \\
        --reason "Pilot agreed with Northfield Pumps, 2026-10-22"

The account is named by ``--email`` (matched the way sign-in stores it: lower
case, without a "+tag", Gmail dots dropped) or by ``--user-id``. An email that
could mean more than one account is refused with their ids, to run again with
``--user-id``. It prints the account as it is and asks before changing it
(``--yes`` skips the question, for a reviewed run). It then writes a
``user.plan_changed`` audit row (actor "staff script"; from, to and the reason)
in the same transaction as the change, so the organization's Activity shows it.
The same plan again changes nothing and writes nothing. This is a command an
operator runs with database access, never a web route; it replaces setting
``users.plan`` by hand (docs/operations/free-checks.md, "Giving an account more
checks").

What each plan means is unchanged by this script:
  * ``pilot``: unlimited checks and the tools that need approved access. Stripe
    billing only moves accounts between trial and pro, so it never overwrites it.
  * ``pro``: Pro's monthly allowance needs an active Stripe subscription; without
    one the account keeps the free allowance until Stripe records one.
  * ``trial``: the remaining lifetime free allowance (usage is never erased). An
    account with an active Pro subscription is set back to pro by Stripe's next
    subscription event.

Exit codes: 0 done (or nothing to change), 2 refused (no such account, an
email matching more than one account, a deleted account, a missing reason, an
unknown plan, the change not confirmed, or the plan changing while asked).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Callable, Optional, Sequence

PLANS = ("trial", "pro", "pilot")
ACTOR = "staff script"
MAX_REASON = 500


class Refused(Exception):
    """A request the script won't carry out; the message says why."""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.set_plan",
        description="Set one account's plan, with a reason, audited (actor \"staff script\").",
    )
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--email", help="the account's email address")
    who.add_argument("--user-id", type=int, help="the account's id (when an email matches more than one)")
    p.add_argument("--plan", required=True, choices=PLANS, help="trial, pro or pilot")
    p.add_argument("--reason", required=True, help="why (kept on the audit row), e.g. the agreement it follows")
    p.add_argument("--yes", action="store_true", help="change it without asking first")
    return p


def _ask(prompt: str) -> bool:
    """Yes only for an explicit y or yes; no answer (end of input) is no."""
    try:
        answer = input(prompt)
    except EOFError:
        print()
        return False
    return answer.strip().lower() in ("y", "yes")


async def _find_account(session, email: Optional[str], user_id: Optional[int]):
    """The one account ``email`` or ``user_id`` names, else ``Refused``.

    An email is matched in the form sign-in stores it (``normalize_email``), and
    also as typed, for an account stored before that form existed. More than one
    account answering is refused: the operator picks one with ``--user-id``.
    """
    from sqlalchemy import func, or_, select

    from src.auth.disposable import normalize_email
    from src.db.models import User

    if user_id is not None:
        user = (await session.execute(select(User).where(User.id == int(user_id)))).scalars().first()
        if user is None:
            raise Refused(f"No account with id {user_id}.")
        return user
    typed = (email or "").strip()
    if "@" not in typed:
        raise Refused("Give the account's email address, or its id with --user-id.")
    matches = (await session.execute(
        select(User).where(or_(User.email_lower == normalize_email(typed),
                               func.lower(User.email) == typed.lower())).order_by(User.id)
    )).scalars().all()
    if not matches:
        raise Refused("No account with that email.")
    if len(matches) > 1:
        which = ", ".join(f"{u.id} ({u.email})" for u in matches)
        raise Refused(f"That email matches more than one account: {which}. Run again with --user-id.")
    return matches[0]


def _line(label: str, user_id: int, email: str, plan: str, org: Optional[str], billing: Optional[str]) -> str:
    bits = [f"account {user_id} {email}", f"plan {plan}"]
    bits.append(f"organization {org}" if org else "no organization")
    bits.append(f"Stripe {billing}" if billing else "no Stripe subscription")
    return f"{label} " + " · ".join(bits)


async def set_plan(
    session,
    email: Optional[str],
    plan: str,
    reason: str,
    out=print,
    *,
    user_id: Optional[int] = None,
    confirm: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Set the plan of the account ``email`` (or ``user_id``) names; returns
    whether it changed.

    ``confirm``, when given, is asked after the account is shown and before
    anything changes; no row is locked while it waits. The caller commits.
    Raises ``Refused`` for a request it won't carry out."""
    from sqlalchemy import select

    from src.auth.org_context import resolve_org
    from src.auth.validation_caps import PRO_ACTIVE_STATUSES
    from src.db.models import BillingAccount, User
    from src.services.audit_service import emit_event
    from src.services.person_label import is_deleted_account

    if plan not in PLANS:
        raise Refused(f"Plan must be one of {', '.join(PLANS)}.")
    reason = " ".join((reason or "").split())
    if not reason:
        raise Refused("A reason is required (it is kept on the audit row).")
    if len(reason) > MAX_REASON:
        raise Refused(f"Keep the reason under {MAX_REASON} characters.")
    user = await _find_account(session, email, user_id)
    if is_deleted_account(user.email):
        raise Refused("That account was deleted; its plan can't change.")
    status = (await session.execute(
        select(BillingAccount.status).where(BillingAccount.user_id == user.id)
    )).scalar_one_or_none()
    billing = status if status and status != "none" else None
    org = await resolve_org(session, user.id)
    before = user.plan
    out(_line("Before:", user.id, user.email, before, org, billing))
    if not user.is_active:
        out("Note: this account is deactivated; it can't sign in until it is reactivated.")
    if before == plan:
        out(f"Already on {plan}; nothing changed.")
        return False
    if confirm is not None and not confirm(f"Change account {user.id} {user.email} from {before} to {plan}? [y/N] "):
        raise Refused("Not confirmed; nothing changed.")
    # Lock the row only now, and change it only if it is still what was shown.
    user = (await session.execute(
        select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True)
    )).scalars().one()
    if user.plan != before:
        raise Refused(f"Its plan changed to {user.plan} meanwhile; nothing changed. Run again.")
    user.plan = plan
    await emit_event(
        session, None, "user.plan_changed", "user", str(user.id),
        {"from": before, "to": plan, "reason": reason, "by": ACTOR, "user_id": user.id, "email": user.email},
        user_email=ACTOR, org_id=org,
    )
    await session.flush()
    out(_line("After: ", user.id, user.email, plan, org, billing))
    active_pro = billing in PRO_ACTIVE_STATUSES
    if plan == "pro" and not active_pro:
        out("No active Pro subscription: until Stripe records one, this account has the free allowance.")
    if plan == "trial" and active_pro:
        out("This account has an active Pro subscription: Stripe's next subscription event sets it back to pro.")
    return True


async def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    import src.db.engine as eng

    await eng.init_engine()
    try:
        async with eng.get_session_factory()() as session:
            try:
                changed = await set_plan(
                    session, args.email, args.plan, args.reason,
                    user_id=args.user_id, confirm=None if args.yes else _ask,
                )
            except Refused as exc:
                await session.rollback()
                print(str(exc), file=sys.stderr)
                return 2
            await session.commit()
        if changed:
            print(f"Done. Audit row user.plan_changed written (actor \"{ACTOR}\").")
        return 0
    finally:
        await eng.dispose_engine()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
