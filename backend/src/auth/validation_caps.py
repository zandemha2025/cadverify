"""Ten lifetime part checks, reserved durably before any CAD computation.

A check groups the viewer, geometry analysis and costing of one upload. Each
operation can succeed once. The browser supplies a UUID, never an entitlement;
the server binds it to the authenticated account and actual file bytes.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import UploadFile

from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_session_factory
from src.db.models import TrialCheck, User

FREE_CHECKS = 10
# A preview can reserve a slot while the user proceeds to analysis. Stale,
# unfinished uploads release their slots; completed checks never reset.
CHECK_LIFETIME = timedelta(hours=1)


def _problem(status: int, code: str, message: str, **details) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **details})


def _unavailable() -> HTTPException:
    return _problem(503, "allowance_unavailable", "We couldn't confirm your check allowance. Please try again shortly.")


def _exhausted(used: int, reserved: int) -> HTTPException:
    return _problem(
        403, "user_validation_cap_exceeded",
        "Your 10 free lifetime checks are used or in progress. Request paid access to continue. Saved results remain available.",
        used=used, reserved=reserved, cap=FREE_CHECKS, remaining=0, window_days=0, plan="trial",
    )


async def _counts(session, user_id: int, now: datetime) -> tuple[int, int]:
    rows = (await session.execute(
        select(TrialCheck.completed, func.count()).where(
            TrialCheck.user_id == user_id,
            or_(TrialCheck.completed.is_(True), and_(
                or_(
                    TrialCheck.created_at > now - CHECK_LIFETIME,
                    func.jsonb_path_exists(TrialCheck.operations, cast('$.* ? (@ == "running")', JSONPATH)),
                ),
                TrialCheck.operations != {},
            )),
        ).group_by(TrialCheck.completed)
    )).all()
    totals = dict(rows)
    return int(totals.get(True, 0)), int(totals.get(False, 0))


async def user_trial_usage(user_id: int) -> dict:
    try:
        async with get_session_factory()() as session:
            plan = (await session.execute(select(User.plan).where(User.id == user_id))).scalar_one()
            if plan == "pilot":
                return {"plan": plan, "unlimited": True, "used": None, "cap": None, "remaining": None}
            used, reserved = await _counts(session, user_id, datetime.now(timezone.utc))
            return {"plan": plan, "unlimited": False, "used": used, "reserved": reserved,
                    "cap": FREE_CHECKS, "remaining": max(0, FREE_CHECKS - used - reserved), "window_days": 0}
    except SQLAlchemyError as exc:
        raise _unavailable() from exc


async def require_paid_access(user: AuthedUser = Depends(require_api_key)) -> None:
    """Manual operator approval, using the existing pilot entitlement."""
    try:
        async with get_session_factory()() as session:
            plan = (await session.execute(select(User.plan).where(User.id == user.user_id))).scalar_one()
    except SQLAlchemyError as exc:
        raise _unavailable() from exc
    if plan != "pilot":
        raise paid_access_required()


def paid_access_required() -> HTTPException:
    return _problem(403, "paid_access_required",
                    "This tool requires approved paid access. Your free allowance includes 10 single-part CAD checks. Request paid access to use advanced tools.")


async def reserve_check(user_id: int, check_id: str, file_hash: str, operation: str) -> bool:
    """Short account row lock makes admission atomic across API processes.

    PostgreSQL NO KEY UPDATE serializes allowances without blocking result
    foreign keys. No connection/lock stays held during CAD work. A crashed process leaves a
    bounded reservation, never an uncounted concurrent computation.
    """
    now = datetime.now(timezone.utc)
    try:
        async with get_session_factory()() as session, session.begin():
            plan = (await session.execute(
                select(User.plan).where(User.id == user_id).with_for_update(key_share=True)
            )).scalar_one()
            if plan == "pilot":
                return False
            row = await session.get(TrialCheck, (user_id, check_id))
            if row is not None:
                # Repair is its own one-credit operation, never a free add-on to
                # an already completed check or a bundle for different bytes.
                if ((operation == "repair" and (row.completed or row.operations))
                        or (operation != "repair" and "repair" in row.operations)):
                    raise _problem(409, "repair_check_separate", "Start a separate repair check. Repair includes its own verification.")
                if row.file_hash != file_hash:
                    raise _problem(409, "check_file_mismatch", "Start a new check for a different CAD file.")
                if row.created_at <= now - CHECK_LIFETIME:
                    raise _problem(409, "check_expired", "This check has expired. Start a new check or open your saved results.")
                if operation in row.operations:
                    raise _problem(409, "check_operation_exists", "This step is already running or complete. Open your saved results or start a new check.")
            # A failed request can retry its empty reservation, but must compete
            # for a slot again (another request may have used the released slot).
            if row is None or (not row.completed and not row.operations):
                used, reserved = await _counts(session, user_id, now)
                if used + reserved >= FREE_CHECKS:
                    raise _exhausted(used, reserved)
            if row is None:
                row = TrialCheck(user_id=user_id, check_id=check_id, file_hash=file_hash,
                                 created_at=now, completed=False, operations={})
                session.add(row)
            row.operations = {**row.operations, operation: "running"}
            return True
    except SQLAlchemyError as exc:
        raise _unavailable() from exc


async def finish_check(user_id: int, check_id: str, operation: str, success: bool) -> None:
    try:
        async with get_session_factory()() as session, session.begin():
            # Same lock order as admission, including concurrent viewer requests.
            await session.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
            row = await session.get(TrialCheck, (user_id, check_id))
            if row is None:
                raise _unavailable()
            operations = dict(row.operations)
            if success:
                operations[operation] = "complete"
                if operation not in {"preview", "preview-analysis", "assembly-json", "assembly-glb"}:
                    row.completed = True
            else:
                operations.pop(operation, None)
            row.operations = operations
    except SQLAlchemyError as exc:
        raise _unavailable() from exc


async def enforce_validation_caps(request: Request, user: AuthedUser = Depends(require_api_key)) -> None:
    # Reuse the route's bounded upload policy without buffering another copy.
    from src.api.routes import _max_upload_bytes

    path = request.url.path
    if (path.endswith(("/fit", "/repair"))
            or (path.endswith("/assembly") and request.query_params.get("format", "json").lower() != "json")
            or request.query_params.get("segmentation") == "sam3d"):
        await require_paid_access(user)
        return
    raw_id = request.headers.get("x-part-check-id")
    try:
        check_id = str(UUID(raw_id)) if raw_id else str(uuid4())
    except (ValueError, AttributeError):
        raise _problem(400, "invalid_check_id", "The part check identifier must be a UUID.")
    file = (await request.form()).get("file")
    if not isinstance(file, UploadFile):
        raise _problem(400, "check_file_required", "Upload a CAD file to start a check.")
    # Bind exactly the file FastAPI passes to the handler. Ignored extra form
    # fields must not change the identity, or make ambiguous multipart hashes.
    filename = (file.filename or "").encode()
    digest = hashlib.sha256(len(filename).to_bytes(8, "big") + filename)
    size = 0
    try:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > _max_upload_bytes():
                raise _problem(413, "file_too_large", "The CAD file exceeds the upload size limit.")
            digest.update(chunk)
    finally:
        await file.seek(0)
    if not size:
        raise _problem(400, "empty_file", "Empty file uploaded.")
    if path.endswith('/preview-mesh'):
        purpose = request.query_params.get('purpose')
        operation = 'repair-source' if purpose == 'repair' else 'preview-analysis' if purpose == 'analysis' else 'preview'
    elif path.endswith('/repair/verify'):
        operation = 'repair'
    elif path.endswith('/assembly'):
        fmt = request.query_params.get('format', 'json').lower()
        if fmt not in {'json', 'glb', 'analysis'}:
            raise _problem(400, "invalid_assembly_format", "Choose json, glb, or analysis.")
        operation = 'assembly-' + fmt
    elif '/cost' in path:
        operation = 'cost'
    elif path.endswith(('/validate', '/quick', '/demo')):
        operation = 'analysis'
    else:
        operation = path.rsplit('/', 1)[-1]
    if await reserve_check(user.user_id, check_id, digest.hexdigest(), operation):
        request.state.trial_check = (user.user_id, check_id, operation)


class MeteredRoute(APIRoute):
    """Settle at the ASGI response boundary, after function dependencies commit.

    get_route_handler() returns BEFORE FastAPI closes its transaction stack.
    Settling there deadlocks on the result's user FK and can charge a failed
    commit. http.response.start runs after that stack has finished.
    """
    async def handle(self, scope, receive, send):
        response_ready = False
        accounting_failed = False

        async def send_metered(message):
            nonlocal response_ready, accounting_failed
            if accounting_failed:
                return
            if message["type"] == "http.response.start":
                response_ready = True
                receipt = scope.get("state", {}).get("trial_check")
                if receipt:
                    try:
                        success = message["status"] < 400
                        if receipt[2] == "repair":
                            success = success and scope.get("state", {}).get("repair_verified") is True
                        elif receipt[2] == "repair-source":
                            # Format conversion prepares local repair; only a
                            # subsequently verified candidate spends a check.
                            success = False
                        await finish_check(*receipt, success=success)
                    except HTTPException as exc:
                        # Keep the reservation on uncertainty. Never report
                        # success or refund completed work after a DB outage.
                        accounting_failed = True
                        await JSONResponse(status_code=503, content={"detail": exc.detail})(scope, receive, send)
                        return
            await send(message)

        try:
            await super().handle(scope, receive, send_metered)
        except Exception:
            receipt = scope.get("state", {}).get("trial_check")
            if receipt and not response_ready:
                await finish_check(*receipt, success=False)
            raise
