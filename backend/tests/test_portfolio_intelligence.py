from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.services import portfolio_intelligence_service as service

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _issue(code: str, severity: str = "error", message: str | None = None) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message or code.replace("_", " ").title(),
        "fix_suggestion": f"Fix {code}",
    }


def _analysis(
    ulid: str,
    part: str,
    *,
    org: str = "org-a",
    created_at: datetime = NOW,
    version: str = "0.3.0",
    universal: object = None,
    scores: object = None,
    result_json: object = None,
):
    result = (
        {
            "universal_issues": [] if universal is None else universal,
            "process_scores": [] if scores is None else scores,
        }
        if result_json is None
        else result_json
    )
    return SimpleNamespace(
        ulid=ulid,
        org_id=org,
        mesh_hash=part,
        filename=f"{part}.step",
        created_at=created_at,
        analysis_version=version,
        result_json=result,
    )


def _summary(
    part: str,
    analysis_id: str,
    *,
    org: str = "org-a",
    row_json: object = None,
):
    return SimpleNamespace(
        id=1,
        org_id=org,
        mesh_hash=part,
        updated_at=NOW,
        row_json=(
            {"analysis": {"id": analysis_id}}
            if row_json is None
            else row_json
        ),
    )


def test_clusters_are_deterministic_latest_part_deduped_and_stale_visible():
    analyses = [
        # Historical rerun for p1 must not inflate OLD_ONLY or recurrence.
        _analysis(
            "a-old",
            "p1",
            created_at=NOW - timedelta(days=1),
            universal=[_issue("OLD_ONLY")],
        ),
        _analysis(
            "a1",
            "p1",
            universal=[
                _issue("THIN_WALL", "warning", "warning first"),
                _issue("THIN_WALL", message="Z thin wall"),
                _issue("THIN_WALL", message="duplicate must not count"),
            ],
            scores=[
                {
                    "process": "cnc_3axis",
                    "issues": [_issue("NO_FIXTURE", message="No fixture")],
                }
            ],
        ),
        _analysis(
            "a2",
            "p2",
            universal=[_issue("THIN_WALL", "critical", "A thin wall")],
            scores=[
                {"process": "cnc_3axis", "issues": [_issue("NO_FIXTURE")]},
            ],
        ),
        _analysis(
            "a3",
            "p3",
            version="0.2.0",
            universal=[_issue("THIN_WALL")],
            scores=[
                {"process": "cnc_3axis", "issues": [_issue("SINGLETON")]},
            ],
        ),
        _analysis("foreign", "foreign-part", org="org-b", universal=[_issue("THIN_WALL")]),
    ]
    summaries = [
        _summary("p1", "a1"),
        _summary("p2", "older-projection"),
        _summary("p3", "a3"),
        _summary("foreign-part", "foreign", org="org-b"),
    ]

    first = service.cluster_blockers(analyses, summaries, "org-a")
    second = service.cluster_blockers(reversed(analyses), reversed(summaries), "org-a")

    assert first == second
    assert [row["code"] for row in first["clusters"]] == ["THIN_WALL", "NO_FIXTURE"]
    thin = first["clusters"][0]
    assert thin["affected_part_count"] == 3
    assert [row["part_key"] for row in thin["affected_parts"]] == ["p1", "p2", "p3"]
    assert thin["affected_parts"][0]["finding_ref"] == {
        "scope": "universal",
        "code": "THIN_WALL",
        "occurrence": 1,
    }
    assert thin["message"] == "Engine finding recurs with part-specific details"
    assert thin["stale"] is True and thin["stale_part_count"] == 2
    assert thin["count_basis"] == "distinct_latest_parts"
    assert thin["provenance"]["findings"] == "SAVED_ENGINE_FINDINGS"
    assert first["summary"] == {
        "latest_part_count": 3,
        "parts_with_blockers": 3,
        "recurring_cluster_count": 2,
        "recurring_affected_part_count": 3,
        "stale_affected_part_count": 2,
        "part_summary_count": 3,
        "malformed_analysis_count": 0,
        "malformed_part_summary_count": 0,
        "truncated": False,
    }
    assert "OLD_ONLY" not in str(first)
    assert "foreign-part" not in str(first)


def test_malformed_stored_results_are_skipped_without_losing_valid_blockers():
    analyses = [
        _analysis("bad", "p0", result_json="not-json-object"),
        _analysis(
            "a1",
            "p1",
            universal="not-a-list",
            scores=[
                None,
                {"process": "cnc_3axis", "issues": [None, _issue("BLOCK")]},
            ],
        ),
        _analysis(
            "a2",
            "p2",
            scores=[{"process": "cnc_3axis", "issues": [_issue("BLOCK")]}],
        ),
    ]
    summaries = [_summary("p1", "a1", row_json="bad"), _summary("p2", "a2")]

    result = service.cluster_blockers(analyses, summaries, "org-a")

    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["code"] == "BLOCK"
    assert result["clusters"][0]["affected_part_count"] == 2
    assert result["summary"]["malformed_analysis_count"] == 2
    assert result["summary"]["malformed_part_summary_count"] == 1
    p1 = result["clusters"][0]["affected_parts"][0]
    assert p1["staleness"]["part_summary"] == "malformed"
    assert p1["stale"] is True


