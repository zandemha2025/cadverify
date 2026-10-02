"""Geometry refusal explains the actual defect and locates it in source space."""
import numpy as np
import trimesh

from src.analysis.base_analyzer import analyze_geometry, check_normals, check_watertight
from src.analysis.models import AnalysisResult
from src.analysis.serialization import serialize_issue
from src.costing import EstimateOptions, estimate_decision
from src.costing.report import render_text


def test_open_edges_are_source_coordinates_with_a_bounded_honest_sample():
    mesh = trimesh.creation.box(extents=[10, 20, 30])
    mesh.apply_translation([123, -45, 67])
    mesh.update_faces(np.arange(len(mesh.faces)) != 0)
    issue = check_watertight(mesh)[0]
    counts = np.bincount(mesh.edges_unique_inverse)
    expected = mesh.vertices[mesh.edges_unique[counts == 1]]
    assert len(expected) == 3
    np.testing.assert_equal(issue.edge_segments, expected)
    np.testing.assert_equal(issue.region_center, expected[0].mean(axis=0))
    payload = serialize_issue(issue, max_faces=2)
    assert payload["edge_segment_count"] == 3
    assert len(payload["edge_segments"]) == 2
    assert payload["edge_segments_truncated"] is True
    assert payload["scope"] == "localized"
    assert "3 open edges" in payload["message"]
    assert payload["edge_segments"][0] == expected[0].tolist()
    assert payload["edge_segments"][-1] == expected[-1].tolist()
    # No source face IDs are misrepresented as decimated-analysis indices.
    assert "affected_faces_sample" not in payload
    result = AnalysisResult("open.stl", "stl", analyze_geometry(mesh), universal_issues=[issue])
    report = estimate_decision(result, mesh, [], EstimateOptions())
    assert report.status == "GEOMETRY_INVALID" and not report.estimates
    assert "3 open edges" in report.reason
    text = render_text(report)
    assert "Volume unavailable" in text and "0 cm³" not in text


def test_nonmanifold_edges_and_reversed_faces_get_their_actual_locations():
    mesh = trimesh.creation.box()
    mesh.faces = np.vstack([mesh.faces, mesh.faces[0]])
    issue = check_watertight(mesh)[0]
    assert "0 open edges and 3 edges shared by more than two faces" in issue.message
    assert len(issue.edge_segments) == 3

    mesh = trimesh.creation.box()
    mesh.faces[0] = mesh.faces[0][::-1]
    mesh._cache.clear()
    assert mesh.is_watertight
    issue = check_normals(mesh)[0]
    face_vertices = set(mesh.faces[0])
    for segment in issue.edge_segments:
        assert all(any(np.array_equal(point, mesh.vertices[i]) for i in face_vertices) for point in segment)
    assert len(issue.edge_segments) == 3
    result = AnalysisResult("reversed.stl", "stl", analyze_geometry(mesh), universal_issues=[issue])
    report = estimate_decision(result, mesh, [], EstimateOptions())
    assert "inconsistent directions" in report.reason
    assert "non-watertight" not in report.reason


def test_closed_solid_has_no_failure_edges():
    mesh = trimesh.creation.box(extents=[10, 20, 30])
    assert check_watertight(mesh) == []
    assert check_normals(mesh) == []
    assert analyze_geometry(mesh).volume == 6000
