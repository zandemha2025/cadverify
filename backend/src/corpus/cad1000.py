"""Metadata-only ingestion and retrieval for ``markov-ai/cad-1000-hours``.

The source is a workflow dataset, not engineering ground truth.  Its task text,
narration and rubrics can ground instructional context, but must never modify a
deterministic makeability verdict or be represented as measured evidence.

The dataset currently declares no license.  Records are therefore quarantined
by default: they are useful for local evaluation only and are excluded from
retrieval/training unless a caller explicitly opts in after obtaining rights.
Video, event streams, inputs and output CAD files are deliberately not fetched.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import re
import urllib.parse
import urllib.request
from collections.abc import Mapping
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from src.corpus.paths import CAD1000_KNOWLEDGE

DATASET_ID = "markov-ai/cad-1000-hours"
DATASET_REVISION = "b1bd4711343017fc40dfa6fe40a6cd338b7edaf6"
DATASET_URL = f"https://huggingface.co/datasets/{DATASET_ID}"
API_URL = (
    f"https://huggingface.co/api/datasets/{DATASET_ID}/revision/{DATASET_REVISION}"
)
RAW_URL = f"{DATASET_URL}/raw/{DATASET_REVISION}"
LICENSE_STATUS = "UNDECLARED"
# The platform verifies manufactured parts.  Architecture/BIM/drafting traces
# may be useful to a generic CAD agent, but are not the default CadVerify corpus.
CADVERIFY_CORE_SOFTWARE = frozenset({"solidworks", "catia", "nx-cad"})
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+.-]*", re.IGNORECASE)
_STOPWORDS = frozenset(
    "a an and are as at be by for from in into is it of on or that the this to was were with".split()
)
_MIN_QUERY_TOKEN_COVERAGE = 0.30
SERVING_INDEX_ROLES = ("design_intent", "design_requirement", "authoring_trace")
SERVING_INDEX_MAX_RECORDS = 12_000
SERVING_INDEX_MAX_TEXT_CHARS = 4_096
SERVING_INDEX_MAX_METADATA_CHARS = 1_024
_SERVING_COMPACT_KEYS = (
    "dataset_revision",
    "workflow_id",
    "application",
    "software",
    "task",
    "knowledge_role",
    "record_type",
    "source_path",
    "workflow",
    "start_s",
    "end_s",
    "license_status",
    "eligible_for_production_retrieval",
    "engineering_authority",
    "is_manufacturing_ground_truth",
    "may_affect_deterministic_verdict",
)

JsonFetcher = Callable[[str], object]


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url, headers={"User-Agent": "cadverify-cad1000-ingester/0.1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _artifact_url(workflow_path: str, filename: str) -> str:
    path = urllib.parse.quote(f"{workflow_path}/{filename}", safe="/")
    return f"{RAW_URL}/{path}"


def discover_workflows(
    application: Optional[str] = None,
    *,
    cadverify_core_only: bool = False,
    fetch_json: JsonFetcher = _fetch_json,
) -> list[str]:
    """Return workflow paths from the dataset file manifest.

    Dataset-info is used instead of the paginated tree endpoint so applications
    with more than 1,000 artifact files are not silently truncated.
    """
    info = fetch_json(f"{API_URL}?blobs=false")
    if not isinstance(info, dict):
        raise ValueError("Hugging Face dataset info was not an object")
    prefix = f"{application.strip('/')}/" if application else None
    paths = {
        str(item["rfilename"]).removesuffix("/task_desc.json")
        for item in info.get("siblings", [])
        if isinstance(item, dict)
        and str(item.get("rfilename", "")).endswith("/task_desc.json")
        and (prefix is None or str(item.get("rfilename", "")).startswith(prefix))
        and (
            not cadverify_core_only
            or str(item.get("rfilename", "")).split("/", 1)[0]
            in CADVERIFY_CORE_SOFTWARE
        )
    }
    return sorted(paths)


def _base_record(path: str, task: dict, metadata: dict) -> dict:
    return {
        "schema_version": "1.0",
        "dataset": DATASET_ID,
        "dataset_revision": DATASET_REVISION,
        "dataset_url": DATASET_URL,
        "workflow_id": path.rsplit("/", 1)[-1],
        "software": path.split("/", 1)[0],
        "domain": task.get("domain"),
        "application": task.get("application"),
        "task": task.get("task"),
        "description": task.get("description"),
        "deliverables": task.get("deliverables", []),
        "duration_ms": metadata.get("total_duration_ms"),
        "total_frames": metadata.get("total_frames"),
        "event_count": metadata.get("event_count"),
        "fps": metadata.get("fps"),
        "source_path": path,
        "source_kind": "third_party_workflow_demonstration",
        "provenance": "THIRD_PARTY_UNVERIFIED",
        "engineering_authority": "NONE",
        "is_manufacturing_ground_truth": False,
        "license_status": LICENSE_STATUS,
        "eligible_for_training": False,
        "eligible_for_production_retrieval": False,
        "may_affect_deterministic_verdict": False,
        "allowed_uses": [
            "design_intent_retrieval",
            "requirement_interpretation",
            "redesign_explanation_context",
        ],
        "forbidden_uses": [
            "manufacturing_feasibility_decision",
            "machine_capability_decision",
            "material_environment_validation",
            "validated_cost_or_time_claim",
        ],
    }


def workflow_records(
    path: str,
    *,
    fetch_json: JsonFetcher = _fetch_json,
) -> Iterator[dict]:
    """Yield retrieval-sized records for one workflow's small JSON artifacts."""
    values = {
        name: fetch_json(_artifact_url(path, name))
        for name in ("task_desc.json", "metadata.json", "rubrics.json", "narration.json")
    }
    task = values["task_desc.json"]
    metadata = values["metadata.json"]
    rubrics = values["rubrics.json"]
    narration = values["narration.json"]
    if not all(isinstance(value, dict) for value in (task, metadata, rubrics, narration)):
        raise ValueError(f"Unexpected artifact shape for workflow {path}")
    assert isinstance(task, dict)
    assert isinstance(metadata, dict)
    assert isinstance(rubrics, dict)
    assert isinstance(narration, dict)
    base = _base_record(path, task, metadata)
    overview = "\n".join(filter(None, (task.get("task"), task.get("description"))))
    if overview:
        yield {
            **base,
            "record_type": "workflow",
            "knowledge_role": "design_intent",
            "text": overview,
        }

    for rubric in rubrics.get("rubrics", []):
        if isinstance(rubric, dict) and rubric.get("requirement"):
            yield {
                **base,
                "record_type": "rubric",
                "knowledge_role": "design_requirement",
                "rubric_id": rubric.get("id"),
                "text": rubric["requirement"],
            }

    for index, annotation in enumerate(narration.get("annotations", [])):
        if not isinstance(annotation, dict):
            continue
        text = "\n".join(
            filter(None, (annotation.get("action"), annotation.get("intent"), annotation.get("details")))
        )
        if not text:
            continue
        yield {
            **base,
            "record_type": "workflow_segment",
            "knowledge_role": "authoring_trace",
            "segment_index": index,
            "start_s": annotation.get("start_s"),
            "end_s": annotation.get("end_s"),
            "segment_app": annotation.get("app"),
            "action": annotation.get("action"),
            "intent": annotation.get("intent"),
            "text": text,
        }


