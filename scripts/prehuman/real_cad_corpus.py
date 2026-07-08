#!/usr/bin/env python3
"""Pre-human real CAD corpus gate.

Downloads a small, pinned subset of public NIST CAD corpora, then exercises the
same local STEP/native-CAD boundary the app uses before any customer CAD is
involved. The only network access allowed is fixture download; parse/cost runs
with AF_INET/AF_INET6 sockets blocked.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import warnings
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
OUTPUT_ROOT = Path(os.getenv("E2E_ARTIFACT_DIR", REPO_ROOT / ".gstack" / "qa-reports"))
RUN_ID = os.getenv("E2E_RUN_ID") or dt.datetime.utcnow().strftime("%Y-%m-%d")
MAX_ZIP_BYTES = int(os.getenv("PREHUMAN_MAX_ZIP_BYTES", str(80 * 1024 * 1024)))
PER_CASE_TIMEOUT_SEC = float(os.getenv("PREHUMAN_CASE_TIMEOUT_SEC", "35"))

NIST_LANDING_PAGE = (
    "https://www.nist.gov/ctl/smart-connected-systems-division/"
    "smart-connected-manufacturing-systems-group/mbe-pmi-0"
)

SOURCES = {
    "nist_pmi_step": {
        "name": "NIST PMI STEP Files",
        "landing_page": NIST_LANDING_PAGE,
        "document_url": "https://www.nist.gov/document/nist-pmi-step-files",
        "resolved_zip_url": (
            "https://www.nist.gov/system/files/documents/noindex/2024/06/19/"
            "NIST-PMI-STEP-Files.zip"
        ),
        "expected_sha256": "8fa78429e6d8d9b0d7681d223b6aa9ec98c3772185c55b1a0e3679b21c181911",
        "expected_bytes": 13976599,
    },
    "nist_mtc_assembly": {
        "name": "NIST MTC Assembly",
        "landing_page": NIST_LANDING_PAGE,
        "document_url": "https://www.nist.gov/document/nist-cad-models-mtc-assembly",
        "resolved_zip_url": (
            "https://www.nist.gov/system/files/documents/noindex/2025/09/04/"
            "NIST-MTC-Assembly.zip"
        ),
        "expected_sha256": "9aeb53e54f682ea1732857d06a7f0513c71667a2d84407396325fa6ce5340bbc",
        "expected_bytes": 15861580,
    },
}

CASES = [
    {
        "id": "NIST-AP203-GEOM-FTC-11",
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/AP203 geometry only/nist_ftc_11_asme1_rb.stp",
        "family": "FTC",
        "schema": "AP203",
        "cad_category": "geometry_only",
        "expected_outcome": "OK",
    },
    {
        "id": "NIST-AP203-GEOM-CTC-03",
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/AP203 geometry only/nist_ctc_03_asme1_rc.stp",
        "family": "CTC",
        "schema": "AP203",
        "cad_category": "geometry_only",
        "expected_outcome": "OK",
    },
    {
        "id": "NIST-AP203-GEOM-FTC-09",
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/AP203 geometry only/nist_ftc_09_asme1_rd.stp",
        "family": "FTC",
        "schema": "AP203",
        "cad_category": "geometry_only",
        "expected_outcome": "OK",
    },
    {
        "id": "NIST-AP203-PMI-CTC-01",
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/AP203 with PMI/nist_ctc_01_asme1_ap203.stp",
        "family": "CTC",
        "schema": "AP203",
        "cad_category": "pmi_present_step",
        "expected_outcome": "OK",
    },
    {
        "id": "NIST-AP242-CTC-03",
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/nist_ctc_03_asme1_ap242-e2.stp",
        "family": "CTC",
        "schema": "AP242",
        "cad_category": "pmi_present_step",
        "expected_outcome": "OK",
    },
    {
        "id": "NIST-AP242-STC-06",
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/nist_stc_06_asme1_ap242-e3.stp",
        "family": "STC",
        "schema": "AP242",
        "cad_category": "pmi_present_step",
        "expected_outcome": "OK",
    },
    {
        "id": "NIST-AP242-STC-08",
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/nist_stc_08_asme1_ap242-e3.stp",
        "family": "STC",
        "schema": "AP242",
        "cad_category": "pmi_present_step",
        "expected_outcome": "OK",
    },
    {
        "id": "NIST-AP242-STC-09",
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/nist_stc_09_asme1_ap242-e3.stp",
        "family": "STC",
        "schema": "AP242",
        "cad_category": "pmi_present_step",
        "expected_outcome": "OK",
    },
    {
        "id": "NIST-AP242-CTC-05-INVALID",
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/nist_ctc_05_asme1_ap242-e1.stp",
        "family": "CTC",
        "schema": "AP242",
        "cad_category": "problem_geometry_control",
        "expected_outcome": "GEOMETRY_INVALID",
    },
    {
        "id": "NIST-MTC-SOLIDWORKS-ASSEMBLY-UNSUPPORTED",
        "source": "nist_mtc_assembly",
        "inner_path": "NIST-MTC-Assembly/SolidWorks/nist_mtc_crada_assembly_rev-D.SLDASM",
        "family": "MTC",
        "schema": "native_solidworks",
        "cad_category": "native_assembly_control",
        "expected_outcome": "UNSUPPORTED_SUFFIX",
    },
]

ALLOWED_PROVENANCE = {"MEASURED", "SHOP", "USER", "DEFAULT"}


def cache_root() -> Path:
    data_dir = os.getenv("CADVERIFY_DATA_DIR")
    base = Path(data_dir).expanduser() if data_dir else REPO_ROOT / "data"
    return base.resolve() / "real-cad-cache"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def allowlisted_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "www.nist.gov"
        and parsed.path.startswith("/system/files/documents/noindex/")
        and parsed.path.endswith(".zip")
    )


def download_source(source_id: str, source: Dict[str, Any]) -> Dict[str, Any]:
    url = source["resolved_zip_url"]
    if not allowlisted_url(url):
        raise RuntimeError("refusing non-allowlisted source URL: %s" % url)

    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / ("%s.zip" % source_id)
    meta_path = root / ("%s.meta.json" % source_id)
    meta: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    if not target.exists() or sha256_file(target) != source["expected_sha256"]:
        tmp = target.with_suffix(".zip.tmp")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "cadverify-prehuman-ci/1.0",
                "Accept": "application/zip,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
            length = int(resp.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                raise RuntimeError("%s did not return Content-Length" % source_id)
            if length > MAX_ZIP_BYTES:
                raise RuntimeError("%s is over the configured ZIP cap" % source_id)
            data = resp.read(MAX_ZIP_BYTES + 1)
            if len(data) > MAX_ZIP_BYTES:
                raise RuntimeError("%s exceeded max ZIP bytes while downloading" % source_id)
            tmp.write_bytes(data)
            meta = {
                "last_modified": resp.headers.get("Last-Modified"),
                "content_length": length,
                "content_type": resp.headers.get("Content-Type"),
                "downloaded_at": dt.datetime.utcnow().isoformat() + "Z",
            }
        actual = sha256_file(tmp)
        if actual != source["expected_sha256"]:
            raise RuntimeError(
                "%s SHA-256 mismatch: expected %s got %s"
                % (source_id, source["expected_sha256"], actual)
            )
        tmp.replace(target)
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    actual_size = target.stat().st_size
    actual_sha = sha256_file(target)
    if actual_size != source["expected_bytes"]:
        raise RuntimeError("%s byte size changed: %s" % (source_id, actual_size))
    if actual_sha != source["expected_sha256"]:
        raise RuntimeError("%s cached SHA-256 changed: %s" % (source_id, actual_sha))

    return {
        "id": source_id,
        "name": source["name"],
        "landing_page": source["landing_page"],
        "document_url": source["document_url"],
        "resolved_zip_url": url,
        "zip_path": str(target),
        "zip_sha256": actual_sha,
        "zip_bytes": actual_size,
        "last_modified": meta.get("last_modified"),
        "content_type": meta.get("content_type"),
    }


def read_inner(zip_path: Path, inner_path: str) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(inner_path)


def run_worker(source: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--zip",
        source["zip_path"],
        "--inner",
        case["inner_path"],
        "--expected",
        case["expected_outcome"],
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=PER_CASE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return {
            "outcome": "TIMEOUT",
            "status": "FAIL",
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "error": "case exceeded %.1fs subprocess timeout" % PER_CASE_TIMEOUT_SEC,
        }

    parsed: Optional[Dict[str, Any]] = None
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            parsed = json.loads(line)
            break
    if parsed is None:
        return {
            "outcome": "WORKER_ERROR",
            "status": "FAIL",
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-1000:],
            "stderr_tail": (proc.stderr or "")[-1000:],
        }
    parsed["elapsed_sec"] = parsed.get("elapsed_sec") or round(time.perf_counter() - start, 3)
    if proc.returncode != 0 and parsed.get("status") == "PASS":
        parsed["status"] = "FAIL"
        parsed["error"] = "worker exited nonzero: %s" % proc.returncode
    return parsed


def finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, dict):
        return all(finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(finite(v) for v in value)
    return True


def unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def validate_case(case: Dict[str, Any], result: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    expected = case["expected_outcome"]
    outcome = result.get("outcome")
    if outcome != expected:
        failures.append("expected %s, got %s" % (expected, outcome))

    runtime_warnings = result.get("runtime_warnings") or []
    if runtime_warnings:
        failures.append("runtime warnings emitted during parse/cost")

    if result.get("network_egress_blocked") is not True:
        failures.append("network egress guard was not active")

    if expected == "OK":
        geometry = result.get("geometry") or {}
        if not finite(geometry):
            failures.append("geometry contains non-finite values")
        if geometry.get("face_count", 0) <= 0:
            failures.append("face_count is not positive")
        if geometry.get("volume_cm3", 0) <= 0:
            failures.append("volume_cm3 is not positive")
        if geometry.get("watertight") is not True:
            failures.append("expected watertight real single-solid geometry")
        if not result.get("decision"):
            failures.append("missing decision block")
        if result.get("estimate_count", 0) <= 0:
            failures.append("missing cost estimates")
        if not result.get("line_items_sum_ok"):
            failures.append("unit cost does not match rounded line-item sum")
        bad_provenance = set(result.get("provenance_values") or []) - ALLOWED_PROVENANCE
        if bad_provenance:
            failures.append("unexpected provenance tags: %s" % sorted(bad_provenance))
        if not result.get("finite_report"):
            failures.append("report contains non-finite values")

    if expected == "GEOMETRY_INVALID":
        geometry = result.get("geometry") or {}
        if not finite(geometry):
            failures.append("invalid-geometry report contains non-finite values")
        if geometry.get("face_count", 0) <= 0:
            failures.append("invalid-geometry control did not produce measured face count")

    if expected == "UNSUPPORTED_SUFFIX":
        message = result.get("error") or ""
        if "Unsupported file type" not in message:
            failures.append("unsupported-native control did not use the suffix boundary")

    pmi = result.get("pmi_check") or {}
    if case["cad_category"] == "pmi_present_step" and pmi.get("status") == "checked":
        if pmi.get("has_pmi") is not True:
            failures.append("XDE PMI check ran but did not detect PMI")

    return failures


def run_main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    sources = {sid: download_source(sid, source) for sid, source in SOURCES.items()}

    case_results = []
    for case in CASES:
        source = sources[case["source"]]
        inner_bytes = read_inner(Path(source["zip_path"]), case["inner_path"])
        result = run_worker(source, case)
        failures = validate_case(case, result)
        case_results.append(
            {
                **case,
                "source_document_url": SOURCES[case["source"]]["document_url"],
                "source_zip_sha256": source["zip_sha256"],
                "inner_sha256": sha256_bytes(inner_bytes),
                "inner_bytes": len(inner_bytes),
                "status": "PASS" if not failures else "FAIL",
                "failures": failures,
                **result,
            }
        )

    failed = [item for item in case_results if item["status"] != "PASS"]
    ap242_ok = [
        item for item in case_results
        if item["schema"] == "AP242" and item["expected_outcome"] == "OK" and item["status"] == "PASS"
    ]
    stc_ok = [
        item for item in case_results
        if item["family"] == "STC" and item["expected_outcome"] == "OK" and item["status"] == "PASS"
    ]
    ap203_geom_ok = [
        item for item in case_results
        if item["schema"] == "AP203"
        and item["cad_category"] == "geometry_only"
        and item["expected_outcome"] == "OK"
        and item["status"] == "PASS"
    ]
    acceptance = {
        "min_ap242_pmi_step_ok": len(ap242_ok) >= 3,
        "min_stc_step_ok": len(stc_ok) >= 2,
        "min_ap203_geometry_step_ok": len(ap203_geom_ok) >= 2,
        "native_cad_unsupported_control": any(
            item["expected_outcome"] == "UNSUPPORTED_SUFFIX" and item["status"] == "PASS"
            for item in case_results
        ),
        "geometry_invalid_control": any(
            item["expected_outcome"] == "GEOMETRY_INVALID" and item["status"] == "PASS"
            for item in case_results
        ),
        "all_cases_passed": not failed,
    }
    status = "PASS" if all(acceptance.values()) else "NEEDS_FIXES"
    data = {
        "status": status,
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "run_id": RUN_ID,
        "source_boundary": (
            "Public NIST CAD/STEP test files exercise pre-human parser, geometry, "
            "cost, and unsupported-native-CAD boundaries. They are not customer "
            "pilot evidence and do not imply NIST endorsement."
        ),
        "truth_boundary": (
            "STEP is triangulated through gmsh/OCC for DFM and cost. Semantic PMI/GD&T "
            "is recorded as skipped unless OCP XDE is available."
        ),
        "cache_dir": str(cache_root()),
        "sources": list(sources.values()),
        "acceptance": acceptance,
        "cases": case_results,
        "failed": failed,
    }

    json_path = OUTPUT_ROOT / ("prehuman-real-cad-corpus-%s.json" % RUN_ID)
    md_path = OUTPUT_ROOT / ("qa-report-prehuman-real-cad-corpus-%s.md" % RUN_ID)
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown(data), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "cases": len(case_results),
                "passed": len(case_results) - len(failed),
                "failed": [item["id"] for item in failed],
                "report": str(md_path),
            },
            indent=2,
        )
    )
    return 0 if status == "PASS" else 1


def pmi_check(data: bytes, filename: str) -> Dict[str, Any]:
    if not filename.lower().endswith((".step", ".stp")):
        return {"status": "not_applicable"}
    from src.parsers.step_ap242_parser import is_ap242_supported, parse_ap242_from_bytes

    if not is_ap242_supported():
        return {"status": "skipped_xde_unavailable", "has_pmi": None}
    doc = parse_ap242_from_bytes(data, filename)
    return {
        "status": "checked",
        "has_pmi": bool(doc.has_pmi),
        "shape_label_count": len(doc.shape_labels),
    }


@contextlib.contextmanager
def block_network_sockets():
    real_socket = socket.socket
    blocked = {socket.AF_INET, socket.AF_INET6}

    def guarded_socket(family=socket.AF_INET, *args, **kwargs):
        if family in blocked:
            raise AssertionError("network socket opened during CAD parse/cost")
        return real_socket(family, *args, **kwargs)

    socket.socket = guarded_socket  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket = real_socket  # type: ignore[assignment]


def provenance_values(report: Dict[str, Any]) -> List[str]:
    values = []
    for assumption in report.get("assumptions") or []:
        values.append(assumption.get("provenance"))
    for estimate in report.get("estimates") or []:
        for driver in estimate.get("drivers") or []:
            values.append(driver.get("provenance"))
    return unique([value for value in values if isinstance(value, str)])


def line_items_sum_ok(report: Dict[str, Any]) -> bool:
    for estimate in report.get("estimates") or []:
        unit_cost = estimate.get("unit_cost_usd")
        line_items = estimate.get("line_items") or {}
        if not isinstance(unit_cost, (int, float)) or not line_items:
            return False
        total = round(sum(float(v) for v in line_items.values()), 2)
        if abs(float(unit_cost) - total) >= 0.02:
            return False
    return True


def run_worker_mode(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(BACKEND_ROOT))
    from fastapi import HTTPException

    from src.api.routes import _parse_mesh, _run_cost_engine
    from src.costing import EstimateOptions, estimate_decision, report_to_dict

    data = read_inner(Path(args.zip), args.inner)
    filename = Path(args.inner).name
    start = time.perf_counter()

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            # Keep noisy C-extension output out of the JSON path when possible.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with block_network_sockets():
                    pmi = pmi_check(data, filename)
                    mesh, suffix = _parse_mesh(data, filename)
                    result, mesh, features = _run_cost_engine(mesh, filename)
                    report = estimate_decision(
                        result,
                        mesh,
                        features,
                        EstimateOptions(
                            quantities=[50, 5000],
                            material_class="aluminum",
                            material_class_is_user=True,
                            region="US",
                            region_is_user=True,
                        ),
                    )
                    report_dict = report_to_dict(report)
        runtime_warnings = unique(str(item.message) for item in caught)

        outcome = report.status
        output = {
            "status": "PASS",
            "outcome": outcome,
            "suffix": suffix,
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "network_egress_blocked": True,
            "runtime_warnings": runtime_warnings,
            "pmi_check": pmi,
            "geometry": report_dict.get("geometry"),
            "decision": report_dict.get("decision"),
            "estimate_count": len(report_dict.get("estimates") or []),
            "line_items_sum_ok": line_items_sum_ok(report_dict),
            "provenance_values": provenance_values(report_dict),
            "finite_report": finite(report_dict),
            "first_estimate": (report_dict.get("estimates") or [None])[0],
        }
    except HTTPException as exc:
        detail = exc.detail
        message = detail if isinstance(detail, str) else json.dumps(detail, sort_keys=True)
        if exc.status_code == 400 and "Unsupported file type" in message:
            outcome = "UNSUPPORTED_SUFFIX"
        else:
            outcome = "HTTP_%s" % exc.status_code
        output = {
            "status": "PASS" if outcome == args.expected else "FAIL",
            "outcome": outcome,
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "network_egress_blocked": True,
            "runtime_warnings": [],
            "pmi_check": {"status": "not_reached"},
            "error": message,
            "http_status": exc.status_code,
        }
    except Exception as exc:
        output = {
            "status": "FAIL",
            "outcome": "PARSER_OR_COST_EXCEPTION",
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "network_egress_blocked": True,
            "runtime_warnings": [],
            "pmi_check": {"status": "unknown"},
            "error": "%s: %s" % (type(exc).__name__, str(exc)[:300]),
        }

    print(json.dumps(output, sort_keys=True))
    return 0 if output.get("status") == "PASS" else 1


def markdown(data: Dict[str, Any]) -> str:
    rows = "\n".join(
        "| {status} | {id} | {schema} | {family} | {expected} | {outcome} | {secs} | {failures} |".format(
            status=item["status"],
            id=item["id"],
            schema=item["schema"],
            family=item["family"],
            expected=item["expected_outcome"],
            outcome=item.get("outcome"),
            secs=item.get("elapsed_sec"),
            failures="; ".join(item.get("failures") or []) or "pass",
        )
        for item in data["cases"]
    )
    sources = "\n".join(
        "- {name}: {document} -> {zip} ({sha}, {size} bytes)".format(
            name=source["name"],
            document=source["document_url"],
            zip=source["resolved_zip_url"],
            sha=source["zip_sha256"],
            size=source["zip_bytes"],
        )
        for source in data["sources"]
    )
    return """# Pre-Human Real CAD Corpus Gate

- Run: {run_id}
- Status: {status}
- Boundary: {boundary}
- Truth boundary: {truth_boundary}
- Cache: `{cache_dir}`

## Sources

{sources}

## Acceptance

```json
{acceptance}
```

## Cases

| Result | Case | Schema | Family | Expected | Outcome | Seconds | Evidence |
| --- | --- | --- | --- | --- | --- | ---: | --- |
{rows}
""".format(
        run_id=data["run_id"],
        status=data["status"],
        boundary=data["source_boundary"],
        truth_boundary=data["truth_boundary"],
        cache_dir=data["cache_dir"],
        sources=sources,
        acceptance=json.dumps(data["acceptance"], indent=2, sort_keys=True),
        rows=rows,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--zip")
    parser.add_argument("--inner")
    parser.add_argument("--expected")
    return parser.parse_args()


if __name__ == "__main__":
    parsed_args = parse_args()
    if parsed_args.worker:
        raise SystemExit(run_worker_mode(parsed_args))
    raise SystemExit(run_main())
