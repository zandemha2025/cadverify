"""Add draft to side walls about the check's pull direction (+Z), with full OCP.

gmsh exposes no draft operation, so this fix needs the complete OpenCASCADE
Python bindings (``cadquery-ocp``, import name ``OCP``). They are NOT a
production dependency today: ``available()`` gates every offer of this fix, and
``cad_fix_service`` never lists ``add_draft`` as something ScaleCAD can do
unless the module imports. Nothing else depends on it.

The edit (``BRepOffsetAPI_DraftAngle``): every planar or vertical-axis
cylindrical/conical face whose outward normal is within 10 degrees of
horizontal (the engine's side-wall band) and has less than the requested draft
is tilted about the line where it meets the horizontal plane through its own
lowest point. Matter is removed above that plane, so each wall keeps its base
and opens upward: outer walls lean in, holes and pockets widen toward the top.
That is a +Z pull with the parting line at the bottom of each wall. Faces of
any other surface type are left as they are and reported.
"""
from __future__ import annotations

# The OCP imports below are all lazy and gated by available(): the bindings are
# an optional dependency, absent from the production and CI environments.
# pyright: reportMissingImports=false

import importlib.util
import math
import os
import tempfile

from src.fixes.brep_fixes import FixOutcome, FixRefused, _deterministic

SIDEWALL_BAND_DEG = 10.0  # engine: 80-100 degrees from +Z is a side wall


def available() -> bool:
    try:
        return importlib.util.find_spec("OCP") is not None
    except (ImportError, ValueError):
        return False


def _read(data: bytes, suffix: str):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.IGESControl import IGESControl_Reader
    from OCP.STEPControl import STEPControl_Reader

    with tempfile.TemporaryDirectory(prefix="cadfix-ocp-") as tmp:
        path = os.path.join(tmp, f"source{suffix}")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        reader = STEPControl_Reader() if suffix in (".step", ".stp") else IGESControl_Reader()
        if reader.ReadFile(path) != IFSelect_RetDone:
            raise FixRefused("The stored file could not be read as CAD geometry.")
        reader.TransferRoots()
        return reader.OneShape()


def _write(shape, suffix: str) -> bytes:
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.IGESControl import IGESControl_Writer
    from OCP.Interface import Interface_Static
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    with tempfile.TemporaryDirectory(prefix="cadfix-ocp-") as tmp:
        path = os.path.join(tmp, f"fixed{suffix}")
        if suffix in (".step", ".stp"):
            Interface_Static.SetCVal_s("write.step.unit", "MM")
            writer = STEPControl_Writer()
            if writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone or writer.Write(path) != IFSelect_RetDone:
                raise RuntimeError("STEP write failed")
        else:
            writer = IGESControl_Writer("MM", 1)
            writer.AddShape(shape)
            writer.ComputeModel()
            if not writer.Write(path):
                raise RuntimeError("IGES write failed")
        with open(path, "rb") as fh:
            return _deterministic(fh.read(), suffix)


def _cast(name: str):
    """``TopoDS.Solid_s`` in OCP 7.8, ``TopoDS.Solid`` in OCP 8."""
    from OCP.TopoDS import TopoDS

    return getattr(TopoDS, f"{name}_s", None) or getattr(TopoDS, name)


def _explore(shape, kind: str):
    from OCP import TopAbs
    from OCP.TopExp import TopExp_Explorer

    cast = _cast(kind.capitalize())
    out = []
    exp = TopExp_Explorer(shape, getattr(TopAbs, f"TopAbs_{kind.upper()}"))
    while exp.More():
        out.append(cast(exp.Current()))
        exp.Next()
    return out


def _solids(shape):
    return _explore(shape, "solid")