def ingest(
    output: Path = CAD1000_KNOWLEDGE,
    *,
    rights_manifest: Optional[Path] = None,
    application: Optional[str] = None,
    all_software: bool = False,
    limit: Optional[int] = None,
    fetch_json: JsonFetcher = _fetch_json,
) -> dict:
    """Write an atomic, metadata-only JSONL snapshot and return its counts."""
    # The legacy network builder is retained only for a rights-cleared textual
    # pilot. The manifest/refinery pipeline is the canonical full-data path.
    # Check before discovery so an ungranted run performs zero network or disk I/O.
    if rights_manifest is None:
        raise PermissionError("a reviewed rights manifest is required before ingestion")
    from src.corpus.cad1000_manifest import load_manifest

    manifest = load_manifest(rights_manifest)
    if (
        manifest.get("dataset_revision") != DATASET_REVISION
        or manifest.get("rights", {}).get("local_research") is not True
    ):
        raise PermissionError("manifest does not grant local_research rights")
    paths = discover_workflows(
        application,
        cadverify_core_only=application is None and not all_software,
        fetch_json=fetch_json,
    )
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        paths = paths[:limit]
    if not paths:
        raise ValueError(f"No workflows found for application={application!r}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    counts: Counter[str] = Counter()
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            for path in paths:
                for record in workflow_records(path, fetch_json=fetch_json):
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    counts[record["record_type"]] += 1
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "dataset": DATASET_ID,
        "workflows": len(paths),
        "records": sum(counts.values()),
        "record_types": dict(sorted(counts.items())),
        "license_status": LICENSE_STATUS,
        "production_eligible": False,
        "scope": (
            f"application:{application}"
            if application
            else "all-software" if all_software else "cadverify-core-mechanical"
        ),
        "output": str(output),
    }


