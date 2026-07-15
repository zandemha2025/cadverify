"""Bounded reader for STEP AP242 embedded tessellated geometry.

Some valid AP242 files carry ``TESSELLATED_SHAPE_REPRESENTATION`` geometry
instead of a boundary representation. OpenCASCADE/gmsh cannot import that
branch, but the file already contains the exact coordinates and triangle
strips/fans needed by the downstream trimesh-based DFM and cost engine.

This is deliberately a narrow, non-evaluating Part 21 reader. It recognizes
only the AP242 tessellation entities needed to construct a mesh, enforces hard
record/scalar/triangle bounds, traverses only solids/shells referenced by a
tessellated shape representation, and ignores PMI/presentation entities.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, cast

import numpy as np
import trimesh


_AP242 = b"AP242_MANAGED_MODEL_BASED_3D_ENGINEERING"
_TESSELLATED_REP = b"TESSELLATED_SHAPE_REPRESENTATION"
_FACE_MARKERS = (b"TRIANGULATED_FACE", b"COMPLEX_TRIANGULATED_FACE")

_ENTITY_START = re.compile(rb"#\s*(\d+)\s*=\s*([A-Z][A-Z0-9_]*)\s*\(")
_REF = re.compile(r"#\s*(\d+)")
_BYTE_REF = re.compile(rb"#\s*(\d+)")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?")
_SI_METRE_UNIT = re.compile(
    r"SI_UNIT\s*\(\s*(\$|\.[A-Z_]+\.)\s*,\s*\.METRE\.\s*\)",
    re.IGNORECASE,
)
_CONVERSION_UNIT = re.compile(
    r"CONVERSION_BASED_UNIT\s*\(\s*'([^']+)'\s*,\s*#\s*(\d+)\s*\)",
    re.IGNORECASE,
)
_LENGTH_MEASURE = re.compile(
    rf"LENGTH_MEASURE\s*\(\s*({_NUMBER.pattern})\s*\)\s*,\s*#\s*(\d+)",
    re.IGNORECASE,
)

_WANTED_TYPES = {
    "COORDINATES_LIST",
    "TRIANGULATED_FACE",
    "COMPLEX_TRIANGULATED_FACE",
    "TESSELLATED_SOLID",
    "TESSELLATED_SHELL",
    "TESSELLATED_SHAPE_REPRESENTATION",
}

MAX_ENTITY_RECORDS = 250_000
MAX_NESTING = 8
MAX_NUMERIC_SCALARS = 12_000_000
MAX_COORDINATE_POINTS = 3_000_000
MAX_TRIANGLES = 5_000_000
MAX_UNIT_RECORD_BYTES = 64 * 1024

_SI_PREFIX_TO_METRES = {
    "$": 1.0,
    ".EXA.": 1e18,
    ".PETA.": 1e15,
    ".TERA.": 1e12,
    ".GIGA.": 1e9,
    ".MEGA.": 1e6,
    ".KILO.": 1e3,
    ".HECTO.": 1e2,
    ".DECA.": 1e1,
    ".DECI.": 1e-1,
    ".CENTI.": 1e-2,
    ".MILLI.": 1e-3,
    ".MICRO.": 1e-6,
    ".NANO.": 1e-9,
    ".PICO.": 1e-12,
    ".FEMTO.": 1e-15,
    ".ATTO.": 1e-18,
}

_NAMED_LENGTH_TO_MM = {
    "INCH": 25.4,
    "INCHES": 25.4,
    "FOOT": 304.8,
    "FEET": 304.8,
    "MIL": 0.0254,
    "THOU": 0.0254,
}


class AP242TessellationError(ValueError):
    """The file declares AP242 tessellated geometry but it is unsafe/invalid."""


@dataclass(frozen=True)
class _Entity:
    kind: str
    arguments: str


def is_ap242_tessellated(data: bytes) -> bool:
    """Cheap, data-specific capability probe before native CAD import."""
    # Part 21 does not require representation entities to occur near the
    # header. Inspect the bounded upload in full so a late tessellation is not
    # misrouted into a native importer that cannot consume it.
    head = data.upper()
    return (
        _AP242 in head
        and _TESSELLATED_REP in head
        and any(marker in head for marker in _FACE_MARKERS)
    )


def _matching_paren(data: bytes, open_index: int) -> int:
    depth = 0
    quoted = False
    index = open_index
    while index < len(data):
        char = data[index]
        if quoted:
            if char == 39:  # apostrophe; doubled apostrophe escapes itself
                if index + 1 < len(data) and data[index + 1] == 39:
                    index += 2
                    continue
                quoted = False
        elif char == 39:
            quoted = True
        elif char == 40:  # (
            depth += 1
            if depth > MAX_NESTING + 4:
                raise AP242TessellationError("STEP entity nesting is too deep.")
        elif char == 41:  # )
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                break
        index += 1
    raise AP242TessellationError("STEP entity has an unterminated argument list.")


def _entities(data: bytes) -> dict[int, _Entity]:
    found: dict[int, _Entity] = {}
    position = 0
    records = 0
    while match := _ENTITY_START.search(data, position):
        records += 1
        if records > MAX_ENTITY_RECORDS:
            raise AP242TessellationError("STEP file contains too many entity records.")
        entity_id = int(match.group(1))
        kind = match.group(2).decode("ascii")
        open_index = match.end() - 1
        close_index = _matching_paren(data, open_index)
        if kind in _WANTED_TYPES:
            try:
                arguments = data[open_index + 1 : close_index].decode("ascii")
            except UnicodeDecodeError as exc:
                raise AP242TessellationError(
                    "AP242 tessellated geometry must use Part 21 ASCII syntax."
                ) from exc
            found[entity_id] = _Entity(kind=kind, arguments=arguments)
        position = close_index + 1
    return found


def _split_arguments(value: str) -> list[str]:
    out: list[str] = []
    start = 0
    depth = 0
    quoted = False
    index = 0
    while index < len(value):
        char = value[index]
        if quoted:
            if char == "'":
                if index + 1 < len(value) and value[index + 1] == "'":
                    index += 2
                    continue
                quoted = False
        elif char == "'":
            quoted = True
        elif char == "(":
            depth += 1
            if depth > MAX_NESTING:
                raise AP242TessellationError("STEP list nesting is too deep.")
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise AP242TessellationError("STEP list parentheses are unbalanced.")
        elif char == "," and depth == 0:
            out.append(value[start:index].strip())
            start = index + 1
        index += 1
    if quoted or depth != 0:
        raise AP242TessellationError("STEP entity arguments are malformed.")
    out.append(value[start:].strip())
    return out


class _NumericListParser:
    def __init__(self, text: str):
        self.text = text
        self.index = 0
        self.scalars = 0

    def parse(self):
        value = self._value(0)
        self._space()
        if self.index != len(self.text):
            raise AP242TessellationError("Unexpected token in STEP numeric list.")
        return value

    def _space(self) -> None:
        while self.index < len(self.text) and self.text[self.index].isspace():
            self.index += 1

    def _value(self, depth: int):
        self._space()
        if depth > MAX_NESTING:
            raise AP242TessellationError("STEP numeric list nesting is too deep.")
        if self.index < len(self.text) and self.text[self.index] == "(":
            self.index += 1
            values = []
            self._space()
            if self.index < len(self.text) and self.text[self.index] == ")":
                self.index += 1
                return values
            while True:
                values.append(self._value(depth + 1))
                self._space()
                if self.index >= len(self.text):
                    raise AP242TessellationError("Unterminated STEP numeric list.")
                token = self.text[self.index]
                self.index += 1
                if token == ")":
                    return values
                if token != ",":
                    raise AP242TessellationError("Malformed STEP numeric list.")

        match = _NUMBER.match(self.text, self.index)
        if not match:
            raise AP242TessellationError("STEP tessellation contains a non-numeric index or coordinate.")
        token = match.group(0)
        self.index = match.end()
        self.scalars += 1
        if self.scalars > MAX_NUMERIC_SCALARS:
            raise AP242TessellationError("STEP tessellation contains too many numeric values.")
        if any(char in token for char in ".Ee"):
            value = float(token)
            if not math.isfinite(value):
                raise AP242TessellationError("STEP tessellation contains a non-finite coordinate.")
            return value
        return int(token)


def _numeric_list(text: str):
    return _NumericListParser(text).parse()


def _references(text: str) -> list[int]:
    return [int(item) for item in _REF.findall(text)]


def _single_reference(text: str) -> int:
    refs = _references(text)
    if len(refs) != 1:
        raise AP242TessellationError("STEP tessellation has an invalid entity reference.")
    return refs[0]


def _raw_entity_record(data: bytes, entity_id: int) -> str:
    """Return one complete Part 21 entity assignment without evaluating it."""
    match = re.search(rb"#\s*" + str(entity_id).encode("ascii") + rb"\s*=", data)
    if match is None:
        raise AP242TessellationError("STEP unit context references a missing entity.")
    start = match.end()
    index = start
    depth = 0
    quoted = False
    while index < len(data) and index - start <= MAX_UNIT_RECORD_BYTES:
        char = data[index]
        if quoted:
            if char == 39:
                if index + 1 < len(data) and data[index + 1] == 39:
                    index += 2
                    continue
                quoted = False
        elif char == 39:
            quoted = True
        elif char == 40:
            depth += 1
        elif char == 41:
            depth -= 1
            if depth < 0:
                raise AP242TessellationError("STEP unit entity is malformed.")
        elif char == 59 and depth == 0:
            try:
                return data[start:index].decode("ascii")
            except UnicodeDecodeError as exc:
                raise AP242TessellationError(
                    "STEP unit declarations must use Part 21 ASCII syntax."
                ) from exc
        index += 1
    raise AP242TessellationError("STEP unit entity is missing or exceeds its size bound.")


def _unit_record_scale_to_mm(
    data: bytes,
    record: str,
    *,
    seen: frozenset[int] = frozenset(),
) -> float:
    si_match = _SI_METRE_UNIT.search(record)
    if si_match:
        prefix = si_match.group(1).upper()
        metres = _SI_PREFIX_TO_METRES.get(prefix)
        if metres is None:
            raise AP242TessellationError(f"Unsupported SI length prefix {prefix}.")
        return metres * 1000.0

    conversion = _CONVERSION_UNIT.search(record)
    if conversion:
        name = conversion.group(1).strip().upper()
        known_scale = _NAMED_LENGTH_TO_MM.get(name)
        if known_scale is not None:
            return known_scale

        measure_id = int(conversion.group(2))
        if measure_id in seen or len(seen) >= 4:
            raise AP242TessellationError("STEP converted length unit contains a reference cycle.")
        measure_record = _raw_entity_record(data, measure_id)
        measure = _LENGTH_MEASURE.search(measure_record)
        if measure is None:
            raise AP242TessellationError(
                f"Unsupported converted STEP length unit {name or '(unnamed)'}."
            )
        factor = float(measure.group(1))
        base_id = int(measure.group(2))
        if not math.isfinite(factor) or factor <= 0:
            raise AP242TessellationError("STEP converted length unit has an invalid factor.")
        base_record = _raw_entity_record(data, base_id)
        return factor * _unit_record_scale_to_mm(
            data,
            base_record,
            seen=seen | {measure_id, base_id},
        )

    raise AP242TessellationError("STEP length unit is unsupported or incomplete.")


def _length_scale_to_mm(data: bytes, entities: dict[int, _Entity]) -> float:
    """Resolve each tessellated representation's active length unit to mm."""
    context_ids: list[int] = []
    for entity in entities.values():
        if entity.kind != "TESSELLATED_SHAPE_REPRESENTATION":
            continue
        args = _split_arguments(entity.arguments)
        if len(args) < 3:
            raise AP242TessellationError("Tessellated shape representation has no context.")
        context_ids.append(_single_reference(args[2]))

    scales: list[float] = []
    for context_id in dict.fromkeys(context_ids):
        context = _raw_entity_record(data, context_id)
        marker = re.search(
            r"GLOBAL_UNIT_ASSIGNED_CONTEXT\s*\(\s*\(([^)]*)\)\s*\)",
            context,
            re.IGNORECASE,
        )
        if marker is None:
            raise AP242TessellationError(
                "Tessellated shape representation has no global unit assignment."
            )
        length_records = []
        for raw_id in _BYTE_REF.findall(marker.group(1).encode("ascii")):
            unit_record = _raw_entity_record(data, int(raw_id))
            if "LENGTH_UNIT" in unit_record.upper():
                length_records.append(unit_record)
        if len(length_records) != 1:
            raise AP242TessellationError(
                "STEP representation must declare exactly one active length unit."
            )
        scales.append(_unit_record_scale_to_mm(data, length_records[0]))

    if not scales:
        raise AP242TessellationError("AP242 tessellation has no dimensional context.")
    if any(not math.isclose(scale, scales[0], rel_tol=0, abs_tol=1e-12) for scale in scales[1:]):
        raise AP242TessellationError(
            "Multiple tessellated representations use incompatible length units."
        )
    return scales[0]


