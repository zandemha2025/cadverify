from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.design_intelligence import router
from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.services import design_intelligence_service as service
from src.services import org_precedent_service
from src.corpus.cad1000 import DATASET_REVISION


@pytest.fixture(autouse=True)
def _authenticated_actor_email(monkeypatch):
    async def lookup(user_id: int | None) -> str:
        assert user_id == 1
        return "analyst@example.com"

    monkeypatch.setattr("src.api.design_intelligence._lookup_email", lookup)


def _record(
    role: str,
    text: str,
    *,
    eligible: bool = False,
    license_status: str = "UNDECLARED",
    revision: str = DATASET_REVISION,
) -> dict:
    record_type = {
        "design_intent": "workflow",
        "design_requirement": "rubric",
        "authoring_trace": "workflow_segment",
    }[role]
    return {
        "dataset_url": "https://huggingface.co/datasets/markov-ai/cad-1000-hours",
        "dataset_revision": revision,
        "source_path": "solidworks/wf-1",
        "workflow_id": "wf-1",
        "application": "SOLIDWORKS",
        "task": "Create a machined housing with mounting bosses and internal pockets.",
        "record_type": record_type,
        "knowledge_role": role,
        "text": text,
        "start_s": 12.5 if role == "authoring_trace" else None,
        "end_s": 18.0 if role == "authoring_trace" else None,
        "provenance": "THIRD_PARTY_UNVERIFIED",
        "license_status": license_status,
        "rights": {"production_retrieval": eligible},
        "eligible_for_production_retrieval": eligible,
        "eligible_for_training": False,
        "engineering_authority": "NONE",
        "is_manufacturing_ground_truth": False,
        "may_affect_deterministic_verdict": False,
    }


def _write(
    path: Path, *, eligible: bool = False, license_status: str = "UNDECLARED"
) -> None:
    rows = [
        _record(
            "design_intent",
            "machined housing internal pocket",
            eligible=eligible,
            license_status=license_status,
        ),
        _record(
            "design_requirement",
            "Internal pocket shall retain mounting bosses",
            eligible=eligible,
            license_status=license_status,
        ),
        _record(
            "authoring_trace",
            "Added a fillet to the internal pocket corner",
            eligible=eligible,
            license_status=license_status,
        ),
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _finding() -> dict:
    return {
        "code": "INTERNAL_RADIUS_TOO_SMALL",
        "severity": "error",
        "message": "Internal pocket radius is below the 3-axis milling threshold.",
        "fix_suggestion": "Increase the internal radius to at least 3 mm.",
        "process": "cnc_3axis",
        "measured_value": 1.2,
        "required_value": 3.0,
    }


class _Result:
    def __init__(self, org_id: str | None):
        self.org_id = org_id

    def scalar_one_or_none(self):
        return self.org_id


class _Session:
    def __init__(self, org_id: str | None):
        self.org_id = org_id

    async def execute(self, _statement):
        return _Result(self.org_id)


class _SavedSession:
    def __init__(self, org_id: str | None, analysis=None):
        self.org_id = org_id
        self.analysis = analysis
        self.calls = 0

    async def execute(self, _statement):
        self.calls += 1
        if self.calls == 1:
            return _Result(self.org_id)
        owned = (
            self.analysis
            if self.analysis is not None and self.analysis.org_id == self.org_id
            else None
        )
        return _Result(owned)


def _app(org_id: str | None = "org-a", role: str = "viewer") -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/design-intelligence")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=1, api_key_id=0, key_prefix="session", role=role
    )
    app.dependency_overrides[get_db_session] = lambda: _Session(org_id)
    return app


def _saved_app(
    analysis, org_id: str | None = "org-a", role: str = "viewer"
) -> FastAPI:
    app = _app(org_id, role)
    app.dependency_overrides[get_db_session] = lambda: _SavedSession(org_id, analysis)
    return app


class _FeedbackSession:
    def __init__(self, analysis, org_id: str | None = "org-a"):
        self.analysis = analysis
        self.org_id = org_id
        self.rows = []
        self.commits = 0

    async def execute(self, statement):
        sql = str(statement)
        if "FROM analyses" in sql:
            owned = (
                self.analysis
                if self.analysis is not None
                and self.analysis.org_id == self.org_id
                else None
            )
            return _Result(owned)
        if "FROM audit_log" in sql:
            params = statement.compile().params
            key = next(
                value
                for value in params.values()
                if value in {"decision", "advisory"}
            )
            finding_ref = next(
                (value for value in params.values() if isinstance(value, dict)),
                None,
            )
            rows = [
                row
                for row in self.rows
                if row.org_id == self.org_id
                and row.resource_id == self.analysis.ulid
                and key in (row.detail_json or {})
                and (
                    finding_ref is None
                    or (row.detail_json or {}).get("finding_ref") == finding_ref
                )
            ]
            return _Result(rows[-1] if rows else None)
        return _Result(self.org_id)

    def add(self, row):
        row.id = len(self.rows) + 1
        self.rows.append(row)

    async def commit(self):
        self.commits += 1


