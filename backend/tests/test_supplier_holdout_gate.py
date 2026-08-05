"""Protected supplier-quote evidence is a mandatory, fail-closed release gate."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.costing.supplier_holdout import (
    SCHEMA,
    SupplierHoldoutError,
    decode_and_validate_evidence,
    parse_evidence_json,
    validate_evidence,
)


RELEASE = "a" * 40
NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)


def valid_payload() -> dict:
    return {
        "schema": SCHEMA,
        "release_sha": RELEASE,
        "generated_at": "2026-07-11T12:00:00Z",
        "expires_at": "2026-08-10T12:00:00Z",
        "n_parts": 24,
        "n_suppliers": 3,
        "mean_abs_pct_error": 0.22,
        "p90_abs_pct_error": 0.44,
        "process_median_bias": {
            "additive": -0.14,
            "cnc": 0.12,
            "injection_molding": 0.20,
        },
        "process_part_counts": {
            "additive": 8,
            "cnc": 10,
            "injection_molding": 6,
        },
        "process_supplier_counts": {
            "additive": 3,
            "cnc": 3,
            "injection_molding": 3,
        },
        "provenance_locked": True,
        "license_reviewed": True,
        "holdout_excluded_from_tuning": True,
        "corpus_sha256": "1" * 64,
        "quotes_sha256": "2" * 64,
        "results_sha256": "3" * 64,
        "approval_sha256": "4" * 64,
        "reviewer_id": "reviewer@example.com",
        "approval_id": "GRC-approval-2026-0712",
    }


def test_valid_release_bound_supplier_holdout_passes():
    evidence = validate_evidence(
        valid_payload(), expected_release_sha=RELEASE, now=NOW
    )

    assert evidence.n_parts == 24
    assert evidence.n_suppliers == 3
    assert evidence.max_process_median_bias == 0.20


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("release_sha",), "b" * 40, "requested release SHA"),
        (("n_parts",), 19, "at least 20"),
        (("n_suppliers",), 2, "at least 3"),
        (("mean_abs_pct_error",), 0.31, "MAPE"),
        (("p90_abs_pct_error",), 0.51, "P90"),
        (("process_median_bias", "cnc"), -0.26, "cnc"),
        (("process_part_counts", "additive"), 4, "at least 5"),
        (("process_supplier_counts", "cnc"), 2, "at least 3"),
        (("provenance_locked",), False, "provenance_locked"),
        (("license_reviewed",), False, "license_reviewed"),
        (("holdout_excluded_from_tuning",), False, "excluded"),
        (("reviewer_id",), "TBD", "placeholder"),
        (("corpus_sha256",), "not-a-hash", "SHA-256"),
    ],
)
def test_threshold_or_provenance_failure_blocks(path, value, message):
    payload = deepcopy(valid_payload())
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(SupplierHoldoutError, match=message):
        validate_evidence(payload, expected_release_sha=RELEASE, now=NOW)


def test_missing_launch_process_family_blocks():
    payload = valid_payload()
    del payload["process_median_bias"]["injection_molding"]

    with pytest.raises(SupplierHoldoutError, match="injection_molding"):
        validate_evidence(payload, expected_release_sha=RELEASE, now=NOW)


def test_process_count_maps_must_match_bias_families_and_cover_holdout():
    mismatched = valid_payload()
    del mismatched["process_part_counts"]["injection_molding"]
    with pytest.raises(SupplierHoldoutError, match="exactly"):
        validate_evidence(mismatched, expected_release_sha=RELEASE, now=NOW)

    undercounted = valid_payload()
    undercounted["process_part_counts"] = {
        "additive": 5,
        "cnc": 5,
        "injection_molding": 5,
    }
    with pytest.raises(SupplierHoldoutError, match="full quoted holdout"):
        validate_evidence(undercounted, expected_release_sha=RELEASE, now=NOW)


def test_stale_expired_and_future_evidence_block():
    stale = valid_payload()
    stale["generated_at"] = "2026-05-01T00:00:00Z"
    with pytest.raises(SupplierHoldoutError, match="older than 30 days"):
        validate_evidence(stale, expected_release_sha=RELEASE, now=NOW)

    expired = valid_payload()
    expired["expires_at"] = "2026-07-12T11:59:59Z"
    with pytest.raises(SupplierHoldoutError, match="expired"):
        validate_evidence(expired, expected_release_sha=RELEASE, now=NOW)

    future = valid_payload()
    future["generated_at"] = "2026-07-12T12:06:00Z"
    with pytest.raises(SupplierHoldoutError, match="future"):
        validate_evidence(future, expected_release_sha=RELEASE, now=NOW)


def test_schema_is_exact_and_duplicate_json_keys_are_rejected():
    payload = valid_payload()
    payload["unreviewed_extension"] = True
    with pytest.raises(SupplierHoldoutError, match="extra"):
        validate_evidence(payload, expected_release_sha=RELEASE, now=NOW)

    with pytest.raises(SupplierHoldoutError, match="duplicate JSON key"):
        parse_evidence_json(b'{"schema":"one","schema":"two"}')


def test_base64_decoder_returns_stable_evidence_digest():
    raw = json.dumps(valid_payload(), sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.b64encode(raw).decode("ascii")

    evidence, digest = decode_and_validate_evidence(
        encoded, expected_release_sha=RELEASE, now=NOW
    )

    assert evidence.release_sha == RELEASE
    assert len(digest) == 64


def test_missing_or_malformed_protected_secret_blocks():
    with pytest.raises(SupplierHoldoutError, match="is required"):
        decode_and_validate_evidence("", expected_release_sha=RELEASE, now=NOW)
    with pytest.raises(SupplierHoldoutError, match="valid base64"):
        decode_and_validate_evidence("%%%", expected_release_sha=RELEASE, now=NOW)


def test_ci_entrypoint_exports_only_validated_evidence_hash(tmp_path):
    payload = valid_payload()
    current = datetime.now(timezone.utc).replace(microsecond=0)
    payload["generated_at"] = (current - timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    payload["expires_at"] = (current + timedelta(days=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    output_file = tmp_path / "github-output"
    env_file = tmp_path / "github-env"
    backend = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "CADVERIFY_RELEASE_SHA": RELEASE,
        "CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_B64": base64.b64encode(raw).decode(),
        "GITHUB_OUTPUT": str(output_file),
        "GITHUB_ENV": str(env_file),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "scripts/ci/validate_supplier_holdout.py",
        ],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output_file.read_text().startswith("evidence_sha256=")
    assert env_file.read_text().startswith(
        "CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_SHA256="
    )
    assert payload["reviewer_id"] not in result.stdout
    assert payload["approval_id"] not in result.stdout
