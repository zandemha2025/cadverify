"""Capture a Sentry event locally and assert cv_live_ is scrubbed.

Dumps the scrubbed payload to backend/build/captured_sentry.json so the CI
grep step can independently verify no raw cv_live_ token leaks through.
"""
import json
import os

from src.auth.scrubbing import sentry_before_send


def test_captured_event_has_no_cv_live():
    simulated_event = {
        "message": "auth failed for cv_live_abcd1234_" + "x" * 32,
        "extra": {
            "headers": {"Authorization": "Bearer cv_live_eeeeffff_" + "y" * 32}
        },
        "breadcrumbs": [
            {
                "category": "http",
                "message": "GET /api/v1/validate with cv_live_gggghhhh_"
                + "z" * 32,
            }
        ],
    }
    scrubbed = sentry_before_send(simulated_event, None)
    dump = json.dumps(scrubbed)
    os.makedirs("build", exist_ok=True)
    with open("build/captured_sentry.json", "w") as f:
        f.write(dump)
    # The redacted marker literally contains "cv_live_***REDACTED***"; only
    # non-redacted occurrences of cv_live_ indicate a leak.
    remaining = dump.replace("cv_live_***REDACTED***", "")
    assert "cv_live_" not in remaining, f"LEAK: {dump}"
