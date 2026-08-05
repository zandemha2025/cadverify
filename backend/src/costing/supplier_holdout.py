"""Fail-closed validation for protected supplier-quote holdout evidence.

The underlying CAD files, supplier quotes, and approval records can be
confidential, so production promotion consumes a small signed-off summary plus
cryptographic hashes of the retained evidence. The summary is release-bound,
short-lived, schema-locked, and cannot be produced by the synthetic regression
fixtures in this repository.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, NoReturn


SCHEMA = "cadverify-supplier-holdout-v1"
EVIDENCE_ENV = "CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_B64"
RELEASE_ENV = "CADVERIFY_RELEASE_SHA"
REQUIRED_PROCESS_FAMILIES = frozenset(
    {"additive", "cnc", "injection_molding"}
)
MIN_PARTS_PER_PROCESS = 5
MIN_SUPPLIERS_PER_PROCESS = 3
MAX_EVIDENCE_AGE = timedelta(days=30)
MAX_VALIDITY_WINDOW = timedelta(days=90)
_CLOCK_SKEW = timedelta(minutes=5)
_MAX_DECODED_BYTES = 64 * 1024
_HEX_40 = re.compile(r"\A[0-9a-f]{40}\Z")
_HEX_64 = re.compile(r"\A[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:@/+\-]{2,127}\Z")
_PLACEHOLDER_IDENTIFIERS = {
    "unknown",
    "none",
    "n/a",
    "na",
    "tbd",
    "todo",
    "placeholder",
    "test",
}
_EXPECTED_FIELDS = frozenset(
    {
        "schema",
        "release_sha",
        "generated_at",
        "expires_at",
        "n_parts",
        "n_suppliers",
        "mean_abs_pct_error",
        "p90_abs_pct_error",
        "process_median_bias",
        "process_part_counts",
        "process_supplier_counts",
        "provenance_locked",
        "license_reviewed",
        "holdout_excluded_from_tuning",
        "corpus_sha256",
        "quotes_sha256",
        "results_sha256",
        "approval_sha256",
        "reviewer_id",
        "approval_id",
    }
)


class SupplierHoldoutError(ValueError):
    """The protected supplier evidence is absent, malformed, stale, or failing."""


@dataclass(frozen=True)
class SupplierQuoteEvidence:
    """Validated aggregate metrics and provenance for one immutable release."""

    release_sha: str
    generated_at: datetime
    expires_at: datetime
    n_parts: int
    n_suppliers: int
    mean_abs_pct_error: float
    p90_abs_pct_error: float
    process_median_bias: dict[str, float]
    process_part_counts: dict[str, int]
    process_supplier_counts: dict[str, int]
    provenance_locked: bool
    license_reviewed: bool
    holdout_excluded_from_tuning: bool
    corpus_sha256: str
    quotes_sha256: str
    results_sha256: str
    approval_sha256: str
    reviewer_id: str
    approval_id: str

    @property
    def max_process_median_bias(self) -> float:
        return max(
            self.process_median_bias.values(), key=abs, default=0.0
        )


def _fail(message: str) -> NoReturn:
    raise SupplierHoldoutError(message)


def _parse_timestamp(value: Any, field: str) -> datetime:
    if type(value) is not str or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value
    ):
        _fail(f"{field} must be an exact UTC timestamp ending in Z")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        _fail(f"{field} is not a valid UTC timestamp")


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        _fail(f"{field} must be a finite number")
    return result


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        _fail(f"{field} must be a positive integer")
    return value


def _identifier(value: Any, field: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        _fail(f"{field} must be a non-placeholder retained-evidence identifier")
    if value.casefold() in _PLACEHOLDER_IDENTIFIERS:
        _fail(f"{field} must not be a placeholder")
    return value


def _sha256(value: Any, field: str) -> str:
    if type(value) is not str or not _HEX_64.fullmatch(value):
        _fail(f"{field} must be a lowercase SHA-256 digest")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            _fail(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def parse_evidence_json(raw: bytes) -> Mapping[str, Any]:
    """Parse UTF-8 JSON while rejecting oversized input and duplicate keys."""
    if not raw or len(raw) > _MAX_DECODED_BYTES:
        _fail("supplier holdout evidence is empty or too large")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupplierHoldoutError(
            "supplier holdout evidence must be valid UTF-8 JSON"
        ) from exc
    if type(payload) is not dict:
        _fail("supplier holdout evidence must be a JSON object")
    return payload


def validate_evidence(
    payload: Mapping[str, Any],
    *,
    expected_release_sha: str,
    now: datetime | None = None,
) -> SupplierQuoteEvidence:
    """Validate the exact v1 contract and all commercial accuracy thresholds."""
    if type(payload) is not dict:
        _fail("supplier holdout evidence must be a JSON object")
    fields = frozenset(payload)
    if fields != _EXPECTED_FIELDS:
        missing = sorted(_EXPECTED_FIELDS - fields)
        extra = sorted(fields - _EXPECTED_FIELDS)
        _fail(
            "supplier holdout schema fields differ "
            f"(missing={missing}, extra={extra})"
        )
    if payload["schema"] != SCHEMA:
        _fail(f"schema must equal {SCHEMA}")
    if not _HEX_40.fullmatch(expected_release_sha):
        _fail("expected release SHA must be 40 lowercase hexadecimal characters")
    if payload["release_sha"] != expected_release_sha:
        _fail("supplier holdout evidence is not bound to the requested release SHA")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        _fail("validation clock must be timezone-aware")
    current = current.astimezone(timezone.utc)
    generated_at = _parse_timestamp(payload["generated_at"], "generated_at")
    expires_at = _parse_timestamp(payload["expires_at"], "expires_at")
    if generated_at > current + _CLOCK_SKEW:
        _fail("supplier holdout evidence was generated in the future")
    if current - generated_at > MAX_EVIDENCE_AGE:
        _fail("supplier holdout evidence is older than 30 days")
    if expires_at <= current:
        _fail("supplier holdout evidence has expired")
    if expires_at <= generated_at:
        _fail("expires_at must be later than generated_at")
    if expires_at - generated_at > MAX_VALIDITY_WINDOW:
        _fail("supplier holdout validity window exceeds 90 days")

    n_parts = _positive_int(payload["n_parts"], "n_parts")
    n_suppliers = _positive_int(payload["n_suppliers"], "n_suppliers")
    if n_parts < 20:
        _fail("supplier holdout requires at least 20 independent quoted parts")
    if n_suppliers < 3:
        _fail("supplier holdout requires quotes from at least 3 suppliers")

    mape = _number(payload["mean_abs_pct_error"], "mean_abs_pct_error")
    p90 = _number(payload["p90_abs_pct_error"], "p90_abs_pct_error")
    if mape < 0 or mape > 0.30:
        _fail("supplier holdout MAPE must be between 0 and 0.30")
    if p90 < 0 or p90 > 0.50:
        _fail("supplier holdout P90 absolute error must be between 0 and 0.50")

    raw_biases = payload["process_median_bias"]
    if type(raw_biases) is not dict:
        _fail("process_median_bias must be an object")
    missing_families = REQUIRED_PROCESS_FAMILIES - frozenset(raw_biases)
    if missing_families:
        _fail(
            "process_median_bias is missing launch families: "
            + ", ".join(sorted(missing_families))
        )
    biases: dict[str, float] = {}
    for family, value in raw_biases.items():
        if type(family) is not str or not re.fullmatch(
            r"[a-z][a-z0-9_]{1,63}", family
        ):
            _fail("process_median_bias contains an invalid process family")
        bias = _number(value, f"process_median_bias.{family}")
        if abs(bias) > 0.25:
            _fail(f"process median bias for {family} exceeds +/-0.25")
        biases[family] = bias

    def _count_map(field: str, *, minimum: int, ceiling: int) -> dict[str, int]:
        raw_counts = payload[field]
        if type(raw_counts) is not dict:
            _fail(f"{field} must be an object")
        if frozenset(raw_counts) != frozenset(biases):
            _fail(f"{field} must cover exactly the process median-bias families")
        counts: dict[str, int] = {}
        for family, value in raw_counts.items():
            count = _positive_int(value, f"{field}.{family}")
            if count < minimum:
                _fail(
                    f"{field}.{family} requires at least {minimum} independent "
                    "observations"
                )
            if count > ceiling:
                _fail(f"{field}.{family} cannot exceed its global total")
            counts[family] = count
        return counts

    process_part_counts = _count_map(
        "process_part_counts",
        minimum=MIN_PARTS_PER_PROCESS,
        ceiling=n_parts,
    )
    process_supplier_counts = _count_map(
        "process_supplier_counts",
        minimum=MIN_SUPPLIERS_PER_PROCESS,
        ceiling=n_suppliers,
    )
    if sum(process_part_counts.values()) < n_parts:
        _fail("process_part_counts do not account for the full quoted holdout")

    for field in (
        "provenance_locked",
        "license_reviewed",
        "holdout_excluded_from_tuning",
    ):
        if payload[field] is not True:
            _fail(f"{field} must be true")

    return SupplierQuoteEvidence(
        release_sha=expected_release_sha,
        generated_at=generated_at,
        expires_at=expires_at,
        n_parts=n_parts,
        n_suppliers=n_suppliers,
        mean_abs_pct_error=mape,
        p90_abs_pct_error=p90,
        process_median_bias=biases,
        process_part_counts=process_part_counts,
        process_supplier_counts=process_supplier_counts,
        provenance_locked=True,
        license_reviewed=True,
        holdout_excluded_from_tuning=True,
        corpus_sha256=_sha256(payload["corpus_sha256"], "corpus_sha256"),
        quotes_sha256=_sha256(payload["quotes_sha256"], "quotes_sha256"),
        results_sha256=_sha256(payload["results_sha256"], "results_sha256"),
        approval_sha256=_sha256(payload["approval_sha256"], "approval_sha256"),
        reviewer_id=_identifier(payload["reviewer_id"], "reviewer_id"),
        approval_id=_identifier(payload["approval_id"], "approval_id"),
    )


def decode_and_validate_evidence(
    encoded: str,
    *,
    expected_release_sha: str,
    now: datetime | None = None,
) -> tuple[SupplierQuoteEvidence, str]:
    """Decode a GitHub-safe base64 secret and return evidence plus its hash."""
    if not encoded:
        _fail(f"protected secret {EVIDENCE_ENV} is required")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SupplierHoldoutError(
            f"protected secret {EVIDENCE_ENV} is not valid base64"
        ) from exc
    evidence = validate_evidence(
        parse_evidence_json(raw),
        expected_release_sha=expected_release_sha,
        now=now,
    )
    return evidence, hashlib.sha256(raw).hexdigest()


def load_protected_evidence(
    *, now: datetime | None = None
) -> tuple[SupplierQuoteEvidence, str]:
    """Load the release SHA and protected evidence from the process environment."""
    return decode_and_validate_evidence(
        os.getenv(EVIDENCE_ENV, ""),
        expected_release_sha=os.getenv(RELEASE_ENV, ""),
        now=now,
    )
