"""Deleting a person's sign-in account: what goes, what stays, and the receipt.

Product decision (2026-10-22): a person can delete their own account from
Account > Security, by typing its email. It is refused while they are the only
admin of an organization other people are in (they make someone else an admin
there, or delete the organization, first). Otherwise, in one transaction:

* each organization only they are in is deleted through the organization
  deletion path (``data_deletion_service.remove_org_rows``): every part, file,
  record and setting, its audit rows redacted, its usage counts kept without
  file hashes;
* they leave every other organization: memberships removed, their API keys
  revoked, invitations addressed to them removed. What they made there (parts,
  checks, records) belongs to that organization and stays, attributed to the
  deleted account;
* sign-in ends everywhere: the account is deactivated and its session version
  bumped (every cookie and key refused), its SSO and SCIM bindings removed;
* the person is redacted from the audit trail: rows they made lose their email,
  network address and browser; their email is replaced wherever a row names it;
* the free-check and catalog ledgers are deleted after their counts are kept
  in ``deleted_account_allowances`` under a one-way fingerprint of the email
  (``deleted_account_allowance``), so signing up again doesn't reissue them;
* a live Pro subscription is cancelled at Stripe first, at once (nothing more is
  charged; the rest of the period isn't refunded). If Stripe can't be reached,
  nothing is deleted;
* the account row stays as an anonymous, deactivated tombstone: its id holds
  the Stripe customer reference (``billing_accounts``) that billing law needs,
  and the organizations' records point at it. Email, name, phone, password,
  Google subject, sign-up details and settings are cleared; the email becomes
  ``deleted-account-<id>@deleted.invalid``, so the address can sign up again as
  a new account;
* ScaleCAD's own customer list (the Notion CRM page) is moved to Notion's
  trash, and the deleted organizations' stored files are removed, after the
  commit, by the same resumable steps as an organization deletion.

A ``data_deletions`` receipt (scope ``account``, target the account id) and an
``account.deleted`` audit row record that it happened, when, and the counts.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException
from sqlalchemy import Text, and_, case, cast, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import (
    ApiKey,
    AuditLog,
    AuthIdentity,
    BillingAccount,
    CatalogPart,
    DataDeletion,
    Membership,
    NotificationRead,
    OrgInvite,
    Organization,
    ScimIdentity,
    TrialCheck,
    UsageEvent,
    User,
)
from src.services import data_deletion_service as dd

logger = logging.getLogger("cadverify.account_deletion")

# The actor shown on audit rows the deleted person made (the column is NOT NULL).
ACCOUNT_DELETED_EMAIL = "deleted account"
ACCOUNT = dd.ACCOUNT

DELETE = "delete"
LEAVE = "leave"
BLOCKED = "blocked"


def tombstone_email(user_id: int) -> str:
    return f"deleted-account-{int(user_id)}@deleted.invalid"


@dataclass
class OrgPlan:
    org_id: str
    name: str
    role: str
    members: int
    other_admins: int

    @property
    def action(self) -> str:
        if self.members <= 1:
            return DELETE
        if self.role == "admin" and self.other_admins == 0:
            return BLOCKED
        return LEAVE


async def _plan(session: AsyncSession, user_id: int) -> list[OrgPlan]:
    """Each organization the person is in, and what deleting the account does to it."""
    mine = (
        await session.execute(
            select(Membership.org_id, Membership.org_role, Organization.name)
            .join(Organization, Organization.id == Membership.org_id)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at.asc(), Membership.id.asc())
        )
    ).all()
    plans = []
    for org_id, role, name in mine:
        members, admins = (
            await session.execute(
                select(
                    func.count(),
                    func.count().filter(and_(Membership.org_role == "admin", Membership.user_id != user_id)),
                ).where(Membership.org_id == org_id)
            )
        ).one()
        plans.append(OrgPlan(org_id=org_id, name=name or "", role=role or "member",
                             members=int(members), other_admins=int(admins)))
    return plans


def _blocker(p: OrgPlan) -> dict[str, Any]:
    return {
        "org_id": p.org_id,
        "name": p.name,
        "members": p.members,
        "message": (
            f"You're the only admin of {p.name}, and {p.members - 1} other "
            f"{'person is' if p.members == 2 else 'people are'} in it. In Account > Organization, make "
            "another member an admin, or delete the organization, then delete your account."
        ),
    }


async def _billing(session: AsyncSession, user_id: int, *, lock: bool = False) -> Optional[BillingAccount]:
    stmt = select(BillingAccount).where(BillingAccount.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


def _live_subscription(account: Optional[BillingAccount]) -> bool:
    from src.auth.validation_caps import PRO_ACTIVE_STATUSES

    return bool(account and account.stripe_subscription_id and account.status in PRO_ACTIVE_STATUSES)


def _billing_view(plan: str, account: Optional[BillingAccount]) -> dict[str, Any]:
    live = _live_subscription(account)
    return {
        "plan": plan,
        "subscription_status": account.status if account else None,
        "period_end": account.current_period_end.isoformat() if account and account.current_period_end else None,
        "cancels_now": live,
    }


async def _active_keys(session: AsyncSession, user_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(ApiKey).where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
            )
        ).scalar_one()
    )


async def _user(session: AsyncSession, user_id: int, *, lock: bool = False) -> User:
    stmt = select(User).where(User.id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="Account not found")
    return user


async def account_deletion_preview(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """What deleting the account would do, for the confirmation."""
    user = await _user(session, user_id)
    plans = await _plan(session, user_id)
    deleted = []
    for p in plans:
        if p.action == DELETE:
            deleted.append({"org_id": p.org_id, "name": p.name, "will_remove": await dd._org_counts(session, p.org_id)})
    blockers = [_blocker(p) for p in plans if p.action == BLOCKED]
    return {
        "email": user.email,
        "can_delete": not blockers,
        "blockers": blockers,
        "orgs_deleted": deleted,
        "orgs_left": [
            {"org_id": p.org_id, "name": p.name, "role": p.role, "members": p.members}
            for p in plans if p.action == LEAVE
        ],
        "api_keys": await _active_keys(session, user_id),
        "billing": _billing_view(user.plan, await _billing(session, user_id)),
        "kept": dd.KEPT_AFTER_ACCOUNT_DELETE,
    }


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------


def _stripe_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "billing_cancel_failed",
            "message": "ScaleCAD couldn't cancel your Pro plan with Stripe, so nothing was deleted. Retry in a few minutes.",
        },
    )


async def cancel_subscription_at_stripe(subscription_id: str, idempotency_key: str) -> None:
    """Cancel now (no proration, no refund). Already gone counts as cancelled."""
    from src.billing.stripe_client import StripeError, billing_enabled, stripe_request

    if not billing_enabled():
        raise _stripe_unavailable()
    try:
        await stripe_request("DELETE", f"/v1/subscriptions/{subscription_id}", idempotency_key=idempotency_key)
    except StripeError as exc:
        if exc.status == 404:
            return
        logger.warning("account deletion: Stripe cancel failed (%s)", exc.status)
        raise _stripe_unavailable() from exc


CancelSubscription = Callable[[str, str], Awaitable[None]]


# ---------------------------------------------------------------------------
# Audit redaction
# ---------------------------------------------------------------------------


def _are_escape(value: str) -> str:
    """Escape for a Postgres ARE: a backslash before any non-alphanumeric is a literal."""
    return re.sub(r"([^0-9A-Za-z])", r"\\\1", value)


def _email_pattern(emails: set[str]) -> str:
    """The emails as whole addresses (not inside a longer one), case-insensitive."""
    alts = "|".join(sorted({_are_escape(e) for e in emails if e}))
    return f"(^|[^A-Za-z0-9._%+-])({alts})(?=[^A-Za-z0-9.-]|$)"


async def _redact_person(session: AsyncSession, user_id: int, emails: set[str], org_ids: list[str]) -> int:
    """Audit rows lose the person: their email, network address and browser."""
    made = await session.execute(
        update(AuditLog).where(AuditLog.user_id == user_id)
        .values(user_email=ACCOUNT_DELETED_EMAIL, ip_address=None, user_agent=None)
        .execution_options(synchronize_session=False)
    )
    pattern = _email_pattern(emails)
    # Rows that can name them: their own, their organizations' (invites, role
    # changes), and pilot requests sent from the public form with their email.
    scope = [AuditLog.user_id == user_id, AuditLog.action == "pilot.requested"]
    if org_ids:
        scope.append(AuditLog.org_id.in_(org_ids))
    detail_text = cast(AuditLog.detail_json, Text)
    named = await session.execute(
        update(AuditLog)
        .where(
            or_(*scope),
            or_(detail_text.op("~*")(pattern), AuditLog.user_email.op("~*")(pattern),
                AuditLog.result_summary.op("~*")(pattern)),
        )
        .values(
            detail_json=case(
                (AuditLog.detail_json.is_(None), None),
                else_=cast(func.regexp_replace(detail_text, pattern, r"\1redacted", "gi"), JSONB),
            ),
            user_email=case(
                (AuditLog.user_email.op("~*")(pattern), ACCOUNT_DELETED_EMAIL), else_=AuditLog.user_email
            ),
            ip_address=case((AuditLog.user_email.op("~*")(pattern), None), else_=AuditLog.ip_address),
            user_agent=case((AuditLog.user_email.op("~*")(pattern), None), else_=AuditLog.user_agent),
            result_summary=func.regexp_replace(AuditLog.result_summary, pattern, r"\1redacted", "gi"),
        )
        .execution_options(synchronize_session=False)
    )
    return int(made.rowcount or 0) + int(named.rowcount or 0)


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------


def _emails_match(typed: str, email: str) -> bool:
    return bool((typed or "").strip()) and (typed or "").strip().lower() == (email or "").strip().lower()


def _merge_steps(groups: list[list[dict]]) -> list[dict]:
    """The deleted organizations' storage steps, each kind of orphan sweep once, at the end."""
    out: list[dict] = []
    orphans: list[dict] = []
    for steps in groups:
        for step in steps:
            if step.get("kind") == "orphans":
                if step not in orphans:
                    orphans.append(step)
            elif step not in out:
                out.append(step)
    return out + orphans


