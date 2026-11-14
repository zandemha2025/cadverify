"""Leakage-safe retrieval evaluation for the CAD1000 advisory corpus.

Queries are human-authored and identify the workflow they were derived from.
Every record from those workflows is held out of the search index; relevance
must instead name other workflows explicitly.  This keeps sibling task,
rubric, and narration text from turning self-retrieval into a fake success.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

from src.corpus.cad1000 import (
    SERVING_INDEX_MAX_RECORDS,
    WorkflowKnowledgeBase,
    advisory_retrieval_eligible,
    production_retrieval_eligible,
    select_serving_records,
)
from src.corpus.paths import CAD1000_KNOWLEDGE

DEFAULT_K = (1, 3, 5)


def load_json_records(path: Path) -> list[dict]:
    """Load either a JSON array/object-with-queries or newline-delimited JSON."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(value, dict):
        value = value.get("queries")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{path} must contain a JSON array, JSONL objects, or {{'queries': [...]}}")
    return value


def split_by_workflow(
    records: Iterable[dict], heldout_workflow_ids: Iterable[str]
) -> tuple[list[dict], list[dict]]:
    """Return stable ``(reference, heldout)`` lists without splitting a workflow."""
    heldout_ids = {str(value).strip() for value in heldout_workflow_ids if str(value).strip()}
    reference: list[dict] = []
    heldout: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("corpus records must be JSON objects")
        workflow_id = str(record.get("workflow_id", "")).strip()
        if not workflow_id:
            raise ValueError("every corpus record must have a workflow_id for group-safe splitting")
        (heldout if workflow_id in heldout_ids else reference).append(record)
    stable = lambda record: json.dumps(record, ensure_ascii=False, sort_keys=True)
    return sorted(reference, key=stable), sorted(heldout, key=stable)


def _validated_queries(queries: Iterable[dict], corpus_workflows: set[str]) -> list[dict]:
    validated: list[dict] = []
    query_ids: set[str] = set()
    for index, query in enumerate(queries):
        if not isinstance(query, dict):
            raise ValueError("queries must be JSON objects")
        query_id = str(query.get("query_id", query.get("id", ""))).strip()
        text = str(query.get("query", query.get("text", ""))).strip()
        workflow_id = str(query.get("workflow_id", "")).strip()
        if not query_id or not text or not workflow_id:
            raise ValueError(
                f"query {index} requires query_id, query text, and source workflow_id"
            )
        if query_id in query_ids:
            raise ValueError(f"duplicate query_id: {query_id}")
        query_ids.add(query_id)
        if workflow_id not in corpus_workflows:
            raise ValueError(f"query {query_id} references unknown workflow_id: {workflow_id}")
        if "relevant_workflow_ids" not in query:
            raise ValueError(f"query {query_id} requires explicit relevant_workflow_ids")
        raw_relevance = query["relevant_workflow_ids"]
        if not isinstance(raw_relevance, list):
            raise ValueError(f"query {query_id} relevant_workflow_ids must be a list")
        relevant = sorted({str(value).strip() for value in raw_relevance if str(value).strip()})
        expected_no_match = query.get("expected_no_match") is True
        if expected_no_match and relevant:
            raise ValueError(
                f"negative query {query_id} cannot include relevance labels"
            )
        if not expected_no_match and not relevant:
            raise ValueError(
                f"query {query_id} requires relevance labels or expected_no_match=true"
            )
        if workflow_id in relevant:
            raise ValueError(f"query {query_id} cannot label its own workflow as relevant")
        unknown = sorted(set(relevant) - corpus_workflows)
        if unknown:
            raise ValueError(f"query {query_id} has unknown relevance labels: {unknown}")
        validated.append(
            {
                **query,
                "query_id": query_id,
                "query": text,
                "workflow_id": workflow_id,
                "relevant_workflow_ids": relevant,
                "expected_no_match": expected_no_match,
                "application": str(query.get("application") or "UNSPECIFIED"),
                "task_family": str(query.get("task_family") or "UNSPECIFIED"),
            }
        )
    return sorted(validated, key=lambda query: query["query_id"])


def _rank_workflows(knowledge: WorkflowKnowledgeBase, query: str) -> list[dict]:
    """Collapse record hits to a deterministic best-score-per-workflow ranking."""
    best: dict[str, dict] = {}
    for hit in knowledge.search(query, limit=max(1, len(knowledge.records))):
        workflow_id = str(hit.record.get("workflow_id", "")).strip()
        if not workflow_id:
            continue
        candidate = {
            "workflow_id": workflow_id,
            "score": hit.score,
            "source_path": str(hit.record.get("source_path", "")),
        }
        current = best.get(workflow_id)
        if current is None or candidate["score"] > current["score"]:
            best[workflow_id] = candidate
    return sorted(
        best.values(),
        key=lambda item: (-item["score"], item["workflow_id"], item["source_path"]),
    )


def compute_metrics(results: Sequence[dict], k_values: Sequence[int] = DEFAULT_K) -> dict:
    """Compute mean reciprocal rank and recall@k with defined empty behavior."""
    ks = _validated_k(k_values)
    count = len(results)
    if not count:
        return {
            "query_count": 0,
            "abstentions": 0,
            "mrr": 0.0,
            "recall_at_k": {str(k): 0.0 for k in ks},
        }

    reciprocal_rank = 0.0
    recalls = {k: 0.0 for k in ks}
    abstentions = 0
    for result in results:
        ranked = list(result.get("ranked_workflow_ids", []))
        relevant = set(result.get("relevant_workflow_ids", []))
        if not ranked:
            abstentions += 1
        first = next((index for index, item in enumerate(ranked, 1) if item in relevant), None)
        if first is not None:
            reciprocal_rank += 1.0 / first
        for k in ks:
            recalls[k] += len(relevant.intersection(ranked[:k])) / len(relevant) if relevant else 0.0
    return {
        "query_count": count,
        "abstentions": abstentions,
        "mrr": reciprocal_rank / count,
        "recall_at_k": {str(k): recalls[k] / count for k in ks},
    }


