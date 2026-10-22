"""The wall check counts mesh triangles, and says the thinnest wall first (op-15).

"88058 faces below 0.8 mm min wall" on a flat plate with a dozen CAD faces: the
count is mesh triangles. The engine says so, and the run, the parts list and Make
or buy read its sentence as "Walls down to 0.364 mm, under the 0.8 mm min wall for
3-axis milling (88,058 mesh triangles)"; records made before keep reading right.
"""
from __future__ import annotations

import trimesh

from src.analysis.serialization import wall_words


def test_the_wall_sentence_in_plain_words():
    assert wall_words("88058 mesh triangles (97.0%) below 0.8mm min wall for 3-axis milling. Thinnest: 0.364mm.") == (
        "Walls down to 0.364 mm, under the 0.8 mm min wall for 3-axis milling (88,058 mesh triangles)")
    # A record made before op-15 said "faces" and named the method by its code.
    assert wall_words("24 faces (100.0%) below 1.5mm min wall for ded. Thinnest: 0.5mm.") == (
        "Walls down to 0.5 mm, under the 1.5 mm min wall for metal deposition (DED) (24 mesh triangles)")
    # The warning: under what a method recommends; a 0.7999 mm wall never reads as 0.8.
    assert wall_words("12 mesh triangles (3.1%) below 1.2mm for FDM printing. Thinnest: 0.7999mm. May warp.") == (
        "Walls down to 0.7999 mm, under the 1.2 mm recommended for FDM printing (12 mesh triangles)")
    assert wall_words("8 sidewall faces (100.0% of sidewall area) below 1.0° draft") is None
    assert wall_words(None) is None


def test_the_engine_counts_mesh_triangles_and_the_run_reads_it_plainly():
    from tests.test_deposition_size_floor import _analyze

    result, _mesh, _feats = _analyze(trimesh.creation.box(extents=[120.0, 80.0, 0.5]))
    thin = [i for s in result.process_scores for i in s.issues if i.code == "THIN_WALL"]
    assert thin, "a 0.5 mm plate is too thin for some method"
    for issue in thin:
        assert " mesh triangles (" in issue.message and " faces (" not in issue.message
        assert wall_words(issue.message).startswith("Walls down to ")
