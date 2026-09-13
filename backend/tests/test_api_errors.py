import json

import pytest

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("detail", "failure_class", "repairable"),
    [
        ("Empty file uploaded", "empty_file", False),
        ("Unsupported file type: .obj. Use .stl", "unsupported_type", False),
        (
            "File does not appear to be a valid STEP file (missing ISO-10303-21 header).",
            "invalid_or_incomplete_export",
            False,
        ),
        ("Failed to parse mesh file", "tessellation_failed", False),
    ],
)
async def test_cad_upload_400_carries_repair_why(detail, failure_class, repairable):
    from fastapi import HTTPException, Request
    from src.api.errors import structured_http_error_handler

    request = Request({"type": "http", "method": "POST", "path": "/api/v1/validate", "headers": []})
    response = await structured_http_error_handler(request, HTTPException(status_code=400, detail=detail))
    body = json.loads(response.body)
    assert body["code"] == "BAD_REQUEST"
    assert body["message"] == detail
    assert body["diagnosis"]["failure_class"] == failure_class
    assert body["diagnosis"]["repairable"] is repairable
    assert body["diagnosis"]["plain_reason"]
    assert body["diagnosis"]["next_action"]
    assert body["diagnosis"]["location"] is None


@pytest.mark.asyncio
async def test_unknown_400_does_not_invent_cad_diagnosis():
    from fastapi import HTTPException, Request
    from src.api.errors import structured_http_error_handler

    request = Request({"type": "http", "method": "POST", "path": "/api/v1/validate", "headers": []})
    response = await structured_http_error_handler(request, HTTPException(status_code=400, detail="Unknown process: nope"))
    body = json.loads(response.body)
    assert "diagnosis" not in body
