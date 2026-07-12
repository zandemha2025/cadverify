"""STEP/IGES ASSEMBLY ingestion — per-part solids + world positions + product tree.

The single-part path (``step_mesher``) FLATTENS a STEP file to one triangulated
shell and the G1 gate refuses anything with >1 solid. That is a deliberate scope
boundary, not a capability gap: gmsh's embedded OpenCASCADE kernel already exposes
each sub-solid, its baked world placement, and the nested product-label tree of a
real STEP assembly. THIS module is the assembly-aware sibling of ``step_mesher``:
it enumerates ``getEntities(3)`` and, for every solid, captures

  * its own tessellated mesh (a ``trimesh.Trimesh`` in WORLD coordinates),
  * its world position — bbox, ``occ.getCenterOfMass`` centroid, ``occ.getMass``
    volume,
  * its name + full ``/``-separated tree_path (via ``getEntityName``), the ``::N``
    instance indices parsed into a real nested parent->children product tree,
  * a geometry_summary (boundary-face count, triangle/vertex counts, bbox dims).

Discipline REUSED from ``step_mesher`` (not re-invented, not regressed):
  * the SAME OCC import calls (``occ.importShapes`` + ``synchronize``) and the SAME
    curvature-adaptive, diagonal-scaled mesh-size policy,
  * the SAME retry ladder (``_MESH_RUNGS``: primary -> MeshAdapt-uniform ->
    +OCC-heal) applied at the WHOLE-assembly level, so a periodic-surface abort
    recovers to a coarser-but-valid shell instead of hard-failing,
  * the process-global ``_GMSH_LOCK`` (gmsh is not thread-safe),
  * ``trimesh(process=True)`` per solid to recover per-part watertightness.

Bounds (never unbounded): ``MAX_ASSEMBLY_PARTS`` caps how many solids we TESSELLATE
— past it we degrade to a metadata-only model (positions + tree, no per-part
meshes) with an honest note rather than blowing the mesh budget or the timeout.
``MAX_ASSEMBLY_FACES`` caps total triangles (a clean 400, like the single-part
``MAX_TRIANGLES`` cap).

Honest limits (SURFACED in the model's ``limits``/``notes``, never faked):
  * AP203/AP214 bakes mate constraints (coincident/concentric/distance) INTO the
    world transforms during export — you recover final positions, NEVER the
    parametric "why". GD&T / PMI / tolerances are AP242 + OCP only. Neither is
    reconstructable from the geometry here.
  * Native ``.SLDASM`` / ``.prt`` / ``.SAT`` / ``.CATProduct`` etc. need a licensed
    kernel/reader (OCC's ``importShapes`` reads STEP/IGES/BREP only). Those are
    refused with a specific error (see ``native_cad_error``) — the same real-world
    wall the NIST MTC "Box Assembly" package hit (it shipped ZERO neutral geometry).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import trimesh

from src.parsers.step_mesher import (
    _CURVATURE_PTS,
    _GMSH_LOCK,
    _MAX_SIZE_MM,
    _MESH_RUNGS,
    _MIN_SIZE_MM,
    _OCC_HEAL_OPTS,
    _TARGET_DIAG_SEGMENTS,
    _EmptyMeshError,
    _StepReadError,
    is_step_supported,
)

logger = logging.getLogger("cadverify.assembly_mesher")

_HAS_GMSH = is_step_supported()
try:  # pragma: no cover - import guard mirrors step_mesher
    import gmsh  # noqa: F401
except (ImportError, OSError):  # pragma: no cover
    gmsh = None  # type: ignore


# ── Bounds (env-overridable, always finite) ─────────────────────────────────
def _max_assembly_parts() -> int:
    """Solid ceiling we will TESSELLATE. Past it we still extract positions + the
    tree (cheap, mesh-free) but skip per-part meshes with an honest note."""
    try:
        return max(1, int(os.getenv("MAX_ASSEMBLY_PARTS", "500")))
    except ValueError:
        return 500


def _max_assembly_faces() -> int:
    """Total-triangle ceiling across all per-part meshes (a clean 400 past it,
    mirroring the single-part MAX_TRIANGLES cap)."""
    try:
        return max(1000, int(os.getenv("MAX_ASSEMBLY_FACES", "2000000")))
    except ValueError:
        return 2_000_000


# The container label gmsh's STEP reader wraps the root product in; it is a gmsh
# artifact, not a product node, so we drop a leading occurrence of it.
_GMSH_ROOT_CONTAINER = "Shapes"
# OCC appends a trailing " & & <n>" style/colour code to entity labels; strip it.
_OCC_LABEL_SUFFIX = re.compile(r"\s*&\s*&\s*\d+\s*$")

# Native / proprietary CAD formats OCC's importShapes CANNOT read (need a licensed
# kernel). Mapped to the reader/vendor so the refusal is specific, not generic.
NATIVE_CAD_FORMATS: dict[str, str] = {
    ".sldasm": "SolidWorks assembly",
    ".sldprt": "SolidWorks part",
    ".prt": "Siemens NX / Creo part",
    ".asm": "Creo / Pro-E assembly",
    ".catpart": "CATIA part",
    ".catproduct": "CATIA assembly",
    ".sat": "ACIS (.SAT)",
    ".sab": "ACIS binary (.SAB)",
    ".jt": "Siemens JT",
    ".ipt": "Autodesk Inventor part",
    ".iam": "Autodesk Inventor assembly",
    ".x_t": "Parasolid text",
    ".x_b": "Parasolid binary",
    ".3dm": "Rhino",
    ".f3d": "Fusion 360",
}

# Formats OCC CAN read as an assembly (STL carries no solid tree, so it is not here).
ASSEMBLY_SUFFIXES = (".step", ".stp", ".iges", ".igs")


def is_native_cad_suffix(suffix: str) -> bool:
    return suffix.lower() in NATIVE_CAD_FORMATS


def native_cad_error(suffix: str) -> ValueError:
    """A SPECIFIC, honest error for a native-CAD upload the route maps to 400.

    Names the vendor kernel and points at the neutral-format fix. This is the same
    wall the NIST MTC 'Box Assembly' package hit — it shipped only native NX/
    SolidWorks/ACIS geometry and ZERO STEP/IGES, so nothing here could read it.
    """
    suffix = suffix.lower()
    vendor = NATIVE_CAD_FORMATS.get(suffix, "native CAD")
    return ValueError(
        f"Cannot ingest {suffix} ({vendor}): it is a proprietary/native CAD "
        f"format that requires a licensed reader. Export the assembly to STEP "
        f"(AP203/AP214/AP242) or IGES and upload that instead."
    )


# ── Data model (P2 render + P3 analysis consume this) ───────────────────────
@dataclass
class WorldPose:
    """A sub-part's baked world placement (STEP consumes mate constraints INTO
    these transforms during export — this is final position, never the parametric
    relationship)."""

    bbox_min: list[float]
    bbox_max: list[float]
    bbox_size: list[float]
    centroid: list[float]  # occ.getCenterOfMass
    volume: float          # occ.getMass, mm^3

    def to_dict(self) -> dict:
        return {
            "bbox_min": self.bbox_min,
            "bbox_max": self.bbox_max,
            "bbox_size": self.bbox_size,
            "centroid": self.centroid,
            "volume": self.volume,
        }


@dataclass
class GeometrySummary:
    num_boundary_faces: int   # B-rep faces bounding this solid
    num_triangles: int        # tessellated triangles (0 if mesh skipped)
    num_vertices: int
    bbox_dims: list[float]

    def to_dict(self) -> dict:
        return {
            "num_boundary_faces": self.num_boundary_faces,
            "num_triangles": self.num_triangles,
            "num_vertices": self.num_vertices,
            "bbox_dims": self.bbox_dims,
        }


@dataclass
class PartInstance:
    """One positioned solid (one leaf of the product tree)."""

    id: str                    # stable machine ref; == the GLB node name
    name: str                  # product-definition name, e.g. "bolt"
    occurrence: str            # occurrence/usage name, e.g. "BOLT"
    instance: int              # ::N index disambiguating sibling occurrences
    tree_path: str             # readable path, e.g. "as1/L-BRACKET-ASSEMBLY::1/.../bolt"
    occ_label: str             # raw gmsh label (provenance)
    world: WorldPose
    geometry_summary: GeometrySummary
    mesh_ref: Optional[str]    # id to fetch the per-part mesh (GLB node), None if skipped
    # In-memory only (NOT serialized): the per-part world-coord mesh for GLB export.
    mesh: Optional[trimesh.Trimesh] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "occurrence": self.occurrence,
            "instance": self.instance,
            "tree_path": self.tree_path,
            "occ_label": self.occ_label,
            "world": self.world.to_dict(),
            "geometry_summary": self.geometry_summary.to_dict(),
            "mesh_ref": self.mesh_ref,
        }


@dataclass
class TreeNode:
    """A node in the reconstructed product tree. Internal nodes are sub-assemblies
    (``part_id is None``); leaves link to a ``PartInstance`` via ``part_id``."""

    name: str
    occurrence: str
    instance: int
    children: list["TreeNode"] = field(default_factory=list)
    part_id: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "occurrence": self.occurrence,
            "instance": self.instance,
        }
        if self.part_id is not None:
            d["part_id"] = self.part_id
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class AssemblyModel:
    kind: str                       # "assembly" | "single_part"
    part_count: int
    parts: list[PartInstance]
    tree: TreeNode
    assembly_bbox_min: list[float]
    assembly_bbox_max: list[float]
    assembly_diag: float
    unique_designs: dict[str, int]  # product name -> instance count
    source_suffix: str
    truncated: bool = False
    skipped: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "part_count": self.part_count,
            "parts": [p.to_dict() for p in self.parts],
            "tree": self.tree.to_dict(),
            "assembly": {
                "bbox_min": self.assembly_bbox_min,
                "bbox_max": self.assembly_bbox_max,
                "diagonal": self.assembly_diag,
            },
            "unique_designs": self.unique_designs,
            "source_suffix": self.source_suffix,
            "truncated": self.truncated,
            "skipped": self.skipped,
            "limits": _HONEST_LIMITS,
            "notes": self.notes,
        }


# Surfaced verbatim in every response so a hardcore engineer sees the boundary.
_HONEST_LIMITS = {
    "mate_constraints": (
        "AP203/AP214 bakes mate constraints (coincident/concentric/distance) into "
        "the world transforms at export. Final positions are recovered here; the "
        "parametric relationships are gone and cannot be reconstructed."
    ),
    "gdt_pmi_tolerances": (
        "GD&T / PMI / tolerances are AP242 + a B-rep kernel (OCP) only — not "
        "present in this triangulated extraction."
    ),
    "native_formats": (
        "Native .SLDASM/.prt/.SAT/.CATProduct etc. require a licensed reader and "
        "are refused with a specific error; export to STEP/IGES first."
    ),
    "mesh_level": (
        "This is a triangulated-shell extraction (per-part meshes), NOT B-rep. It "
        "makes each part LOOK and MEASURE right for position/DFM/cost; it does not "
        "assert analytic-surface semantics."
    ),
}


# ── Label -> product-tree parsing ───────────────────────────────────────────
def _strip_suffix(label: str) -> str:
    return _OCC_LABEL_SUFFIX.sub("", label).strip()


def _split_occurrence(token: str) -> tuple[str, int]:
    """``"NUT-BOLT-ASSEMBLY::2"`` -> ``("NUT-BOLT-ASSEMBLY", 2)``; a bare token ->
    instance 1."""
    if "::" in token:
        name, _, idx = token.rpartition("::")
        try:
            return name.strip(), int(idx.strip())
        except ValueError:
            return token.strip(), 1
    return token.strip(), 1


def _parse_label(label: str) -> tuple[str, list[tuple[str, int, str]]]:
    """Parse a gmsh STEP label path into ``(root_name, segments)``.

    OCC/gmsh emits an assembly label as
    ``Shapes / <root> / (<OCCURRENCE::N> / <product>)*`` — each tree level is an
    (occurrence, product) token PAIR, the occurrence carrying the ``::N`` instance
    index. We drop the ``Shapes`` container, take the root, and fold the remainder
    into ``(occurrence_name, instance, product_name)`` segments (one per tree
    level, root excluded). Robust to a missing container, an odd trailing token, or
    absent ``::N`` (defaults instance 1)."""
    tokens = [t.strip() for t in _strip_suffix(label).split("/") if t.strip()]
    if tokens and tokens[0] == _GMSH_ROOT_CONTAINER:
        tokens = tokens[1:]
    if not tokens:
        return "root", []
    root = tokens[0]
    rest = tokens[1:]
    segments: list[tuple[str, int, str]] = []
    i = 0
    while i < len(rest):
        occ_tok = rest[i]
        prod_tok = rest[i + 1] if i + 1 < len(rest) else occ_tok
        occ_name, instance = _split_occurrence(occ_tok)
        segments.append((occ_name, instance, prod_tok))
        i += 2
    return root, segments


def _build_tree(root_name: str, parsed: list[tuple[list[tuple[str, int, str]], str]]) -> TreeNode:
    """Rebuild the nested parent->children product tree from each part's parsed
    segments. ``parsed`` is ``[(segments, part_id), ...]``. Siblings are keyed by
    ``(occurrence, instance)`` so two distinct occurrences of the same product stay
    separate nodes; the deepest segment of each part is its leaf and carries
    ``part_id``."""
    root = TreeNode(name=root_name, occurrence=root_name, instance=1)
    for segments, part_id in parsed:
        node = root
        for depth, (occ, inst, prod) in enumerate(segments):
            match = next(
                (c for c in node.children if c.occurrence == occ and c.instance == inst),
                None,
            )
            if match is None:
                match = TreeNode(name=prod, occurrence=occ, instance=inst)
                node.children.append(match)
            node = match
        if segments:  # leaf links to the part
            node.part_id = part_id
        else:  # a solid directly at the root (degenerate single-node assembly)
            root.part_id = part_id
    return root


# ── Extraction ──────────────────────────────────────────────────────────────
def _configure_mesh(curvature_pts: float, heal: bool) -> None:
    """Apply the SAME pre-import option policy as step_mesher._tessellate_once, so
    the assembly mesh shares the single-part fidelity/robustness story. (MeshSizeMax
    + Mesh.Algorithm are set post-import in _extract_once, once the bbox is known.)"""
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
    if heal:
        for opt in _OCC_HEAL_OPTS:
            gmsh.option.setNumber(opt, 1)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", curvature_pts)


def _solid_metadata(dim: int, tag: int) -> tuple[WorldPose, int, str]:
    """Per-solid world position (bbox + centroid + mass) and boundary-face count,
    computed BEFORE meshing (occ mass/COM are B-rep queries). Returns
    ``(WorldPose, num_boundary_faces, occ_label)``."""
    label = gmsh.model.getEntityName(dim, tag)
    x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(dim, tag)
    try:
        volume = float(gmsh.model.occ.getMass(dim, tag))
    except Exception:
        volume = 0.0
    try:
        cx, cy, cz = gmsh.model.occ.getCenterOfMass(dim, tag)
    except Exception:
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        cz = (z0 + z1) / 2.0
    bnd = gmsh.model.getBoundary([(dim, tag)], oriented=False, recursive=False)
    pose = WorldPose(
        bbox_min=[x0, y0, z0],
        bbox_max=[x1, y1, z1],
        bbox_size=[x1 - x0, y1 - y0, z1 - z0],
        centroid=[float(cx), float(cy), float(cz)],
        volume=volume,
    )
    return pose, len(bnd), label


def _solid_mesh(dim: int, tag: int, node_coords: dict) -> trimesh.Trimesh:
    """Build a world-coord trimesh for ONE solid from the already-generated 2D
    mesh, collecting the triangles of its boundary surfaces (spike-proven path).
    ``process=True`` merges coincident vertices -> per-solid watertightness, the
    same discipline as step_mesher._run_rung."""
    bnd = gmsh.model.getBoundary([(dim, tag)], oriented=False, recursive=False)
    used: dict[int, int] = {}
    tris: list[list[int]] = []
    for (bd, bt) in bnd:
        etypes, _etags, enodes = gmsh.model.mesh.getElements(2, bt)
        for et, conn in zip(etypes, enodes):
            if et != 2:  # gmsh type 2 == 3-node triangle
                continue
            conn = conn.astype(np.int64)
            for i in range(0, len(conn), 3):
                idx = []
                for n in conn[i : i + 3]:
                    n = int(n)
                    if n not in used:
                        used[n] = len(used)
                    idx.append(used[n])
                tris.append(idx)
    if not tris:
        return trimesh.Trimesh()
    verts = np.zeros((len(used), 3), dtype=np.float64)
    for node_tag, local in used.items():
        verts[local] = node_coords[node_tag]
    faces = np.asarray(tris, dtype=np.int64)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=True)


def _extract_once(path: str, algorithm, curvature_pts: float, heal: bool) -> AssemblyModel:
    """One full gmsh cycle: import -> enumerate solids -> per-solid metadata ->
    (mesh + partition, unless over the part cap) -> build tree. MUST hold
    ``_GMSH_LOCK``. Raises ``_StepReadError`` (unreadable, non-retryable) or a
    generic exception (mesh failure, caller advances the ladder)."""
    gmsh.initialize(interruptible=False)
    try:
        _configure_mesh(curvature_pts, heal)
        gmsh.model.add("assembly")
        try:
            gmsh.model.occ.importShapes(path)
            gmsh.model.occ.synchronize()
        except Exception as exc:
            raise _StepReadError(str(exc)) from exc

        vols = gmsh.model.getEntities(3)
        num_solids = len(vols)
        if num_solids == 0:
            raise ValueError("No solid bodies found in the file.")

        gx0, gy0, gz0, gx1, gy1, gz1 = gmsh.model.getBoundingBox(-1, -1)
        diag = ((gx1 - gx0) ** 2 + (gy1 - gy0) ** 2 + (gz1 - gz0) ** 2) ** 0.5

        # Per-solid metadata FIRST (mesh-free B-rep queries), so a metadata-only
        # degradation over the part cap is still fully positioned + treed.
        metas: list[tuple[int, WorldPose, int, str]] = []
        for (dim, tag) in vols:
            pose, nfaces, label = _solid_metadata(dim, tag)
            metas.append((tag, pose, nfaces, label))

        part_cap = _max_assembly_parts()
        notes: list[str] = []
        truncated = False
        skipped: list[dict] = []
        do_mesh = num_solids <= part_cap
        if not do_mesh:
            truncated = True
            notes.append(
                f"{num_solids} solids exceeds MAX_ASSEMBLY_PARTS={part_cap}; "
                f"positions + product tree extracted, per-part meshes skipped."
            )

        node_coords: dict[int, np.ndarray] = {}
        if do_mesh:
            size_max = min(
                max(diag / _TARGET_DIAG_SEGMENTS, _MIN_SIZE_MM), _MAX_SIZE_MM
            )
            gmsh.option.setNumber("Mesh.MeshSizeMax", size_max)
            if algorithm is not None:
                gmsh.option.setNumber("Mesh.Algorithm", algorithm)
            gmsh.model.mesh.generate(2)
            ntags, ncoords, _ = gmsh.model.mesh.getNodes()
            if ncoords.size == 0:
                raise ValueError("Assembly produced no meshable geometry.")
            coords = ncoords.reshape(-1, 3)
            node_coords = {int(t): coords[i] for i, t in enumerate(ntags)}

        parts: list[PartInstance] = []
        parsed_for_tree: list[tuple[list[tuple[str, int, str]], str]] = []
        unique_designs: dict[str, int] = {}
        root_name = "root"
        total_faces = 0
        face_cap = _max_assembly_faces()

        for (tag, pose, nfaces, label) in metas:
            root, segments = _parse_label(label)
            root_name = root
            if segments:
                occ, inst, prod = segments[-1]
            else:
                occ, inst, prod = root, 1, root
            part_id = f"part-{tag}"
            mesh_obj: Optional[trimesh.Trimesh] = None
            ntris = 0
            nverts = 0
            mesh_ref: Optional[str] = None
            if do_mesh:
                mesh_obj = _solid_mesh(3, tag, node_coords)
                ntris = int(len(mesh_obj.faces))
                nverts = int(len(mesh_obj.vertices))
                total_faces += ntris
                if total_faces > face_cap:
                    raise ValueError(
                        f"Assembly tessellation exceeded {face_cap:,} triangles "
                        f"(MAX_ASSEMBLY_FACES). Reduce the assembly or raise the cap."
                    )
                if ntris > 0:
                    mesh_ref = part_id

            readable = _strip_suffix(label)
            if readable.startswith(_GMSH_ROOT_CONTAINER + "/"):
                readable = readable[len(_GMSH_ROOT_CONTAINER) + 1 :]
            parts.append(
                PartInstance(
                    id=part_id,
                    name=prod,
                    occurrence=occ,
                    instance=inst,
                    tree_path=readable,
                    occ_label=label,
                    world=pose,
                    geometry_summary=GeometrySummary(
                        num_boundary_faces=nfaces,
                        num_triangles=ntris,
                        num_vertices=nverts,
                        bbox_dims=pose.bbox_size,
                    ),
                    mesh_ref=mesh_ref,
                    mesh=mesh_obj,
                )
            )
            parsed_for_tree.append((segments, part_id))
            unique_designs[prod] = unique_designs.get(prod, 0) + 1
            if do_mesh and (mesh_obj is None or len(mesh_obj.faces) == 0):
                skipped.append({"id": part_id, "reason": "empty per-part mesh"})

        tree = _build_tree(root_name, parsed_for_tree)
        kind = "single_part" if num_solids == 1 else "assembly"
        if kind == "single_part":
            notes.append(
                "Exactly one solid: this is a single part, not an assembly. Use "
                "POST /api/v1/validate for canonical single-part DFM + cost."
            )
        return AssemblyModel(
            kind=kind,
            part_count=num_solids,
            parts=parts,
            tree=tree,
            assembly_bbox_min=[gx0, gy0, gz0],
            assembly_bbox_max=[gx1, gy1, gz1],
            assembly_diag=diag,
            unique_designs=unique_designs,
            source_suffix=Path(path).suffix.lower(),
            truncated=truncated,
            skipped=skipped,
            notes=notes,
        )
    finally:
        gmsh.finalize()


def _extract_with_ladder(path: str) -> AssemblyModel:
    """Assembly extraction with the SAME retry ladder as step_mesher._mesh_step_
    file: rung 0 (primary, byte-identical option set) first, then MeshAdapt-uniform,
    then +OCC-heal. Serialized on ``_GMSH_LOCK``."""
    last_msg = ""
    for idx, (name, algo, curv, heal) in enumerate(_MESH_RUNGS):
        try:
            with _GMSH_LOCK:
                model = _extract_once(path, algo, curv, heal)
        except _StepReadError as exc:
            raise ValueError(
                "Could not read STEP/IGES geometry (not a valid/supported file)."
            ) from exc
        except Exception as exc:  # this rung failed to MESH a readable assembly
            last_msg = str(exc)
            nxt = _MESH_RUNGS[idx + 1][0] if idx + 1 < len(_MESH_RUNGS) else None
            if nxt is not None:
                logger.info(
                    "assembly mesher rung '%s' failed (%s); retrying with '%s'",
                    name, last_msg[:120], nxt,
                )
            continue
        if idx > 0:
            logger.info(
                "assembly mesher recovered on retry rung '%s' (parts=%d)",
                name, model.part_count,
            )
        return model
    raise ValueError(
        f"Could not tessellate this assembly [{last_msg[:160]}] "
        f"(all {len(_MESH_RUNGS)} mesh strategies failed)."
    )


def extract_assembly_from_bytes(data: bytes, filename: str = "upload.step") -> AssemblyModel:
    """Parse STEP/IGES bytes -> ``AssemblyModel``. The public entry (picklable for
    the process pool). Mirrors step_mesher's temp-file discipline (0o600, guaranteed
    unlink). Raises ``ValueError`` (route -> 400) on any read/mesh failure; never
    leaks gmsh internals."""
    if not _HAS_GMSH:
        raise RuntimeError("gmsh not installed")
    suffix = Path(filename).suffix.lower()
    if is_native_cad_suffix(suffix):
        raise native_cad_error(suffix)
    if suffix not in ASSEMBLY_SUFFIXES:
        raise ValueError(
            f"Assembly ingestion needs a STEP/IGES file (got {suffix or 'no suffix'}). "
            f"STL carries no assembly structure — upload .step/.stp/.iges/.igs."
        )
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w+b")
    try:
        os.chmod(tmp.name, 0o600)
        tmp.write(data)
        tmp.flush()
        tmp.close()
        return _extract_with_ladder(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass


# ── GLB export (P2 render) ──────────────────────────────────────────────────
def assembly_to_glb(model: AssemblyModel, target_faces: int = 0) -> bytes:
    """Export ONE GLB with a named node per part, world transforms preserved (the
    per-part meshes are already in world coordinates). ``mesh_ref``/node name ties
    each GLB node back to its JSON ``PartInstance``. Optionally decimate parts
    proportionally to ``target_faces`` (reusing the engine's ``_decimate_to``) so a
    heavy assembly still fits a WebGL budget."""
    from src.analysis.context import _decimate_to

    meshed = [p for p in model.parts if p.mesh is not None and len(p.mesh.faces) > 0]
    if not meshed:
        raise ValueError("No per-part meshes to export (metadata-only assembly).")
    total = sum(len(p.mesh.faces) for p in meshed)
    scene = trimesh.Scene()
    for p in meshed:
        m = p.mesh
        if target_faces and total > target_faces:
            share = max(500, int(target_faces * len(m.faces) / total))
            if len(m.faces) > share:
                reduced, _strategy = _decimate_to(m, share)
                if reduced is not None and 0 < len(reduced.faces) < len(m.faces):
                    m = reduced
        scene.add_geometry(m, geom_name=p.id, node_name=p.id)
    return bytes(scene.export(file_type="glb"))
