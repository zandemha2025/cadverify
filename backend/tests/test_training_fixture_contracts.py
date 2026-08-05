from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.services import groundtruth_service, manifest_service, parts_master_service
from src.services.connector_adapters import (
    ConnectorAdapterSettings,
    SapS4ProductBomReadOnlyAdapter,
    WindchillPartBomReadOnlyAdapter,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "docs" / "training" / "fixtures"
CONTRACTS = {
    "README.md": "8f0f70354d3672ebe2effe743ee486c45c7912b06c0c2f0a463ec09fdceca9f3",
    "ground-truth-mixed.csv": "16cd702c4e063170bffcc496515b10e5fcf988e7f3bd77e0c28d3625d9f7762a",
    "parts-manifest-mixed.csv": "567fc0c2853324d0401e2001208bf8d2c5a6ec65d099a882c05a9aab87281268",
    "parts-master-map.csv": "118e15d195c0666533187aef6f598106c64d9aae6ab94d50bfbafa81b2d05ac5",
    "sap-s4hana-sandbox.json": "31aa45fef08c44fc7cb8cd7cc30340a294d2fa620092200f6f7f83b588f2664f",
    "windchill-sandbox.json": "5ff55031f13a1dc53f3c185f87c98f84101a81c23b72019774892ffe22117307",
    "wire-only-unmeshable.step": "a5d464dce37e9160691f7cb721ca9d9b94d3dcabd75eb776f837430985fa23a7",
}


def test_training_fixture_bytes_and_csv_oracles_are_exact():
    for name, digest in CONTRACTS.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest

    actuals, actual_errors = groundtruth_service.parse_ground_truth_csv(
        (FIXTURES / "ground-truth-mixed.csv").read_text()
    )
    assert len(actuals) == 8
    assert all(row["stand_in"] is True for row in actuals)
    assert all(row["source_type"] == "demo" for row in actuals)
    assert {
        row["evidence_sha256"] for row in actuals
    } == {"76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a"}
    assert len(actual_errors) == 1 and actual_errors[0]["line"] == 10
    for phrase in (
        "unknown process",
        "quantity must be",
        "actual_unit_cost_usd must be",
        "unknown material_class",
        "currency must be",
        "invoice_date must be",
        "evidence_sha256 must be",
    ):
        assert phrase in actual_errors[0]["reason"]

    manifest, manifest_errors = manifest_service.parse_manifest_csv(
        (FIXTURES / "parts-manifest-mixed.csv").read_text()
    )
    assert [row["part_id"] for row in manifest] == ["PV-INT-001", "PV-INT-002"]
    assert len(manifest_errors) == 1 and manifest_errors[0]["line"] == 4

    mapping, mapping_errors = parts_master_service.parse_identity_mapping(
        (FIXTURES / "parts-master-map.csv").read_text(), content_hint=".csv"
    )
    assert sorted(mapping) == ["cube.step", "missing.step"]
    assert len(mapping_errors) == 1 and mapping_errors[0] == {
        "line": 4,
        "reason": "missing filename",
    }


def test_offline_connector_replays_normalize_without_warnings():
    sap_rows = json.loads((FIXTURES / "sap-s4hana-sandbox.json").read_text())
    sap = SapS4ProductBomReadOnlyAdapter(
        ConnectorAdapterSettings(connector_id="training-sap")
    ).dry_run_diff(sap_rows)
    assert (sap.source_record_count, sap.normalized_part_count, sap.normalized_bom_node_count) == (3, 2, 1)
    assert sap.warnings == []

    windchill_rows = json.loads((FIXTURES / "windchill-sandbox.json").read_text())
    windchill = WindchillPartBomReadOnlyAdapter(
        ConnectorAdapterSettings(connector_id="training-windchill")
    ).dry_run_diff(windchill_rows)
    assert (
        windchill.source_record_count,
        windchill.normalized_part_count,
        windchill.normalized_bom_node_count,
    ) == (3, 2, 1)
    assert windchill.warnings == []
