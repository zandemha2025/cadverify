"""Process-local reuse of one part's analysed geometry for re-pricing.

Pricing depends on the material, quantities, rates and machines; the geometry
analysis it starts from (parse, measure, every process's DFM rules) depends
only on the file. Re-pricing the same file in another material used to re-run
that analysis (about 10 s on a 185k-face IGES). This keeps the analysed part a
caller just produced, so the next price of the SAME bytes, filename and units
by the SAME account skips straight to costing.

Honesty: an entry holds exactly the objects the cost engine would build from
those bytes (same parse, same analysis code, same order), so a reused price is
identical to a fresh one. It is a cache, never a source of truth: a miss (a
different API process, an expired or evicted entry, the cache turned off)
falls back to the full analysis with the same result.

Bounded: entries expire (``COST_GEOMETRY_CACHE_TTL_SEC``, default 1800 s), at
most ``COST_GEOMETRY_CACHE_ENTRIES`` are kept (default 4; 0 turns it off) and
their total face count stays under ``COST_GEOMETRY_CACHE_MAX_FACES`` (default
800,000). An entry is stored without trimesh's lazy caches (about 35 MB for a
185k-face part); only the part priced most recently keeps the ones pricing
fills (about 80 MB more for that part), so flipping materials on one part is
fastest while the rest stay small. Scoped to the account, so one tenant's
upload never answers another's request, even by timing.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_ENTRIES = 4
DEFAULT_TTL_SEC = 1800.0
DEFAULT_MAX_FACES = 800_000


def _env_number(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def max_entries() -> int:
    return max(0, int(_env_number("COST_GEOMETRY_CACHE_ENTRIES", DEFAULT_ENTRIES)))


def ttl_sec() -> float:
    return max(0.0, _env_number("COST_GEOMETRY_CACHE_TTL_SEC", DEFAULT_TTL_SEC))


def max_faces() -> int:
    return max(0, int(_env_number("COST_GEOMETRY_CACHE_MAX_FACES", DEFAULT_MAX_FACES)))


@dataclass
class AnalysedPart:
    """What the cost engine builds from a file before it prices anything.

    ``result``/``mesh``/``features`` are ``_run_cost_engine_ctx``'s output;
    ``identity_vec`` is the shape signature it derives from them. Use them only
    while holding ``lock``: the engine reads them, and trimesh fills lazy caches
    on first read.
    """

    result: Any
    mesh: Any
    features: Any
    identity_vec: Any
    suffix: str
    faces: int
    lock: threading.Lock = field(default_factory=threading.Lock)
    expires_at: float = 0.0


_lock = threading.Lock()
_entries: "OrderedDict[tuple, AnalysedPart]" = OrderedDict()
_hot: Optional[tuple] = None  # the entry allowed to keep its lazy caches


def _cool(entry: AnalysedPart) -> None:
    """Drop an entry's lazy trimesh caches (the next price fills them again).
    Skipped while a request is pricing with it."""
    if entry.lock.acquire(blocking=False):
        try:
            entry.mesh._cache.clear()
        except Exception:  # noqa: BLE001 - a cache that can't clear just stays
            pass
        finally:
            entry.lock.release()


def _make_hot(k: tuple) -> None:
    """Call with ``_lock`` held: ``k`` becomes the one entry with warm caches."""
    global _hot
    if _hot is not None and _hot != k:
        prev = _entries.get(_hot)
        if prev is not None:
            _cool(prev)
    _hot = k


def key(user_id: int, data: bytes, filename: str, units: str, *, orientation: str | None = None) -> tuple:
    """The identity a reused analysis must match: account, bytes, name, units,
    and the orientation the part was turned to (``Orientation.key``; None for
    the file's own), since a turned part is analysed as placed."""
    base = (int(user_id), hashlib.sha256(data).hexdigest(), filename or "unknown", units)
    return base if orientation is None else (*base, orientation)


def get(k: tuple) -> Optional[AnalysedPart]:
    now = time.monotonic()
    with _lock:
        entry = _entries.get(k)
        if entry is None:
            return None
        if entry.expires_at <= now:
            del _entries[k]
            return None
        _entries.move_to_end(k)
        _make_hot(k)
        return entry


def put(k: tuple, entry: AnalysedPart) -> bool:
    """Keep ``entry`` (newest last), evicting the oldest past the limits.

    Returns False when the cache is off or the part alone exceeds the face budget.
    """
    limit, budget, ttl = max_entries(), max_faces(), ttl_sec()
    if limit <= 0 or ttl <= 0 or entry.faces > budget:
        return False
    entry.expires_at = time.monotonic() + ttl
    _cool(entry)  # stored small; pricing refills what it reads
    with _lock:
        _entries.pop(k, None)
        _entries[k] = entry
        _make_hot(k)
        total = sum(e.faces for e in _entries.values())
        while _entries and (len(_entries) > limit or total > budget):
            _, old = _entries.popitem(last=False)
            total -= old.faces
    return True


def clear() -> None:
    global _hot
    with _lock:
        _entries.clear()
        _hot = None


def size() -> int:
    with _lock:
        return len(_entries)
