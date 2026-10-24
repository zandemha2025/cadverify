"""Deterministic OpenCASCADE generation in a hard-timeboxed child process.

Only the allowlisted operation plans in :mod:`src.designs.schema` enter this
module. No source string is accepted or evaluated. A stuck/segfaulting CAD
kernel is isolated from the API/worker and killed at the deadline.
"""
from __future__ import annotations

import math
import multiprocessing
import os
import queue
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.designs.schema import draft_run, validate_design_plan
from src.parsers.sigpipe import ignore_sigpipe

DEFAULT_TIMEOUT_SECONDS = 45.0
MIN_ARTIFACT_BYTES = 128
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024


class DesignGenerationError(RuntimeError):
    code = "DESIGN_GENERATION_FAILED"


class DesignGenerationTimeout(DesignGenerationError):
    code = "DESIGN_GENERATION_TIMEOUT"


@dataclass(frozen=True)
class GeneratedArtifacts:
    step_bytes: bytes
    stl_bytes: bytes
    metadata: dict[str, Any]


def _fuse(gmsh: Any, entities: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(entities) == 1:
        return entities
    result, _ = gmsh.model.occ.fuse([entities[0]], entities[1:], removeObject=True, removeTool=True)
    return [(int(dim), int(tag)) for dim, tag in result if int(dim) == 3]


def _tapered_block(
    gmsh: Any,
    lower: tuple[float, float, float],
    upper: tuple[float, float, float],
) -> list[tuple[int, int]]:
    """A six-faced solid between two centred rectangles ``(half_x, half_y, z)``.

    Every face is a true plane (exported as STEP ``PLANE``, not a lofted
    B-spline): equal rectangles give a box, a smaller lower rectangle gives
    side walls that lean in at one angle.
    """
    occ = gmsh.model.occ

    def ring(half_x: float, half_y: float, z: float) -> list[int]:
        return [
            occ.addPoint(-half_x, -half_y, z),
            occ.addPoint(half_x, -half_y, z),
            occ.addPoint(half_x, half_y, z),
            occ.addPoint(-half_x, half_y, z),
        ]

    low, high = ring(*lower), ring(*upper)
    bottom = [occ.addLine(low[i], low[(i + 1) % 4]) for i in range(4)]
    top = [occ.addLine(high[i], high[(i + 1) % 4]) for i in range(4)]
    rise = [occ.addLine(low[i], high[i]) for i in range(4)]
    faces = [
        occ.addPlaneSurface([occ.addCurveLoop(bottom)]),
        occ.addPlaneSurface([occ.addCurveLoop(top)]),
    ]
    for i in range(4):
        loop = occ.addCurveLoop([bottom[i], rise[(i + 1) % 4], -top[i], -rise[i]])
        faces.append(occ.addPlaneSurface([loop]))
    volume = occ.addVolume([occ.addSurfaceLoop(faces)])
    return [(3, int(volume))]


def _cut(gmsh: Any, solids: list[tuple[int, int]], tools: list[tuple[int, int]]) -> list[tuple[int, int]]:
    cut, _ = gmsh.model.occ.cut(solids, tools, removeObject=True, removeTool=True)
    return [(int(dim), int(tag)) for dim, tag in cut if int(dim) == 3]


def _drafted_plate(gmsh: Any, plan: Any) -> list[tuple[int, int]]:
    """Width, depth and hole diameters at the bottom face; the edges lean in and
    the holes open up toward the top, all at ``draft_angle_deg``."""
    tan = math.tan(math.radians(plan.draft_angle_deg))
    run = draft_run(plan.thickness_mm, plan.draft_angle_deg)
    half_x, half_y = plan.width_mm / 2.0, plan.depth_mm / 2.0
    solids = _tapered_block(
        gmsh,
        (half_x, half_y, 0.0),
        (half_x - run, half_y - run, plan.thickness_mm),
    )
    if not plan.holes:
        return solids
    margin = max(1.0, plan.thickness_mm * 0.1)
    tools = []
    for hole in plan.holes:
        radius = hole.diameter_mm / 2.0
        # The tool cone runs past both faces; below the bottom face it narrows,
        # so keep that overrun short enough for its tip radius to stay positive.
        below = min(margin, 0.5 * radius / tan)
        tools.append((3, int(gmsh.model.occ.addCone(
            hole.x_mm,
            hole.y_mm,
            -below,
            0.0,
            0.0,
            plan.thickness_mm + below + margin,
            radius - below * tan,
            radius + (plan.thickness_mm + margin) * tan,
        ))))
    return _cut(gmsh, solids, tools)


def _drafted_enclosure(gmsh: Any, plan: Any) -> list[tuple[int, int]]:
    """Width and depth at the open rim; outside and inside walls lean in toward
    the base by ``draft_angle_deg`` and stay ``wall_thickness_mm`` apart."""
    tan = math.tan(math.radians(plan.draft_angle_deg))
    wall = plan.wall_thickness_mm
    height = plan.height_mm
    half_x, half_y = plan.width_mm / 2.0, plan.depth_mm / 2.0
    run = draft_run(height, plan.draft_angle_deg)
    outer = _tapered_block(gmsh, (half_x - run, half_y - run, 0.0), (half_x, half_y, height))
    # Parallel inside planes, one wall thickness square to the outside planes.
    offset = wall / math.cos(math.radians(plan.draft_angle_deg))
    top = height + max(1.0, wall)  # cut past the rim so it opens cleanly
    floor_run = (height - wall) * tan
    above_run = (top - height) * tan
    inner = _tapered_block(
        gmsh,
        (half_x - floor_run - offset, half_y - floor_run - offset, wall),
        (half_x + above_run - offset, half_y + above_run - offset, top),
    )
    return _cut(gmsh, outer, inner)


def _build_shape(gmsh: Any, plan: Any) -> list[tuple[int, int]]:
    draft = float(getattr(plan, "draft_angle_deg", 0.0) or 0.0)
    if plan.kind == "plate" and draft > 0:
        return _drafted_plate(gmsh, plan)
    if plan.kind == "enclosure" and draft > 0:
        return _drafted_enclosure(gmsh, plan)
    # Draft 0 keeps the original construction exactly.
    if plan.kind == "plate":
        body = gmsh.model.occ.addBox(
            -plan.width_mm / 2.0,
            -plan.depth_mm / 2.0,
            0.0,
            plan.width_mm,
            plan.depth_mm,
            plan.thickness_mm,
        )
        solids = [(3, int(body))]
        if plan.holes:
            margin = max(1.0, plan.thickness_mm * 0.1)
            tools = [
                (
                    3,
                    int(
                        gmsh.model.occ.addCylinder(
                            hole.x_mm,
                            hole.y_mm,
                            -margin,
                            0.0,
                            0.0,
                            plan.thickness_mm + 2.0 * margin,
                            hole.diameter_mm / 2.0,
                        )
                    ),
                )
                for hole in plan.holes
            ]
            cut, _ = gmsh.model.occ.cut(solids, tools, removeObject=True, removeTool=True)
            solids = [(int(dim), int(tag)) for dim, tag in cut if int(dim) == 3]
        return solids

    if plan.kind == "bracket":
        base = gmsh.model.occ.addBox(
            -plan.width_mm / 2.0,
            -plan.depth_mm / 2.0,
            0.0,
            plan.width_mm,
            plan.depth_mm,
            plan.thickness_mm,
        )
        upright = gmsh.model.occ.addBox(
            -plan.width_mm / 2.0,
            -plan.depth_mm / 2.0,
            0.0,
            plan.thickness_mm,
            plan.depth_mm,
            plan.height_mm,
        )
        return _fuse(gmsh, [(3, int(base)), (3, int(upright))])

    wall = plan.wall_thickness_mm
    components = [
        (3, int(gmsh.model.occ.addBox(-plan.width_mm / 2.0, -plan.depth_mm / 2.0, 0.0, plan.width_mm, plan.depth_mm, wall))),
        (3, int(gmsh.model.occ.addBox(-plan.width_mm / 2.0, -plan.depth_mm / 2.0, 0.0, wall, plan.depth_mm, plan.height_mm))),
        (3, int(gmsh.model.occ.addBox(plan.width_mm / 2.0 - wall, -plan.depth_mm / 2.0, 0.0, wall, plan.depth_mm, plan.height_mm))),
        (3, int(gmsh.model.occ.addBox(-plan.width_mm / 2.0 + wall, -plan.depth_mm / 2.0, 0.0, plan.width_mm - 2.0 * wall, wall, plan.height_mm))),
        (3, int(gmsh.model.occ.addBox(-plan.width_mm / 2.0 + wall, plan.depth_mm / 2.0 - wall, 0.0, plan.width_mm - 2.0 * wall, wall, plan.height_mm))),
    ]
    return _fuse(gmsh, components)


def _orient_outward(gmsh: Any, solids: list[tuple[int, int]]) -> None:
    """Wind every boundary surface's triangles outward from its solid.

    The mesher winds a surface by its own parametrisation. OpenCASCADE boxes and
    boolean results carry outward faces, but a solid sewn from hand-made plane
    surfaces (``_tapered_block``) does not, so its preview STL came out with
    some faces wound inward (INCONSISTENT_NORMALS) while its STEP was a valid
    solid. A point just off a triangle's front side must lie outside the solid;
    a surface whose triangles face in is reversed.
    """
    mesh = gmsh.model.mesh
    for dim, tag in solids:
        box = gmsh.model.getBoundingBox(dim, tag)
        size = max(box[3] - box[0], box[4] - box[1], box[5] - box[2])
        for _sdim, surface in gmsh.model.getBoundary([(dim, tag)], combined=False, oriented=False):
            surface = abs(int(surface))
            types, _tags, nodes = mesh.getElements(2, surface)
            tri = next((list(n) for t, n in zip(types, nodes) if int(t) == 2 and len(n)), None)
            if tri is None:
                continue
            best = None
            for i in range(0, len(tri), 3):
                a, b, c = (mesh.getNode(int(n))[0] for n in tri[i:i + 3])
                u = [b[k] - a[k] for k in range(3)]
                v = [c[k] - a[k] for k in range(3)]
                normal = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
                area2 = math.sqrt(sum(x * x for x in normal))
                if best is None or area2 > best[0]:
                    best = (area2, [(a[k] + b[k] + c[k]) / 3.0 for k in range(3)], normal)
                if i >= 300:  # the largest of the first hundred triangles is plenty
                    break
            if best is None:  # tri is non-empty, so the loop above always sets it
                raise RuntimeError(f"surface {surface} has no triangle to orient by")
            area2, centre, normal = best
            if area2 <= 0:
                continue
            step = max(1e-4, 1e-4 * size)
            probe = [centre[k] + step * normal[k] / area2 for k in range(3)]
            if gmsh.model.isInside(dim, tag, probe) > 0:
                mesh.reverse([(2, surface)])


def _child_generate(plan_data: dict[str, Any], step_path: str, stl_path: str, result_queue: Any) -> None:
    """Child-process entrypoint. All exceptions become bounded status data."""
    try:
        import gmsh

        plan = validate_design_plan(plan_data)
        gmsh.initialize(["proofshape-design-generator", "-nopopup"], interruptible=False)
        ignore_sigpipe()  # gmsh just reset it to terminate the process
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("scalecad_design")
            solids = _build_shape(gmsh, plan)
            gmsh.model.occ.synchronize()
            if not solids:
                raise RuntimeError("OpenCASCADE produced no solid")

            boxes = [gmsh.model.getBoundingBox(dim, tag) for dim, tag in solids]
            minimums = [min(box[i] for box in boxes) for i in range(3)]
            maximums = [max(box[i + 3] for box in boxes) for i in range(3)]
            bbox = [maximums[i] - minimums[i] for i in range(3)]
            volume_mm3 = sum(float(gmsh.model.occ.getMass(dim, tag)) for dim, tag in solids)

            gmsh.write(step_path)
            max_dim = max(bbox)
            gmsh.option.setNumber("Mesh.MeshSizeMax", max(0.5, min(10.0, max_dim / 35.0)))
            gmsh.option.setNumber("Mesh.MeshSizeMin", max(0.1, min(2.0, max_dim / 140.0)))
            # Holes and round edges at least 12 facets round, as ScaleCAD meshes
            # an uploaded STEP (step_mesher._CURVATURE_PTS): a coarser preview
            # reads its holes' facets as corners and undercuts the STEP doesn't have.
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
            gmsh.model.mesh.generate(2)
            _orient_outward(gmsh, solids)
            gmsh.write(stl_path)
            # ``getElements(2)[1]`` is a list of element-tag arrays. Keep the
            # metadata calculation explicit to avoid depending on numpy.
            element_tags = gmsh.model.mesh.getElements(2)[1]
            surface_elements = sum(len(tags) for tags in element_tags)
            result_queue.put(
                {
                    "ok": True,
                    "metadata": {
                        "bbox_mm": [round(float(v), 6) for v in bbox],
                        "volume_cm3": round(volume_mm3 / 1000.0, 6),
                        "surface_elements": int(surface_elements),
                        "solid_count": len(solids),
                        "engine": "proofshape-occ-v1",
                    },
                }
            )
        finally:
            gmsh.finalize()
    except BaseException as exc:  # child boundary: never leak a traceback/payload
        result_queue.put(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "message": str(exc)[:300],
            }
        )


