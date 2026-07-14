#!/usr/bin/env python3
"""Pre-human real CAD corpus gate.

Downloads a small, pinned subset of public NIST CAD corpora, then exercises the
same local STEP/native-CAD boundary the app uses before any customer CAD is
involved. The only network access allowed is fixture download; parse/cost runs
with AF_INET/AF_INET6 sockets blocked.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
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
RUN_ID = os.getenv("E2E_RUN_ID") or dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
MAX_ZIP_BYTES = int(os.getenv("PREHUMAN_MAX_ZIP_BYTES", str(80 * 1024 * 1024)))
# The production route owns a 60-second parse budget. The outer corpus worker
# needs enough time to observe that bounded result and shut its parser children
# down cleanly instead of pre-empting the very crash/timeout containment it is
# supposed to verify.
PER_CASE_TIMEOUT_SEC = float(os.getenv("PREHUMAN_CASE_TIMEOUT_SEC", "90"))

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

def nist_step_case(
    case_id: str,
    inner_path: str,
    family: str,
    schema: str,
    cad_category: str,
) -> Dict[str, str]:
    return {
        "id": case_id,
        "source": "nist_pmi_step",
        "inner_path": "NIST-PMI-STEP-Files/" + inner_path,
        "family": family,
        "schema": schema,
        "cad_category": cad_category,
        "expected_outcome": "OK",
    }


# Every STEP file in the pinned NIST archive is an explicit product gate. This
# prevents a hand-picked happy subset from hiding a broken schema/family branch.
CASES = [
    *[
        nist_step_case(
            f"NIST-AP203-GEOM-CTC-{number:02d}",
            f"AP203 geometry only/nist_ctc_{number:02d}_asme1_{revision}.stp",
            "CTC",
            "AP203",
            "geometry_only",
        )
        for number, revision in [(1, "rd"), (2, "rc"), (3, "rc"), (4, "rd"), (5, "rd")]
    ],
    *[
        nist_step_case(
            f"NIST-AP203-GEOM-FTC-{number:02d}",
            f"AP203 geometry only/nist_ftc_{number:02d}_asme1_{revision}.stp",
            "FTC",
            "AP203",
            "geometry_only",
        )
        for number, revision in [
            (6, "rd"),
            (7, "rd"),
            (8, "rc"),
            (9, "rd"),
            (10, "rb"),
            (11, "rb"),
        ]
    ],
    *[
        nist_step_case(
            f"NIST-AP203-PMI-CTC-{number:02d}",
            f"AP203 with PMI/nist_ctc_{number:02d}_asme1_ap203.stp",
            "CTC",
            "AP203",
            "pmi_present_step",
        )
        for number in range(1, 6)
    ],
    *[
        nist_step_case(
            f"NIST-AP242-CTC-{number:02d}",
            f"nist_ctc_{number:02d}_asme1_ap242-{edition}.stp",
            "CTC",
            "AP242",
            "pmi_present_step",
        )
        for number, edition in [(1, "e1"), (2, "e2"), (3, "e2"), (4, "e1"), (5, "e1")]
    ],
    *[
        nist_step_case(
            f"NIST-AP242-FTC-{number:02d}",
            f"nist_ftc_{number:02d}_asme1_ap242-{edition}.stp",
            "FTC",
            "AP242",
            "pmi_present_step",
        )
        for number, edition in [
            (6, "e2"),
            (7, "e2"),
            (8, "e2"),
            (9, "e1"),
            (10, "e2"),
            (11, "e2"),
        ]
    ],
    nist_step_case(
        "NIST-AP242-FTC-08-TESSELLATED",
        "nist_ftc_08_asme1_ap242-e1-tg.stp",
        "FTC",
        "AP242",
        "embedded_tessellation_step",
    ),
    *[
        nist_step_case(
            f"NIST-AP242-STC-{number:02d}",
            f"nist_stc_{number:02d}_asme1_ap242-{edition}.stp",
            "STC",
            "AP242",
            "pmi_present_step",
        )
        for number, edition in [(6, "e3"), (7, "e3"), (8, "e3"), (9, "e3"), (10, "e2")]
    ],
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

# The exhaustive CASES matrix above remains the pre-human product gate.  The
# browser set is intentionally much smaller: one file per materially different
# UI/parser branch, with AP242 e1 shared by the embedded-tessellation exemplar.
# Keep this plan data-only so ``--browser-plan`` is a deterministic, offline
# regression surface and materialization can inherit the exhaustive case facts.
BROWSER_SET_SCHEMA_VERSION = 1
BROWSER_SET_ID = "nist-representative-browser-v1"
BROWSER_REQUIRED_COVERAGE = (
    "ap203_geometry",
    "ap203_pmi",
    "ap242_e1",
    "ap242_e2",
    "ap242_e3",
    "ap242_embedded_tessellation",
    "tracked_periodic_step",
    "native_assembly_unsupported",
)
BROWSER_OPTIONAL_COVERAGE = ("iges",)
TRACKED_PERIODIC_PATH = Path("backend/tests/assets/nist_periodic_ctc05.stp")
TRACKED_PERIODIC_SHA256 = "5140b8f41fa1d0a069ea978e28c92a597f47220d0a11e667b79ff5f7c7243b86"

BROWSER_REPRESENTATIVE_CASES: List[Dict[str, Any]] = [
    {
        "id": "BROWSER-AP203-GEOMETRY",
        "corpus_case_id": "NIST-AP203-GEOM-CTC-01",
        "filename": "01-ap203-geometry-ctc01.stp",
        "schema_edition": "AP203",
        "coverage_tags": ["ap203_geometry"],
        "support_status": "supported",
        "expected_browser_outcome": "verified_and_saved",
    },
    {
        "id": "BROWSER-AP203-PMI",
        "corpus_case_id": "NIST-AP203-PMI-CTC-01",
        "filename": "02-ap203-pmi-ctc01.stp",
        "schema_edition": "AP203",
        "coverage_tags": ["ap203_pmi"],
        "support_status": "supported",
        "expected_browser_outcome": "verified_and_saved",
    },
    {
        "id": "BROWSER-AP242-E1-TESSELLATED",
        "corpus_case_id": "NIST-AP242-FTC-08-TESSELLATED",
        "filename": "03-ap242-e1-embedded-tessellation-ftc08.stp",
        "schema_edition": "AP242 e1",
        "coverage_tags": ["ap242_e1", "ap242_embedded_tessellation"],
        "support_status": "supported",
        "expected_browser_outcome": "verified_and_saved",
    },
    {
        "id": "BROWSER-AP242-E2",
        "corpus_case_id": "NIST-AP242-CTC-03",
        "filename": "04-ap242-e2-ctc03.stp",
        "schema_edition": "AP242 e2",
        "coverage_tags": ["ap242_e2"],
        "support_status": "supported",
        "expected_browser_outcome": "verified_and_saved",
    },
    {
        "id": "BROWSER-AP242-E3",
        "corpus_case_id": "NIST-AP242-STC-06",
        "filename": "05-ap242-e3-stc06.stp",
        "schema_edition": "AP242 e3",
        "coverage_tags": ["ap242_e3"],
        "support_status": "supported",
        "expected_browser_outcome": "verified_and_saved",
    },
    {
        "id": "BROWSER-TRACKED-PERIODIC-STEP",
        "tracked_path": TRACKED_PERIODIC_PATH.as_posix(),
        "filename": "06-tracked-periodic-ctc05.stp",
        "family": "CTC",
        "schema": "AP203",
        "schema_edition": "AP203",
        "cad_category": "tracked_periodic_surface_step",
        "coverage_tags": ["tracked_periodic_step"],
        "support_status": "supported",
        "expected_browser_outcome": "verified_and_saved",
    },
    {
        "id": "BROWSER-SYNTHESIZED-IGES",
        "synthetic_kind": "gmsh_occ_box_iges",
        "filename": "07-synthesized-occ-box.iges",
        "family": "SYNTHETIC-ROUNDTRIP",
        "schema": "IGES",
        "schema_edition": "IGES 5.x",
        "cad_category": "synthesized_real_iges",
        "coverage_tags": ["iges"],
        "support_status": "supported",
        "expected_browser_outcome": "verified_and_saved",
        "optional": True,
    },
    {
        "id": "BROWSER-NATIVE-SOLIDWORKS-ASSEMBLY-UNSUPPORTED",
        "corpus_case_id": "NIST-MTC-SOLIDWORKS-ASSEMBLY-UNSUPPORTED",
        "filename": "08-native-solidworks-assembly.sldasm",
        "schema_edition": "SolidWorks native assembly",
        "coverage_tags": ["native_assembly_unsupported"],
        "support_status": "unsupported",
        "expected_browser_outcome": "unsupported_native_assembly",
    },
]

FTC08_EQUIVALENCE_IDS = [
    "NIST-AP203-GEOM-FTC-08",
    "NIST-AP242-FTC-08",
    "NIST-AP242-FTC-08-TESSELLATED",
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


def download_source(
    source_id: str,
    source: Dict[str, Any],
    *,
    offline: bool = False,
) -> Dict[str, Any]:
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
        if offline:
            raise RuntimeError(
                "%s is not present with its pinned SHA-256 in offline mode" % source_id
            )
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


def browser_plan() -> Dict[str, Any]:
    """Return the small browser plan without touching network, cache, or gmsh."""
    exhaustive = {case["id"]: case for case in CASES}
    selections: List[Dict[str, Any]] = []
    for order, selected in enumerate(BROWSER_REPRESENTATIVE_CASES, start=1):
        item = dict(selected)
        corpus_case_id = item.get("corpus_case_id")
        if corpus_case_id:
            corpus_case = exhaustive.get(corpus_case_id)
            if corpus_case is None:
                raise RuntimeError("browser plan references unknown corpus case %s" % corpus_case_id)
            item = {**corpus_case, **item, "source_kind": "nist_archive_member"}
        elif item.get("tracked_path"):
            item["source_kind"] = "tracked_repository_fixture"
        elif item.get("synthetic_kind"):
            item["source_kind"] = "synthesized_iges"
        else:
            raise RuntimeError("browser plan case %s has no source" % item.get("id"))
        item["order"] = order
        selections.append(item)

    return {
        "schema_version": BROWSER_SET_SCHEMA_VERSION,
        "set_id": BROWSER_SET_ID,
        "exhaustive_nist_step_case_count": sum(
            1 for case in CASES if case["source"] == "nist_pmi_step"
        ),
        "required_coverage": list(BROWSER_REQUIRED_COVERAGE),
        "optional_coverage": list(BROWSER_OPTIONAL_COVERAGE),
        "selections": selections,
    }


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as fh:
        tmp = Path(fh.name)
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _canonicalize_iges_header(data: bytes) -> bytes:
    """Remove writer time/user entropy while preserving valid 80-column IGES."""
    text = data.decode("ascii")
    lines = text.splitlines()
    if not lines or any(len(line) != 80 for line in lines):
        raise RuntimeError("gmsh IGES writer did not emit 80-column records")
    global_indexes = [index for index, line in enumerate(lines) if line[72] == "G"]
    if not global_indexes:
        raise RuntimeError("gmsh IGES output has no global section")

    payload = "".join(lines[index][:72].rstrip() for index in global_indexes)
    payload, timestamp_count = re.subn(
        r"15H\d{8}\.\d{6}", "15H19700101.000000", payload
    )
    payload, user_count = re.subn(
        r",\d+H[^,]*,,11,0,", ",9Hcadverify,,11,0,", payload, count=1
    )
    if timestamp_count < 1 or user_count != 1 or not payload.rstrip().endswith(";"):
        raise RuntimeError("could not canonicalize the gmsh IGES global header")

    capacity = 72 * len(global_indexes)
    if len(payload) > capacity:
        raise RuntimeError("canonical IGES global section exceeded its record capacity")
    payload = payload.ljust(capacity)
    for sequence, index in enumerate(global_indexes, start=1):
        chunk = payload[(sequence - 1) * 72 : sequence * 72]
        lines[index] = "%sG%07d" % (chunk, sequence)
    return ("\n".join(lines) + "\n").encode("ascii")


@contextlib.contextmanager
def _silence_native_output():
    """Keep C/C++ writer diagnostics from corrupting the JSON CLI stream."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved_stdout = os.dup(sys.stdout.fileno())
    saved_stderr = os.dup(sys.stderr.fileno())
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, sys.stdout.fileno())
        os.dup2(devnull, sys.stderr.fileno())
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_stdout, sys.stdout.fileno())
        os.dup2(saved_stderr, sys.stderr.fileno())
        os.close(saved_stdout)
        os.close(saved_stderr)
        os.close(devnull)


