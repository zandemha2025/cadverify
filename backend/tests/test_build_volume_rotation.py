from types import SimpleNamespace

from src.analysis.models import BoundingBox, ProcessType
from src.analysis.processes.checks import check_build_volume


def _context(dims):
    box = BoundingBox(0, 0, 0, dims[0], dims[1], dims[2])
    return SimpleNamespace(info=SimpleNamespace(bounding_box=box))


def test_build_volume_accepts_an_axis_permutation_fit():
    assert check_build_volume(
        _context((350, 200, 100)), (300, 300, 350), ProcessType.FDM
    ) == []


def test_turning_envelope_accepts_length_along_machine_long_axis():
    assert check_build_volume(
        _context((300, 80, 80)), (254, 254, 533), ProcessType.CNC_TURNING
    ) == []


def test_build_volume_rejects_true_exceed_in_every_rotation():
    issues = check_build_volume(
        _context((350, 310, 100)), (300, 300, 350), ProcessType.FDM
    )
    assert len(issues) == 1
    assert issues[0].code == "EXCEEDS_BUILD_VOLUME"
    assert issues[0].severity.value == "error"
    assert "any axis-aligned rotation" in issues[0].message