def _token_sequence(value: str, *, include_stopwords: bool = False) -> list[str]:
    tokens = [token.lower().rstrip(".-") for token in _TOKEN_RE.findall(value)]
    return [
        token
        for token in tokens
        if token and (include_stopwords or token not in _STOPWORDS)
    ]


def _tokens(value: str) -> Counter[str]:
    return Counter(_token_sequence(value))


def _content_bigrams(value: str) -> set[tuple[str, str]]:
    tokens = _token_sequence(value, include_stopwords=True)
    return {
        (left, right)
        for left, right in zip(tokens, tokens[1:])
        if left not in _STOPWORDS and right not in _STOPWORDS
    }


@dataclass(frozen=True)
class SearchHit:
    score: float
    record: dict


def _is_advisory_record(record: dict) -> bool:
    return (
        record.get("engineering_authority") == "NONE"
        and record.get("may_affect_deterministic_verdict") is False
        and record.get("is_manufacturing_ground_truth") is False
    )


def production_retrieval_eligible(record: dict) -> bool:
    """Require both explicit rights clearance and the advisory-only contract."""
    license_status = str(record.get("license_status", "")).strip().upper()
    rights = record.get("rights")
    return (
        _is_advisory_record(record)
        and isinstance(rights, Mapping)
        and rights.get("production_retrieval") is True
        and record.get("eligible_for_production_retrieval") is True
        and license_status not in {"", "NONE", "NULL", "UNDECLARED", "UNKNOWN"}
    )


def advisory_retrieval_eligible(
    record: dict, *, include_quarantined: bool = False
) -> bool:
    return _is_advisory_record(record) and (
        include_quarantined or production_retrieval_eligible(record)
    )


def _compact_scalar(value: object, max_chars: int) -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)[:max_chars]


def _compact_serving_record(
    record: dict, *, max_text_chars: int, max_metadata_chars: int
) -> dict:
    compact = {
        key: _compact_scalar(record[key], max_metadata_chars)
        for key in _SERVING_COMPACT_KEYS
        if key in record
    }
    compact["text"] = str(record.get("text", ""))[:max_text_chars]
    rights = record.get("rights")
    if isinstance(rights, Mapping):
        compact["rights"] = {
            "production_retrieval": rights.get("production_retrieval") is True
        }
    timestamp = record.get("timestamp_range")
    if isinstance(timestamp, dict):
        compact["timestamp_range"] = {
            key: _compact_scalar(timestamp.get(key), max_metadata_chars)
            for key in ("start", "end")
        }
    return compact


@dataclass(frozen=True)
class ServingRecordSelection:
    records: tuple[dict, ...]
    eligible_records_scanned: int
    index_truncated: bool