class BrowserIgesUnavailable(RuntimeError):
    """A real IGES was generated, but the isolated production route refused it."""

    def __init__(self, message: str, candidate: bytes, generator: Dict[str, Any]):
        super().__init__(message)
        self.candidate_sha256 = sha256_bytes(candidate)
        self.candidate_bytes = len(candidate)
        self.generator = generator


def _probe_canonical_iges_with_production_route(path: Path) -> Dict[str, Any]:
    """Probe in a fresh process so writer state cannot make the reader pass."""
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(BACKEND_ROOT)
        if not current_pythonpath
        else str(BACKEND_ROOT) + os.pathsep + current_pythonpath
    )
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--browser-iges-probe",
                str(path),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=PER_CASE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "isolated production IGES probe exceeded %.1fs" % PER_CASE_TIMEOUT_SEC
        ) from exc

    parsed: Optional[Dict[str, Any]] = None
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                pass
            break
    if proc.returncode != 0 or not parsed or parsed.get("status") != "PASS":
        detail = (parsed or {}).get("error") or (proc.stderr or proc.stdout or "probe failed")[-500:]
        raise RuntimeError("isolated production parser rejected IGES: %s" % detail)
    # Runtime is useful in the private probe process but intentionally excluded
    # from the materialized manifest: identical bytes must produce identical JSON.
    return {
        key: parsed[key]
        for key in (
            "status",
            "suffix",
            "face_count",
            "watertight",
            "volume_cm3",
            "bbox_mm",
            "dfm_verdict",
            "assembly_kind",
            "assembly_part_count",
            "network_egress_blocked",
        )
    }


