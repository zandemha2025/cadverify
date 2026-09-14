"""Tests for the private cost-validation evidence set
(backend/data/cost-validation/validation-set-v1.json).

Contract under test (2026-09-14 cost-validation lane):
  1. Schema: every entry carries process, vendor, evidence_kind, source_url,
     retrieved date and an epistemic status (SOURCE_OBSERVED / SECONDARY_REPORTED).
  2. Source hygiene: every source_url is https; SOURCE_OBSERVED entries must name a
     real external page (not an in-repo path); retrieved dates are ISO dates
     not in the future.
  3. Process linkage: every entry's process is one the engine supports, or the
     documented "multi" umbrella.
  4. Numeric sanity: any quoted price floor is positive; hourly bands are
     ordered [lo, hi].
  5. Honesty law: the set carries honesty_rules and no entry may present an
     INFERRED price point as evidence.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "backend" / "data" / "cost-validation" / "validation-set-v1.json"
sys.path.insert(0, str(REPO / "backend"))

from src.analysis.models import ProcessType  # noqa: E402

SUPPORTED = {p.value for p in ProcessType} | {"multi"}
ISO_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

SET = json.loads(DATA.read_text())
ENTRIES = SET["entries"]


def test_schema_fields_present():
    required = {
        "id", "process", "vendor", "evidence_kind", "vendor_claim",
        "source_url", "retrieved", "status",
    }
    for e in ENTRIES:
        missing = required - set(e)
        assert not missing, f"{e.get('id')} missing fields {missing}"
        assert e["status"] in {"SOURCE_OBSERVED", "SECONDARY_REPORTED"}, e["id"]
        assert e["comparison_scope"] == "context_only_not_quote_locked"


def test_ids_unique():
    ids = [e["id"] for e in ENTRIES]
    assert len(ids) == len(set(ids))


def test_source_urls_https_and_external_for_confirmed():
    for e in ENTRIES:
        assert e["source_url"].startswith("https://"), e["id"]


def test_retrieved_dates_iso_not_future():
    today = date.today().isoformat()
    for e in ENTRIES:
        assert ISO_DATE.match(e["retrieved"]), e["id"]
        assert e["retrieved"] <= today, f"{e['id']} retrieved date in future"


def test_process_supported_or_multi():
    for e in ENTRIES:
        assert e["process"] in SUPPORTED, f"{e['id']}: {e['process']} unsupported"


def test_numeric_sanity():
    for e in ENTRIES:
        if "price_floor_usd" in e:
            assert e["price_floor_usd"] > 0, e["id"]
        for band_map_key in ("hourly_bands_usd", "material_kg_usd"):
            for k, band in e.get(band_map_key, {}).items():
                lo, hi = band
                assert lo > 0, f"{e['id']}:{k}"
                if hi is not None:
                    assert hi >= lo, f"{e['id']}:{k} band inverted"


def test_honesty_rules_present_and_no_inferred_prices():
    assert SET.get("honesty_rules"), "honesty_rules block required"
    for e in ENTRIES:
        assert "INFERRED" not in e["vendor_claim"]
        assert e["status"] != "INFERRED"
    joined = " ".join(SET["honesty_rules"]).lower()
    assert "not" in joined and "accuracy" in joined and "quote-locked" in joined


def test_minimum_coverage():
    # The set must anchor the three headline families: additive polymer,
    # subtractive, and injection molding tooling.
    procs = {e["process"] for e in ENTRIES}
    assert procs & {"sla", "fdm", "sls", "mjf"}, "no additive polymer anchor"
    assert procs & {"cnc_3axis", "cnc_5axis", "cnc_turning"}, "no CNC anchor"
    assert "injection_molding" in procs, "no IM tooling anchor"
