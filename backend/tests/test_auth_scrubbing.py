import json

from src.auth.scrubbing import _KEY_RE, scrub_processor, sentry_before_send


def test_regex_matches():
    m = _KEY_RE.search(
        "request with key cv_live_abcd1234_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx ok"
    )
    assert m is not None


def test_scrub_processor_redacts_string_values():
    ev = {"msg": "token=cv_live_abcd1234_xxxx", "user_id": 42}
    out = scrub_processor(None, None, ev)
    assert "cv_live_" not in out["msg"] or "***REDACTED***" in out["msg"]
    assert "***REDACTED***" in out["msg"]
    assert out["user_id"] == 42


def test_scrub_processor_redacts_authorization_header_key():
    ev = {"Authorization": "Bearer cv_live_xxx", "other": "fine"}
    out = scrub_processor(None, None, ev)
    assert out["Authorization"] == "***REDACTED***"


def test_scrub_processor_handles_nested_dict():
    ev = {"req": {"headers": {"authorization": "Bearer cv_live_xxx"}, "body": "ok"}}
    out = scrub_processor(None, None, ev)
    assert out["req"]["headers"]["authorization"] == "***REDACTED***"


def test_sentry_before_send_scrubs_nested_json():
    event = {
        "message": "error for cv_live_abcd_xxxxxxxxxxxx",
        "extra": {"headers": {"Authorization": "Bearer cv_live_ee_ffff"}},
        "breadcrumbs": [{"message": "cv_live_hhh_iiii"}],
    }
    out = sentry_before_send(event, None)
    assert "cv_live_" not in json.dumps(out) or "***REDACTED***" in json.dumps(out)
    # stronger: no raw cv_live_ token survives (only the redacted marker)
    dump = json.dumps(out)
    # redacted marker itself contains "cv_live_***REDACTED***" — filter it out
    assert dump.replace("cv_live_***REDACTED***", "") .find("cv_live_") == -1


def test_sentry_before_send_noop_when_clean():
    event = {"message": "nothing sensitive here"}
    out = sentry_before_send(event, None)
    assert out is event
