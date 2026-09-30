"""BOM / assembly hierarchy service (customer-context Slice 3 — the ROLLUP).

Today a part's annual volume comes from a single FLAT declared field. This service
persists the customer's REAL multi-level tree (``bom_edges``) and rolls the total
up it, so the founder's line becomes literally true: a door handle (part) belongs
to a door assembly (environment) belongs to a vehicle (total), and

    annual_volume = qty_per_parent x ... x parents_per_vehicle x vehicles_per_year

is resolved edge-by-edge from the real hierarchy instead of guessed.

Two honest ingest sources:
  * an extracted STEP/IGES assembly (``assembly_mesher.AssemblyModel``) — edges are
    DERIVED from the real product tree, ``qty_per_parent`` the MEASURED instance
    count of a child design under one parent occurrence (``source='assembly_step'``).
  * a customer ``parent_ref,child_ref,qty_per_parent`` BOM (CSV/JSON) — USER-declared
    structure, per-row validated, bad rows reported + skipped (``source='bom_csv'``).

HONESTY RAILS (non-negotiable):
  * An edge is only ever a REAL relationship (parsed or declared). We NEVER
    fabricate a parent/child link or a quantity.
  * A part with NO tree has NO rollup — ``rolled_up_multiplier`` returns ``None`` and
    the caller falls back to the flat declared volume, labelled ``'declared'``
    (byte-identical to the pre-Slice-3 path).
  * A shared component (a nut under two sub-assemblies) is a real DAG:
    ``rolled_up_multiplier`` SUMS the part's count over every path to the root — it
    never silently drops a path. Cycles are rejected before replacement; legacy
    cycles have no rollup and return an explicit error on the ancestry endpoint.
  * Org-scoped throughout (``WHERE org_id = caller``, FK CASCADE) — a caller can
    never read another org's edges.

The pure helpers (``edges_from_assembly``, ``parse_bom_csv/json``, ``ancestry``,
``rolled_up_multiplier``, ``resolve_annual_volume``) are unit-tested without a DB.
The DB adapters are thin, idempotent per ``(org_id, assembly_key)``, and do NOT
commit — the caller owns the transaction (mirrors the sibling services).
"""
from __future__ import annotations

import csv
import io
import json
from collections import deque
from graphlib import CycleError, TopologicalSorter
from typing import Any, Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import BomEdge

SOURCE_ASSEMBLY_STEP = "assembly_step"
SOURCE_BOM_CSV = "bom_csv"

# Defensive cap on a single BOM ingest (a BOM is text — a small cap is honest).
BOM_MAX_ROWS = 20000
# Bound the ancestry preview, independently of the exact rollup calculation.
_MAX_PATHS = 100000
_MAX_PATH_NODES = 100000
_MAX_SAFE_COUNT = 9_007_199_254_740_991  # Exact JSON integers in the browser.

# ── BOM CSV/JSON contract (mirrors manifest_service's CSV style) ──────────────
# Required: parent_ref, child_ref. Optional: qty_per_parent (default 1),
# child_name. A missing optional is fine; qty must be a positive integer when
# present. A malformed row is reported + skipped — the batch survives.
BOM_REQUIRED_COLUMNS = ("parent_ref", "child_ref")
BOM_OPTIONAL_COLUMNS = ("qty_per_parent", "child_name")
BOM_HEADER = ",".join(BOM_REQUIRED_COLUMNS + BOM_OPTIONAL_COLUMNS)


def _example_bom_row() -> str:
    return "door-assembly,handle,2,Door handle"


def _clean(v: Any) -> str:
    return ("" if v is None else str(v)).strip()


