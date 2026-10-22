"""The org a request's role gate checked, held for the rest of that request.

A role gate (``rbac.require_org_role``, ``rbac.require_org_writer`` and its twin
``require_org_checker``) reads the caller's ACTIVE org and their role in it.
The route then works out the org again (``org_context.resolve_org``,
``caller_org_subquery``, ``auth.models.lookup_org_membership``). Between the two
reads the same person's own ``POST /api/v1/orgs/switch`` can move the active
org, so the gate passed on one org (their personal org, where they are admin)
and the write landed in another (one they only view).

The gate binds ``(user_id, org_id)`` here once it has passed; for the rest of
the request every org resolver answers that org for the same user, whatever
``users.current_org_id`` says by then. The resolvers still check that the
membership is live, so a member removed mid-request resolves to no org, never
to a different one.

The binding is a ``ContextVar`` set by the gate dependency and reset in its
teardown (the gates are ``yield`` dependencies), so it never outlives the
request: a later request on the same worker, even one awaited in the same task
(an in-process ASGI client), starts unbound. arq jobs never run a gate, so a job
is never bound; a job carries its org on its row.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

_GATE_ORG: ContextVar[Optional[tuple[int, str]]] = ContextVar(
    "cadverify_gate_org", default=None
)


def gate_org(user_id: object) -> Optional[str]:
    """The org the request's gate checked for ``user_id``, else None (unbound)."""
    bound = _GATE_ORG.get()
    if bound is None:
        return None
    try:
        uid = int(user_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return bound[1] if bound[0] == uid else None


def bind_gate_org(user_id: int, org_id: Optional[str]) -> Optional[Token]:
    """Bind the org a gate just checked; returns the token to release it with."""
    if org_id is None:
        return None
    return _GATE_ORG.set((int(user_id), str(org_id)))


def release_gate_org(token: Optional[Token]) -> None:
    """Undo :func:`bind_gate_org` (the gate's teardown)."""
    if token is None:
        return
    try:
        _GATE_ORG.reset(token)
    except (ValueError, RuntimeError):
        # Reset from another context, or twice: never leave a binding behind.
        _GATE_ORG.set(None)
