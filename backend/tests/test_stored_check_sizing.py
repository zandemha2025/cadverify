"""How big a file one worker can check: the measured memory model and its refusal."""
from __future__ import annotations

import struct

import pytest

from src.services import stored_check_service as svc

MB = 1024**2


def _binary_stl(tmp_path, triangles: int) -> str:
    p = tmp_path / "part.stl"
    with open(p, "wb") as fh:
        fh.write(b"\0" * 80 + struct.pack("<I", triangles))
        fh.truncate(84 + 50 * triangles)
    return str(p)


def test_a_binary_stl_is_sized_by_its_triangles_and_matches_the_measurements(tmp_path):
    need, basis = svc.estimate_memory_bytes(_binary_stl(tmp_path, 327_680), "part.stl")
    assert basis["format"] == "stl" and basis["triangles"] == 327_680
    assert need == int(975.0 * 1.10 * MB)  # the measured point, with 10% headroom
    between, _ = svc.estimate_memory_bytes(_binary_stl(tmp_path, 655_360), "part.stl")
    assert 975 * 1.1 * MB < between < 2016 * 1.1 * MB


def test_an_ascii_stl_is_sized_from_its_text(tmp_path):
    p = tmp_path / "part.stl"
    p.write_bytes(b"solid part\n" + b"x" * (290 * 81_920))
    need, basis = svc.estimate_memory_bytes(str(p), "part.stl")
    assert basis["format"] == "stl_ascii" and abs(basis["triangles"] - 81_920) < 2
    assert abs(need / MB - 461 * 1.1) < 2


def test_step_grows_with_file_size_and_past_the_last_point_at_its_slope(tmp_path):
    p = tmp_path / "asm.step"
    p.write_bytes(b"x" * int(20 * MB))
    need, basis = svc.estimate_memory_bytes(str(p), "asm.step")
    slope = (2396 - 1531) / (10.07 - 4.92)
    assert basis["format"] == "step"
    assert need == pytest.approx((2396 + slope * (20 - 10.07)) * 1.1 * MB, rel=1e-3)


@pytest.mark.parametrize("gb", [2, 4, 8, 16])
def test_the_largest_checkable_file_round_trips_through_the_model(tmp_path, gb):
    budget = int(gb * 1024**3 * 0.6)
    largest = svc.largest_checkable_bytes("step", budget)
    p = tmp_path / "big.step"
    with open(p, "wb") as fh:
        fh.truncate(largest)
    need, _ = svc.estimate_memory_bytes(str(p), "big.step")
    assert need <= budget < need * 1.01 + MB


def test_the_refusal_names_what_it_needs_and_the_largest_it_checks(monkeypatch):
    monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", str(1229))
    msg = svc.too_heavy_message(int(6.1 * 1024**3), {"format": "step"})
    assert msg.startswith("This file needs about 6.1 GB of memory to check; the largest STEP file ScaleCAD checks today is about ")
    assert msg.endswith("Nothing was charged.")


def test_the_budget_is_a_share_of_the_machine_unless_set(monkeypatch):
    monkeypatch.delenv("CHECK_MEMORY_BUDGET_MB", raising=False)
    monkeypatch.setattr(svc, "_container_memory_bytes", lambda: 2 * 1024**3)
    assert svc.check_memory_budget_bytes() == int(2 * 1024**3 * 0.6)
    monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "3000")
    assert svc.check_memory_budget_bytes() == 3000 * MB


def test_the_time_budget_follows_the_format():
    assert svc.time_budget_sec(10 * MB, "asm.step") == pytest.approx(120 + 90 * 10)
    assert svc.time_budget_sec(65 * MB, "mesh.stl") == pytest.approx(120 + 5 * 65)
    assert svc.time_budget_sec(5 * 1024**3, "huge.step") == svc.STORED_CHECK_JOB_TIMEOUT_SECONDS - 300
