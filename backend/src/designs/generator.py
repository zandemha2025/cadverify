"""Deterministic OpenCASCADE generation in a hard-timeboxed child process.

Only the allowlisted operation plans in :mod:`src.designs.schema` enter this
module. No source string is accepted or evaluated. A stuck/segfaulting CAD
kernel is isolated from the API/worker and killed at the deadline.
"""
from __future__ import annotations

import multiprocessing
import os
import queue
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.designs.schema import validate_design_plan

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


def _build_shape(gmsh: Any, plan: Any) -> list[tuple[int, int]]:
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


def _child_generate(plan_data: dict[str, Any], step_path: str, stl_path: str, result_queue: Any) -> None:
    """Child-process entrypoint. All exceptions become bounded status data."""
    try:
        import gmsh

        plan = validate_design_plan(plan_data)
        gmsh.initialize(["proofshape-design-generator", "-nopopup"], interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("proofshape_design")
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
            gmsh.model.mesh.generate(2)
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
