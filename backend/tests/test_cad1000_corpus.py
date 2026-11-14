import json
from pathlib import Path

import pytest

from src.corpus.cad1000 import (
    CADVERIFY_CORE_SOFTWARE,
    WorkflowKnowledgeBase,
    discover_workflows,
    ingest,
    production_retrieval_eligible,
)
from src.corpus.cad1000_manifest import build_manifest, write_manifest


WORKFLOW = "autocad/workflow-a"


def _rights_manifest(tmp_path: Path, *, local_research: bool = True) -> Path:
    path = tmp_path / "manifest.json"
    manifest = build_manifest(
        {
            "id": "markov-ai/cad-1000-hours",
            "sha": "b1bd4711343017fc40dfa6fe40a6cd338b7edaf6",
            "cardData": {"license": "cc-by-4.0"},
            "siblings": [{"rfilename": f"{WORKFLOW}/task_desc.json", "size": 1}],
        },
        grants={
            "local_research": local_research,
            "production_retrieval": False,
            "training": False,
            "redistribution": False,
        },
    )
    write_manifest(path, manifest)
    return path


def fixture_fetch(url: str):
    if "/api/datasets/" in url:
        return {
            "siblings": [
                {"rfilename": f"{WORKFLOW}/task_desc.json"},
                {"rfilename": "solidworks/workflow-b/task_desc.json"},
                {"rfilename": f"{WORKFLOW}/clip.mp4"},
            ]
        }
    if url.endswith("task_desc.json"):
        return {
            "domain": "Architecture",
            "application": "AutoCAD",
            "task": "Create a furnished floor plan",
            "description": "Draw walls, rooms, doors, windows, and parking.",
            "deliverables": [{"type": "dwg"}],
        }
    if url.endswith("metadata.json"):
        return {
            "total_duration_ms": 120_000,
            "total_frames": 3_600,
            "event_count": 420,
            "fps": 30,
        }
    if url.endswith("rubrics.json"):
        return {"rubrics": [{"id": "R1", "requirement": "Show two parking spaces."}]}
    if url.endswith("narration.json"):
        return {
            "annotations": [
                {
                    "start_s": 10,
                    "end_s": 15,
                    "action": "Used OFFSET to create parallel walls.",
                    "intent": "Create consistent wall thickness.",
                    "app": "AutoCAD",
                }
            ]
        }
    raise AssertionError(f"unexpected URL: {url}")


def test_discovery_filters_without_tree_pagination():
    assert discover_workflows("autocad", fetch_json=fixture_fetch) == [WORKFLOW]


def test_cadverify_core_excludes_architecture_and_keeps_mechanical_apps():
    def fetch(_url: str):
        return {
            "siblings": [
                {"rfilename": "autocad/a/task_desc.json"},
                {"rfilename": "revit-architecture/b/task_desc.json"},
                {"rfilename": "solidworks/c/task_desc.json"},
                {"rfilename": "catia/d/task_desc.json"},
                {"rfilename": "nx-cad/e/task_desc.json"},
            ]
        }

    paths = discover_workflows(cadverify_core_only=True, fetch_json=fetch)
    assert {path.split("/", 1)[0] for path in paths} == CADVERIFY_CORE_SOFTWARE


def test_ingest_writes_provenance_tagged_atomic_snapshot(tmp_path: Path):
    output = tmp_path / "knowledge.jsonl"
    summary = ingest(
        output,
        rights_manifest=_rights_manifest(tmp_path),
        application="autocad",
        fetch_json=fixture_fetch,
    )
    records = [json.loads(line) for line in output.read_text().splitlines()]

    assert summary["records"] == 3
    assert summary["record_types"] == {"rubric": 1, "workflow": 1, "workflow_segment": 1}
    assert {record["provenance"] for record in records} == {"THIRD_PARTY_UNVERIFIED"}
    assert all(record["eligible_for_training"] is False for record in records)
    assert all(record["may_affect_deterministic_verdict"] is False for record in records)
    assert all(record["engineering_authority"] == "NONE" for record in records)
    assert all(record["is_manufacturing_ground_truth"] is False for record in records)
    assert {record["knowledge_role"] for record in records} == {
        "authoring_trace",
        "design_intent",
        "design_requirement",
    }
    assert all("manufacturing_feasibility_decision" in record["forbidden_uses"] for record in records)
    assert {record["total_frames"] for record in records} == {3_600}
    assert {record["event_count"] for record in records} == {420}
    assert {record["fps"] for record in records} == {30}
    assert not output.with_suffix(".jsonl.tmp").exists()