# ---------------------------------------------------------------------------
# Derive edges from a parsed assembly's product tree (pure — no DB)
# ---------------------------------------------------------------------------
def edges_from_assembly(model: Any) -> list[dict]:
    """Derive the DESIGN-collapsed parent->child edges of an ``AssemblyModel``.

    Walks the extracted product tree (``model.tree``: nested ``TreeNode``s keyed by
    ``(occurrence, instance)``) and, for every internal node, groups its children by
    DESIGN name and emits one edge ``parent_design -> child_design`` whose
    ``qty_per_parent`` is the MEASURED count of that child design under one parent
    occurrence. Collapsing by design (not by instance) is what makes the rollup
    meaningful: 3 NUT-BOLT-ASSEMBLY per L-BRACKET-ASSEMBLY x 2 L-BRACKET-ASSEMBLY
    per vehicle x 1 bolt per NUT-BOLT-ASSEMBLY = 6 bolts/vehicle — the real total.

    ``child_ref``/``parent_ref`` are the design (product) names; a design appearing
    under two different parents yields two edges (a real DAG, e.g. a nut shared by
    ROD-ASSEMBLY and NUT-BOLT-ASSEMBLY). Depth is the child's depth below the root
    (root's direct children are depth 1). Returns ``[]`` for a degenerate
    single-node tree (nothing to roll up). Nothing is fabricated — every edge and
    quantity is read from the parsed geometry.
    """
    tree = getattr(model, "tree", None)
    if tree is None:
        return []

    # (parent_design, child_design) -> {qty_per_occurrence, depth, child_name}.
    edges: dict[tuple[str, str], dict] = {}
    # ponytail: BOM keys are names; reject conflicting structures until stable
    # product IDs are carried through the parser and customer-context mapping.
    structures: dict[str, dict[str, int]] = {}

    def _design(node: Any) -> str:
        # Prefer the product/design name; fall back to occurrence for a bare node.
        return (getattr(node, "name", None) or getattr(node, "occurrence", None) or "").strip()

    def walk(node: Any, depth: int) -> None:
        children = getattr(node, "children", None) or []
        parent_design = _design(node)
        # Count child instances by design under THIS single parent occurrence.
        by_design: dict[str, int] = {}
        for c in children:
            cd = _design(c)
            by_design[cd] = by_design.get(cd, 0) + 1
        if structures.setdefault(parent_design, by_design) != by_design:
            raise ValueError(
                f"Assembly name {parent_design[:120]!r} has different child structures. "
                "Give distinct designs unique names before importing their BOM."
            )
        for cd, qty in by_design.items():
            edges.setdefault((parent_design, cd), {
                "qty_per_parent": qty,
                "depth": depth + 1,
                "child_name": cd or None,
            })
        for c in children:
            walk(c, depth + 1)

    walk(tree, 0)

    out: list[dict] = []
    for (parent_ref, child_ref), meta in edges.items():
        out.append({
            "parent_ref": parent_ref,
            "child_ref": child_ref,
            "child_name": meta["child_name"],
            "qty_per_parent": int(meta["qty_per_parent"]),
            "depth": int(meta["depth"]),
        })
    return out


# ---------------------------------------------------------------------------
# Parse a customer BOM (CSV / JSON) into edge rows (pure — no DB)
# ---------------------------------------------------------------------------
def _coerce_row(parent: str, child: str, qty_raw: str, child_name: str) -> tuple[Optional[dict], Optional[str]]:
    """Validate one declared BOM triple → (row, error). qty defaults to 1; a
    non-integer or non-positive qty is a reported error (never coerced). A row
    whose parent == child is a self-loop and is rejected (a part can't contain
    itself)."""
    errs: list[str] = []
    if not parent:
        errs.append("missing parent_ref")
    if not child:
        errs.append("missing child_ref")
    if parent and child and parent == child:
        errs.append(f"self-referential edge (parent == child == '{parent}')")
    qty = 1
    if qty_raw:
        try:
            qty = int(qty_raw)
        except ValueError:
            errs.append(f"qty_per_parent not an integer ('{qty_raw}')")
        else:
            if qty <= 0:
                errs.append(f"qty_per_parent must be > 0 (got {qty})")
            elif qty > 2_147_483_647:
                errs.append("qty_per_parent must be at most 2147483647")
    if errs:
        return None, "; ".join(errs)
    return {
        "parent_ref": parent,
        "child_ref": child,
        "child_name": child_name or None,
        "qty_per_parent": qty,
    }, None


