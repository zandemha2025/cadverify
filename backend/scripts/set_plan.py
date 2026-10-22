"""Staff: set one account's plan (trial, pro or pilot), with a reason, audited.

    cd backend
    DATABASE_URL=postgresql://… python -m scripts.set_plan \\
        --email dana@northfieldpumps.com --plan pilot \\
        --reason "Pilot agreed with Northfield Pumps, 2026-10-22"

Prints the account before and after, and writes a ``user.plan_changed`` audit
row (actor "staff script"; from, to and the reason) in the same transaction as
the change, so the organization's Activity shows it. The same plan again changes
nothing and writes nothing. This is a command an operator runs with database
access, never a web route; it replaces setting ``users.plan`` by hand
(docs/operations/free-checks.md, "Giving an account more checks").

What each plan means is unchanged by this script:
  * ``pilot``: unlimited checks and the tools that need approved access. Stripe
    billing only moves accounts between trial and pro, so it never overwrites it.
  * ``pro``: Pro's monthly allowance needs an active Stripe subscription; without
    one the account keeps the free allowance until Stripe records one.
  * ``trial``: the remaining lifetime free allowance (usage is never erased). An
    account with an active Pro subscription is set back to pro by Stripe's next
    subscription event.

Exit codes: 0 done (or nothing to change), 2 refused (no such account, a
deleted account, a missing reason, an unknown plan).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Optional, Sequence

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
    p.add_argument("--email", required=True, help="the account's email address")
    p.add_argument("--plan", required=True, choices=PLANS, help="trial, pro or pilot")
    p.add_argument("--reason", required=True, help="why (kept on the audit row), e.g. the agreement it follows")
    return p


def _line(label: str, user_id: int, email: str, plan: str, org: Optional[str], billing: Optional[str]) -> str:
    bits = [f"account {user_id} {email}", f"plan {plan}"]
    bits.append(f"organization {org}" if org else "no organization")
    bits.append(f"Stripe {billing}" if billing else "no Stripe subscription")
    return f"{label} " + " · ".join(bits)


async def set_plan(session, email: str, plan: str, reason: str, out=print) -> bool:
    """Set the plan of the account with ``email``; returns whether it changed.

    The caller commits. Raises ``Refused`` for a request it won't carry out."""
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
    email_lower = (email or "").strip().lower()
    user = (await session.execute(
        select(User).where(User.email_lower == email_lower).with_for_update()
    )).scalars().first()
    if user is None:
        raise Refused("No account with that email.")
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
                changed = await set_plan(session, args.email, args.plan, args.reason)
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