def test_quarantine_is_default_and_explicit_for_research():
    records = [
        {
            "text": "Use OFFSET to create parallel walls",
            "application": "AutoCAD",
            "record_type": "workflow_segment",
            "source_path": WORKFLOW,
            "license_status": "UNDECLARED",
            "eligible_for_production_retrieval": False,
            "engineering_authority": "NONE",
            "is_manufacturing_ground_truth": False,
            "may_affect_deterministic_verdict": False,
        }
    ]
    assert WorkflowKnowledgeBase(records).search("offset walls") == []

    hits = WorkflowKnowledgeBase(records, include_quarantined=True).search("offset walls")
    assert len(hits) == 1
    assert hits[0].record["source_path"] == WORKFLOW


def test_retrieval_filters_application_and_record_type():
    base = {
        "license_status": "CC-BY-4.0",
        "rights": {"production_retrieval": True},
        "eligible_for_production_retrieval": True,
        "engineering_authority": "NONE",
        "is_manufacturing_ground_truth": False,
        "may_affect_deterministic_verdict": False,
    }
    records = [
        {
            **base,
            "text": "parking spaces and vehicle blocks",
            "application": "AutoCAD",
            "record_type": "rubric",
            "knowledge_role": "design_requirement",
            "source_path": "a",
        },
        {
            **base,
            "text": "parking fixture in an assembly",
            "application": "SOLIDWORKS",
            "record_type": "workflow_segment",
            "knowledge_role": "authoring_trace",
            "source_path": "b",
        },
    ]
    knowledge = WorkflowKnowledgeBase(records)
    hits = knowledge.search(
        "parking",
        application="AutoCAD",
        record_type="rubric",
        knowledge_role="design_requirement",
    )
    assert [hit.record["source_path"] for hit in hits] == ["a"]


def test_retrieval_rejects_undeclared_license_and_unsafe_authority():
    base = {
        "text": "machined pocket fillet",
        "license_status": "CC-BY-4.0",
        "rights": {"production_retrieval": True},
        "eligible_for_production_retrieval": True,
        "engineering_authority": "NONE",
        "is_manufacturing_ground_truth": False,
        "may_affect_deterministic_verdict": False,
    }
    undeclared = {**base, "license_status": "UNDECLARED"}
    unsafe = {**base, "engineering_authority": "ENGINEERING_GROUND_TRUTH"}
    assert WorkflowKnowledgeBase([undeclared, unsafe]).records == []
    assert WorkflowKnowledgeBase([unsafe], include_quarantined=True).records == []
    assert WorkflowKnowledgeBase([[], None], include_quarantined=True).records == []

    for rights in (None, {"production_retrieval": False}, "yes"):
        candidate = {**base}
        if rights is None:
            candidate.pop("rights")
        else:
            candidate["rights"] = rights
        assert production_retrieval_eligible(candidate) is False
    assert production_retrieval_eligible(base) is True


def test_retrieval_does_not_match_only_on_stopwords():
    record = {
        "text": "the fixture is in the assembly",
        "license_status": "CC-BY-4.0",
        "rights": {"production_retrieval": True},
        "eligible_for_production_retrieval": True,
        "engineering_authority": "NONE",
        "is_manufacturing_ground_truth": False,
        "may_affect_deterministic_verdict": False,
    }
    assert WorkflowKnowledgeBase([record]).search("the radius is below the limit") == []


def test_retrieval_abstains_on_one_generic_overlap_but_keeps_meaningful_phrase():
    base = {
        "license_status": "CC-BY-4.0",
        "rights": {"production_retrieval": True},
        "eligible_for_production_retrieval": True,
        "engineering_authority": "NONE",
        "is_manufacturing_ground_truth": False,
        "may_affect_deterministic_verdict": False,
    }
    knowledge = WorkflowKnowledgeBase(
        [
            {**base, "text": "Adjust the selected sketch geometry."},
            {**base, "text": "Create an internal pocket in the housing."},
        ]
    )

    assert knowledge.search(
        "quantum nebula insurance underwriting adjust orbital temperature"
    ) == []
    assert len(knowledge.search("internal pocket radius milling threshold")) == 1


def test_failed_ingest_does_not_replace_existing_snapshot(tmp_path: Path):
    output = tmp_path / "knowledge.jsonl"
    output.write_text("existing\n")

    def failing_fetch(url: str):
        if "/api/datasets/" in url:
            return fixture_fetch(url)
        raise RuntimeError("network interrupted")

    with pytest.raises(RuntimeError, match="network interrupted"):
        ingest(
            output,
            rights_manifest=_rights_manifest(tmp_path),
            application="autocad",
            fetch_json=failing_fetch,
        )
    assert output.read_text() == "existing\n"


def test_ingest_without_local_research_grant_performs_no_fetch_or_write(tmp_path: Path):
    output = tmp_path / "knowledge.jsonl"
    calls: list[str] = []

    def fetch(url: str):
        calls.append(url)
        return fixture_fetch(url)

    with pytest.raises(PermissionError, match="does not grant local_research"):
        ingest(
            output,
            rights_manifest=_rights_manifest(tmp_path, local_research=False),
            application="autocad",
            fetch_json=fetch,
        )

    assert calls == []
    assert not output.exists()