def _feedback_app(
    analysis, org_id: str | None = "org-a", role: str = "analyst"
) -> tuple[FastAPI, _FeedbackSession]:
    app = _app(org_id, role)
    session = _FeedbackSession(analysis, org_id)
    app.dependency_overrides[get_db_session] = lambda: session
    return app, session


def _saved_analysis(*, org_id: str = "org-a"):
    first = _finding()
    second = {**_finding(), "message": "Second matching engine finding."}
    process_issue = {
        **_finding(),
        "code": "TOOL_ACCESS_LIMITED",
        "message": "Pocket cannot be reached by the selected tool.",
    }
    return SimpleNamespace(
        ulid="01SAVED000000000000000001",
        org_id=org_id,
        result_json={
            "overall_verdict": "fail",
            "universal_issues": [first, second],
            "process_scores": [
                {"process": "cnc_3axis", "issues": [process_issue]},
            ],
        },
    )


def _advisory_result(*, revision: str = DATASET_REVISION) -> dict:
    return {
        "status": "available",
        "reason": None,
        "finding_code": "INTERNAL_RADIUS_TOO_SMALL",
        "authority": "ADVISORY_ONLY",
        "engineering_authority": "NONE",
        "provenance": "THIRD_PARTY_UNVERIFIED",
        "may_affect_deterministic_verdict": False,
        "is_manufacturing_ground_truth": False,
        "corpus_revision": revision,
        "possible_intents": [
            {
                "candidate": "Housing",
                "source_url": "https://example.test/intent",
            }
        ],
        "relevant_requirements": [],
        "workflow_evidence": [
            {
                "excerpt": "Bounded response excerpt",
                "source_url": "https://example.test/evidence",
            }
        ],
    }


def test_service_fails_closed_without_corpus(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(tmp_path / "missing.jsonl"))
    monkeypatch.delenv("CAD1000_RESEARCH_MODE", raising=False)
    service.reset_cache()
    result = service.explain_finding(_finding())
    assert result["status"] == "unavailable"
    assert result["reason"] == "knowledge_corpus_missing"
    assert result["may_affect_deterministic_verdict"] is False
    assert result["engineering_authority"] == "NONE"
    assert "redesign_test" not in result


def test_service_fails_closed_for_malformed_corpus(monkeypatch, tmp_path: Path):
    corpus = tmp_path / "knowledge.jsonl"
    corpus.write_text("{not-json}\n")
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    service.reset_cache()
    result = service.explain_finding(_finding())
    assert result["status"] == "unavailable"
    assert result["workflow_evidence"] == []


def test_serving_index_is_bounded_compact_and_deterministic(monkeypatch, tmp_path: Path):
    rows = []
    for role in ("design_intent", "design_requirement", "authoring_trace"):
        for index in range(8):
            row = _record(
                role,
                f"{role} {index} " + "x" * 200,
                eligible=True,
                license_status="CC-BY-4.0",
            )
            row.update(
                workflow_id=f"{role}-{index}",
                source_path=f"solidworks/{role}-{index}",
            )
            rows.append(row)
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text("".join(json.dumps(row) + "\n" for row in rows))
    second.write_text("".join(json.dumps(row) + "\n" for row in reversed(rows)))
    monkeypatch.setattr(service, "_MAX_INDEX_RECORDS", 6)
    monkeypatch.setattr(service, "_MAX_TEXT_CHARS", 32)

    first_index = service._build_knowledge(first, include_quarantined=False)
    second_index = service._build_knowledge(second, include_quarantined=False)

    assert len(first_index.knowledge.records) == 6
    assert first_index.eligible_records_scanned == 24
    assert first_index.indexed_records == 6
    assert first_index.index_truncated is True
    assert Counter(row["knowledge_role"] for row in first_index.knowledge.records) == {
        "design_intent": 2,
        "design_requirement": 2,
        "authoring_trace": 2,
    }
    assert all(len(row["text"]) <= 32 for row in first_index.knowledge.records)
    assert {row["workflow_id"] for row in first_index.knowledge.records} == {
        row["workflow_id"] for row in second_index.knowledge.records
    }


def test_no_match_discloses_bounded_index_without_claiming_full_corpus_absence(
    monkeypatch, tmp_path: Path
):
    rows = []
    for role in ("design_intent", "design_requirement", "authoring_trace"):
        for index in range(2):
            row = _record(
                role,
                f"lathe spindle collet {index}",
                eligible=True,
                license_status="CC-BY-4.0",
            )
            row.update(
                workflow_id=f"{role}-{index}",
                source_path=f"solidworks/{role}-{index}",
            )
            rows.append(row)
    corpus = tmp_path / "knowledge.jsonl"
    corpus.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.delenv("CAD1000_RESEARCH_MODE", raising=False)
    monkeypatch.setattr(service, "_MAX_INDEX_RECORDS", 3)
    service.reset_cache()

    result = service.explain_finding(
        {
            "code": "UNSEEN_QUASAR",
            "severity": "info",
            "message": "quasar nebula token",
        }
    )

    assert result["status"] == "no_match"
    assert result["reason"] == "no_relevant_precedent_in_bounded_index"
    assert result["eligible_records_scanned"] == 6
    assert result["indexed_records"] == 3
    assert result["index_truncated"] is True


