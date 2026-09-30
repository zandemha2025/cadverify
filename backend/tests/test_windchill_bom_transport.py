"""Real HTTPX request construction and vendor-shaped fixtures, not tenant proof.

Contract: PTC WRS GetPartStructure with Part/PartUse expansion (no occurrences),
GetCSRFToken, and PartUse.Quantity/Unit.Value documented by PTC.
"""
from copy import deepcopy
import json

import httpx
import pytest

from src.services import connector_transport as transport
from src.services.bom_service import rolled_up_multiplier
from tests.test_connector_probe_transport import mock_http


def node(number, children=(), *, quantity=None, link=None):
    result = {
        "Part": {"ID": f"OR:wt.part.WTPart:{number}", "Number": str(number), "Name": f"Part {number}"},
        "Resolved": True, "HasChildren": bool(children), "Components": list(children),
        "HasUnresolvedObjectsByAccessRights": None,
    }
    if quantity is not None:
        result["PartUse"] = {"ID": f"OR:wt.part.WTPartUsageLink:{link}", "Quantity": quantity, "Unit": {"Value": "ea"}}
    return result


def structure():
    root = node(1, [
        node(2, [node(4, quantity=3, link=13)], quantity=2, link=11),
        node(3, [node(4, quantity=2, link=14)], quantity=1, link=12),
    ])
    root["HasUnresolvedObjectsByAccessRights"] = False
    return root


async def read(monkeypatch, payload, *, raw=None, source_count=4):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "windchill.example"
        assert request.extensions["sni_hostname"] == "windchill.example"
        assert request.headers["authorization"] == "Bearer vendor-secret"
        if len(requests) == 1:
            assert request.method == "GET"
            assert request.url.path == "/Windchill/servlet/odata/PTC/GetCSRFToken()"
            return httpx.Response(200, json={"NonceKey": "CSRF_NONCE", "NonceValue": "nonce-sentinel"},
                                  headers={"set-cookie": "JSESSIONID=session-sentinel; Domain=windchill.example; Path=/Windchill; Secure; HttpOnly"})
        assert request.method == "POST"
        assert request.url.path == "/Windchill/servlet/odata/ProdMgmt/Parts('OR:wt.part.WTPart:1')/PTC.ProdMgmt.GetPartStructure"
        assert request.headers["csrf_nonce"] == "nonce-sentinel"
        assert request.headers["cookie"] == "JSESSIONID=session-sentinel"
        assert "Occurrences" not in request.url.params["$expand"]
        assert "PartUse" in request.url.params["$expand"]
        assert json.loads(request.content) == {"NavigationCriteria": {"ID": "OR:wt.filter.NavigationCriteria:10"}}
        return httpx.Response(200, content=raw) if raw is not None else httpx.Response(200, json=payload)

    mock_http(monkeypatch, handler)
    reader = getattr(transport, "read_windchill_bom", None)
    assert reader is not None, "Windchill currently has no BOM transport"
    result = await reader(
        "https://windchill.example", "bearer", {"token": "vendor-secret"},
        part_id="OR:wt.part.WTPart:1", navigation_id="OR:wt.filter.NavigationCriteria:10",
    )
    assert len(requests) == 2
    assert all(sentinel not in str(result) for sentinel in ["vendor-secret", "nonce-sentinel", "session-sentinel"])
    rows, actual_source_count = result
    assert actual_source_count == source_count
    return rows


@pytest.mark.asyncio
async def test_authenticated_complete_bom_preserves_shared_counts_and_session(monkeypatch):
    rows = await read(monkeypatch, structure())
    assert len(rows) == 4
    assert rolled_up_multiplier(rows, "OR:wt.part.WTPart:4") == 8


@pytest.mark.asyncio
async def test_distinct_usage_links_sum_without_collapsing_part_identities(monkeypatch):
    root = structure()
    root["Components"].append(node(2, [node(4, quantity=3, link=13)], quantity=1, link=15))
    # Same part number/name can belong to distinct part revisions; IDs stay distinct.
    root["Components"][1]["Part"].update(Number="2", Name="Part 2")
    rows = await read(monkeypatch, root, source_count=6)
    assert len(rows) == 4
    assert rolled_up_multiplier(rows, "OR:wt.part.WTPart:4") == 11


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", [
    "permission", "unresolved", "truncated", "missing_children", "leaf_with_children",
    "unit", "fraction", "missing_quantity", "duplicate_usage", "conflicting_structure",
    "wrong_root", "cycle",
])
async def test_incomplete_or_ambiguous_bom_never_becomes_importable(monkeypatch, defect):
    root = structure()
    child = root["Components"][0]
    if defect == "permission": root["HasUnresolvedObjectsByAccessRights"] = True
    elif defect == "unresolved": child["Resolved"] = False
    elif defect == "truncated": child["Components@odata.nextLink"] = "https://other.example/leak"
    elif defect == "missing_children": del child["Components"]
    elif defect == "leaf_with_children": child["HasChildren"] = False
    elif defect == "unit": child["PartUse"]["Unit"]["Value"] = "kg"
    elif defect == "fraction": child["PartUse"]["Quantity"] = 2.5
    elif defect == "missing_quantity": del child["PartUse"]["Quantity"]
    elif defect == "duplicate_usage": root["Components"].append(deepcopy(child))
    elif defect == "conflicting_structure":
        altered = deepcopy(child)
        altered["PartUse"]["ID"] = "OR:wt.part.WTPartUsageLink:15"
        altered["Components"][0]["PartUse"]["Quantity"] = 7
        root["Components"].append(altered)
    elif defect == "wrong_root": root["Part"]["ID"] = "OR:wt.part.WTPart:9"
    elif defect == "cycle": child["Components"][0]["Part"] = deepcopy(root["Part"])
    with pytest.raises(transport.ConnectorConnectionError):
        await read(monkeypatch, root)


@pytest.mark.asyncio
async def test_decimal_quantity_is_not_rounded_into_a_whole_part(monkeypatch):
    raw = json.dumps(structure()).replace('"Quantity": 2,', '"Quantity": 2.0000000000000001,')
    with pytest.raises(transport.ConnectorConnectionError):
        await read(monkeypatch, {}, raw=raw)


@pytest.mark.asyncio
async def test_bom_selector_cannot_inject_an_odata_path(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("invalid selector sent"))
    reader = getattr(transport, "read_windchill_bom", None)
    assert reader is not None, "Windchill currently has no BOM transport"
    with pytest.raises(transport.ConnectorConnectionError):
        await reader("https://windchill.example", "bearer", {"token": "sentinel"}, part_id="1')/other", navigation_id=None)
