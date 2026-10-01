"""SAP-shaped fixtures validate the read contract, never real-tenant proof."""
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from src.db.models import ConnectorCredentialProfile
from src.services import connector_credentials_service as creds
from src.services import connector_transport as transport
from tests.test_connector_probe_transport import HTTP_CLIENT, mock_http


SELECTION = {
    "bill_of_material": "00058298", "variant": "1", "version": "",
    "engineering_change_document": "", "plant": "0001", "application": "PP01",
    "explosion_date": "2026-09-30", "explosion_level": 2,
}


def explosion():
    return {"d": {"results": [{
        "Bill_Of_Material_Root": "00058298", "B_O_M_Hdr_Root_Matl_Hier_Node": "EX_H",
        "bill_of_material_root_variant": "1", "b_o_m_hdr_matl_hier_node": "EX_H",
        "bill_of_material_component": "EX_H2", "b_o_m_explosion_level": "1",
        "bill_of_material_item_quantity": "5.000", "bill_of_material_item_unit": "EA",
        "b_o_m_header_quantity_primary": "2.000", "b_o_m_header_base_unit": "EA",
        "bill_of_material_comp_quant": "2.500", "bill_of_material_item_number": "0010",
        "b_o_m_component_description": "Part", "path": "1", "path_predecessor": "1",
        "supplier": "discard-this-field",
    }]}}


@pytest.mark.asyncio
async def test_preview_sends_documented_get_and_keeps_quantity_meanings_distinct(monkeypatch):
    requests = []

    def vendor(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/sap/opu/odata/sap/API_BILL_OF_MATERIAL_SRV;v=2/ExplodeBOM"
        assert request.headers["authorization"] == "Bearer fixture-secret"
        assert request.headers["host"] == "sap.example"
        assert request.extensions["sni_hostname"] == "sap.example"
        assert request.url.params["Material"] == "'EX_H'"
        assert request.url.params["RequiredQuantity"] == "1.000m"
        assert request.url.params["BOMExplosionLevel"] == "2m"
        assert request.url.params["BOMExplosionIsLimited"] == "false"
        assert request.url.params["BOMExplosionIsMultilevel"] == "true"
        assert request.url.params["BOMExplosionDate"] == "datetime'2026-09-30T00:00:00'"
        return httpx.Response(200, json=explosion())

    mock_http(monkeypatch, vendor)
    rows, count = await transport.read_sap_bom_preview(
        "https://sap.example/sap/opu/odata/sap/API_PRODUCT_SRV", "bearer", {"token": "fixture-secret"},
        part_id="EX_H", selection=SELECTION,
    )
    assert count == 1 and len(requests) == 1
    assert rows[0]["item_quantity"] == "5.000"
    assert rows[0]["header_quantity"] == "2.000"
    assert rows[0]["exploded_quantity"] == "2.500"
    assert "qty_per_parent" not in rows[0]
    assert "fixture-secret" not in str(rows) and "discard-this-field" not in str(rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["next", "root", "material", "variant", "quantity", "shape", "empty"])
async def test_malformed_or_wrong_selection_never_passes_preview(monkeypatch, defect):
    payload = explosion()
    row = payload["d"]["results"][0]
    if defect == "next": payload["d"]["__next"] = "https://other.example/secret"
    elif defect == "root": row["Bill_Of_Material_Root"] = "other"
    elif defect == "material": row["B_O_M_Hdr_Root_Matl_Hier_Node"] = "other"
    elif defect == "variant": row["bill_of_material_root_variant"] = "2"
    elif defect == "quantity": row["bill_of_material_item_quantity"] = "NaN"
    elif defect == "shape": payload = {"value": [row]}
    elif defect == "empty": payload["d"]["results"] = []
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(transport.ConnectorConnectionError):
        await transport.read_sap_bom_preview("https://sap.example", "bearer", {"token": "fixture-secret"}, part_id="EX_H", selection=SELECTION)


@pytest.mark.asyncio
async def test_invalid_selection_and_import_do_not_send_credentials(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("invalid request sent"))
    selection = {**SELECTION, "explosion_date": "2026-02-30"}
    with pytest.raises(transport.ConnectorConnectionError):
        await transport.read_sap_bom_preview("https://sap.example", "bearer", {"token": "fixture-secret"}, part_id="EX_H", selection=selection)
    profile = ConnectorCredentialProfile(ulid="SAP1", org_id="ORG1", connector_id="sap_s4hana_product_bom_readonly")
    with pytest.raises(HTTPException) as error:
        await creds.run_bom_profile(AsyncMock(), profile, user_id=1, part_id="EX_H", assembly_key="test", mode="import", sap_selection=SELECTION)
    assert error.value.status_code == 400 and "preview" in error.value.detail.lower()


@pytest.mark.asyncio
async def test_preview_ledger_cannot_claim_an_import_or_complete_graph(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=deepcopy(explosion())))
    encrypted, _ = creds.encrypt_secret({"token": "fixture-secret"})
    profile = ConnectorCredentialProfile(ulid="SAP1", org_id="ORG1", connector_id="sap_s4hana_product_bom_readonly",
        base_url="https://sap.example", auth_type="bearer", encrypted_secret_json=encrypted)
    session = AsyncMock()
    session.add = lambda row: None
    run = await creds.run_bom_profile(session, profile, user_id=1, part_id="EX_H", assembly_key="test", mode="dry_run", sap_selection=SELECTION)
    assert run.status == "passed" and run.imported_count == 0
    assert run.metadata_json["import_supported"] is False
    assert run.metadata_json["complete_structure_verified"] is False
    assert run.metadata_json["preview_edges"] == []
    assert len(run.metadata_json["preview_components"]) == 1
    assert run.metadata_json["sap_selection"] == SELECTION
    assert "fixture-secret" not in str(run.metadata_json)