def test_part_specific_fixes_are_never_laundered_into_cluster_advice():
    left = _issue("THIN_WALL", message="Wall is 0.4 mm")
    right = _issue("THIN_WALL", message="Wall is 0.8 mm")
    left["fix_suggestion"] = "Increase rib A"
    right["fix_suggestion"] = "Change material B"
    result = service.cluster_blockers(
        [_analysis("a1", "p1", universal=[left]), _analysis("a2", "p2", universal=[right])],
        [_summary("p1", "a1"), _summary("p2", "a2")],
        "org-a",
    )
    cluster = result["clusters"][0]
    assert cluster["fix_suggestion"] is None
    assert cluster["message"] == "Engine finding recurs with part-specific details"
    assert {row["fix_suggestion"] for row in cluster["affected_parts"]} == {
        "Increase rib A",
        "Change material B",
    }


def test_missing_part_summary_is_stale_not_current():
    result = service.cluster_blockers(
        [
            _analysis("a1", "p1", universal=[_issue("BLOCK")]),
            _analysis("a2", "p2", universal=[_issue("BLOCK")]),
        ],
        [],
        "org-a",
    )
    assert result["clusters"][0]["stale_part_count"] == 2
    assert all(
        row["staleness"]["part_summary"] == "missing" and row["stale"]
        for row in result["clusters"][0]["affected_parts"]
    )


def test_empty_state_is_zeroed_and_declares_no_llm_inference():
    result = service.cluster_blockers([], [], "org-a")

    assert result["clusters"] == []
    assert all(value == 0 for value in result["summary"].values())
    assert result["provenance"]["llm_inference"] is False
    assert (
        result["provenance"]["source"]
        == "ACTIVE_ORGANIZATION_LATEST_SAVED_ANALYSES"
    )
    assert result["provenance"]["minimum_distinct_parts"] == 2


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, analyses, summaries):
        self.results = [_Result(analyses), _Result(summaries)]
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


def test_database_reads_are_org_scoped_and_defensively_exclude_foreign_rows():
    session = _Session(
        [
            _analysis("a1", "p1", universal=[_issue("BLOCK")]),
            _analysis("foreign", "foreign", org="org-b", universal=[_issue("BLOCK")]),
        ],
        [_summary("foreign", "foreign", org="org-b")],
    )

    result = asyncio.run(service.build_blocker_clusters(session, "org-a"))

    assert result["clusters"] == []
    assert result["summary"]["latest_part_count"] == 1
    sql = [
        str(statement.compile(compile_kwargs={"literal_binds": True}))
        for statement in session.statements
    ]
    assert "analyses.org_id = 'org-a'" in sql[0]
    assert f"LIMIT {service.MAX_BLOCKER_PARTS + 1}" in sql[0]
    assert "part_summaries.org_id = 'org-a'" in sql[1]


def test_missing_org_performs_no_database_read():
    session = _Session([], [])
    result = asyncio.run(service.build_blocker_clusters(session, None))
    assert result["clusters"] == []
    assert session.statements == []


def test_database_scan_is_bounded_and_truthfully_marked_truncated():
    analyses = [
        _analysis(f"a-{index:05d}", f"p-{index:05d}")
        for index in range(service.MAX_BLOCKER_PARTS + 1)
    ]
    session = _Session(analyses, [])

    result = asyncio.run(service.build_blocker_clusters(session, "org-a"))

    assert result["summary"]["latest_part_count"] == service.MAX_BLOCKER_PARTS
    assert result["summary"]["truncated"] is True
    assert result["provenance"]["scope"] == "MOST_RECENT_LATEST_PARTS_BOUNDED"


@pytest.mark.asyncio
async def test_endpoint_uses_the_resolved_active_org(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.api import portfolio_intelligence as api
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api.router, prefix="/api/v1/portfolio-intelligence")
    session = object()
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=7, api_key_id=1, key_prefix="test", role="viewer"
    )
    app.dependency_overrides[get_db_session] = lambda: session
    seen = {}

    async def resolve_org(_session, user_id):
        assert _session is session and user_id == 7
        return "org-a"

    async def build(_session, org_id):
        seen["args"] = (_session, org_id)
        return {"clusters": [], "summary": {}, "provenance": {}}

    monkeypatch.setattr(api, "resolve_org", resolve_org)
    monkeypatch.setattr(api.service, "build_blocker_clusters", build)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/portfolio-intelligence/blocker-clusters"
        )

    assert response.status_code == 200
    assert seen["args"] == (session, "org-a")


@pytest.mark.asyncio
async def test_endpoint_requires_active_org_membership(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.api import portfolio_intelligence as api
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api.router, prefix="/api/v1/portfolio-intelligence")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=7, api_key_id=1, key_prefix="test", role="viewer"
    )
    app.dependency_overrides[get_db_session] = lambda: object()

    async def no_org(*_args):
        return None

    async def must_not_build(*_args):
        raise AssertionError("portfolio service must not run without an org")

    monkeypatch.setattr(api, "resolve_org", no_org)
    monkeypatch.setattr(api.service, "build_blocker_clusters", must_not_build)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/portfolio-intelligence/blocker-clusters"
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Organization membership required"
