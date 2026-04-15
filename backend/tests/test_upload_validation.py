"""Tests for pre-parse upload validation."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.upload_validation import validate_magic, enforce_triangle_cap


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


def test_enforce_triangle_cap_raises_when_exceeded(monkeypatch):
    monkeypatch.setenv("MAX_TRIANGLES", "10")
    import trimesh
    mesh = trimesh.creation.icosphere(subdivisions=3)  # >> 10 faces
    with pytest.raises(HTTPException) as exc:
        enforce_triangle_cap(mesh)
    assert exc.value.status_code == 400