@pytest.mark.asyncio
async def test_api_exposes_preview_but_never_offers_import(monkeypatch):
    from fastapi import FastAPI
    from src.api import integrations
    from src.auth.rate_limit import limiter
    from src.auth.rbac import OrgAuthContext
    from src.db.engine import get_db_session

    encrypted, _ = creds.encrypt_secret({"token": "fixture-secret"})
    profile = ConnectorCredentialProfile(ulid="SAP1", org_id="ORG1", connector_id="sap_s4hana_product_bom_readonly",
        base_url="https://sap.example", auth_type="bearer", encrypted_secret_json=encrypted)
    monkeypatch.setattr(creds, "get_profile", AsyncMock(return_value=profile))
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=explosion()))
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(integrations.router, prefix="/integrations")
    app.dependency_overrides[integrations.require_integration_admin] = lambda: OrgAuthContext(
        user_id=1, api_key_id=1, key_prefix="test", role="analyst", is_superadmin=False, org_id="ORG1", org_role="admin",
    )
    session = AsyncMock()
    session.add = lambda row: None
    app.dependency_overrides[get_db_session] = lambda: session
    body = {"part_id": "EX_H", "assembly_key": "read test", "sap_selection": SELECTION}
    async with HTTP_CLIENT(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/integrations/credential-profiles/SAP1/bom-runs", json=body)
        assert response.status_code == 200, response.text
        run = response.json()["run"]
        assert run["status"] == "passed" and run["metadata"]["import_supported"] is False
        assert run["api_name"] == "API_BILL_OF_MATERIAL_SRV;v=2/ExplodeBOM"
        assert run["rows_valid"] == 1 and run["imported_count"] == 0
        assert "fixture-secret" not in response.text
        invalid = await client.post("/integrations/credential-profiles/SAP1/bom-runs", json={**body, "sap_selection": {**SELECTION, "explosion_level": 0}})
        assert invalid.status_code == 422