def parse_bom_csv(text: str) -> tuple[list[dict], list[dict]]:
    """Parse a BOM CSV into ``(rows, errors)`` — STRICT and HONEST.

    Contract (``BOM_HEADER``): required ``parent_ref,child_ref``; optional
    ``qty_per_parent`` (default 1), ``child_name``. Mirrors
    ``manifest_service.parse_manifest_csv``: BOM-tolerant header, blank lines
    skipped, a malformed HEADER (missing required column / empty file) yields
    ``([], [one error])`` rather than guessing, and a malformed ROW is reported +
    skipped so the batch survives.
    """
    rows: list[dict] = []
    errors: list[dict] = []
    if not text or not text.strip():
        return rows, [{"line": 0, "reason": "empty CSV (no header, no rows)"}]

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return rows, [{"line": 0, "reason": "empty CSV (no header, no rows)"}]

    if header and header[0].startswith("﻿"):
        header[0] = header[0][1:]
    cols = [_clean(h).lower() for h in header]
    col_index = {name: i for i, name in enumerate(cols)}
    missing = [c for c in BOM_REQUIRED_COLUMNS if c not in col_index]
    if missing:
        return rows, [{
            "line": 1,
            "reason": (
                f"header missing required column(s): {', '.join(missing)}. "
                f"Expected header: {BOM_HEADER}"
            ),
        }]

    def cell(record: list, name: str) -> str:
        i = col_index.get(name)
        if i is None or i >= len(record):
            return ""
        return _clean(record[i])

    for offset, record in enumerate(reader):
        line = offset + 2  # header is line 1
        if not any(_clean(c) for c in record):
            continue
        row, err = _coerce_row(
            cell(record, "parent_ref"),
            cell(record, "child_ref"),
            cell(record, "qty_per_parent"),
            cell(record, "child_name"),
        )
        if err:
            errors.append({"line": line, "reason": err})
            continue
        rows.append(row)
    return rows, errors


def parse_bom_json(text: str) -> tuple[list[dict], list[dict]]:
    """Parse a BOM from JSON into ``(rows, errors)``. Accepts a top-level list of
    ``{parent_ref, child_ref, qty_per_parent?, child_name?}`` or an object
    ``{"edges": [...]}`` / ``{"rows": [...]}``. Same vocabulary + honesty as CSV."""
    rows: list[dict] = []
    if not text or not text.strip():
        return rows, [{"line": 0, "reason": "empty BOM JSON"}]
    try:
        doc = json.loads(text)
    except (ValueError, TypeError) as exc:
        return rows, [{"line": 0, "reason": f"invalid JSON: {exc}"}]
    if isinstance(doc, dict):
        raw = doc.get("edges", doc.get("rows"))
    elif isinstance(doc, list):
        raw = doc
    else:
        return rows, [{"line": 0, "reason": "JSON must be a list or {edges:[...]}"}]

    if not isinstance(raw, list):
        return rows, [{"line": 0, "reason": "JSON must contain an edges or rows list"}]
    errors: list[dict] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append({"line": idx, "reason": "edge entry is not an object"})
            continue
        row, err = _coerce_row(
            _clean(entry.get("parent_ref")),
            _clean(entry.get("child_ref")),
            _clean(entry.get("qty_per_parent")),
            _clean(entry.get("child_name")),
        )
        if err:
            errors.append({"line": idx, "reason": err})
            continue
        rows.append(row)
    return rows, errors


def parse_bom(text: str, *, content_hint: str = "") -> tuple[list[dict], list[dict]]:
    """Dispatch to the JSON or CSV parser. JSON when the hint says so OR the first
    non-space char is ``[`` / ``{``; else CSV."""
    hint = (content_hint or "").lower()
    stripped = (text or "").lstrip()
    is_json = "json" in hint or hint.endswith(".json") or stripped[:1] in ("[", "{")
    return parse_bom_json(text) if is_json else parse_bom_csv(text)


# ---------------------------------------------------------------------------
# Pure ancestry + rollup over an in-memory edge list
# ---------------------------------------------------------------------------
def _child_to_parents(edges: Iterable[dict]) -> dict[str, list[tuple[str, int]]]:
    """Validate counts and build the child -> parents adjacency."""
    adj: dict[str, list[tuple[str, int]]] = {}
    seen: set[tuple[str | None, str]] = set()
    for e in edges:
        child, parent = e["child_ref"], e.get("parent_ref")
        pair = (parent, child)
        if pair in seen:
            raise ValueError(
                "Duplicate BOM relationship. Use one row per parent/child pair "
                "with its total qty_per_parent."
            )
        seen.add(pair)
        qty = e.get("qty_per_parent", 1)
        if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= 2_147_483_647:
            raise ValueError("BOM quantities must be integers between 1 and 2147483647.")
        adj.setdefault(child, [])
        if parent is not None:
            adj[child].append((parent, qty))
    return adj


