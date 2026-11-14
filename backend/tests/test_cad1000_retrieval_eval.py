from __future__ import annotations

import json

import pytest

from src.eval.cad1000_retrieval import (
    compute_metrics,
    evaluate_retrieval,
    load_json_records,
    split_by_workflow,
)


def record(workflow_id: str, text: str, *, licensed: bool = True, **extra) -> dict:
    return {
        "workflow_id": workflow_id,
        "source_path": f"solidworks/{workflow_id}",
        "record_type": "workflow",
        "knowledge_role": "design_intent",
        "text": text,
        "application": "SOLIDWORKS",
        "license_status": "CC-BY-4.0" if licensed else "UNDECLARED",
        "rights": {"production_retrieval": licensed},
        "eligible_for_production_retrieval": licensed,
        "engineering_authority": "NONE",
        "is_manufacturing_ground_truth": False,
        "may_affect_deterministic_verdict": False,
        **extra,
    }


def query(
    workflow_id: str = "heldout",
    *,
    text: str = "pocket fillet",
    relevant: list[str] | None = None,
    expected_no_match: bool = False,
) -> dict:
    return {
        "query_id": "q1",
        "query": text,
        "workflow_id": workflow_id,
        "relevant_workflow_ids": ["alpha"] if relevant is None else relevant,
        "expected_no_match": expected_no_match,
        "application": "SOLIDWORKS",
        "task_family": "machined enclosure",
    }


def test_split_holds_out_every_sibling_record_and_is_stable():
    records = [
        record("heldout", "task", record_type="workflow"),
        record("alpha", "reference"),
        record("heldout", "rubric", record_type="rubric"),
        record("heldout", "narration", record_type="workflow_segment"),
    ]

    reference, heldout = split_by_workflow(reversed(records), {"heldout"})

    assert {item["workflow_id"] for item in reference} == {"alpha"}
    assert [item["record_type"] for item in heldout] == [
        "rubric",
        "workflow",
        "workflow_segment",
    ]


def test_evaluation_split_and_ranking_are_deterministic():
    records = [
        record("heldout", "pocket fillet source task", record_type="workflow"),
        record("heldout", "pocket fillet source rubric", record_type="rubric"),
        record("alpha", "pocket fillet"),
        record("beta", "pocket fillet"),
    ]

    first = evaluate_retrieval(records, [query()], k_values=(1, 2))
    second = evaluate_retrieval(reversed(records), [query()], k_values=(2, 1))

    assert first == second
    assert first["split"]["heldout_records"] == 2
    assert first["split"]["indexed_workflow_ids"] == ["alpha", "beta"]
    assert first["queries"][0]["ranked_workflow_ids"] == ["alpha", "beta"]
    assert first["overall"]["mrr"] == 1.0


def test_metrics_mrr_recall_and_empty_arithmetic():
    results = [
        {
            "ranked_workflow_ids": ["x", "a", "b"],
            "relevant_workflow_ids": ["a", "b"],
        },
        {
            "ranked_workflow_ids": ["c"],
            "relevant_workflow_ids": ["c"],
        },
    ]

    assert compute_metrics(results, (1, 2, 3)) == {
        "query_count": 2,
        "abstentions": 0,
        "mrr": 0.75,
        "recall_at_k": {"1": 0.5, "2": 0.75, "3": 1.0},
    }
    assert compute_metrics([], (1, 5)) == {
        "query_count": 0,
        "abstentions": 0,
        "mrr": 0.0,
        "recall_at_k": {"1": 0.0, "5": 0.0},
    }


def test_zero_hit_abstains_and_reports_per_application_and_task_family():
    report = evaluate_retrieval(
        [record("heldout", "source"), record("alpha", "pocket fillet")],
        [query(text="unmatched vocabulary")],
        k_values=(1,),
    )

    expected = {
        "query_count": 1,
        "abstentions": 1,
        "mrr": 0.0,
        "recall_at_k": {"1": 0.0},
    }
    assert report["overall"] == expected
    assert report["by_application"] == {"SOLIDWORKS": expected}
    assert report["by_task_family"] == {"machined enclosure": expected}
    assert report["queries"][0]["abstained"] is True


