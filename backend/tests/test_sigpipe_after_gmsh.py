"""A process that has run gmsh still ignores SIGPIPE.

gmsh's first initialize() resets SIGPIPE to its default action (terminate). The
backend then dies with no traceback on a write to a closed socket, as the suite
did on CI (exit status 141). ``src.parsers.sigpipe.ignore_sigpipe`` restores
the ignore after every initialize.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

_CHILD = r"""
import sys
sys.path.insert(0, ".")

def ignored():
    for line in open("/proc/self/status"):
        if line.startswith("SigIgn:"):
            return bool(int(line.split()[1], 16) & (1 << 12))

before = ignored()
from src.parsers.step_mesher import step_to_trimesh_from_bytes
from pathlib import Path
data = Path("src/parsers/fixtures/prewarm-cube.step").read_bytes()
mesh = step_to_trimesh_from_bytes(data, "prewarm-cube.step")
print(before, ignored(), len(mesh.faces) > 0)
"""


@pytest.mark.skipif(importlib.util.find_spec("gmsh") is None, reason="gmsh is not installed")
@pytest.mark.skipif(not Path("/proc/self/status").exists(), reason="reads the kernel's signal mask from /proc")
def test_a_process_that_meshed_a_step_still_ignores_sigpipe():
    # A fresh interpreter: the first gmsh initialize in a process is the one that resets it.
    out = subprocess.run(
        [sys.executable, "-c", _CHILD], cwd=BACKEND, capture_output=True, text=True, timeout=120, check=True,
    ).stdout.split()[-3:]
    assert out == ["True", "True", "True"], out


def test_every_gmsh_initialize_in_src_restores_the_ignore():
    # The pin for the call sites: a new initialize without it brings the crash back.
    missing = []
    for path in sorted((BACKEND / "src").rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not re.match(r"\s*gmsh\.initialize\(", line):  # a call, not a mention in a docstring
                continue
            following = lines[i + 1] if i + 1 < len(lines) else ""
            if "ignore_sigpipe()" not in following:
                missing.append(f"{path.relative_to(BACKEND)}:{i + 1}")
    assert not missing, f"gmsh.initialize without ignore_sigpipe() on the next line: {missing}"