def synthesize_box_iges() -> tuple[bytes, Dict[str, Any]]:
    """Create and re-open a real 20 mm OCC box as deterministic IGES bytes."""
    try:
        import gmsh  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("gmsh is not installed") from exc

    with tempfile.TemporaryDirectory(prefix="cadverify-browser-iges-") as temp_dir:
        raw_path = Path(temp_dir) / "box.iges"
        canonical_path = Path(temp_dir) / "canonical-box.iges"
        initialized = False
        try:
            gmsh.initialize()
            initialized = True
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("General.Verbosity", 0)
            gmsh.model.add("cadverify_representative_box")
            gmsh.model.occ.addBox(0, 0, 0, 20, 20, 20)
            gmsh.model.occ.synchronize()
            gmsh.write(str(raw_path))
        finally:
            if initialized:
                gmsh.finalize()

        canonical = _canonicalize_iges_header(raw_path.read_bytes())
        canonical_path.write_bytes(canonical)

        # Re-open the canonicalized artifact through the same OCC reader.  This
        # proves header normalization did not turn a real solid into plausible
        # looking text that only passes a suffix/magic check.
        initialized = False
        with _silence_native_output():
            try:
                gmsh.initialize()
                initialized = True
                gmsh.option.setNumber("General.Terminal", 0)
                gmsh.option.setNumber("General.Verbosity", 0)
                gmsh.model.add("cadverify_canonical_iges_reopen")
                imported = gmsh.model.occ.importShapes(str(canonical_path))
                gmsh.model.occ.synchronize()
                if not imported or max(dimension for dimension, _tag in imported) < 2:
                    raise RuntimeError("canonical IGES did not re-open as OCC geometry")
                # OpenCASCADE's IGES writer represents a closed box as six trimmed
                # surfaces rather than one native volume entity.  That is the exact
                # shell representation the production mesher consumes and closes.
                bbox = gmsh.model.getBoundingBox(-1, -1)
                extents = [bbox[3 + index] - bbox[index] for index in range(3)]
                if any(abs(value - 20.0) > 1e-3 for value in extents):
                    raise RuntimeError("canonical IGES box extents changed: %s" % extents)
            finally:
                if initialized:
                    gmsh.finalize()

        generator = {
            "generator": "gmsh/OpenCASCADE",
            "gmsh_version": str(getattr(gmsh, "__version__", "unknown")),
            "shape": "OCC box",
            "dimensions_mm": [20, 20, 20],
            "imported_entities_after_reopen": len(imported),
            "highest_imported_dimension": max(dimension for dimension, _tag in imported),
            "canonical_header_timestamp": "19700101.000000",
            "canonical_header_author": "cadverify",
        }
        try:
            production_probe = _probe_canonical_iges_with_production_route(canonical_path)
        except RuntimeError as exc:
            raise BrowserIgesUnavailable(str(exc), canonical, generator) from exc
        generator["isolated_production_probe"] = production_probe
        return canonical, generator