def _face_ids(entities: dict[int, _Entity]) -> list[int]:
    shape_items: list[int] = []
    for entity in entities.values():
        if entity.kind != "TESSELLATED_SHAPE_REPRESENTATION":
            continue
        args = _split_arguments(entity.arguments)
        if len(args) < 2:
            raise AP242TessellationError("Tessellated shape representation is incomplete.")
        shape_items.extend(_references(args[1]))

    pending = shape_items or [
        entity_id
        for entity_id, entity in entities.items()
        if entity.kind in {"TESSELLATED_SOLID", "TESSELLATED_SHELL"}
    ]
    face_ids: list[int] = []
    seen: set[int] = set()
    while pending:
        item_id = pending.pop()
        if item_id in seen:
            continue
        seen.add(item_id)
        item = entities.get(item_id)
        if item is None:
            continue
        if item.kind in {"TRIANGULATED_FACE", "COMPLEX_TRIANGULATED_FACE"}:
            face_ids.append(item_id)
            continue
        if item.kind not in {"TESSELLATED_SOLID", "TESSELLATED_SHELL"}:
            continue
        args = _split_arguments(item.arguments)
        if len(args) < 2:
            raise AP242TessellationError("Tessellated solid or shell is incomplete.")
        pending.extend(_references(args[1]))
    if not face_ids:
        raise AP242TessellationError("AP242 tessellated representation contains no faces.")
    return list(dict.fromkeys(face_ids))


