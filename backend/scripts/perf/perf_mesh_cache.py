"""Real cold-vs-warm measurement of the parsed-mesh cache.

Drives the ACTUAL _parse_mesh_async coroutine (the same entrypoint the
/validate, /validate/cost and /validate/preview-mesh routes call) on the
committed cube.step, measured with time.perf_counter(). No fabricated numbers.
"""
import asyncio
import platform
import sys
import time
from pathlib import Path

# Allow running standalone (`python scripts/perf/perf_mesh_cache.py`) from the
# backend dir: put the backend root (which contains `src/`) on the path.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND_ROOT))

from src.api.routes import _parse_mesh_async
from src.parsers import mesh_cache

DATA = (_BACKEND_ROOT / "tests/assets/cube.step").read_bytes()


async def timed_parse():
    t = time.perf_counter()
    mesh, suffix = await _parse_mesh_async(DATA, "cube.step")
    return time.perf_counter() - t, mesh


async def main():
    cache = mesh_cache.get_cache()

    print("=== mesh parse cache: cold (miss) vs warm (hit) ===")
    print(f"host: single-container {platform.machine()} / py{platform.python_version()}")
    print(f"part: tests/assets/cube.step  ({len(DATA)} bytes)")

    cache.clear()
    cold, m = await timed_parse()
    print(f"faces: {len(m.faces)}  vertices: {len(m.vertices)}")
    print(f"cold  (miss, gmsh/OCC tessellation): {cold:.4f}s")

    warm_times = []
    for _ in range(10):
        w, _ = await timed_parse()
        warm_times.append(w)
    best = min(warm_times)
    avg = sum(warm_times) / len(warm_times)
    print(f"warm  (hit, deep copy): best {best*1000:.3f}ms  avg {avg*1000:.3f}ms  (N=10)")
    print(f"speedup on hit: {cold/best:.0f}x (cold {cold:.4f}s -> warm {best:.4f}s)")
    print(f"cache counters: hits={cache.hits} misses={cache.misses} "
          f"entries={len(cache)} bytes={cache.total_bytes}")

    # Prove the burst pattern: a single part hit by 3 endpoints re-parses once.
    cache.clear()
    burst = []
    for label in ("validate", "validate/cost", "validate/preview-mesh"):
        t, _ = await timed_parse()
        burst.append((label, t))
    print("\n=== verify-flow burst (same part, 3 endpoints) ===")
    for label, t in burst:
        kind = "MISS/parse" if t > 0.1 else "HIT/copy"
        print(f"  {label:24s} {t:.4f}s  [{kind}]")
    total_cached = sum(t for _, t in burst)
    # counterfactual: 3 cold parses
    print(f"  cached total:        {total_cached:.4f}s")
    print(f"  3x cold (no cache):  ~{cold*3:.4f}s  (each endpoint re-parses)")
    print(f"cache counters: hits={cache.hits} misses={cache.misses}")


if __name__ == "__main__":
    asyncio.run(main())