def _roots(edges: Iterable[dict]) -> set[str]:
    parents, children = set(), set()
    for edge in edges:
        children.add(edge["child_ref"])
        if edge.get("parent_ref") is not None:
            parents.add(edge["parent_ref"])
    return parents - children


def _checked_graph(edges: list[dict]) -> tuple[dict[str, list[tuple[str, int]]], list[str]]:
    adj = _child_to_parents(edges)
    try:
        order = list(TopologicalSorter({child: [p for p, _ in parents] for child, parents in adj.items()}).static_order())
    except CycleError as exc:
        raise ValueError("This BOM contains a cycle. Correct the parent-child relationships before calculating demand.") from exc
    return adj, order


def _ancestry_paths(adj: dict[str, list[tuple[str, int]]], child_ref: str) -> tuple[list[list[str]], bool]:
    """Iterative bounded preview; the numeric rollup never depends on this list."""
    paths: list[list[str]] = []
    path = [child_ref]
    stack = [iter(adj.get(child_ref, []))]
    visits = 1
    returned_nodes = 0
    while stack:
        if not adj.get(path[-1]):
            returned_nodes += len(path)
            if len(paths) >= _MAX_PATHS or returned_nodes > _MAX_PATH_NODES:
                return paths, True
            paths.append(path.copy())
        parent = next(stack[-1], None)
        if parent is None:
            stack.pop()
            path.pop()
        else:
            visits += 1
            if visits > _MAX_PATH_NODES:
                return paths, True
            path.append(parent[0])
            stack.append(iter(adj.get(parent[0], [])))
    return paths, False


def ancestry_paths(edges: list[dict], child_ref: str) -> list[list[str]]:
    """Root paths for a valid graph, bounded for display; cycles yield no paths."""
    try:
        adj, order = _checked_graph(edges)
    except ValueError:
        return []
    return _ancestry_paths(adj, child_ref)[0] if child_ref in order else []


def ancestry(edges: list[dict], child_ref: str) -> list[str]:
    """Shortest, then lexicographically first genuine child -> root path."""
    try:
        adj, order = _checked_graph(edges)
    except ValueError:
        return []
    if child_ref not in order:
        return []
    previous: dict[str, str | None] = {child_ref: None}
    queue = deque([child_ref])
    while queue:
        node = queue.popleft()
        parents = adj.get(node, [])
        if not parents:
            path = []
            cursor: str | None = node
            while cursor is not None:
                path.append(cursor)
                cursor = previous[cursor]
            return path[::-1]
        for parent, _ in sorted(parents):
            if parent not in previous:
                previous[parent] = node
                queue.append(parent)
    return []


def rolled_up_multiplier(edges: list[dict], child_ref: str) -> Optional[int]:
    """Sum every root-path using dynamic programming, without enumerating paths.

    A cycle, invalid count or unsupported exact count yields no rollup. A root
    counts once. Shared components sum all their parents' weighted counts.
    """
    try:
        adj, order = _checked_graph(edges)
    except ValueError:
        return None
    totals: dict[str, int | None] = {}
    for node in order:
        parents = adj.get(node, [])
        if any(totals[parent] is None for parent, _ in parents):
            totals[node] = None
            continue
        count = sum((totals[parent] or 0) * qty for parent, qty in parents) if parents else 1
        totals[node] = count if count <= _MAX_SAFE_COUNT else None
    return totals.get(child_ref)


def annual_volume(edges: list[dict], child_ref: str, roots_per_year: int) -> Optional[int]:
    """``rolled_up_multiplier(child_ref) x roots_per_year`` — units/year of a part,
    resolved from the real tree. ``None`` when the part has no rollup (no tree) —
    never a fabricated volume."""
    mult = rolled_up_multiplier(edges, child_ref)
    if mult is None or roots_per_year is None or roots_per_year <= 0:
        return None
    count = int(mult) * int(roots_per_year)
    return count if count <= _MAX_SAFE_COUNT else None


