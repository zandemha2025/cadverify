"""Regression PROD-018: a CSV must not become evidence of a vendor API run."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.services import integration_service as svc


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_id", [
    "sap_s4hana_product_bom_readonly",
    "windchill_part_bom_readonly",
])
@pytest.mark.parametrize("mode", [svc.MODE_DRY_RUN, svc.MODE_IMPORT])
async def test_csv_cannot_claim_a_sandbox_api_run(connector_id, mode, monkeypatch):
    session = AsyncMock()
    session.add = MagicMock()
    importer = AsyncMock()
    monkeypatch.setattr(svc.manifest_service, "import_manifest", importer)

    with pytest.raises(HTTPException) as error:
        await svc.run_connector_csv(
            session,
            org_id="audit-org",
            user_id=1,
            connector_id=connector_id,
            raw=b"part_id\nAUDIT-CUBE\n",
            mode=mode,
        )

    assert error.value.status_code == 400
    assert "CSV" in error.value.detail
    importer.assert_not_awaited()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