async def delete_account(
    session: AsyncSession,
    *,
    user_id: int,
    confirm_email: str,
    cancel_subscription: Optional[CancelSubscription] = None,
) -> DataDeletion:
    """Delete the person's account (see the module docstring). Commits; returns the receipt."""
    user = await _user(session, user_id, lock=True)
    if not _emails_match(confirm_email, user.email):
        raise HTTPException(
            status_code=400,
            detail={"code": "confirm_email_mismatch", "message": "Type your account's email exactly to delete it."},
        )
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"account-delete:{user_id}"})
    # Lock every organization the person is in (in id order), then decide: no one
    # can join an organization that is about to be deleted with it, or leave one
    # the person is about to leave without an admin.
    org_ids = sorted({p.org_id for p in await _plan(session, user_id)})
    if org_ids:
        await session.execute(
            select(Organization.id).where(Organization.id.in_(org_ids)).order_by(Organization.id).with_for_update()
        )
    plans = await _plan(session, user_id)
    blockers = [_blocker(p) for p in plans if p.action == BLOCKED]
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={"code": "account_delete_blocked", "message": blockers[0]["message"], "blockers": blockers},
        )

    deletion_ulid = str(ULID())
    email, email_lower = user.email, user.email_lower
    emails = {e for e in (email, email_lower, (email or "").lower()) if e}

    # Billing first: if Stripe can't cancel the plan, nothing is deleted.
    billing = await _billing(session, user_id, lock=True)
    plan_cancelled = False
    if _live_subscription(billing):
        cancel = cancel_subscription or cancel_subscription_at_stripe
        await cancel(billing.stripe_subscription_id, f"account-delete-{deletion_ulid}")
        billing.status = "canceled"
        billing.updated_at = dd.now_utc()
        plan_cancelled = True

    # The free allowance this email used outlives the account, as a fingerprint.
    from src.services import deleted_account_allowance as allowance

    await allowance.carry_over(session, user_id, email_lower)
    checks_used, parts_used = await allowance.used_counts(session, user_id)
    await allowance.remember(session, email_lower, checks_used, parts_used)

    # Organizations only the person is in go, through the organization deletion path.
    deleting = [p for p in plans if p.action == DELETE]
    leaving = [p for p in plans if p.action == LEAVE]
    invited_orgs = (
        await session.execute(
            select(OrgInvite.org_id).where(
                or_(func.lower(OrgInvite.email).in_(sorted({e.lower() for e in emails})),
                    OrgInvite.invited_user_id == user_id, OrgInvite.accepted_by == user_id)
            ).distinct()
        )
    ).scalars().all()
    step_groups: list[list[dict]] = []
    org_totals: dict[str, int] = {}
    for p in deleting:
        removal = await dd.remove_org_rows(
            session, org_id=p.org_id, user_id=user_id, deletion_ulid=deletion_ulid, actor_email=ACCOUNT_DELETED_EMAIL
        )
        step_groups.append(removal.steps)
        for key, value in removal.counts.items():
            org_totals[key] = org_totals.get(key, 0) + int(value or 0)

    async def run(stmt) -> int:
        return int((await session.execute(stmt.execution_options(synchronize_session=False))).rowcount or 0)

    removed: dict[str, Any] = {
        "organizations_deleted": len(deleting),
        "organizations_left": len(leaving),
        "memberships_removed": await run(delete(Membership).where(Membership.user_id == user_id)),
        "api_keys_revoked": await run(
            update(ApiKey).where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None)).values(revoked_at=func.now())
        ),
        "invitations_removed": await run(
            delete(OrgInvite).where(
                or_(func.lower(OrgInvite.email).in_(sorted({e.lower() for e in emails})),
                    OrgInvite.invited_user_id == user_id, OrgInvite.accepted_by == user_id)
            )
        ),
        "sign_in_links_removed": await run(delete(AuthIdentity).where(AuthIdentity.user_id == user_id))
        + await run(delete(ScimIdentity).where(ScimIdentity.user_id == user_id)),
        "notification_reads_removed": await run(delete(NotificationRead).where(NotificationRead.user_id == user_id)),
        "free_check_records_removed": await run(delete(TrialCheck).where(TrialCheck.user_id == user_id))
        + await run(delete(CatalogPart).where(CatalogPart.user_id == user_id)),
        "usage_events_unhashed": await run(
            update(UsageEvent).where(UsageEvent.user_id == user_id, UsageEvent.mesh_hash.is_not(None))
            .values(mesh_hash=None)
        ),
        "plan_cancelled": plan_cancelled,
        "free_checks_used": checks_used,
        "free_catalog_parts_used": parts_used,
    }
    if deleting:
        removed["deleted_organizations"] = {
            k: org_totals.get(k, 0) for k in ("parts", "checks", "cost_records", "batches", "designs", "actual_costs")
        }
    removed["audit_events_redacted"] = await _redact_person(
        session, user_id, emails, sorted({*(p.org_id for p in leaving), *invited_orgs})
    )

    # ScaleCAD's customer list entry goes too (after the commit; retried).
    steps = _merge_steps(step_groups)
    steps.append({"kind": "crm_archive", "user_id": int(user_id), "page_id": user.notion_page_id})

    await session.execute(
        update(User).where(User.id == user_id).values(
            email=tombstone_email(user_id),
            email_lower=tombstone_email(user_id),
            google_sub=None,
            password_hash=None,
            full_name=None,
            phone=None,
            signup_metadata={},
            preferences={},
            verified_phone=None,
            phone_verified_at=None,
            notion_page_id=None,
            last_seen_at=None,
            free_check_grant=None,
            current_org_id=None,
            role="viewer",
            is_active=False,
            deactivated_at=func.now(),
            session_version=User.session_version + 1,
            crm_sync_after=text("'infinity'::timestamptz"),
        ).execution_options(synchronize_session=False)
    )
    session.add(
        AuditLog(
            user_id=user_id,
            org_id=None,
            user_email=ACCOUNT_DELETED_EMAIL,
            action="account.deleted",
            resource_type="user",
            resource_id=str(user_id),
            detail_json={"deletion_id": deletion_ulid, "removed": removed},
        )
    )
    receipt = DataDeletion(
        ulid=deletion_ulid,
        scope=ACCOUNT,
        org_id=deleting[0].org_id if deleting else "",
        target=str(user_id),
        requested_by=user_id,
        status="removing_files",
        removed_json=removed,
        steps_json=steps,
        steps_total=len(steps),
        steps_done=0,
        final_sweep_due_at=dd.now_utc() + dd.ORG_FINAL_SWEEP_DELAY if deleting else None,
    )
    session.add(receipt)
    await session.commit()
    for p in deleting:
        dd.forget_cached(p.org_id, None)
    logger.info("account %d deleted (%d organizations deleted, %d left)", user_id, len(deleting), len(leaving))
    return receipt