@pytest.mark.parametrize(
    "finding",
    [
        {
            "code": "SYNTHETIC_ORTHOGONAL",
            "message": "Quantum nebula insurance underwriting tax compliance.",
            "fix_suggestion": "Adjust orbital coffee temperature.",
            "process": "synthetic",
        },
        {
            "code": "EXCEEDS_BUILD_VOLUME",
            "message": "Part exceeds the selected printer build volume.",
            "fix_suggestion": "Reduce dimensions or select a larger machine.",
            "process": "fdm",
        },
    ],
)
def test_service_abstains_when_only_generic_cad_words_overlap(
    monkeypatch, tmp_path: Path, finding: dict
):
    rows = [
        _record("design_intent", "Create a larger part with selected geometry."),
        _record(
            "design_requirement",
            "The drawing shall include a larger shaded view of the complete part.",
        ),
        _record(
            "authoring_trace",
            "Build the connected outline, adjust the view, and keep geometry selected.",
        ),
    ]
    corpus = tmp_path / "knowledge.jsonl"
    corpus.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
    monkeypatch.setenv("RELEASE", "dev")
    service.reset_cache()

    result = service.explain_finding(finding)

    assert result["status"] == "no_match"
    assert result["possible_intents"] == []
    assert result["relevant_requirements"] == []
    assert result["workflow_evidence"] == []


def test_serving_index_rejects_oversized_file_and_line(monkeypatch, tmp_path: Path):
    corpus = tmp_path / "knowledge.jsonl"
    corpus.write_text(json.dumps(_record("design_intent", "pocket radius")) + "\n")

    monkeypatch.setattr(service, "_MAX_CORPUS_BYTES", corpus.stat().st_size - 1)
    with pytest.raises(ValueError, match="corpus exceeds"):
        service._build_knowledge(corpus, include_quarantined=True)

    monkeypatch.setattr(service, "_MAX_CORPUS_BYTES", 10_000)
    monkeypatch.setattr(service, "_MAX_LINE_BYTES", 20)
    with pytest.raises(ValueError, match="corpus line 1 exceeds"):
        service._build_knowledge(corpus, include_quarantined=True)


@pytest.mark.asyncio
async def test_concurrent_first_load_is_single_and_does_not_block_loop(
    monkeypatch, tmp_path: Path
):
    corpus = tmp_path / "knowledge.jsonl"
    _write(corpus)
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
    monkeypatch.setenv("RELEASE", "dev")
    service.reset_cache()
    original = service._build_knowledge
    calls = 0

    def slow_build(path, include_quarantined):
        nonlocal calls
        calls += 1
        time.sleep(0.15)
        return original(path, include_quarantined)

    monkeypatch.setattr(service, "_build_knowledge", slow_build)
    first = asyncio.create_task(service.explain_finding_async(_finding()))
    second = asyncio.create_task(service.explain_finding_async(_finding()))

    await asyncio.sleep(0.03)
    assert calls == 1
    assert not first.done()
    assert not second.done()

    results = await asyncio.gather(first, second)
    assert calls == 1
    assert [result["status"] for result in results] == [
        "research_only",
        "research_only",
    ]


def test_unlicensed_records_are_quarantined_by_default(monkeypatch, tmp_path: Path):
    corpus = tmp_path / "knowledge.jsonl"
    _write(corpus, eligible=False)
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.delenv("CAD1000_RESEARCH_MODE", raising=False)
    service.reset_cache()
    result = service.explain_finding(_finding())
    assert result["status"] == "unavailable"
    assert result["reason"] == "no_eligible_knowledge_records"


def test_research_mode_returns_cited_advisory_context(monkeypatch, tmp_path: Path):
    corpus = tmp_path / "knowledge.jsonl"
    _write(corpus, eligible=False)
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
    monkeypatch.setenv("RELEASE", "dev")
    service.reset_cache()
    result = service.explain_finding(_finding())
    assert result["status"] == "research_only"
    assert result["authority"] == "ADVISORY_ONLY"
    assert result["may_affect_deterministic_verdict"] is False
    assert result["is_manufacturing_ground_truth"] is False
    assert result["possible_intents"][0]["confidence"] == "hypothesis"
    assert result["possible_intents"][0]["license_status"] == "UNDECLARED"
    assert result["possible_intents"][0]["production_eligible"] is False
    assert result["relevant_requirements"][0]["license_status"] == "UNDECLARED"
    assert result["workflow_evidence"][0]["source_url"].endswith("#t=12.500")
    assert DATASET_REVISION in result["workflow_evidence"][0]["source_url"]
    assert "redesign_test" not in result


