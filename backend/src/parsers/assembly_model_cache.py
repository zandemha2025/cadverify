"""The extracted assembly model of one check, kept briefly so the check's calls extract it once.

The app asks ``/validate/assembly`` three times about one assembly file: ``json``
(how many bodies, and the product tree), then ``glb`` (the 3D view) and
``analysis`` together. Each call extracted the whole model again: 7.7 s of gmsh
each for the 30-body asm-30. The model is now kept for the check that made it
(the organization, the person and the file: ``compute_budget.check_key()``) for
``TTL_SEC`` seconds, and handed out as a deep copy on every hit, so no call can
change what another gets.

Bounded: at most ``MAX_ENTRIES`` models and ``MAX_FACES`` triangles held in all
(a model over that alone isn't kept). asm-30's kept copy (153,168 triangles) is
6.7 MB, so the bound is about 13 MB, held outside any check's reservation.
Deleting a file's data forgets its models (``mesh_cache.forget_hashes`` calls
``forget_hashes`` here).
"""
from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from typing import Optional

TTL_SEC = 60.0
MAX_ENTRIES = 4
MAX_FACES = 300_000

_LOCK = threading.Lock()
# (check key, suffix) -> (expires at, model, triangles, every body meshed)
_STORE: "OrderedDict[tuple[str, str], tuple[float, object, int, bool]]" = OrderedDict()


def _faces(model) -> int:
    return sum(len(getattr(p.mesh, "faces", ())) for p in model.parts if getattr(p, "mesh", None) is not None)


def _expire(now: float) -> None:
    for key in [k for k, v in _STORE.items() if v[0] <= now]:
        del _STORE[key]


def get(check: Optional[str], suffix: str, *, meshed: bool):
    """A copy of this check's model, or None. ``meshed``: the caller needs every
    body's mesh (a one-solid model read unmeshed for the probe doesn't serve it)."""
    if not check:
        return None
    now = time.monotonic()
    with _LOCK:
        _expire(now)
        entry = _STORE.get((check, suffix))
        if entry is None or (meshed and not entry[3]):
            return None
        model = entry[1]
    return copy.deepcopy(model)


def put(check: Optional[str], suffix: str, model, *, mesh_single_part: bool) -> None:
    """Keep a copy of ``model`` for this check (nothing without a check)."""
    if not check:
        return
    faces = _faces(model)
    if faces > MAX_FACES:
        return
    kept = copy.deepcopy(model)
    meshed = mesh_single_part or getattr(model, "part_count", 0) != 1
    now = time.monotonic()
    with _LOCK:
        _expire(now)
        _STORE.pop((check, suffix), None)
        _STORE[(check, suffix)] = (now + TTL_SEC, kept, faces, meshed)
        while len(_STORE) > MAX_ENTRIES or sum(v[2] for v in _STORE.values()) > MAX_FACES:
            _STORE.popitem(last=False)


def forget_hashes(hashes) -> int:
    """Drop the models of checks of these files (their SHA-256s)."""
    wanted = {str(h).lower() for h in hashes}
    with _LOCK:
        gone = [k for k in _STORE if set(k[0].rsplit(":", 1)[-1].split("+")) & wanted]
        for key in gone:
            del _STORE[key]
    return len(gone)


def clear() -> None:
    with _LOCK:
        _STORE.clear()
