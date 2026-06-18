"""Tests for pre-parse upload validation."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.upload_validation import (
    binary_stl_triangle_count,
    demo_max_triangles,
    enforce_stl_triangle_count_cap,
    enforce_triangle_cap,
    validate_magic,
)


def binary_stl_with_triangles(count: int) -> bytes:
    return b"\0" * 80 + count.to_bytes(4, "little") + (b"\0" * 50 * count)


def test_validate_magic_accepts_valid_step():
    validate_magic(b"ISO-10303-21;\nHEADER;", ".step")  # no raise


def test_validate_magic_rejects_jpeg_as_step():
    with pytest.raises(HTTPException) as exc:
        validate_magic(b"\xff\xd8\xff\xe0JFIF", ".step")
    assert exc.value.status_code == 400


def test_validate_magic_rejects_short_stl():
    with pytest.raises(HTTPException) as exc:
        validate_magic(b"short", ".stl")
    assert exc.value.status_code == 400


def test_validate_magic_accepts_binary_stl_header():
    # 84 bytes of zeros → valid binary STL structure (0 triangles, still parses)
    validate_magic(b"\x00" * 84, ".stl")


def test_binary_stl_triangle_count_exact_length():
    assert binary_stl_triangle_count(binary_stl_with_triangles(12)) == 12


def test_binary_stl_triangle_count_ignores_inexact_ascii_like_payload():
    data = b"solid part\nendsolid part\n".ljust(120, b" ")
    assert binary_stl_triangle_count(data) is None


def test_demo_max_triangles_defaults_to_public_demo_limit(monkeypatch):
    monkeypatch.delenv("DEMO_MAX_TRIANGLES", raising=False)
    assert demo_max_triangles() == 500_000


def test_enforce_stl_triangle_count_cap_raises_before_parse():
    data = binary_stl_with_triangles(11)
    with pytest.raises(HTTPException) as exc:
        enforce_stl_triangle_count_cap(
            data,
            limit=10,
            limit_name="DEMO_MAX_TRIANGLES",
            status_code=413,
            subject="Public demo STL",
        )
    assert exc.value.status_code == 413
    assert "11" in exc.value.detail
    assert "DEMO_MAX_TRIANGLES" in exc.value.detail


def test_enforce_triangle_cap_raises_when_exceeded(monkeypatch):
    monkeypatch.setenv("MAX_TRIANGLES", "10")
    import trimesh
    mesh = trimesh.creation.icosphere(subdivisions=3)  # >> 10 faces
    with pytest.raises(HTTPException) as exc:
        enforce_triangle_cap(mesh)
    assert exc.value.status_code == 400