def test_alternate_revision_is_preserved_in_response_and_citation_urls(
    monkeypatch, tmp_path: Path
):
    revision = "c" * 40
    corpus = tmp_path / "knowledge.jsonl"
    rows = [
        _record(role, "internal pocket fillet", revision=revision)
        for role in ("design_intent", "design_requirement", "authoring_trace")
    ]
    corpus.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
    monkeypatch.setenv("RELEASE", "dev")
    service.reset_cache()

    result = service.explain_finding(_finding())

    assert result["corpus_revision"] == revision
    cited = [
        row["source_url"]
        for key in ("possible_intents", "relevant_requirements", "workflow_evidence")
        for row in result[key]
    ]
    assert cited
    assert all(f"/{revision}/" in url for url in cited)
    assert all(DATASET_REVISION not in url for url in cited)


def test_mixed_or_missing_corpus_revisions_fail_closed(monkeypatch, tmp_path: Path):
    for suffix, rows in {
        "mixed": [
            _record("design_intent", "internal pocket", revision="c" * 40),
            _record("authoring_trace", "internal fillet", revision="d" * 40),
        ],
        "missing": [
            {
                key: value
                for key, value in _record("design_intent", "internal pocket").items()
                if key != "dataset_revision"
            }
        ],
    }.items():
        corpus = tmp_path / f"{suffix}.jsonl"
        corpus.write_text("".join(json.dumps(row) + "\n" for row in rows))
        monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
        monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
        monkeypatch.setenv("RELEASE", "dev")
        service.reset_cache()

        result = service.explain_finding(_finding())

        assert result["status"] == "unavailable"
        assert result["corpus_revision"] is None
        assert result["workflow_evidence"] == []


def test_refinery_narration_schema_keeps_workflow_video_citation_and_times(
    monkeypatch, tmp_path: Path
):
    corpus = tmp_path / "refined.jsonl"
    record = _record("authoring_trace", "internal pocket fillet")
    record.pop("source_path")
    record.pop("start_s")
    record.pop("end_s")
    record.update(
        record_type="workflow_narration",
        workflow="solidworks/workflow with space",
        timestamp_range={"basis": "video_seconds", "start": 12.5, "end": 18.0},
    )
    corpus.write_text(json.dumps(record) + "\n")
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
    monkeypatch.setenv("RELEASE", "dev")
    service.reset_cache()

    result = service.explain_finding(_finding())

    evidence = result["workflow_evidence"][0]
    assert evidence["start_s"] == 12.5
    assert evidence["end_s"] == 18.0
    assert evidence["source_url"].endswith(
        "/solidworks/workflow%20with%20space/clip.mp4#t=12.500"
    )


def test_bad_source_timestamp_cannot_break_advisory_response(monkeypatch, tmp_path: Path):
    corpus = tmp_path / "knowledge.jsonl"
    record = _record("authoring_trace", "internal pocket fillet")
    record["start_s"] = "not-a-number"
    corpus.write_text(json.dumps(record) + "\n")
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
    monkeypatch.setenv("RELEASE", "dev")
    service.reset_cache()
    result = service.explain_finding(_finding())
    assert result["status"] == "research_only"
    assert "#t=" not in result["workflow_evidence"][0]["source_url"]


def test_rights_cleared_records_work_without_research_mode(monkeypatch, tmp_path: Path):
    corpus = tmp_path / "knowledge.jsonl"
    _write(corpus, eligible=True, license_status="CC-BY-4.0")
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.delenv("CAD1000_RESEARCH_MODE", raising=False)
    service.reset_cache()
    result = service.explain_finding(_finding())
    assert result["status"] == "available"
    assert result["research_mode"] is False
    assert all(row["production_eligible"] for row in result["possible_intents"])
    assert all(row["production_eligible"] for row in result["workflow_evidence"])


def test_research_mode_is_forced_off_in_production(monkeypatch, tmp_path: Path):
    corpus = tmp_path / "knowledge.jsonl"
    _write(corpus, eligible=False)
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
    monkeypatch.setenv("RELEASE", "prod-v1")
    service.reset_cache()
    result = service.explain_finding(_finding())
    assert result["status"] == "unavailable"
    assert result["reason"] == "no_eligible_knowledge_records"


@pytest.mark.parametrize("release", [None, "", "preview", "prod-v1"])
def test_research_mode_requires_explicit_local_release(monkeypatch, release):
    monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
    if release is None:
        monkeypatch.delenv("RELEASE", raising=False)
    else:
        monkeypatch.setenv("RELEASE", release)
    assert service.research_mode_enabled() is False


@pytest.mark.parametrize("release", ["dev", "development", "local", "test", "ci"])
def test_research_mode_allows_explicit_local_release(monkeypatch, release):
    monkeypatch.setenv("CAD1000_RESEARCH_MODE", "1")
    monkeypatch.setenv("RELEASE", release)
    assert service.research_mode_enabled() is True


