"""Source-linked manufacturing evidence, immutable reviews and scoped reuse.

This is a bounded, human-confirmed reconciliation workflow. It does not infer
design intent from pixels, qualify a process, or grant manufacturing authority.
"""
from __future__ import annotations

import hashlib
import json
import asyncio
import csv
import io
import os
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from dataclasses import asdict
from html import escape
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from fastapi import HTTPException
from sqlalchemy import select, update
from ulid import ULID

from src.auth.org_context import resolve_org
from src.db.models import EngineeringPackage, CostDecision
from src.services import audit_service
from src.services.cost_decision_service import spreadsheet_safe_cell
from src.storage import get_object_store

Key = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
Short = Annotated[str, Field(min_length=1, max_length=200)]
EvidenceKind = Literal["manufacturing", "inspection", "material", "service", "translation", "cam", "resource", "authorization"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Scope(Input):
    process: str = Field(default="", max_length=100)
    material: str = Field(default="", max_length=200)
    machine: str = Field(default="", max_length=200)
    setup: str = Field(default="", max_length=200)
    inspection_method: str = Field(default="", max_length=200)


class Source(Input):
    id: Key
    name: Short
    kind: Literal["model", "drawing", "specification", "evidence", "comparison"]
    revision: str = Field(default="", max_length=100)
    reference: str = Field(default="", max_length=2000)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    filename: str = Field(default="", max_length=255)
    authority: Literal["controlling", "supporting", "derivative"] = "supporting"
    coverage: Literal["unreviewed", "partial", "complete"] = "unreviewed"
    coverage_note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def has_reference(self):
        if not (self.sha256 or self.reference):
            raise ValueError("A source needs an original file or controlled reference")
        return self


class Requirement(Input):
    id: Key
    characteristic: Short
    feature: str = Field(default="", max_length=200)
    kind: Literal["dimension", "gdt", "material", "finish", "service", "interface", "process", "other"]
    value: Text
    unit: str = Field(default="", max_length=30)
    lower: float | None = None
    upper: float | None = None
    source_id: Key
    location: Text
    required_evidence: list[EvidenceKind] = Field(default_factory=lambda: ["manufacturing", "inspection"], min_length=1, max_length=8)

    @model_validator(mode="after")
    def ordered_limits(self):
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("Requirement lower limit exceeds upper limit")
        return self


class Evidence(Input):
    id: Key
    kind: EvidenceKind
    source_id: Key
    location: Text
    requirement_ids: list[Key] = Field(default_factory=list, max_length=500)
    scope: Scope = Field(default_factory=Scope)
    conclusion: Literal["supports", "fails", "inconclusive"] = "inconclusive"
    rationale: Text
    expires_on: date | None = None
    outcome_ids: list[Key] = Field(default_factory=list, max_length=100)
    supersedes_evidence_ids: list[Key] = Field(default_factory=list, max_length=100)


class Action(Input):
    id: Key
    blocker_id: str = Field(default="", max_length=200)
    title: Short
    owner: Short
    required_evidence: Text
    requirement_ids: list[Key] = Field(default_factory=list, max_length=500)
    closure_evidence_ids: list[Key] = Field(default_factory=list, max_length=100)
    rationale: str = Field(default="", max_length=2000)


class Outcome(Input):
    id: Key
    source_id: Key
    location: Text
    revision: Short
    order: Short
    scope: Scope
    requirement_ids: list[Key] = Field(default_factory=list, max_length=500)
    samples: int = Field(ge=1, le=10000000)
    failures: int = Field(ge=0)
    observed_on: date
    note: Text
    actual_setup_minutes: float | None = Field(default=None, ge=0)
    actual_cycle_minutes: float | None = Field(default=None, ge=0)
    actual_material_kg: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_counts(self):
        if self.failures > self.samples:
            raise ValueError("Outcome failures exceed sample count")
        return self


class Authorization(Input):
    authority: Short
    reference: Text
    activity: Text
    revision: Short
    order: Short
    evidence_id: Key


class PackageDocument(Input):
    part_number: Short
    revision: Short
    order: Short
    effectivity: str = Field(default="", max_length=2000)
    quantity: int = Field(ge=1, le=10000000)
    scope: Scope = Field(default_factory=Scope)
    sources: list[Source] = Field(default_factory=list, max_length=100)
    requirements: list[Requirement] = Field(default_factory=list, max_length=500)
    evidence: list[Evidence] = Field(default_factory=list, max_length=500)
    actions: list[Action] = Field(default_factory=list, max_length=200)
    outcomes: list[Outcome] = Field(default_factory=list, max_length=100)
    authorization: Authorization | None = None
    note: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def linked(self):
        indices = {}
        for name in ("sources", "requirements", "evidence", "actions", "outcomes"):
            rows = getattr(self, name)
            ids = {r.id for r in rows}
            if len(ids) != len(rows):
                raise ValueError(f"Duplicate {name} identifiers")
            indices[name] = ids
        for row in [*self.requirements, *self.evidence, *self.outcomes]:
            if row.source_id not in indices["sources"]:
                raise ValueError(f"Unknown source {row.source_id}")
        for row in [*self.evidence, *self.actions, *self.outcomes]:
            if set(row.requirement_ids) - indices["requirements"]:
                raise ValueError(f"Unknown requirement on {row.id}")
        for row in self.evidence:
            if set(row.outcome_ids) - indices["outcomes"]:
                raise ValueError(f"Unknown outcome on {row.id}")
            if row.id in row.supersedes_evidence_ids or set(row.supersedes_evidence_ids) - indices["evidence"]:
                raise ValueError(f"Invalid superseded evidence on {row.id}")
        for row in self.actions:
            if set(row.closure_evidence_ids) - indices["evidence"]:
                raise ValueError(f"Unknown closure evidence on {row.id}")
        if self.authorization and self.authorization.evidence_id not in indices["evidence"]:
            raise ValueError("Unknown authorization evidence")
        return self


def digest(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def requirement_value(row: Requirement) -> dict:
    """Engineering content; source revision/position can change without changing a bore."""
    return row.model_dump(include={"characteristic", "feature", "kind", "value", "unit", "lower", "upper", "required_evidence"})


def physical_context(context, scope):
    context = context or {}
    physical_context = {}
    physical_context["units"] = context.get("units") or "mm"
    physical_context["tolerance_class"] = context.get("tolerance_class") or "standard"
    physical_context["service_environment"] = context.get("service_environment") or None
    physical_context["shop_caps"] = (context.get("shop_caps") or {}).get("ops") or {}
    physical_context["machines"] = [{key: value for key, value in machine.items()
                                    if key not in {"hourly_rate_usd", "capital_frac", "count"}}
        for machine in context.get("inventory", []) if machine.get("name") == scope.machine]
    return json.loads(json.dumps(physical_context))


def review_fingerprints(doc: PackageDocument, mesh_hash: str, evaluation_context=None) -> dict:
    sources = {s.id: s for s in doc.sources}
    requirements = {r.id: r for r in doc.requirements}
    outcomes = {o.id: o for o in doc.outcomes}
    prints = {f"source:{s.id}": digest(s) for s in doc.sources}
    for req in doc.requirements:
        prints[f"requirement:{req.id}"] = digest({"requirement": req.model_dump(mode="json"),
                                                 "source": digest(sources[req.source_id])})
    for ev in doc.evidence:
        prints[f"evidence:{ev.id}"] = digest({
            "evidence": ev.model_dump(mode="json"), "source": digest(sources[ev.source_id]),
            "geometry": mesh_hash, "scope": doc.scope.model_dump(),
            "physical_context": physical_context(evaluation_context, doc.scope),
            # Empty dependencies cannot establish unaffected status on revisions.
            "requirements": {key: requirement_value(requirements[key]) for key in sorted(ev.requirement_ids)},
            "unscoped_configuration": None if ev.requirement_ids else [doc.revision, doc.order, doc.effectivity],
            "outcomes": {key: outcomes[key].model_dump(mode="json") for key in sorted(ev.outcome_ids)},
            "superseded_evidence": {old.id: old.model_dump(mode="json") for old in doc.evidence if old.id in ev.supersedes_evidence_ids},
        })
    for action in doc.actions:
        prints[f"action:{action.id}"] = digest({"action": action.model_dump(),
            "evidence": {key: prints[f"evidence:{key}"] for key in sorted(action.closure_evidence_ids)}})
    return prints


def review_document(doc, mesh_hash, *, previous, user_id, source_ids, requirement_ids, evidence_ids, action_ids, evaluation_context=None):
    """Only explicit review commands create receipts; edits invalidate old receipts."""
    prints = review_fingerprints(doc, mesh_hash, evaluation_context)
    receipts = {key: receipt for key, receipt in (previous or {}).items()
                if key in prints and receipt.get("fingerprint") == prints[key]}
    now = datetime.now(timezone.utc).isoformat()
    for kind, ids in [("source", source_ids), ("requirement", requirement_ids),
                      ("evidence", evidence_ids), ("action", action_ids)]:
        for key in ids:
            name = f"{kind}:{key}"
            if name not in prints:
                raise ValueError(f"Cannot review missing {name}")
            receipts[name] = {"fingerprint": prints[name], "user_id": user_id, "reviewed_at": now}
    return receipts


def evaluate_package(doc: PackageDocument, mesh_hash: str, report: dict, receipts: dict,
                     *, previous: PackageDocument | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    prints = review_fingerprints(doc, mesh_hash, report.get("review_context", report.get("evaluation_context")))
    def reviewed(kind, key):
        name = f"{kind}:{key}"
        return receipts.get(name, {}).get("fingerprint") == prints.get(name) and name in prints

    blockers = []
    actions = {a.blocker_id: a for a in doc.actions if a.blocker_id}
    def block(key, kind, text, requirement_ids=(), need=None):
        action = actions.get(key)
        blockers.append({"id": key, "kind": kind, "consequence": text,
            "requirement_ids": list(requirement_ids), "owner": action.owner if action else "Unassigned",
            "required_evidence": action.required_evidence if action else need or text,
            "action_id": action.id if action else None})

    controlling = [s for s in doc.sources if s.authority == "controlling" and s.kind in {"model", "drawing", "specification"}]
    if not controlling:
        block("authority", "authority", "Declare the source authority for this order.")
    for source in doc.sources:
        if source.kind != "evidence" and (source.coverage != "complete" or not reviewed("source", source.id)):
            block(f"source:{source.id}", "coverage", f"Confirm {source.name} coverage and its mapping to this configuration.")
    if not doc.requirements:
        block("requirements", "coverage", "No source-linked requirements are recorded; engineering coverage is unknown.")

    grouped = defaultdict(list)
    for req in doc.requirements:
        grouped[(req.feature.casefold(), req.characteristic.casefold())].append(req)
        if not reviewed("requirement", req.id):
            block(f"review:{req.id}", "requirement_review", f"Confirm {req.characteristic} at {req.location}.", [req.id])
    for group in grouped.values():
        values = {digest({k: v for k, v in requirement_value(r).items()
                          if k not in {"characteristic", "feature", "required_evidence"}}) for r in group}
        if len(values) > 1:
            block(f"conflict:{group[0].id}", "conflict", f"Sources disagree on {group[0].characteristic}; obtain a source-authority disposition.", [r.id for r in group])

    outcomes = {o.id: o for o in doc.outcomes}
    evidence_status = []
    supported = set()
    for ev in doc.evidence:
        reason = "reviewed"
        if ev.expires_on and ev.expires_on < today:
            reason = "expired"
        elif not reviewed("evidence", ev.id):
            reason = "review_required"
        elif ev.scope != doc.scope:
            reason = "scope_mismatch"
        elif ev.conclusion != "supports":
            reason = ev.conclusion
        elif not ev.requirement_ids and ev.kind != "authorization":
            reason = "dependencies_unknown"
        elif any(outcomes[key].scope != doc.scope or outcomes[key].failures > 0 for key in ev.outcome_ids):
            reason = "outcome_requires_disposition"
        elif ev.kind in {"manufacturing", "inspection", "cam"} and not all(
                getattr(doc.scope, key) for key in ("process", "material", "machine", "setup")):
            reason = "scope_incomplete"
        elif ev.kind == "inspection" and not doc.scope.inspection_method:
            reason = "inspection_method_missing"
        if reason == "reviewed":
            supported.add(ev.id)
        evidence_status.append({"id": ev.id, "status": "supported" if reason == "reviewed" else "review_required",
                                "reason": reason, "requirement_ids": ev.requirement_ids})
    superseded = {old_id for ev in doc.evidence if ev.id in supported
                  for old_id in ev.supersedes_evidence_ids
                  if any(old.id == old_id and old.scope == ev.scope and old.kind == ev.kind
                         and set(old.requirement_ids) <= set(ev.requirement_ids) for old in doc.evidence)}
    for ev_status in evidence_status:
        if ev_status["id"] in superseded:
            supported.discard(ev_status["id"])
            ev_status["status"] = "superseded"
            ev_status["reason"] = "superseded_by_reviewed_disposition"
    for outcome in doc.outcomes:
        if not outcome.requirement_ids:
            block(f"outcome:{outcome.id}", "outcome", "Map the observed outcome to requirements before deciding applicability.")
        elif outcome.failures and outcome.scope == doc.scope and not any(
                ev.id in superseded and outcome.id in ev.outcome_ids for ev in doc.evidence):
            block(f"outcome:{outcome.id}", "outcome", "Observed failures require a reviewed disposition; retain the original observation and link superseding evidence.", outcome.requirement_ids)
    for req in doc.requirements:
        for kind in req.required_evidence:
            relevant = [e for e in doc.evidence if e.kind == kind and req.id in e.requirement_ids]
            # A contrary observation remains decisive even beside a supporting study.
            failed = any(e.conclusion == "fails" and e.scope == doc.scope and e.id not in superseded for e in relevant)
            if failed or not any(e.id in supported for e in relevant):
                block(f"{kind}:{req.id}", kind,
                      f"{req.characteristic}: {'contrary evidence needs disposition' if failed else 'applicable ' + kind + ' evidence is needed'}.",
                      [req.id], f"Provide and review {kind} evidence for this requirement, process, machine, setup and conditions.")

    verification = report.get("verification") or {}
    per_route = verification.get("per_route") or {}
    selected = per_route.get(doc.scope.process) or {}
    estimates = [e for e in report.get("estimates", []) if e.get("process") == doc.scope.process]
    route_estimates = [e for e in estimates if e.get("material") == doc.scope.material]
    screening = "unknown"
    if any(e.get("dfm_ready") is False or e.get("environment_excluded") for e in route_estimates) or selected.get("verdict") in {"not_makeable", "environment_excluded"}:
        screening = "blocked"
    elif route_estimates and all(e.get("dfm_ready") is True and not e.get("environment_unknown") for e in route_estimates) and selected.get("verdict") in {"makeable_in_house", "makeable_with_secondary_op"} and selected.get("best_machine") == doc.scope.machine:
        screening = "passed"
    if report.get("evaluation_stale"):
        screening = "unknown"
    if screening != "passed":
        block("screening", "screening", "Selected manufacturing scope needs a current geometry/process/machine evaluation; conditional resources do not establish readiness.")

    alternatives = []
    for estimate in report.get("estimates", []):
        if estimate.get("quantity") != doc.quantity:
            continue
        fit = per_route.get(estimate.get("process")) or {}
        needs = list(estimate.get("dfm_blockers") or [])
        needs.extend(f.get("human", "Missing machine capability") for f in fit.get("failures", []))
        if estimate.get("environment_excluded") or estimate.get("environment_unknown"):
            needs.append(estimate.get("environment_exclusion_reason") or estimate.get("environment_evidence_needed") or "Resolve service-condition evidence")
        if not fit:
            needs.append("Machine capability has not been evaluated")
        elif fit.get("verdict") == "makeable_outsource_only":
            needs.append("Select and qualify an outside supplier or add applicable owned equipment")
        if report.get("evaluation_stale"):
            needs.append(report.get("stale_reason") or "Re-run verification with current manufacturing inputs")
        needs.append("Review requirement-specific manufacturing and inspection evidence for this route")
        alternatives.append({"process": estimate.get("process"), "material": estimate.get("material"),
            "quantity": doc.quantity, "machine": fit.get("best_machine"), "screening_verdict": fit.get("verdict", "unknown"),
            "conditions": needs, "resources": estimate.get("drivers", []),
            "unit_cost_usd": estimate.get("unit_cost_usd"), "confidence": estimate.get("confidence"),
            "basis": "Conditional estimate at the evaluated quantity; changes need engineering review."})

    action_status = []
    for action in doc.actions:
        closed = bool(action.closure_evidence_ids and action.rationale and reviewed("action", action.id)
                      and set(action.closure_evidence_ids) <= supported
                      and not any(b["id"] == action.blocker_id for b in blockers))
        action_status.append({"id": action.id, "status": "closed" if closed else "open"})
        if not closed:
            block(f"action:{action.id}", "action_closure", f"Complete and review closure of: {action.title}.", action.requirement_ids)
            blockers[-1].update(owner=action.owner, required_evidence=action.required_evidence, action_id=action.id)
    auth = doc.authorization
    authorization = "not_recorded"
    if auth and auth.revision == doc.revision and auth.order == doc.order and auth.evidence_id in supported:
        ev = next(e for e in doc.evidence if e.id == auth.evidence_id)
        if ev.kind == "authorization":
            authorization = "external_record_attached"

    changes = {"changed_requirements": [], "added_requirements": [], "removed_requirements": [],
               "unchanged_requirements": [], "scope_changed": False, "configuration_changed": False}
    if previous:
        old = {r.id: r for r in previous.requirements}
        new = {r.id: r for r in doc.requirements}
        changes.update({
            "added_requirements": sorted(new.keys() - old.keys()),
            "removed_requirements": sorted(old.keys() - new.keys()),
            "changed_requirements": sorted(k for k in old.keys() & new.keys() if requirement_value(old[k]) != requirement_value(new[k])),
            "unchanged_requirements": sorted(k for k in old.keys() & new.keys() if requirement_value(old[k]) == requirement_value(new[k])),
            "scope_changed": previous.scope != doc.scope,
            "configuration_changed": (previous.revision, previous.order, previous.effectivity) != (doc.revision, doc.order, doc.effectivity),
        })
    return {"screening": screening, "qualification": "evidence_needed" if blockers else "reviewed_evidence",
            "authorization": authorization, "blockers": blockers, "evidence_status": evidence_status,
            "action_status": action_status, "alternatives": alternatives, "changes": changes,
            "boundary": "Screening, reviewed qualification evidence and external authorization are separate. CadVerify does not grant product acceptance or release authority."}


class WritePackage(Input):
    decision_id: Key
    document: PackageDocument
    previous_id: Key | None = None
    state: Literal["draft", "issued"] = "draft"
    review_note: str = Field(default="", max_length=2000)
    confirm_sources: list[Key] = Field(default_factory=list, max_length=100)
    confirm_requirements: list[Key] = Field(default_factory=list, max_length=500)
    review_evidence: list[Key] = Field(default_factory=list, max_length=500)
    close_actions: list[Key] = Field(default_factory=list, max_length=200)


def document_store():
    return get_object_store("engineering-documents", default_root=os.getenv("ENGINEERING_DOCUMENT_BLOB_DIR", "/data/blobs/engineering-documents"))


def document_key(org_id, sha256):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", org_id) or not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise ValueError("Invalid document address")
    return f"{org_id}/{sha256}"


async def store_document(org_id, filename, data):
    if not data or len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "Documents must contain 1 byte to 20 MiB")
    suffix = filename.rsplit(".", 1)[-1].lower()
    if suffix not in {"pdf", "png", "jpg", "jpeg", "csv", "json", "txt", "step", "stp", "iges", "igs", "stl"}:
        raise HTTPException(422, "Use PDF, image, CSV, JSON, text, STEP, IGES or STL")
    sha = hashlib.sha256(data).hexdigest()
    await asyncio.to_thread(document_store().put, document_key(org_id, sha), data,
                            content_type="application/octet-stream")
    return {"sha256": sha, "filename": filename[:255], "bytes": len(data),
            "coverage": "unreviewed", "note": "Original retained. Confirm source authority and map characteristics, or import a reviewed tool export."}


async def require_org(session, user):
    org_id = await resolve_org(session, user.user_id)
    if not org_id or (user.org_id is not None and org_id != user.org_id):
        raise HTTPException(403, "An active organization is required")
    return org_id


async def get_package(session, org_id, package_id):
    row = (await session.execute(select(EngineeringPackage).where(
        EngineeringPackage.org_id == org_id, EngineeringPackage.id == package_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Engineering package not found")
    return row


def serialize_package(row, *, detail=True):
    payload = row.payload
    doc = payload["document"]
    result = {"id": row.id, "series_id": row.series_id, "version": row.version,
        "mesh_hash": row.mesh_hash, "state": row.state, "is_latest": row.is_latest,
        "created_at": row.created_at.isoformat(), "created_by": row.created_by,
        "part_number": doc["part_number"], "revision": doc["revision"], "order": doc["order"],
        "screening": payload["evaluation"]["screening"], "qualification": payload["evaluation"]["qualification"],
        "blocker_count": len(payload["evaluation"]["blockers"])}
    if detail:
        result.update(payload)
    return result


async def save_package(session, user, body: WritePackage):
    org_id = await require_org(session, user)
    if len(body.model_dump_json().encode()) > 2 * 1024 * 1024:
        raise HTTPException(413, "Engineering package exceeds 2 MiB; split it into part packages")
    decision = (await session.execute(select(CostDecision).where(
        CostDecision.org_id == org_id, CostDecision.ulid == body.decision_id))).scalar_one_or_none()
    if decision is None:
        raise HTTPException(404, "Saved evaluation not found")
    previous = await get_package(session, org_id, body.previous_id) if body.previous_id else None
    if previous and not previous.is_latest:
        raise HTTPException(409, "A newer version exists. Reload before saving; your changes were not overwritten.")
    if body.state == "issued" and not body.review_note:
        raise HTTPException(422, "An issued packet requires a reviewer note")
    # File references are resolved only in this tenant's namespace, never fetched
    # from user-supplied URLs. Existence checks are bounded by the schema's 100 sources.
    for source in body.document.sources:
        if source.sha256 and not await asyncio.to_thread(document_store().exists, document_key(org_id, source.sha256)):
            raise HTTPException(422, f"Original document is unavailable: {source.id}")
    old_doc = PackageDocument.model_validate(previous.payload["document"]) if previous else None
    assessment_report = await current_report(session, org_id, decision.mesh_hash, decision.result_json or {}, body.document.scope,
                                             stale_reason=decision.stale_reason if decision.stale_at else None)
    receipts = review_document(body.document, decision.mesh_hash,
        previous=previous.payload.get("reviews") if previous else None, user_id=user.user_id,
        source_ids=body.confirm_sources, requirement_ids=body.confirm_requirements,
        evidence_ids=body.review_evidence, action_ids=body.close_actions,
        evaluation_context=assessment_report.get("review_context"))
    evaluation = evaluate_package(body.document, decision.mesh_hash, assessment_report, receipts, previous=old_doc)
    identifier = str(ULID())
    row = EngineeringPackage(id=identifier, org_id=org_id, series_id=previous.series_id if previous else identifier,
        mesh_hash=decision.mesh_hash, version=previous.version + 1 if previous else 1,
        is_latest=True, state=body.state, created_by=user.user_id,
        payload={"document": body.document.model_dump(mode="json"), "reviews": receipts,
                 "evaluation": evaluation, "decision_id": decision.ulid,
                 "engine_version": decision.engine_version, "evaluation_snapshot": assessment_report,
                 "previous_id": previous.id if previous else None, "review_note": body.review_note,
                 "evaluated_on": date.today().isoformat()})
    if previous:
        claimed = await session.execute(update(EngineeringPackage).where(
            EngineeringPackage.org_id == org_id, EngineeringPackage.id == previous.id,
            EngineeringPackage.is_latest.is_(True)).values(is_latest=False).returning(EngineeringPackage.id))
        if claimed.scalar_one_or_none() is None:
            raise HTTPException(409, "A newer version exists. Reload before saving.")
    session.add(row)
    await session.flush()
    await audit_service.emit_event(session, user.user_id, "engineering_package." + body.state,
        "engineering_package", resource_id=row.id, org_id=org_id,
        detail={"series_id": row.series_id, "version": row.version, "decision_id": decision.ulid,
                "screening": evaluation["screening"], "blockers": len(evaluation["blockers"])})
    return row


async def current_report(session, org_id, mesh_hash, report, scope, *, stale_reason=None):
    from src.services.machine_inventory_service import load_org_inventory, load_shop_caps
    from src.services.part_context_service import get_context
    inventory = await load_org_inventory(session, org_id)
    caps = await load_shop_caps(session, org_id)
    context = await get_context(session, org_id, mesh_hash)
    original = report.get("evaluation_context")
    current = {**(original or {}), "inventory": [asdict(m) for m in inventory],
               "shop_caps": asdict(caps) if caps else None,
               "service_environment": context.service_environment if context else None}
    current = json.loads(json.dumps(current))
    stale = original is None or physical_context(original, scope) != physical_context(current, scope)
    return {**report, "review_context": current, "evaluation_stale": stale or bool(stale_reason),
            "stale_reason": stale_reason or ("Manufacturing inputs changed or the saved input snapshot is missing; re-run verification." if stale else None)}


async def current_assessment(session, row):
    doc = PackageDocument.model_validate(row.payload["document"])
    decision = (await session.execute(select(CostDecision).where(CostDecision.org_id == row.org_id,
        CostDecision.ulid == row.payload["decision_id"]))).scalar_one_or_none()
    report = await current_report(session, row.org_id, row.mesh_hash, row.payload["evaluation_snapshot"], doc.scope,
        stale_reason=(decision.stale_reason if decision and decision.stale_at else None))
    assessment = evaluate_package(doc, row.mesh_hash, report, row.payload["reviews"])
    assessment["changes"] = row.payload["evaluation"]["changes"]
    assessment["stale_reason"] = report.get("stale_reason")
    assessment["assessed_on"] = date.today().isoformat()
    return assessment


async def list_packages(session, org_id, *, mesh_hash=None, series_id=None, cursor=None, limit=25, blocker_kind=None, owner=None):
    query = select(EngineeringPackage).where(EngineeringPackage.org_id == org_id)
    if series_id:
        query = query.where(EngineeringPackage.series_id == series_id)
    else:
        query = query.where(EngineeringPackage.is_latest.is_(True))
    if mesh_hash:
        query = query.where(EngineeringPackage.mesh_hash == mesh_hash)
    if cursor:
        query = query.where(EngineeringPackage.id < cursor)
    if blocker_kind or owner:
        match = {key: value for key, value in {"kind": blocker_kind, "owner": owner}.items() if value}
        query = query.where(EngineeringPackage.payload["evaluation"]["blockers"].contains([match]))
    rows = list((await session.execute(query.order_by(EngineeringPackage.id.desc()).limit(limit + 1))).scalars())
    return {"packages": [serialize_package(row, detail=False) for row in rows[:limit]],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


def import_characteristics(data: bytes, filename: str) -> list[dict]:
    """Explicit exchange contract, not a claim to understand arbitrary vendor files."""
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Characteristic import exceeds 2 MiB")
    text = data.decode("utf-8-sig")
    if filename.lower().endswith(".json"):
        rows = json.loads(text)
        if isinstance(rows, dict):
            rows = rows.get("requirements")
        if not isinstance(rows, list):
            raise ValueError("JSON must contain a requirements array")
    elif filename.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV needs unique column names")
        rows = []
        for row in reader:
            if len(rows) >= 500:
                raise ValueError("Import at most 500 characteristics per part package")
            if None in row or any(value is None for value in row.values()):
                raise ValueError("CSV row length does not match its header")
            row = {key: value for key, value in row.items() if value != ""}
            if "required_evidence" in row:
                row["required_evidence"] = row["required_evidence"].split(";")
            rows.append(row)
    else:
        raise ValueError("Import characteristics as CSV or JSON")
    if not rows or len(rows) > 500:
        raise ValueError("Import 1–500 characteristics")
    parsed = [Requirement.model_validate(row).model_dump(mode="json") for row in rows]
    if len({r["id"] for r in parsed}) != len(parsed):
        raise ValueError("Characteristic identifiers must be unique")
    return parsed


def export_characteristics(payload):
    output = io.StringIO(newline="")
    columns = list(Requirement.model_fields)
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in payload["document"]["requirements"]:
        writer.writerow(spreadsheet_safe_cell(";".join(row[key]) if isinstance(row[key], list) else row[key]) for key in columns)
    return output.getvalue()


def packet_html(row):
    """Self-contained printable packet; escaped data, no remotely fetched assets."""
    p = row.payload
    d, result = p["document"], p["evaluation"]
    def text(value):
        return escape(str(value if value is not None else "—"))
    def scope_text(scope):
        return " · ".join(f"{key.replace('_', ' ')}: {value}" for key, value in scope.items() if value)
    def table(headers, rows):
        return "<table><thead><tr>" + "".join(f"<th>{text(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(
            "<tr>" + "".join(f"<td>{text(cell)}</td>" for cell in cells) + "</tr>" for cells in rows) + "</tbody></table>"
    alternatives = []
    for a in result['alternatives']:
        alternatives.extend([
            f"<h3>{text(a['process'].replace('_', ' '))} · {text(a['material'])} · {text(a['machine'])}</h3>",
            f"<p>Quantity {a['quantity']} · conditional unit estimate USD {text(a['unit_cost_usd'])}. {text(a['basis'])}</p>",
            "<ul>" + "".join(f"<li>{text(condition)}</li>" for condition in a['conditions']) + "</ul>",
            table(["Resource / value", "Provenance / assumption"],
                  [[r.get('name', '').replace('_', ' ') + ': ' + str(r.get('value', '')) + ' ' + str(r.get('unit', '')),
                    str(r.get('provenance', '')) + ' · ' + str(r.get('source', ''))] for r in a['resources']]),
        ])
    parts = ["<!doctype html><html lang='en'><meta charset='utf-8'><title>Engineering decision packet</title><style>body{font:14px system-ui;margin:0;color:#17252c}h1,h2,h3{break-after:avoid}table{table-layout:fixed;border-collapse:collapse;width:100%;margin:16px 0;font-size:12px}th,td{border:1px solid #cbd5df;padding:8px;text-align:left;overflow-wrap:anywhere}tr{break-inside:avoid}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}small{color:#52616a}@page{size:A4;margin:18mm}</style><body>",
        f"<h1>{text(d['part_number'])} · revision {text(d['revision'])}</h1>",
        f"<p>Order {text(d['order'])} · quantity {d['quantity']} · version {row.version} · {text(row.state)}</p>",
        f"<p>Effectivity: {text(d['effectivity'])}</p><p>Packet {text(row.id)} · source geometry {text(row.mesh_hash)}</p>",
        f"<p>Manufacturing scope: {text(scope_text(d['scope']))}</p>",
        f"<p>Saved evaluation: {text(p.get('decision_id'))} · engine {text(p.get('engine_version'))}</p>",
        f"<p>Screening: <b>{text(result['screening'].replace('_', ' '))}</b> · qualification: <b>{text(result['qualification'].replace('_', ' '))}</b> · authorization: <b>{text(result['authorization'].replace('_', ' '))}</b></p>",
        f"<p>{text(result['boundary'])}</p><p>Evaluation date: {text(p['evaluated_on'])}. This immutable snapshot does not establish current evidence validity after its date.</p>",
        "<h2>Sources and authority</h2>", table(["ID / Source", "Revision", "Authority", "Coverage", "Reference / SHA-256"],
            [[s['id'] + ': ' + s['name'], s['revision'], s['authority'], s['coverage'], s['reference'] + ' / ' + str(s['sha256'] or '')] for s in d['sources']]),
        "<h2>Source-linked characteristics</h2>", table(["ID / feature", "Requirement", "Limits", "Source location"],
            [[r['id'] + ' / ' + r['feature'], r['characteristic'] + ': ' + r['value'] + ' ' + r['unit'], f"{r['lower']} … {r['upper']}", r['source_id'] + ' / ' + r['location']] for r in d['requirements']]),
        "<h2>Required actions</h2>", table(["Consequence", "Owner", "Closure evidence"],
            [[b['consequence'], b['owner'], b['required_evidence']] for b in result['blockers']]),
        "<h2>Evidence and applicability</h2>", table(["Evidence / requirements", "Conclusion", "Source", "Scope", "Rationale / expiry"],
            [[e['id'] + ' / ' + ', '.join(e['requirement_ids']), e['conclusion'], e['source_id'] + ' / ' + e['location'], scope_text(e['scope']), e['rationale'] + ' / ' + str(e['expires_on']) + ' · supersedes: ' + ', '.join(e.get('supersedes_evidence_ids', []))] for e in d['evidence']]),
        "<h2>Evidence review status</h2>", table(["Evidence", "State", "Reason"], [[e['id'], e['status'], e['reason']] for e in result['evidence_status']]),
        "<h2>Revision consequences</h2><pre>" + text(json.dumps(result['changes'], indent=2)) + "</pre>",
        "<h2>Conditional route alternatives</h2>", "".join(alternatives),
        "<h2>Observed outcomes</h2>", table(["ID / date", "Order / revision", "Samples / failures", "Scope / actuals", "Evidence / note"],
            [[o['id'] + ' / ' + o['observed_on'], o['order'] + ' / ' + o['revision'], f"{o['samples']} / {o['failures']}", scope_text(o['scope']) + f" · setup {o['actual_setup_minutes']} min, cycle {o['actual_cycle_minutes']} min/part, material {o['actual_material_kg']} kg", o['source_id'] + ' / ' + o['location'] + ': ' + o['note']] for o in d['outcomes']]),
        "<h2>External authorization record</h2><pre>" + text(json.dumps(d['authorization'], indent=2)) + "</pre>",
        "<h2>Review receipts</h2><pre>" + text(json.dumps(p['reviews'], indent=2)) + "</pre>",
        f"<p>Reviewer note: {text(p['review_note'])}</p><p>{text(d['note'])}</p></body></html>"]
    return "".join(parts)
