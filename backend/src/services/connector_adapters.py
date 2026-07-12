"""Read-only enterprise connector adapter contracts.

These classes are intentionally conservative: they define how SAP/PLM records
will be probed, normalized, and dry-run compared before any live write path
exists. No adapter here can send supplier messages, mutate SAP/PLM, or claim live
certification without a successful connector-run evidence row at the right
promotion level.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
                    material=str(row.get("Material") or row.get("material") or "").strip() or None,
                    source_system=self.source_system,
                    source_payload_ref=ref,
                )
            elif kind in {"bom_item", "bom"}:
                parent = str(row.get("BillOfMaterial") or row.get("parent_part_number") or "").strip()
                child = str(row.get("BillOfMaterialComponent") or row.get("child_part_number") or "").strip()
                if not parent or not child:
                    warnings.append(f"{ref}: missing SAP BOM parent/component")
                    continue
                qty = _float(row.get("BillOfMaterialItemQuantity") or row.get("quantity"), default=1.0)
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
                bom_nodes.append(
                    ExternalBomNode(
                        parent_part_number=parent,
                        child_part_number=child,
                        quantity=_float(row.get("Quantity") or row.get("quantity"), default=1.0),
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


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
