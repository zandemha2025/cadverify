import math

from src.services.analysis_service import server_timing_header


def test_server_timing_uses_fixed_stage_order_and_numeric_durations():
    header = server_timing_header({
        "total": 20.04,
        "upload_read": 1.16,
        "parse": 3.26,
        "context": 12.74,
        "tenant_secret": 999.0,
    })
    assert header == "upload_read;dur=1.2, parse;dur=3.3, context;dur=12.7, total;dur=20.0"
    assert "tenant" not in header


def test_server_timing_drops_invalid_values_and_empty_input():
    assert server_timing_header(None) is None
    assert server_timing_header({}) is None
    assert server_timing_header({
        "parse": -1.0,
        "context": math.inf,
        "total": math.nan,
    }) is None
