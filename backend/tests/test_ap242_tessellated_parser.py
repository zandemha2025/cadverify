"""AP242 embedded tessellation ingestion without native OCC import."""
from __future__ import annotations

import numpy as np
import pytest

from src.parsers import step_mesher
from src.parsers.ap242_tessellated_parser import (
    AP242TessellationError,
    is_ap242_tessellated,
    parse_ap242_tessellated,
)


def _step(
    *,
    points: str,
    faces: str,
    pnmax: int = 8,
    pnindex: str = "()",
    length_unit: str = ".MILLI.,.METRE.",
) -> bytes:
    return f"""ISO-10303-21;
HEADER;
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));
ENDSEC;
DATA;
#1=COORDINATES_LIST('',{pnmax},({points}));
#2=TRIANGULATED_FACE('',#1,{pnmax},(),$,{pnindex},({faces}));
#3=TESSELLATED_SOLID('PartBody',(#2),$);
#4=TESSELLATED_SHAPE_REPRESENTATION('Part',(#3),#99);
#90=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT({length_unit}));
#91=(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.));
#92=(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT());
#99=(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNIT_ASSIGNED_CONTEXT((#90,#91,#92))REPRESENTATION_CONTEXT('',''));
ENDSEC;
END-ISO-10303-21;
""".encode()


CUBE_POINTS = """(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)"""
CUBE_FACES = """(1,3,2),(1,4,3),(5,6,7),(5,7,8),
(1,2,6),(1,6,5),(4,8,7),(4,7,3),
(1,5,8),(1,8,4),(2,3,7),(2,7,6)"""


def test_ap242_embedded_cube_is_exact_and_watertight():
    data = _step(points=CUBE_POINTS, faces=CUBE_FACES)
    assert is_ap242_tessellated(data)

    mesh = parse_ap242_tessellated(data)

    assert mesh.is_watertight
    assert len(mesh.faces) == 12
    assert np.allclose(mesh.bounds, [[-1, -1, -1], [1, 1, 1]])
    assert mesh.volume == pytest.approx(8.0)


def test_pnindex_maps_local_face_indices_to_coordinate_indices():
    data = _step(
        points=CUBE_POINTS,
        faces=CUBE_FACES,
        pnindex="(8,7,6,5,4,3,2,1)",
    )
    mesh = parse_ap242_tessellated(data)
    assert mesh.is_watertight
    assert abs(mesh.volume) == pytest.approx(8.0)


def test_step_mesher_uses_embedded_geometry_when_gmsh_is_absent(monkeypatch):
    monkeypatch.setattr(step_mesher, "_HAS_GMSH", False)
    mesh = step_mesher.step_to_trimesh_from_bytes(
        _step(points=CUBE_POINTS, faces=CUBE_FACES),
        "embedded.step",
    )
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(8.0)


def test_metres_are_scaled_to_millimetres():
    mesh = parse_ap242_tessellated(
        _step(points=CUBE_POINTS, faces=CUBE_FACES, length_unit="$,.METRE.")
    )
    assert np.allclose(mesh.extents, [2000.0, 2000.0, 2000.0])
    assert mesh.volume == pytest.approx(8_000_000_000.0)


def test_named_inches_are_scaled_to_millimetres():
    data = _step(points=CUBE_POINTS, faces=CUBE_FACES).replace(
        b"#90=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));",
        b"#90=(CONVERSION_BASED_UNIT('inch',#93)LENGTH_UNIT()NAMED_UNIT(#94));"
        b"#93=MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#95);"
        b"#94=DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.);"
        b"#95=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));",
    )
    mesh = parse_ap242_tessellated(data)
    assert np.allclose(mesh.extents, [50.8, 50.8, 50.8])
    assert mesh.volume == pytest.approx(50.8**3)


def test_missing_dimensional_context_is_rejected():
    data = _step(points=CUBE_POINTS, faces=CUBE_FACES).replace(
        b"GLOBAL_UNIT_ASSIGNED_CONTEXT((#90,#91,#92))",
        b"GLOBAL_UNIT_ASSIGNED_CONTEXT((#91,#92))",
    )
    with pytest.raises(AP242TessellationError, match="exactly one active length unit"):
        parse_ap242_tessellated(data)


def test_invalid_triangle_index_is_bounded():
    data = _step(points=CUBE_POINTS, faces="(1,2,99)")
    with pytest.raises(AP242TessellationError, match="outside"):
        parse_ap242_tessellated(data)


def test_non_ap242_step_is_not_claimed():
    data = b"ISO-10303-21; FILE_SCHEMA(('AP203')); DATA; ENDSEC;"
    assert not is_ap242_tessellated(data)
