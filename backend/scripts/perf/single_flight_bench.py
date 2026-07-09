"""Real BEFORE/AFTER proof for async single-flight parse dedup.

Fires N CONCURRENT ``_parse_mesh_async`` calls for the SAME large periodic-
surface NIST part (nist_ctc_05, ~seconds to tessellate via the retry ladder) and
counts how many underlying pool parses actually run:

  * BEFORE (MESH_PARSE_CACHE_DISABLED=1): no coordination -> N independent parses
    contend for the pool; total wall ~ N/workers waves of a single parse.
  * AFTER  (default):                     single-flight -> exactly ONE parse; all
    N callers share it; total wall ~ one parse.

We instrument by wrapping ``parse_pool.submit_async`` with a counter (one entry
== one full parse pipeline). Run from backend/:

    PYTHONPATH=$PWD .venv/bin/python scripts/perf/single_flight_bench.py
"""
from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.api import routes
from src.parsers import mesh_cache, parse_pool

PART = Path(
    "/home/user/cadverify/data/real-corpus/NIST-PMI-STEP-Files/"
    "AP203 geometry only/nist_ctc_05_asme1_rd.stp"
)
CUBE = Path("tests/assets/cube.step")
N = 3  # the real Verify burst: /validate + /validate/cost + /validate/preview-mesh


def _instrument():
    """Wrap parse_pool.submit_async with a call counter; return (restore, calls)."""
    calls = {"n": 0}
    orig = parse_pool.submit_async

    async def _counting(data, suffix):
        calls["n"] += 1
        return await orig(data, suffix)

    parse_pool.submit_async = _counting
    routes.parse_pool.submit_async = _counting  # routes imported the module ref

    def restore():
        parse_pool.submit_async = orig
        routes.parse_pool.submit_async = orig

    return restore, calls


async def _run(data: bytes, disabled: bool):
    if disabled:
        os.environ["MESH_PARSE_CACHE_DISABLED"] = "1"
    else:
        os.environ.pop("MESH_PARSE_CACHE_DISABLED", None)
    mesh_cache.get_cache().clear()
    restore, calls = _instrument()
    try:
        t = time.perf_counter()
        results = await asyncio.gather(
            *[routes._parse_mesh_async(data, "nist.step") for _ in range(N)]
        )
        wall = time.perf_counter() - t
    finally:
        restore()
    faces = [len(m.faces) for m, _ in results]
    ids = {id(m) for m, _ in results}
    return wall, calls["n"], faces, len(ids)


async def main() -> str:
    data = PART.read_bytes()
    out: list[str] = []

    def p(s: str = ""):
        out.append(s)
        print(s, flush=True)

    p("=== async single-flight parse dedup: BEFORE vs AFTER (real periodic part) ===")
    p(f"measured: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC  (time.perf_counter, real runs)")
    p(f"host: single-container  machine={platform.machine()}  "
      f"py{platform.python_version()}  os.cpu_count()={os.cpu_count()}")
    p(f"pool workers = {parse_pool.worker_count()}  (min(cpu-1, cap=8); PARSE_POOL_WORKERS overrides)")
    p(f"ANALYSIS_TIMEOUT_SEC = {os.getenv('ANALYSIS_TIMEOUT_SEC', '60')} (route budget / 504 threshold)")
    p(f"part: {PART.name}  bytes={len(data)}  (NIST periodic-surface, retry-ladder recovery)")
    p(f"concurrency N = {N}  (the Verify burst: /validate + /validate/cost + /validate/preview-mesh)")
    p("")

    # warm the spawn pool + recovery-rung executors cheaply (cube), off the clock.
    tw = time.perf_counter()
    await routes._parse_mesh_async(CUBE.read_bytes(), "cube.step")
    p(f"warm-up (cube via ladder, pays spawn+import once): {time.perf_counter() - tw:.2f}s")
    p("")

    # single-part baseline (warm pool, cold cache) — one parse, for reference.
    mesh_cache.get_cache().clear()
    t = time.perf_counter()
    m, _ = await routes._parse_mesh_async(data, "nist.step")
    single = time.perf_counter() - t
    p(f"single periodic parse (warm pool, cold cache): {single:.2f}s  faces={len(m.faces)}")
    p("")

    before_wall, before_n, before_faces, before_ids = await _run(data, disabled=True)
    p(f"--- BEFORE (MESH_PARSE_CACHE_DISABLED=1): {N} concurrent, SAME part ---")
    p(f"  underlying parses actually run : {before_n}   (== N: no dedup)")
    p(f"  total wall-clock               : {before_wall:.2f}s   (~{before_wall / single:.2f}x one parse)")
    p(f"  all callers got a valid mesh   : {before_faces}  distinct objects={before_ids}/{N}")
    p("")

    after_wall, after_n, after_faces, after_ids = await _run(data, disabled=False)
    p(f"--- AFTER (default, single-flight): {N} concurrent, SAME part ---")
    p(f"  underlying parses actually run : {after_n}   (== 1: ONE shared parse)")
    p(f"  total wall-clock               : {after_wall:.2f}s   (~{after_wall / single:.2f}x one parse)")
    p(f"  all callers got a valid mesh   : {after_faces}  distinct objects={after_ids}/{N}")
    p("")

    p("=== RESULT ===")
    p(f"  parses: {before_n} (before) -> {after_n} (after)   [{before_n}x -> 1x redundant tessellation]")
    p(f"  wall  : {before_wall:.2f}s (before) -> {after_wall:.2f}s (after)   "
      f"[{before_wall / max(after_wall, 1e-9):.2f}x faster on the cold burst]")
    p("  Single-flight collapses the N-way cold-cache burst into one parse: every")
    p("  caller (incl. /validate/preview-mesh) shares it, so preview-mesh no longer")
    p("  blows ANALYSIS_TIMEOUT_SEC while /validate already returned 200.")

    assert after_n == 1, f"AFTER must be exactly one parse, got {after_n}"
    assert before_n == N, f"BEFORE must be N parses, got {before_n}"
    assert after_ids == N, "each caller must own an independent mesh"
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = asyncio.run(main())
    parse_pool.shutdown()
    dest = sys.argv[1] if len(sys.argv) > 1 else None
    if dest:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_text(text)
        print(f"\nwrote {dest}", flush=True)