def _sewn_solid(shape):
    """IGES often carries loose faces: sew them, tightest tolerance first, and
    make a solid only when sewing closes exactly one shell with no free edges
    (the same outcome the gmsh import reaches with OCC sewing)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid

    faces = _explore(shape, "face")
    for tolerance in (1e-6, 1e-5, 1e-4):
        sewing = BRepBuilderAPI_Sewing(tolerance)
        for face in faces:
            sewing.Add(face)
        sewing.Perform()
        shells = _explore(sewing.SewedShape(), "shell")
        if len(shells) != 1 or sewing.NbFreeEdges() or sewing.NbMultipleEdges():
            continue
        maker = BRepBuilderAPI_MakeSolid(shells[0])
        if not maker.IsDone():
            continue
        fixer = ShapeFix_Solid(maker.Solid())
        fixer.Perform()
        solids = _solids(fixer.Solid())
        if len(solids) == 1 and _volume(solids[0]) > 0:
            return solids[0]
    return None


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return float(props.Mass())


def _faces(shape):
    return _explore(shape, "face")


def _face_info(face):
    """``(kind, min outward-normal z, max z, zmin)`` sampled over the face."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.TopAbs import TopAbs_REVERSED

    surf = BRepAdaptor_Surface(face, True)
    kind = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone"}.get(surf.GetType(), "other")
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
    nz = []
    props = BRepLProp_SLProps(surf, 1, 1e-7)
    for i in range(5):
        for j in range(5):
            u = umin + (umax - umin) * (i + 0.5) / 5
            v = vmin + (vmax - vmin) * (j + 0.5) / 5
            props.SetParameters(u, v)
            if not props.IsNormalDefined():
                continue
            n = props.Normal()
            z = n.Z() * (-1.0 if face.Orientation() == TopAbs_REVERSED else 1.0)
            nz.append(z)
    box = Bnd_Box()
    BRepBndLib.Add_s(face, box)
    zmin = box.CornerMin().Z()
    zmax = box.CornerMax().Z()
    return kind, nz, zmin, zmax, surf


def _vertical_axis(surf) -> bool:
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder

    if surf.GetType() == GeomAbs_Cylinder:
        axis = surf.Cylinder().Axis().Direction()
    elif surf.GetType() == GeomAbs_Cone:
        axis = surf.Cone().Axis().Direction()
    else:
        return True
    return abs(abs(axis.Z()) - 1.0) < 1e-6


def add_draft(data: bytes, suffix: str, angle_deg: float) -> FixOutcome:
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

    if suffix not in (".step", ".stp", ".iges", ".igs"):
        raise FixRefused("Adding draft needs a STEP or IGES file; an STL has no faces to tilt.")
    if not (0.25 <= angle_deg <= 10.0):
        raise FixRefused("Use a draft angle from 0.25 to 10 degrees.")
    shape = _read(data, suffix)
    solids = _solids(shape)
    if not solids and suffix in (".iges", ".igs"):
        sewn = _sewn_solid(shape)
        solids = [sewn] if sewn is not None else []
    if len(solids) != 1:
        raise FixRefused("The file has no closed solid to edit." if not solids else
                         f"The file holds {len(solids)} solids. ScaleCAD edits one solid at a time.")
    solid = solids[0]
    before = _volume(solid)
    need = math.sin(math.radians(angle_deg)) - 1e-9
    band = math.sin(math.radians(SIDEWALL_BAND_DEG))
    tool = BRepOffsetAPI_DraftAngle(solid)
    drafted, skipped_kind, failed = 0, 0, 0
    pull = gp_Dir(0, 0, 1)
    for face in _faces(solid):
        kind, nz, zmin, zmax, surf = _face_info(face)
        if not nz or max(abs(z) for z in nz) > band:
            continue  # not a side wall
        if min(nz) >= need:
            continue  # already drafted enough for a +Z pull
        if kind == "other" or not _vertical_axis(surf):
            skipped_kind += 1
            continue
        tool.Add(face, pull, math.radians(angle_deg), gp_Pln(gp_Pnt(0, 0, zmin), pull), True)
        if tool.AddDone():
            drafted += 1
        else:
            tool.Remove(face)
            failed += 1
    if not drafted:
        return FixOutcome(False, None, suffix, "No side wall could be tilted.",
                          {"faces_failed": failed, "faces_unsupported": skipped_kind})
    tool.Build()
    if not tool.IsDone():
        return FixOutcome(False, None, suffix, "OpenCASCADE could not rebuild the solid with draft.",
                          {"faces_drafted": drafted})
    result = tool.Shape()
    out_solids = _solids(result)
    if len(out_solids) != 1 or not BRepCheck_Analyzer(result).IsValid():
        return FixOutcome(False, None, suffix, "Drafting produced an invalid solid.", {"faces_drafted": drafted})
    after = _volume(out_solids[0])
    if not (after > 0 and math.isfinite(after)):
        return FixOutcome(False, None, suffix, "Drafting produced an empty solid.")
    fixed = _write(result, suffix)
    return FixOutcome(True, fixed, suffix, None, {
        "faces_drafted": drafted,
        "faces_failed": failed,
        "faces_unsupported": skipped_kind,
        "angle_deg": angle_deg,
        "pull_direction": [0, 0, 1],
        "brep_volume_before_mm3": round(before, 3),
        "brep_volume_after_mm3": round(after, 3),
    })
