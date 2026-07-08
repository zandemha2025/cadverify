"""Bounded, thread-safe, in-process cache for parsed meshes (CORE perf).

Keyed by ``(sha256(raw upload bytes), file suffix)``. Stores the RAW parsed
trimesh — the exact object ``_parse_mesh()`` produces BEFORE any units scaling,
decimation, or analysis.

Correctness invariant (the crux): the cache stores a deep copy it makes itself
and hands out a deep copy (``mesh.copy()``) on every hit. No caller ever shares
an object with the cache, so mutating a returned mesh can never corrupt the
cached copy or any other caller. This makes the cache correctness-transparent:
enabled vs disabled produce byte-identical geometry.

Bounds: capped by BOTH entry count and approximate resident bytes
(vertex + face arrays), evicting least-recently-used first. Never unbounded.

Scope caveat: this is a PER-PROCESS cache. Each uvicorn worker / replica has
its own; there is no cross-worker sharing (that would need the blob store /
redis, out of scope here).
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from typing import Dict, Optional, Tuple

_Key = Tuple[str, str]

# Modest, env-overridable defaults. 16 parts / 256 MiB is generous for the
# validate+cost+preview burst on a single part while staying well bounded.
DEFAULT_MAX_ENTRIES = 16
DEFAULT_MAX_BYTES = 256 * 1024 * 1024  # 256 MiB


def is_disabled() -> bool:
    """Opt-out switch. Defaults to ENABLED; when set, behavior is today's."""
    return os.getenv("MESH_PARSE_CACHE_DISABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _max_entries() -> int:
    try:
        return max(1, int(os.getenv("MESH_PARSE_CACHE_MAX_ENTRIES", str(DEFAULT_MAX_ENTRIES))))
    except (TypeError, ValueError):
        return DEFAULT_MAX_ENTRIES


def _max_bytes() -> int:
    try:
        return max(1, int(os.getenv("MESH_PARSE_CACHE_MAX_BYTES", str(DEFAULT_MAX_BYTES))))
    except (TypeError, ValueError):
        return DEFAULT_MAX_BYTES


def mesh_nbytes(mesh) -> int:
    """Approximate resident size: the vertex + face arrays (the bulk of a
    Trimesh). Robust to objects lacking those attributes (returns 0)."""
    total = 0
    for attr in ("vertices", "faces"):
        arr = getattr(mesh, attr, None)
        nbytes = getattr(arr, "nbytes", None)
        if nbytes is not None:
            total += int(nbytes)
    return total


def key_for(data: bytes, suffix: str) -> _Key:
    return (hashlib.sha256(data).hexdigest(), suffix)


class MeshParseCache:
    """LRU cache guarded by a single lock. A race at worst re-parses (two
    threads miss the same key, both parse, both put — last put wins with an
    independent copy); it can never corrupt an entry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: "OrderedDict[_Key, object]" = OrderedDict()
        self._bytes: Dict[_Key, int] = {}
        self._total_bytes = 0
        # process-local observability counters (not authoritative metrics)
        self.hits = 0
        self.misses = 0

    def get(self, key: _Key):
        """Return a DEEP COPY of the cached mesh, or None on miss. The cached
        object is copied under the lock and never handed out directly."""
        with self._lock:
            mesh = self._store.get(key)
            if mesh is None:
                self.misses += 1
                return None
            self._store.move_to_end(key)  # mark most-recently-used
            self.hits += 1
            return mesh.copy()

    def put(self, key: _Key, mesh) -> None:
        """Store a DEEP COPY of ``mesh`` and evict LRU until within bounds."""
        copy = mesh.copy()
        size = mesh_nbytes(copy)
        with self._lock:
            if key in self._store:
                self._total_bytes -= self._bytes.pop(key, 0)
                del self._store[key]
            self._store[key] = copy
            self._bytes[key] = size
            self._total_bytes += size
            self._store.move_to_end(key)
            self._evict_locked()

    def _evict_locked(self) -> None:
        max_entries = _max_entries()
        max_bytes = _max_bytes()
        # Evict least-recently-used (front) until BOTH bounds hold. Keep at
        # least one entry so an oversized-vs-byte-bound part is still cacheable.
        while self._store and (
            len(self._store) > max_entries or self._total_bytes > max_bytes
        ):
            if len(self._store) == 1:
                break
            old_key, _ = self._store.popitem(last=False)
            self._total_bytes -= self._bytes.pop(old_key, 0)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._bytes.clear()
            self._total_bytes = 0
            self.hits = 0
            self.misses = 0

    def __contains__(self, key: _Key) -> bool:
        with self._lock:
            return key in self._store

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return self._total_bytes


_CACHE = MeshParseCache()


def get_cache() -> MeshParseCache:
    """The process-wide singleton cache."""
    return _CACHE
