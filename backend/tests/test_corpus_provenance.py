"""Corpus ingestion fails closed when redistribution provenance is incomplete."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from unittest.mock import Mock

import pytest
import trimesh

from src.corpus import demo_seed, gather
from src.corpus.provenance import (
    has_complete_provenance,
    has_documented_license,
    has_valid_source_url,
)


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("CC0-1.0", True),
        ("Apache-2.0", True),
        ("GPL-3.0-only", True),
        ("LicenseRef-CadVerify-Reviewed-counsel-2026-07", True),
        ("licensed", False),
        ("CC-BY", False),
        ("Public-Domain", False),
        ("MIT OR Apache-2.0", False),
        ("LicenseRef-Custom", False),
        ("LicenseRef-CadVerify-Reviewed-x", False),
        ("", False),
        ("UNKNOWN", False),
        ("UNKNOWN (see source)", False),
        ("see-repo", False),
        ("NOASSERTION", False),
        ("N/A", False),
        ("NONE", False),
        ("UNLICENSED", False),
        ("TBD", False),
    ],
)
def test_corpus_license_gate(value, accepted):
    assert has_documented_license(value) is accepted


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("https://example.test/model/1", True),
        ("https://example.test:8443/model/1?version=2", True),
        ("", False),
        ("not-a-url", False),
        ("http://example.test/model/1", False),
        ("https://user:password@example.test/model/1", False),
        ("https://example.test:99999/model/1", False),
        ("https://exa mple.test/model/1", False),
    ],
)
def test_corpus_source_url_gate(value, accepted):
    assert has_valid_source_url(value) is accepted


@pytest.mark.parametrize(
    ("source_url", "license_name"),
    [
        ("", "CC0-1.0"),
        ("https://example.test/model/1", "UNKNOWN"),
        ("", "UNKNOWN"),
        ("not-a-url", "CC0-1.0"),
        ("http://example.test/model/1", "CC0-1.0"),
        ("https://user:secret@example.test/model/1", "CC0-1.0"),
        ("https://example.test/model/1", "licensed"),
    ],
)
def test_add_part_rejects_incomplete_provenance_before_writing(
    source_url, license_name
):
    output = io.StringIO()
    seen: set[str] = set()
    near: set[tuple] = set()

    result = gather.add_part(
        raw=b"not parsed because provenance fails first",
        original_format="stl",
        filename="unlicensed.stl",
        source_url=source_url,
        dataset="test",
        license=license_name,
        out_fh=output,
        seen_ids=seen,
        near=near,
    )

    assert result is None
    assert output.getvalue() == ""
    assert seen == set()
    assert near == set()


def test_complete_provenance_requires_both_reviewed_fields():
    assert has_complete_provenance(
        "https://example.test/model/1", "MIT"
    )
    assert not has_complete_provenance("http://example.test/model/1", "MIT")
    assert not has_complete_provenance(
        "https://example.test/model/1", "looks-open"
    )


def test_add_part_accepts_documented_asset_and_persists_provenance(
    tmp_path, monkeypatch
):
    mesh_dir = tmp_path / "meshes"
    mesh_dir.mkdir()
    monkeypatch.setattr(gather, "MESH_DIR", mesh_dir)
    raw = trimesh.creation.box(extents=(20, 10, 5)).export(file_type="stl")
    assert isinstance(raw, bytes)
    output = io.StringIO()
    seen: set[str] = set()
    near: set[tuple] = set()

    part_id = gather.add_part(
        raw=raw,
        original_format="stl",
        filename="licensed-box.stl",
        source_url="https://example.test/models/licensed-box",
        dataset="internal-test",
        license="CC0-1.0",
        out_fh=output,
        seen_ids=seen,
        near=near,
    )

    assert part_id is not None
    record = json.loads(output.getvalue())
    assert record["source_url"] == "https://example.test/models/licensed-box"
    assert record["license"] == "CC0-1.0"
    assert record["part_id"] == part_id
    assert (mesh_dir / f"{part_id}.stl").is_file()
    assert part_id in seen


def test_demo_seed_mixed_manifest_imports_only_documented_assets(
    tmp_path, monkeypatch
):
    parts_dir = tmp_path / "incoming"
    mesh_dir = tmp_path / "corpus" / "meshes"
    manifest = tmp_path / "corpus" / "manifest.jsonl"
    parts_dir.mkdir()

    valid = trimesh.creation.box(extents=(10, 10, 10))
    invalid = trimesh.creation.box(extents=(12, 8, 6))
    valid.export(parts_dir / "valid.stl")
    invalid.export(parts_dir / "unknown-license.stl")
    with (parts_dir / "_manifest.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["filename", "source", "source_url", "license"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "filename": "valid.stl",
                "source": "internal-test",
                "source_url": "https://example.test/models/valid",
                "license": "CC0-1.0",
            }
        )
        writer.writerow(
            {
                "filename": "unknown-license.stl",
                "source": "internal-test",
                "source_url": "https://example.test/models/unknown",
                "license": "NOASSERTION",
            }
        )

    def _ensure_dirs():
        mesh_dir.mkdir(parents=True, exist_ok=True)
        manifest.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(demo_seed, "MESH_DIR", mesh_dir)
    monkeypatch.setattr(demo_seed, "MANIFEST", manifest)
    monkeypatch.setattr(demo_seed, "ensure_dirs", _ensure_dirs)

    assert demo_seed.seed_demo_corpus(parts_dir) == 1
    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    assert [record["filename"] for record in records] == ["valid.stl"]
    assert records[0]["license"] == "CC0-1.0"


@pytest.mark.parametrize(
    ("license_name", "expected_added"),
    [("Apache-2.0", 1), ("NOASSERTION", 0)],
)
def test_github_collection_enforces_repository_license_gate(
    license_name, expected_added, monkeypatch
):
    """The default GitHub path must run the shared provenance gate, not crash."""
    monkeypatch.setattr(gather, "GITHUB_REPOS", [("owner/repo", "main", 1)])
    commit_sha = "c" * 40
    source = (
        gather.GitHubSource(
            repo="owner/repo",
            requested_ref="main",
            commit_sha=commit_sha,
            license_spdx="Apache-2.0",
            license_path="LICENSE",
            license_blob_sha="d" * 40,
            license_sha256="e" * 64,
            license_artifact_url=(
                f"https://github.com/owner/repo/blob/{commit_sha}/LICENSE"
            ),
        )
        if license_name == "Apache-2.0"
        else None
    )
    monkeypatch.setattr(
        gather, "_resolve_github_source", lambda _repo, _ref: source
    )
    add_part = Mock(return_value="part-1")
    monkeypatch.setattr(gather, "add_part", add_part)

    tree = Mock(status_code=200)
    tree.json.return_value = {
        "tree": [{"type": "blob", "path": "cad/fixture.stl"}]
    }
    mesh = Mock(status_code=200, content=b"licensed mesh bytes")

    def fake_get(url, **_kwargs):
        return tree if "/git/trees/" in url else mesh

    monkeypatch.setattr(gather.requests, "get", fake_get)

    added = gather.fetch_github(
        io.StringIO(), seen_ids=set(), near=set(), sleep=0
    )

    assert added == expected_added
    assert add_part.call_count == expected_added
    if expected_added:
        assert add_part.call_args.kwargs["license"] == "Apache-2.0"
        assert add_part.call_args.kwargs["dataset"] == (
            f"github:owner/repo@{commit_sha}"
        )
        assert add_part.call_args.kwargs["source_url"].endswith(
            f"/owner/repo/blob/{commit_sha}/cad/fixture.stl"
        )
        extra = add_part.call_args.kwargs["extra"]
        assert extra["github_requested_ref"] == "main"
        assert extra["github_commit_sha"] == commit_sha
        assert extra["license_artifact_sha256"] == "e" * 64


def test_github_source_resolution_pins_license_to_exact_commit(monkeypatch):
    commit_sha = "a" * 40
    license_bytes = b"Apache License\nVersion 2.0\n"
    license_blob_sha = hashlib.sha1(  # nosec B324 - Git object fixture
        f"blob {len(license_bytes)}\0".encode() + license_bytes,
        usedforsecurity=False,
    ).hexdigest()
    calls: list[tuple[str, dict]] = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if "/commits/" in url:
            response = Mock(status_code=200)
            response.json.return_value = {"sha": commit_sha}
            return response
        assert url.endswith("/repos/owner/repo/license")
        assert kwargs["params"] == {"ref": commit_sha}
        response = Mock(status_code=200)
        response.json.return_value = {
            "license": {"spdx_id": "Apache-2.0"},
            "path": "LICENSE",
            "sha": license_blob_sha,
            "encoding": "base64",
            "content": base64.b64encode(license_bytes).decode(),
        }
        return response

    monkeypatch.setattr(gather.requests, "get", fake_get)

    source = gather._resolve_github_source("owner/repo", "main")

    assert source is not None
    assert source.commit_sha == commit_sha
    assert source.license_spdx == "Apache-2.0"
    assert source.license_blob_sha == license_blob_sha
    assert source.license_sha256 == hashlib.sha256(license_bytes).hexdigest()
    assert source.license_artifact_url == (
        f"https://github.com/owner/repo/blob/{commit_sha}/LICENSE"
    )
    assert len(calls) == 2


def test_github_source_resolution_rejects_unreviewed_license(monkeypatch):
    commit = Mock(status_code=200)
    commit.json.return_value = {"sha": "a" * 40}
    license_response = Mock(status_code=200)
    license_response.json.return_value = {
        "license": {"spdx_id": "NOASSERTION"},
    }
    monkeypatch.setattr(
        gather.requests,
        "get",
        Mock(side_effect=[commit, license_response]),
    )

    assert gather._resolve_github_source("owner/repo", "main") is None


def test_thingi10k_rejects_ambiguous_license_before_asset_download(monkeypatch):
    metadata = {
        "input_summary.csv": (
            "ID,License,Thing ID\n"
            "cc0-part,Creative Commons - Public Domain Dedication,1\n"
            "ambiguous-part,Creative Commons - Attribution,2\n"
        ),
        "geometry_data.csv": (
            "file_id,num_faces\ncc0-part,100\nambiguous-part,100\n"
        ),
        "contextual_data.csv": "Thing ID,Category\n1,Mechanical\n2,Mechanical\n",
    }
    monkeypatch.setattr(gather, "_cached_csv", lambda name: metadata[name])
    add_part = Mock(return_value="part-1")
    monkeypatch.setattr(gather, "add_part", add_part)
    downloaded: list[str] = []

    def fake_get(url, **_kwargs):
        downloaded.append(url)
        return Mock(status_code=200, content=b"licensed mesh bytes")

    monkeypatch.setattr(gather.requests, "get", fake_get)

    added = gather.fetch_thingi10k(
        1, io.StringIO(), seen_ids=set(), near=set(), sleep=0
    )

    assert added == 1
    assert len(downloaded) == 1
    assert downloaded[0].endswith("/cc0-part.stl")
    assert add_part.call_args.kwargs["license"] == "CC0-1.0"