def _validated_k(k_values: Sequence[int]) -> tuple[int, ...]:
    ks = tuple(sorted({int(value) for value in k_values}))
    if not ks or ks[0] < 1:
        raise ValueError("k values must be positive integers")
    return ks


def evaluate_retrieval(
    records: Iterable[dict],
    queries: Iterable[dict],
    *,
    k_values: Sequence[int] = DEFAULT_K,
    research_mode: bool = False,
    max_index_records: int | None = None,
) -> dict:
    """Evaluate curated queries against the exact bounded serving selection."""
    corpus = list(records)
    workflow_ids = {
        str(record.get("workflow_id", "")).strip()
        for record in corpus
        if isinstance(record, dict) and str(record.get("workflow_id", "")).strip()
    }
    curated = _validated_queries(queries, workflow_ids)
    heldout_ids = {query["workflow_id"] for query in curated}
    reference, heldout = split_by_workflow(corpus, heldout_ids)

    relevance_in_holdout = sorted(
        {
            workflow_id
            for query in curated
            for workflow_id in query["relevant_workflow_ids"]
            if workflow_id in heldout_ids
        }
    )
    if relevance_in_holdout:
        raise ValueError(
            "relevance labels must point to reference workflows, not held-out workflows: "
            f"{relevance_in_holdout}"
        )

    safe_corpus = [
        record
        for record in corpus
        if isinstance(record, dict)
        and advisory_retrieval_eligible(record, include_quarantined=True)
    ]
    quarantined = [record for record in safe_corpus if not production_retrieval_eligible(record)]
    if quarantined and not research_mode:
        raise PermissionError(
            "quarantined corpus requires explicit research_mode=True; production retrieval is disabled"
        )

    index_limit = (
        SERVING_INDEX_MAX_RECORDS
        if max_index_records is None
        else max_index_records
    )
    selection = select_serving_records(
        corpus,
        include_quarantined=research_mode,
        max_records=index_limit,
    )
    indexed_reference, indexed_heldout = split_by_workflow(
        selection.records, heldout_ids
    )
    knowledge = WorkflowKnowledgeBase(
        indexed_reference, include_quarantined=research_mode
    )
    max_k = max(_validated_k(k_values))
    results: list[dict] = []
    for query in curated:
        ranking = _rank_workflows(knowledge, query["query"])
        results.append(
            {
                "query_id": query["query_id"],
                "workflow_id": query["workflow_id"],
                "application": query["application"],
                "task_family": query["task_family"],
                "relevant_workflow_ids": query["relevant_workflow_ids"],
                "expected_no_match": query["expected_no_match"],
                "ranked_workflow_ids": [item["workflow_id"] for item in ranking],
                "top_hits": ranking[:max_k],
                "abstained": not ranking,
            }
        )

    def grouped_metrics(field: str) -> dict:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for result in results:
            if result["expected_no_match"]:
                continue
            grouped[result[field]].append(result)
        return {
            name: compute_metrics(grouped[name], k_values)
            for name in sorted(grouped)
        }

    indexed_workflow_ids = sorted(
        {str(record.get("workflow_id")) for record in knowledge.records}
    )
    positive_results = [result for result in results if not result["expected_no_match"]]
    negative_results = [result for result in results if result["expected_no_match"]]
    false_positive_queries = sum(
        bool(result["ranked_workflow_ids"]) for result in negative_results
    )
    eligible_count = selection.eligible_records_scanned
    return {
        "mode": "research" if research_mode else "production",
        "research_mode": research_mode,
        "quarantined_records": len(quarantined),
        "rejected_records": len(corpus) - len(safe_corpus),
        "serving_index": {
            "max_records": index_limit,
            "eligible_records_scanned": eligible_count,
            "indexed_records": len(selection.records),
            "indexed_eligible_coverage": (
                len(selection.records) / eligible_count if eligible_count else 0.0
            ),
            "index_truncated": selection.index_truncated,
        },
        "split": {
            "strategy": "query_workflow_holdout",
            "reference_workflow_ids": sorted(workflow_ids - heldout_ids),
            "heldout_workflow_ids": sorted(heldout_ids),
            "reference_records": len(reference),
            "heldout_records": len(heldout),
            "indexed_reference_records": len(indexed_reference),
            "indexed_heldout_records": len(indexed_heldout),
            "indexed_workflow_ids": indexed_workflow_ids,
        },
        "overall": compute_metrics(positive_results, k_values),
        "negative_queries": {
            "query_count": len(negative_results),
            "correct_abstentions": len(negative_results) - false_positive_queries,
            "false_positive_queries": false_positive_queries,
            "false_positive_rate": (
                false_positive_queries / len(negative_results)
                if negative_results
                else 0.0
            ),
        },
        "by_application": grouped_metrics("application"),
        "by_task_family": grouped_metrics("task_family"),
        "queries": results,
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CAD1000_KNOWLEDGE)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--k", type=int, nargs="+", default=list(DEFAULT_K))
    parser.add_argument(
        "--research",
        action="store_true",
        help="explicitly opt in to evaluating quarantined/unlicensed records",
    )
    args = parser.parse_args()
    report = evaluate_retrieval(
        load_json_records(args.corpus),
        load_json_records(args.queries),
        k_values=args.k,
        research_mode=args.research,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    _main()
