"""Per-user ceilings on ScaleCAD's tools for free accounts.

ScaleCAD's own fixes, mesh repair, Fit in context and Design Studio are on
every plan, the free trial included (product owner decision, 2026-10-21).
None of them uses a part check: a check means a part, and these work on a
part already checked (fixes, repair), measure a pair (fit) or generate one
(Studio, whose result is checked like any upload when the user checks it).

Every other protection stays on the routes: authentication and roles, org
scoping, the kill switch, admission control, the route's own per-user limit
(src.auth.rate_limit, counted per URL) and the tool's size and time limits.
A free (trial) account also gets the ceiling below, counted per user across
all its parts, because each of these runs real CAD work. Pro and pilot
accounts keep only the route limits.

Ceilings (env-tunable, slowapi syntax, e.g. "10/hour;40/day"):
  fix     FREE_FIX_LIMIT     10/hour;40/day  isolated CAD worker + re-check + prices
  repair  FREE_REPAIR_LIMIT  10/hour;40/day  two analyses around a mesh repair
  fit     FREE_FIT_LIMIT     10/hour;40/day  two meshes parsed, seated and measured
  design  FREE_DESIGN_LIMIT  20/hour;60/day  one OpenCASCADE generation per design or revision
  catalog FREE_CATALOG_LIMIT 6/hour;20/day   one free catalog run started (src.auth.catalog_allowance)
  recheck FREE_RECHECK_LIMIT 30/hour;150/day one re-check of a part already checked
  fit_preview FREE_FIT_PREVIEW_LIMIT 20/hour;80/day  one 3D preview in Fit in assembly (two per pair)

The counters share the rate limiter's storage (Redis in released processes)
and are off whenever the rate limiter is (RATE_LIMIT_DISABLED in dev/test).
"""
from __future__ import annotations

import logging
import math
import os
import time

from fastapi import Depends, HTTPException, Request
from limits import RateLimitItem, parse_many

from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key

logger = logging.getLogger("cadverify.free_tool_limits")

# tool -> (env var, default, what one use is called in a sentence)
TOOLS: dict[str, tuple[str, str, str, str]] = {
    "fix": ("FREE_FIX_LIMIT", "10/hour;40/day", "fix", "fixes"),
    "repair": ("FREE_REPAIR_LIMIT", "10/hour;40/day", "mesh repair", "mesh repairs"),
    "fit": ("FREE_FIT_LIMIT", "10/hour;40/day", "fit measurement", "fit measurements"),
    "design": ("FREE_DESIGN_LIMIT", "20/hour;60/day", "design or revision", "designs or revisions"),
    "catalog": ("FREE_CATALOG_LIMIT", "6/hour;20/day", "catalog run", "catalog runs"),
    "recheck": ("FREE_RECHECK_LIMIT", "30/hour;150/day", "re-check", "re-checks"),
    "fit_preview": ("FREE_FIT_PREVIEW_LIMIT", "20/hour;80/day", "Fit in assembly preview", "Fit in assembly previews"),
}

_WINDOW_WORDS = {"second": "a second", "minute": "a minute", "hour": "an hour", "day": "a day", "month": "a month", "year": "a year"}


def tool_limits(tool: str) -> list[RateLimitItem]:
    env, default, _one, _many = TOOLS[tool]
    raw = os.getenv(env, "").strip() or default
    try:
        return list(parse_many(raw))
    except ValueError:
        logger.warning("%s=%r is not a rate limit; using %s", env, raw, default)
        return list(parse_many(default))


def _per(item: RateLimitItem) -> str:
    name = item.GRANULARITY.name
    if item.multiples == 1:
        return _WINDOW_WORDS.get(name, f"a {name}")
    return f"every {item.multiples} {name}s"


def _wait(seconds: int) -> str:
    if seconds < 90:
        return "in a minute"
    minutes = math.ceil(seconds / 60)
    if minutes < 58:
        return f"in {minutes} minutes"
    if minutes <= 62:
        return "in an hour"
    hours = math.ceil(minutes / 60)
    return f"in {hours} hours"


def describe(tool: str) -> str:
    """'10 fixes an hour and 40 a day' for this tool's current ceilings."""
    _env, _default, one, many = TOOLS[tool]
    parts = []
    for n, item in enumerate(tool_limits(tool)):
        noun = (one if item.amount == 1 else many) if n == 0 else ""
        parts.append(f"{item.amount}{' ' + noun if noun else ''} {_per(item)}")
    return " and ".join(parts)


def _refusal(tool: str, retry_after: int) -> HTTPException:
    message = f"Free accounts can run {describe(tool)}. You can run the next one {_wait(retry_after)}."
    return HTTPException(
        status_code=429,
        detail={
            "code": "free_tool_limit",
            "message": message,
            "tool": tool,
            "limits": describe(tool),
            "retry_after_s": retry_after,
            "plan": "trial",
        },
        headers={"Retry-After": str(retry_after)},
    )


async def _enforce(tool: str, user: AuthedUser) -> None:
    if not limiter.enabled:
        return
    from src.auth.validation_caps import effective_plan

    if await effective_plan(user.user_id) != "trial":
        return
    backend = limiter.limiter
    ids = ("free-tool", tool, f"user:{user.user_id}")
    for item in tool_limits(tool):
        if not backend.hit(item, *ids):
            reset, _remaining = backend.get_window_stats(item, *ids)
            raise _refusal(tool, max(1, int(math.ceil(reset - time.time()))))


async def limit_free_fixes(user: AuthedUser = Depends(require_api_key)) -> None:
    await _enforce("fix", user)


async def limit_free_repair(user: AuthedUser = Depends(require_api_key)) -> None:
    await _enforce("repair", user)


async def limit_free_fit(user: AuthedUser = Depends(require_api_key)) -> None:
    await _enforce("fit", user)


async def limit_free_designs(user: AuthedUser = Depends(require_api_key)) -> None:
    await _enforce("design", user)


async def limit_free_catalog_runs(user: AuthedUser = Depends(require_api_key)) -> None:
    await _enforce("catalog", user)


async def limit_free_recheck(user: AuthedUser = Depends(require_api_key)) -> None:
    await _enforce("recheck", user)


async def limit_free_fit_previews(request: Request, user: AuthedUser = Depends(require_api_key)) -> None:
    """Fit in assembly's 3D previews (preview-mesh ?purpose=fit) reserve no check; this bounds them."""
    if request.query_params.get("purpose") == "fit":
        await _enforce("fit_preview", user)


ALL = (limit_free_fixes, limit_free_repair, limit_free_fit, limit_free_designs, limit_free_catalog_runs, limit_free_recheck,
       limit_free_fit_previews)
