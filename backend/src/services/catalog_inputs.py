"""The few keys of a saved check or priced record that the parts pages read,
cached by record in this process.

Why: the catalog grid, the portfolio and triage fold the org's newest analysis
and cost decision per part and derive each row from their ``result_json``.
Loading the whole column cost about a second per request for an org with 90
priced parts: 45 MB of JSON, nearly all of it each estimate's DFM blocker
details, decoded on the API's one core for every page load (capacity report C6).
The rows read a few dozen keys of it.

Both columns are immutable once written: ``persist_cost_decision`` keeps
historical rows as they were and an analysis is never rewritten; nothing
updates either column. So the folds list their rows without ``result_json``,
then ask here for the slim inputs of the rows they keep. Each record is read in
full and slimmed once per process (a miss), then served from memory.
``is_current`` caches the one other fact the cost fold needs per record,
whether it is a what-if, computed by the same SQL test as
``cost_decision_service.current_price_clause``.

Contract:
  * ``slim_cost`` / ``slim_analysis`` keep exactly the keys
    ``catalog_service``'s derivation reads (``derive_row``, ``make_now_estimate``,
    ``derive_savings``, the quantity-matched annualization) plus the record
    list's ``what_if`` / ``rate_card`` / ``priced_at``, with the same presence,
    absence and values. Anything that isn't a dict or list where one is
    expected is passed through untouched, so a malformed record fails the same
    way it did. ``tests/test_catalog_inputs.py`` holds every derived figure
    identical on full and slim records. A new reader of another key must add
    it here.
  * The cached dicts are shared between requests: readers must not mutate them.
  * Keys are ``(id, ulid)``: a deleted and re-inserted record never reuses both.
    A record's entry is only ever served to a fold whose org-scoped query
    returned that record, so the cache can't cross tenants.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Pure slimming
# ---------------------------------------------------------------------------

_COST_KEYS = ("decision", "quantities", "rate_card", "estimates", "what_if", "priced_at")
_ESTIMATE_KEYS = (
    "process", "material", "quantity", "dfm_ready", "dfm_blockers",
    "confidence", "drivers", "unit_cost_usd", "environment_excluded",
)
_ANALYSIS_KEYS = ("best_process", "universal_issues", "process_scores")
_SCORE_KEYS = ("process", "recommended_material", "issues")
_ISSUE_KEYS = ("code", "message", "severity")

# Driver provenance is all ``posture`` reads, from a small vocabulary
# (MEASURED / SHOP / USER / DEFAULT): one shared dict per value keeps a cached
# record's drivers to a list of references.
_DRIVER_BY_PROVENANCE: dict[Any, dict] = {}
_DRIVER_NO_PROVENANCE: dict = {}


def _pick(d: dict, keys: Iterable[str]) -> dict:
    return {k: d[k] for k in keys if k in d}


def _slim_driver(d: Any) -> Any:
    if not isinstance(d, dict):
        return d
    if "provenance" not in d:
        return _DRIVER_NO_PROVENANCE
    p = d["provenance"]
    if not (p is None or isinstance(p, str)) or len(_DRIVER_BY_PROVENANCE) > 64:
        return {"provenance": p}
    shared = _DRIVER_BY_PROVENANCE.get(p)
    if shared is None:
        shared = _DRIVER_BY_PROVENANCE.setdefault(p, {"provenance": p})
    return shared


def _slim_estimate(e: Any) -> Any:
    if not isinstance(e, dict):
        return e
    out = _pick(e, _ESTIMATE_KEYS)
    if isinstance(out.get("confidence"), dict):
        out["confidence"] = _pick(out["confidence"], ("validated",))
    if isinstance(out.get("drivers"), list):
        out["drivers"] = [_slim_driver(d) for d in out["drivers"]]
    return out


def slim_cost(result_json: Any) -> Any:
    """A cost decision's ``result_json`` reduced to what the parts pages read."""
    if not isinstance(result_json, dict):
        return result_json
    out = _pick(result_json, _COST_KEYS)
    if isinstance(out.get("estimates"), list):
        out["estimates"] = [_slim_estimate(e) for e in out["estimates"]]
    if isinstance(out.get("rate_card"), dict):
        out["rate_card"] = _pick(out["rate_card"], ("version",))
    return out


def _slim_issue(i: Any) -> Any:
    return _pick(i, _ISSUE_KEYS) if isinstance(i, dict) else i


def _slim_score(p: Any) -> Any:
    if not isinstance(p, dict):
        return p
    out = _pick(p, _SCORE_KEYS)
    if isinstance(out.get("issues"), list):
        out["issues"] = [_slim_issue(i) for i in out["issues"]]
    return out


