"""Read-only enterprise connector adapter contracts.

These classes are intentionally conservative: they define how SAP/PLM records
will be probed, normalized, and dry-run compared before any live write path
exists. No adapter here can send supplier messages, mutate SAP/PLM, or claim live
certification without a successful connector-run evidence row at the right
promotion level.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Protocol

from src.services.integration_service import (
    BOUNDARY_SANDBOX,
    CONNECTOR_MODE_SANDBOX_API,
)


@dataclass(frozen=True)
class ConnectorAdapterSettings:
    connector_id: str
    base_url: str | None = None
    credential_profile_id: str | None = None
    api_name: str | None = None
    api_version: str | None = None
    mode: str = CONNECTOR_MODE_SANDBOX_API
    boundary_label: str = BOUNDARY_SANDBOX


@dataclass(frozen=True)
class ProbeResult:
    connector_id: str
    configured: bool
    mode: str
    boundary_label: str
    read_only: bool
    reason: str | None = None


@dataclass(frozen=True)
class ExternalPart:
    external_id: str
    part_number: str
    revision: str | None = None
    description: str | None = None
    material: str | None = None
    source_system: str | None = None
    source_payload_ref: str | None = None


@dataclass(frozen=True)
class ExternalBomNode:
    parent_part_number: str
    child_part_number: str
    quantity: float
    unit: str | None = None
    line_number: str | None = None
    source_payload_ref: str | None = None


@dataclass(frozen=True)
class NormalizedConnectorPayload:
    parts: list[ExternalPart] = field(default_factory=list)
    bom_nodes: list[ExternalBomNode] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DryRunDiff:
    connector_id: str
    source_record_count: int
    normalized_part_count: int
    normalized_bom_node_count: int
    warnings: list[str]


class ReadOnlyConnectorAdapter(Protocol):
    settings: ConnectorAdapterSettings

    def probe_credentials(self) -> ProbeResult:
        ...

    def normalize(self, records: Iterable[dict[str, Any]]) -> NormalizedConnectorPayload:
        ...

    def dry_run_diff(self, records: Iterable[dict[str, Any]]) -> DryRunDiff:
        ...


class _BaseReadOnlyAdapter:
    source_system = "enterprise"

    def __init__(self, settings: ConnectorAdapterSettings):
        self.settings = settings

    def probe_credentials(self) -> ProbeResult:
        configured = bool(self.settings.base_url and self.settings.credential_profile_id)
        return ProbeResult(
            connector_id=self.settings.connector_id,
            configured=configured,
            mode=self.settings.mode,
            boundary_label=self.settings.boundary_label,
            read_only=True,
            reason=None if configured else "base_url and credential_profile_id are required",
        )

    def dry_run_diff(self, records: Iterable[dict[str, Any]]) -> DryRunDiff:
        rows = list(records)
        normalized = self.normalize(rows)
        return DryRunDiff(
            connector_id=self.settings.connector_id,
            source_record_count=len(rows),
            normalized_part_count=len(normalized.parts),
            normalized_bom_node_count=len(normalized.bom_nodes),
            warnings=normalized.warnings,
        )


class SapS4ProductBomReadOnlyAdapter(_BaseReadOnlyAdapter):
    """Normalize SAP S/4HANA product/BOM read data into CadVerify primitives."""

    source_system = "SAP S/4HANA"

    def normalize(self, records: Iterable[dict[str, Any]]) -> NormalizedConnectorPayload:
        parts: dict[str, ExternalPart] = {}
        bom_nodes: list[ExternalBomNode] = []
        warnings: list[str] = []

        for index, row in enumerate(records, start=1):
            kind = str(row.get("kind") or row.get("type") or "").lower()
            ref = str(row.get("source_ref") or f"sap:{index}")
            if kind in {"product", "material", "part"}:
                part_number = str(row.get("Product") or row.get("Material") or row.get("part_number") or "").strip()
                if not part_number:
                    warnings.append(f"{ref}: missing SAP product/material id")
                    continue
                parts[part_number] = ExternalPart(
                    external_id=part_number,
                    part_number=part_number,
                    revision=str(row.get("Revision") or row.get("revision") or "").strip() or None,
                    description=str(row.get("ProductDescription") or row.get("description") or "").strip() or None,
                    material=str(row.get("material") or "").strip() or None,
                    source_system=self.source_system,
                    source_payload_ref=ref,
                )
            elif kind in {"bom_item", "bom"}:
                parent = str(row.get("Material") or row.get("parent_part_number") or "").strip()
                child = str(row.get("BillOfMaterialComponent") or row.get("child_part_number") or "").strip()
                if not parent or not child:
                    warnings.append(f"{ref}: missing SAP BOM parent/component")
                    continue
                qty = _positive_quantity(row.get("BillOfMaterialItemQuantity", row.get("quantity")))
                if qty is None:
                    warnings.append(f"{ref}: unsupported BOM quantity; provide a finite positive number")
                    continue
                bom_nodes.append(
                    ExternalBomNode(
                        parent_part_number=parent,
                        child_part_number=child,
                        quantity=qty,
                        unit=str(row.get("BillOfMaterialItemUnit") or row.get("unit") or "").strip() or None,
                        line_number=str(row.get("BillOfMaterialItemNumber") or row.get("line_number") or "").strip() or None,
                        source_payload_ref=ref,
                    )
                )
            else:
                warnings.append(f"{ref}: unsupported SAP record kind '{kind or 'unknown'}'")

        return NormalizedConnectorPayload(
            parts=list(parts.values()),
            bom_nodes=bom_nodes,
            warnings=warnings,
        )


class WindchillPartBomReadOnlyAdapter(_BaseReadOnlyAdapter):
    """Normalize PTC Windchill part/BOM read data into CadVerify primitives."""

    source_system = "PTC Windchill"

    def normalize(self, records: Iterable[dict[str, Any]]) -> NormalizedConnectorPayload:
        parts: dict[str, ExternalPart] = {}
        bom_nodes: list[ExternalBomNode] = []
        warnings: list[str] = []

        for index, row in enumerate(records, start=1):
            kind = str(row.get("kind") or row.get("@type") or row.get("type") or "").lower()
            ref = str(row.get("source_ref") or f"windchill:{index}")
            if kind in {"part", "wt.part.wtpart"}:
                number = str(row.get("Number") or row.get("number") or row.get("part_number") or "").strip()
                if not number:
                    warnings.append(f"{ref}: missing Windchill part number")
                    continue
                parts[number] = ExternalPart(
                    external_id=str(row.get("ID") or row.get("id") or number),
                    part_number=number,
                    revision=str(row.get("Revision") or row.get("version") or "").strip() or None,
                    description=str(row.get("Name") or row.get("description") or "").strip() or None,
                    material=str(row.get("Material") or row.get("material") or "").strip() or None,
                    source_system=self.source_system,
                    source_payload_ref=ref,
                )
            elif kind in {"partuse", "bom_item", "usage"}:
                parent = str(row.get("ParentNumber") or row.get("parent_part_number") or "").strip()
                child = str(row.get("ChildNumber") or row.get("child_part_number") or "").strip()
                if not parent or not child:
                    warnings.append(f"{ref}: missing Windchill BOM parent/child")
                    continue
                qty = _positive_quantity(row.get("Quantity", row.get("quantity")))
                if qty is None:
                    warnings.append(f"{ref}: unsupported BOM quantity; provide a finite positive number")
                    continue
                bom_nodes.append(
                    ExternalBomNode(
                        parent_part_number=parent,
                        child_part_number=child,
                        quantity=qty,
                        unit=str(row.get("Unit") or row.get("unit") or "").strip() or None,
                        line_number=str(row.get("FindNumber") or row.get("line_number") or "").strip() or None,
                        source_payload_ref=ref,
                    )
                )
            else:
                warnings.append(f"{ref}: unsupported Windchill record kind '{kind or 'unknown'}'")

        return NormalizedConnectorPayload(
            parts=list(parts.values()),
            bom_nodes=bom_nodes,
            warnings=warnings,
        )


def _positive_quantity(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        quantity = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return quantity if math.isfinite(quantity) and quantity > 0 else None


def sap_bom_preview_rows(payload: dict[str, Any], material: str, selection: dict[str, Any]) -> tuple[list[dict], int]:
    """Project ExplodeBOM values for inspection, without inferring BOM edges.

    Item quantity, header base quantity and exploded quantity have different
    meanings. Keep them separate; path/predecessor is not a verified graph.
    """
    collection = payload.get("d")
    if not isinstance(collection, dict) or "__next" in collection:
        raise ValueError("SAP returned an unsupported or paginated BOM response.")
    records = collection.get("results")
    # ponytail: conservative preview cap across unverified SAP versions; revise after tenant metadata validation.
    if not isinstance(records, list) or not records or len(records) >= 9999:
        raise ValueError("SAP returned no BOM components or exceeded the supported preview size (9998 records).")
    rows = []
    for record in records:
        if (not isinstance(record, dict)
                or record.get("Bill_Of_Material_Root") != selection["bill_of_material"]
                or record.get("B_O_M_Hdr_Root_Matl_Hier_Node") != material
                or record.get("bill_of_material_root_variant") != selection["variant"]):
            raise ValueError("SAP returned a different or unidentified root BOM, material or alternative.")
        row = {}
        for target, source in {
            "component": "bill_of_material_component", "header_material": "b_o_m_hdr_matl_hier_node",
            "item_unit": "bill_of_material_item_unit", "header_unit": "b_o_m_header_base_unit",
            "item_number": "bill_of_material_item_number",
        }.items():
            value = record.get(source)
            if not isinstance(value, str) or not value.strip() or len(value) > 120:
                raise ValueError("SAP returned missing or invalid component identity or units.")
            row[target] = value
        for target, source in {
            "level": "b_o_m_explosion_level", "item_quantity": "bill_of_material_item_quantity",
            "header_quantity": "b_o_m_header_quantity_primary", "exploded_quantity": "bill_of_material_comp_quant",
        }.items():
            value = record.get(source)
            if isinstance(value, bool) or not re.fullmatch(r"-?\d{1,20}(?:\.\d{1,20})?", str(value)):
                raise ValueError("SAP returned a missing or invalid BOM quantity or level.")
            number = Decimal(str(value))
            if ((target == "header_quantity" and number <= 0)
                    or (target == "level" and (number < 1 or number > selection["explosion_level"] or number != number.to_integral_value()))):
                raise ValueError("SAP returned an invalid header quantity or unexpected explosion level.")
            row[target] = str(value)
        rows.append(row)
    return rows, len(records)


def windchill_bom_rows(payload: dict[str, Any], expected_root: str) -> tuple[list[dict], int]:
    """Map complete GetPartStructure data to existing BOM rows using part IDs.

    Distinct usage links to the same child are additive. Repeated occurrences of
    a shared parent must describe the same child counts, never extra assemblies.
    """
    from src.services.bom_service import BOM_MAX_ROWS, _checked_graph

    def part(node: dict) -> tuple[str, str]:
        value = node.get("Part")
        if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k].strip() for k in ("ID", "Number")):
            raise ValueError("The BOM is missing expanded part identity. Check the Windchill API version.")
        if not re.fullmatch(r"OR:wt\.part\.WTPart:[0-9]{1,30}", value["ID"]):
            raise ValueError("The BOM must identify exact part iterations, not unresolved part masters.")
        return value["ID"], str(value.get("Name") or value["Number"])

    if part(payload)[0] != expected_root:
        raise ValueError("The returned root differs from the requested part iteration.")
    if payload.get("HasUnresolvedObjectsByAccessRights") is not False:
        raise ValueError("Windchill could not confirm access to the complete BOM.")
    stack = [payload]
    structures: dict[str, dict[str, int]] = {}
    edges: dict[tuple[str, str], dict] = {}
    usages: dict[str, tuple[str, str, int]] = {}
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > BOM_MAX_ROWS:
            raise ValueError("The BOM exceeds the 20000 component limit.")
        if (node.get("Resolved") is not True or node.get("HasUnresolvedObjectsByAccessRights") is True
                or any(key.endswith("nextLink") for key in node)):
            raise ValueError("The BOM is unresolved, access-restricted or paginated; a complete structure is required.")
        children = node.get("Components", [])
        if (not isinstance(children, list) or not isinstance(node.get("HasChildren"), bool)
                or node["HasChildren"] != bool(children) or any(not isinstance(c, dict) for c in children)):
            raise ValueError("The BOM has incomplete or inconsistent component expansion.")
        parent_id, _ = part(node)
        counts: dict[str, int] = {}
        links: set[str] = set()
        for child in children:
            child_id, name = part(child)
            usage = child.get("PartUse")
            if not isinstance(usage, dict) or not isinstance(usage.get("ID"), str) or not usage["ID"]:
                raise ValueError("The BOM is missing expanded part usage links.")
            if usage["ID"] in links:
                raise ValueError("The BOM repeats a usage link. Request the structure without occurrence expansion.")
            links.add(usage["ID"])
            unit = usage.get("Unit")
            if not isinstance(unit, dict) or str(unit.get("Value", "")).lower() != "ea":
                raise ValueError("BOM demand requires each (ea) units; mass, length and other units cannot be treated as part counts.")
            try:
                quantity = Decimal(str(usage.get("Quantity")))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("The BOM quantity is missing or invalid.") from exc
            if not (quantity.is_finite() and 0 < quantity <= 2_147_483_647 and quantity == quantity.to_integral_value()):
                raise ValueError("BOM quantities must be exact whole-part counts between 1 and 2147483647.")
            association = (parent_id, child_id, int(quantity))
            if usages.setdefault(usage["ID"], association) != association:
                raise ValueError("The same usage link has conflicting part identities or quantities.")
            counts[child_id] = counts.get(child_id, 0) + int(quantity)
            if counts[child_id] > 2_147_483_647:
                raise ValueError("Combined BOM quantities exceed the supported part count.")
            edges.setdefault((parent_id, child_id), {"parent_ref": parent_id, "child_ref": child_id, "child_name": name})
        if structures.setdefault(parent_id, counts) != counts:
            raise ValueError("The same part iteration has conflicting BOM structures.")
        for child_id, quantity in counts.items():
            edges[(parent_id, child_id)]["qty_per_parent"] = quantity
        stack.extend(children)
    rows = [edges[key] for key in sorted(edges)]
    if not rows:
        raise ValueError("The selected part has no BOM components to import.")
    _checked_graph(rows)
    return rows, visited - 1
