"""The CI route-auth gate covers the auth routers as well as the API routers.

scripts/ci/check_route_auth.py fails on any route without an auth dependency
that is not on its public allowlist. It scans backend/src/api and
backend/src/auth; the intentionally public sign-in routes are allowlisted by
module ("auth/<file>").
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "ci" / "check_route_auth.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_route_auth_under_test", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_gate_passes_on_this_tree_and_counts_auth_routes():
    result = subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    gate = _load_gate()
    assert ROOT / "backend/src/auth" in gate.ROUTER_DIRS
    assert ("post", "/magic/start") in gate.PUBLIC_ALLOWLIST["auth/magic_link.py"]


def test_an_unlisted_public_auth_route_fails_the_gate(tmp_path, monkeypatch, capsys):
    api = tmp_path / "api"
    auth = tmp_path / "auth"
    api.mkdir()
    auth.mkdir()
    (api / "ok.py").write_text(
        "from fastapi import APIRouter, Depends\n"
        "router = APIRouter()\n"
        "@router.get('/x')\n"
        "async def x(user=Depends(require_api_key)):\n"
        "    return {}\n"
    )
    (auth / "leaky.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.post('/grant')\n"
        "async def grant():\n"
        "    return {}\n"
    )
    gate = _load_gate()
    monkeypatch.setattr(gate, "ROUTER_DIRS", [api, auth])
    assert gate.main() == 1
    assert "auth/leaky.py: POST /grant" in capsys.readouterr().out


def test_an_allowlisted_public_auth_route_passes(tmp_path, monkeypatch):
    api = tmp_path / "api"
    auth = tmp_path / "auth"
    api.mkdir()
    auth.mkdir()
    (auth / "magic_link.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.post('/magic/start')\n"
        "async def magic_start():\n"
        "    return {}\n"
    )
    gate = _load_gate()
    monkeypatch.setattr(gate, "ROUTER_DIRS", [api, auth])
    assert gate.main() == 0