def test_explicit_negative_query_requires_and_measures_abstention():
    report = evaluate_retrieval(
        [
            record("heldout", "source", knowledge_role="design_requirement"),
            record("alpha", "Adjust the selected sketch geometry"),
        ],
        [
            query(
                text="quantum nebula insurance underwriting adjust orbital temperature",
                relevant=[],
                expected_no_match=True,
            )
        ],
        k_values=(1,),
    )

    assert report["queries"][0]["ranked_workflow_ids"] == []
    assert report["overall"]["query_count"] == 0
    assert report["negative_queries"] == {
        "query_count": 1,
        "correct_abstentions": 1,
        "false_positive_queries": 0,
        "false_positive_rate": 0.0,
    }


def test_eval_cannot_credit_relevant_record_excluded_by_serving_cap():
    candidates = [
        record("alpha", "alpha-only spindle phrase"),
        record("beta", "beta-only impeller phrase"),
    ]
    from src.corpus.cad1000 import select_serving_records

    selected = select_serving_records(candidates, max_records=1).records
    selected_id = selected[0]["workflow_id"]
    excluded = next(item for item in candidates if item["workflow_id"] != selected_id)
    report = evaluate_retrieval(
        [
            record("heldout", "source", knowledge_role="design_requirement"),
            *candidates,
        ],
        [query(text=excluded["text"], relevant=[excluded["workflow_id"]])],
        k_values=(1,),
        max_index_records=1,
    )

    assert excluded["workflow_id"] not in report["split"]["indexed_workflow_ids"]
    assert report["overall"]["mrr"] == 0.0
    assert report["serving_index"] == {
        "max_records": 1,
        "eligible_records_scanned": 3,
        "indexed_records": 1,
        "indexed_eligible_coverage": 1 / 3,
        "index_truncated": True,
    }


def test_relevance_must_be_explicit_non_self_and_in_reference_split():
    records = [record("heldout", "source"), record("other-heldout", "source"), record("alpha", "match")]
    missing = query()
    missing.pop("relevant_workflow_ids")
    with pytest.raises(ValueError, match="explicit relevant_workflow_ids"):
        evaluate_retrieval(records, [missing])
    with pytest.raises(ValueError, match="cannot label its own workflow"):
        evaluate_retrieval(records, [query(relevant=["heldout"])])
    second = {**query("other-heldout", relevant=["alpha"]), "query_id": "q2"}
    with pytest.raises(ValueError, match="reference workflows"):
        evaluate_retrieval(records, [query(relevant=["other-heldout"]), second])
    with pytest.raises(ValueError, match="relevance labels or expected_no_match"):
        evaluate_retrieval(records, [query(relevant=[])])
    with pytest.raises(ValueError, match="cannot include relevance labels"):
        evaluate_retrieval(records, [query(expected_no_match=True)])


def test_quarantine_requires_opt_in_and_existing_kb_rejects_unsafe_authority():
    records = [
        record("heldout", "source", licensed=False),
        record("alpha", "pocket fillet", licensed=False),
        record(
            "unsafe",
            "pocket fillet",
            licensed=False,
            engineering_authority="ENGINEERING_GROUND_TRUTH",
        ),
    ]
    with pytest.raises(PermissionError, match="research_mode=True"):
        evaluate_retrieval(records, [query()], k_values=(1,))

    report = evaluate_retrieval(
        records,
        [query()],
        k_values=(1,),
        research_mode=True,
    )

    assert report["mode"] == "research"
    assert report["research_mode"] is True
    assert report["quarantined_records"] == 2
    assert report["rejected_records"] == 1
    assert report["split"]["indexed_workflow_ids"] == ["alpha"]


def test_loader_accepts_json_jsonl_and_query_envelope(tmp_path):
    array = tmp_path / "array.json"
    lines = tmp_path / "records.jsonl"
    envelope = tmp_path / "queries.json"
    array.write_text(json.dumps([{"a": 1}]))
    lines.write_text('{"a": 1}\n{"a": 2}\n')
    envelope.write_text(json.dumps({"queries": [{"a": 3}]}))

    assert load_json_records(array) == [{"a": 1}]
    assert load_json_records(lines) == [{"a": 1}, {"a": 2}]
    assert load_json_records(envelope) == [{"a": 3}]