def slim_analysis(result_json: Any) -> Any:
    """An analysis's ``result_json`` reduced to what the parts pages read."""
    if not isinstance(result_json, dict):
        return result_json
    out = _pick(result_json, _ANALYSIS_KEYS)
    if isinstance(out.get("universal_issues"), list):
        out["universal_issues"] = [_slim_issue(i) for i in out["universal_issues"]]
    if isinstance(out.get("process_scores"), list):
        out["process_scores"] = [_slim_score(p) for p in out["process_scores"]]
    return out


# ---------------------------------------------------------------------------
# Bounded per-process caches
# ---------------------------------------------------------------------------


def _budget_bytes() -> int:
    """``CATALOG_INPUT_CACHE_MB`` (default 64): the slim records' size as JSON.
    0 turns the cache off (every read loads its records)."""
    try:
        mb = float(os.getenv("CATALOG_INPUT_CACHE_MB", "64"))
    except ValueError:
        mb = 64.0
    return max(0, int(mb * 1024 * 1024))


class _Cache:
    """Insertion-ordered, size-bounded map; the oldest entries leave first."""

    def __init__(self, max_entries: int = 0):
        self._d: dict[tuple, tuple[Any, int]] = {}
        self._bytes = 0
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def get(self, key: tuple) -> tuple[bool, Any]:
        hit = self._d.get(key)
        return (False, None) if hit is None else (True, hit[0])

    def put(self, key: tuple, value: Any, size: int, budget: int) -> None:
        if budget <= 0 or size > budget:
            return
        with self._lock:
            old = self._d.pop(key, None)
            if old is not None:
                self._bytes -= old[1]
            self._d[key] = (value, size)
            self._bytes += size
            while self._d and (
                self._bytes > budget
                or (self._max_entries and len(self._d) > self._max_entries)
            ):
                oldest = next(iter(self._d))
                self._bytes -= self._d.pop(oldest)[1]

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self._bytes = 0

    def __len__(self) -> int:
        return len(self._d)

    @property
    def bytes(self) -> int:
        return self._bytes


_COST = _Cache()
_ANALYSIS = _Cache()
# (id, ulid) -> is not a what-if. ~150 bytes an entry; bounded by count.
_CURRENT = _Cache(max_entries=200_000)


def reset_for_tests() -> None:
    _COST.clear()
    _ANALYSIS.clear()
    _CURRENT.clear()


def stats() -> dict:
    return {
        "cost_records": len(_COST), "cost_bytes": _COST.bytes,
        "analysis_records": len(_ANALYSIS), "analysis_bytes": _ANALYSIS.bytes,
        "currentness_records": len(_CURRENT),
    }


def _size(value: Any) -> int:
    try:
        return len(json.dumps(value, separators=(",", ":"), default=str))
    except (TypeError, ValueError):
        return 1 << 20


async def _inputs(session: AsyncSession, model, cache: _Cache, slim, keys: list[tuple]) -> dict:
    out: dict = {}
    missing: list[tuple] = []
    for key in keys:
        found, value = cache.get(key)
        if found:
            out[key] = value
        else:
            missing.append(key)
    if missing:
        budget = _budget_bytes()
        ids = [k[0] for k in missing]
        rows = (await session.execute(
            select(model.id, model.ulid, model.result_json).where(model.id.in_(ids))
        )).all()
        wanted = set(missing)
        for row_id, ulid, rj in rows:
            key = (row_id, ulid)
            if key not in wanted:
                continue
            value = slim(rj)
            out[key] = value
            cache.put(key, value, _size(value), budget)
    return out


async def cost_inputs(session: AsyncSession, keys: list[tuple]) -> dict:
    """``{(id, ulid): slim result_json}`` for these cost decisions (a deleted one is absent)."""
    from src.db.models import CostDecision

    return await _inputs(session, CostDecision, _COST, slim_cost, keys)


async def analysis_inputs(session: AsyncSession, keys: list[tuple]) -> dict:
    """``{(id, ulid): slim result_json}`` for these analyses (a deleted one is absent)."""
    from src.db.models import Analysis

    return await _inputs(session, Analysis, _ANALYSIS, slim_analysis, keys)


async def current_flags(session: AsyncSession, keys: list[tuple]) -> dict:
    """``{(id, ulid): True}`` when the cost decision can be a part's price (not a
    what-if), by ``current_price_clause``'s own SQL test; a deleted one is absent."""
    from src.db.models import CostDecision
    from src.services.cost_decision_service import current_price_clause

    out: dict = {}
    missing: list[tuple] = []
    for key in keys:
        found, value = _CURRENT.get(key)
        if found:
            out[key] = value
        else:
            missing.append(key)
    if missing:
        rows = (await session.execute(
            select(CostDecision.id, CostDecision.ulid, current_price_clause())
            .where(CostDecision.id.in_([k[0] for k in missing]))
        )).all()
        wanted = set(missing)
        for row_id, ulid, current in rows:
            key = (row_id, ulid)
            if key in wanted:
                out[key] = bool(current)
                _CURRENT.put(key, bool(current), 1, 1 << 62)
    return out