def select_serving_records(
    records: Iterable[dict],
    *,
    include_quarantined: bool = False,
    max_records: int = SERVING_INDEX_MAX_RECORDS,
    max_text_chars: int = SERVING_INDEX_MAX_TEXT_CHARS,
    max_metadata_chars: int = SERVING_INDEX_MAX_METADATA_CHARS,
    roles: tuple[str, ...] = SERVING_INDEX_ROLES,
) -> ServingRecordSelection:
    """Apply the production index's deterministic role-balanced selection."""
    if max_records < 1 or max_text_chars < 1 or max_metadata_chars < 1 or not roles:
        raise ValueError("serving index limits and roles must be non-empty and positive")
    base, remainder = divmod(max_records, len(roles))
    quotas = {
        role: base + (position < remainder) for position, role in enumerate(roles)
    }
    heaps: dict[str, list[tuple[int, int, dict]]] = {
        role: [] for role, quota in quotas.items() if quota
    }
    eligible_records_scanned = 0
    sequence = 0
    for record in records:
        if not isinstance(record, dict) or not advisory_retrieval_eligible(
            record, include_quarantined=include_quarantined
        ):
            continue
        eligible_records_scanned += 1
        role = record.get("knowledge_role")
        if not isinstance(role, str) or role not in heaps:
            continue
        compact = _compact_serving_record(
            record,
            max_text_chars=max_text_chars,
            max_metadata_chars=max_metadata_chars,
        )
        canonical = json.dumps(
            compact, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        rank = int.from_bytes(hashlib.sha256(canonical).digest()[:8], "big")
        item = (-rank, sequence, compact)
        sequence += 1
        heap = heaps[role]
        if len(heap) < quotas[role]:
            heapq.heappush(heap, item)
        elif rank < -heap[0][0]:
            heapq.heapreplace(heap, item)

    selected = [item for heap in heaps.values() for item in heap]
    selected.sort(
        key=lambda item: (
            -item[0],
            str(item[2].get("source_path") or item[2].get("workflow") or ""),
        )
    )
    return ServingRecordSelection(
        records=tuple(item[2] for item in selected),
        eligible_records_scanned=eligible_records_scanned,
        index_truncated=eligible_records_scanned > len(selected),
    )


class WorkflowKnowledgeBase:
    """Small dependency-free BM25 index for evaluation and integration pilots."""

    def __init__(self, records: Iterable[dict], *, include_quarantined: bool = False):
        self.records = [
            record
            for record in records
            if isinstance(record, dict)
            and _is_advisory_record(record)
            and (include_quarantined or production_retrieval_eligible(record))
        ]
        self.documents = [_tokens(str(record.get("text", ""))) for record in self.records]
        self.document_frequency: Counter[str] = Counter()
        for document in self.documents:
            self.document_frequency.update(document.keys())
        self.average_length = (
            sum(sum(document.values()) for document in self.documents) / len(self.documents)
            if self.documents
            else 0.0
        )

    @classmethod
    def from_jsonl(
        cls, path: Path = CAD1000_KNOWLEDGE, *, include_quarantined: bool = False
    ) -> "WorkflowKnowledgeBase":
        with path.open(encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        return cls(records, include_quarantined=include_quarantined)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        application: Optional[str] = None,
        record_type: Optional[str] = None,
        knowledge_role: Optional[str] = None,
    ) -> list[SearchHit]:
        if limit < 1 or not self.records:
            return []
        query_tokens = _tokens(query)
        query_bigrams = _content_bigrams(query)
        total = len(self.records)
        k1, b = 1.5, 0.75
        hits: list[SearchHit] = []
        for record, document in zip(self.records, self.documents):
            if application and str(record.get("application", "")).lower() != application.lower():
                continue
            if record_type and record.get("record_type") != record_type:
                continue
            if knowledge_role and record.get("knowledge_role") != knowledge_role:
                continue
            length = max(1, sum(document.values()))
            score = 0.0
            for token, query_count in query_tokens.items():
                frequency = document.get(token, 0)
                if not frequency:
                    continue
                df = self.document_frequency[token]
                inverse_frequency = math.log(1.0 + (total - df + 0.5) / (df + 0.5))
                denominator = frequency + k1 * (
                    1.0 - b + b * length / max(1.0, self.average_length)
                )
                score += query_count * inverse_frequency * frequency * (k1 + 1.0) / denominator
            matched = query_tokens.keys() & document.keys()
            relevant = len(query_tokens) == 1 and bool(matched)
            if len(matched) >= 2:
                relevant = (
                    len(matched) / len(query_tokens) >= _MIN_QUERY_TOKEN_COVERAGE
                    or bool(query_bigrams & _content_bigrams(str(record.get("text", ""))))
                )
            if score > 0 and relevant:
                hits.append(SearchHit(score=score, record=record))
        return sorted(hits, key=lambda hit: (-hit.score, hit.record.get("source_path", "")))[:limit]


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--application", help="dataset directory, e.g. autocad")
    scope.add_argument(
        "--all-software",
        action="store_true",
        help="include architecture/BIM/drafting workflows (excluded by default)",
    )
    parser.add_argument("--limit", type=int, help="pilot workflow count")
    parser.add_argument("--output", type=Path, default=CAD1000_KNOWLEDGE)
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="reviewed pinned manifest granting local_research rights",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            ingest(
                args.output,
                rights_manifest=args.manifest,
                application=args.application,
                all_software=args.all_software,
                limit=args.limit,
            )
        )
    )


if __name__ == "__main__":
    _main()
