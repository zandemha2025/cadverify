from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from src.services import org_precedent_service as service


def _analysis(
    ulid: str,
    *,
    org_id: str = "org-a",
    bbox=(10.0, 20.0, 40.0),
    volume=8000.0,
    area=2800.0,
    faces=100,
    version=service.CURRENT_ANALYSIS_VERSION,
    mesh_hash=None,
    result_json=None,
):
    result = (
        {
            "geometry": {
                "bounding_box_mm": list(bbox),
                "volume_mm3": volume,
                "surface_area_mm2": area,
                "faces": faces,
            },
            "features": [{"kind": "hole"}, {"kind": "hole"}, {"kind": "flat"}],
            "overall_verdict": "issues",
            "best_process": "cnc_3axis",
            "process_scores": [
                {
                    "process": "cnc_3axis",
                    "recommended_material": "Aluminum 6061",
                    "recommended_machine": "Haas VF-2",
                }
            ],
        }
        if result_json is None
        else result_json
    )
    return SimpleNamespace(
        ulid=ulid,
        org_id=org_id,
        filename=f"{ulid}.step",
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        analysis_version=version,
        mesh_hash=mesh_hash or f"hash:{ulid}",
        result_json=result,
    )


def test_nearest_order_is_deterministic_and_engine_fields_are_provenanced():
    target = _analysis("target")
    farther = _analysis("z-far", bbox=(30, 30, 30), volume=27000, area=5400, faces=400)
    tied_b = _analysis("b-near", bbox=(10.5, 20.5, 40.5), volume=8500, area=2900, faces=105)
    tied_a = _analysis("a-near", bbox=(10.5, 20.5, 40.5), volume=8500, area=2900, faces=105)

    result = service.rank_precedents(target, [farther, tied_b, tied_a], 3)

    assert [row["analysis_id"] for row in result["cases"]] == ["a-near", "b-near"]
    case = result["cases"][0]
    assert case["analysis_url"] == "/analyses/a-near"
    assert case["analysis_api_url"] == "/api/v1/analyses/a-near"
    assert case["verdict"] == "issues"
    assert case["best_process"] == "cnc_3axis"
    assert case["recommended_material"] == "Aluminum 6061"
    assert case["recommended_machine"] == "Haas VF-2"
    assert 2 <= len(case["shared_geometry"]) <= 3
    assert {item["provenance"] for item in case["shared_geometry"]} <= {
        "MEASURED",
        "MEASURED_DERIVED",
    }
    assert case["provenance"] == {
        "identity": "SAVED_ANALYSIS_METADATA",
        "geometry": "MEASURED",
        "similarity": "DETERMINISTIC",
        "verdict": "ENGINE",
        "route": "ENGINE",
        "material": "ENGINE",
        "machine": "ENGINE",
        "staleness": "SAVED_ANALYSIS_METADATA",
        "actual_outcome": "NOT_LINKED",
    }
    assert result["algorithm_version"] == service.ALGORITHM_VERSION
    assert result["corpus_version"] == service.CORPUS_VERSION
    assert result["may_affect_deterministic_verdict"] is False


def test_unusable_geometry_abstains_and_bad_candidates_are_skipped():
    bad_target = _analysis("target", result_json={"geometry": {"bounding_box_mm": [1, 0, 3]}})
    assert service.rank_precedents(bad_target, [], 3)["reason"] == "target_geometry_unusable"

    target = _analysis("target")
    bad_candidate = _analysis("bad", result_json={"geometry": {}})
    result = service.rank_precedents(target, [bad_candidate], 3)
    assert result["status"] == "no_match"
    assert result["cases"] == []


def test_self_cross_org_and_strict_max_are_enforced_defensively():
    target = _analysis("target")
    candidates = [target, _analysis("foreign", org_id="org-b")]
    candidates.extend(_analysis(f"case-{index}") for index in range(8))

    result = service.rank_precedents(target, candidates, 999)

    assert len(result["cases"]) == 5
    assert "target" not in {row["analysis_id"] for row in result["cases"]}
    assert "foreign" not in {row["analysis_id"] for row in result["cases"]}


def test_same_mesh_reruns_and_unrelated_geometry_are_not_called_precedents():
    target = _analysis("target", mesh_hash="same-part")
    rerun = _analysis("rerun", mesh_hash="same-part")
    unrelated = _analysis(
        "unrelated",
        bbox=(1000, 1000, 1000),
        volume=1_000_000_000,
        area=6_000_000,
        faces=10_000,
    )

    result = service.rank_precedents(target, [rerun, unrelated], 3)

    assert result["status"] == "no_match"
    assert result["cases"] == []
    assert result["max_distance"] == service.MAX_GEOMETRY_DISTANCE


def test_proportional_but_radically_different_scale_abstains_without_metrics():
    target = _analysis("target", bbox=(1, 2, 4), volume=None, area=None, faces=None)
    huge = _analysis(
        "huge", bbox=(1000, 2000, 4000), volume=None, area=None, faces=None
    )
    close = _analysis(
        "close", bbox=(1.05, 2.05, 4.1), volume=None, area=None, faces=None
    )

    result = service.rank_precedents(target, [huge, close], 3)

    assert [case["analysis_id"] for case in result["cases"]] == ["close"]


def test_analysis_version_marks_stale_without_claiming_validation():
    result = service.rank_precedents(
        _analysis("target", version="1.0.0"),
        [_analysis("old", version="1.0.0")],
        1,
    )
    case = result["cases"][0]
    assert result["analysis_version"] == "1.0.0"
    assert result["current_analysis_version"] == service.CURRENT_ANALYSIS_VERSION
    assert case["analysis_version"] == "1.0.0"
    assert case["stale"] is True
    assert case["provenance"]["actual_outcome"] == "NOT_LINKED"
    assert "validated" not in str(case).lower()


class _OneResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ManyResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class _Session:
    def __init__(self, target, candidates):
        self.results = [_OneResult(target), _ManyResult(candidates)]
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


def test_database_queries_scope_target_and_candidates_to_org_and_exclude_self():
    target = _analysis("target")
    session = _Session(target, [_analysis("near")])

    result = asyncio.run(service.get_org_precedents(session, "org-a", "target", 1))

    assert result["cases"][0]["analysis_id"] == "near"
    target_sql = str(
        session.statements[0].compile(compile_kwargs={"literal_binds": True})
    )
    candidates_sql = str(
        session.statements[1].compile(compile_kwargs={"literal_binds": True})
    )
    assert "analyses.org_id = 'org-a'" in target_sql
    assert "analyses.ulid = 'target'" in target_sql
    assert "analyses.org_id = 'org-a'" in candidates_sql
    assert "analyses.ulid != 'target'" in candidates_sql


def test_missing_or_cross_tenant_target_returns_none_before_candidate_query():
    session = _Session(None, [])
    result = asyncio.run(service.get_org_precedents(session, "org-a", "foreign", 3))
    assert result is None
    assert len(session.statements) == 1


def test_bounded_candidate_search_discloses_truncation():
    target = _analysis("target")
    candidates = [_analysis(f"case-{index:04d}") for index in range(502)]
    session = _Session(target, candidates)

    result = asyncio.run(service.get_org_precedents(session, "org-a", "target", 3))

    assert result["search_truncated"] is True
    assert result["candidates_examined"] == service.MAX_PRECEDENT_CANDIDATES
    sql = str(session.statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert f"LIMIT {service.MAX_PRECEDENT_CANDIDATES + 1}" in sql
