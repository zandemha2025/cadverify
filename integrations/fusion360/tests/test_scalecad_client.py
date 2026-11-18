"""Pure-module tests for the Fusion add-in: the client (against a local
HTTP stub speaking the real contract) and the view model. No adsk import
anywhere — these run in CI with plain pytest.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scalecad_client import (  # noqa: E402
    DIRECT_STEP_LIMIT_BYTES, ScaleCadError, check_part, multipart_body,
)
import view_model as vm  # noqa: E402


# ---------------------------------------------------------------------------
# multipart
# ---------------------------------------------------------------------------

class TestMultipart:
    def test_carries_file_bytes_and_form_fields(self):
        blob = b"ISO-10303-21;" + bytes(range(256))
        body, ctype = multipart_body(
            "file", "bracket.step", blob, "application/step",
            {"qty": "50,5000", "region": "US"})
        assert ctype.startswith("multipart/form-data; boundary=scalecad")
        assert b'name="file"; filename="bracket.step"' in body
        assert b'name="qty"\r\n\r\n50,5000' in body
        assert b'name="region"\r\n\r\nUS' in body
        assert blob in body  # bytes arrive intact through the framing
        assert body.endswith(b"--\r\n")


# ---------------------------------------------------------------------------
# the client against a live local stub of the API contract
# ---------------------------------------------------------------------------

class _StubAPI(BaseHTTPRequestHandler):
    server_version = "stub"
    log_message = lambda *a, **k: None  # noqa: E731

    def _json(self, doc, status=200, headers=None):
        payload = json.dumps(doc).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        seen = self.server.seen
        seen.setdefault(self.path, []).append(
            {h.lower(): v for h, v in self.headers.items()})
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if self.path == "/api/v1/validate":
            if self.server.mode == "auth401":
                return self._json({"code": "auth_invalid", "detail": "bad key"}, 401)
            if self.server.mode == "busy429":
                return self._json({"code": "rate_limited"}, 429,
                                  headers={"Retry-After": "2"})
            return self._json({"overall_verdict": "issues", "best_process": "cnc_milling",
                               "universal_issues": [], "process_scores": [],
                               "geometry": {"bounding_box_mm": [100.0, 80.0, 12.0],
                                            "faces": 1234}})
        if self.path == "/api/v1/validate/cost":
            assert b"name=\"qty\"" in body
            return self._json({"estimates": [{"process": "cnc_milling", "quantity": 50,
                                              "unit_cost_usd": 12.5,
                                              "confidence": {"low_usd": 8.0, "high_usd": 18.0,
                                                             "validated": False}}],
                               "saved": {"id": "01J8TEST", "url": "/api/v1/cost-decisions/01J8TEST"}})
        if self.path == "/api/v1/uploads/multipart":
            return self._json({"upload_id": "up-1", "part_size_bytes": 1024 * 1024,
                               "parts": {}, "complete_url": "/api/v1/uploads/up-1/complete"}, 201)
        if self.path.startswith("/api/v1/uploads/up-1/parts/"):
            self.server.uploaded_parts += 1
            return self._json({"ok": True})
        if self.path == "/api/v1/uploads/up-1/complete":
            return self._json({"ok": True})
        if self.path == "/api/v1/checks":
            self.server.poll_count = 0
            return self._json({"id": "chk-1", "poll_url": "/api/v1/checks/chk-1"}, 202)
        self._json({"detail": "not found"}, 404)

    def do_PUT(self):
        self.do_POST()

    def do_GET(self):
        if self.path == "/api/v1/checks/chk-1":
            self.server.poll_count += 1
            if self.server.poll_count < 2:
                return self._json({"status": "measuring"})
            return self._json({"status": "done", "result": {
                "overall_verdict": "pass", "best_process": "sheet_metal",
                "universal_issues": [], "process_scores": [],
                "geometry": {"bounding_box_mm": [300, 200, 4], "faces": 99}}})
        self._json({"detail": "not found"}, 404)


@pytest.fixture(scope="module")
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubAPI)
    server.mode = "ok"
    server.seen = {}
    server.uploaded_parts = 0
    server.poll_count = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def _origin(stub):
    return f"http://127.0.0.1:{stub.server_address[1]}"


class TestClientContract:
    def test_direct_path_shares_one_check_id_across_both_calls(self, stub, tmp_path):
        result = check_part(_origin(stub), "cv_live_test", b"ISO-10303-21 stub;",
                            "bracket.step", friction_log=str(tmp_path / "f.jsonl"))
        v, c = result["validation"], result["cost"]
        assert v["overall_verdict"] == "issues"
        assert c["estimates"][0]["unit_cost_usd"] == 12.5
        ids_v = [h.get("x-part-check-id") for h in stub.seen["/api/v1/validate"]]
        ids_c = [h.get("x-part-check-id") for h in stub.seen["/api/v1/validate/cost"]]
        assert ids_v[0] == ids_c[0], "validate and cost must share the check id"
        uuid.UUID(ids_v[0])  # and it is a uuid

    def test_auth_error_maps_to_plain_words(self, stub):
        stub.mode = "auth401"
        try:
            with pytest.raises(ScaleCadError) as ei:
                check_part(_origin(stub), "cv_live_bad", b"x;", "p.step")
            assert "re-paste" in ei.value.advice
            assert ei.value.status == 401
        finally:
            stub.mode = "ok"

    def test_rate_limit_carries_retry_after(self, stub):
        stub.mode = "busy429"
        try:
            with pytest.raises(ScaleCadError) as ei:
                check_part(_origin(stub), "cv_live_test", b"x;", "p.step")
            assert ei.value.status == 429
            assert ei.value.retry_after_s == 2.0
            assert "wait and retry" in ei.value.advice
        finally:
            stub.mode = "ok"

    def test_oversize_step_takes_the_resumable_path(self, stub, tmp_path):
        big = b"9" * (DIRECT_STEP_LIMIT_BYTES + 1024)
        result = check_part(_origin(stub), "cv_live_test", big, "big.step",
                            friction_log=str(tmp_path / "f.jsonl"))
        assert "/api/v1/uploads/multipart" in stub.seen
        assert stub.uploaded_parts == (len(big) + 1024 * 1024 - 1) // (1024 * 1024)
        assert result["validation"]["overall_verdict"] == "pass"

    def test_friction_log_records_the_gate_events(self, stub, tmp_path):
        log = str(tmp_path / "friction.jsonl")
        check_part(_origin(stub), "cv_live_test", b"ISO;", "p.step", friction_log=log)
        events = [json.loads(l) for l in open(log)]
        kinds = {e["event"] for e in events}
        assert "check_ok" in kinds
        assert all({"t", "event"} <= set(e) for e in events)


# ---------------------------------------------------------------------------
# the view model
# ---------------------------------------------------------------------------

_VALIDATION = {
    "overall_verdict": "issues",
    "best_process": "cnc_turning",
    "geometry": {"bounding_box_mm": [120.0, 40.0, 40.0], "faces": 4567},
    "universal_issues": [
        {"code": "THIN_WALL", "severity": "ERROR", "message": "wall 0.4mm < 1.0mm",
         "fix_suggestion": "thicken the boss"},
    ],
    "process_scores": [
        {"process": "cnc_turning", "score": 0.8, "verdict": "issues", "issues": [
            {"code": "DEEP_HOLE", "severity": "WARNING", "message": "bore 27:1"}]},
    ],
}


class TestViewModel:
    def test_verdict_in_plain_words_with_best_route(self):
        line = vm.verdict_line(_VALIDATION)
        assert line.startswith("Issues to fix")
        assert "best route: cnc turning" in line

    def test_issues_sort_severity_first_and_carry_scope(self):
        rows = vm.top_issues(_VALIDATION)
        assert rows[0]["severity"] == "ERROR" and rows[0]["where"] == "whole part"
        assert rows[1]["severity"] == "WARNING" and rows[1]["where"] == "cnc turning"
        assert rows[0]["fix"] == "thicken the boss"

    def test_cost_rows_cheapest_first_and_mark_unvalidated(self):
        cost = {"estimates": [
            {"process": "cnc_5axis", "quantity": 50, "unit_cost_usd": 90.0,
             "confidence": {"low_usd": 60, "high_usd": 120, "validated": True}},
            {"process": "cnc_turning", "quantity": 50, "unit_cost_usd": 12.5,
             "confidence": {"low_usd": 8, "high_usd": 18, "validated": False}},
        ]}
        rows = vm.cost_rows(cost)
        assert rows[0]["process"] == "cnc turning"
        assert rows[0]["validated"] is False
        assert rows[1]["validated"] is True

    def test_deep_link_uses_saved_id_else_history(self):
        assert vm.deep_link("https://api.example", {"saved": {"id": "01J"}}) == \
            "https://api.example/analyses/01J"
        assert vm.deep_link("https://api.example", {}) == "https://api.example/history"

    def test_build_never_loses_the_band(self):
        model = vm.build("https://api.example", _VALIDATION,
                         {"estimates": _COST["estimates"]})
        assert model["costs"][0]["band_low"] is not None
        assert model["deep_link"].startswith("https://")


_COST = {"estimates": [
    {"process": "cnc_turning", "quantity": 50, "unit_cost_usd": 12.5,
     "confidence": {"low_usd": 8, "high_usd": 18, "validated": False}}]}
