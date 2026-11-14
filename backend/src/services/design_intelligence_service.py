"""Advisory design-intent context for deterministic DFM findings.

This service is deliberately downstream of the makeability engine.  It retrieves
third-party workflow precedents that may help a human understand design intent;
it never changes an Issue, a verdict, a threshold, or a provenance-bearing
engineering number.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Any, NamedTuple

from src.corpus.cad1000 import (
    DATASET_URL,
    SERVING_INDEX_MAX_METADATA_CHARS,
    SERVING_INDEX_MAX_RECORDS,
    SERVING_INDEX_MAX_TEXT_CHARS,
    SERVING_INDEX_ROLES,
    WorkflowKnowledgeBase,
    production_retrieval_eligible,
    select_serving_records,
)
from src.corpus.paths import CAD1000_KNOWLEDGE

logger = logging.getLogger("cadverify.design_intelligence")

_MAX_EXCERPT = 360
_MAX_PRECEDENTS = 5
_MAX_CORPUS_BYTES = 256 * 1024 * 1024
_MAX_LINE_BYTES = 1024 * 1024
_MAX_INDEX_RECORDS = SERVING_INDEX_MAX_RECORDS
_MAX_TEXT_CHARS = SERVING_INDEX_MAX_TEXT_CHARS
_MAX_METADATA_CHARS = SERVING_INDEX_MAX_METADATA_CHARS
_INDEX_ROLES = SERVING_INDEX_ROLES
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")


class _ServingIndex(NamedTuple):
    knowledge: WorkflowKnowledgeBase
    corpus_revision: str
    eligible_records_scanned: int
    indexed_records: int
    index_truncated: bool


_cache_key: tuple[str, int, int, bool] | None = None
_cache: _ServingIndex | None = None
_cache_lock = threading.Lock()


def design_intelligence_enabled() -> bool:
    return os.getenv("DESIGN_INTELLIGENCE_ENABLED", "0").strip().lower() in {
        "1",
        "true",
    }


def research_mode_enabled() -> bool:
    """Whether explicitly quarantined, unlicensed records may be read locally."""
    requested = os.getenv("CAD1000_RESEARCH_MODE", "0").strip().lower() in {
        "1",
        "true",
    }
    release = os.getenv("RELEASE", "").strip().lower()
    return requested and release in {"dev", "development", "local", "test", "ci"}


def _knowledge_path() -> Path:
    configured = os.getenv("CAD1000_KNOWLEDGE_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else CAD1000_KNOWLEDGE


def reset_cache() -> None:
    """Clear the process-local retrieval cache (used after corpus refresh/tests)."""
    global _cache, _cache_key
    with _cache_lock:
        _cache = None
        _cache_key = None


def _build_knowledge(
    path: Path, include_quarantined: bool
) -> _ServingIndex:
    size = path.stat().st_size
    if size > _MAX_CORPUS_BYTES:
        raise ValueError(
            f"corpus exceeds {_MAX_CORPUS_BYTES}-byte serving limit"
        )

    corpus_revision: str | None = None

    def validated_records():
        nonlocal corpus_revision
        with path.open("rb") as handle:
            for line_number, raw_line in enumerate(handle, 1):
                if len(raw_line) > _MAX_LINE_BYTES:
                    raise ValueError(
                        f"corpus line {line_number} exceeds {_MAX_LINE_BYTES}-byte limit"
                    )
                if not raw_line.strip():
                    continue
                record = json.loads(raw_line)
                if not isinstance(record, dict):
                    raise ValueError(f"corpus line {line_number} was not an object")
                revision = record.get("dataset_revision")
                if not isinstance(revision, str) or not _COMMIT_RE.fullmatch(revision):
                    raise ValueError(
                        f"corpus line {line_number} has no immutable dataset revision"
                    )
                if corpus_revision is None:
                    corpus_revision = revision
                elif revision != corpus_revision:
                    raise ValueError(
                        f"corpus line {line_number} changed dataset revision"
                    )
                yield record

    selection = select_serving_records(
        validated_records(),
        include_quarantined=include_quarantined,
        max_records=_MAX_INDEX_RECORDS,
        max_text_chars=_MAX_TEXT_CHARS,
        max_metadata_chars=_MAX_METADATA_CHARS,
        roles=_INDEX_ROLES,
    )

    if corpus_revision is None:
        raise ValueError("corpus has no records")
    knowledge = WorkflowKnowledgeBase(
        selection.records, include_quarantined=include_quarantined
    )
    indexed_records = len(knowledge.records)
    return _ServingIndex(
        knowledge=knowledge,
        corpus_revision=corpus_revision,
        eligible_records_scanned=selection.eligible_records_scanned,
        indexed_records=indexed_records,
        index_truncated=selection.index_truncated,
    )


def _load_knowledge() -> _ServingIndex | None:
    global _cache, _cache_key
    with _cache_lock:
        path = _knowledge_path()
        try:
            if not path.is_file():
                return None
            stat = path.stat()
        except OSError:
            return None
        include_quarantined = research_mode_enabled()
        key = (str(path), stat.st_mtime_ns, stat.st_size, include_quarantined)
        if _cache_key == key:
            return _cache
        try:
            loaded = _build_knowledge(path, include_quarantined)
        except (OSError, ValueError) as exc:
            logger.warning("design intelligence corpus unreadable: %s", exc)
            _cache, _cache_key = None, key
            return None
        _cache, _cache_key = loaded, key
        return loaded


def _query_for(finding: dict[str, Any]) -> str:
    values = [
        str(finding.get("code", "")).replace("_", " ").replace("-", " "),
        str(finding.get("message", "")),
        str(finding.get("fix_suggestion", "")),
        str(finding.get("process", "")).replace("_", " ").replace("-", " "),
    ]
    # Bound work and prevent an accidental giant issue payload becoming an
    # equally giant in-memory token bag. Pydantic also bounds each input field.
    return " ".join(value for value in values if value).strip()[:6000]


def _source_times(record: dict[str, Any]) -> tuple[Any, Any]:
    start, end = record.get("start_s"), record.get("end_s")
    nested = record.get("timestamp_range")
    if isinstance(nested, dict):
        start = nested.get("start", start)
        end = nested.get("end", end)
    return start, end


def _source_url(record: dict[str, Any]) -> str:
    revision = record.get("dataset_revision")
    if not isinstance(revision, str) or not _COMMIT_RE.fullmatch(revision):
        raise ValueError("knowledge record has no immutable dataset revision")
    source_path = str(record.get("source_path") or record.get("workflow") or "").strip("/")
    quoted_path = urllib.parse.quote(source_path, safe="/")
    start_value, _ = _source_times(record)
    try:
        start = float(start_value)
    except (TypeError, ValueError):
        start = math.nan
    if record.get("record_type") in {"workflow_segment", "workflow_narration"} and math.isfinite(start):
        return f"{DATASET_URL}/resolve/{revision}/{quoted_path}/clip.mp4#t={start:.3f}"
    return f"{DATASET_URL}/tree/{revision}/{quoted_path}"


def _precedent(hit) -> dict[str, Any]:
    record = hit.record
    text = " ".join(str(record.get("text", "")).split())
    start, end = _source_times(record)
    return {
        "workflow_id": record.get("workflow_id"),
        "application": record.get("application") or record.get("software"),
        "task": record.get("task"),
        "knowledge_role": record.get("knowledge_role"),
        "excerpt": text[:_MAX_EXCERPT],
        "start_s": start,
        "end_s": end,
        "source_url": _source_url(record),
        "score": round(float(hit.score), 4),
        "provenance": "THIRD_PARTY_UNVERIFIED",
        "license_status": record.get("license_status", "UNDECLARED"),
        "production_eligible": production_retrieval_eligible(record),
    }


def _index_disclosure(index: _ServingIndex | None) -> dict[str, Any]:
    return {
        "corpus_revision": index.corpus_revision if index else None,
        "eligible_records_scanned": index.eligible_records_scanned if index else 0,
        "indexed_records": index.indexed_records if index else 0,
        "index_truncated": index.index_truncated if index else False,
    }


def _unavailable(
    reason: str, finding: dict[str, Any], index: _ServingIndex | None = None
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "finding_code": finding.get("code"),
        "authority": "ADVISORY_ONLY",
        "engineering_authority": "NONE",
        "provenance": "THIRD_PARTY_UNVERIFIED",
        "may_affect_deterministic_verdict": False,
        "is_manufacturing_ground_truth": False,
        "possible_intents": [],
        "relevant_requirements": [],
        "workflow_evidence": [],
        **_index_disclosure(index),
    }


def explain_finding(finding: dict[str, Any], *, limit: int = 3) -> dict[str, Any]:
    """Return cited design context for one serialized engine finding."""
    index = _load_knowledge()
    if index is None:
        return _unavailable("knowledge_corpus_missing", finding)
    knowledge = index.knowledge
    if not knowledge.records:
        return _unavailable("no_eligible_knowledge_records", finding, index)

    query = _query_for(finding)
    if not query:
        return _unavailable("finding_has_no_searchable_text", finding, index)

    capped = max(1, min(limit, _MAX_PRECEDENTS))
    role_hits = {
        "design_intent": knowledge.search(
            query, limit=capped, knowledge_role="design_intent"
        ),
        "design_requirement": knowledge.search(
            query, limit=capped, knowledge_role="design_requirement"
        ),
        "authoring_trace": knowledge.search(
            query, limit=capped, knowledge_role="authoring_trace"
        ),
    }

    intent_rows: list[dict[str, Any]] = []
    seen_intents: set[tuple[Any, Any]] = set()
    for hit in role_hits["design_intent"]:
        record = hit.record
        key = (record.get("workflow_id"), record.get("task"))
        if key in seen_intents or not record.get("task"):
            continue
        seen_intents.add(key)
        intent_rows.append(
            {
                "candidate": record["task"],
                "basis": "similar third-party workflow task",
                "confidence": "hypothesis",
                "workflow_id": record.get("workflow_id"),
                "source_url": _source_url(record),
                "provenance": "THIRD_PARTY_UNVERIFIED",
                "license_status": record.get("license_status", "UNDECLARED"),
                "production_eligible": production_retrieval_eligible(record),
            }
        )
        if len(intent_rows) >= capped:
            break

    requirements = [_precedent(hit) for hit in role_hits["design_requirement"][:capped]]
    evidence = [_precedent(hit) for hit in role_hits["authoring_trace"][:capped]]
    has_evidence = bool(intent_rows or requirements or evidence)
    status = (
        "research_only"
        if has_evidence and research_mode_enabled()
        else "available" if has_evidence else "no_match"
    )
    return {
        "status": status,
        "reason": (
            None
            if has_evidence
            else "no_relevant_precedent_in_bounded_index"
            if index.index_truncated
            else "no_relevant_precedent"
        ),
        "finding_code": finding.get("code"),
        "authority": "ADVISORY_ONLY",
        "engineering_authority": "NONE",
        "provenance": "THIRD_PARTY_UNVERIFIED",
        "may_affect_deterministic_verdict": False,
        "is_manufacturing_ground_truth": False,
        "research_mode": research_mode_enabled(),
        "possible_intents": intent_rows,
        "relevant_requirements": requirements,
        "workflow_evidence": evidence,
        **_index_disclosure(index),
    }


async def explain_finding_async(
    finding: dict[str, Any], *, limit: int = 3
) -> dict[str, Any]:
    """Run corpus loading and BM25 retrieval without blocking the API loop."""
    return await asyncio.to_thread(explain_finding, finding, limit=limit)