_FIXTURE_BINDING_FIELDS = (
    "id",
    "relative_path",
    "file_sha256",
    "bytes",
    "support_status",
    "expected_browser_outcome",
    "source_ref",
)


def fixture_set_binding_sha256(fixtures: Iterable[Dict[str, Any]]) -> str:
    """Bind exact fixture bytes and truth labels with a language-neutral hash."""
    rows = []
    for fixture in sorted(fixtures, key=lambda item: item["id"]):
        values = [str(fixture[field]) for field in _FIXTURE_BINDING_FIELDS]
        if any("\t" in value or "\n" in value for value in values):
            raise RuntimeError("fixture binding fields may not contain tabs or newlines")
        rows.append("\t".join(values))
    return sha256_bytes(("\n".join(rows) + "\n").encode("utf-8"))


def materialize_browser_set(output_dir: Path, *, offline: bool = False) -> tuple[Path, Dict[str, Any]]:
    """Materialize the bounded browser corpus and its deterministic manifest."""
    output_dir = output_dir.expanduser().resolve()
    files_dir = output_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    plan = browser_plan()
    selections = plan["selections"]
    source_ids = sorted(
        {item["source"] for item in selections if item["source_kind"] == "nist_archive_member"}
    )
    sources = {
        source_id: download_source(source_id, SOURCES[source_id], offline=offline)
        for source_id in source_ids
    }

    fixtures: List[Dict[str, Any]] = []
    omissions: List[Dict[str, Any]] = []
    for selected in selections:
        fixture_bytes: bytes
        source: Dict[str, Any]
        source_ref: str
        if selected["source_kind"] == "nist_archive_member":
            archive = sources[selected["source"]]
            fixture_bytes = read_inner(Path(archive["zip_path"]), selected["inner_path"])
            source_ref = "%s:%s:%s" % (
                selected["source"],
                archive["zip_sha256"],
                selected["inner_path"],
            )
            source = {
                "kind": "nist_archive_member",
                "source_id": selected["source"],
                "document_url": SOURCES[selected["source"]]["document_url"],
                "archive_sha256": archive["zip_sha256"],
                "archive_bytes": archive["zip_bytes"],
                "inner_path": selected["inner_path"],
            }
        elif selected["source_kind"] == "tracked_repository_fixture":
            tracked_path = (REPO_ROOT / selected["tracked_path"]).resolve()
            fixture_bytes = tracked_path.read_bytes()
            actual = sha256_bytes(fixture_bytes)
            if actual != TRACKED_PERIODIC_SHA256:
                raise RuntimeError(
                    "tracked periodic STEP SHA-256 mismatch: expected %s got %s"
                    % (TRACKED_PERIODIC_SHA256, actual)
                )
            source_ref = "repository:%s:%s" % (selected["tracked_path"], actual)
            source = {
                "kind": "tracked_repository_fixture",
                "repository_path": selected["tracked_path"],
                "pinned_sha256": actual,
                "origin": "NIST CTC 05 periodic-surface regression fixture",
            }
        elif selected["source_kind"] == "synthesized_iges":
            try:
                fixture_bytes, generator = synthesize_box_iges()
            except Exception as exc:
                if not selected.get("optional"):
                    raise
                omission: Dict[str, Any] = {
                    "id": selected["id"],
                    "coverage_tags": selected["coverage_tags"],
                    "reason": "real IGES browser fixture unavailable: %s: %s"
                    % (type(exc).__name__, str(exc)[:240]),
                }
                if isinstance(exc, BrowserIgesUnavailable):
                    omission.update(
                        {
                            "candidate_sha256": exc.candidate_sha256,
                            "candidate_bytes": exc.candidate_bytes,
                            "generator": exc.generator,
                            "production_probe_passed": False,
                        }
                    )
                omissions.append(omission)
                continue
            source_ref = "synthetic:gmsh:%s:occ-box-20mm" % generator["gmsh_version"]
            source = {"kind": "synthesized_iges", **generator}
        else:
            raise RuntimeError("unknown browser source kind %s" % selected["source_kind"])

        relative_path = (Path("files") / selected["filename"]).as_posix()
        target = output_dir / relative_path
        digest = sha256_bytes(fixture_bytes)
        _atomic_write(target, fixture_bytes)
        if sha256_file(target) != digest or target.stat().st_size != len(fixture_bytes):
            raise RuntimeError("materialized fixture verification failed for %s" % selected["id"])

        fixtures.append(
            {
                "id": selected["id"],
                "order": selected["order"],
                "filename": selected["filename"],
                "relative_path": relative_path,
                "file_sha256": digest,
                "bytes": len(fixture_bytes),
                "family": selected["family"],
                "schema": selected["schema"],
                "schema_edition": selected["schema_edition"],
                "cad_category": selected["cad_category"],
                "coverage_tags": selected["coverage_tags"],
                "support_status": selected["support_status"],
                "expected_browser_outcome": selected["expected_browser_outcome"],
                "source_ref": source_ref,
                "source": source,
            }
        )

    coverage = {
        tag: [fixture["id"] for fixture in fixtures if tag in fixture["coverage_tags"]]
        for tag in (*BROWSER_REQUIRED_COVERAGE, *BROWSER_OPTIONAL_COVERAGE)
    }
    missing_required = [tag for tag in BROWSER_REQUIRED_COVERAGE if not coverage[tag]]
    if missing_required:
        raise RuntimeError("browser fixture set is missing required coverage: %s" % missing_required)

    archive_manifest = []
    for source_id in source_ids:
        source = sources[source_id]
        archive_manifest.append(
            {
                "id": source_id,
                "name": source["name"],
                "document_url": source["document_url"],
                "resolved_zip_url": source["resolved_zip_url"],
                "zip_sha256": source["zip_sha256"],
                "zip_bytes": source["zip_bytes"],
            }
        )

    manifest: Dict[str, Any] = {
        "schema_version": BROWSER_SET_SCHEMA_VERSION,
        "set_id": BROWSER_SET_ID,
        "purpose": (
            "Bounded representative fixtures for a real human-browser Verify run; "
            "the exhaustive 33-file NIST STEP matrix remains CASES in this script."
        ),
        "truth_boundary": (
            "Supported part formats must visibly complete geometry, should-cost, "
            "provenance, persistence, and Records reopen. Native assemblies remain "
            "an explicit unsupported control and are never reported as verified."
        ),
        "binding_algorithm": "sha256(tab-joined fixture fields sorted by id; newline terminated)",
        "binding_fields": list(_FIXTURE_BINDING_FIELDS),
        "required_coverage": list(BROWSER_REQUIRED_COVERAGE),
        "optional_coverage": list(BROWSER_OPTIONAL_COVERAGE),
        "coverage": coverage,
        "source_archives": archive_manifest,
        "fixtures": sorted(fixtures, key=lambda item: item["order"]),
        "omissions": omissions,
    }
    manifest["fixture_set_sha256"] = fixture_set_binding_sha256(manifest["fixtures"])
    manifest_path = output_dir / "representative-cad-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return manifest_path, manifest


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

    if expected == "UNSUPPORTED_SUFFIX":
        message = result.get("error") or ""
        if "Unsupported file type" not in message:
            failures.append("unsupported-native control did not use the suffix boundary")

    pmi = result.get("pmi_check") or {}
    if case["cad_category"] == "pmi_present_step" and pmi.get("status") == "checked":
        if pmi.get("has_pmi") is not True:
            failures.append("XDE PMI check ran but did not detect PMI")

    return failures


