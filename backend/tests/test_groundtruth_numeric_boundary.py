"""Non-finite actuals must never enter stored records or calibration inputs."""
import pytest

from src.costing.groundtruth import GroundTruthRecord
from src.services import groundtruth_service as svc


@pytest.mark.parametrize("field", ["actual_unit_cost_usd", "actual_machine_hours", "actual_setup_hours", "actual_labor_hours", "actual_inspection_hours", "actual_cycle_seconds"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_dataclass_and_csv_reject_nonfinite_actuals(field, value):
    payload = {"part_id": "numeric-check", "process": "sls", "quantity": 10, "actual_unit_cost_usd": 12, field: value}
    with pytest.raises(ValueError, match=field):
        GroundTruthRecord(**payload)
    rows, errors = svc.parse_ground_truth_csv(
        ",".join(payload) + "\n" + ",".join(str(v) for v in payload.values()) + "\n"
    )
    assert rows == []
    assert len(errors) == 1 and field in errors[0]["reason"]


@pytest.mark.asyncio
async def test_unstorable_quantity_is_rejected_before_any_database_work():
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()
    session.add = MagicMock()
    payload = {"part_id": "too-many", "process": "sls", "quantity": 2**31, "actual_unit_cost_usd": 12}
    with pytest.raises(ValueError, match="quantity"):
        await svc.ingest_record(session, "org", None, payload)
    session.execute.assert_not_called()
    rows, errors = svc.parse_ground_truth_csv(
        "part_id,process,quantity,actual_unit_cost_usd\ntoo-many,sls,2147483648,12\n"
    )
    assert rows == [] and "quantity" in errors[0]["reason"]


def test_zero_hours_and_max_quantity_remain_valid():
    row = GroundTruthRecord("valid", "sls", 2**31 - 1, 12, actual_machine_hours=0)
    assert row.actual_machine_hours == 0
    rows, errors = svc.parse_ground_truth_csv(
        "part_id,process,quantity,actual_unit_cost_usd,actual_machine_hours\nvalid,sls,2147483647,12,0\n"
    )
    assert len(rows) == 1 and errors == []