def generate_design_artifacts(
    plan_value: object,
    *,
    timeout_seconds: float | None = None,
) -> GeneratedArtifacts:
    """Generate real STEP + STL bytes from one strict operation plan."""
    try:
        plan = validate_design_plan(plan_value)
    except Exception as exc:
        raise DesignGenerationError("persisted operation plan is invalid") from exc
    raw_timeout: float | str = (
        timeout_seconds
        if timeout_seconds is not None
        else os.getenv(
            "DESIGN_GENERATION_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)
        )
    )
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise DesignGenerationError(
            "generation timeout configuration is invalid"
        ) from exc
    timeout = max(1.0, min(timeout, 120.0))
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)

    with tempfile.TemporaryDirectory(prefix="proofshape-design-") as tmp:
        step_path = str(Path(tmp) / "model.step")
        stl_path = str(Path(tmp) / "preview.stl")
        process = context.Process(
            target=_child_generate,
            args=(plan.model_dump(mode="json"), step_path, stl_path, result_queue),
            daemon=False,
        )
        try:
            process.start()
            process.join(timeout)
            if process.is_alive():
                process.kill()
                process.join(5.0)
                raise DesignGenerationTimeout(
                    f"CAD generation exceeded the {timeout:.0f}s safety limit"
                )
            try:
                outcome = result_queue.get(timeout=1.0)
            except queue.Empty as exc:
                raise DesignGenerationError(
                    f"CAD worker exited without an artifact (exit={process.exitcode})"
                ) from exc
        finally:
            result_queue.close()
            result_queue.join_thread()

        if not outcome.get("ok"):
            error_type = outcome.get("error_type", "GenerationError")
            message = outcome.get("message", "CAD generation failed")
            raise DesignGenerationError(f"{error_type}: {message}")

        step_file = Path(step_path)
        stl_file = Path(stl_path)
        if (
            step_file.stat().st_size > MAX_ARTIFACT_BYTES
            or stl_file.stat().st_size > MAX_ARTIFACT_BYTES
        ):
            raise DesignGenerationError("CAD kernel returned an oversized artifact")
        step = step_file.read_bytes()
        stl = stl_file.read_bytes()
        if len(step) < MIN_ARTIFACT_BYTES or len(stl) < MIN_ARTIFACT_BYTES:
            raise DesignGenerationError("CAD kernel returned an empty artifact")
        return GeneratedArtifacts(
            step_bytes=step,
            stl_bytes=stl,
            metadata=dict(outcome["metadata"]),
        )
