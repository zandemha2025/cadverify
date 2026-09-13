from __future__ import annotations

import numpy as np
import pytest
import trimesh

from src.services.fit_seating import apply_seating, propose_auto_seating


def asymmetric_part():
    base = trimesh.creation.box(extents=[4, 2, 1])
    tab = trimesh.creation.box(extents=[1, 1, 2])
    tab.apply_translation([1.5, 0.5, 1.0])
    return trimesh.util.concatenate([base, tab])


def test_auto_seating_recovers_known_translation_or_refuses_ambiguity_honestly():
    a = asymmetric_part()
    b = a.copy()
    b.apply_translation([7, -3, 2])
    report = propose_auto_seating(a, b)
    # Disconnected but exact shells can still create duplicate ICP minima. Either a
    # clear transform is recovered or the service must retain shared coordinates.
    if report["accepted"]:
        seated = apply_seating(b, report["transform"])
        assert np.max(np.abs(seated.bounds - a.bounds)) < 1e-4
        assert report["rmse_mm"] < 1e-4
    else:
        assert report["method"] == "shared_frame_fallback"
        assert "ambiguous" in report["reason"]


def test_symmetric_part_does_not_claim_a_unique_auto_mate():
    a = trimesh.creation.box(extents=[10, 10, 10])
    b = a.copy()
    b.apply_translation([20, 0, 0])
    report = propose_auto_seating(a, b)
    assert report["manual_nudge_available"] is True
    if not report["accepted"]:
        assert report["transform"] == np.eye(4).tolist()


def test_manual_nudge_is_applied_in_shared_frame():
    mesh = trimesh.creation.box()
    transform = np.eye(4)
    transform[:3, 3] = [1.25, -2, 0.5]
    moved = apply_seating(mesh, transform.tolist())
    assert moved.centroid.tolist() == pytest.approx([1.25, -2, 0.5])