def test_eligible_flag_cannot_override_undeclared_license(monkeypatch, tmp_path: Path):
    corpus = tmp_path / "knowledge.jsonl"
    _write(corpus, eligible=True, license_status="UNDECLARED")
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(corpus))
    monkeypatch.delenv("CAD1000_RESEARCH_MODE", raising=False)
    service.reset_cache()
    result = service.explain_finding(_finding())
    assert result["status"] == "unavailable"
    assert result["reason"] == "no_eligible_knowledge_records"


def test_endpoint_is_authenticated_and_feature_gated(monkeypatch):
    app = _app()
    client = TestClient(app)
    monkeypatch.delenv("DESIGN_INTELLIGENCE_ENABLED", raising=False)
    response = client.post(
        "/api/v1/design-intelligence/explain", json={"finding": _finding()}
    )
    assert response.status_code == 503


def test_endpoint_requires_authentication(monkeypatch):
    app = _app()
    app.dependency_overrides.pop(require_api_key)
    client = TestClient(app)
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    response = client.post(
        "/api/v1/design-intelligence/explain", json={"finding": _finding()}
    )
    assert response.status_code == 401


def test_endpoint_returns_advisory_unavailable_without_corpus(monkeypatch, tmp_path: Path):
    app = _app()
    client = TestClient(app)
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setenv("CAD1000_KNOWLEDGE_PATH", str(tmp_path / "missing.jsonl"))
    service.reset_cache()
    response = client.post(
        "/api/v1/design-intelligence/explain", json={"finding": _finding()}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"


def test_endpoint_rejects_extra_fields(monkeypatch):
    app = _app()
    client = TestClient(app)
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    payload = _finding()
    payload["result_json"] = {"attempt": "smuggle verdict input"}
    response = client.post(
        "/api/v1/design-intelligence/explain", json={"finding": payload}
    )
    assert response.status_code == 422


def test_endpoint_rejects_non_finite_values(monkeypatch):
    app = _app()
    client = TestClient(app)
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    payload = _finding()
    payload["measured_value"] = "NaN"
    response = client.post(
        "/api/v1/design-intelligence/explain", json={"finding": payload}
    )
    assert response.status_code == 422


def test_endpoint_requires_active_org_membership(monkeypatch):
    app = _app(org_id=None)
    client = TestClient(app)
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    response = client.post(
        "/api/v1/design-intelligence/explain", json={"finding": _finding()}
    )
    assert response.status_code == 403


def test_saved_endpoint_resolves_duplicate_occurrence_and_audits_citations(monkeypatch):
    analysis = _saved_analysis()
    app = _saved_app(analysis)
    client = TestClient(app)
    seen: dict = {}
    corpus_revision = "c" * 40

    def explain(finding, *, limit):
        seen["finding"] = finding
        seen["limit"] = limit
        return _advisory_result(revision=corpus_revision)

    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setattr(service, "explain_finding", explain)
    monkeypatch.setattr(
        "src.api.design_intelligence.emit_event",
        lambda *args: seen.setdefault("audit", args),
    )
    response = client.post(
        f"/api/v1/design-intelligence/analyses/{analysis.ulid}/explain",
        json={
            "scope": "universal",
            "code": "INTERNAL_RADIUS_TOO_SMALL",
            "occurrence": 1,
            "limit": 4,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert seen["finding"]["message"] == "Second matching engine finding."
    assert "overall_verdict" not in seen["finding"]
    assert seen["limit"] == 4
    assert body["analysis_id"] == analysis.ulid
    assert body["finding_ref"] == {
        "scope": "universal",
        "code": "INTERNAL_RADIUS_TOO_SMALL",
        "occurrence": 1,
    }
    assert body["corpus_revision"] == corpus_revision
    assert body["authority"] == "ADVISORY_ONLY"
    assert body["may_affect_deterministic_verdict"] is False
    audit = seen["audit"]
    assert audit[:4] == (
        1,
        "design_intelligence.explained",
        "analysis",
        analysis.ulid,
    )
    assert audit[4] == {
        "finding_ref": body["finding_ref"],
        "status": "available",
        "citations": [
            "https://example.test/intent",
            "https://example.test/evidence",
        ],
    }
    assert audit[5] == "org-a"
    assert "Bounded response excerpt" not in str(audit[4])


def test_saved_endpoint_resolves_process_finding(monkeypatch):
    analysis = _saved_analysis()
    app = _saved_app(analysis)
    client = TestClient(app)
    seen: dict = {}
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setattr(
        service,
        "explain_finding",
        lambda finding, *, limit: seen.setdefault("finding", finding)
        and _advisory_result(),
    )
    monkeypatch.setattr("src.api.design_intelligence.emit_event", lambda *args: None)
    response = client.post(
        f"/api/v1/design-intelligence/analyses/{analysis.ulid}/explain",
        json={
            "scope": "process",
            "process": "cnc_3axis",
            "code": "TOOL_ACCESS_LIMITED",
            "occurrence": 0,
        },
    )
    assert response.status_code == 200, response.text
    assert seen["finding"]["code"] == "TOOL_ACCESS_LIMITED"
    assert seen["finding"]["process"] == "cnc_3axis"


def test_saved_endpoint_cross_org_and_missing_are_404(monkeypatch):
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    for analysis in (_saved_analysis(org_id="org-b"), None):
        app = _saved_app(analysis, org_id="org-a")
        response = TestClient(app).post(
            "/api/v1/design-intelligence/analyses/01UNKNOWN/explain",
            json={
                "scope": "universal",
                "code": "INTERNAL_RADIUS_TOO_SMALL",
                "occurrence": 0,
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Analysis not found"


def test_saved_endpoint_out_of_range_occurrence_is_404(monkeypatch):
    analysis = _saved_analysis()
    app = _saved_app(analysis)
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    response = TestClient(app).post(
        f"/api/v1/design-intelligence/analyses/{analysis.ulid}/explain",
        json={
            "scope": "universal",
            "code": "INTERNAL_RADIUS_TOO_SMALL",
            "occurrence": 2,
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Finding not found"


def test_saved_endpoint_validates_scope_process_and_rejects_smuggling(monkeypatch):
    analysis = _saved_analysis()
    app = _saved_app(analysis)
    client = TestClient(app)
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    invalid_payloads = [
        {"scope": "process", "code": "TOOL_ACCESS_LIMITED", "occurrence": 0},
        {
            "scope": "universal",
            "process": "cnc_3axis",
            "code": "INTERNAL_RADIUS_TOO_SMALL",
            "occurrence": 0,
        },
        {"scope": "other", "code": "INTERNAL_RADIUS_TOO_SMALL", "occurrence": 0},
        {
            "scope": "universal",
            "code": "INTERNAL_RADIUS_TOO_SMALL",
            "occurrence": 0,
            "message": "smuggled finding prose",
            "overall_verdict": "pass",
        },
    ]
    for payload in invalid_payloads:
        response = client.post(
            f"/api/v1/design-intelligence/analyses/{analysis.ulid}/explain",
            json=payload,
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    "decision",
    [
        "make_in_house",
        "make_outside",
        "acquire_capability",
        "redesign",
    ],
)
def test_feedback_accepts_each_decision_without_intelligence_flag_and_commits(
    monkeypatch, decision
):
    analysis = _saved_analysis()
    app, session = _feedback_app(analysis)
    monkeypatch.delenv("DESIGN_INTELLIGENCE_ENABLED", raising=False)

    response = TestClient(app).put(
        f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback",
        json={"decision": decision},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "analysis_id": analysis.ulid,
        "saved": True,
        "decision": decision,
        "advisory": None,
        "finding_ref": None,
        "source": "authenticated_user",
        "provenance": "user",
    }
    assert session.commits == 1
    assert session.rows[0].detail_json == {
        "decision": decision,
        "source": "authenticated_user",
        "provenance": "user",
    }


@pytest.mark.parametrize("advisory", ["helpful", "not_relevant", "incorrect"])
def test_feedback_accepts_each_advisory_with_server_owned_finding(
    monkeypatch, advisory
):
    analysis = _saved_analysis()
    app, session = _feedback_app(analysis)
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    finding_ref = {
        "scope": "universal",
        "code": "INTERNAL_RADIUS_TOO_SMALL",
        "occurrence": 0,
    }

    response = TestClient(app).put(
        f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback",
        json={"advisory": advisory, "finding_ref": finding_ref},
    )

    assert response.status_code == 200, response.text
    assert response.json()["advisory"] == advisory
    assert response.json()["finding_ref"] == finding_ref
    assert session.commits == 1
    assert session.rows[0].detail_json == {
        "advisory": advisory,
        "finding_ref": finding_ref,
        "source": "authenticated_user",
        "provenance": "user",
    }
    assert session.rows[0].user_email == "analyst@example.com"


def test_feedback_payload_is_strict_and_bounded(monkeypatch):
    analysis = _saved_analysis()
    app, session = _feedback_app(analysis)
    client = TestClient(app)
    monkeypatch.delenv("DESIGN_INTELLIGENCE_ENABLED", raising=False)
    finding_ref = {
        "scope": "universal",
        "code": "INTERNAL_RADIUS_TOO_SMALL",
        "occurrence": 0,
    }
    invalid_payloads = [
        {},
        {"decision": "inhouse"},
        {"decision": "redesign", "quantity": 500},
        {"advisory": "helpful"},
        {"decision": "redesign", "finding_ref": finding_ref},
        {
            "advisory": "helpful",
            "finding_ref": {**finding_ref, "measured_value": 1.2},
        },
        {
            "advisory": "helpful",
            "finding_ref": {**finding_ref, "occurrence": "0"},
        },
        {
            "advisory": "helpful",
            "finding_ref": {**finding_ref, "code": "x" * 129},
        },
    ]

    for payload in invalid_payloads:
        response = client.put(
            f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback",
            json=payload,
        )
        assert response.status_code == 422, payload
    assert session.rows == []
    assert session.commits == 0


def test_feedback_missing_finding_and_cross_org_are_404(monkeypatch):
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    analysis = _saved_analysis()
    app, session = _feedback_app(analysis)
    missing = TestClient(app).put(
        f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback",
        json={
            "advisory": "incorrect",
            "finding_ref": {
                "scope": "universal",
                "code": "DOES_NOT_EXIST",
                "occurrence": 0,
            },
        },
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Finding not found"
    assert session.commits == 0

    foreign = _saved_analysis(org_id="org-b")
    foreign_app, foreign_session = _feedback_app(foreign, org_id="org-a")
    cross_org = TestClient(foreign_app).put(
        f"/api/v1/design-intelligence/analyses/{foreign.ulid}/feedback",
        json={"decision": "redesign"},
    )
    assert cross_org.status_code == 404
    assert cross_org.json()["detail"] == "Analysis not found"
    assert foreign_session.commits == 0


def test_feedback_requires_analyst(monkeypatch):
    analysis = _saved_analysis()
    app, session = _feedback_app(analysis, role="viewer")
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    response = TestClient(app).put(
        f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback",
        json={"decision": "redesign"},
    )
    assert response.status_code == 403
    assert session.rows == []


def test_feedback_never_claims_saved_when_commit_fails(monkeypatch):
    analysis = _saved_analysis()
    app, session = _feedback_app(analysis)
    monkeypatch.delenv("DESIGN_INTELLIGENCE_ENABLED", raising=False)

    async def fail_commit():
        raise RuntimeError("database unavailable")

    session.commit = fail_commit
    response = TestClient(app, raise_server_exceptions=False).put(
        f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback",
        json={"decision": "make_in_house"},
    )
    assert response.status_code == 500
    assert "saved" not in response.text


def test_feedback_readback_preserves_latest_independent_signals_and_is_idempotent(
    monkeypatch,
):
    analysis = _saved_analysis()
    app, session = _feedback_app(analysis)
    client = TestClient(app)
    monkeypatch.delenv("DESIGN_INTELLIGENCE_ENABLED", raising=False)
    url = f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback"
    finding_ref = {
        "scope": "process",
        "process": "cnc_3axis",
        "code": "TOOL_ACCESS_LIMITED",
        "occurrence": 0,
    }

    first = client.put(
        url,
        json={
            "decision": "make_outside",
            "advisory": "helpful",
            "finding_ref": finding_ref,
        },
    )
    repeated = client.put(
        url,
        json={
            "decision": "make_outside",
            "advisory": "helpful",
            "finding_ref": finding_ref,
        },
    )
    advisory = client.put(
        url, json={"advisory": "incorrect", "finding_ref": finding_ref}
    )
    changed = client.put(url, json={"decision": "acquire_capability"})
    readback = client.get(url)

    assert first.status_code == repeated.status_code == advisory.status_code == 200
    assert changed.status_code == readback.status_code == 200
    assert len(session.rows) == 3
    assert session.commits == 4
    assert readback.json() == {
        "analysis_id": analysis.ulid,
        "saved": True,
        "decision": "acquire_capability",
        "advisory": "incorrect",
        "finding_ref": finding_ref,
        "source": "authenticated_user",
        "provenance": "user",
    }


def test_feedback_readback_without_signals_is_an_empty_success(monkeypatch):
    analysis = _saved_analysis()
    app, session = _feedback_app(analysis)
    client = TestClient(app)
    monkeypatch.delenv("DESIGN_INTELLIGENCE_ENABLED", raising=False)
    url = f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback"
    finding_ref = {
        "scope": "universal",
        "code": "INTERNAL_RADIUS_TOO_SMALL",
        "occurrence": 0,
    }

    expected = {
        "analysis_id": analysis.ulid,
        "saved": True,
        "decision": None,
        "advisory": None,
        "finding_ref": None,
        "source": "authenticated_user",
        "provenance": "user",
    }
    analysis_wide = client.get(url)
    finding = client.get(url, params=finding_ref)

    assert analysis_wide.status_code == finding.status_code == 200
    assert analysis_wide.json() == finding.json() == expected
    assert session.rows == []


def test_feedback_readback_restores_each_finding_independently(monkeypatch):
    analysis = _saved_analysis()
    app, session = _feedback_app(analysis)
    client = TestClient(app)
    monkeypatch.delenv("DESIGN_INTELLIGENCE_ENABLED", raising=False)
    url = f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback"
    first_ref = {
        "scope": "universal",
        "code": "INTERNAL_RADIUS_TOO_SMALL",
        "occurrence": 0,
    }
    second_ref = {**first_ref, "occurrence": 1}

    assert client.put(
        url, json={"advisory": "helpful", "finding_ref": first_ref}
    ).status_code == 200
    assert client.put(
        url, json={"advisory": "incorrect", "finding_ref": second_ref}
    ).status_code == 200
    assert client.put(
        url, json={"advisory": "helpful", "finding_ref": first_ref}
    ).status_code == 200

    first = client.get(url, params=first_ref)
    second = client.get(url, params=second_ref)
    analysis_wide = client.get(url)

    assert first.status_code == second.status_code == analysis_wide.status_code == 200
    assert first.json()["advisory"] == "helpful"
    assert first.json()["finding_ref"] == first_ref
    assert second.json()["advisory"] == "incorrect"
    assert second.json()["finding_ref"] == second_ref
    assert analysis_wide.json()["finding_ref"] == second_ref
    assert len(session.rows) == 2
    assert [row.user_email for row in session.rows] == [
        "analyst@example.com",
        "analyst@example.com",
    ]


def test_feedback_readback_rejects_partial_or_unknown_finding_locator(monkeypatch):
    analysis = _saved_analysis()
    app, _ = _feedback_app(analysis)
    client = TestClient(app)
    monkeypatch.delenv("DESIGN_INTELLIGENCE_ENABLED", raising=False)
    url = f"/api/v1/design-intelligence/analyses/{analysis.ulid}/feedback"

    partial = client.get(url, params={"code": "INTERNAL_RADIUS_TOO_SMALL"})
    unknown = client.get(
        url,
        params={"scope": "universal", "code": "UNKNOWN", "occurrence": 0},
    )

    assert partial.status_code == 422
    assert unknown.status_code == 404


def _precedent_result() -> dict:
    return {
        "status": "available",
        "reason": None,
        "analysis_id": "01SAVED000000000000000001",
        "authority": "ADVISORY_ONLY",
        "may_affect_deterministic_verdict": False,
        "corpus_version": org_precedent_service.CORPUS_VERSION,
        "algorithm_version": org_precedent_service.ALGORITHM_VERSION,
        "analysis_version": "1.0.0",
        "current_analysis_version": org_precedent_service.CURRENT_ANALYSIS_VERSION,
        "max_distance": org_precedent_service.MAX_GEOMETRY_DISTANCE,
        "cases": [
            {
                "analysis_id": "01CASE0000000000000000001",
                "filename": "private-customer-part.step",
            }
        ],
        "provenance": {
            "corpus": "ACTIVE_ORGANIZATION_SAVED_ANALYSES",
            "similarity": "DETERMINISTIC_DERIVED_FROM_MEASURED_GEOMETRY",
        },
    }


def test_org_precedent_endpoint_remains_available_when_third_party_feature_is_off(monkeypatch):
    monkeypatch.delenv("DESIGN_INTELLIGENCE_ENABLED", raising=False)
    async def get_precedents(*_args):
        return _precedent_result()

    monkeypatch.setattr(org_precedent_service, "get_org_precedents", get_precedents)
    response = TestClient(_app()).get(
        "/api/v1/design-intelligence/analyses/01TARGET/precedents"
    )
    assert response.status_code == 200


def test_precedent_endpoint_is_member_scoped_and_audits_without_customer_payload(
    monkeypatch,
):
    app = _app(org_id="org-a")
    seen: dict = {}

    async def get_precedents(session, org_id, analysis_ulid, limit):
        seen["call"] = (session.org_id, org_id, analysis_ulid, limit)
        return _precedent_result()

    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setattr(
        org_precedent_service, "get_org_precedents", get_precedents
    )
    monkeypatch.setattr(
        "src.api.design_intelligence.emit_event",
        lambda *args: seen.setdefault("audit", args),
    )
    response = TestClient(app).get(
        "/api/v1/design-intelligence/analyses/01TARGET/precedents?limit=5"
    )

    assert response.status_code == 200, response.text
    assert seen["call"] == ("org-a", "org-a", "01TARGET", 5)
    assert response.json()["cases"][0]["analysis_id"] == "01CASE0000000000000000001"
    audit = seen["audit"]
    assert audit[:4] == (
        1,
        "design_intelligence.precedents_viewed",
        "analysis",
        "01TARGET",
    )
    assert audit[4] == {
        "status": "available",
        "case_count": 1,
        "algorithm_version": org_precedent_service.ALGORITHM_VERSION,
    }
    assert audit[5] == "org-a"
    assert "private-customer-part" not in str(audit)
    assert "01CASE" not in str(audit)


def test_precedent_endpoint_cross_org_or_missing_target_is_404(monkeypatch):
    async def not_found(*_args):
        return None

    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    monkeypatch.setattr(org_precedent_service, "get_org_precedents", not_found)
    response = TestClient(_app(org_id="org-a")).get(
        "/api/v1/design-intelligence/analyses/01FOREIGN/precedents"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Analysis not found"


def test_precedent_endpoint_requires_membership_and_strict_limit(monkeypatch):
    monkeypatch.setenv("DESIGN_INTELLIGENCE_ENABLED", "1")
    missing_member = TestClient(_app(org_id=None)).get(
        "/api/v1/design-intelligence/analyses/01TARGET/precedents"
    )
    assert missing_member.status_code == 404
    for limit in (0, 6, 999):
        response = TestClient(_app()).get(
            f"/api/v1/design-intelligence/analyses/01TARGET/precedents?limit={limit}"
        )
        assert response.status_code == 422
