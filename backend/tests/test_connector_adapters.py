from __future__ import annotations

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
            "Material": "316L",
        },
        {
            "kind": "bom_item",
            "BillOfMaterial": "VALVE-100",
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