def resolve_annual_volume(
    declared_annual_volume: Optional[int],
    multiplier: Optional[int],
    roots_per_year: Optional[int],
) -> dict:
    """The SINGLE volume-basis decision (pure, unit-tested).

    Prefers the BOM rollup WHEN a real tree gives a ``multiplier`` and
    ``roots_per_year`` is declared; else the flat declared ``annual_volume``; else
    nothing. Returns ``{"annual_volume", "annual_volume_basis"}`` with basis one of
    ``'bom_rollup' | 'declared' | 'default'``. NEVER fabricates a rollup when there
    is no tree — that is exactly the declared/​default fallback.
    """
    if (multiplier is not None and roots_per_year is not None and roots_per_year > 0
            and multiplier * roots_per_year <= _MAX_SAFE_COUNT):
        return {
            "annual_volume": int(multiplier) * int(roots_per_year),
            "annual_volume_basis": "bom_rollup",
        }
    if declared_annual_volume is not None:
        return {
            "annual_volume": int(declared_annual_volume),
            "annual_volume_basis": "declared",
        }
    return {"annual_volume": None, "annual_volume_basis": "default"}


# ---------------------------------------------------------------------------
# DB adapters (thin; org-scoped; idempotent per (org_id, assembly_key))
# ---------------------------------------------------------------------------
async def load_edges(session: AsyncSession, org_id: str, assembly_key: str) -> list[dict]:
    """Every edge of one tree in the caller's org, as plain dicts (pure-helper
    input). Falsy org/key → ``[]`` (never a cross-org read)."""
    if not org_id or not assembly_key:
        return []
    rows = (
        await session.execute(
            select(BomEdge).where(
                BomEdge.org_id == org_id,
                BomEdge.assembly_key == assembly_key,
            )
        )
    ).scalars().all()
    return [
        {
            "parent_ref": r.parent_ref,
            "child_ref": r.child_ref,
            "child_name": r.child_name,
            "qty_per_parent": int(r.qty_per_parent),
            "depth": int(r.depth),
            "source": r.source,
        }
        for r in rows
    ]


async def _replace_tree(
    session: AsyncSession,
    org_id: str,
    assembly_key: str,
    edge_rows: list[dict],
    source: str,
) -> int:
    """Idempotent per ``(org_id, assembly_key)``: delete the org's existing edges
    for this key, then insert the given rows. Org-scoped; does NOT commit."""
    _checked_graph(edge_rows)
    await session.execute(
        delete(BomEdge).where(
            BomEdge.org_id == org_id,
            BomEdge.assembly_key == assembly_key,
        )
    )
    for e in edge_rows:
        session.add(
            BomEdge(
                org_id=org_id,
                assembly_key=assembly_key,
                parent_ref=e.get("parent_ref"),
                child_ref=e["child_ref"],
                child_name=e.get("child_name"),
                qty_per_parent=e.get("qty_per_parent", 1),
                depth=int(e.get("depth", 0) or 0),
                source=source,
            )
        )
    await session.flush()
    return len(edge_rows)


async def load_org_trees(session: AsyncSession, org_id: str) -> dict[str, list[dict]]:
    """Every BOM tree in the caller's org, grouped ``assembly_key -> [edge, ...]``.

    One org-scoped SELECT so the portfolio roll-up can resolve rollups in-memory
    (no per-part query). Empty dict when the org has no edges — the caller's
    ``has_any_bom`` gate then leaves the portfolio byte-identical."""
    if not org_id:
        return {}
    rows = (
        await session.execute(
            select(BomEdge).where(BomEdge.org_id == org_id)
        )
    ).scalars().all()
    trees: dict[str, list[dict]] = {}
    for r in rows:
        trees.setdefault(r.assembly_key, []).append(
            {
                "parent_ref": r.parent_ref,
                "child_ref": r.child_ref,
                "child_name": r.child_name,
                "qty_per_parent": int(r.qty_per_parent),
                "depth": int(r.depth),
                "source": r.source,
            }
        )
    return trees


