from __future__ import annotations

import pytest

from src.services.connector_adapters import (
    ConnectorAdapterSettings,
    SapS4ProductBomReadOnlyAdapter,
    WindchillPartBomReadOnlyAdapter,
)
from src.services.integration_service import BOUNDARY_SANDBOX, CONNECTOR_MODE_SANDBOX_API


def test_sap_adapter_probe_is_read_only_and_requires_credentials():
    adapter = SapS4ProductBomReadOnlyAdapter(
        ConnectorAdapterSettings(connector_id="sap_s4hana_product_bom_readonly")
    )

    probe = adapter.probe_credentials()

    assert probe.connector_id == "sap_s4hana_product_bom_readonly"
    assert probe.configured is False
    assert probe.read_only is True
    assert probe.mode == CONNECTOR_MODE_SANDBOX_API
    assert probe.boundary_label == BOUNDARY_SANDBOX
    assert "credential_profile_id" in probe.reason


def test_sap_adapter_normalizes_product_and_bom_rows_without_write_claims():
    adapter = SapS4ProductBomReadOnlyAdapter(
        ConnectorAdapterSettings(
            connector_id="sap_s4hana_product_bom_readonly",
            base_url="https://sap.example",
            credential_profile_id="cred_1",
        )
    )

    diff = adapter.dry_run_diff([
        {
            "kind": "product",
            "Product": "VALVE-100",
            "ProductDescription": "Valve body",
            "material": "316L",
        },
        {
            "kind": "bom_item",
            "BillOfMaterial": "00000123",
            "Material": "VALVE-100",
            "BillOfMaterialComponent": "STEM-200",
            "BillOfMaterialItemQuantity": "2",
            "BillOfMaterialItemUnit": "EA",
        },
    ])

    assert diff.source_record_count == 2
    assert diff.normalized_part_count == 1
    assert diff.normalized_bom_node_count == 1
    assert diff.warnings == []


def test_windchill_adapter_normalizes_partuse_rows():
    adapter = WindchillPartBomReadOnlyAdapter(
        ConnectorAdapterSettings(
            connector_id="windchill_part_bom_readonly",
            base_url="https://plm.example",
            credential_profile_id="cred_2",
        )
    )

    normalized = adapter.normalize([
        {
            "kind": "part",
            "ID": "OR:wt.part.WTPart:1",
            "Number": "PUMP-10",
            "Revision": "A",
            "Name": "Pump body",
            "Material": "Duplex 2205",
        },
        {
            "kind": "PartUse",
            "ParentNumber": "PUMP-10",
            "ChildNumber": "SEAL-20",
            "Quantity": 4,
            "Unit": "EA",
            "FindNumber": "0010",
        },
    ])

    assert normalized.parts[0].part_number == "PUMP-10"
    assert normalized.parts[0].revision == "A"
    assert normalized.bom_nodes[0].parent_part_number == "PUMP-10"
    assert normalized.bom_nodes[0].child_part_number == "SEAL-20"
    assert normalized.bom_nodes[0].quantity == 4
    assert normalized.warnings == []


@pytest.mark.parametrize("adapter_type,quantity_key,base_row", [
    (SapS4ProductBomReadOnlyAdapter, "BillOfMaterialItemQuantity", {
        "kind": "bom_item", "Material": "PARENT", "BillOfMaterial": "00000123",
        "BillOfMaterialComponent": "CHILD",
    }),
    (WindchillPartBomReadOnlyAdapter, "Quantity", {
        "kind": "PartUse", "ParentNumber": "PARENT", "ChildNumber": "CHILD",
    }),
])
def test_bom_quantities_are_never_invented_and_valid_neighbors_survive(adapter_type, quantity_key, base_row):
    adapter = adapter_type(ConnectorAdapterSettings(connector_id="test"))
    invalid = [None, "", "bad", 0, -2, True, "NaN", "Infinity", 10 ** 400]
    rows = [{**base_row, "quantity": 7, quantity_key: value} for value in invalid]
    rows += [{**base_row, quantity_key: "2.5"}, {**base_row, "quantity": 3}]
    result = adapter.normalize(rows)
    assert [edge.quantity for edge in result.bom_nodes] == [2.5, 3]
    assert len(result.warnings) == len(invalid)
    assert all("quantity" in warning for warning in result.warnings)


def test_sap_bom_id_and_material_number_are_not_part_material_properties():
    adapter = SapS4ProductBomReadOnlyAdapter(ConnectorAdapterSettings(connector_id="test"))
    result = adapter.normalize([
        {"kind": "product", "Material": "PARENT"},
        {"kind": "bom_item", "Material": "PARENT", "BillOfMaterial": "00000123",
         "BillOfMaterialComponent": "CHILD", "BillOfMaterialItemQuantity": "2"},
        {"kind": "bom_item", "BillOfMaterial": "00000999",
         "BillOfMaterialComponent": "CHILD", "BillOfMaterialItemQuantity": "2"},
    ])
    assert result.parts[0].part_number == "PARENT"
    assert result.parts[0].material is None
    assert len(result.bom_nodes) == 1
    assert result.bom_nodes[0].parent_part_number == "PARENT"
    assert len(result.warnings) == 1
    assert "parent" in result.warnings[0]