def _triangles_from_strip(strip: list[int]) -> Iterable[tuple[int, int, int]]:
    if len(strip) < 3:
        raise AP242TessellationError("Triangle strip contains fewer than three points.")
    for index in range(len(strip) - 2):
        a, b, c = strip[index : index + 3]
        yield (a, b, c) if index % 2 == 0 else (b, a, c)


def _triangles_from_fan(fan: list[int]) -> Iterable[tuple[int, int, int]]:
    if len(fan) < 3:
        raise AP242TessellationError("Triangle fan contains fewer than three points.")
    root = fan[0]
    for index in range(1, len(fan) - 1):
        yield root, fan[index], fan[index + 1]


def parse_ap242_tessellated(data: bytes) -> trimesh.Trimesh:
    """Parse one AP242 tessellated solid/shell into a processed trimesh mesh."""
    if not is_ap242_tessellated(data):
        raise AP242TessellationError("STEP file does not declare AP242 tessellated geometry.")
    entities = _entities(data)
    selected_faces = _face_ids(entities)
    length_scale_to_mm = _length_scale_to_mm(data, entities)

    coordinate_cache: dict[int, list[list[float]]] = {}
    vertices: list[list[float]] = []
    vertex_map: dict[tuple[int, int], int] = {}
    faces: list[tuple[int, int, int]] = []

    def coordinates(entity_id: int) -> list[list[float]]:
        if entity_id in coordinate_cache:
            return coordinate_cache[entity_id]
        entity = entities.get(entity_id)
        if entity is None or entity.kind != "COORDINATES_LIST":
            raise AP242TessellationError("Tessellated face references a missing coordinates list.")
        args = _split_arguments(entity.arguments)
        if len(args) != 3:
            raise AP242TessellationError("Coordinates list has an unsupported attribute shape.")
        try:
            declared_count = int(args[1])
        except ValueError as exc:
            raise AP242TessellationError("Coordinates list has an invalid point count.") from exc
        points = _numeric_list(args[2])
        if not isinstance(points, list) or declared_count != len(points):
            raise AP242TessellationError("Coordinates list point count does not match its payload.")
        if declared_count <= 0 or declared_count > MAX_COORDINATE_POINTS:
            raise AP242TessellationError("Coordinates list exceeds the supported point bound.")
        normalized: list[list[float]] = []
        for point in points:
            if not isinstance(point, list) or len(point) != 3:
                raise AP242TessellationError("Each tessellated coordinate must contain X, Y, and Z.")
            xyz = [float(value) for value in point]
            if not all(math.isfinite(value) for value in xyz):
                raise AP242TessellationError("STEP tessellation contains a non-finite coordinate.")
            normalized.append([value * length_scale_to_mm for value in xyz])
        coordinate_cache[entity_id] = normalized
        return normalized

    def global_vertex(coordinate_id: int, one_based_index: int) -> int:
        points = coordinates(coordinate_id)
        if one_based_index < 1 or one_based_index > len(points):
            raise AP242TessellationError("Triangle index is outside its coordinates list.")
        key = (coordinate_id, one_based_index)
        if key not in vertex_map:
            vertex_map[key] = len(vertices)
            vertices.append(points[one_based_index - 1])
        return vertex_map[key]

    for face_id in selected_faces:
        entity = entities.get(face_id)
        if entity is None or entity.kind not in {"TRIANGULATED_FACE", "COMPLEX_TRIANGULATED_FACE"}:
            raise AP242TessellationError("Tessellated solid references a missing triangular face.")
        args = _split_arguments(entity.arguments)
        expected_args = 7 if entity.kind == "TRIANGULATED_FACE" else 8
        if len(args) != expected_args:
            raise AP242TessellationError(f"{entity.kind} has an unsupported attribute shape.")
        coordinate_id = _single_reference(args[1])
        try:
            pnmax = int(args[2])
        except ValueError as exc:
            raise AP242TessellationError("Tessellated face has an invalid point count.") from exc
        pnindex_value = _numeric_list(args[5])
        if not isinstance(pnindex_value, list) or not all(
            isinstance(value, int) for value in pnindex_value
        ):
            raise AP242TessellationError("Tessellated face pnindex must be an integer list.")
        pnindex = cast(list[int], pnindex_value)
        if pnindex and len(pnindex) != pnmax:
            raise AP242TessellationError("Tessellated face pnindex length does not equal pnmax.")

        def resolve(local_index: int) -> int:
            if local_index < 1 or local_index > pnmax:
                raise AP242TessellationError("Triangle index is outside the face point range.")
            coordinate_index = pnindex[local_index - 1] if pnindex else local_index
            return global_vertex(coordinate_id, coordinate_index)

        raw_triangles: Iterable[tuple[int, int, int]]
        if entity.kind == "TRIANGULATED_FACE":
            triangles = _numeric_list(args[6])
            if not isinstance(triangles, list) or not triangles:
                raise AP242TessellationError("Triangulated face triangle payload is invalid.")
            expanded_triangles: list[tuple[int, int, int]] = []
            for item in triangles:
                if (
                    not isinstance(item, list)
                    or len(item) != 3
                    or not all(isinstance(value, int) for value in item)
                ):
                    raise AP242TessellationError(
                        "Each triangulated face entry must contain three integer indices."
                    )
                expanded_triangles.append((item[0], item[1], item[2]))
            raw_triangles = expanded_triangles
        else:
            strips = _numeric_list(args[6])
            fans = _numeric_list(args[7])
            if not isinstance(strips, list) or not isinstance(fans, list):
                raise AP242TessellationError("Triangle strip/fan payload is invalid.")
            expanded: list[tuple[int, int, int]] = []
            for strip in strips:
                if not isinstance(strip, list) or not all(isinstance(value, int) for value in strip):
                    raise AP242TessellationError("Triangle strip must be an integer list.")
                expanded.extend(_triangles_from_strip(strip))
            for fan in fans:
                if not isinstance(fan, list) or not all(isinstance(value, int) for value in fan):
                    raise AP242TessellationError("Triangle fan must be an integer list.")
                expanded.extend(_triangles_from_fan(fan))
            if not expanded:
                raise AP242TessellationError("Complex triangulated face contains no triangles.")
            raw_triangles = expanded

        for triangle in raw_triangles:
            if not all(isinstance(value, int) for value in triangle):
                raise AP242TessellationError("Triangle indices must be integers.")
            resolved = (
                resolve(triangle[0]),
                resolve(triangle[1]),
                resolve(triangle[2]),
            )
            if len(set(resolved)) != 3:
                continue
            faces.append(resolved)
            if len(faces) > MAX_TRIANGLES:
                raise AP242TessellationError("AP242 tessellation exceeds the supported triangle bound.")

    if not vertices or not faces:
        raise AP242TessellationError("AP242 tessellated geometry is empty.")
    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=True,
        validate=True,
    )
    mesh.remove_unreferenced_vertices()
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise AP242TessellationError("AP242 tessellated geometry produced an empty mesh.")
    if mesh.is_watertight:
        mesh.fix_normals()
    return mesh