async def ingest_assembly(
    session: AsyncSession,
    org_id: str,
    assembly_key: str,
    model: Any,
) -> dict:
    """Persist a parsed assembly's REAL edges (``source='assembly_step'``),
    idempotently replacing any prior tree for ``(org_id, assembly_key)``. Returns an
    honest summary ``{assembly_key, edges, roots, source}``; ``edges=0`` (with a
    note) for a degenerate single-part assembly — never a fabricated edge."""
    edge_rows = edges_from_assembly(model)
    count = await _replace_tree(session, org_id, assembly_key, edge_rows, SOURCE_ASSEMBLY_STEP)
    roots = sorted(_roots(edge_rows))
    out = {
        "assembly_key": assembly_key,
        "edges": count,
        "roots": roots,
        "source": SOURCE_ASSEMBLY_STEP,
    }
    if count == 0:
        out["note"] = "no multi-level hierarchy in this assembly (nothing to roll up)"
    return out


async def ingest_bom_rows(
    session: AsyncSession,
    org_id: str,
    assembly_key: str,
    rows: list[dict],
) -> dict:
    """Persist declared BOM rows (``source='bom_csv'``), idempotently replacing the
    prior tree for ``(org_id, assembly_key)``. ``rows`` are already-validated edge
    dicts from ``parse_bom*``. Returns ``{assembly_key, edges, roots, source}``."""
    count = await _replace_tree(session, org_id, assembly_key, rows, SOURCE_BOM_CSV)
    return {
        "assembly_key": assembly_key,
        "edges": count,
        "roots": sorted(_roots(rows)),
        "source": SOURCE_BOM_CSV,
    }


async def get_ancestry(
    session: AsyncSession,
    org_id: str,
    assembly_key: str,
    child_ref: str,
) -> dict:
    """The org-scoped ancestry + rollup for a part, HONEST when the tree is absent.

    Returns ``{assembly_key, child_ref, has_tree, ancestry:[child..root],
    ancestry_paths:[...], rolled_up_multiplier, roots}``. When no tree/part exists,
    ``has_tree=False``, empty chains, and ``rolled_up_multiplier=None`` (never a
    500, never a fabricated chain)."""
    edges = await load_edges(session, org_id, assembly_key)
    if not edges:
        return {
            "assembly_key": assembly_key,
            "child_ref": child_ref,
            "has_tree": False,
            "ancestry": [],
            "ancestry_paths": [],
            "rolled_up_multiplier": None,
            "roots": [],
        }
    try:
        adj, order = _checked_graph(edges)
        error = None
    except ValueError as exc:
        adj, order, error = {}, [], str(exc)
    multiplier = rolled_up_multiplier(edges, child_ref) if error is None else None
    paths, truncated = _ancestry_paths(adj, child_ref) if child_ref in order else ([], False)
    if error is None and child_ref in order and multiplier is None:
        error = "The BOM count exceeds the supported exact integer range. Demand was not calculated."
    return {
        "assembly_key": assembly_key,
        "child_ref": child_ref,
        "has_tree": child_ref in order and error is None,
        "ancestry": ancestry(edges, child_ref) if error is None else [],
        "ancestry_paths": paths if error is None else [],
        "ancestry_paths_truncated": truncated,
        "rolled_up_multiplier": multiplier,
        "roots": sorted(_roots(edges)),
        "error": error,
    }


async def annual_volume_for_context(
    session: AsyncSession,
    org_id: str,
    ctx_row: Any,
) -> dict:
    """Resolve the annual volume + basis that should feed the analysis for a part,
    from its declared context row.

    Prefers the BOM rollup when the context names a real tree
    (``bom_assembly_key`` + ``bom_child_ref`` resolve to edges) AND declares
    ``bom_roots_per_year``; otherwise the flat declared ``annual_volume``; otherwise
    default (no volume). Returns ``{"annual_volume", "annual_volume_basis"}``. A
    context with no BOM linkage never touches ``bom_edges`` and yields exactly the
    declared value — byte-identical to the pre-Slice-3 path.
    """
    declared = getattr(ctx_row, "annual_volume", None) if ctx_row is not None else None
    assembly_key = getattr(ctx_row, "bom_assembly_key", None) if ctx_row is not None else None
    child_ref = getattr(ctx_row, "bom_child_ref", None) if ctx_row is not None else None
    roots_per_year = getattr(ctx_row, "bom_roots_per_year", None) if ctx_row is not None else None

    multiplier: Optional[int] = None
    if assembly_key and child_ref:
        edges = await load_edges(session, org_id, assembly_key)
        if edges:
            multiplier = rolled_up_multiplier(edges, child_ref)
    return resolve_annual_volume(declared, multiplier, roots_per_year)