def finalize_case_result(
    case: Dict[str, Any],
    source: Dict[str, Any],
    inner_bytes: bytes,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach provenance and a validator-owned verdict to one worker result."""
    failures = validate_case(case, result)
    return {
        **case,
        "source_document_url": SOURCES[case["source"]]["document_url"],
        "source_zip_sha256": source["zip_sha256"],
        "inner_sha256": sha256_bytes(inner_bytes),
        "inner_bytes": len(inner_bytes),
        **result,
        # Never allow a worker's self-reported status to overwrite the outer
        # oracle. That previously let an expectation mismatch appear as PASS.
        "worker_status": result.get("status"),
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }


def geometry_equivalence(
    case_results: List[Dict[str, Any]],
    member_ids: List[str],
    *,
    max_bbox_delta_mm: float = 0.2,
    max_relative_volume_delta: float = 0.002,
) -> Dict[str, Any]:
    """Compare one physical part encoded as B-rep and embedded tessellation."""
    indexed = {item["id"]: item for item in case_results}
    failures: List[str] = []
    members = []
    for member_id in member_ids:
        item = indexed.get(member_id)
        if item is None:
            failures.append("missing member %s" % member_id)
            continue
        if item.get("status") != "PASS":
            failures.append("member %s did not pass its case oracle" % member_id)
            continue
        geometry = item.get("geometry") or {}
        bbox = geometry.get("bbox_mm")
        volume = geometry.get("volume_cm3")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 3
            or not all(isinstance(value, (int, float)) for value in bbox)
            or not isinstance(volume, (int, float))
            or float(volume) <= 0
        ):
            failures.append("member %s has incomplete geometry evidence" % member_id)
            continue
        members.append(
            {
                "id": member_id,
                "bbox_mm": [float(value) for value in bbox],
                "volume_cm3": float(volume),
            }
        )

    observed_bbox_delta = 0.0
    observed_volume_delta = 0.0
    if len(members) == len(member_ids):
        baseline = members[0]
        for member in members[1:]:
            observed_bbox_delta = max(
                observed_bbox_delta,
                *(abs(a - b) for a, b in zip(baseline["bbox_mm"], member["bbox_mm"])),
            )
            observed_volume_delta = max(
                observed_volume_delta,
                abs(member["volume_cm3"] - baseline["volume_cm3"])
                / baseline["volume_cm3"],
            )
        if observed_bbox_delta > max_bbox_delta_mm:
            failures.append(
                "bounding-box delta %.6gmm exceeds %.6gmm"
                % (observed_bbox_delta, max_bbox_delta_mm)
            )
        if observed_volume_delta > max_relative_volume_delta:
            failures.append(
                "relative volume delta %.6g exceeds %.6g"
                % (observed_volume_delta, max_relative_volume_delta)
            )

    return {
        "id": "NIST-FTC-08-CROSS-REPRESENTATION",
        "status": "PASS" if not failures else "FAIL",
        "member_ids": member_ids,
        "members": members,
        "max_bbox_delta_mm_allowed": max_bbox_delta_mm,
        "max_relative_volume_delta_allowed": max_relative_volume_delta,
        "observed_max_bbox_delta_mm": round(observed_bbox_delta, 6),
        "observed_max_relative_volume_delta": round(observed_volume_delta, 8),
        "failures": failures,
    }


def run_main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    sources = {sid: download_source(sid, source) for sid, source in SOURCES.items()}

    case_results = []
    for case in CASES:
        source = sources[case["source"]]
        inner_bytes = read_inner(Path(source["zip_path"]), case["inner_path"])
        result = run_worker(source, case)
        case_results.append(finalize_case_result(case, source, inner_bytes, result))

    failed = [item for item in case_results if item["status"] != "PASS"]
    nist_step_results = [item for item in case_results if item["source"] == "nist_pmi_step"]
    with zipfile.ZipFile(sources["nist_pmi_step"]["zip_path"]) as archive:
        pinned_step_paths = {
            path for path in archive.namelist() if path.lower().endswith((".step", ".stp"))
        }
    selected_step_paths = {item["inner_path"] for item in nist_step_results}
    step_coverage = {
        "pinned_count": len(pinned_step_paths),
        "selected_count": len(selected_step_paths),
        "missing": sorted(pinned_step_paths - selected_step_paths),
        "unexpected": sorted(selected_step_paths - pinned_step_paths),
    }
    equivalence = geometry_equivalence(case_results, FTC08_EQUIVALENCE_IDS)
    acceptance = {
        "all_pinned_nist_step_files_exercised": (
            selected_step_paths == pinned_step_paths and len(pinned_step_paths) == 33
        ),
        "all_33_nist_step_files_passed": (
            len(nist_step_results) == 33
            and all(item["status"] == "PASS" for item in nist_step_results)
        ),
        "ap242_embedded_tessellation_passed": any(
            item["id"] == "NIST-AP242-FTC-08-TESSELLATED" and item["status"] == "PASS"
            for item in case_results
        ),
        "ftc08_cross_representation_equivalent": equivalence["status"] == "PASS",
        "native_cad_unsupported_control": any(
            item["expected_outcome"] == "UNSUPPORTED_SUFFIX" and item["status"] == "PASS"
            for item in case_results
        ),
        "all_cases_passed": not failed,
    }
    status = "PASS" if all(acceptance.values()) else "NEEDS_FIXES"
    data = {
        "status": status,
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "run_id": RUN_ID,
        "source_boundary": (
            "Public NIST CAD/STEP test files exercise pre-human parser, geometry, "
            "cost, and unsupported-native-CAD boundaries. They are not customer "
            "pilot evidence and do not imply NIST endorsement."
        ),
        "truth_boundary": (
            "B-rep STEP is triangulated through isolated gmsh/OCC; standardized AP242 "
            "embedded tessellation is consumed directly with declared unit conversion. "
            "Semantic PMI/GD&T is recorded as skipped unless OCP XDE is available."
        ),
        "cache_dir": str(cache_root()),
        "sources": list(sources.values()),
        "acceptance": acceptance,
        "step_coverage": step_coverage,
        "equivalence": equivalence,
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

    from src.api.routes import _parse_mesh_async, _run_cost_engine
    from src.costing import EstimateOptions, estimate_decision, report_to_dict
    from src.parsers import parse_pool

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
                    # Exercise the actual production parser boundary, including
                    # spawn-process isolation, crash recovery, per-rung caps,
                    # route timeout, and cache behavior. The former synchronous
                    # helper let a native gmsh segfault kill this corpus worker
                    # even though the deployed API contains that crash.
                    mesh, suffix = asyncio.run(_parse_mesh_async(data, filename))
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
        runtime_warning_details = [
            {
                "message": str(item.message),
                "category": item.category.__name__,
                "filename": item.filename,
                "lineno": item.lineno,
            }
            for item in caught
        ]

        outcome = report.status
        output = {
            "status": "PASS",
            "outcome": outcome,
            "suffix": suffix,
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "network_egress_blocked": True,
            "runtime_warnings": runtime_warnings,
            "runtime_warning_details": runtime_warning_details,
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

    finally:
        # Each case is its own outer subprocess. Do not leave gmsh children
        # behind after success, rejection, timeout, or a crashed native rung.
        try:
            parse_pool.shutdown(kill=True, final=True)
        except Exception:
            pass

    print(json.dumps(output, sort_keys=True))
    return 0 if output.get("status") == "PASS" else 1


def run_browser_iges_probe_mode(args: argparse.Namespace) -> int:
    """Fresh-process feasibility oracle for the actual isolated browser route."""
    sys.path.insert(0, str(BACKEND_ROOT))
    from src.api.routes import _extract_assembly_async, _parse_mesh_async, _run_cost_engine
    from src.parsers import parse_pool

    path = Path(args.browser_iges_probe)
    started = time.perf_counter()
    try:
        data = path.read_bytes()

        async def probe():
            assembly = await _extract_assembly_async(data, path.name)
            mesh, suffix = await _parse_mesh_async(data, path.name)
            return assembly, mesh, suffix

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with block_network_sockets():
                assembly, mesh, suffix = asyncio.run(probe())
                analysis, mesh, _features = _run_cost_engine(mesh, path.name)
        bbox = [float(value) for value in mesh.extents]
        volume_cm3 = float(mesh.volume / 1000.0)
        if (
            suffix not in (".iges", ".igs")
            or len(mesh.faces) <= 0
            or not mesh.is_watertight
            or volume_cm3 <= 0
            or not all(value > 0 and math.isfinite(value) for value in bbox)
            or assembly.kind != "single_part"
            or assembly.part_count != 1
        ):
            raise RuntimeError("isolated route returned incomplete IGES geometry")
        output = {
            "status": "PASS",
            "suffix": suffix,
            "face_count": len(mesh.faces),
            "watertight": bool(mesh.is_watertight),
            "volume_cm3": round(volume_cm3, 6),
            "bbox_mm": bbox,
            "dfm_verdict": str(getattr(analysis, "overall_verdict", "unknown")),
            "assembly_kind": assembly.kind,
            "assembly_part_count": assembly.part_count,
            "network_egress_blocked": True,
            "elapsed_sec": round(time.perf_counter() - started, 3),
        }
    except Exception as exc:
        output = {
            "status": "FAIL",
            "error": "%s: %s" % (type(exc).__name__, str(exc)[:300]),
            "network_egress_blocked": True,
            "elapsed_sec": round(time.perf_counter() - started, 3),
        }
    finally:
        try:
            parse_pool.shutdown(kill=True, final=True)
        except Exception:
            pass
    print(json.dumps(output, sort_keys=True))
    return 0 if output["status"] == "PASS" else 1


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

## Archive Coverage

```json
{step_coverage}
```

## Cross-Representation Geometry Oracle

```json
{equivalence}
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
        step_coverage=json.dumps(data["step_coverage"], indent=2, sort_keys=True),
        equivalence=json.dumps(data["equivalence"], indent=2, sort_keys=True),
        rows=rows,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the exhaustive real-CAD gate or deterministically materialize "
            "the bounded representative browser fixture set."
        )
    )
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--zip")
    parser.add_argument("--inner")
    parser.add_argument("--expected")
    parser.add_argument("--browser-iges-probe", help=argparse.SUPPRESS)
    browser = parser.add_mutually_exclusive_group()
    browser.add_argument(
        "--browser-plan",
        action="store_true",
        help="print the deterministic representative selection without materializing files",
    )
    browser.add_argument(
        "--materialize-browser-set",
        metavar="DIRECTORY",
        help="write representative fixtures and a hash-bound JSON manifest",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="forbid downloads; require both pinned NIST archives in the local cache",
    )
    return parser.parse_args()


if __name__ == "__main__":
    parsed_args = parse_args()
    if parsed_args.browser_iges_probe:
        raise SystemExit(run_browser_iges_probe_mode(parsed_args))
    if parsed_args.worker:
        raise SystemExit(run_worker_mode(parsed_args))
    if parsed_args.browser_plan:
        print(json.dumps(browser_plan(), indent=2, sort_keys=True))
        raise SystemExit(0)
    if parsed_args.materialize_browser_set:
        browser_manifest_path, browser_manifest = materialize_browser_set(
            Path(parsed_args.materialize_browser_set),
            offline=parsed_args.offline,
        )
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "set_id": browser_manifest["set_id"],
                    "fixtures": len(browser_manifest["fixtures"]),
                    "omissions": browser_manifest["omissions"],
                    "fixture_set_sha256": browser_manifest["fixture_set_sha256"],
                    "manifest": str(browser_manifest_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(0)
    raise SystemExit(run_main())
