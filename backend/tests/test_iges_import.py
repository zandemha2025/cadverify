"""Real IGES must work before any earlier CAD read initializes OCC's units."""
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("preference", [0, 1, 2, 3])
def test_iges_curve_recovery_preserves_authored_geometry_and_preferences(preference):
    from src.parsers.step_mesher import _iges_3d_preference

    source = (Path(__file__).parent / "assets" / "bored-block-mm.iges").read_bytes()
    source = source.replace(b"142,0,113,123,133,3;", f"142,0,113,123,133,{preference};".encode())
    recovered = _iges_3d_preference(source)
    if preference in (1, 2):
        assert recovered is None, "An explicit representation choice must not change"
    else:
        assert recovered is not None and len(recovered) == len(source)
        changes = [(a, b) for a, b in zip(source, recovered) if a != b]
        assert changes == [(ord(str(preference)), ord("2"))]
        assert _iges_3d_preference(recovered) is None


@pytest.mark.parametrize("reader", ["single", "assembly"])
def test_iges_curve_retry_does_not_close_a_missing_face(reader):
    from src.parsers.step_mesher import _iges_3d_preference, step_to_trimesh_from_bytes
    from src.parsers.assembly_mesher import extract_assembly_from_bytes

    # The same bored block with its upper cap removed still has ambiguous curves,
    # so it exercises the retry AND restoration of the native unclosed result.
    data = (Path(__file__).parent / "assets" / "open-bored-block-mm.iges").read_bytes()
    assert _iges_3d_preference(data) is not None
    if reader == "assembly":
        with pytest.raises(ValueError, match="No solid bodies found"):
            extract_assembly_from_bytes(data, "open.iges")
    else:
        assert not step_to_trimesh_from_bytes(data, "open.iges").is_watertight


@pytest.mark.parametrize("unit,scale,suffix", [("mm", 1, ".iges"), ("inch", 25.4, ".igs")])
@pytest.mark.parametrize("reader", ["single", "assembly"])
@pytest.mark.parametrize("shape", ["box", "bored-block", "open-plane"])
def test_cold_iges_import_preserves_units(unit, scale, suffix, reader, shape):
    fixture = Path(__file__).parent / "assets" / f"{shape}-{unit}.iges"
    # A separate interpreter matters: generating or reading another IGES first
    # initializes OCC's unit registry and would conceal the production failure.
    result = subprocess.run(
        [sys.executable, "-c", """
import json, sys
from pathlib import Path
from src.parsers.step_mesher import step_to_trimesh_from_bytes
from src.parsers.assembly_mesher import extract_assembly_from_bytes
data = Path(sys.argv[1]).read_bytes()
filename = 'part' + sys.argv[2]
if sys.argv[3] == 'assembly':
    if sys.argv[4] == 'open-plane':
        try:
            extract_assembly_from_bytes(data, filename)
        except ValueError as exc:
            assert 'No solid bodies found' in str(exc), str(exc)
        else:
            raise AssertionError('Unclosed IGES surfaces must not invent a solid')
    else:
        model = extract_assembly_from_bytes(data, filename)
        assert model.kind == 'single_part' and model.part_count == 1
        print(json.dumps({'extents': model.parts[0].world.bbox_size, 'volume': model.parts[0].world.volume}))
else:
    mesh = step_to_trimesh_from_bytes(data, filename)
    if sys.argv[4] == 'open-plane':
        assert not mesh.is_watertight, 'Do not bridge gaps to force a solid'
    else:
        assert mesh.is_watertight
        print(json.dumps({'extents': mesh.extents.tolist(), 'volume': mesh.volume}))
""", str(fixture.resolve()), suffix, reader, shape],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    if shape != "open-plane":
        measured = json.loads(result.stdout.splitlines()[-1])
        assert measured["extents"] == pytest.approx([20 * scale, 15 * scale, 10 * scale], abs=1e-4)
        volume = 3000 if shape == "box" else 3000 - math.pi * 3**2 * 10
        assert measured["volume"] == pytest.approx(volume * scale**3, rel=1e-8 if shape == "box" or reader == "assembly" else 1e-4)
